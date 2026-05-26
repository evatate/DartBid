from flask import Blueprint, request
from app import get_db, close_db, login_required
from db_helpers import ok, err

'''
POST /api/bids               -- place a bid (buyer)
POST /api/bids/<id>/accept   -- accept a bid (seller) → full atomic transaction
'''

bids_bp = Blueprint('bids', __name__)


@bids_bp.route('/', methods=['POST'])
@login_required
def place_bid():
    """
    Place a bid on an active listing.

    Business rules enforced:
    - Listing must be active and not past expiresAt
    - Buyer cannot bid on their own listing
    - Buyer cannot have more than one active (pending) bid per listing
    - Buyer cannot be already enrolled in this section
    - First bid >= minPrice; each subsequent bid > current highest by >= $0.01
    - Buyer must have sufficient balance (funds held immediately as bid_hold)
    - Balance cannot go negative (checked before deduction)

    Body: { listingId, amount }
    """
    data = request.get_json()
    if not data:
        return err("No data provided")
    for field in ['listingId', 'amount']:
        if field not in data:
            return err(f"Missing field: {field}")

    listing_id = int(data['listingId'])
    amount     = float(data['amount'])
    buyer_id   = request.student_id

    if amount <= 0:
        return err("Bid amount must be positive")

    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)

        # Fetch listing
        cursor.execute(
            "SELECT listingId, sellerId, sectionId, minPrice, status, expiresAt "
            "FROM listing WHERE listingId = %s",
            (listing_id,)
        )
        listing = cursor.fetchone()
        if not listing:
            return err("Listing not found", 404)
        if listing['status'] != 'active':
            return err("Listing is not active")

        # Check not past expiry
        cursor.execute("SELECT NOW() > %s AS expired", (listing['expiresAt'],))
        if cursor.fetchone()['expired']:
            return err("Listing has expired")

        # No self-bidding
        if listing['sellerId'] == buyer_id:
            return err("You cannot bid on your own listing")

        # No duplicate active bid
        cursor.execute(
            "SELECT bidId FROM bid "
            "WHERE listingId = %s AND buyerId = %s AND status = 'pending'",
            (listing_id, buyer_id)
        )
        if cursor.fetchone():
            return err("You already have an active bid on this listing")

        # Not already enrolled in the section
        cursor.execute(
            "SELECT enrollmentId FROM enrollment "
            "WHERE studentId = %s AND sectionId = %s AND status = 'enrolled'",
            (buyer_id, listing['sectionId'])
        )
        if cursor.fetchone():
            return err("You are already enrolled in this section")

        # Bid floor: highest pending bid + $0.01, or minPrice if no bids yet
        cursor.execute(
            "SELECT MAX(amount) AS topBid FROM bid "
            "WHERE listingId = %s AND status = 'pending'",
            (listing_id,)
        )
        top = cursor.fetchone()['topBid']
        floor = (float(top) + 0.01) if top is not None else float(listing['minPrice'])
        if amount < floor:
            return err(f"Bid must be at least ${floor:.2f}")

        # Sufficient balance check (prevents negative balance)
        cursor.execute(
            "SELECT accountBalance FROM student WHERE studentId = %s", (buyer_id,)
        )
        student = cursor.fetchone()
        if not student:
            return err("Student not found", 404)
        if float(student['accountBalance']) < amount:
            return err("Insufficient account balance")

        # ── All checks passed — hold funds and insert bid ──────────────────
        c = cnx.cursor(prepared=True)
        c.execute(
            "UPDATE student SET accountBalance = accountBalance - %s WHERE studentId = %s",
            (amount, buyer_id)
        )
        c.execute(
            "SELECT accountBalance FROM student WHERE studentId = %s", (buyer_id,)
        )
        new_bal = float(c.fetchone()[0])
        c.execute(
            "INSERT INTO accountTransaction (studentId, amount, type, balanceAfter) "
            "VALUES (%s, %s, 'bid_hold', %s)",
            (buyer_id, amount, new_bal)
        )
        c.execute(
            "INSERT INTO bid (listingId, buyerId, amount, expiresAt) VALUES (%s, %s, %s, %s)",
            (listing_id, buyer_id, amount, listing['expiresAt'])
        )
        bid_id = c.lastrowid

        # Notify seller (bid_received)
        c.execute(
            "INSERT INTO notification (studentId, type, payload) VALUES (%s, 'bid_received', %s)",
            (listing['sellerId'], f'{{"bidId": {bid_id}, "amount": {amount}}}')
        )
        # Audit log
        c.execute(
            "INSERT INTO auditLog (entityType, entityId, action, actorId, details) "
            "VALUES ('bid', %s, 'created', %s, %s)",
            (bid_id, buyer_id, f'{{"amount": {amount}}}')
        )
        cnx.commit()
        c.close()
        return ok({"bidId": bid_id, "amountHeld": amount}, "Bid placed successfully", 201)

    except Exception as e:
        if cnx: cnx.rollback()
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@bids_bp.route('/<int:bid_id>/accept', methods=['POST'])
@login_required
def accept_bid(bid_id):
    """
    Seller accepts a bid. This is the core atomic transaction.
    All steps succeed together or the entire operation rolls back.

    Steps (in order):
      1.  Insert transaction record
      2.  Drop seller enrollment (status = 'dropped')
      3.  Enroll buyer (INSERT … ON DUPLICATE KEY UPDATE)
      4.  Recompute section.currentEnrollment (verify cap not breached)
      5.  Pay out seller (buyer's funds already held from bid_hold)
      6.  Log seller accountTransaction (payout)
      7.  Mark winning bid 'accepted'
      8.  Mark all other pending bids 'outbid' + refund each buyer
      9.  Log accountTransaction (bid_refund) for each losing bidder
      10. Close listing (status = 'completed')
      11. Append priceHistory (1:1 with transaction — unique constraint enforced in DB)
      12. Notify buyer (bid_accepted) and seller (payout)
      13. Write audit log entry

    Business rules verified:
    - Only the seller (request.student_id) can accept
    - Bid and listing must both be active
    - Enrollment cap is never exceeded (checked in step 4)
    """
    seller_id = request.student_id
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)

        # Fetch bid + listing together
        cursor.execute(
            """
            SELECT b.bidId, b.listingId, b.buyerId, b.amount, b.status,
                   l.sellerId, l.sectionId, l.status AS listingStatus
            FROM bid b
            JOIN listing l ON b.listingId = l.listingId
            WHERE b.bidId = %s
            """,
            (bid_id,)
        )
        bid = cursor.fetchone()
        if not bid:
            return err("Bid not found", 404)
        if bid['sellerId'] != seller_id:
            return err("Not authorized — you do not own this listing", 403)
        if bid['status'] != 'pending':
            return err("Bid is no longer active")
        if bid['listingStatus'] != 'active':
            return err("Listing is not active")

        listing_id  = bid['listingId']
        buyer_id    = bid['buyerId']
        section_id  = bid['sectionId']
        final_price = float(bid['amount'])

        # Need termId for enrollment insert (unique key: studentId+sectionId+termId)
        cursor.execute(
            "SELECT termId, enrollmentCap FROM section WHERE sectionId = %s", (section_id,)
        )
        section_row = cursor.fetchone()
        if not section_row:
            return err("Section not found", 404)
        term_id      = section_row['termId']
        enroll_cap   = section_row['enrollmentCap']

        # ── Begin atomic block ─────────────────────────────────────────────
        c = cnx.cursor(prepared=True)

        # 1. Transaction record
        c.execute(
            "INSERT INTO `transaction` (listingId, bidId, buyerId, sellerId, finalPrice) "
            "VALUES (%s, %s, %s, %s, %s)",
            (listing_id, bid_id, buyer_id, seller_id, final_price)
        )
        txn_id = c.lastrowid

        # 2. Drop seller enrollment
        c.execute(
            "UPDATE enrollment SET status = 'dropped', droppedAt = NOW() "
            "WHERE studentId = %s AND sectionId = %s AND termId = %s AND status = 'enrolled'",
            (seller_id, section_id, term_id)
        )

        # 3. Enroll buyer (handles case where buyer was previously dropped from this section)
        c.execute(
            """
            INSERT INTO enrollment (studentId, sectionId, termId, status, enrolledAt)
            VALUES (%s, %s, %s, 'enrolled', NOW())
            ON DUPLICATE KEY UPDATE status = 'enrolled', droppedAt = NULL, enrolledAt = NOW()
            """,
            (buyer_id, section_id, term_id)
        )

        # 4. Recompute currentEnrollment and verify cap
        c.execute(
            "UPDATE section SET currentEnrollment = ("
            "  SELECT COUNT(*) FROM enrollment "
            "  WHERE sectionId = %s AND status = 'enrolled'"
            ") WHERE sectionId = %s",
            (section_id, section_id)
        )
        c.execute(
            "SELECT currentEnrollment FROM section WHERE sectionId = %s", (section_id,)
        )
        new_count = c.fetchone()[0]
        if new_count > enroll_cap:
            cnx.rollback()
            return err("Transaction aborted: section enrollment cap would be exceeded", 409)

        # 5 + 6. Pay seller
        c.execute(
            "UPDATE student SET accountBalance = accountBalance + %s WHERE studentId = %s",
            (final_price, seller_id)
        )
        c.execute("SELECT accountBalance FROM student WHERE studentId = %s", (seller_id,))
        seller_bal = float(c.fetchone()[0])
        c.execute(
            "INSERT INTO accountTransaction (studentId, amount, type, relatedTransactionId, balanceAfter) "
            "VALUES (%s, %s, 'payout', %s, %s)",
            (seller_id, final_price, txn_id, seller_bal)
        )

        # 7. Mark winning bid accepted
        c.execute("UPDATE bid SET status = 'accepted' WHERE bidId = %s", (bid_id,))

        # 8 + 9. Invalidate + refund all other pending bids
        cursor.execute(
            "SELECT bidId, buyerId, amount FROM bid "
            "WHERE listingId = %s AND status = 'pending' AND bidId != %s",
            (listing_id, bid_id)
        )
        for lb in cursor.fetchall():
            c.execute("UPDATE bid SET status = 'outbid' WHERE bidId = %s", (lb['bidId'],))
            c.execute(
                "UPDATE student SET accountBalance = accountBalance + %s WHERE studentId = %s",
                (lb['amount'], lb['buyerId'])
            )
            c.execute("SELECT accountBalance FROM student WHERE studentId = %s", (lb['buyerId'],))
            lb_bal = float(c.fetchone()[0])
            c.execute(
                "INSERT INTO accountTransaction (studentId, amount, type, balanceAfter) "
                "VALUES (%s, %s, 'bid_refund', %s)",
                (lb['buyerId'], lb['amount'], lb_bal)
            )
            c.execute(
                "INSERT INTO notification (studentId, type, payload) VALUES (%s, 'outbid', %s)",
                (lb['buyerId'], f'{{"listingId": {listing_id}, "transactionId": {txn_id}}}')
            )

        # 10. Close listing
        c.execute("UPDATE listing SET status = 'completed' WHERE listingId = %s", (listing_id,))

        # 11. Append price history (DB unique constraint on transactionId ensures 1:1)
        c.execute(
            "INSERT INTO priceHistory (transactionId, price) VALUES (%s, %s)",
            (txn_id, final_price)
        )

        # 12. Notifications
        c.execute(
            "INSERT INTO notification (studentId, type, payload) VALUES (%s, 'bid_accepted', %s)",
            (buyer_id, f'{{"transactionId": {txn_id}, "finalPrice": {final_price}}}')
        )
        c.execute(
            "INSERT INTO notification (studentId, type, payload) VALUES (%s, 'payout', %s)",
            (seller_id, f'{{"transactionId": {txn_id}, "finalPrice": {final_price}}}')
        )

        # 13. Audit log
        c.execute(
            "INSERT INTO auditLog (entityType, entityId, action, actorId, details) "
            "VALUES ('transaction', %s, 'completed', %s, %s)",
            (txn_id, seller_id,
             f'{{"finalPrice": {final_price}, "sectionId": {section_id}, "buyerId": "anon"}}')
        )

        cnx.commit()
        c.close()
        return ok(
            {"transactionId": txn_id, "finalPrice": final_price},
            "Transaction completed successfully"
        )

    except Exception as e:
        if cnx: cnx.rollback()
        return err(f"Transaction rolled back: {str(e)}", 500)
    finally:
        close_db(cnx, cursor)
