from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date, time
import pyodbc
from contextlib import contextmanager
import os
from dataclasses import dataclass

app = FastAPI(title="Flight Booking API", version="1.0.0")

class FlightSearchRequest(BaseModel):
    source_city: str = Field(..., description="Source city name")
    destination_city: str = Field(..., description="Destination city name") 
    travel_date: str = Field(..., description="Travel date")
    seats_required: int = Field(..., gt=0, description="Number of seats required")
    limit: int = Field(5, ge=1, description="Maximum number of results to return")

class FlightResult(BaseModel):
    flight_id: int
    airline_name: str
    flight_number: str
    source_airport: str
    destination_airport: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    base_price: float
    available_seats: int

class ConnectingFlightResult(BaseModel):
    total_duration_minutes: int
    total_price: float
    flights: List[FlightResult]

from typing import List
from pydantic import BaseModel, Field


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


# Database connection manager
@contextmanager
def get_db_connection():
    conn_str = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=LAPTOP-5JTDUHDE\\MSSQLSERVER01;"
    "DATABASE=Airplane_Booking;"
    "Trusted_Connection=yes;"
    "Encrypt=no;"
    )

    conn = None
    try:
        conn = pyodbc.connect(conn_str)
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")
    finally:
        if conn:
            conn.close()

# Helper functions
def get_airport_id_by_code(cursor, airport_code: str) -> Optional[int]:
    """Get airport ID by airport code (could be IATA or ICAO)"""
    query = """
    SELECT airport_id 
    FROM Airport 
    WHERE iata_code = ? OR icao_code = ?
    """
    cursor.execute(query, (airport_code, airport_code))
    result = cursor.fetchone()
    return result[0] if result else None

# API Endpoints

@app.get("/")
async def root():
    return {"message": "Flight Booking API is running"}

def get_airports_by_city_name(cursor, city_name: str):
    """
    Get all airport IDs for a given city name
    """
    query = """
    SELECT a.airport_id 
    FROM Airport a
    INNER JOIN City c ON a.city_id = c.city_id
    WHERE c.city_name = ? AND c.is_deleted = 0 AND a.is_deleted = 0
    """
    cursor.execute(query, (city_name,))
    return [row[0] for row in cursor.fetchall()]

from fastapi import HTTPException
from datetime import datetime
from typing import List

from fastapi import HTTPException
from typing import List
from datetime import datetime

from datetime import datetime
from typing import List
from fastapi import HTTPException

@app.post("/flights/internal-search")
async def search_internal_flight(request: FlightSearchRequest):
    """
    Search for a single internal (domestic) flight using city names.
    Returns one flight with full departure and arrival datetime, matching booking endpoint style.
    """
    try:
        parsed_date = datetime.strptime(request.travel_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid travel_date format. Use YYYY-MM-DD.")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get airport IDs by city
        source_airport_ids = get_airports_by_city_name(cursor, request.source_city)
        dest_airport_ids = get_airports_by_city_name(cursor, request.destination_city)

        if not source_airport_ids:
            raise HTTPException(status_code=404, detail=f"No airports found for source city: {request.source_city}")
        if not dest_airport_ids:
            raise HTTPException(status_code=404, detail=f"No airports found for destination city: {request.destination_city}")

        source_placeholders = ",".join(["?"] * len(source_airport_ids))
        dest_placeholders = ",".join(["?"] * len(dest_airport_ids))

        query = f"""
        SELECT TOP 1
            f.flight_id,
            a.airline_name,
            f.flight_number,
            src.iata_code AS source_airport,
            dest.iata_code AS destination_airport,
            f.departure_time,
            f.arrival_time,
            f.duration_minutes,
            f.base_price,
            CASE 
                WHEN fi.available_seats IS NOT NULL THEN fi.available_seats
                ELSE f.total_seats
            END AS available_seats
        FROM Flight f
        INNER JOIN Airline a ON f.airline_id = a.airline_id
        INNER JOIN Airport src ON f.source_airport = src.airport_id
        INNER JOIN Airport dest ON f.destination_airport = dest.airport_id
        LEFT JOIN Flight_Instance fi ON f.flight_id = fi.flight_id 
            AND fi.flight_date = ?
            AND fi.is_deleted = 0
        WHERE f.source_airport IN ({source_placeholders})
          AND f.destination_airport IN ({dest_placeholders})
          AND f.is_deleted = 0
          AND (
              (fi.available_seats IS NOT NULL AND fi.available_seats >= ?) OR
              (fi.available_seats IS NULL AND f.total_seats >= ?)
          )
        ORDER BY f.base_price ASC, f.departure_time ASC
        """

        params = [parsed_date] + source_airport_ids + dest_airport_ids + [request.seats_required, request.seats_required]
        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="No matching internal flight found.")

        # Combine travel_date + time to form full datetime
        dep_time = row[5] or datetime.min.time()
        arr_time = row[6] or datetime.min.time()
        departure_datetime = datetime.combine(parsed_date, dep_time)
        arrival_datetime = datetime.combine(parsed_date, arr_time)

        return [{
        "flight_id": row[0],
        "airline_name": row[1],
        "flight_number": row[2],
        "source_airport": row[3],
        "destination_airport": row[4],
        "departure_time": departure_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "arrival_time": arrival_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_minutes": row[7],
        "base_price": float(row[8]),
        "available_seats": row[9]
    }]

