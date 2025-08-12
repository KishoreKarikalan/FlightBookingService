from fastapi import APIRouter, HTTPException
from models.schemas import BookingRequest, BookingResponse, BookingDetailResponse
from services.booking_service import BookingService

router = APIRouter()
booking_service = BookingService()

@router.post("/book", response_model=BookingResponse)
async def book_flight(request: BookingRequest):
    """Book a flight with passenger details"""
    return await booking_service.book_flight(request)

@router.get("/{booking_id}", response_model=BookingDetailResponse)
async def get_booking_details(booking_id: int):
    """Get full booking details including passenger list and airport/city information"""
    return await booking_service.get_booking_details(booking_id)