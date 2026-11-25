# Distributed Cinema Booking System

A multi-service distributed cinema ticket booking demo built with **FastAPI** microservices, **SQLite** databases per service, and a browser-based frontend (`index.html`).

## Architecture & Microservices

| Service | Port | SQLite Database | Core Responsibilities (`FR1`–`FR10`) |
| :--- | :--- | :--- | :--- |
| **Booking Service** | `8001` | `booking.db` | Creates bookings (`FR5`), handles `Idempotency-Key` duplicate protection, coordinates payment and email receipts (`FR7`), and serves booking history/receipts (`FR8`, `FR10`) |
| **Availability Service** | `8002` | `availability.db` | Lists showtimes (`FR1`), returns seat maps (`FR2`), and locks selected seats (`FR4`) |
| **Notification Service** | `8003` | `notification.db` | Records and serves email receipt notification logs (`FR9`) |
| **Payment Service** | `8004` | `payment.db` | Processes booking payment transactions (`FR7`) |
| **Frontend Demo UI** | `5500` (HTTP server) | — | Step-by-step browser client (`index.html`) showing port-level requests, responses, and receipts |

---

## Data Design (Isolated Databases)

- **Availability DB (`availability.db`, `:8002`):** `SHOWTIMES` (`showtime_id`, `movie_title`, `hall_number`, `start_time`, `ticket_price`) and `SEATS` (`seat_id`, `showtime_id`, `seat_number`, `status`: `AVAILABLE` | `LOCKED` | `BOOKED`).
- **Booking DB (`booking.db`, `:8001`):** `BOOKINGS` (`booking_id`, `customer_email`, `showtime_id`, `seats_booked`, `total_amount`, `payment_id`, `status`, `receipt_status`, `created_at`) and `IDEMPOTENCY_LOGS` (`key_id`, `request_hash`, `response_body`, `created_at`).
- **Payment DB (`payment.db`, `:8004`):** `PAYMENTS` (`payment_id`, `booking_id`, `amount`, `payment_method`, `status`, `created_at`).
- **Notification DB (`notification.db`, `:8003`):** `NOTIFICATIONS` (`notification_id`, `booking_id`, `customer_email`, `message`, `status`, `sent_at`).

---

## Running the System Locally

### 1. Start Each Microservice (Separate Terminals)

Run each command inside its respective service folder (`booking_service`, `availability_service`, `notification_service`, `payment_service`):

```bash
# Terminal 1 — Booking Service (:8001)
uvicorn main:app --port 8001 --reload

# Terminal 2 — Availability Service (:8002)
uvicorn main:app --port 8002 --reload

# Terminal 3 — Notification Service (:8003)
uvicorn main:app --port 8003 --reload

# Terminal 4 — Payment Service (:8004)
uvicorn main:app --port 8004 --reload


2. Serve the Frontend Demo (index.html)
In a separate terminal inside the client_app

python -m http.server 5500

Open http://127.0.0.1:5500/index.html in your browser and press Ctrl + Shift + R if you need to force-refresh after changes.

Demo Flow & Key Endpoints
Step 1 — Movies & Showtimes (FR1): GET http://127.0.0.1:8002/api/v1/showtimes
Step 2 — Seat Map & Lock (FR2, FR4):GET http://127.0.0.1:8002/api/v1/availability/{showtime_id}POST http://127.0.0.1:8002/api/v1/availability/lock
Step 3 — Checkout & Payment (FR5, FR7):POST http://127.0.0.1:8001/api/v1/bookings with header Idempotency-Key: <unique-key>Stays on Step 3 after submission so you can inspect the receipt card, the 201 Created JSON trace, or jump manually to Step 4.   
Step 4 — History & Receipts (FR8–FR10):GET http://127.0.0.1:8001/api/v1/bookingsGET http://127.0.0.1:8003/api/v1/notifications

Sample Successful Booking Response (201 Created)

{
  "handled_by": "Booking Service (Port 8001)",
  "booking_id": "BK-902830",
  "status": "CONFIRMED",
  "customer_email": "haziq@example.com",
  "showtime_id": 101,
  "seats": [
    "A2"
  ],
  "total_amount": 18,
  "payment_id": "PAY-902200",
  "receipt_status": "SENT_VIA_EMAIL",
  "created_at": "2026-11-21 15:51:03"
}

Resetting Seat State for a Fresh Demo
1. Stop all four uvicorn processes with Ctrl + C.

2. Delete or back up the SQLite .db files (availability.db, booking.db, payment.db, notification.db).

3. Restart all four uvicorn services so tables and initial AVAILABLE seats are re-seeded, then refresh the browser.