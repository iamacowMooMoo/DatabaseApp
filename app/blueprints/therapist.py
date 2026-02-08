from flask import Blueprint, render_template, request, redirect, url_for, current_app
from db import get_db

therapist_bp = Blueprint('therapist', __name__)

@therapist_bp.route('/therapist', methods=['POST'])
def therapist_login():
    eid = request.form.get('therapist_id')
    return redirect(url_for('therapist.therapist_dashboard', eid=eid))

@therapist_bp.route('/therapist/<int:eid>')
def therapist_dashboard(eid):
    conn = get_db()
    cur = conn.cursor()
    
    # Get therapist basic info
    cur.execute("""
        SELECT e.name, e.work_name, e.employment_start, STRING_AGG(DISTINCT rd.role_type, ', ')
        FROM employees e
        LEFT JOIN roles r ON e.eid = r.eid AND r.start_date <= CURRENT_DATE AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        LEFT JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE e.eid = %s
        GROUP BY e.eid, e.name, e.work_name, e.employment_start
    """, (eid,))
    therapist = cur.fetchone()
    
    if not therapist:
        return "Therapist not found", 404
    
    # Jobs Today - services completed today
    cur.execute("""
        SELECT 
            s.name as service_name,
            ti.cost - ti.item_discount as final_cost,
            ti.actual_start,
            ti.actual_end,
            c.cid,
            c.name as customer_name
        FROM transaction_items ti
        JOIN services s ON ti.sid = s.sid
        JOIN transactions t ON ti.tid = t.tid
        JOIN customers c ON t.cid = c.cid
        WHERE ti.therapist_eid = %s
            AND ti.actual_start::date = CURRENT_DATE
            AND ti.actual_end IS NOT NULL
        ORDER BY ti.actual_start DESC
    """, (eid,))
    jobs_today = cur.fetchall()
    
    # Jobs Yesterday - services completed yesterday
    cur.execute("""
        SELECT 
            s.name as service_name,
            ti.cost - ti.item_discount as final_cost,
            ti.actual_start,
            ti.actual_end,
            c.cid,
            c.name as customer_name
        FROM transaction_items ti
        JOIN services s ON ti.sid = s.sid
        JOIN transactions t ON ti.tid = t.tid
        JOIN customers c ON t.cid = c.cid
        WHERE ti.therapist_eid = %s
            AND ti.actual_start::date = CURRENT_DATE - INTERVAL '1 day'
            AND ti.actual_end IS NOT NULL
        ORDER BY ti.actual_start DESC
    """, (eid,))
    jobs_yesterday = cur.fetchall()
    
    # Stats for different periods
    stats = {}
    for period, sql in [
        ('today', "ti.actual_start::date = CURRENT_DATE"),
        ('week', "ti.actual_start >= DATE_TRUNC('week', CURRENT_DATE)"),
        ('month', "ti.actual_start >= DATE_TRUNC('month', CURRENT_DATE)"),
        ('ytd', "ti.actual_start >= DATE_TRUNC('year', CURRENT_DATE)")
    ]:
        cur.execute(f"""
            SELECT COUNT(*), COALESCE(SUM(cost - item_discount), 0)
            FROM transaction_items ti
            JOIN transactions t ON ti.tid = t.tid
            WHERE ti.therapist_eid = %s AND {sql} AND t.status IN ('completed', 'paid')
        """, (eid,))
        result = cur.fetchone()
        stats[period] = (result[0], float(result[1]) if result[1] else 0.0)
    
    # ============================================
    # REAL WINDOW FUNCTION - Monthly Leaderboard
    # ============================================
    
    window_function_sql = """
WITH therapist_revenue AS (
    SELECT 
        e.eid,
        e.work_name,
        COALESCE(SUM(ti.cost - ti.item_discount), 0) as revenue
    FROM employees e
    JOIN roles r ON e.eid = r.eid 
        AND r.start_date <= CURRENT_DATE
        AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
    JOIN role_definition rd ON r.rdid = rd.rdid 
        AND (rd.role_type ILIKE '%%Therapist%%' 
             OR rd.role_type ILIKE '%%Beautician%%' 
             OR rd.role_type ILIKE '%%Doctor%%')
    LEFT JOIN transaction_items ti ON e.eid = ti.therapist_eid
        AND ti.actual_start >= DATE_TRUNC('month', CURRENT_DATE)
        AND ti.actual_end IS NOT NULL
    LEFT JOIN transactions t ON ti.tid = t.tid AND t.status IN ('completed', 'paid')
    WHERE (e.employment_end IS NULL OR e.employment_end >= CURRENT_DATE)
    GROUP BY e.eid, e.work_name
),
ranked_therapists AS (
    SELECT 
        eid,
        work_name,
        revenue,
        RANK() OVER (ORDER BY revenue DESC) as rank,
        LAG(revenue, 1) OVER (ORDER BY revenue DESC) as person_above_revenue,
        LEAD(revenue, 1) OVER (ORDER BY revenue DESC) as person_below_revenue,
        FIRST_VALUE(revenue) OVER (ORDER BY revenue DESC) as leader_revenue,
        COUNT(*) OVER () as total_therapists
    FROM therapist_revenue
)
SELECT * FROM ranked_therapists
WHERE eid = %(eid)s;
    """.strip()
        
    # Execute window function query
    cur.execute(window_function_sql, {'eid': eid})
    row = cur.fetchone()
    
    if row:
        revenue = float(row[2]) if row[2] else 0.0
        rank = row[3]
        person_above = float(row[4]) if row[4] else None
        person_below = float(row[5]) if row[5] else None
        leader_revenue = float(row[6]) if row[6] else 0.0
        total_therapists = row[7]
        
        # Calculate gaps using window function results
        gap_to_leader = leader_revenue - revenue
        
        if person_below:
            gap_to_next = person_below - revenue
        else:
            gap_to_next = 0  # Already last
        
        if person_above:
            gap_from_above = revenue - person_above
        else:
            gap_from_above = 0  # Already first
        
        gap_from_8k = 8000.0 - revenue
        bonus_status = 'Bonus Achieved! 🎉' if revenue >= 8000 else f'Needs ${gap_from_8k:.2f} more'
        
        leaderboard = {
            'eid': eid,
            'work_name': row[1],
            'revenue': revenue,
            'rank': rank,
            'total_therapists': total_therapists,
            'leader_revenue': leader_revenue,
            'gap_to_leader': gap_to_leader,
            'person_above_revenue': person_above,
            'gap_from_above': gap_from_above,
            'person_below_revenue': person_below,
            'gap_to_next': gap_to_next,
            'gap_from_8k': gap_from_8k,
            'bonus_status': bonus_status,
            'is_leader': rank == 1
        }
        
        current_app.logger.info(f"Window Function Leaderboard: Rank {rank} of {total_therapists}, Revenue ${revenue}")
    else:
        # Therapist not found in list (shouldn't happen, but handle gracefully)
        leaderboard = {
            'eid': eid,
            'work_name': therapist[1],
            'revenue': 0.0,
            'rank': 0,
            'total_therapists': 0,
            'leader_revenue': 0.0,
            'gap_to_leader': 0.0,
            'person_above_revenue': None,
            'gap_from_above': 0.0,
            'person_below_revenue': None,
            'gap_to_next': 0.0,
            'gap_from_8k': 8000.0,
            'bonus_status': 'Needs $8000.00 more',
            'is_leader': False
        }
    
    # Top 5 Customers (regular query - no window function needed here)
    top_customers_sql = """
SELECT 
    c.cid,
    c.name,
    COALESCE(SUM(ti.cost - ti.item_discount), 0) as total_spend,
    COUNT(DISTINCT t.tid) as total_visits,
    MAX(ti.actual_end) as last_visit_date,
    COALESCE(SUM(ti.cost - ti.item_discount) / NULLIF(COUNT(DISTINCT t.tid), 0), 0) as avg_spend_per_visit,
    COALESCE(AVG(EXTRACT(EPOCH FROM (ti.actual_end - ti.actual_start))/60), 0) as avg_minutes_per_visit
FROM customers c
JOIN transactions t ON c.cid = t.cid
JOIN transaction_items ti ON t.tid = ti.tid
WHERE ti.therapist_eid = %s
    AND ti.actual_start IS NOT NULL
    AND ti.actual_end IS NOT NULL
    AND t.status IN ('completed', 'paid')
GROUP BY c.cid, c.name
ORDER BY total_spend DESC
LIMIT 5;
    """.strip()
    
    cur.execute(top_customers_sql, (eid,))
    top_customers = cur.fetchall()
    
    # Convert customer stats to float
    top_customers_converted = []
    for customer in top_customers:
        customer_list = list(customer)
        customer_list[2] = float(customer_list[2]) if customer_list[2] else 0.0
        customer_list[5] = float(customer_list[5]) if customer_list[5] else 0.0
        customer_list[6] = float(customer_list[6]) if customer_list[6] else 0.0
        top_customers_converted.append(tuple(customer_list))
    
    cur.close()
    conn.close()
    
    return render_template('therapist.html', 
                         therapist=therapist, 
                         eid=eid, 
                         jobs_today=jobs_today,
                         jobs_yesterday=jobs_yesterday,
                         stats=stats, 
                         leaderboard=leaderboard,
                         window_sql=window_function_sql,
                         top_customers=top_customers_converted,
                         top_customers_sql=top_customers_sql)