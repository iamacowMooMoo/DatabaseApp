from flask import render_template, request, redirect, url_for, jsonify, session
from . import cashier_bp
from db import get_db

@cashier_bp.route('/cashier/new-transaction')
def new_transaction():
    """Step 1: Select or search for customer"""
    return render_template('cashier_select_customer.html')

@cashier_bp.route('/cashier/api/search-customers')
def search_customers_cashier():
    """AJAX API for customer search in cashier interface"""
    query = request.args.get('q', '').strip()
    search_by = request.args.get('by', 'name')
    
    if not query or len(query) < 2:
        return jsonify([])
    
    conn = get_db()
    cur = conn.cursor()
    
    if search_by == 'mobile':
        cur.execute("""
            SELECT cid, name, mobile_number, nric_fin_passport_no, country_code
            FROM customers
            WHERE mobile_number ILIKE %s
            ORDER BY name
            LIMIT 10
        """, (f'%{query}%',))
    else:
        cur.execute("""
            SELECT cid, name, mobile_number, nric_fin_passport_no, country_code
            FROM customers
            WHERE name ILIKE %s
            ORDER BY name
            LIMIT 10
        """, (f'%{query}%',))
    
    results = cur.fetchall()
    cur.close()
    conn.close()
    
    customers = []
    for row in results:
        customers.append({
            'cid': row[0],
            'name': row[1],
            'mobile': row[2],
            'nric': row[3],
            'country': row[4]
        })
    
    return jsonify(customers)

@cashier_bp.route('/cashier/register-customer', methods=['GET', 'POST'])
def register_customer():
    """Register new customer"""
    if request.method == 'POST':
        name = request.form.get('name')
        mobile = request.form.get('mobile')
        nric = request.form.get('nric')
        country_code = request.form.get('country_code', 'SG')
        gender = request.form.get('gender', 'Male')
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO customers (nric_fin_passport_no, name, gender, mobile_number, country_code)
            VALUES (%s, %s, %s::gender_enum, %s, %s)
            RETURNING cid
        """, (nric, name, gender, mobile, country_code))
        
        cid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return redirect(url_for('cashier.create_transaction_for_customer', cid=cid))
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT country_code, country_name FROM nationcode ORDER BY country_name")
    countries = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('cashier_register_customer.html', countries=countries)