from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from db import get_db
from datetime import datetime, date, timedelta
import time

management_bp = Blueprint('management', __name__, url_prefix='/management')

@management_bp.route('/debug-time')
def debug_time():
    return jsonify({
        'python_now': datetime.now().isoformat(),
        'python_utc': datetime.utcnow().isoformat(),
        'system_time': time.strftime('%Y-%m-%d %H:%M:%S %Z'),
        'timezone': time.tzname if hasattr(time, 'tzname') else 'unknown'
    })

def get_payment_breakdown(cur, start_date, end_date=None):
    """
    Get payment breakdown by method for a given date range
    Returns list of dicts with method and amount
    """
    if end_date is None:
        end_date = datetime.now()
    
    query = """
        SELECT 
            p.payment_method,
            COALESCE(SUM(p.payment_amount), 0) as total
        FROM payments p
        JOIN transactions t ON p.tid = t.tid
        WHERE p.payment_time >= %s 
          AND p.payment_time < %s
        GROUP BY p.payment_method
        ORDER BY total DESC
    """
    
    cur.execute(query, (start_date, end_date))
    results = cur.fetchall()
    
    return [{'method': row[0], 'amount': float(row[1])} for row in results]


def get_services_and_revenue(cur, start_date, end_date=None):
    """
    Get total services count and revenue for a date range
    """
    if end_date is None:
        end_date = datetime.now()
    
    # Count services (transaction items)
    cur.execute("""
        SELECT COUNT(*)
        FROM transaction_items ti
        JOIN transactions t ON ti.tid = t.tid
        WHERE ti.actual_start >= %s 
          AND ti.actual_start < %s
    """, (start_date, end_date))
    
    services = cur.fetchone()[0]
    
    # Get total revenue (from payments, not transaction totals to match reality)
    cur.execute("""
        SELECT COALESCE(SUM(payment_amount), 0)
        FROM payments p
        WHERE p.payment_time >= %s 
          AND p.payment_time < %s
    """, (start_date, end_date))
    
    revenue = float(cur.fetchone()[0])
    
    return services, revenue


def get_room_utilization(cur):
    """
    Get 3 most used and 3 least used rooms using RIGHT JOIN
    Shows ALL rooms even if never booked (0 usage)
    """
    query = """
        SELECT 
            r.room_name,
            COUNT(ti.ttid) as booking_count,
            COALESCE(SUM(ti.cost - ti.item_discount), 0) as revenue
        FROM transaction_items ti
        RIGHT JOIN room r ON ti.rid = r.rid
        GROUP BY r.rid, r.room_name
        ORDER BY booking_count DESC
    """
    cur.execute(query)
    all_rooms = cur.fetchall()
    
    # Split into most used (top 3) and least used (bottom 3)
    most_used = all_rooms[:3] if len(all_rooms) >= 3 else all_rooms
    least_used = all_rooms[-3:] if len(all_rooms) >= 3 else all_rooms
    
    return {
        'most_used': [{'name': r[0], 'bookings': r[1], 'revenue': float(r[2])} for r in most_used],
        'least_used': [{'name': r[0], 'bookings': r[1], 'revenue': float(r[2])} for r in least_used]
    }


