from fastapi import HTTPException
from datetime import datetime

from models.schemas import (
    BookingRequest, BookingResponse, BookingDetailResponse, 
    BookingPassenger
)
from database.connection import get_db_connection

class BookingService:
    """Service class for booking-related operations"""
    
    async def book_flight(self, request: BookingRequest) -> BookingResponse:
        """Book a flight with passenger details"""
        print(f"Booking request: {request}")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                conn.autocommit = False

                # Check if flight instance exists
                check_query = """
                SELECT fi.available_seats, f.base_price, fi.flight_date
                FROM Flight_Instance fi
                INNER JOIN Flight f ON fi.flight_id = f.flight_id
                WHERE fi.flight_id = ? AND fi.flight_date = ?
                """
                cursor.execute(check_query, (request.flight_id, request.travel_date))
                result = cursor.fetchone()

                if not result:
                    # Flight instance does not exist – create it
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

                    # Insert new flight instance
                    insert_instance_query = """
                    INSERT INTO Flight_Instance (flight_id, flight_date, available_seats, is_deleted)
                    VALUES (?, ?, ?, 0)
                    """
                    cursor.execute(insert_instance_query, (request.flight_id, request.travel_date, total_seats))

                    available_seats = total_seats
                    flight_date = request.travel_date
                else:
                    available_seats, base_price, flight_date = result

                # Check seat availability
                if available_seats < request.seats_required:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Only {available_seats} seats available, requested {request.seats_required}"
                    )

                total_price = float(base_price) * request.seats_required

                # Create booking
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

                # Add passengers
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

                # Update available seats
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

    async def get_booking_details(self, booking_id: int) -> BookingDetailResponse:
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