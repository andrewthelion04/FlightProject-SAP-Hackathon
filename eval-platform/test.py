import requests

BASE_URL = "http://127.0.0.1:8080"
API_KEY = "7bcd6334-bc2e-4cbf-b9d4-61cb9e868869"  # schimbă cu cheia ta dacă e altă cheie

def headers(session_id=None):
    h = {"API-KEY": API_KEY, "Content-Type": "application/json"}
    if session_id:
        h["SESSION-ID"] = session_id
    return h

# start session
resp = requests.post(f"{BASE_URL}/api/v1/session/start", headers=headers(), timeout=10)
print("start:", resp.status_code, resp.text)
resp.raise_for_status()
session_id = resp.text.strip()

# play round cu payload minim valid (day/hour in interval, fără flightLoads)

payload = {
    "day": 0,
    "hour": 0,
    "flightLoads": [],
    "kitPurchasingOrders": {"first": 0, "business": 0, "premiumEconomy": 0, "economy": 0},
}
resp = requests.post(f"{BASE_URL}/api/v1/play/round", headers=headers(session_id), json=payload, timeout=10)
print("round:", resp.status_code, resp.text)

# end session
resp = requests.post(f"{BASE_URL}/api/v1/session/end", headers=headers(session_id), timeout=10)
print("end:", resp.status_code,resp.text)