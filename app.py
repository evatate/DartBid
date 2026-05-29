import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
import json
import bcrypt
import jwt
import datetime
from functools import wraps
from shared_utils import get_db, close_db, login_required, create_token

'''
DartBid API using Flask + JWT
Final Project: DartBid
Names: Caroline Chung, Giselle Wu, Eva Tate, Helen Cui
Course: Dartmouth CS 61 Spring 2026

Usage:
    Start flask: flask --app app.py run --port 8080
    Test with Postman at http://localhost:8080/api/

Routes:
    POST /api/auth/register       -- create student account
    POST /api/auth/login          -- login, receive JWT

    GET  /api/students/me         -- own profile + balance (auth required)
    POST /api/students/me/deposit -- add funds to own account (auth required)
    GET  /api/students/me/enrollments        -- own active enrollments (auth required)
    GET  /api/students/me/listings           -- own listings / seller dashboard (auth required)
    GET  /api/students/me/bids               -- own bids as buyer (auth required)
    GET  /api/students/me/account-history    -- full ledger history (auth required)
    GET  /api/students/me/transactions       -- completed transactions as buyer or seller (auth required)

    GET  /api/listings            -- browse active listings (auth required, filters via query params)
    POST /api/listings            -- create a listing (auth required, seller)
    GET  /api/listings/<id>       -- listing detail with bids + price history (auth required)
    POST /api/listings/<id>/cancel   -- cancel own listing (auth required, seller)
    POST /api/listings/expire-all    -- expire stale listings + refund bids (auth required)

    POST /api/bids                -- place a bid (auth required, buyer)
    POST /api/bids/<id>/accept    -- accept a bid (auth required, seller)

    GET  /api/sections            -- browse sections (auth required, filters)
    GET  /api/sections/ticker     -- stock ticker feed (auth required)
    GET  /api/sections/departments   -- department list for dropdowns (auth required)
    GET  /api/sections/distributives -- distributive list for dropdowns (auth required)
    GET  /api/sections/<id>       -- section detail + active listing + price history (auth required)

    GET  /api/notifications       -- own notifications (auth required)
    POST /api/notifications/mark-read  -- mark all read (auth required)
'''

app = Flask(__name__)

# Only allow specific websites defined in .env
allowed_origins = os.environ.get('ALLOWED_ORIGINS')
origins_list = [o.strip() for o in allowed_origins.split(',')] if allowed_origins else []
CORS(app, resources={r"/api/*": {"origins": origins_list}})

# Environment variable validation
if not os.environ.get('JWT_SECRET'):
    app.logger.error("JWT_SECRET is not set in environment variables!")


# Error handlers

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405

@app.route('/')
def home():
    return jsonify({
        "message": "DartBid API is running!",
        "status": "healthy",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })

@app.route('/api/health')
def health():
    return jsonify({"status": "ok"})


# Register blueprints

from routes.auth         import auth_bp
from routes.students     import students_bp
from routes.listings     import listings_bp
from routes.bids         import bids_bp
from routes.sections     import sections_bp
from routes.notifications import notifications_bp

app.register_blueprint(auth_bp,          url_prefix='/api/auth')
app.register_blueprint(students_bp,      url_prefix='/api/students')
app.register_blueprint(listings_bp,      url_prefix='/api/listings')
app.register_blueprint(bids_bp,          url_prefix='/api/bids')
app.register_blueprint(sections_bp,      url_prefix='/api/sections')
app.register_blueprint(notifications_bp, url_prefix='/api/notifications')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
