import os
import psycopg2
import time
import redis

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://dev_admin:dev_password@postgres:5432/spa_db')

def get_db():
    """Get PostgreSQL database connection with retry"""
    max_retries = 10
    retry_delay = 2
    
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except psycopg2.OperationalError as e:
            if i < max_retries - 1:
                print(f"Database connection failed, retrying in {retry_delay}s... ({i+1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                raise e

def get_redis():
    """Get Redis connection"""
    return redis.Redis(
        host='redis',
        port=6379,
        db=0,
        decode_responses=True
    )