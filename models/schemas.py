from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date, time

# Flight Search Models
class FlightSearchRequest(BaseModel):
    source_city: str = Field(..., description="Source city name")
    destination_city: str = Field(..., description="Destination city name") 
    travel_datetime: datetime
    seats_required: int = Field(..., gt=0, description="Number of seats required")
    limit: int = Field(5, ge=1, description="Maximum number of results to return")

class FlightResult(BaseModel):
    flight_id: int
    airline_name: str
    flight_number: str
    source_airport: str
    destination_airport: str
    source_city: str
    destination_city: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    base_price: float
    available_seats: int

class FlightResultAll(BaseModel):
    flight_id: int
    airline_name: str
    flight_number: str
    source_airport: str
    destination_airport: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    base_price: float
    arrival_day_offset: int
    available_seats: int

class ConnectingFlightResult(BaseModel):
    total_duration_minutes: int
    total_price: float
    flights: List[FlightResult]

# Booking Models
class PassengerDetail(BaseModel):
    name: str = Field(..., description="Passenger's full name")
    age: int = Field(..., gt=0, description="Passenger's age")
    gender: str = Field(..., pattern="^(M|F|O)$", description="Gender: M, F, or O")
    passport_no: str = Field(..., description="Passport number")

class BookingRequest(BaseModel):
    flight_id: int = Field(..., description="Flight ID to book")
    seats_required: int = Field(..., gt=0, description="Number of seats to book")
    travel_date: str = Field(..., description="Date of travel (YYYY-MM-DD)")
    passenger_details: List[PassengerDetail] = Field(..., description="List of passenger details")

class BookingResponse(BaseModel):
    booking_id: int
    status: str
    total_price: float
    message: str

class BookingPassenger(BaseModel):
    name: str
    age: int
    gender: str
    passport_no: str

class BookingDetailResponse(BaseModel):
    booking_id: int
    flight_id: int
    flight_number: str
    airline_name: str
    source_airport_code: str
    source_airport_name: str
    source_city_name: str
    destination_airport_code: str
    destination_airport_name: str
    destination_city_name: str
    status: str
    total_price: float
    passenger_count: int
    passengers: Optional[List[BookingPassenger]] = None
    departure_time: datetime
    arrival_time: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M")
        }