def get_average_metrics(cur, start_date, end_date=None):
    """
    Calculate average spend per visit and average service duration
    Uses AVG function for both financial and time metrics
    """
    if end_date is None:
        end_date = datetime.now()
    
    # Average spend per visit (total transaction value / number of transactions)
    cur.execute("""
        SELECT 
            COALESCE(AVG(transaction_total), 0) as avg_spend_per_visit,
            COUNT(*) as total_visits
        FROM (
            SELECT 
                t.tid,
                SUM(ti.cost - ti.item_discount) as transaction_total
            FROM transactions t
            JOIN transaction_items ti ON t.tid = ti.tid
            WHERE t.created_at >= %s 
              AND t.created_at < %s
              AND t.status IN ('completed', 'paid')
            GROUP BY t.tid
        ) transaction_totals
    """, (start_date, end_date))
    
    avg_spend_result = cur.fetchone()
    avg_spend = float(avg_spend_result[0]) if avg_spend_result[0] else 0.0
    total_visits = avg_spend_result[1]
    
    # Average service duration in minutes (actual time spent)
    cur.execute("""
        SELECT 
            COALESCE(AVG(
                EXTRACT(EPOCH FROM (ti.actual_end - ti.actual_start))/60
            ), 0) as avg_duration_minutes,
            COUNT(*) as completed_services
        FROM transaction_items ti
        JOIN transactions t ON ti.tid = t.tid
        WHERE ti.actual_start IS NOT NULL
          AND ti.actual_end IS NOT NULL
          AND ti.actual_start >= %s 
          AND ti.actual_start < %s
          AND t.status IN ('completed', 'paid')
    """, (start_date, end_date))
    
    avg_duration_result = cur.fetchone()
    avg_duration = float(avg_duration_result[0]) if avg_duration_result[0] else 0.0
    completed_services = avg_duration_result[1]
    
    return {
        'avg_spend_per_visit': avg_spend,
        'total_visits': total_visits,
        'avg_duration_minutes': avg_duration,
        'completed_services': completed_services
    }


def get_high_spenders_last_month(cur):
    """
    Find customers spending 30% above last month's average
    Uses CTE with HAVING clause for post-aggregation filtering
    """
    query = """
        WITH monthly_stats AS (
            -- First get the overall average
            SELECT AVG(total_spent) as avg_spending
            FROM (
                SELECT SUM(ti.cost - ti.item_discount) as total_spent
                FROM customers c
                JOIN transactions t ON c.cid = t.cid
                JOIN transaction_items ti ON t.tid = ti.tid
                WHERE ti.actual_start >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
                  AND ti.actual_start < DATE_TRUNC('month', CURRENT_DATE)
                  AND t.status IN ('completed', 'paid')
                GROUP BY c.cid
                -- HAVING can be used here if needed for minimum thresholds
            ) customer_totals
        ),
        monthly_customer_spending AS (
            -- Calculate total spending per customer for last month
            SELECT 
                c.cid,
                c.name,
                c.mobile_number,
                SUM(ti.cost - ti.item_discount) as total_spent,
                COUNT(DISTINCT t.tid) as visit_count,
                SUM(ti.cost - ti.item_discount) as customer_total
            FROM customers c
            JOIN transactions t ON c.cid = t.cid
            JOIN transaction_items ti ON t.tid = ti.tid
            WHERE ti.actual_start >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
              AND ti.actual_start < DATE_TRUNC('month', CURRENT_DATE)
              AND t.status IN ('completed', 'paid')
            GROUP BY c.cid, c.name, c.mobile_number
            HAVING SUM(ti.cost - ti.item_discount) > 0  -- HAVING: Only customers who actually spent money
        )
        SELECT 
            mcs.cid,
            mcs.name,
            mcs.mobile_number,
            mcs.total_spent,
            mcs.visit_count,
            ROUND(mcs.total_spent / NULLIF(mcs.visit_count, 0), 2) as avg_per_visit,
            ms.avg_spending as last_month_average,
            ROUND(((mcs.total_spent - ms.avg_spending) / ms.avg_spending * 100), 1) as percent_above_average
        FROM monthly_customer_spending mcs
        CROSS JOIN monthly_stats ms
        WHERE mcs.total_spent >= ms.avg_spending * 1.30
        ORDER BY mcs.total_spent DESC
    """
    
    cur.execute(query)
    results = cur.fetchall()
    
    return [{
        'cid': row[0],
        'name': row[1],
        'mobile': row[2],
        'total_spent': float(row[3]),
        'visit_count': row[4],
        'avg_per_visit': float(row[5]) if row[5] else 0.0,
        'last_month_average': float(row[6]),
        'percent_above': float(row[7])
    } for row in results]