@app.post("/flights/search", response_model=List[ConnectingFlightResult])
async def search_flights(request: FlightSearchRequest):
    """
    Search for direct flights based on source city, destination city, date and seat availability.
    Returns each direct flight wrapped as a ConnectingFlightResult with a single flight.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        source_airport_ids = get_airports_by_city_name(cursor, request.source_city)
        dest_airport_ids = get_airports_by_city_name(cursor, request.destination_city)
        
        if not source_airport_ids:
            raise HTTPException(status_code=404, detail=f"No airports found for source city: {request.source_city}")
        if not dest_airport_ids:
            raise HTTPException(status_code=404, detail=f"No airports found for destination city: {request.destination_city}")
        
        source_placeholders = ','.join(['?'] * len(source_airport_ids))
        dest_placeholders = ','.join(['?'] * len(dest_airport_ids))
        
        query = f"""
        SELECT 
            f.flight_id,
            a.airline_name,
            f.flight_number,
            src.iata_code AS source_airport,
            dest.iata_code AS destination_airport,
            CAST(f.departure_time AS TIME) AS departure_time,
            CAST(f.arrival_time AS TIME) AS arrival_time,
            f.duration_minutes,
            f.base_price,
            f.arrival_day_offset,
            CASE 
                WHEN fi.available_seats IS NOT NULL THEN fi.available_seats
                ELSE f.total_seats
            END AS available_seats
        FROM Flight f
        INNER JOIN Airline a ON f.airline_id = a.airline_id
        INNER JOIN Airport src ON f.source_airport = src.airport_id
        INNER JOIN Airport dest ON f.destination_airport = dest.airport_id
        LEFT JOIN Flight_Instance fi ON f.flight_id = fi.flight_id 
            AND fi.flight_date = ? 
            AND fi.is_deleted = 0
        WHERE f.source_airport IN ({source_placeholders})
            AND f.destination_airport IN ({dest_placeholders})
            AND f.is_deleted = 0
            AND (
                (fi.available_seats IS NOT NULL AND fi.available_seats >= ?) OR
                (fi.available_seats IS NULL AND f.total_seats >= ?)
            )
        ORDER BY f.base_price ASC, f.departure_time ASC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
        """
        
        params = [request.travel_date] + source_airport_ids + dest_airport_ids + [request.seats_required, request.seats_required, request.limit]
        
        cursor.execute(query, params)
        
        results = []
        travel_date = datetime.strptime(request.travel_date, "%Y-%m-%d").date()

        for row in cursor.fetchall():
            departure_dt = datetime.combine(travel_date, row[5])
            arrival_dt = datetime.combine(travel_date, row[6])

            flight = FlightResult(
                flight_id=row[0],
                airline_name=row[1],
                flight_number=row[2],
                source_airport=row[3],
                destination_airport=row[4],
                departure_time=departure_dt,
                arrival_time=arrival_dt,
                duration_minutes=row[7],
                base_price=float(row[8]),
                available_seats=row[10]
            )

            results.append(ConnectingFlightResult(
                total_duration_minutes=flight.duration_minutes,
                total_price=flight.base_price,
                flights=[flight]
            ))

        
        return results

@app.post("/flights/search-connecting", response_model=List[ConnectingFlightResult])
async def search_connecting_flights(request: FlightSearchRequest):
    """
    Debug version of connecting flights search
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        source_airport_ids = get_airports_by_city_name(cursor, request.source_city)
        dest_airport_ids = get_airports_by_city_name(cursor, request.destination_city)
        
        if not source_airport_ids:
            raise HTTPException(status_code=404, detail=f"No airports found for source city: {request.source_city}")
        if not dest_airport_ids:
            raise HTTPException(status_code=404, detail=f"No airports found for destination city: {request.destination_city}")
        
        source_placeholders = ','.join(['?'] * len(source_airport_ids))
        dest_placeholders = ','.join(['?'] * len(dest_airport_ids))

        query = f"""
        WITH ConnectingFlights AS (
            SELECT 
                f1.flight_id as first_flight_id,
                a1.airline_name as first_airline_name,
                f1.flight_number as first_flight_number,
                src1.iata_code as first_source_airport,
                layover.iata_code as layover_airport,
                DATEADD(SECOND, DATEDIFF(SECOND, 0, f1.departure_time), CAST(? AS DATETIME)) AS first_departure,
                DATEADD(DAY, f1.arrival_day_offset,
                    DATEADD(SECOND, DATEDIFF(SECOND, 0, f1.arrival_time), CAST(? AS DATETIME))
                ) AS first_arrival,
                f1.duration_minutes as first_duration,
                f1.base_price as first_price,
                f1.arrival_day_offset as first_arrival_day_offset,
                CASE 
                    WHEN fi1.available_seats IS NOT NULL THEN fi1.available_seats
                    ELSE f1.total_seats
                END as first_available_seats,

                f2.flight_id as second_flight_id,
                a2.airline_name as second_airline_name,
                f2.flight_number as second_flight_number,
                dest2.iata_code as second_dest_airport,
                DATEADD(SECOND, DATEDIFF(SECOND, 0, f2.departure_time), CAST(? AS DATETIME)) AS second_departure,
                DATEADD(DAY, f2.arrival_day_offset,
                    DATEADD(SECOND, DATEDIFF(SECOND, 0, f2.arrival_time), CAST(? AS DATETIME))
                ) AS second_arrival,
                f2.duration_minutes as second_duration,
                f2.base_price as second_price,
                f2.arrival_day_offset as second_arrival_day_offset,
                CASE 
                    WHEN fi2.available_seats IS NOT NULL THEN fi2.available_seats
                    ELSE f2.total_seats
                END as second_available_seats,

                (f1.duration_minutes + f2.duration_minutes) as total_duration,
                (f1.base_price + f2.base_price) as total_price

            FROM Flight f1
            INNER JOIN Airline a1 ON f1.airline_id = a1.airline_id
            INNER JOIN Airport src1 ON f1.source_airport = src1.airport_id
            INNER JOIN Airport layover ON f1.destination_airport = layover.airport_id
            LEFT JOIN Flight_Instance fi1 ON f1.flight_id = fi1.flight_id 
                AND fi1.flight_date = ? 
                AND fi1.is_deleted = 0

            INNER JOIN Flight f2 ON f1.destination_airport = f2.source_airport
            INNER JOIN Airline a2 ON f2.airline_id = a2.airline_id
            INNER JOIN Airport dest2 ON f2.destination_airport = dest2.airport_id
            LEFT JOIN Flight_Instance fi2 ON f2.flight_id = fi2.flight_id 
                AND fi2.flight_date = ? 
                AND fi2.is_deleted = 0

            WHERE f1.source_airport IN ({source_placeholders})
                AND f2.destination_airport IN ({dest_placeholders})
                AND f1.is_deleted = 0
                AND f2.is_deleted = 0
                AND (
                    (fi1.available_seats IS NOT NULL AND fi1.available_seats >= ?) OR
                    (fi1.available_seats IS NULL AND f1.total_seats >= ?)
                )
                AND (
                    (fi2.available_seats IS NOT NULL AND fi2.available_seats >= ?) OR
                    (fi2.available_seats IS NULL AND f2.total_seats >= ?)
                )
        )
        SELECT TOP 5 *
        FROM ConnectingFlights
        ORDER BY total_price ASC, total_duration ASC
        """

        params = [
            request.travel_date,  # f1.departure_time
            request.travel_date,  # f1.arrival_time
            request.travel_date,  # f2.departure_time
            request.travel_date,  # f2.arrival_time
            request.travel_date,  # fi1.flight_date
            request.travel_date,  # fi2.flight_date
        ] + source_airport_ids + dest_airport_ids + [
            request.seats_required, request.seats_required,
            request.seats_required, request.seats_required
        ]

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            flights = [
                FlightResult(
                    flight_id=row[0],
                    airline_name=row[1],
                    flight_number=row[2],
                    source_airport=row[3],
                    destination_airport=row[4],
                    departure_time=row[5],
                    arrival_time=row[6],
                    duration_minutes=row[7],
                    base_price=float(row[8]),
                    arrival_day_offset=row[9],
                    available_seats=row[10]
                ),
                FlightResult(
                    flight_id=row[11],
                    airline_name=row[12],
                    flight_number=row[13],
                    source_airport=row[4],  # Layover
                    destination_airport=row[14],
                    departure_time=row[15],
                    arrival_time=row[16],
                    duration_minutes=row[17],
                    base_price=float(row[18]),
                    arrival_day_offset=row[19],
                    available_seats=row[20]
                )
            ]

            results.append(ConnectingFlightResult(
                total_duration_minutes=row[21],
                total_price=float(row[22]),
                flights=flights
            ))

        return results
    
