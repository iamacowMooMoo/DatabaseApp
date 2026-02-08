# routes_redis.py - Redis-enhanced version with GLOBAL caching
from flask import render_template, request, redirect, url_for, session
from . import cashier_bp
from db import get_db, get_redis
import json
import time
from decimal import Decimal
from datetime import datetime, date
from .cache_utils import (
    serialize_data, 
    CACHE_KEY_TRANSACTIONS, 
    CACHE_KEY_STAFF, 
    CACHE_KEY_ROOMS, 
    CACHE_KEY_BUSY,
    CACHE_TTL
)

def get_employee(conn, eid):
    """Get employee info - always from DB"""
    cur = conn.cursor()
    cur.execute("SELECT name, work_name FROM employees WHERE eid = %s", (eid,))
    result = cur.fetchone()
    cur.close()
    return result

def query_all_data(conn):
    """Query all dashboard data from PostgreSQL"""
    # Active transactions
    cur = conn.cursor()
    cur.execute("""
        SELECT t.tid, c.cid, c.name, t.entry_time,
               (SELECT MAX(ti.scheduled_end) 
                FROM transaction_items ti 
                WHERE ti.tid = t.tid) as expected_exit,
               GREATEST(0, t.total_cost - t.total_discount - t.total_paid) as outstanding,
               t.status
        FROM transactions t
        JOIN customers c ON t.cid = c.cid
        WHERE t.status IN ('pending', 'partial', 'paid')
        AND t.exit_time IS NULL
        ORDER BY t.entry_time DESC
    """)
    transactions = cur.fetchall()
    
    # Available staff
    cur.execute("""
        SELECT e.work_name, rd.role_type
        FROM employees e
        JOIN roles r ON e.eid = r.eid 
            AND r.start_date <= CURRENT_DATE 
            AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE NOT EXISTS (
            SELECT 1 FROM transaction_items ti
            WHERE ti.therapist_eid = e.eid
            AND ti.scheduled_start <= CURRENT_TIMESTAMP
            AND ti.scheduled_end >= CURRENT_TIMESTAMP
            AND ti.actual_end IS NULL
        )
        AND (e.employment_end IS NULL OR e.employment_end >= CURRENT_DATE)
        ORDER BY rd.role_type, e.work_name
    """)
    available_staff = cur.fetchall()
    
    # Available rooms
    cur.execute("""
        SELECT rid, room_name 
        FROM room
        WHERE rid NOT IN (
            SELECT DISTINCT rid 
            FROM transaction_items 
            WHERE scheduled_start <= CURRENT_TIMESTAMP 
            AND scheduled_end >= CURRENT_TIMESTAMP 
            AND actual_end IS NULL
        )
    """)
    available_rooms = cur.fetchall()
    
    # Busy therapists
    cur.execute("""
        SELECT e.work_name, r.room_name, c.name, ti.scheduled_end,
               EXTRACT(EPOCH FROM (ti.scheduled_end - CURRENT_TIMESTAMP))/60
        FROM transaction_items ti
        JOIN employees e ON ti.therapist_eid = e.eid
        JOIN room r ON ti.rid = r.rid
        JOIN transactions t ON ti.tid = t.tid
        JOIN customers c ON t.cid = c.cid
        WHERE ti.scheduled_start <= CURRENT_TIMESTAMP
        AND ti.scheduled_end >= CURRENT_TIMESTAMP
        AND ti.actual_end IS NULL
        ORDER BY ti.scheduled_end
    """)
    busy_therapists = cur.fetchall()
    
    cur.close()
    
    return transactions, available_staff, available_rooms, busy_therapists

