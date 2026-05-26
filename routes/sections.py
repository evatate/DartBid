from flask import Blueprint, request
from app import get_db, close_db, login_required
from db_helpers import ok, err

'''
GET /api/sections                  -- browse sections (filters: department, distributive, termId)
GET /api/sections/ticker           -- stock ticker (active listings + price movement)
GET /api/sections/departments      -- all departments for filter dropdowns
GET /api/sections/distributives    -- all distributives for filter dropdowns
GET /api/sections/<id>             -- section detail + active listing + full price history

NOTE: string routes (/ticker, /departments, /distributives) are registered before /<id>
so Flask does not try to cast them as integers.
'''

sections_bp = Blueprint('sections', __name__)


@sections_bp.route('/', methods=['GET'])
@login_required
def get_sections():
    """Browse all sections. Supports filters: department (code), distributive (code), termId."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)

        query = """
            SELECT
                s.sectionId, s.meetingTime, s.location,
                s.enrollmentCap, s.currentEnrollment,
                c.courseCode, c.title,
                d.name AS department, d.code AS departmentCode,
                dist.name AS distributive, dist.code AS distributiveCode,
                p.name AS professorName,
                t.name AS termName, t.termId
            FROM section s
            JOIN class c      ON s.classId      = c.classId
            JOIN department d ON c.departmentId = d.departmentId
            LEFT JOIN distributive dist ON c.distributiveId = dist.distributiveId
            JOIN professor p  ON s.professorId  = p.professorId
            JOIN term t       ON s.termId       = t.termId
            WHERE 1=1
        """
        params = []

        dept = request.args.get('department')
        dist = request.args.get('distributive')
        term = request.args.get('termId')

        if dept:
            query += " AND d.code = %s";  params.append(dept)
        if dist:
            query += " AND dist.code = %s"; params.append(dist)
        if term:
            query += " AND s.termId = %s"; params.append(int(term))

        query += " ORDER BY c.courseCode"
        cursor.execute(query, params)
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@sections_bp.route('/ticker', methods=['GET'])
@login_required
def get_ticker():
    """
    Stock ticker for the home page banner.
    Returns all sections with active listings, current high bid, last sale price,
    and price direction (up / down / flat / new).

    Price history is joined via: priceHistory → transaction → listing → section
    (priceHistory has no direct sectionId column per schema).
    """
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                s.sectionId,
                c.courseCode,
                c.title,
                l.listingId,
                l.minPrice,
                COALESCE(MAX(b.amount), l.minPrice) AS currentPrice,
                (
                    SELECT ph2.price
                    FROM priceHistory ph2
                    JOIN `transaction` t2 ON ph2.transactionId = t2.transactionId
                    JOIN listing l2       ON t2.listingId      = l2.listingId
                    WHERE l2.sectionId = s.sectionId
                    ORDER BY ph2.recordedAt DESC
                    LIMIT 1
                ) AS lastSalePrice
            FROM listing l
            JOIN section s    ON l.sectionId    = s.sectionId
            JOIN class c      ON s.classId      = c.classId
            LEFT JOIN bid b   ON l.listingId    = b.listingId AND b.status = 'pending'
            WHERE l.status = 'active' AND l.expiresAt > NOW()
            GROUP BY l.listingId, s.sectionId, c.courseCode, c.title, l.minPrice
            ORDER BY c.courseCode
            """
        )
        rows = cursor.fetchall()
        for row in rows:
            cur_p  = float(row['currentPrice'])  if row['currentPrice']  else None
            last_p = float(row['lastSalePrice']) if row['lastSalePrice'] else None
            if cur_p is not None and last_p is not None:
                diff = cur_p - last_p
                row['priceChange'] = diff
                row['direction']   = 'up' if diff > 0 else ('down' if diff < 0 else 'flat')
            else:
                row['priceChange'] = None
                row['direction']   = 'new'
        return ok(rows)
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@sections_bp.route('/departments', methods=['GET'])
@login_required
def get_departments():
    """All departments — for filter dropdowns."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute("SELECT departmentId, name, code FROM department ORDER BY name")
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@sections_bp.route('/distributives', methods=['GET'])
@login_required
def get_distributives():
    """All distributives — for filter dropdowns."""
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute("SELECT distributiveId, name, code FROM distributive ORDER BY name")
        return ok(cursor.fetchall())
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)


@sections_bp.route('/<int:section_id>', methods=['GET'])
@login_required
def get_section(section_id):
    """
    Section detail page.
    Returns: section info, active listing (if any) with bid summary,
    and full price history for the stock chart.
    """
    cnx = cursor = None
    try:
        cnx = get_db()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                s.sectionId, s.meetingTime, s.location,
                s.enrollmentCap, s.currentEnrollment,
                c.courseCode, c.title,
                d.name  AS department,
                dist.name AS distributive,
                p.name  AS professorName,
                t.name  AS termName, t.termId,
                t.addDropStart, t.addDropEnd
            FROM section s
            JOIN class c      ON s.classId      = c.classId
            JOIN department d ON c.departmentId = d.departmentId
            LEFT JOIN distributive dist ON c.distributiveId = dist.distributiveId
            JOIN professor p  ON s.professorId  = p.professorId
            JOIN term t       ON s.termId       = t.termId
            WHERE s.sectionId = %s
            """,
            (section_id,)
        )
        section = cursor.fetchone()
        if not section:
            return err("Section not found", 404)

        # Active listing with bid summary (no buyerIds)
        cursor.execute(
            """
            SELECT
                l.listingId, l.minPrice, l.status, l.expiresAt,
                (SELECT MAX(b.amount) FROM bid b
                 WHERE b.listingId = l.listingId AND b.status = 'pending') AS highestBid,
                (SELECT COUNT(*)     FROM bid b
                 WHERE b.listingId = l.listingId AND b.status = 'pending') AS bidCount
            FROM listing l
            WHERE l.sectionId = %s AND l.status = 'active' AND l.expiresAt > NOW()
            LIMIT 1
            """,
            (section_id,)
        )
        section['activeListing'] = cursor.fetchone()

        # Full price history for stock chart
        # Join chain: priceHistory → transaction → listing → section (no direct sectionId on priceHistory)
        cursor.execute(
            """
            SELECT ph.price, ph.recordedAt
            FROM priceHistory ph
            JOIN `transaction` t ON ph.transactionId = t.transactionId
            JOIN listing l       ON t.listingId      = l.listingId
            WHERE l.sectionId = %s
            ORDER BY ph.recordedAt ASC
            """,
            (section_id,)
        )
        section['priceHistory'] = cursor.fetchall()

        return ok(section)
    except Exception as e:
        return err(str(e), 500)
    finally:
        close_db(cnx, cursor)
