from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from db import get_db

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/customer', methods=['POST'])
def customer_login():
    """Customer login - handles both dropdown and old search methods"""
    search_type = request.form.get('search_type')
    
    if search_type == 'dropdown':
        customer_id = request.form.get('customer_id')
        if customer_id:
            return redirect(url_for('customer.customer_dashboard', cid=customer_id))
        return "No customer selected", 400
    
    # Old search method (kept for compatibility)
    search_term = request.form.get('search_term')
    search_by = request.form.get('search_by')
    
    if not search_term:
        return "No search term provided", 400
    
    conn = get_db()
    cur = conn.cursor()
    
    if search_by == 'mobile':
        cur.execute("""
            SELECT cid, name, mobile_number 
            FROM customers 
            WHERE mobile_number ILIKE %s
            LIMIT 1
        """, (f'%{search_term}%',))
    elif search_by == 'name':
        cur.execute("""
            SELECT cid, name, mobile_number 
            FROM customers 
            WHERE name ILIKE %s
            LIMIT 1
        """, (f'%{search_term}%',))
    else:  # cid
        cur.execute("""
            SELECT cid, name, mobile_number 
            FROM customers 
            WHERE cid = %s
        """, (search_term,))
    
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if result:
        return redirect(url_for('customer.customer_dashboard', cid=result[0]))
    return "Customer not found", 404

@customer_bp.route('/customer-direct', methods=['POST'])
def customer_direct():
    """Direct access after selecting from live search results"""
    customer_id = request.form.get('customer_id')
    if customer_id:
        return redirect(url_for('customer.customer_dashboard', cid=customer_id))
    return "No customer selected", 400

@customer_bp.route('/api/search-customers')
def search_customers_api():
    """AJAX API for live customer search"""
    query = request.args.get('q', '').strip()
    search_by = request.args.get('by', 'name')  # 'name' or 'mobile'
    
    if not query or len(query) < 2:
        return jsonify([])
    
    conn = get_db()
    cur = conn.cursor()
    
    if search_by == 'mobile':
        # Search by mobile number (partial match)
        cur.execute("""
            SELECT cid, name, mobile_number, nric_fin_passport_no
            FROM customers
            WHERE mobile_number ILIKE %s
            ORDER BY name
            LIMIT 10
        """, (f'%{query}%',))
    else:
        # Search by name (partial match)
        cur.execute("""
            SELECT cid, name, mobile_number, nric_fin_passport_no
            FROM customers
            WHERE name ILIKE %s
            ORDER BY name
            LIMIT 10
        """, (f'%{query}%',))
    
    results = cur.fetchall()
    cur.close()
    conn.close()
    
    # Convert to list of dicts for JSON
    customers = []
    for row in results:
        customers.append({
            'cid': row[0],
            'name': row[1],
            'mobile': row[2],
            'nric': row[3]
        })
    
    return jsonify(customers)

@customer_bp.route('/customer/<int:cid>')
def customer_dashboard(cid):
    """Customer dashboard"""
    conn = get_db()
    cur = conn.cursor()
    
    # Get customer info
    cur.execute("SELECT name FROM customers WHERE cid = %s", (cid,))
    customer = cur.fetchone()
    if not customer:
        return "Customer not found", 404
    
    # SQL queries as strings to display
    top_therapists_sql = """
        SELECT e.work_name, COUNT(*) as services_done
        FROM transaction_items ti
        JOIN employees e ON ti.therapist_eid = e.eid
        JOIN transactions t ON ti.tid = t.tid
        WHERE t.cid = %s AND t.status IN ('completed', 'paid')
        GROUP BY e.eid, e.work_name
        ORDER BY services_done DESC
        LIMIT 3
    """
    
    last_therapist_sql = """
        SELECT e.work_name, ti.actual_end, s.name
        FROM transaction_items ti
        JOIN employees e ON ti.therapist_eid = e.eid
        JOIN services s ON ti.sid = s.sid
        JOIN transactions t ON ti.tid = t.tid
        WHERE t.cid = %s AND ti.actual_end IS NOT NULL
        ORDER BY ti.actual_end DESC
        LIMIT 1
    """
    
    invoices_sql = """
        SELECT t.tid, t.entry_time, t.total_cost, t.total_discount, 
               (t.total_cost - t.total_discount), t.total_paid, t.status
        FROM transactions t
        WHERE t.cid = %s
        ORDER BY t.entry_time DESC
    """
    
    # Execute queries
    cur.execute(top_therapists_sql, (cid,))
    top_therapists = cur.fetchall()
    
    cur.execute(last_therapist_sql, (cid,))
    last_therapist = cur.fetchone()
    
    cur.execute(invoices_sql, (cid,))
    invoices = cur.fetchall()
    
    # Invoice items
    invoice_details = []
    for inv in invoices:
        cur.execute("""
            SELECT s.name, e.work_name, ti.cost, ti.item_discount, (ti.cost - ti.item_discount)
            FROM transaction_items ti
            JOIN services s ON ti.sid = s.sid
            JOIN employees e ON ti.therapist_eid = e.eid
            WHERE ti.tid = %s
        """, (inv[0],))
        items = cur.fetchall()
        invoice_details.append({'invoice': inv, 'invoice_items': items})
    
    cur.close()
    conn.close()
    
    return render_template('customer.html',
                         customer_name=customer[0],
                         cid=cid,
                         top_therapists=top_therapists,
                         last_therapist=last_therapist,
                         invoices=invoice_details,
                         sql_queries={
                             'top_therapists': top_therapists_sql,
                             'last_therapist': last_therapist_sql,
                             'invoices': invoices_sql
                         })