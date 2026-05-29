from flask import Blueprint, jsonify, request
import bcrypt
from shared_utils import get_db, close_db, create_token
from db_helpers import ok, err, is_duplicate

'''
POST /api/auth/register  -- create student account
POST /api/auth/login     -- returns JWT token
'''

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Create a new student account.
    Body: { name, email, password, yearStanding, major (optional) }
    Each new student gets a $500 simulated starting balance.
    """
    data = request.get_json()
    if not data:
        return err("No data provided")

    for field in ['name', 'email', 'password', 'yearStanding']:
        if field not in data:
            return err(f"Missing field: {field}")

    valid_years = ('freshman', 'sophomore', 'junior', 'senior')
    if data['yearStanding'] not in valid_years:
        if data['yearStanding'] not in valid_years:
            return err(f"yearStanding must be one of: {', '.join(valid_years)}")

    # Using 10 rounds to prevent timeouts on slow Free Tier CPUs
    hashed = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt(10))

    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(prepared=True)
        cursor.execute(
            "INSERT INTO student (name, email, hashedPassword, yearStanding, major, accountBalance) "
            "VALUES (%s, %s, %s, %s, %s, 500.00)",
            (
                data['name'],
                data['email'],
                hashed.decode('utf-8'),
                data['yearStanding'],
                data.get('major'),
            )
        )
        cnx.commit()
        student_id = cursor.lastrowid
        token = create_token(student_id)
        return ok({"studentId": student_id, "token": token}, "Account created", 201)

    except Exception as e:
        if cnx and cnx.is_connected(): cnx.rollback()
        if is_duplicate(e):
            return err("Email already registered", 409)
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login with email + password. Returns JWT token.
    Body: { email, password }
    """
    data = request.get_json()
    if not data or 'email' not in data or 'password' not in data:
        return err("Email and password required")

    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(prepared=True)
        cursor.execute(
            "SELECT studentId, hashedPassword FROM student WHERE email = %s",
            (data['email'],)
        )
        row = cursor.fetchone()
        if not row:
            return err("Invalid email or password", 401)

        student_id, hashed_pw = row

        if isinstance(hashed_pw, bytearray):
            hashed_pw = bytes(hashed_pw)
        elif isinstance(hashed_pw, str):
            hashed_pw = hashed_pw.encode('utf-8')

        try:
            if not bcrypt.checkpw(data['password'].encode('utf-8'), hashed_pw):
                return err("Invalid email or password", 401)
        except ValueError:
            return err("Database password format is invalid. Check for truncation or incorrect hashing method.", 500)

        token = create_token(student_id)
        return ok({"token": token, "studentId": student_id})

    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)