@app.post("/flights/book", response_model=BookingResponse)
async def book_flight(request: BookingRequest):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            conn.autocommit = False

            # 🔍 Check if flight instance exists
            check_query = """
            SELECT fi.available_seats, f.base_price, fi.flight_date
            FROM Flight_Instance fi
            INNER JOIN Flight f ON fi.flight_id = f.flight_id
            WHERE fi.flight_id = ? AND fi.flight_date = ?
            """
            cursor.execute(check_query, (request.flight_id, request.travel_date))
            result = cursor.fetchone()

            if not result:
                # 🔧 Flight instance does not exist – create it
                get_flight_query = """
                SELECT total_seats, base_price
                FROM Flight
                WHERE flight_id = ? AND is_deleted = 0
                """
                cursor.execute(get_flight_query, (request.flight_id,))
                flight_info = cursor.fetchone()

                if not flight_info:
                    raise HTTPException(status_code=404, detail="Flight not found")

                total_seats, base_price = flight_info

                # 🚀 Insert new flight instance
                insert_instance_query = """
                INSERT INTO Flight_Instance (flight_id, flight_date, available_seats, is_deleted)
                VALUES (?, ?, ?, 0)
                """
                cursor.execute(insert_instance_query, (request.flight_id, request.travel_date, total_seats))

                available_seats = total_seats
                flight_date = request.travel_date
            else:
                available_seats, base_price, flight_date = result

            # 🧮 Check seat availability
            if available_seats < request.seats_required:
                raise HTTPException(
                    status_code=400,
                    detail=f"Only {available_seats} seats available, requested {request.seats_required}"
                )

            total_price = float(base_price) * request.seats_required

            # 💾 Create booking
            booking_query = """
            INSERT INTO Booking (flight_id, user_id, booking_date, travel_date, status, total_price)
            OUTPUT INSERTED.booking_id
            VALUES (?, ?, GETDATE(), ?, 'confirmed', ?)
            """
            cursor.execute(booking_query, (
                request.flight_id,
                1,  # TODO: Replace with actual user ID when auth is integrated
                flight_date,
                total_price
            ))
            booking_id = cursor.fetchone()[0]

            # 🧍 Add passengers
            for i, passenger in enumerate(request.passenger_details):
                passenger_query = """
                INSERT INTO Passenger (booking_id, name, age, gender, passport_no)
                VALUES (?, ?, ?, ?, ?)
                """
                cursor.execute(passenger_query, (
                    booking_id,
                    passenger.name,
                    passenger.age,
                    passenger.gender,
                    passenger.passport_no
                ))

            # ✏️ Update available seats
            update_seats_query = """
            UPDATE Flight_Instance 
            SET available_seats = available_seats - ?
            WHERE flight_id = ? AND flight_date = ?
            """
            cursor.execute(update_seats_query, (request.seats_required, request.flight_id, request.travel_date))

            conn.commit()

            return BookingResponse(
                booking_id=booking_id,
                status="confirmed",
                total_price=total_price,
                message=f"Successfully booked {request.seats_required} seats"
            )

        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"Booking failed: {str(e)}")
        finally:
            conn.autocommit = True



