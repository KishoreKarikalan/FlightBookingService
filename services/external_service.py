import httpx
import json
from typing import Dict, Any
from fastapi import HTTPException
import logging
from models.schemas import (
    AlternativeFlightData
)

from config.settings import EXTERNAL_API_URL, EXTERNAL_API_TIMEOUT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExternalService:
    """Service for communicating with external APIs"""
    
    def __init__(self, external_api_url: str = None, timeout: int = None):
        # Use configuration from settings
        self.external_api_url = external_api_url or EXTERNAL_API_URL
        self.timeout = timeout or EXTERNAL_API_TIMEOUT
    
    async def send_flight_alternatives(self, alternative_data: AlternativeFlightData) -> bool:
        """
        Send flight alternatives to external endpoint
        
        Args:
            alternative_data: Data containing cancelled flight info and alternatives
            
        Returns:
            bool: True if successful, False otherwise
        """

        print("\n\n\n\n Alternative Data: ", alternative_data, "\n\n\n\n")
        try:
            # Convert Pydantic model to dict for JSON serialization
            payload = alternative_data.model_dump()
            
            # Add additional metadata if needed
            payload["timestamp"] = alternative_data.__dict__.get("timestamp", "2025-08-12T00:00:00Z")
            payload["service"] = "flight_booking_api"
            
            logger.info(f"Sending flight alternatives for cancelled flight {alternative_data.cancelled_flight_id}")
            logger.debug(f"Payload: {json.dumps(payload, indent=2, default=str)}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.external_api_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Source": "flight_booking_api",
                        # Add authentication headers if needed
                        # "Authorization": f"Bearer {your_api_token}",
                    }
                )
                
                # Check if request was successful
                response.raise_for_status()
                
                logger.info(f"Successfully sent alternatives to external API. Response: {response.status_code}")
                return True
                
        except httpx.TimeoutException:
            logger.error(f"Timeout when sending alternatives to external API")
            return False
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error when sending alternatives: {e.response.status_code} - {e.response.text}")
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error when sending alternatives: {str(e)}")
            return False
    
    async def notify_flight_cancellation(self, flight_id: int, flight_date: str, reason: str) -> bool:
        """
        Send flight cancellation notification to external system
        
        Args:
            flight_id: The cancelled flight ID
            flight_date: Date of the cancelled flight
            reason: Cancellation reason
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            notification_url = f"{self.external_api_url.rstrip('/flight-alternatives')}/flight-cancellation"
            
            payload = {
                "flight_id": flight_id,
                "flight_date": flight_date,
                "reason": reason,
                "timestamp": "2025-08-12T00:00:00Z",
                "source": "flight_booking_api"
            }
            
            logger.info(f"Sending cancellation notification for flight {flight_id}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    notification_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Source": "flight_booking_api",
                    }
                )
                
                response.raise_for_status()
                logger.info(f"Successfully sent cancellation notification. Response: {response.status_code}")
                return True
                
        except Exception as e:
            logger.error(f"Error sending cancellation notification: {str(e)}")
            return False