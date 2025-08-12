from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from config.settings import load_fingerprints

# Load allowed fingerprints
ALLOWED_FINGERPRINTS = load_fingerprints()

class FingerprintAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to authenticate requests using client certificate fingerprints"""
    
    async def dispatch(self, request: Request, call_next):
        # Get client certificate fingerprint from Nginx
        client_cert_fingerprint = request.headers.get("x-client-cert-fingerprint")
        
        print(f"Received fingerprint: {client_cert_fingerprint}")
        print(f"Request headers: {dict(request.headers)}")
        
        # Check if fingerprint header is present
        if not client_cert_fingerprint:
            print("No client certificate fingerprint provided")
            return JSONResponse(
                status_code=403,
                content={"detail": "No client certificate fingerprint provided"}
            )
        
        # Check if fingerprint is in allowed list
        if client_cert_fingerprint not in ALLOWED_FINGERPRINTS:
            print(f"Fingerprint {client_cert_fingerprint} not in allowed list")
            print(f"Allowed fingerprints: {ALLOWED_FINGERPRINTS}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid certificate fingerprint"}
            )
        
        print(f"Fingerprint {client_cert_fingerprint} validated successfully")
        
        try:
            response = await call_next(request)
            return response
        except StarletteHTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail}
            )
        except Exception as exc:
            print(f"Unexpected error: {exc}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )