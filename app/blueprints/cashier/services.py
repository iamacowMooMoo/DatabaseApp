from flask import render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
from . import cashier_bp
from db import get_db, get_redis
from .cache_utils import serialize_data, invalidate_availability_cache, invalidate_all_dashboard_cache

def refresh_availability_cache(redis_client):
    """
    Refresh availability cache immediately after invalidation.
    This ensures next user always hits cache.
    """
    conn = get_db()
    cur = conn.cursor()
    
    # Repopulate staff availability (30 min TTL)
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
    redis_client.setex("spa:availability:staff", 1800, json.dumps(serialize_data(staff)))
    
    # Repopulate rooms (30 min TTL)
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
    redis_client.setex("spa:availability:rooms", 1800, json.dumps(serialize_data(rooms)))
    
    # Repopulate busy therapists (30 min TTL)
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
    redis_client.setex("spa:availability:busy", 1800, json.dumps(serialize_data(busy)))
    
    cur.close()
    conn.close()

def invalidate_and_refresh_availability_cache(redis_client):
    """Invalidate and immediately refresh availability cache"""
    keys_to_delete = [
        "spa:availability:staff",
        "spa:availability:rooms", 
        "spa:availability:busy"
    ]
    for key in keys_to_delete:
        redis_client.delete(key)
    
    # Repopulate with fresh data so next request hits cache
    refresh_availability_cache(redis_client)

# ==================== SERVICE SCHEDULING ====================

@cashier_bp.route('/cashier/transaction/<int:tid>/schedule')
def schedule_service(tid):
    """Step 1: Select Date and Time"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT t.tid, c.name, c.mobile_number
        FROM transactions t
        JOIN customers c ON t.cid = c.cid
        WHERE t.tid = %s
    """, (tid,))
    transaction = cur.fetchone()
    
    if not transaction:
        return "Transaction not found", 404
    
    hours = list(range(0, 24))
    minutes = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    default_date = datetime.now().strftime('%Y-%m-%d')
    
    cur.close()
    conn.close()
    
    return render_template('cashier_schedule.html',
                         transaction=transaction,
                         hours=hours,
                         minutes=minutes,
                         default_date=default_date)

