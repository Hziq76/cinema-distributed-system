from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3
import uuid
from datetime import datetime

app = FastAPI(title="Payment Service", version="1.0")

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
            paid_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# FR7: Process and send payment details
@app.post("/api/v1/payments")
def process_payment(payload: PaymentRequest):
    payment_id = f"PAY-{uuid.uuid4().hex[:6].upper()}"
    paid_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seats_str = ",".join(payload.seats)

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO payments (payment_id, customer_email, showtime_id, seats, amount, payment_method, status, paid_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (payment_id, payload.customer_email, payload.showtime_id, seats_str, payload.amount, payload.payment_method, "PAID", paid_at))
    conn.commit()
    conn.close()

    return {
        "handled_by": "Payment Service (Port 8004)",
        "payment_id": payment_id,
        "status": "PAID",
        "amount": payload.amount,
        "payment_method": payload.payment_method,
        "paid_at": paid_at
    }