import requests

'''
DartBid API Client
Final Project: DartBid
Names: Caroline Chung, Giselle Wu, Eva Tate, Helen Cui
Course: Dartmouth CS 61 Spring 2026
    based on Lab 4 scaffold

Usage: python3 call_api.py
       Server must be running: flask --app app.py run --port 8080
'''

BASE_URL = "http://localhost:8080/api"
token = None


def get_headers():
    return {"Authorization": f"Bearer {token}"} if token else {}


def handle(response):
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        if isinstance(data, list):
            for item in data: print(item)
        else:
            print(data)
    except Exception:
        print(response.text)


def conn_err():
    print("Could not connect. Is Flask running on port 8080?")


# ── Auth ──────────────────────────────────────────────────────────────────────

def register():
    name      = input("Name: ")
    email     = input("Email: ")
    password  = input("Password: ")
    year      = input("Year standing (freshman/sophomore/junior/senior): ")
    major     = input("Major (optional): ")
    try:
        r = requests.post(f"{BASE_URL}/auth/register", json={
            "name": name, "email": email, "password": password,
            "yearStanding": year, "major": major or None
        })
        handle(r)
    except requests.exceptions.ConnectionError: conn_err()


def login():
    global token
    email    = input("Email: ")
    password = input("Password: ")
    try:
        r = requests.post(f"{BASE_URL}/auth/login",
                          json={"email": email, "password": password})
        if r.status_code == 200:
            token = r.json()['data']['token']
            print("Login successful! Token saved.")
        else:
            handle(r)
    except requests.exceptions.ConnectionError: conn_err()


# ── Student / account ─────────────────────────────────────────────────────────

