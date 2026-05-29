import os
import mysql.connector
import jwt
from functools import wraps
from flask import request, jsonify

JWT_SECRET = os.environ.get('JWT_SECRET', 'test_secret')
JWT_ALGORITHM = 'HS256'

def get_db():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASS'),
        database=os.environ.get('DB_NAME'),
        port=int(os.environ.get('DB_PORT', '3306'))
    )

def close_db(cnx, cursor=None):
    if cursor:
        try: cursor.close()
        except: pass
    if cnx:
        try: cnx.close()
        except: pass

def decode_token(token):
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid token"}), 401
        try:
            payload = decode_token(auth.split(' ')[1])
            request.student_id = payload['student_id']
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated