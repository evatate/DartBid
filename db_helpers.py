"""
Shared DB utilities for DartBid routes.
All routes import get_db / close_db / ok / err from here.
Mirrors the mysql.connector pattern from Lab 4.
"""
from flask import jsonify
import mysql.connector


def get_db():
    """Import and call shared_utils.get_db()."""
    from shared_utils import get_db as _get_db
    return _get_db()


def close_db(cnx, cursor=None):
    from shared_utils import close_db as _close_db
    _close_db(cnx, cursor)


def ok(data=None, message=None, status=200):
    """Standard success envelope."""
    resp = {}
    if data is not None:
        resp['data'] = data
    if message:
        resp['message'] = message
    return jsonify(resp), status


def err(message, status=400):
    """Standard error envelope."""
    return jsonify({"error": message}), status


def is_duplicate(e):
    return hasattr(e, 'errno') and e.errno == 1062