def my_profile():
    try: handle(requests.get(f"{BASE_URL}/students/me", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def deposit():
    amount = input("Deposit amount: $")
    try:
        handle(requests.post(f"{BASE_URL}/students/me/deposit",
                             headers=get_headers(), json={"amount": float(amount)}))
    except requests.exceptions.ConnectionError: conn_err()

def my_enrollments():
    try: handle(requests.get(f"{BASE_URL}/students/me/enrollments", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def my_listings():
    try: handle(requests.get(f"{BASE_URL}/students/me/listings", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def my_bids():
    try: handle(requests.get(f"{BASE_URL}/students/me/bids", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def my_account_history():
    try: handle(requests.get(f"{BASE_URL}/students/me/account-history", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def my_transactions():
    try: handle(requests.get(f"{BASE_URL}/students/me/transactions", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()


# ── Sections ──────────────────────────────────────────────────────────────────

def browse_sections():
    dept = input("Filter by dept code (blank = all): ").strip()
    dist = input("Filter by distrib code (blank = all): ").strip()
    params = {}
    if dept: params['department'] = dept
    if dist: params['distributive'] = dist
    try: handle(requests.get(f"{BASE_URL}/sections/", headers=get_headers(), params=params))
    except requests.exceptions.ConnectionError: conn_err()

def section_detail():
    sid = input("Section ID: ")
    try: handle(requests.get(f"{BASE_URL}/sections/{sid}", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def ticker():
    try: handle(requests.get(f"{BASE_URL}/sections/ticker", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()


# ── Listings ──────────────────────────────────────────────────────────────────

def browse_listings():
    dept   = input("Filter by dept code (blank = all): ").strip()
    dist   = input("Filter by distrib (blank = all): ").strip()
    search = input("Search (blank = all): ").strip()
    params = {}
    if dept:   params['department']   = dept
    if dist:   params['distributive'] = dist
    if search: params['search']       = search
    try: handle(requests.get(f"{BASE_URL}/listings/", headers=get_headers(), params=params))
    except requests.exceptions.ConnectionError: conn_err()

def listing_detail():
    lid = input("Listing ID: ")
    try: handle(requests.get(f"{BASE_URL}/listings/{lid}", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def create_listing():
    sid       = input("Section ID to list: ")
    min_price = input("Minimum asking price: $")
    expires   = input("Expires at (YYYY-MM-DD HH:MM:SS, blank = end of add/drop): ").strip()
    body = {"sectionId": int(sid), "minPrice": float(min_price)}
    if expires: body['expiresAt'] = expires
    try:
        handle(requests.post(f"{BASE_URL}/listings/", headers=get_headers(), json=body))
    except requests.exceptions.ConnectionError: conn_err()

def cancel_listing():
    lid = input("Listing ID to cancel: ")
    try:
        handle(requests.post(f"{BASE_URL}/listings/{lid}/cancel",
                             headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()


# ── Bids ──────────────────────────────────────────────────────────────────────

def place_bid():
    lid    = input("Listing ID: ")
    amount = input("Bid amount: $")
    try:
        handle(requests.post(f"{BASE_URL}/bids/", headers=get_headers(),
                             json={"listingId": int(lid), "amount": float(amount)}))
    except requests.exceptions.ConnectionError: conn_err()

def accept_bid():
    bid_id = input("Bid ID to accept: ")
    try:
        handle(requests.post(f"{BASE_URL}/bids/{bid_id}/accept", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()


# ── Notifications ─────────────────────────────────────────────────────────────

def my_notifications():
    try: handle(requests.get(f"{BASE_URL}/notifications/", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()

def mark_notifications_read():
    try: handle(requests.post(f"{BASE_URL}/notifications/mark-read", headers=get_headers()))
    except requests.exceptions.ConnectionError: conn_err()


# ── Automated tests ───────────────────────────────────────────────────────────

def run_all_tests():
    """Full automated test suite (press T)."""
    global token
    print("\n=== DartBid API Test Suite ===")

    def get_auth_header(t):
        return {"Authorization": f"Bearer {t}"}

    # T1: unauthenticated access
    print("\nT1: Unauthenticated access")
    old_token = token
    token = None
    r = requests.get(f"{BASE_URL}/listings/")
    print(f"  GET /listings (no token)  -> {r.status_code} (expect 401)")
    r = requests.get(f"{BASE_URL}/students/me")
    print(f"  GET /students/me (no token) -> {r.status_code} (expect 401)")

    # T2: bad login
    print("\nT2: Bad credentials")
    r = requests.post(f"{BASE_URL}/auth/login",
                      json={"email": "nobody@dartmouth.edu", "password": "wrong"})
    print(f"  POST /auth/login (bad creds) -> {r.status_code} (expect 401)")

    # T3: Setup two users (Seller and Buyer)
    print("\nT3: User Setup (Seller & Buyer)")
    import time; ts = int(time.time())
    seller_email = f"seller{ts}@dartmouth.edu"
    buyer_email = f"buyer{ts}@dartmouth.edu"
    
    requests.post(f"{BASE_URL}/auth/register", json={
        "name": "Seller User", "email": seller_email,
        "password": "password", "yearStanding": "senior"
    })
    s_login = requests.post(f"{BASE_URL}/auth/login", json={"email": seller_email, "password": "password"}).json()
    seller_token = s_login['data']['token']
    
    requests.post(f"{BASE_URL}/auth/register", json={
        "name": "Buyer User", "email": buyer_email,
        "password": "password", "yearStanding": "sophomore"
    })
    b_login = requests.post(f"{BASE_URL}/auth/login", json={"email": buyer_email, "password": "password"}).json()
    buyer_token = b_login['data']['token']
    print("  Two test users created and logged in.")

    # Use seller token for initial setup
    token = seller_token

    # T4: profile + deposit
    print("\nT4: Profile and deposit")
    r = requests.get(f"{BASE_URL}/students/me", headers=get_headers())
    print(f"  GET /students/me -> {r.status_code} (expect 200)")
    r = requests.post(f"{BASE_URL}/students/me/deposit",
                      headers=get_headers(), json={"amount": 100.00})
    print(f"  POST /students/me/deposit $100 -> {r.status_code} (expect 200)")
    r = requests.post(f"{BASE_URL}/students/me/deposit",
                      headers=get_headers(), json={"amount": -50})
    print(f"  POST /students/me/deposit -$50 (invalid) -> {r.status_code} (expect 400)")

    # T5: browse
    print("\nT5: Browse sections and listings")
    r = requests.get(f"{BASE_URL}/sections/", headers=get_headers())
    print(f"  GET /sections -> {r.status_code} (expect 200)")
    r = requests.get(f"{BASE_URL}/sections/ticker", headers=get_headers())
    print(f"  GET /sections/ticker -> {r.status_code} (expect 200)")
    r = requests.get(f"{BASE_URL}/sections/departments", headers=get_headers())
    print(f"  GET /sections/departments -> {r.status_code} (expect 200)")
    r = requests.get(f"{BASE_URL}/listings/", headers=get_headers())
    print(f"  GET /listings -> {r.status_code} (expect 200)")

    # T6: create listing without enrollment (expect 400)
    print("\nT6: Create listing without enrollment (expect error)")
    r = requests.post(f"{BASE_URL}/listings/", headers=get_headers(),
                      json={"sectionId": 1, "minPrice": 25.00})
    print(f"  POST /listings (not enrolled) -> {r.status_code} (expect 400)")

    # T7: enrollments / bids / transactions (should be empty for new user)
    print("\nT7: Empty collections for new user")
    for path in ['/students/me/enrollments', '/students/me/bids',
                 '/students/me/listings', '/students/me/transactions',
                 '/students/me/account-history']:
        r = requests.get(f"{BASE_URL}{path}", headers=get_headers())
        print(f"  GET {path} -> {r.status_code} (expect 200)")

    # T8: notifications
    print("\nT8: Notifications")
    r = requests.get(f"{BASE_URL}/notifications/", headers=get_headers())
    print(f"  GET /notifications -> {r.status_code} (expect 200)")
    r = requests.post(f"{BASE_URL}/notifications/mark-read", headers=get_headers())
    print(f"  POST /notifications/mark-read -> {r.status_code} (expect 200)")

    # T9: place bid on nonexistent listing
    print("\nT9: Bid on nonexistent listing")
    r = requests.post(f"{BASE_URL}/bids/", headers=get_headers(),
                      json={"listingId": 99999, "amount": 50.00})
    print(f"  POST /bids (bad listingId) -> {r.status_code} (expect 404)")

    # T10: expire-all (no stale listings yet)
    print("\nT10: expire-all")
    r = requests.post(f"{BASE_URL}/listings/expire-all", headers=get_headers())
    print(f"  POST /listings/expire-all -> {r.status_code} (expect 200)")

    print("\n=== Tests complete! ===")
    print("(Full buy/sell flow requires two enrolled students — test manually via menu.)")


# ── Menu ──────────────────────────────────────────────────────────────────────

def print_menu():
    status = "logged in" if token else "not logged in"
    print(f"""
DartBid API Client  ({status})
─── Auth ──────────────────────────
 1. Register new account
 2. Login
─── My account ─────────────────────
 3. My profile + balance
 4. Deposit funds
 5. My enrollments
 6. My listings (seller dashboard)
 7. My bids
 8. My account history (ledger)
 9. My transactions
─── Browse ──────────────────────────
10. Browse sections
11. Section detail
12. Stock ticker
13. Browse listings
14. Listing detail
─── Actions ─────────────────────────
15. Create listing
16. Cancel listing
17. Place bid
18. Accept bid
─── Notifications ───────────────────
19. View notifications
20. Mark all read
─── Utilities ───────────────────────
 T. Run all tests
 L. Logout
 0. Exit""")


if __name__ == '__main__':
    while True:
        print_menu()
        choice = input("Choice: ").strip().upper()
        actions = {
            '1':  register,        '2':  login,
            '3':  my_profile,      '4':  deposit,
            '5':  my_enrollments,  '6':  my_listings,
            '7':  my_bids,         '8':  my_account_history,
            '9':  my_transactions,
            '10': browse_sections, '11': section_detail,
            '12': ticker,          '13': browse_listings,
            '14': listing_detail,
            '15': create_listing,  '16': cancel_listing,
            '17': place_bid,       '18': accept_bid,
            '19': my_notifications,'20': mark_notifications_read,
            'T':  run_all_tests,
        }
        if choice == '0':
            print("Goodbye!"); break
        elif choice == 'L':
            token = None; print("Logged out.")
        elif choice in actions:
            actions[choice]()
        else:
            print("Invalid choice.")
