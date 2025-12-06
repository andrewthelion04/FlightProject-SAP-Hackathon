"""Configuration values for the rotables optimizer client."""
import os

# API connectivity
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8080")
API_KEY = os.getenv("API_KEY", "7bcd6334-bc2e-4cbf-b9d4-61cb9e868869")

# CSV parsing
CSV_DELIMITER = ";"

# Strategy thresholds
BUFFER_PASSENGERS = 5
MIN_STOCK_THRESHOLD = 50
CARGO_TOPUP = 20