@cashier_bp.route('/cashier-redis/<int:eid>')
def cashier_dashboard_redis(eid):
    """Redis-enhanced cashier dashboard with timing metrics"""
    start_time = time.time()
    
    # Always get DB connection first
    conn = get_db()
    
    # Check employee exists (always from DB)
    cashier = get_employee(conn, eid)
    if not cashier:
        conn.close()
        return redirect(url_for('index'))
    
    # Try to get Redis connection
    try:
        redis_client = get_redis()
        redis_client.ping()
        redis_available = True
    except Exception as e:
        redis_available = False
        print(f"Redis connection failed: {e}")
    
    cache_hits = 0
    cache_misses = 0
    
    if not redis_available:
        # Fallback: query everything from SQL
        transactions, available_staff, available_rooms, busy_therapists = query_all_data(conn)
        conn.close()
        
        total_time = time.time() - start_time
        return render_template('cashier_redis.html',
                             cashier=cashier,
                             eid=eid,
                             transactions=transactions,
                             available_staff=available_staff,
                             available_rooms=available_rooms,
                             busy_therapists=busy_therapists,
                             response_time=f"{total_time:.4f}",
                             cache_hits=0,
                             cache_misses=4)
    
    # Redis is available - try to get from cache
    # 1. Transactions
    cached_txn = redis_client.get(CACHE_KEY_TRANSACTIONS)
    if cached_txn:
        transactions = json.loads(cached_txn)
        cache_hits += 1
        print(f"CACHE HIT: {CACHE_KEY_TRANSACTIONS}")
    else:
        print(f"CACHE MISS: {CACHE_KEY_TRANSACTIONS}")
        cur = conn.cursor()
        cur.execute("""
            SELECT t.tid, c.cid, c.name, t.entry_time,
                   (SELECT MAX(ti.scheduled_end) 
                    FROM transaction_items ti 
                    WHERE ti.tid = t.tid) as expected_exit,
                   GREATEST(0, t.total_cost - t.total_discount - t.total_paid) as outstanding,
                   t.status
            FROM transactions t
            JOIN customers c ON t.cid = c.cid
            WHERE t.status IN ('pending', 'partial', 'paid')
            AND t.exit_time IS NULL
            ORDER BY t.entry_time DESC
        """)
        transactions = cur.fetchall()
        cur.close()
        
        serialized = serialize_data(transactions)
        redis_client.setex(CACHE_KEY_TRANSACTIONS, CACHE_TTL['transactions'], json.dumps(serialized))
        cache_misses += 1
    
    # 2. Staff
    cached_staff = redis_client.get(CACHE_KEY_STAFF)
    if cached_staff:
        available_staff = json.loads(cached_staff)
        cache_hits += 1
        print(f"CACHE HIT: {CACHE_KEY_STAFF}")
    else:
        print(f"CACHE MISS: {CACHE_KEY_STAFF}")
        cur = conn.cursor()
        cur.execute("""
            SELECT e.work_name, rd.role_type
            FROM employees e
            JOIN roles r ON e.eid = r.eid 
                AND r.start_date <= CURRENT_DATE 
                AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
            JOIN role_definition rd ON r.rdid = rd.rdid
            WHERE NOT EXISTS (
                SELECT 1 FROM transaction_items ti
                WHERE ti.therapist_eid = e.eid
                AND ti.scheduled_start <= CURRENT_TIMESTAMP
                AND ti.scheduled_end >= CURRENT_TIMESTAMP
                AND ti.actual_end IS NULL
            )
            AND (e.employment_end IS NULL OR e.employment_end >= CURRENT_DATE)
            ORDER BY rd.role_type, e.work_name
        """)
        available_staff = cur.fetchall()
        cur.close()
        
        serialized = serialize_data(available_staff)
        redis_client.setex(CACHE_KEY_STAFF, CACHE_TTL['staff'], json.dumps(serialized))
        cache_misses += 1
    
    # 3. Rooms
    cached_rooms = redis_client.get(CACHE_KEY_ROOMS)
    if cached_rooms:
        available_rooms = json.loads(cached_rooms)
        cache_hits += 1
        print(f"CACHE HIT: {CACHE_KEY_ROOMS}")
    else:
        print(f"CACHE MISS: {CACHE_KEY_ROOMS}")
        cur = conn.cursor()
        cur.execute("""
            SELECT rid, room_name 
            FROM room
            WHERE rid NOT IN (
                SELECT DISTINCT rid 
                FROM transaction_items 
                WHERE scheduled_start <= CURRENT_TIMESTAMP 
                AND scheduled_end >= CURRENT_TIMESTAMP 
                AND actual_end IS NULL
            )
        """)
        available_rooms = cur.fetchall()
        cur.close()
        
        serialized = serialize_data(available_rooms)
        redis_client.setex(CACHE_KEY_ROOMS, CACHE_TTL['rooms'], json.dumps(serialized))
        cache_misses += 1
    
    # 4. Busy therapists
    cached_busy = redis_client.get(CACHE_KEY_BUSY)
    if cached_busy:
        busy_therapists = json.loads(cached_busy)
        cache_hits += 1
        print(f"CACHE HIT: {CACHE_KEY_BUSY}")
    else:
        print(f"CACHE MISS: {CACHE_KEY_BUSY}")
        cur = conn.cursor()
        cur.execute("""
            SELECT e.work_name, r.room_name, c.name, ti.scheduled_end,
                   EXTRACT(EPOCH FROM (ti.scheduled_end - CURRENT_TIMESTAMP))/60
            FROM transaction_items ti
            JOIN employees e ON ti.therapist_eid = e.eid
            JOIN room r ON ti.rid = r.rid
            JOIN transactions t ON ti.tid = t.tid
            JOIN customers c ON t.cid = c.cid
            WHERE ti.scheduled_start <= CURRENT_TIMESTAMP
            AND ti.scheduled_end >= CURRENT_TIMESTAMP
            AND ti.actual_end IS NULL
            ORDER BY ti.scheduled_end
        """)
        busy_therapists = cur.fetchall()
        cur.close()
        
        serialized = serialize_data(busy_therapists)
        redis_client.setex(CACHE_KEY_BUSY, CACHE_TTL['busy'], json.dumps(serialized))
        cache_misses += 1
    
    conn.close()
    
    total_time = time.time() - start_time
    print(f"Total: {cache_hits} hits, {cache_misses} misses")
    
    return render_template('cashier_redis.html',
                         cashier=cashier,
                         eid=eid,
                         transactions=transactions,
                         available_staff=available_staff,
                         available_rooms=available_rooms,
                         busy_therapists=busy_therapists,
                         response_time=f"{total_time:.4f}",
                         cache_hits=cache_hits,
                         cache_misses=cache_misses)

