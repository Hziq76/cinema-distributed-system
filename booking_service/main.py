from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3
import uuid
import httpx
from datetime import datetime

app = FastAPI(title="Booking & History Service", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE = "booking.db"
AVAILABILITY_SERVICE_URL = "http://127.0.0.1:8002"
NOTIFICATION_SERVICE_URL = "http://127.0.0.1:8003"
PAYMENT_SERVICE_URL = "http://127.0.0.1:8004"

class BookingRequest(BaseModel):
    customer_email: str = Field(..., min_length=5)
    showtime_id: int = Field(..., gt=0)
    seats: list[str] = Field(..., min_length=1)
    total_price: float = Field(..., gt=0)
    payment_method: str = "Card / FPX Online"

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            customer_email TEXT,
            showtime_id INTEGER,
            seats TEXT,
            total_amount REAL,
            payment_id TEXT,
            status TEXT,
            receipt_status TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# FR5, FR7, FR8, NFR1, NFR2, NFR4: Create booking, coordinate payment/seats/receipt
@app.post("/api/v1/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(payload: BookingRequest, idempotency_key: str = Header(None)):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is missing")

    if "@" not in payload.customer_email:
        raise HTTPException(status_code=400, detail="Invalid customer email format")

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # NFR2: Idempotency check
    cursor.execute("SELECT * FROM bookings WHERE idempotency_key = ?", (idempotency_key,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return {
            "handled_by": "Booking Service (Port 8001)",
            "booking_id": existing["booking_id"],
            "status": existing["status"],
            "customer_email": existing["customer_email"],
            "showtime_id": existing["showtime_id"],
            "seats": existing["seats"].split(","),
            "total_amount": existing["total_amount"],
            "payment_id": existing["payment_id"],
            "receipt_status": existing["receipt_status"],
            "created_at": existing["created_at"],
            "message": "Duplicate request detected (Idempotency matched)"
        }

    # Step 1: Confirm seats as BOOKED on Availability Service (Port 8002)
    try:
        avail_res = httpx.post(
            f"{AVAILABILITY_SERVICE_URL}/api/v1/availability/confirm",
            json={"showtime_id": payload.showtime_id, "seats": payload.seats},
            timeout=5.0
        )
        if avail_res.status_code != 200:
            conn.close()
            raise HTTPException(status_code=400, detail=avail_res.json().get("detail", "Seat booking conflict."))
    except httpx.RequestError:
        conn.close()
        raise HTTPException(status_code=503, detail="Availability Service (8002) is offline.")

    # Step 2: Process payment on Payment Service (Port 8004)
    payment_id = "PAY-PENDING"
    try:
        pay_res = httpx.post(
            f"{PAYMENT_SERVICE_URL}/api/v1/payments",
            json={
                "customer_email": payload.customer_email,
                "showtime_id": payload.showtime_id,
                "seats": payload.seats,
                "amount": payload.total_price,
                "payment_method": payload.payment_method
            },
            timeout=5.0
        )
        if pay_res.status_code == 200:
            payment_id = pay_res.json().get("payment_id", "PAY-OK")
    except httpx.RequestError:
        conn.close()
        raise HTTPException(status_code=503, detail="Payment Service (8004) is offline.")

    # Step 3: Save booking & ticket receipt record (FR5, FR8, NFR6)
    booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
    seats_str = ",".join(payload.seats)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    receipt_status = "SENT_VIA_EMAIL"

    # Step 4: Call Notification Service (Port 8003) with NFR4 partial-failure resilience
    try:
        notify_res = httpx.post(
            f"{NOTIFICATION_SERVICE_URL}/api/v1/notify",
            json={
                "booking_id": booking_id,
                "customer_email": payload.customer_email,
                "status": "CONFIRMED",
                "showtime_id": payload.showtime_id,
                "seats": payload.seats,
                "total_amount": payload.total_price,
                "payment_id": payment_id
            },
            timeout=3.0
        )
        if notify_res.status_code != 200:
            receipt_status = "QUEUED_NOTIFICATION_ERROR"
    except httpx.RequestError:
        receipt_status = "QUEUED_NOTIFICATION_OFFLINE"

    cursor.execute("""
        INSERT INTO bookings (booking_id, idempotency_key, customer_email, showtime_id, seats, total_amount, payment_id, status, receipt_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (booking_id, idempotency_key, payload.customer_email, payload.showtime_id, seats_str, payload.total_price, payment_id, "CONFIRMED", receipt_status, created_at))
    conn.commit()
    conn.close()

    return {
        "handled_by": "Booking Service (Port 8001)",
        "booking_id": booking_id,
        "status": "CONFIRMED",
        "customer_email": payload.customer_email,
        "showtime_id": payload.showtime_id,
        "seats": payload.seats,
        "total_amount": payload.total_price,
        "payment_id": payment_id,
        "receipt_status": receipt_status,
        "created_at": created_at
    }

# FR8 & FR10: Search/track previous bookings and retrieve ticket receipt
@app.get("/api/v1/bookings")
def search_bookings(email: str = Query(None), booking_id: str = Query(None)):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if booking_id:
        cursor.execute("SELECT * FROM bookings WHERE booking_id = ?", (booking_id.strip().upper(),))
    elif email:
        cursor.execute("SELECT * FROM bookings WHERE customer_email = ? ORDER BY created_at DESC", (email.strip(),))
    else:
        cursor.execute("SELECT * FROM bookings ORDER BY created_at DESC LIMIT 20")

    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        item = dict(r)
        item["seats"] = item["seats"].split(",")
        results.append(item)

    return {
        "handled_by": "Booking & History Service (Port 8001)",
        "count": len(results),
        "bookings": results
    }