@management_bp.route('/', methods=['GET', 'POST'])
def dashboard():
    """Main management dashboard"""
    manager_id = None
    
    if request.method == 'POST':
        manager_id = request.form.get('management_id')
        if manager_id:
            session['manager_id'] = manager_id
    else:
        # GET request - check session
        manager_id = session.get('manager_id')
    
    if not manager_id:
        return redirect(url_for('index'))  # Back to login if no session
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get manager info
    cur.execute("""
        SELECT e.eid, e.work_name, e.name, rd.role_type
        FROM employees e
        LEFT JOIN roles r ON e.eid = r.eid 
            AND r.start_date <= CURRENT_DATE 
            AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        LEFT JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE e.eid = %s
    """, (manager_id,))
    
    manager = cur.fetchone()
    if not manager:
        session.pop('manager_id', None)
        return "Manager not found", 404
    
    # Calculate date ranges
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)
    
    # Get stats for each period
    daily_services, daily_revenue = get_services_and_revenue(cur, today_start)
    weekly_services, weekly_revenue = get_services_and_revenue(cur, week_start)
    monthly_services, monthly_revenue = get_services_and_revenue(cur, month_start)
    yearly_services, yearly_revenue = get_services_and_revenue(cur, year_start)
    
    # Get payment breakdowns
    daily_payments = get_payment_breakdown(cur, today_start)
    weekly_payments = get_payment_breakdown(cur, week_start)
    monthly_payments = get_payment_breakdown(cur, month_start)
    yearly_payments = get_payment_breakdown(cur, year_start)
    
    # Package data for template
    daily = {
        'services': daily_services,
        'revenue': daily_revenue,
        'payments': daily_payments
    }
    weekly = {
        'services': weekly_services,
        'revenue': weekly_revenue,
        'payments': weekly_payments
    }
    monthly = {
        'services': monthly_services,
        'revenue': monthly_revenue,
        'payments': monthly_payments
    }
    yearly = {
        'services': yearly_services,
        'revenue': yearly_revenue,
        'payments': yearly_payments
    }
    
    # Top 5 therapists this month
    cur.execute("""
        SELECT 
            e.work_name,
            COUNT(ti.ttid) as service_count,
            COALESCE(SUM(ti.cost - ti.item_discount), 0) as revenue
        FROM employees e
        JOIN transaction_items ti ON e.eid = ti.therapist_eid
        JOIN transactions t ON ti.tid = t.tid
        WHERE ti.actual_start >= %s
          AND ti.actual_start < %s
        GROUP BY e.eid, e.work_name
        ORDER BY revenue DESC
        LIMIT 5
    """, (month_start, now))
    
    top_therapists = cur.fetchall()
    
    # Currently working (services in progress)
    cur.execute("""
        SELECT 
            e.work_name,
            r.room_name,
            ti.ttid,
            ti.scheduled_end,
            EXTRACT(EPOCH FROM (ti.scheduled_end - NOW()))/60 as minutes_left
        FROM transaction_items ti
        JOIN employees e ON ti.therapist_eid = e.eid
        JOIN room r ON ti.rid = r.rid
        WHERE ti.actual_start IS NOT NULL
          AND ti.actual_end IS NULL
          AND ti.scheduled_end > NOW()
        ORDER BY ti.scheduled_end
    """)
    
    working_now = cur.fetchall()
    
    # Available therapists (not in working_now)
    cur.execute("""
        SELECT DISTINCT e.work_name
        FROM employees e
        JOIN roles r ON e.eid = r.eid
        JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE rd.role_type ILIKE '%therapist%'
          AND (e.employment_end IS NULL OR e.employment_end > CURRENT_DATE)
          AND r.start_date <= CURRENT_DATE
          AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
          AND e.eid NOT IN (
              SELECT therapist_eid 
              FROM transaction_items 
              WHERE actual_start IS NOT NULL 
                AND actual_end IS NULL
          )
        ORDER BY e.work_name
    """)
    
    available = cur.fetchall()
    
    # ========== ADVANCED SQL QUERIES ==========
    
    # Get room utilization (RIGHT JOIN)
    room_stats = get_room_utilization(cur)
    
    # Get average metrics for all periods (AVG function)
    daily_avg = get_average_metrics(cur, today_start)
    weekly_avg = get_average_metrics(cur, week_start)
    monthly_avg = get_average_metrics(cur, month_start)
    yearly_avg = get_average_metrics(cur, year_start)
    
    # Get high spenders (CTE + HAVING)
    high_spenders = get_high_spenders_last_month(cur)
    
    cur.close()
    conn.close()
    
    return render_template('management.html',
                         manager=manager,
                         daily=daily,
                         weekly=weekly,
                         monthly=monthly,
                         yearly=yearly,
                         top_therapists=top_therapists,
                         working_now=working_now,
                         available=available,
                         # ADVANCED SQL DATA
                         room_stats=room_stats,
                         daily_avg=daily_avg,
                         weekly_avg=weekly_avg,
                         monthly_avg=monthly_avg,
                         yearly_avg=yearly_avg,
                         high_spenders=high_spenders)


