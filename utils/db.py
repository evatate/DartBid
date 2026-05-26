from app import mysql
from flask import jsonify


def get_cursor():
    return mysql.connection.cursor()


def commit():
    mysql.connection.commit()


def rollback():
    mysql.connection.rollback()


def error_response(message, status=400):
    return jsonify({"error": message}), status


def success_response(data=None, message=None, status=200):
    resp = {}
    if data is not None:
        resp["data"] = data
    if message:
        resp["message"] = message
    return jsonify(resp), status
