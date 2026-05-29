from flask import Blueprint, request
from db_helpers import ok, err

'''
All routes are scoped to the authenticated student via JWT (request.student_id).
No student can access another student's private data through these endpoints.

GET  /api/students/me
POST /api/students/me/deposit
GET  /api/students/me/enrollments
GET  /api/students/me/listings
GET  /api/students/me/bids
GET  /api/students/me/account-history
GET  /api/students/me/transactions
'''

students_bp = Blueprint('students', __name__)


@students_bp.route('/me', methods=['GET'])
@login_required
def get_profile():
    """Return own profile and current balance."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT studentId, name, email, accountBalance, yearStanding, major, createdAt "
            "FROM student WHERE studentId = %s",
            (request.student_id,)
        )
        student = cursor.fetchone()
        if not student:
            return err("Student not found", 404)
        return ok(student)
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@students_bp.route('/me/deposit', methods=['POST'])
@login_required
def deposit():
    """
    Simulate depositing funds (like DASH top-up).
    Body: { amount: float }
    Business rule: amount must be positive. Balance cannot go negative (enforced here and at bid time).
    """
    data = request.get_json()
    amount = data.get('amount') if data else None
    if not amount or float(amount) <= 0:
        return err("Amount must be a positive number")
    amount = float(amount)

    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(prepared=True)
        cursor.execute(
            "UPDATE student SET accountBalance = accountBalance + %s WHERE studentId = %s",
            (amount, request.student_id)
        )
        if cursor.rowcount == 0:
            return err("Student not found", 404)

        # Read new balance for audit record
        cursor2 = cnx.cursor(dictionary=True)
        cursor2.execute("SELECT accountBalance FROM student WHERE studentId = %s", (request.student_id,))
        new_balance = float(cursor2.fetchone()['accountBalance'])
        cursor2.close()

        cursor.execute(
            "INSERT INTO accountTransaction (studentId, amount, type, balanceAfter) "
            "VALUES (%s, %s, 'deposit', %s)",
            (request.student_id, amount, new_balance)
        )
        cnx.commit()
        return ok({"newBalance": new_balance}, "Deposit successful")
    except Exception as e:
        if cnx: cnx.rollback()
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@students_bp.route('/me/enrollments', methods=['GET'])
@login_required
def get_enrollments():
    """Return all currently enrolled sections for the authenticated student."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT e.enrollmentId, e.sectionId, e.status, e.enrolledAt,
                   c.courseCode, c.title,
                   s.meetingTime, s.location,
                   p.name AS professorName,
                   t.name AS termName
            FROM enrollment e
            JOIN section s  ON e.sectionId  = s.sectionId
            JOIN class c    ON s.classId    = c.classId
            JOIN professor p ON s.professorId = p.professorId
            JOIN term t     ON e.termId     = t.termId
            WHERE e.studentId = %s AND e.status = 'enrolled'
            ORDER BY t.name, c.courseCode
            """,
            (request.student_id,)
        )
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@students_bp.route('/me/listings', methods=['GET'])
@login_required
def get_my_listings():
    """
    Seller dashboard: all listings created by this student, with bid counts and highest bid.
    Includes bids for each active listing so the seller can review and accept.
    """
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT l.listingId, l.sectionId, l.minPrice, l.status,
                   l.createdAt, l.expiresAt,
                   c.courseCode, c.title,
                   s.meetingTime, s.location,
                   COUNT(b.bidId)  AS bidCount,
                   MAX(b.amount)  AS highestBid
            FROM listing l
            JOIN section s ON l.sectionId = s.sectionId
            JOIN class c   ON s.classId   = c.classId
            LEFT JOIN bid b ON l.listingId = b.listingId AND b.status = 'pending'
            WHERE l.sellerId = %s
            GROUP BY l.listingId
            ORDER BY l.createdAt DESC
            """,
            (request.student_id,)
        )
        listings = cursor.fetchall()

        # For each active listing attach pending bids so seller can accept
        # bidId and amount visible; buyerId omitted (anonymity rule)
        for listing in listings:
            if listing['status'] == 'active':
                cursor2 = cnx.cursor(dictionary=True)
                cursor2.execute(
                    "SELECT bidId, amount, createdAt FROM bid "
                    "WHERE listingId = %s AND status = 'pending' ORDER BY amount DESC",
                    (listing['listingId'],)
                )
                listing['bids'] = cursor2.fetchall()
                cursor2.close()
            else:
                listing['bids'] = []

        return ok(listings)
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@students_bp.route('/me/bids', methods=['GET'])
@login_required
def get_my_bids():
    """Buyer view: all bids placed by this student across all listings."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT b.bidId, b.listingId, b.amount, b.status,
                   b.createdAt, b.expiresAt,
                   c.courseCode, c.title,
                   s.meetingTime,
                   l.minPrice,
                   l.expiresAt AS listingExpiresAt,
                   l.status    AS listingStatus
            FROM bid b
            JOIN listing l ON b.listingId = l.listingId
            JOIN section s ON l.sectionId = s.sectionId
            JOIN class c   ON s.classId   = c.classId
            WHERE b.buyerId = %s
            ORDER BY b.createdAt DESC
            """,
            (request.student_id,)
        )
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@students_bp.route('/me/account-history', methods=['GET'])
@login_required
def get_account_history():
    """Full ledger: every deposit, bid_hold, bid_refund, payout for this student."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT accountTxnId, amount, type, relatedTransactionId, balanceAfter, createdAt "
            "FROM accountTransaction WHERE studentId = %s ORDER BY createdAt DESC",
            (request.student_id,)
        )
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@students_bp.route('/me/transactions', methods=['GET'])
@login_required
def get_my_transactions():
    """
    Completed marketplace transactions where this student was buyer OR seller.
    Seller's identity not revealed to buyers and vice versa — only own role shown.
    """
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT t.transactionId, t.finalPrice, t.createdAt,
                   c.courseCode, c.title,
                   s.meetingTime,
                   CASE WHEN t.buyerId = %s THEN 'buyer' ELSE 'seller' END AS myRole
            FROM transaction t
            JOIN listing l ON t.listingId = l.listingId
            JOIN section s ON l.sectionId = s.sectionId
            JOIN class c   ON s.classId   = c.classId
            WHERE t.buyerId = %s OR t.sellerId = %s
            ORDER BY t.createdAt DESC
            """,
            (request.student_id, request.student_id, request.student_id)
        )
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)
