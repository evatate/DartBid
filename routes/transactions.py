from flask import Blueprint
from utils.db import get_cursor, error_response, success_response

transactions_bp = Blueprint("transactions", __name__)


@transactions_bp.route("/<int:transaction_id>", methods=["GET"])
def get_transaction(transaction_id):
    """Get a completed transaction by ID."""
    cur = get_cursor()
    cur.execute(
        """
        SELECT t.transactionId, t.finalPrice, t.createdAt,
               l.sectionId,
               c.courseCode, c.title,
               s.meetingTime
        FROM transaction t
        JOIN listing l ON t.listingId = l.listingId
        JOIN section s ON l.sectionId = s.sectionId
        JOIN class c ON s.classId = c.classId
        WHERE t.transactionId = %s
        """,
        (transaction_id,),
    )
    txn = cur.fetchone()
    if not txn:
        return error_response("Transaction not found", 404)
    return success_response(txn)