@management_bp.route('/therapist-admin')
def therapist_admin():
    """Therapist management page"""
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Get countries for dropdown
        cur.execute("SELECT country_code, country_name FROM nationcode ORDER BY country_name")
        countries = cur.fetchall()
        
        # Get available roles
        cur.execute("SELECT rdid, role_type FROM role_definition ORDER BY role_type")
        roles = cur.fetchall()
        
        today = date.today().isoformat()
        
        return render_template('therapist_admin.html', 
                             countries=countries, 
                             roles=roles,
                             today=today)
    except Exception as e:
        flash(f'Error loading page: {str(e)}', 'error')
        return redirect(url_for('management.dashboard'))
    finally:
        cur.close()
        conn.close()


@management_bp.route('/add-therapist', methods=['POST'])
def add_therapist():
    """Add new therapist with initial role"""
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Insert employee
        cur.execute("""
            INSERT INTO employees (nric_fin_passport_no, name, work_name, gender, 
                                 mobile_number, country_code, employment_start, employment_end)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING eid
        """, (
            request.form['nric'],
            request.form['full_name'],
            request.form['work_name'],
            request.form['gender'],
            request.form['mobile'],
            request.form['country_code'],
            request.form['employment_start'],
            request.form['employment_end'] or None
        ))
        
        eid = cur.fetchone()[0]
        
        # Insert initial role
        cur.execute("""
            INSERT INTO roles (eid, rdid, start_date, end_date)
            VALUES (%s, %s, %s, %s)
        """, (
            eid,
            request.form['role_type'],
            request.form['role_start'],
            request.form['role_end'] or None
        ))
        
        conn.commit()
        flash(f'Therapist {request.form["work_name"]} added successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Error adding therapist: {str(e)}', 'error')
    
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('management.therapist_admin'))


