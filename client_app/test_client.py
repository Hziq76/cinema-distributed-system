import time
import httpx

BOOKING_URL = "http://127.0.0.1:8001/api/v1/bookings"
SEARCH_URL = "http://127.0.0.1:8001/api/v1/bookings"

def run_tests():
    print("--- STARTING DISTRIBUTED SYSTEM TEST CLIENT ---")

    payload = {
        "customer_email": "client_test@example.com",
        "showtime_id": 101,
        "seats": ["A1"],
        "total_price": 18.00,
        "payment_method": "Card / FPX Online"
    }

    # 1. Test a fresh booking with a unique Idempotency Key
    unique_key = f"client-test-{int(time.time())}"
    headers = {"Idempotency-Key": unique_key}

    print(f"\n[Test 1] Sending fresh booking request with key: {unique_key}")
    try:
        response = httpx.post(BOOKING_URL, json=payload, headers=headers, timeout=5.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.json()}")
    except Exception as e:
        print(f"Error connecting to Booking Service: {e}")

    # 2. Test Idempotency (Sending the exact same key again)
    print(f"\n[Test 2] Resending request with the *same* key to test Idempotency...")
    try:
        response = httpx.post(BOOKING_URL, json=payload, headers=headers, timeout=5.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

    # 3. Test Conflicting Booking (Trying to book already-taken seat A1 with a NEW key)
    conflict_key = f"client-test-conflict-{int(time.time())}"
    conflict_headers = {"Idempotency-Key": conflict_key}
    conflict_payload = {
        "customer_email": "second_customer@example.com",
        "showtime_id": 101,
        "seats": ["A1"],
        "total_price": 18.00,
        "payment_method": "Card / FPX Online"
    }

    print(f"\n[Test 3] Attempting to book already-taken seat 'A1' with a new key...")
    try:
        response = httpx.post(BOOKING_URL, json=conflict_payload, headers=conflict_headers, timeout=5.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

    # 4. Test Booking History / Receipt Lookup by email
    print(f"\n[Test 4] Searching booking history for client_test@example.com...")
    try:
        response = httpx.get(SEARCH_URL, params={"email": "client_test@example.com"}, timeout=5.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- TEST CLIENT COMPLETED ---")

if __name__ == "__main__":
    run_tests()