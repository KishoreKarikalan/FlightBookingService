import pyodbc
from contextlib import contextmanager
from fastapi import HTTPException
from typing import Optional

from config.settings import DATABASE_CONNECTION_STRING

@contextmanager
def get_db_connection():
    """Database connection manager with proper error handling"""
    conn = None
    try:
        conn = pyodbc.connect(DATABASE_CONNECTION_STRING)
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")
    finally:
        if conn:
            conn.close()

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

def get_airports_by_city_name(cursor, city_name: str):
    """Get all airport IDs for a given city name"""
    query = """
    SELECT a.airport_id 
    FROM Airport a
    INNER JOIN City c ON a.city_id = c.city_id
    WHERE c.city_name = ? AND c.is_deleted = 0 AND a.is_deleted = 0
    """
    cursor.execute(query, (city_name,))
    return [row[0] for row in cursor.fetchall()]