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


def release_seats_best_effort(showtime_id: int, seats: list[str]):
    """Compensating action to revert confirmed seats if payment or booking fails."""
    try:
        httpx.post(
            f"{AVAILABILITY_SERVICE_URL}/api/v1/availability/release",
            json={"showtime_id": showtime_id, "seats": seats},
            timeout=5.0,
        )
    except httpx.RequestError:
        pass


# FR5, FR7, FR8, NFR1, NFR2, NFR4: Create booking, coordinate payment/seats/receipt
@app.post("/api/v1/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(payload: BookingRequest, idempotency_key: str = Header(None)):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is missing")

    clean_email = payload.customer_email.strip().lower()
    if "@" not in clean_email:
        raise HTTPException(status_code=400, detail="Invalid customer email format")

    clean_seats = [s.strip().upper() for s in payload.seats if s.strip()]
    if not clean_seats:
        raise HTTPException(status_code=400, detail="At least one valid seat is required")

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # NFR2: Idempotency check so retried requests return the original booking
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
            "message": "Duplicate request detected (Idempotency matched)",
        }

    # Step 1: Confirm seats as BOOKED on Availability Service (Port 8002)
    try:
        avail_res = httpx.post(
            f"{AVAILABILITY_SERVICE_URL}/api/v1/availability/confirm",
            json={"showtime_id": payload.showtime_id, "seats": clean_seats},
            timeout=5.0,
        )
        if avail_res.status_code != 200:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=avail_res.json().get("detail", "Seat booking conflict."),
            )
    except httpx.RequestError:
        conn.close()
        raise HTTPException(status_code=503, detail="Availability Service (8002) is offline.")

    # Step 2: Process payment on Payment Service (Port 8004); revert seats if it fails
    try:
        pay_res = httpx.post(
            f"{PAYMENT_SERVICE_URL}/api/v1/payments",
            json={
                "customer_email": clean_email,
                "showtime_id": payload.showtime_id,
                "seats": clean_seats,
                "amount": payload.total_price,
                "payment_method": payload.payment_method,
            },
            timeout=5.0,
        )
        if pay_res.status_code not in (200, 201):
            release_seats_best_effort(payload.showtime_id, clean_seats)
            conn.close()
            raise HTTPException(
                status_code=402,
                detail=pay_res.json().get("detail", "Payment failed; seats released."),
            )
        payment_id = pay_res.json().get("payment_id", f"PAY-{uuid.uuid4().hex[:6].upper()}")
    except httpx.RequestError:
        release_seats_best_effort(payload.showtime_id, clean_seats)
        conn.close()
        raise HTTPException(
            status_code=503,
            detail="Payment Service (8004) is offline; seats released.",
        )

    # Step 3: Prepare booking & receipt metadata
    booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
    seats_str = ",".join(clean_seats)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    receipt_status = "SENT_VIA_EMAIL"

    # Step 4: Call Notification Service (Port 8003) with partial-failure resilience
    try:
        notify_res = httpx.post(
            f"{NOTIFICATION_SERVICE_URL}/api/v1/notify",
            json={
                "booking_id": booking_id,
                "customer_email": clean_email,
                "status": "CONFIRMED",
                "showtime_id": payload.showtime_id,
                "seats": clean_seats,
                "total_amount": payload.total_price,
                "payment_id": payment_id,
            },
            timeout=3.0,
        )
        if notify_res.status_code != 200:
            receipt_status = "QUEUED_NOTIFICATION_ERROR"
    except httpx.RequestError:
        receipt_status = "QUEUED_NOTIFICATION_OFFLINE"

    # Step 5: Persist confirmed booking in booking.db
    cursor.execute(
        """
        INSERT INTO bookings (
            booking_id, idempotency_key, customer_email, showtime_id,
            seats, total_amount, payment_id, status, receipt_status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            booking_id,
            idempotency_key,
            clean_email,
            payload.showtime_id,
            seats_str,
            payload.total_price,
            payment_id,
            "CONFIRMED",
            receipt_status,
            created_at,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "handled_by": "Booking Service (Port 8001)",
        "booking_id": booking_id,
        "status": "CONFIRMED",
        "customer_email": clean_email,
        "showtime_id": payload.showtime_id,
        "seats": clean_seats,
        "total_amount": payload.total_price,
        "payment_id": payment_id,
        "receipt_status": receipt_status,
        "created_at": created_at,
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
        cursor.execute(
            "SELECT * FROM bookings WHERE LOWER(customer_email) = ? ORDER BY created_at DESC",
            (email.strip().lower(),),
        )
    else:
        cursor.execute("SELECT * FROM bookings ORDER BY created_at DESC LIMIT 20")

    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        item = dict(r)
        item["seats"] = item["seats"].split(",") if item["seats"] else []
        results.append(item)

    return {
        "handled_by": "Booking & History Service (Port 8001)",
        "count": len(results),
        "bookings": results,
    }


# FR11: Cancel an existing booking and release seats on Availability Service (:8002)
@app.post("/api/v1/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str):
    clean_id = booking_id.strip().upper()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM bookings WHERE booking_id = ?", (clean_id,))
    booking = cursor.fetchone()

    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found")

    # Idempotent cancel: already cancelled bookings return cleanly without re-releasing
    if booking["status"] == "CANCELLED":
        conn.close()
        return {
            "handled_by": "Booking Service (Port 8001)",
            "booking_id": clean_id,
            "status": "CANCELLED",
            "message": "Booking is already cancelled",
        }

    seats_list = [s for s in booking["seats"].split(",") if s]

    # Step 1: Release seats back to AVAILABLE on Availability Service (Port 8002)
    try:
        release_res = httpx.post(
            f"{AVAILABILITY_SERVICE_URL}/api/v1/availability/release",
            json={"showtime_id": booking["showtime_id"], "seats": seats_list},
            timeout=5.0,
        )
        if release_res.status_code != 200:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="Failed to release seats on Availability Service",
            )
    except httpx.RequestError:
        conn.close()
        raise HTTPException(status_code=503, detail="Availability Service (8002) is offline.")

    # Step 2: Update booking status to CANCELLED in booking.db
    cursor.execute("UPDATE bookings SET status = ? WHERE booking_id = ?", ("CANCELLED", clean_id))
    conn.commit()
    conn.close()

    return {
        "handled_by": "Booking Service (Port 8001)",
        "booking_id": clean_id,
        "status": "CANCELLED",
        "released_seats": seats_list,
        "message": "Booking cancelled and seats released",
    }