from flask import Blueprint, request
from app import get_db, close_db, login_required
from db_helpers import ok, err

'''
GET  /api/notifications            -- own notifications, unread first (auth required)
POST /api/notifications/mark-read  -- mark all own notifications as read (auth required)
'''

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/', methods=['GET'])
@login_required
def get_notifications():
    """Return latest 50 notifications for the authenticated student, unread first."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT notificationId, type, payload, isRead, createdAt "
            "FROM notification "
            "WHERE studentId = %s "
            "ORDER BY isRead ASC, createdAt DESC "
            "LIMIT 50",
            (request.student_id,)
        )
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@notifications_bp.route('/mark-read', methods=['POST'])
@login_required
def mark_read():
    """Mark all unread notifications as read for the authenticated student."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(prepared=True)
        cursor.execute(
            "UPDATE notification SET isRead = TRUE "
            "WHERE studentId = %s AND isRead = FALSE",
            (request.student_id,)
        )
        cnx.commit()
        return ok({"updated": cursor.rowcount}, "Notifications marked as read")
    except Exception as e:
        if cnx: cnx.rollback()
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)
