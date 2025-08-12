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

def load_fingerprints(path: str = "allowed_fingerprints.json") -> set:
    """Load allowed fingerprints from JSON file"""
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return set(data.get("fingerprints", []))
    except FileNotFoundError:
        print(f"Warning: {path} not found. Creating empty fingerprint set.")
        return set()