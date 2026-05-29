import os
from flask import Blueprint, request, current_app
from app import get_db, close_db
from db_helpers import ok, err

'''
GET  /api/listings              -- browse active listings (filters: department, distributive, professor, minPrice, maxPrice, search)
POST /api/listings              -- create listing (seller)
GET  /api/listings/<id>         -- listing detail + bids (buyerId hidden) + price history
POST /api/listings/<id>/cancel  -- cancel own listing, refund all pending bids
POST /api/listings/expire-all   -- expire stale listings + refund bids (call from scheduler)
'''

listings_bp = Blueprint('listings', __name__)


@listings_bp.route('/', methods=['GET'])
@login_required
def get_listings():
    """
    Browse active, non-expired listings. Sorted by bid activity descending.
    sellerId is intentionally excluded (anonymity rule).
    Supports query params: department, distributive, professor, minPrice, maxPrice, search
    """
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)

        filters = []
        params  = []

        department   = request.args.get('department')
        distributive = request.args.get('distributive')
        professor    = request.args.get('professor')
        min_price    = request.args.get('minPrice')
        max_price    = request.args.get('maxPrice')
        search       = request.args.get('search')

        base = """
            SELECT
                l.listingId, l.minPrice, l.status, l.createdAt, l.expiresAt,
                s.sectionId, s.meetingTime, s.location,
                c.courseCode, c.title,
                d.name AS department, d.code AS departmentCode,
                dist.name AS distributive, dist.code AS distributiveCode,
                p.name AS professorName,
                COUNT(b.bidId) AS bidCount,
                MAX(b.amount)  AS highestBid
            FROM listing l
            JOIN section s    ON l.sectionId    = s.sectionId
            JOIN class c      ON s.classId      = c.classId
            JOIN department d ON c.departmentId = d.departmentId
            LEFT JOIN distributive dist ON c.distributiveId = dist.distributiveId
            JOIN professor p  ON s.professorId  = p.professorId
            LEFT JOIN bid b   ON l.listingId    = b.listingId AND b.status = 'pending'
            WHERE l.status = 'active' AND l.expiresAt > NOW()
        """

        if department:
            filters.append("d.code = %s");    params.append(department)
        if distributive:
            filters.append("dist.code = %s"); params.append(distributive)
        if professor:
            filters.append("p.name LIKE %s"); params.append(f"%{professor}%")
        if min_price:
            filters.append("l.minPrice >= %s"); params.append(float(min_price))
        if max_price:
            filters.append("l.minPrice <= %s"); params.append(float(max_price))
        if search:
            filters.append("(c.title LIKE %s OR c.courseCode LIKE %s)")
            params += [f"%{search}%", f"%{search}%"]

        if filters:
            base += " AND " + " AND ".join(filters)
        base += " GROUP BY l.listingId ORDER BY bidCount DESC, l.createdAt DESC"

        cursor.execute(base, params)
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@listings_bp.route('/<int:listing_id>', methods=['GET'])
@login_required
def get_listing(listing_id):
    """
    Single listing detail.
    - Bids returned without buyerId (anonymity rule).
    - Price history fetched via priceHistory → transaction → listing → section
      (priceHistory has no direct sectionId column per schema).
    """
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                l.listingId, l.minPrice, l.status, l.createdAt, l.expiresAt,
                s.sectionId, s.meetingTime, s.location,
                s.enrollmentCap, s.currentEnrollment,
                c.courseCode, c.title,
                d.name  AS department,
                dist.name AS distributive,
                p.name  AS professorName,
                t.name  AS termName
            FROM listing l
            JOIN section s    ON l.sectionId    = s.sectionId
            JOIN class c      ON s.classId      = c.classId
            JOIN department d ON c.departmentId = d.departmentId
            LEFT JOIN distributive dist ON c.distributiveId = dist.distributiveId
            JOIN professor p  ON s.professorId  = p.professorId
            JOIN term t       ON s.termId       = t.termId
            WHERE l.listingId = %s
            """,
            (listing_id,)
        )
        listing = cursor.fetchone()
        if not listing:
            return err("Listing not found", 404)

        # Pending bids, no buyerId (anonymity)
        cursor.execute(
            "SELECT bidId, amount, createdAt FROM bid "
            "WHERE listingId = %s AND status = 'pending' ORDER BY amount DESC",
            (listing_id,)
        )
        listing['bids'] = cursor.fetchall()

        # Price history, join chain: priceHistory → transaction → listing → section
        cursor.execute(
            """
            SELECT ph.price, ph.recordedAt
            FROM priceHistory ph
            JOIN `transaction` t ON ph.transactionId = t.transactionId
            JOIN listing l2      ON t.listingId      = l2.listingId
            WHERE l2.sectionId = %s
            ORDER BY ph.recordedAt ASC
            """,
            (listing['sectionId'],)
        )
        listing['priceHistory'] = cursor.fetchall()

        return ok(listing)
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@listings_bp.route('/', methods=['POST'])
@login_required
def create_listing():
    """
    Create a listing. Business rules enforced:
    1. Seller must be enrolled in the section.
    2. No existing active listing for same seller + section.
    3. Must be within the add/drop period.
    4. expiresAt is capped to term.addDropEnd (cannot list past close of add/drop).
    """
    data = request.get_json()
    if not data:
        return err("No data provided")
    for field in ['sectionId', 'minPrice']:
        if field not in data:
            return err(f"Missing field: {field}")

    section_id = int(data['sectionId'])
    min_price  = float(data['minPrice'])
    seller_id  = request.student_id

    if min_price <= 0:
        return err("Minimum price must be positive")

    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(prepared=True)

        # 1. Seller enrolled?
        cursor.execute(
            "SELECT enrollmentId FROM enrollment "
            "WHERE studentId = %s AND sectionId = %s AND status = 'enrolled'",
            (seller_id, section_id)
        )
        if not cursor.fetchone():
            return err("You must be enrolled in this section to list it")

        # 2. Duplicate active listing?
        cursor.execute(
            "SELECT listingId FROM listing "
            "WHERE sellerId = %s AND sectionId = %s AND status = 'active'",
            (seller_id, section_id)
        )
        if cursor.fetchone():
            return err("You already have an active listing for this section")

        # 3 + 4. Within add/drop? Fetch addDropEnd to cap expiresAt.
        cursor2 = cnx.cursor(dictionary=True)
        cursor2.execute(
            """
            SELECT t.termId, t.addDropEnd
            FROM term t
            JOIN section s ON s.termId = t.termId
            WHERE s.sectionId = %s AND NOW() BETWEEN t.addDropStart AND t.addDropEnd
            """,
            (section_id,)
        )
        term_row = cursor2.fetchone()
        cursor2.close()
        if not term_row:
            return err("Listings can only be created during the add/drop period")

        add_drop_end = term_row['addDropEnd']
        requested    = data.get('expiresAt')

        # Cap expiresAt: use caller value if provided and earlier, else use addDropEnd
        if requested:
            cursor3 = cnx.cursor()
            cursor3.execute("SELECT LEAST(%s, %s) AS capped", (requested, add_drop_end))
            expires_at = cursor3.fetchone()[0]
            cursor3.close()
        else:
            expires_at = add_drop_end

        # Insert listing
        cursor.execute(
            "INSERT INTO listing (sellerId, sectionId, minPrice, expiresAt) VALUES (%s, %s, %s, %s)",
            (seller_id, section_id, min_price, expires_at)
        )
        listing_id = cursor.lastrowid

        # Audit log
        cursor.execute(
            "INSERT INTO auditLog (entityType, entityId, action, actorId, details) "
            "VALUES ('listing', %s, 'created', %s, %s)",
            (listing_id, seller_id, f'{{"minPrice": {min_price}}}')
        )
        cnx.commit()
        return ok({"listingId": listing_id, "expiresAt": str(expires_at)}, "Listing created", 201)

    except Exception as e:
        if cnx: cnx.rollback()
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@listings_bp.route('/<int:listing_id>/cancel', methods=['POST'])
@login_required
def cancel_listing(listing_id):
    """
    Cancel an active listing (seller only). Atomically:
    - Expires all pending bids
    - Refunds each buyer's bid_hold
    - Logs accountTransaction for each refund
    - Sends listing_expired notification to each buyer
    - Sets listing status = 'cancelled'
    - Writes audit log
    """
    seller_id = request.student_id
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT listingId, sellerId, status FROM listing WHERE listingId = %s",
            (listing_id,)
        )
        listing = cursor.fetchone()
        if not listing:
            return err("Listing not found", 404)
        if listing['sellerId'] != seller_id:
            return err("Not authorized — you do not own this listing", 403)
        if listing['status'] != 'active':
            return err("Only active listings can be cancelled")

        cursor.execute(
            "SELECT bidId, buyerId, amount FROM bid "
            "WHERE listingId = %s AND status = 'pending'",
            (listing_id,)
        )
        pending = cursor.fetchall()

        c = cnx.cursor(prepared=True)
        for bid in pending:
            c.execute("UPDATE bid SET status = 'expired' WHERE bidId = %s", (bid['bidId'],))
            c.execute(
                "UPDATE student SET accountBalance = accountBalance + %s WHERE studentId = %s",
                (bid['amount'], bid['buyerId'])
            )
            c.execute(
                "SELECT accountBalance FROM student WHERE studentId = %s", (bid['buyerId'],)
            )
            new_bal = float(c.fetchone()[0])
            c.execute(
                "INSERT INTO accountTransaction (studentId, amount, type, balanceAfter) "
                "VALUES (%s, %s, 'bid_refund', %s)",
                (bid['buyerId'], bid['amount'], new_bal)
            )
            c.execute(
                "INSERT INTO notification (studentId, type, payload) "
                "VALUES (%s, 'listing_expired', %s)",
                (bid['buyerId'], f'{{"listingId": {listing_id}}}')
            )

        c.execute("UPDATE listing SET status = 'cancelled' WHERE listingId = %s", (listing_id,))
        c.execute(
            "INSERT INTO auditLog (entityType, entityId, action, actorId) "
            "VALUES ('listing', %s, 'cancelled', %s)",
            (listing_id, seller_id)
        )
        cnx.commit()
        c.close()
        return ok(message=f"Listing cancelled. {len(pending)} bid(s) refunded.")

    except Exception as e:
        if cnx: cnx.rollback()
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@listings_bp.route('/expire-all', methods=['POST'])
def expire_all():
    """
    Expire all listings whose expiresAt has passed and status is still 'active'.
    Refunds all pending bids. Call this from a cron job every minute.
    """
    # Protect with a system secret instead of user login
    cron_key = request.headers.get('X-Cron-Key')
    expected_key = os.environ.get('CRON_SECRET')
    
    # Block the request if the secret is missing or wrong
    if not expected_key or cron_key != expected_key:
        current_app.logger.warning(f"Unauthorized cron attempt from {request.remote_addr}")
        return err("Unauthorized", 401)

    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT listingId FROM listing WHERE status = 'active' AND expiresAt <= NOW()"
        )
        stale = cursor.fetchall()

        if not stale:
            return ok({"expired": 0}, "No listings to expire")

        c = cnx.cursor(prepared=True)
        count = 0
        for row in stale:
            lid = row['listingId']
            cursor.execute(
                "SELECT bidId, buyerId, amount FROM bid "
                "WHERE listingId = %s AND status = 'pending'", (lid,)
            )
            for bid in cursor.fetchall():
                c.execute("UPDATE bid SET status = 'expired' WHERE bidId = %s", (bid['bidId'],))
                c.execute(
                    "UPDATE student SET accountBalance = accountBalance + %s WHERE studentId = %s",
                    (bid['amount'], bid['buyerId'])
                )
                c.execute(
                    "SELECT accountBalance FROM student WHERE studentId = %s", (bid['buyerId'],)
                )
                bal = float(c.fetchone()[0])
                c.execute(
                    "INSERT INTO accountTransaction (studentId, amount, type, balanceAfter) "
                    "VALUES (%s, %s, 'bid_refund', %s)",
                    (bid['buyerId'], bid['amount'], bal)
                )
                c.execute(
                    "INSERT INTO notification (studentId, type, payload) "
                    "VALUES (%s, 'listing_expired', %s)",
                    (bid['buyerId'], f'{{"listingId": {lid}}}')
                )
            c.execute("UPDATE listing SET status = 'expired' WHERE listingId = %s", (lid,))
            count += 1

        cnx.commit()
        c.close()
        return ok({"expired": count}, f"{count} listing(s) expired and bids refunded")

    except Exception as e:
        if cnx: cnx.rollback()
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)
