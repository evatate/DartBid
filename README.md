# DartBid Flask API

**DartBid** — a transactional marketplace for Dartmouth course enrollment spots.  
CS 61 Final Project · Caroline Chung, Giselle Wu, Eva Tate, Helen Cui

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 4. Start server
flask --app app.py run --port 8080

# 5. Test with the interactive client
python3 call_api.py

# Or test with Postman at http://localhost:8080/api/
```

---

## Authentication

All routes except `/api/auth/register` and `/api/auth/login` require:
```
Authorization: Bearer <token>
```
Token is returned on register and login. Expires after 2 hours.

---

## API Reference

### Auth
| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | `{name, email, password, yearStanding, major?}` | Create account, returns token |
| `POST` | `/api/auth/login` | `{email, password}` | Login, returns token |

### My Account (authenticated student only)
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/students/me` | Profile + balance |
| `POST` | `/api/students/me/deposit` | Add funds `{amount}` |
| `GET` | `/api/students/me/enrollments` | Currently enrolled sections |
| `GET` | `/api/students/me/listings` | Seller dashboard — all listings + bids |
| `GET` | `/api/students/me/bids` | All bids placed as buyer |
| `GET` | `/api/students/me/account-history` | Full ledger (deposits, holds, refunds, payouts) |
| `GET` | `/api/students/me/transactions` | Completed transactions as buyer or seller |

### Listings
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/listings/` | Browse active listings |
| `POST` | `/api/listings/` | Create listing `{sectionId, minPrice, expiresAt?}` |
| `GET` | `/api/listings/<id>` | Detail + bids (anonymous) + price history |
| `POST` | `/api/listings/<id>/cancel` | Cancel own listing, refunds all bids |
| `POST` | `/api/listings/expire-all` | Expire stale listings (call from cron) |

**GET /api/listings/** query params: `department`, `distributive`, `professor`, `minPrice`, `maxPrice`, `search`

### Bids
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/bids/` | Place bid `{listingId, amount}` — funds held immediately |
| `POST` | `/api/bids/<id>/accept` | Accept bid → full atomic transaction |

**accept_bid** atomically: creates transaction, transfers enrollment, pays seller, refunds losing bidders, closes listing, appends price history, sends notifications, writes audit log. Full rollback on any failure.

### Sections
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sections/` | Browse sections (filters: `department`, `distributive`, `termId`) |
| `GET` | `/api/sections/ticker` | Stock ticker — price movements on active listings |
| `GET` | `/api/sections/departments` | All departments (for dropdowns) |
| `GET` | `/api/sections/distributives` | All distributives (for dropdowns) |
| `GET` | `/api/sections/<id>` | Detail + active listing + full price history |

### Notifications
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/notifications/` | Own notifications, unread first |
| `POST` | `/api/notifications/mark-read` | Mark all as read |

---

## Business Rules Enforced

| Rule | Where |
|------|-------|
| Seller must be enrolled to list | `POST /listings/` |
| One active listing per seller per section | `POST /listings/` |
| Listing only during add/drop window | `POST /listings/` |
| expiresAt capped to term.addDropEnd | `POST /listings/` |
| First bid ≥ minPrice; each subsequent > highest by $0.01 | `POST /bids/` |
| Buyer cannot bid on own listing | `POST /bids/` |
| One active bid per buyer per listing | `POST /bids/` |
| Buyer not already enrolled in section | `POST /bids/` |
| Balance sufficient before bid (held immediately) | `POST /bids/` |
| Balance cannot go negative | `POST /bids/` |
| Enrollment cap never exceeded | `POST /bids/<id>/accept` |
| Full rollback if any transaction step fails | `POST /bids/<id>/accept` |
| Seller anonymity (sellerId never in public responses) | `/listings/` browse |
| Buyer anonymity (buyerId never in bid lists) | all bid responses |
| Price history append-only (no update/delete endpoint) | schema + no route |
| Automatic listing expiry + bid refunds | `POST /listings/expire-all` |

---

## Schema Notes

- `priceHistory` has no `sectionId` — queries join via `priceHistory → transaction → listing → section`
- `section.currentEnrollment` is denormalized and recomputed on every accepted bid
- `accountTransaction.balanceAfter` is a denormalized snapshot (not recomputed from sum)
- `transaction` is a reserved word in MySQL — always quoted as `` `transaction` `` in queries
