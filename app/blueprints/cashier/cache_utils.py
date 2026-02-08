# cache_utils.py - Shared cache management functions
from db import get_redis
import json
from decimal import Decimal
from datetime import datetime, date

def serialize_data(data):
    """Convert PostgreSQL results to JSON-serializable format"""
    if isinstance(data, list):
        return [serialize_data(row) for row in data]
    if isinstance(data, tuple):
        return [serialize_data(item) for item in data]
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    return data

# Global cache keys (shared across all cashiers)
CACHE_KEY_TRANSACTIONS = "spa:transactions:active:global"
CACHE_KEY_STAFF = "spa:availability:staff"
CACHE_KEY_ROOMS = "spa:availability:rooms"
CACHE_KEY_BUSY = "spa:availability:busy"

# Spa-optimized TTLs (in seconds)
CACHE_TTL = {
    'transactions': 1800,     # 30 minutes - transactions don't change that often
    'staff': 1800,            # 30 minutes
    'rooms': 1800,            # 30 minutes
    'busy': 1800              # 30 minutes
}

def invalidate_transactions_cache():
    """Invalidate global active transactions cache"""
    try:
        redis_client = get_redis()
        redis_client.delete(CACHE_KEY_TRANSACTIONS)
    except Exception as e:
        print(f"Cache invalidation failed: {e}")

def invalidate_availability_cache():
    """Invalidate all availability-related caches"""
    try:
        redis_client = get_redis()
        keys_to_delete = [CACHE_KEY_STAFF, CACHE_KEY_ROOMS, CACHE_KEY_BUSY]
        for key in keys_to_delete:
            redis_client.delete(key)
    except Exception as e:
        print(f"Cache invalidation failed: {e}")

def invalidate_all_dashboard_cache():
    """Invalidate both transactions and availability caches"""
    invalidate_transactions_cache()
    invalidate_availability_cache()