@management_bp.route('/api/search-therapists')
def search_therapists():
    """AJAX endpoint for therapist search"""
    query = request.args.get('q', '')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT e.eid, e.work_name, e.name, e.mobile_number,
                   CASE WHEN e.employment_end IS NULL OR e.employment_end > CURRENT_DATE 
                        THEN 'Active' ELSE 'Inactive' END as status
            FROM employees e
            WHERE e.work_name ILIKE %s
               OR e.name ILIKE %s
            ORDER BY e.work_name
            LIMIT 10
        """, (f'%{query}%', f'%{query}%'))
        
        results = [{
            'eid': row[0],
            'work_name': row[1],
            'name': row[2],
            'mobile': row[3],
            'status': row[4]
        } for row in cur.fetchall()]
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@management_bp.route('/api/therapist/<int:eid>')
def get_therapist(eid):
    """AJAX endpoint to get therapist details"""
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Get therapist info
        cur.execute("""
            SELECT eid, nric_fin_passport_no, name, work_name, gender, 
                   mobile_number, country_code, employment_start, employment_end,
                   (employment_end IS NULL OR employment_end > CURRENT_DATE) as is_active
            FROM employees
            WHERE eid = %s
        """, (eid,))
        
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
            
        therapist = {
            'eid': row[0],
            'nric': row[1],
            'name': row[2],
            'work_name': row[3],
            'gender': row[4],
            'mobile': row[5],
            'country_code': row[6],
            'employment_start': row[7].isoformat() if row[7] else None,
            'employment_end': row[8].isoformat() if row[8] else None,
            'is_active': row[9]
        }
        
        # Get roles - use > CURRENT_DATE for strict comparison
        cur.execute("""
            SELECT r.rid, rd.role_type, r.start_date, r.end_date,
                   (r.end_date IS NULL OR r.end_date > CURRENT_DATE) as is_active
            FROM roles r
            JOIN role_definition rd ON r.rdid = rd.rdid
            WHERE r.eid = %s
            ORDER BY r.start_date DESC
        """, (eid,))
        
        roles = [{
            'rid': row[0],
            'role_type': row[1],
            'start_date': row[2].isoformat() if row[2] else None,
            'end_date': row[3].isoformat() if row[3] else None,
            'is_active': row[4]
        } for row in cur.fetchall()]
        
        return jsonify({'therapist': therapist, 'roles': roles})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@management_bp.route('/update-therapist', methods=['POST'])
def update_therapist():
    """Update therapist details - with cascade role ending"""
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Get old employment end date to check if it changed
        cur.execute("SELECT employment_end FROM employees WHERE eid = %s", (request.form['eid'],))
        old_end_date = cur.fetchone()[0]
        
        new_end_date = request.form['employment_end'] or None
        
        # Update employee
        cur.execute("""
            UPDATE employees
            SET name = %s,
                work_name = %s,
                gender = %s,
                mobile_number = %s,
                country_code = %s,
                employment_start = %s,
                employment_end = %s
            WHERE eid = %s
        """, (
            request.form['full_name'],
            request.form['work_name'],
            request.form['gender'],
            request.form['mobile'],
            request.form['country_code'],
            request.form['employment_start'],
            new_end_date,
            request.form['eid']
        ))
        
        # CASCADE: If employment end date is set/changed, end all active roles
        if new_end_date:
            # End all roles that don't have an end date or have end_date >= new_end_date
            cur.execute("""
                UPDATE roles
                SET end_date = %s
                WHERE eid = %s
                  AND (end_date IS NULL OR end_date > %s)
            """, (new_end_date, request.form['eid'], new_end_date))
            
            roles_ended = cur.rowcount
            if roles_ended > 0:
                flash(f'Employment ended and {roles_ended} active role(s) automatically ended.', 'success')
            else:
                flash('Therapist updated successfully!', 'success')
        else:
            flash('Therapist updated successfully!', 'success')
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f'Error updating therapist: {str(e)}', 'error')
    
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('management.therapist_admin'))


@management_bp.route('/add-role', methods=['POST'])
def add_role():
    """Add new role to existing therapist"""
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Check if employment is still active
        cur.execute("""
            SELECT employment_end 
            FROM employees 
            WHERE eid = %s
        """, (request.form['eid'],))
        
        emp_end = cur.fetchone()[0]
        if emp_end and emp_end <= date.today():
            flash('Cannot add role: Employment has already ended.', 'error')
            return redirect(url_for('management.therapist_admin'))
        
        cur.execute("""
            INSERT INTO roles (eid, rdid, start_date, end_date)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form['eid'],
            request.form['role_type'],
            request.form['start_date'],
            request.form['end_date'] or None
        ))
        
        conn.commit()
        flash('Role added successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Error adding role: {str(e)}', 'error')
    
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('management.therapist_admin'))


@management_bp.route('/end-role', methods=['POST'])
def end_role():
    """End a role (set end_date to yesterday so it's immediately inactive)"""
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Set end_date to yesterday so the role is immediately inactive
        cur.execute("""
            UPDATE roles
            SET end_date = CURRENT_DATE - INTERVAL '1 day'
            WHERE rid = %s
        """, (request.form['rid'],))
        
        conn.commit()
        flash('Role ended successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        flash(f'Error ending role: {str(e)}', 'error')
    
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('management.therapist_admin'))