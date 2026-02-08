from flask import Flask, render_template
from db import get_db
import os

# Import blueprints
from blueprints.customer import customer_bp
from blueprints.management import management_bp
from blueprints.police import police_bp
from blueprints.therapist import therapist_bp
from blueprints.cashier import cashier_bp

app = Flask(__name__)

# REQUIRED: Set secret key for sessions
# In production, use a secure random key from environment variable
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Register blueprints
app.register_blueprint(customer_bp)
app.register_blueprint(management_bp)
app.register_blueprint(police_bp)
app.register_blueprint(therapist_bp)
app.register_blueprint(cashier_bp)

@app.route('/')
def index():
    """Main landing page with 5 login perspectives"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT e.eid, e.work_name, e.name, rd.role_type
        FROM employees e
        LEFT JOIN roles r ON e.eid = r.eid 
            AND r.start_date <= CURRENT_DATE 
            AND (r.end_date IS NULL OR r.end_date > CURRENT_DATE)
        LEFT JOIN role_definition rd ON r.rdid = rd.rdid
        WHERE (e.employment_end IS NULL OR e.employment_end >= CURRENT_DATE)
        ORDER BY rd.role_type, e.work_name
    """)
    
    employees = cur.fetchall()
    
    management = [e for e in employees if e[3] and 'manager' in e[3].lower()]
    therapists = [e for e in employees if e[3] and any(x in e[3].lower() for x in ['therapist', 'doctor', 'beautician'])]
    cashiers = [e for e in employees if e[3] and 'cashier' in e[3].lower()]
    
    cur.execute("SELECT cid, name, mobile_number FROM customers ORDER BY name")
    customers = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('index.html',
                         management=management,
                         therapists=therapists,
                         cashiers=cashiers,
                         customers=customers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)