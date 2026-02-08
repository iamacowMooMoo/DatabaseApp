from flask import render_template, request, redirect, url_for, session
from . import cashier_bp
from db import get_db
import time

@cashier_bp.route('/cashier', methods=['POST'])
def cashier_login():
    """Original working route - login from index page"""
    eid = request.form.get('cashier_id')
    session['cashier_eid'] = eid
    return redirect(url_for('cashier.cashier_dashboard', eid=eid))

@cashier_bp.route('/cashier/<int:eid>')
def cashier_dashboard(eid):
    """Main cashier dashboard with response time tracking"""
    start_time = time.time()
    
    conn = get_db()
    cur = conn.cursor()
    
    # Check if employee exists
    cur.execute("SELECT name, work_name FROM employees WHERE eid = %s", (eid,))
    cashier = cur.fetchone()
    
    if not cashier:
        cur.close()
        conn.close()
        session.pop('cashier_eid', None)
        return redirect(url_for('index'))
    
    # Active transactions
    cur.execute("""
        SELECT 
            t.tid,
            c.cid,
            c.name,
            t.entry_time,
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
    conn.close()
    
    total_time = time.time() - start_time
    
    return render_template('cashier.html',
                         cashier=cashier,
                         eid=eid,
                         transactions=transactions,
                         available_staff=available_staff,
                         available_rooms=available_rooms,
                         busy_therapists=busy_therapists,
                         response_time=f"{total_time:.4f}")

@cashier_bp.route('/cashier-direct')
def cashier_redirect():
    """Redirect to dashboard if logged in, else to index"""
    if 'cashier_eid' in session:
        return redirect(url_for('cashier.cashier_dashboard', eid=session['cashier_eid']))
    return redirect(url_for('index'))