@cashier_bp.route('/cashier/transaction/<int:tid>/add-service-step2', methods=['POST'])
def add_service_step2(tid):
    """Step 2: Select Service with discount option"""
    scheduled_date = request.form.get('scheduled_date')
    scheduled_hour = request.form.get('scheduled_hour')
    scheduled_minute = request.form.get('scheduled_minute')
    
    scheduled_start = f"{scheduled_date} {scheduled_hour}:{scheduled_minute}:00"
    session[f'txn_{tid}_scheduled_start'] = scheduled_start
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT t.tid, c.name
        FROM transactions t
        JOIN customers c ON t.cid = c.cid
        WHERE t.tid = %s
    """, (tid,))
    transaction = cur.fetchone()
    
    cur.execute("""
        SELECT s.sid, s.name, s.base_cost, s.duration_minutes, rd.role_type
        FROM services s
        JOIN role_definition rd ON s.rdid = rd.rdid
        WHERE s.active_until IS NULL OR s.active_until >= CURRENT_DATE
        ORDER BY s.name
    """)
    services = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('cashier_select_service.html',
                         transaction=transaction,
                         services=services,
                         scheduled_start=scheduled_start,
                         tid=tid)

@cashier_bp.route('/cashier/transaction/<int:tid>/add-service-step3', methods=['POST'])
def add_service_step3(tid):
    """Step 3: Select Therapist and Room - WITH CUSTOMER CONFLICT CHECK"""
    service_id = request.form.get('service_id')
    scheduled_start = session.get(f'txn_{tid}_scheduled_start')
    
    if not scheduled_start:
        return "Session expired", 400
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get service details
    cur.execute("""
        SELECT s.sid, s.name, s.base_cost, s.duration_minutes, s.rdid, rd.role_type
        FROM services s
        JOIN role_definition rd ON s.rdid = rd.rdid
        WHERE s.sid = %s
    """, (service_id,))
    service = cur.fetchone()
    
    if not service:
        return "Service not found", 404
    
    service_duration = service[3]
    required_role = service[5]
    
    # Calculate scheduled end
    cur.execute("SELECT %s::timestamp + INTERVAL '%s minutes'", (scheduled_start, service_duration))
    scheduled_end = cur.fetchone()[0]
    
    # Check for customer time conflicts
    cur.execute("SELECT cid FROM transactions WHERE tid = %s", (tid,))
    customer_row = cur.fetchone()
    if not customer_row:
        cur.close()
        conn.close()
        return "Transaction not found", 404
    
    customer_cid = customer_row[0]
    
    # Check if customer already has a booking at this time
    cur.execute("""
        SELECT s.name, ti.scheduled_start, ti.scheduled_end
        FROM transaction_items ti
        JOIN transactions t ON ti.tid = t.tid
        JOIN services s ON ti.sid = s.sid
        WHERE t.cid = %s
        AND ti.scheduled_start < %s
        AND ti.scheduled_end > %s
        AND ti.actual_end IS NULL
        LIMIT 1
    """, (customer_cid, scheduled_end, scheduled_start))
    
    conflict = cur.fetchone()
    if conflict:
        cur.close()
        conn.close()
        return render_template('cashier_error.html', 
                             message=f"Customer already has a booking during this time: {conflict[0]} "
                                     f"({conflict[1].strftime('%H:%M')} - {conflict[2].strftime('%H:%M')})")
    
    session[f'txn_{tid}_service_id'] = service_id
    session[f'txn_{tid}_scheduled_end'] = scheduled_end.strftime('%Y-%m-%d %H:%M:%S')
    
    # Available therapists with required role
    cur.execute("""
        SELECT DISTINCT e.eid, e.work_name, rd.role_type
        FROM employees e
        JOIN roles r ON e.eid = r.eid 
            AND r.start_date <= CURRENT_DATE 
            AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE rd.role_type = %s
        AND (e.employment_end IS NULL OR e.employment_end > CURRENT_DATE)
        AND NOT EXISTS (
            SELECT 1 FROM transaction_items ti
            WHERE ti.therapist_eid = e.eid
            AND ti.scheduled_start < %s
            AND ti.scheduled_end > %s
            AND ti.actual_end IS NULL
        )
        ORDER BY e.work_name
    """, (required_role, scheduled_end, scheduled_start))
    
    available_therapists = cur.fetchall()
    
    # Available rooms - FIXED: removed "ti." prefix
    cur.execute("""
        SELECT rid, room_name
        FROM room
        WHERE rid NOT IN (
            SELECT DISTINCT rid 
            FROM transaction_items
            WHERE scheduled_start < %s
            AND scheduled_end > %s
            AND actual_end IS NULL
        )
        ORDER BY room_name
    """, (scheduled_end, scheduled_start))
    
    available_rooms = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('cashier_select_therapist_room.html',
                         transaction={'tid': tid, 'service_name': service[1]},
                         service=service,
                         scheduled_start=scheduled_start,
                         scheduled_end=scheduled_end,
                         therapists=available_therapists,
                         rooms=available_rooms,
                         tid=tid)

@cashier_bp.route('/cashier/transaction/<int:tid>/add-service-final', methods=['POST'])
def add_service_final(tid):
    """Step 4: Save the service with discount"""
    therapist_id = request.form.get('therapist_id')
    room_id = request.form.get('room_id')
    
    service_id = session.get(f'txn_{tid}_service_id')
    scheduled_start = session.get(f'txn_{tid}_scheduled_start')
    scheduled_end = session.get(f'txn_{tid}_scheduled_end')
    item_discount = float(request.form.get('item_discount', 0))
    item_discount_type = request.form.get('item_discount_type', 'none')
    
    if not all([service_id, scheduled_start, scheduled_end]):
        return "Session expired", 400
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT base_cost FROM services WHERE sid = %s", (service_id,))
    service = cur.fetchone()
    cost = service[0] if service else 0
    
    # Validate discount doesn't exceed cost
    item_discount = min(item_discount, cost)
    
    cur.execute("""
        INSERT INTO transaction_items 
        (tid, sid, therapist_eid, rid, scheduled_start, scheduled_end, cost, item_discount, item_discount_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::discount_type_enum)
    """, (tid, service_id, therapist_id, room_id, scheduled_start, scheduled_end, cost, item_discount, item_discount_type))
    
    conn.commit()
    
    # Clear session
    for key in [f'txn_{tid}_service_id', f'txn_{tid}_scheduled_start', f'txn_{tid}_scheduled_end']:
        session.pop(key, None)
    
    cur.close()
    conn.close()
    
    # Invalidate and refresh Redis cache
    try:
        redis_client = get_redis()
        invalidate_and_refresh_availability_cache(redis_client)
    except Exception as e:
        print(f"Redis cache refresh failed: {e}")
    
    return redirect(url_for('cashier.transaction_detail', tid=tid))

# ==================== SERVICE MANAGEMENT ====================

@cashier_bp.route('/cashier/delete-item/<int:ttid>', methods=['POST'])
def delete_transaction_item(ttid):
    """Delete a service item that hasn't started yet"""
    conn = get_db()
    cur = conn.cursor()
    
    # Verify item exists and hasn't started
    cur.execute("""
        SELECT tid, actual_start, cost 
        FROM transaction_items 
        WHERE ttid = %s
    """, (ttid,))
    item = cur.fetchone()
    
    if not item:
        cur.close()
        conn.close()
        return "Item not found", 404
    
    if item[1]:
        cur.close()
        conn.close()
        return "Cannot delete - service has already started", 400
    
    tid = item[0]
    
    # Delete the item
    cur.execute("DELETE FROM transaction_items WHERE ttid = %s", (ttid,))
    
    # Update transaction totals
    cur.execute("""
        UPDATE transactions 
        SET total_cost = total_cost - %s
        WHERE tid = %s
    """, (item[2], tid))
    
    conn.commit()
    cur.close()
    conn.close()
    
    # Invalidate and refresh Redis cache
    try:
        redis_client = get_redis()
        invalidate_and_refresh_availability_cache(redis_client)
    except Exception as e:
        print(f"Redis cache refresh failed: {e}")
    
    return redirect(url_for('cashier.transaction_detail', tid=tid))