@cashier_bp.route('/cashier-redis/warm-cache')
def warm_cache():
    """Manually warm the cache for testing"""
    try:
        redis_client = get_redis()
        redis_client.ping()
    except Exception as e:
        return f"Redis not available: {e}", 500
    
    conn = get_db()
    
    # Query and cache all data
    cur = conn.cursor()
    
    # 1. Transactions
    cur.execute("""
        SELECT t.tid, c.cid, c.name, t.entry_time,
               (SELECT MAX(ti.scheduled_end) 
                FROM transaction_items ti 
                WHERE ti.tid = t.tid) as expected_exit,
               GREATEST(0, t.total_cost - t.total_discount - t.total_paid) as outstanding,
               t.status
        FROM transactions t
        JOIN customers c ON t.cid = c.cid
        WHERE t.status IN ('pending', 'partial', 'paid')
        AND t.exit_time IS NULL
        ORDER BY t.entry_time DESC
    """)
    transactions = cur.fetchall()
    redis_client.setex(CACHE_KEY_TRANSACTIONS, CACHE_TTL['transactions'], 
                       json.dumps(serialize_data(transactions)))
    
    # 2. Staff
    cur.execute("""
        SELECT e.work_name, rd.role_type
        FROM employees e
        JOIN roles r ON e.eid = r.eid 
            AND r.start_date <= CURRENT_DATE 
            AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE NOT EXISTS (
            SELECT 1 FROM transaction_items ti
            WHERE ti.therapist_eid = e.eid
            AND ti.scheduled_start <= CURRENT_TIMESTAMP
            AND ti.scheduled_end >= CURRENT_TIMESTAMP
            AND ti.actual_end IS NULL
        )
        AND (e.employment_end IS NULL OR e.employment_end >= CURRENT_DATE)
        ORDER BY rd.role_type, e.work_name
    """)
    staff = cur.fetchall()
    redis_client.setex(CACHE_KEY_STAFF, CACHE_TTL['staff'], 
                       json.dumps(serialize_data(staff)))
    
    # 3. Rooms
    cur.execute("""
        SELECT rid, room_name 
        FROM room
        WHERE rid NOT IN (
            SELECT DISTINCT rid 
            FROM transaction_items 
            WHERE scheduled_start <= CURRENT_TIMESTAMP 
            AND scheduled_end >= CURRENT_TIMESTAMP 
            AND actual_end IS NULL
        )
    """)
    rooms = cur.fetchall()
    redis_client.setex(CACHE_KEY_ROOMS, CACHE_TTL['rooms'], 
                       json.dumps(serialize_data(rooms)))
    
    # 4. Busy therapists
    cur.execute("""
        SELECT e.work_name, r.room_name, c.name, ti.scheduled_end,
               EXTRACT(EPOCH FROM (ti.scheduled_end - CURRENT_TIMESTAMP))/60
        FROM transaction_items ti
        JOIN employees e ON ti.therapist_eid = e.eid
        JOIN room r ON ti.rid = r.rid
        JOIN transactions t ON ti.tid = t.tid
        JOIN customers c ON t.cid = c.cid
        WHERE ti.scheduled_start <= CURRENT_TIMESTAMP
        AND ti.scheduled_end >= CURRENT_TIMESTAMP
        AND ti.actual_end IS NULL
        ORDER BY ti.scheduled_end
    """)
    busy = cur.fetchall()
    redis_client.setex(CACHE_KEY_BUSY, CACHE_TTL['busy'], 
                       json.dumps(serialize_data(busy)))
    
    cur.close()
    conn.close()
    
    return "Cache warmed successfully! All 4 keys populated."

@cashier_bp.route('/cashier-redis/debug-cache')
def debug_cache():
    """Debug endpoint to check what's in Redis cache"""
    try:
        redis_client = get_redis()
        redis_client.ping()
    except Exception as e:
        return f"Redis not available: {e}", 500
    
    keys = [
        CACHE_KEY_TRANSACTIONS,
        CACHE_KEY_STAFF,
        CACHE_KEY_ROOMS,
        CACHE_KEY_BUSY
    ]
    
    result = []
    for key in keys:
        ttl = redis_client.ttl(key)
        exists = redis_client.exists(key)
        result.append(f"{key}: exists={exists}, ttl={ttl}s")
    
    return "<br>".join(result)

@cashier_bp.route('/test-redis-connection')
def test_redis_connection():
    """Test if Redis connection works"""
    try:
        redis_client = get_redis()
        redis_client.ping()
        redis_client.setex("test_key_123", 60, "hello")
        value = redis_client.get("test_key_123")
        return f"Redis OK! Set and got: {value}"
    except Exception as e:
        import traceback
        return f"Redis FAILED: {str(e)}<br><pre>{traceback.format_exc()}</pre>", 500