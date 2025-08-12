import json
import os

# Database connection string
DATABASE_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=LAPTOP-5JTDUHDE\\MSSQLSERVER01;"
    "DATABASE=Airplane_Booking;"
    "Trusted_Connection=yes;"
    "Encrypt=no;"
)

# External API settings
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "https://api.example.com/flight-alternatives")
EXTERNAL_API_TIMEOUT = int(os.getenv("EXTERNAL_API_TIMEOUT", "30"))

def load_fingerprints(path: str = "allowed_fingerprints.json") -> set:
    """Load allowed fingerprints from JSON file"""
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return set(data.get("fingerprints", []))
    except FileNotFoundError:
        print(f"Warning: {path} not found. Creating empty fingerprint set.")
        return set()