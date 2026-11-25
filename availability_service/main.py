from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3

app = FastAPI(title="Availability & Seat Service", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE = "availability.db"

class SeatActionRequest(BaseModel):
    showtime_id: int = Field(..., gt=0)
    seats: list[str] = Field(..., min_length=1)

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS showtimes (
            showtime_id INTEGER PRIMARY KEY,
            movie_title TEXT,
            hall_number TEXT,
            start_time TEXT,
            ticket_price REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seats (
            showtime_id INTEGER,
            seat_number TEXT,
            status TEXT,
            PRIMARY KEY (showtime_id, seat_number)
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM showtimes")
    if cursor.fetchone()[0] == 0:
        sample_showtimes = [
            (101, "Interstellar: Distributed Edition", "Hall 1", "2026-11-20 19:30", 18.00),
            (102, "The Microservice Matrix", "Hall 2", "2026-11-20 21:15", 20.00),
        ]
        cursor.executemany("INSERT INTO showtimes VALUES (?, ?, ?, ?, ?)", sample_showtimes)

        seat_labels = ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4"]
        for st_id, _, _, _, _ in sample_showtimes:
            for label in seat_labels:
                cursor.execute("INSERT INTO seats VALUES (?, ?, 'AVAILABLE')", (st_id, label))

    conn.commit()
    conn.close()

init_db()

# FR1: List available movies and showtimes
@app.get("/api/v1/showtimes")
def list_showtimes():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM showtimes")
    rows = cursor.fetchall()
    conn.close()
    return {
        "handled_by": "Availability Service (Port 8002)",
        "showtimes": [dict(row) for row in rows]
    }

# FR2 & NFR5: Display seat map (AVAILABLE, LOCKED, BOOKED)
@app.get("/api/v1/availability/{showtime_id}")
def check_availability(showtime_id: int):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT seat_number, status FROM seats WHERE showtime_id = ? ORDER BY seat_number", (showtime_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="Showtime not found")

    return {
        "handled_by": "Availability Service (Port 8002)",
        "showtime_id": showtime_id,
        "seats": [{"seat_number": row["seat_number"], "status": row["status"]} for row in rows]
    }

# FR3 & FR4: Lock selected seats during checkout
@app.post("/api/v1/availability/lock")
def lock_seats(payload: SeatActionRequest):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE")
        for seat in payload.seats:
            cursor.execute(
                "SELECT status FROM seats WHERE showtime_id = ? AND seat_number = ?",
                (payload.showtime_id, seat)
            )
            row = cursor.fetchone()
            if not row or row["status"] != "AVAILABLE":
                conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Seat {seat} is currently {row['status'] if row else 'INVALID'} and cannot be locked."
                )

        for seat in payload.seats:
            cursor.execute(
                "UPDATE seats SET status = 'LOCKED' WHERE showtime_id = ? AND seat_number = ?",
                (payload.showtime_id, seat)
            )
        conn.commit()
    except HTTPException:
        raise
    finally:
        conn.close()

    return {
        "handled_by": "Availability Service (Port 8002)",
        "status": "LOCKED",
        "showtime_id": payload.showtime_id,
        "seats": payload.seats
    }

# FR6 & NFR1: Confirm seats from AVAILABLE or LOCKED -> BOOKED atomically
@app.post("/api/v1/availability/confirm")
def confirm_seats(payload: SeatActionRequest):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE")
        for seat in payload.seats:
            cursor.execute(
                "SELECT status FROM seats WHERE showtime_id = ? AND seat_number = ?",
                (payload.showtime_id, seat)
            )
            row = cursor.fetchone()
            if not row or row["status"] == "BOOKED":
                conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Conflict: Seat {seat} is already BOOKED or invalid."
                )

        for seat in payload.seats:
            cursor.execute(
                "UPDATE seats SET status = 'BOOKED' WHERE showtime_id = ? AND seat_number = ?",
                (payload.showtime_id, seat)
            )
        conn.commit()
    except HTTPException:
        raise
    finally:
        conn.close()

    return {
        "handled_by": "Availability Service (Port 8002)",
        "status": "BOOKED",
        "showtime_id": payload.showtime_id,
        "seats": payload.seats
    }

# Release locked seats if checkout is cancelled or fails
@app.post("/api/v1/availability/release")
def release_seats(payload: SeatActionRequest):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    for seat in payload.seats:
        cursor.execute(
            "UPDATE seats SET status = 'AVAILABLE' WHERE showtime_id = ? AND seat_number = ? AND status = 'LOCKED'",
            (payload.showtime_id, seat)
        )
    conn.commit()
    conn.close()
    return {"handled_by": "Availability Service (Port 8002)", "status": "RELEASED", "seats": payload.seats}