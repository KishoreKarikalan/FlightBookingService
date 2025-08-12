from fastapi import HTTPException
from typing import List
from datetime import datetime, date, time

from models.schemas import (
    FlightSearchRequest, FlightResult, FlightResultAll, 
    ConnectingFlightResult
)
from database.connection import get_db_connection, get_airports_by_city_name

class FlightService:
    """Service class for flight-related operations"""
    
    async def search_internal_flight(self, request: FlightSearchRequest):
        """Search for a single internal (domestic) flight using city names"""
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

    async def search_all_flights(self, request: FlightSearchRequest) -> List[ConnectingFlightResult]:
        """Search for all flights (direct + connecting)"""
        # Check if travel_datetime is a datetime object
        if not isinstance(request.travel_datetime, datetime):
            raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO 8601 format like '2025-08-01T10:30:00'.")

        # Call direct flight search
        direct_flights = await self.search_direct_flights(request)

        # If enough direct flights found, return limited
        if len(direct_flights) >= request.limit:
            return direct_flights[:request.limit]

        # Otherwise, get remaining from connecting flights
        remaining = request.limit - len(direct_flights)
        connecting_flights = await self.search_connecting_flights(request)
        combined = direct_flights + connecting_flights[:remaining]

        return combined

    async def search_direct_flights(self, request: FlightSearchRequest) -> List[ConnectingFlightResult]:
        """Search for direct flights only"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            source_ids = get_airports_by_city_name(cursor, request.source_city)
            dest_ids = get_airports_by_city_name(cursor, request.destination_city)

            if not source_ids or not dest_ids:
                raise HTTPException(status_code=404, detail="Invalid source or destination city.")

            placeholders_src = ','.join(['?'] * len(source_ids))
            placeholders_dst = ','.join(['?'] * len(dest_ids))

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
                departure = datetime.combine(travel_date, row[7])
                arrival = datetime.combine(travel_date, row[8])

                flight = FlightResult(
                    flight_id=row[0], airline_name=row[1], flight_number=row[2],
                    source_airport=row[3], destination_airport=row[4],
                    source_city=row[5], destination_city=row[6],
                    departure_time=departure, arrival_time=arrival,
                    duration_minutes=row[9], base_price=float(row[10]),
                    available_seats=row[12]
                )

                results.append(ConnectingFlightResult(
                    total_duration_minutes=flight.duration_minutes,
                    total_price=flight.base_price,
                    flights=[flight]
                ))

            return results

    async def search_connecting_flights(self, request: FlightSearchRequest) -> List[ConnectingFlightResult]:
        """Search for connecting flights only"""
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
                travel_date, travel_date, travel_date, travel_date,
                travel_date, travel_date,
            ] + source_ids + dest_ids + [
                travel_time,
                request.seats_required, request.seats_required,
                request.seats_required, request.seats_required,
                request.limit
            ]

            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for r in rows:
                f1 = FlightResult(
                    flight_id=r[0], airline_name=r[1], flight_number=r[2],
                    source_airport=r[3], destination_airport=r[4],
                    source_city=r[5], destination_city=r[6],
                    departure_time=r[7], arrival_time=r[8],
                    duration_minutes=r[9], base_price=float(r[10]),
                    available_seats=r[12]
                )
                f2 = FlightResult(
                    flight_id=r[13], airline_name=r[14], flight_number=r[15],
                    source_airport=r[16], destination_airport=r[17],
                    source_city=r[18], destination_city=r[19],
                    departure_time=r[20], arrival_time=r[21],
                    duration_minutes=r[22], base_price=float(r[23]),
                    available_seats=r[25]
                )
                results.append(ConnectingFlightResult(
                    total_duration_minutes=r[26],
                    total_price=float(r[27]),
                    flights=[f1, f2]
                ))

            return results

    async def get_all_flights(self) -> List[FlightResultAll]:
        """Retrieve all available and active flight instances"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                query = """
                SELECT 
                    f.flight_id,
                    a.airline_name,
                    f.flight_number,
                    src.iata_code AS source_airport,
                    dest.iata_code AS destination_airport,
                    f.departure_time,
                    f.arrival_time,
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
                    # Convert time objects to datetime objects
                    departure_time = row[5]
                    arrival_time = row[6]
                    
                    # If they are time objects, convert to datetime with today's date
                    if isinstance(departure_time, time):
                        departure_time = datetime.combine(date.today(), departure_time)
                    if isinstance(arrival_time, time):
                        arrival_time = datetime.combine(date.today(), arrival_time)
                        
                    results.append(FlightResultAll(
                        flight_id=row[0],
                        airline_name=row[1],
                        flight_number=row[2],
                        source_airport=row[3],
                        destination_airport=row[4],
                        departure_time=departure_time,
                        arrival_time=arrival_time,
                        duration_minutes=row[7],
                        base_price=float(row[8]),
                        arrival_day_offset=row[9],
                        available_seats=row[10]
                    ))

                return results
                
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database connection error: {str(e)}"
            )