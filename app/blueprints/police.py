from flask import Blueprint, render_template, redirect, url_for
from datetime import datetime
from db import get_db

police_bp = Blueprint('police', __name__)

@police_bp.route('/police')
def police_dashboard():
    return redirect(url_for('police.police_view', period='day', date=datetime.now().strftime('%Y-%m-%d')))

@police_bp.route('/police/<period>/<date>')
def police_view(period, date):
    conn = get_db()
    cur = conn.cursor()
    
    base_query = """
        SELECT 
            c.name, 
            c.nric_fin_passport_no, 
            nc.default_nationality, 
            t.entry_time, 
            t.exit_time
        FROM transactions t
        JOIN customers c ON t.cid = c.cid
        JOIN nationcode nc ON c.country_code = nc.country_code
        WHERE t.entry_time IS NOT NULL
    """
    
    if period == 'day':
        query = base_query + " AND t.entry_time::date = %s ORDER BY t.entry_time ASC"
        cur.execute(query, (date,))
    elif period == 'week':
        query = base_query + " AND t.entry_time >= %s AND t.entry_time < %s::date + INTERVAL '7 days' ORDER BY t.entry_time ASC"
        cur.execute(query, (date, date))
    elif period == 'month':
        query = base_query + " AND t.entry_time >= %s AND t.entry_time < %s::date + INTERVAL '30 days' ORDER BY t.entry_time ASC"
        cur.execute(query, (date, date))
    elif period == '3months':
        query = base_query + " AND t.entry_time >= %s AND t.entry_time <= (%s::date + INTERVAL '3 months' - INTERVAL '1 day') ORDER BY t.entry_time ASC"
        cur.execute(query, (date, date))
    elif period == '6months':
        query = base_query + " AND t.entry_time >= %s AND t.entry_time <= (%s::date + INTERVAL '6 months' - INTERVAL '1 day') ORDER BY t.entry_time ASC"
        cur.execute(query, (date, date))
    else:
        query = base_query + " AND t.entry_time::date = %s ORDER BY t.entry_time ASC"
        cur.execute(query, (date,))
    
    records = cur.fetchall()
    cur.close()
    conn.close()
    
    period_labels = {
        'day': '1 Day',
        'week': '1 Week', 
        'month': '1 Month (30 days)',
        '3months': '3 Months',
        '6months': '6 Months'
    }
    period_label = period_labels.get(period, period)
    
    return render_template('police.html', records=records, period=period, date=date, period_label=period_label)
