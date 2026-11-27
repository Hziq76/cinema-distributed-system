from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3
import uuid
from datetime import datetime

app = FastAPI(title="Payment Service", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE = "payment.db"


class PaymentRequest(BaseModel):
    customer_email: str
    showtime_id: int
    seats: list[str]
    amount: float = Field(..., gt=0)
    payment_method: str = "Card / FPX Online"


class RefundRequest(BaseModel):
    payment_id: str | None = None
    customer_email: str | None = None
    showtime_id: int | None = None
    seats: list[str] | None = None


def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            customer_email TEXT,
            showtime_id INTEGER,
            seats TEXT,
            amount REAL,
            payment_method TEXT,
            status TEXT,
            paid_at TEXT,
            refunded_at TEXT
        )
    """)
    # Safely add refunded_at if upgrading an existing payment.db created with v1.0
    cursor.execute("PRAGMA table_info(payments)")
    columns = [col[1] for col in cursor.fetchall()]
    if "refunded_at" not in columns:
        cursor.execute("ALTER TABLE payments ADD COLUMN refunded_at TEXT")
    conn.commit()
    conn.close()


init_db()


# FR7: Process and send payment details
@app.post("/api/v1/payments")
def process_payment(payload: PaymentRequest):
    payment_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
    paid_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seats_str = ",".join(s.strip().upper() for s in payload.seats)

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO payments (
            payment_id, customer_email, showtime_id, seats,
            amount, payment_method, status, paid_at, refunded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
    """, (
        payment_id,
        payload.customer_email.strip().lower(),
        payload.showtime_id,
        seats_str,
        payload.amount,
        payload.payment_method,
        "PAID",
        paid_at,
    ))
    conn.commit()
    conn.close()

    return {
        "handled_by": "Payment Service (Port 8004)",
        "payment_id": payment_id,
        "status": "PAID",
        "amount": payload.amount,
        "payment_method": payload.payment_method,
        "paid_at": paid_at,
    }


# Compensating action: Refund payment when a booking is cancelled
@app.post("/api/v1/payments/refund")
def refund_payment(payload: RefundRequest):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    row = None
    if payload.payment_id:
        cursor.execute(
            "SELECT * FROM payments WHERE payment_id = ?",
            (payload.payment_id.strip().upper(),),
        )
        row = cursor.fetchone()
    elif payload.customer_email and payload.showtime_id is not None:
        seats_str = ",".join(s.strip().upper() for s in (payload.seats or []))
        cursor.execute(
            """
            SELECT * FROM payments
            WHERE LOWER(customer_email) = ? AND showtime_id = ? AND seats = ?
            ORDER BY paid_at DESC LIMIT 1
            """,
            (payload.customer_email.strip().lower(), payload.showtime_id, seats_str),
        )
        row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Payment record not found")

    if row["status"] == "REFUNDED":
        conn.close()
        return {
            "handled_by": "Payment Service (Port 8004)",
            "payment_id": row["payment_id"],
            "status": "REFUNDED",
            "amount": row["amount"],
            "refunded_at": row["refunded_at"],
            "message": "Payment already refunded",
        }

    refunded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE payments SET status = ?, refunded_at = ? WHERE payment_id = ?",
        ("REFUNDED", refunded_at, row["payment_id"]),
    )
    conn.commit()
    conn.close()

    return {
        "handled_by": "Payment Service (Port 8004)",
        "payment_id": row["payment_id"],
        "status": "REFUNDED",
        "amount": row["amount"],
        "refunded_at": refunded_at,
        "message": "Payment refunded for cancelled booking",
    }


@app.get("/api/v1/payments")
def list_payments(payment_id: str | None = Query(None)):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if payment_id:
        cursor.execute(
            "SELECT * FROM payments WHERE payment_id = ?",
            (payment_id.strip().upper(),),
        )
    else:
        cursor.execute("SELECT * FROM payments ORDER BY paid_at DESC LIMIT 20")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {
        "handled_by": "Payment Service (Port 8004)",
        "count": len(rows),
        "payments": rows,
    }