@cashier_bp.route('/cashier/start-service/<int:ttid>', methods=['POST'])
def start_service(ttid):
    """Record actual start time for a service"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT tid, actual_start, actual_end 
        FROM transaction_items 
        WHERE ttid = %s
    """, (ttid,))
    item = cur.fetchone()
    
    if not item:
        cur.close()
        conn.close()
        return "Service not found", 404
    
    if item[1]:
        cur.close()
        conn.close()
        return "Service already started", 400
    
    cur.execute("""
        UPDATE transaction_items 
        SET actual_start = CURRENT_TIMESTAMP
        WHERE ttid = %s
    """, (ttid,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    # Invalidate and refresh Redis cache
    try:
        redis_client = get_redis()
        invalidate_and_refresh_availability_cache(redis_client)
    except Exception as e:
        print(f"Redis cache refresh failed: {e}")
    
    return redirect(url_for('cashier.transaction_detail', tid=item[0]))

@cashier_bp.route('/cashier/end-service/<int:ttid>', methods=['POST'])
def end_service(ttid):
    """Record actual end time for a service"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT tid, actual_start, actual_end 
        FROM transaction_items 
        WHERE ttid = %s
    """, (ttid,))
    item = cur.fetchone()
    
    if not item:
        cur.close()
        conn.close()
        return "Service not found", 404
    
    if not item[1]:
        cur.close()
        conn.close()
        return "Service hasn't started yet", 400
    
    if item[2]:
        cur.close()
        conn.close()
        return "Service already ended", 400
    
    cur.execute("""
        UPDATE transaction_items 
        SET actual_end = CURRENT_TIMESTAMP
        WHERE ttid = %s
    """, (ttid,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    # Invalidate and refresh Redis cache
    try:
        redis_client = get_redis()
        invalidate_and_refresh_availability_cache(redis_client)
    except Exception as e:
        print(f"Redis cache refresh failed: {e}")
    
    return redirect(url_for('cashier.transaction_detail', tid=item[0]))

@cashier_bp.route('/cashier/api/edit-options/<int:tid>')
def get_edit_options(tid):
    """Get available options for full edit"""
    ttid = request.args.get('ttid')
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get current item details
    cur.execute("""
        SELECT scheduled_start, scheduled_end, sid
        FROM transaction_items
        WHERE ttid = %s
    """, (ttid,))
    current = cur.fetchone()
    
    if not current:
        cur.close()
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    
    scheduled_start, scheduled_end, current_sid = current
    
    # Get all services
    cur.execute("""
        SELECT s.sid, s.name, s.base_cost, s.duration_minutes, rd.role_type
        FROM services s
        JOIN role_definition rd ON s.rdid = rd.rdid
        WHERE s.active_until IS NULL OR s.active_until >= CURRENT_DATE
        ORDER BY s.name
    """)
    services = []
    for row in cur.fetchall():
        services.append({
            'id': row[0],
            'name': row[1],
            'cost': float(row[2]),
            'duration': row[3],
            'role': row[4]
        })
    
    # Get available therapists (excluding current item)
    cur.execute("""
        SELECT DISTINCT e.eid, e.work_name, rd.role_type
        FROM employees e
        JOIN roles r ON e.eid = r.eid 
            AND r.start_date <= CURRENT_DATE 
            AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE (e.employment_end IS NULL OR e.employment_end >= CURRENT_DATE)
        AND NOT EXISTS (
            SELECT 1 FROM transaction_items ti
            WHERE ti.therapist_eid = e.eid
            AND ti.scheduled_start < %s
            AND ti.scheduled_end > %s
            AND ti.actual_end IS NULL
            AND ti.ttid != %s
        )
        ORDER BY e.work_name
    """, (scheduled_end, scheduled_start, ttid))
    
    therapists = []
    for row in cur.fetchall():
        therapists.append({
            'id': row[0],
            'name': row[1],
            'role': row[2]
        })
    
    # Get available rooms (excluding current item)
    cur.execute("""
        SELECT rid, room_name
        FROM room
        WHERE rid NOT IN (
            SELECT DISTINCT rid 
            FROM transaction_items
            WHERE scheduled_start < %s
            AND scheduled_end > %s
            AND actual_end IS NULL
            AND ttid != %s
        )
        ORDER BY room_name
    """, (scheduled_end, scheduled_start, ttid))
    
    rooms = []
    for row in cur.fetchall():
        rooms.append({
            'id': row[0],
            'name': row[1]
        })
    
    cur.close()
    conn.close()
    
    return jsonify({
        'services': services,
        'therapists': therapists,
        'rooms': rooms
    })

@cashier_bp.route('/cashier/full-edit-item', methods=['POST'])
def full_edit_item():
    """Full edit of a service item - can change everything"""
    ttid = request.form.get('ttid')
    tid = request.form.get('tid')
    service_id = request.form.get('service_id')
    scheduled_date = request.form.get('scheduled_date')
    scheduled_hour = request.form.get('scheduled_hour')
    scheduled_minute = request.form.get('scheduled_minute')
    therapist_id = request.form.get('therapist_id')
    room_id = request.form.get('room_id')
    item_discount = float(request.form.get('item_discount', 0))
    item_discount_type = request.form.get('item_discount_type', 'none')
    
    scheduled_start = f"{scheduled_date} {scheduled_hour}:{scheduled_minute}:00"
    
    conn = get_db()
    cur = conn.cursor()
    
    # Verify item hasn't started
    cur.execute("SELECT actual_start, tid FROM transaction_items WHERE ttid = %s", (ttid,))
    item = cur.fetchone()
    
    if not item:
        cur.close()
        conn.close()
        return "Item not found", 404
    
    if item[0]:
        cur.close()
        conn.close()
        return "Cannot edit - service has already started", 400
    
    # Get service details
    cur.execute("SELECT base_cost, duration_minutes FROM services WHERE sid = %s", (service_id,))
    service = cur.fetchone()
    if not service:
        cur.close()
        conn.close()
        return "Service not found", 404
    
    cost = service[0]
    duration = service[1]
    
    # Calculate scheduled end
    cur.execute("SELECT %s::timestamp + INTERVAL '%s minutes'", (scheduled_start, duration))
    scheduled_end = cur.fetchone()[0]
    
    # Get customer ID for conflict check
    cur.execute("SELECT cid FROM transactions WHERE tid = %s", (tid,))
    customer_cid = cur.fetchone()[0]
    
    # Check for conflicts (excluding current item)
    cur.execute("""
        SELECT s.name, ti.scheduled_start, ti.scheduled_end
        FROM transaction_items ti
        JOIN transactions t ON ti.tid = t.tid
        JOIN services s ON ti.sid = s.sid
        WHERE t.cid = %s
        AND t.tid != %s
        AND ti.ttid != %s
        AND ti.scheduled_start < %s
        AND ti.scheduled_end > %s
        AND ti.actual_end IS NULL
        LIMIT 1
    """, (customer_cid, tid, ttid, scheduled_end, scheduled_start))
    
    conflict = cur.fetchone()
    if conflict:
        cur.close()
        conn.close()
        return render_template('cashier_error.html', 
                             message=f"Customer already has a booking during this time: {conflict[0]} ({conflict[1].strftime('%H:%M')} - {conflict[2].strftime('%H:%M')})")
    
    # Validate discount
    item_discount = min(item_discount, cost)
    
    # Update everything
    cur.execute("""
        UPDATE transaction_items 
        SET sid = %s, therapist_eid = %s, rid = %s,
            scheduled_start = %s, scheduled_end = %s,
            cost = %s, item_discount = %s, item_discount_type = %s::discount_type_enum
        WHERE ttid = %s
    """, (service_id, therapist_id, room_id, scheduled_start, scheduled_end,
          cost, item_discount, item_discount_type, ttid))
    
    conn.commit()
    cur.close()
    conn.close()
    
    # Invalidate and refresh Redis cache
    try:
        redis_client = get_redis()
        invalidate_and_refresh_availability_cache(redis_client)
    except Exception as e:
        print(f"Redis cache refresh failed: {e}")
    
    return redirect(url_for('cashier.transaction_detail', tid=tid))