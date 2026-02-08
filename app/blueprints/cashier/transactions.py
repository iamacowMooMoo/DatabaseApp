from flask import render_template, request, redirect, url_for, session
from . import cashier_bp
from db import get_db
from .cache_utils import invalidate_transactions_cache

@cashier_bp.route('/cashier/create-transaction', methods=['POST'])
def create_transaction():
    """Create new transaction for selected customer with entry time"""
    cid = request.form.get('customer_id')
    cashier_eid = session.get('cashier_eid', 1)
    
    conn = get_db()
    cur = conn.cursor()
    
    # UPDATED: Initialize bill-level discount fields
    cur.execute("""
        INSERT INTO transactions 
        (cid, cashier_eid, entry_time, status, 
         total_cost, total_discount, total_paid,
         billlevel_discount, billlevel_discount_type)
        VALUES (%s, %s, CURRENT_TIMESTAMP, 'pending', 0, 0, 0, 0, 'none')
        RETURNING tid
    """, (cid, cashier_eid))
    
    tid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('cashier.transaction_detail', tid=tid))

@cashier_bp.route('/cashier/create-transaction-for-customer/<int:cid>')
def create_transaction_for_customer(cid):
    """Create transaction immediately after customer registration"""
    cashier_eid = session.get('cashier_eid', 1)
    
    conn = get_db()
    cur = conn.cursor()
    
    # UPDATED: Initialize bill-level discount fields
    cur.execute("""
        INSERT INTO transactions 
        (cid, cashier_eid, entry_time, status, 
         total_cost, total_discount, total_paid,
         billlevel_discount, billlevel_discount_type)
        VALUES (%s, %s, CURRENT_TIMESTAMP, 'pending', 0, 0, 0, 0, 'none')
        RETURNING tid
    """, (cid, cashier_eid))
    
    tid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('cashier.transaction_detail', tid=tid))

@cashier_bp.route('/cashier/transaction/<int:tid>')
def transaction_detail(tid):
    """Transaction detail page with payment and service status info"""
    conn = get_db()
    cur = conn.cursor()
    
    # Get transaction info including exit_time
    cur.execute("""
        SELECT t.tid, c.name, c.mobile_number, t.entry_time, t.status,
               t.total_cost, t.total_paid, t.total_discount, t.exit_time
        FROM transactions t
        JOIN customers c ON t.cid = c.cid
        WHERE t.tid = %s
    """, (tid,))
    transaction = cur.fetchone()
    
    if not transaction:
        return "Transaction not found", 404
    
    # Get transaction items with room info and status
    cur.execute("""
        SELECT ti.ttid, s.name, e.work_name, ti.cost, ti.item_discount, 
               ti.scheduled_start, ti.actual_start, ti.actual_end,
               ti.item_discount_type, r.room_name, s.sid, e.eid, ti.rid
        FROM transaction_items ti
        JOIN services s ON ti.sid = s.sid
        JOIN employees e ON ti.therapist_eid = e.eid
        JOIN room r ON ti.rid = r.rid
        WHERE ti.tid = %s
        ORDER BY ti.scheduled_start
    """, (tid,))
    items = cur.fetchall()
    
    # Get payment history
    cur.execute("""
        SELECT pid, payment_method, payment_amount, payment_time
        FROM payments
        WHERE tid = %s
        ORDER BY payment_time DESC
    """, (tid,))
    payments = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # Calculate outstanding
    total_due = transaction[5] - transaction[7]  # total_cost - total_discount
    outstanding = total_due - transaction[6]  # minus total_paid
    
    return render_template('cashier_transaction.html',
                         transaction=transaction,
                         items=items,
                         payments=payments,
                         total_paid=transaction[6],
                         outstanding=max(0, outstanding),
                         cashier_eid=session.get('cashier_eid', 1))

@cashier_bp.route('/cashier/record-exit/<int:tid>', methods=['POST'])
def record_exit(tid):
    """Record customer exit time for the transaction"""
    conn = get_db()
    cur = conn.cursor()
    
    # Verify transaction exists and has entry time but no exit time
    cur.execute("""
        SELECT entry_time, exit_time, total_cost, total_discount, total_paid, status
        FROM transactions 
        WHERE tid = %s
    """, (tid,))
    txn = cur.fetchone()
    
    if not txn:
        cur.close()
        conn.close()
        return "Transaction not found", 404
    
    if not txn[0]:  # No entry time
        cur.close()
        conn.close()
        return "No entry time recorded", 400
    
    if txn[1]:  # Exit time already exists
        cur.close()
        conn.close()
        return "Exit already recorded", 400
    
    # Calculate if fully paid
    total_due = txn[2] - txn[3]  # total_cost - total_discount
    outstanding = total_due - txn[4]  # minus total_paid
    
    # If fully paid, mark as completed. Otherwise keep current status
    new_status = 'completed' if outstanding <= 0 else txn[5]
    
    # Record exit time
    cur.execute("""
        UPDATE transactions 
        SET exit_time = CURRENT_TIMESTAMP,
            status = %s
        WHERE tid = %s
    """, (new_status, tid))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('cashier.cashier_dashboard', eid=session.get('cashier_eid', 1)))
    