from datetime import datetime
from fastapi import HTTPException

@app.get("/booking/{booking_id}", response_model=BookingDetailResponse)
async def get_booking_details(booking_id: int):
    """Get full booking details including passenger list"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Booking summary with departure and arrival times from Flight table
        summary_query = """
        SELECT 
            b.booking_id,
            b.flight_id,
            f.flight_number,
            a.airline_name,
            b.travel_date,      -- date
            f.departure_time,   -- time
            f.arrival_time,     -- time
            b.status,
            b.total_price
        FROM Booking b
        INNER JOIN Flight f ON b.flight_id = f.flight_id
        INNER JOIN Airline a ON f.airline_id = a.airline_id
        WHERE b.booking_id = ?
        """

        cursor.execute(summary_query, (booking_id,))
        summary = cursor.fetchone()

        if not summary:
            raise HTTPException(status_code=404, detail="Booking not found")

        # Fetch passenger details
        passenger_query = """
        SELECT name, age, gender, passport_no
        FROM Passenger
        WHERE booking_id = ?
        """
        cursor.execute(passenger_query, (booking_id,))
        passengers_raw = cursor.fetchall()

        passengers = [
            BookingPassenger(
                name=row[0],
                age=row[1],
                gender=row[2],
                passport_no=row[3]
            )
            for row in passengers_raw
        ]

        # Combine travel_date (date) and times (time) into datetime objects
        travel_date = summary[4]
        departure_time = summary[5]
        arrival_time = summary[6]

        # Defensive: if times are None, fallback to midnight time
        if departure_time is None:
            departure_time = datetime.min.time()
        if arrival_time is None:
            arrival_time = datetime.min.time()

        departure_datetime = datetime.combine(travel_date, departure_time)
        arrival_datetime = datetime.combine(travel_date, arrival_time)

        return BookingDetailResponse(
            booking_id=summary[0],
            flight_id=summary[1],
            flight_number=summary[2],
            airline_name=summary[3],
            departure_time=departure_datetime,
            arrival_time=arrival_datetime,
            status=summary[7],
            total_price=float(summary[8]),
            passenger_count=len(passengers),
            passengers=passengers
        )


@app.get("/flights/all", response_model=List[FlightResult])
async def get_all_flights():
    """
    Retrieve all available and active flight instances.
    Only returns flights with is_deleted = 0.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        query = """
        SELECT 
            f.flight_id,
            a.airline_name,
            f.flight_number,
            src.iata_code AS source_airport,
            dest.iata_code AS destination_airport,
            CAST(f.departure_time AS TIME) AS departure_time,
            CAST(f.arrival_time AS TIME) AS arrival_time,
            f.duration_minutes,
            f.base_price,
            f.arrival_day_offset,
            f.total_seats
        FROM Flight f
        INNER JOIN Airline a ON f.airline_id = a.airline_id
        INNER JOIN Airport src ON f.source_airport = src.airport_id
        INNER JOIN Airport dest ON f.destination_airport = dest.airport_id
        WHERE f.is_deleted = 0
        ORDER BY f.departure_time ASC;
        """

        cursor.execute(query)
        results = []
        for row in cursor.fetchall():
            results.append(FlightResult(
                flight_id=row[0],
                airline_name=row[1],
                flight_number=row[2],
                source_airport=row[3],
                destination_airport=row[4],
                departure_time=row[5],
                arrival_time=row[6],
                duration_minutes=row[7],
                base_price=float(row[8]),
                arrival_day_offset=row[9],
                available_seats=row[10]
            ))

        return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)