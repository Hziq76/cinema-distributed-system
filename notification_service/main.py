from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
from datetime import datetime

app = FastAPI(title="Notification Service", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE = "notification.db"

class NotifyRequest(BaseModel):
    booking_id: str
    customer_email: str = "customer@example.com"
    status: str
    showtime_id: int
    seats: list[str]
    total_amount: float
    payment_id: str = "N/A"

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id TEXT,
            customer_email TEXT,
            payment_id TEXT,
            message TEXT,
            sent_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# FR9: Send payment & ticket receipt via email (simulated & logged)
@app.post("/api/v1/notify")
def send_notification(payload: NotifyRequest):
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"Receipt Emailed to {payload.customer_email} | Booking {payload.booking_id} "
        f"| Payment {payload.payment_id} | Showtime {payload.showtime_id} "
        f"| Seats {', '.join(payload.seats)} | Paid RM {payload.total_amount:.2f}"
    )
    print(f"[EMAIL RECEIPT] {msg}")

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO notifications (booking_id, customer_email, payment_id, message, sent_at) VALUES (?, ?, ?, ?, ?)",
        (payload.booking_id, payload.customer_email, payload.payment_id, msg, sent_at)
    )
    conn.commit()
    conn.close()

    return {
        "handled_by": "Notification Service (Port 8003)",
        "status": "EMAIL_SENT",
        "booking_id": payload.booking_id,
        "sent_at": sent_at
    }

@app.get("/api/v1/notifications")
def list_notifications():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 20")
    rows = cursor.fetchall()
    conn.close()
    return {
        "handled_by": "Notification Service (Port 8003)",
        "notifications": [dict(r) for r in rows]
    }