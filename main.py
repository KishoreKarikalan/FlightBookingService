from fastapi import FastAPI
import uvicorn

from middleware.auth_middleware import FingerprintAuthMiddleware
from routers import flights, bookings
from config.settings import load_fingerprints

# Load allowed fingerprints
ALLOWED_FINGERPRINTS = load_fingerprints()
print(f"Loaded {len(ALLOWED_FINGERPRINTS)} allowed fingerprints")

# Initialize FastAPI app
app = FastAPI(title="Flight Booking API", version="1.0.0")

# Add middleware (commented out for development)
# app.add_middleware(FingerprintAuthMiddleware)

# Include routers
app.include_router(flights.router, prefix="/flights", tags=["flights"])
app.include_router(bookings.router, prefix="/booking", tags=["bookings"])

@app.get("/")
async def root():
    return {"message": "Flight Booking API is running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)