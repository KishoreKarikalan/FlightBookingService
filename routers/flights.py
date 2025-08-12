from fastapi import APIRouter, HTTPException
from typing import List
from datetime import datetime, date, time

from models.schemas import (
    FlightSearchRequest, FlightResult, FlightResultAll, 
    ConnectingFlightResult, FlightCancellationRequest, FlightCancellationResponse
)
from database.connection import get_db_connection, get_airports_by_city_name
from services.flight_service import FlightService

router = APIRouter()
flight_service = FlightService()

@router.post("/internal-search")
async def search_internal_flight(request: FlightSearchRequest):
    """
    Search for a single internal (domestic) flight using city names.
    Returns one flight with full departure and arrival datetime, matching booking endpoint style.
    """
    return await flight_service.search_internal_flight(request)

@router.post("/search", response_model=List[ConnectingFlightResult])
async def search_all_flights(request: FlightSearchRequest):
    """Search for all flights (direct + connecting) based on the request"""
    return await flight_service.search_all_flights(request)

@router.post("/search-direct", response_model=List[ConnectingFlightResult])
async def search_flights(request: FlightSearchRequest):
    """Search for direct flights only"""
    return await flight_service.search_direct_flights(request)

@router.post("/search-connecting", response_model=List[ConnectingFlightResult])
async def search_connecting_flights(request: FlightSearchRequest):
    """Search for connecting flights only"""
    return await flight_service.search_connecting_flights(request)

@router.get("/all", response_model=List[FlightResultAll])
async def get_all_flights():
    """Retrieve all available and active flight instances"""
    return await flight_service.get_all_flights()

@router.post("/cancel", response_model=FlightCancellationResponse)
async def cancel_flight(request: FlightCancellationRequest):
    """Cancel an entire flight and send alternatives to external endpoint"""
    return await flight_service.cancel_flight(request)