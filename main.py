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
    travel_datetime: datetime
    seats_required: int = Field(..., gt=0, description="Number of seats required")
    limit: int = Field(5, ge=1, description="Maximum number of results to return")

class FlightResult(BaseModel):
    flight_id: int
    airline_name: str
    flight_number: str
    source_airport: str
    destination_airport: str
    source_city: str  # Added
    destination_city: str  # Added
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
    # Validate datetime
    if not isinstance(request.travel_datetime, datetime):
        raise HTTPException(status_code=400, detail="Invalid travel_datetime format. Use ISO format (e.g. 2025-08-01T10:00:00)")

    travel_date = request.travel_datetime.date()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get airport IDs for city names
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
            src.iata_code,
            dest.iata_code,
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
            AND CAST(f.departure_time AS TIME) >= ?
          )
        ORDER BY f.base_price ASC, f.departure_time ASC
        """

        params = (
            [travel_date] +
            source_airport_ids +
            dest_airport_ids +
            [request.seats_required, request.seats_required, request.travel_datetime.time()]
        )
 
        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            return []

        departure_time = row[5] if isinstance(row[5], time) else datetime.strptime(row[5], "%H:%M:%S").time()
        arrival_time = row[6] if isinstance(row[6], time) else datetime.strptime(row[6], "%H:%M:%S").time()

        departure_datetime = datetime.combine(travel_date, departure_time)
        arrival_datetime = datetime.combine(travel_date, arrival_time)

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
async def search_all_flights(request: FlightSearchRequest):
    # 1. Check if travel_datetime is a datetime object
    if not isinstance(request.travel_datetime, datetime):
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO 8601 format like '2025-08-01T10:30:00'.")

    # 2. Call direct flight search
    direct_flights = await search_flights(request)

    # 3. If enough direct flights found, return limited
    if len(direct_flights) >= request.limit:
        return direct_flights[:request.limit]

    # 4. Otherwise, get remaining from connecting flights
    remaining = request.limit - len(direct_flights)
    connecting_flights = await search_connecting_flights(request)
    combined = direct_flights + connecting_flights[:remaining]

    return combined

@app.post("/flights/search-direct", response_model=List[ConnectingFlightResult])
async def search_flights(request: FlightSearchRequest):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        source_ids = get_airports_by_city_name(cursor, request.source_city)
        dest_ids = get_airports_by_city_name(cursor, request.destination_city)

        if not source_ids or not dest_ids:
            raise HTTPException(status_code=404, detail="Invalid source or destination city.")

        placeholders_src = ','.join(['?'] * len(source_ids))
        placeholders_dst = ','.join(['?'] * len(dest_ids))

        # Updated query to include city names via City table JOIN
        query = f"""
        SELECT 
            f.flight_id, a.airline_name, f.flight_number,
            src.iata_code, dest.iata_code,
            src_city.city_name, dest_city.city_name,
            CAST(f.departure_time AS TIME), CAST(f.arrival_time AS TIME),
            f.duration_minutes, f.base_price, f.arrival_day_offset,
            COALESCE(fi.available_seats, f.total_seats)
        FROM Flight f
        INNER JOIN Airline a ON f.airline_id = a.airline_id
        INNER JOIN Airport src ON f.source_airport = src.airport_id
        INNER JOIN Airport dest ON f.destination_airport = dest.airport_id
        INNER JOIN City src_city ON src.city_id = src_city.city_id
        INNER JOIN City dest_city ON dest.city_id = dest_city.city_id
        LEFT JOIN Flight_Instance fi ON fi.flight_id = f.flight_id
            AND fi.flight_date = ? AND fi.is_deleted = 0
        WHERE f.source_airport IN ({placeholders_src})
            AND f.destination_airport IN ({placeholders_dst})
            AND f.is_deleted = 0
            AND CAST(f.departure_time AS TIME) >= ?
            AND (
                (fi.available_seats IS NOT NULL AND fi.available_seats >= ?) OR
                (fi.available_seats IS NULL AND f.total_seats >= ?)
            )
        ORDER BY f.base_price ASC, f.departure_time ASC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
        """

        travel_date = request.travel_datetime.date()
        travel_time = request.travel_datetime.time()

        params = [travel_date] + source_ids + dest_ids + [travel_time, request.seats_required, request.seats_required, request.limit]
        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            departure = datetime.combine(travel_date, row[7])  # Updated index
            arrival = datetime.combine(travel_date, row[8])    # Updated index

            flight = FlightResult(
                flight_id=row[0], airline_name=row[1], flight_number=row[2],
                source_airport=row[3], destination_airport=row[4],
                source_city=row[5], destination_city=row[6],  # Added city names
                departure_time=departure, arrival_time=arrival,
                duration_minutes=row[9], base_price=float(row[10]),  # Updated indices
                arrival_day_offset=row[11], available_seats=row[12]   # Updated indices
            )

            results.append(ConnectingFlightResult(
                total_duration_minutes=flight.duration_minutes,
                total_price=flight.base_price,
                flights=[flight]
            ))

        return results

@app.post("/flights/search-connecting", response_model=List[ConnectingFlightResult])
async def search_connecting_flights(request: FlightSearchRequest):
    with get_db_connection() as conn:
        cursor = conn.cursor()

        source_ids = get_airports_by_city_name(cursor, request.source_city)
        dest_ids = get_airports_by_city_name(cursor, request.destination_city)

        if not source_ids:
            raise HTTPException(status_code=404, detail=f"No airports for source city: {request.source_city}")
        if not dest_ids:
            raise HTTPException(status_code=404, detail=f"No airports for destination city: {request.destination_city}")

        placeholders_src = ','.join(['?'] * len(source_ids))
        placeholders_dst = ','.join(['?'] * len(dest_ids))

        # Updated query to include city names via City table JOINs
        query = f"""
        WITH Connecting AS (
            SELECT 
                f1.flight_id AS f1_flight_id, a1.airline_name AS f1_airline_name, f1.flight_number AS f1_flight_number,
                ap1.iata_code AS f1_source_airport, ap2.iata_code AS f1_dest_airport,
                src_city1.city_name AS f1_source_city, dest_city1.city_name AS f1_dest_city,
                DATEADD(SECOND, DATEDIFF(SECOND, 0, f1.departure_time), CAST(? AS DATETIME)) AS f1_departure_time,
                DATEADD(DAY, f1.arrival_day_offset, DATEADD(SECOND, DATEDIFF(SECOND, 0, f1.arrival_time), CAST(? AS DATETIME))) AS f1_arrival_time,
                f1.duration_minutes AS f1_duration, f1.base_price AS f1_price, f1.arrival_day_offset AS f1_offset,
                COALESCE(fi1.available_seats, f1.total_seats) AS f1_available_seats,

                f2.flight_id AS f2_flight_id, a2.airline_name AS f2_airline_name, f2.flight_number AS f2_flight_number,
                ap2.iata_code AS f2_source_airport, ap3.iata_code AS f2_dest_airport,
                dest_city1.city_name AS f2_source_city, dest_city2.city_name AS f2_dest_city,
                DATEADD(SECOND, DATEDIFF(SECOND, 0, f2.departure_time), CAST(? AS DATETIME)) AS f2_departure_time,
                DATEADD(DAY, f2.arrival_day_offset, DATEADD(SECOND, DATEDIFF(SECOND, 0, f2.arrival_time), CAST(? AS DATETIME))) AS f2_arrival_time,
                f2.duration_minutes AS f2_duration, f2.base_price AS f2_price, f2.arrival_day_offset AS f2_offset,
                COALESCE(fi2.available_seats, f2.total_seats) AS f2_available_seats,

                (f1.duration_minutes + f2.duration_minutes) AS total_duration,
                (f1.base_price + f2.base_price) AS total_price
            FROM Flight f1
            JOIN Flight f2 ON f1.destination_airport = f2.source_airport
            JOIN Airline a1 ON f1.airline_id = a1.airline_id
            JOIN Airline a2 ON f2.airline_id = a2.airline_id
            JOIN Airport ap1 ON f1.source_airport = ap1.airport_id
            JOIN Airport ap2 ON f1.destination_airport = ap2.airport_id
            JOIN Airport ap3 ON f2.destination_airport = ap3.airport_id
            JOIN City src_city1 ON ap1.city_id = src_city1.city_id
            JOIN City dest_city1 ON ap2.city_id = dest_city1.city_id
            JOIN City dest_city2 ON ap3.city_id = dest_city2.city_id
            LEFT JOIN Flight_Instance fi1 ON fi1.flight_id = f1.flight_id AND fi1.flight_date = ? AND fi1.is_deleted = 0
            LEFT JOIN Flight_Instance fi2 ON fi2.flight_id = f2.flight_id AND fi2.flight_date = ? AND fi2.is_deleted = 0
            WHERE f1.source_airport IN ({placeholders_src})
              AND f2.destination_airport IN ({placeholders_dst})
              AND f1.is_deleted = 0 AND f2.is_deleted = 0
              AND CAST(f1.departure_time AS TIME) >= ?
              AND (
                  (fi1.available_seats IS NOT NULL AND fi1.available_seats >= ?) OR
                  (fi1.available_seats IS NULL AND f1.total_seats >= ?)
              )
              AND (
                  (fi2.available_seats IS NOT NULL AND fi2.available_seats >= ?) OR
                  (fi2.available_seats IS NULL AND f2.total_seats >= ?)
              )
        )
        SELECT TOP (?) * FROM Connecting
        ORDER BY total_price ASC, total_duration ASC
        """

        travel_date = request.travel_datetime.date()
        travel_time = request.travel_datetime.time()

        params = [
            travel_date,  # f1.departure_time
            travel_date,  # f1.arrival_time
            travel_date,  # f2.departure_time
            travel_date,  # f2.arrival_time
            travel_date,  # fi1.flight_date
            travel_date,  # fi2.flight_date
        ] + source_ids + dest_ids + [
            travel_time,
            request.seats_required, request.seats_required,  # for fi1
            request.seats_required, request.seats_required,  # for fi2
            request.limit
        ]

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            f1 = FlightResult(
                flight_id=r[0], airline_name=r[1], flight_number=r[2],
                source_airport=r[3], destination_airport=r[4],
                source_city=r[5], destination_city=r[6],  # Added city names
                departure_time=r[7], arrival_time=r[8],
                duration_minutes=r[9], base_price=float(r[10]),
                arrival_day_offset=r[11], available_seats=r[12]
            )
            f2 = FlightResult(
                flight_id=r[13], airline_name=r[14], flight_number=r[15],
                source_airport=r[16], destination_airport=r[17],
                source_city=r[18], destination_city=r[19],  # Added city names
                departure_time=r[20], arrival_time=r[21],
                duration_minutes=r[22], base_price=float(r[23]),
                arrival_day_offset=r[24], available_seats=r[25]
            )
            results.append(ConnectingFlightResult(
                total_duration_minutes=r[26],  # Updated index
                total_price=float(r[27]),      # Updated index
                flights=[f1, f2]
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
    """Get full booking details including passenger list and airport/city information"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Enhanced booking summary with airport names and city names
        summary_query = """
        SELECT 
            b.booking_id,
            b.flight_id,
            f.flight_number,
            a.airline_name,
            b.travel_date,          -- date
            f.departure_time,       -- time
            f.arrival_time,         -- time
            b.status,
            b.total_price,
            -- Source airport and city information
            src_airport.iata_code AS source_airport_code,
            src_airport.airport_name AS source_airport_name,
            src_city.city_name AS source_city_name,
            -- Destination airport and city information
            dest_airport.iata_code AS destination_airport_code,
            dest_airport.airport_name AS destination_airport_name,
            dest_city.city_name AS destination_city_name
        FROM Booking b
        INNER JOIN Flight f ON b.flight_id = f.flight_id
        INNER JOIN Airline a ON f.airline_id = a.airline_id
        INNER JOIN Airport src_airport ON f.source_airport = src_airport.airport_id
        INNER JOIN Airport dest_airport ON f.destination_airport = dest_airport.airport_id
        INNER JOIN City src_city ON src_airport.city_id = src_city.city_id
        INNER JOIN City dest_city ON dest_airport.city_id = dest_city.city_id
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
            source_airport_code=summary[9],
            source_airport_name=summary[10],
            source_city_name=summary[11],
            destination_airport_code=summary[12],
            destination_airport_name=summary[13],
            destination_city_name=summary[14],
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