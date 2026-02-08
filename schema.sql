-- ============================================================================
-- SPA/SALON MANAGEMENT SYSTEM - DATABASE SCHEMA
-- Specialist Diploma in Computing - Database Systems and Management
-- ============================================================================
-- File: schema.sql
-- Description: Complete database schema including enums, tables, indexes,
--              constraints, and triggers for PostgreSQL
-- ============================================================================

-- ============================================================================
-- SECTION 1: CLEANUP (Optional - uncomment for clean setup)
-- ============================================================================
DROP TABLE IF EXISTS refunds CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS transaction_items CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS services CASCADE;
DROP TABLE IF EXISTS roles CASCADE;
DROP TABLE IF EXISTS role_definition CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS room CASCADE;
DROP TABLE IF EXISTS nationcode CASCADE;

DROP TYPE IF EXISTS status_enum CASCADE;
DROP TYPE IF EXISTS discount_type_enum CASCADE;
DROP TYPE IF EXISTS gender_enum CASCADE;
DROP TYPE IF EXISTS paymentmethod_enum CASCADE;

-- ============================================================================
-- SECTION 2: CUSTOM ENUMERATIONS
-- ============================================================================

-- Payment/invoice status workflow: pending → partial → paid → completed/refunded
CREATE TYPE status_enum AS ENUM (
  'pending',      -- No payment received
  'partial',      -- Partial payment received
  'paid',         -- Fully paid, service pending/delivering
  'refunded',     -- Payment refunded (full or partial)
  'cancelled',    -- Transaction cancelled
  'completed'     -- Service delivered and paid
);

-- Discount types for analytics and tracking
CREATE TYPE discount_type_enum AS ENUM (
  'none',         -- Nothing to see
  'promo',        -- Promotional discount
  'waiver',       -- Management waiver
  'management',   -- Management override
  'staff'         -- Staff discount
);

-- Gender for customers and employees
CREATE TYPE gender_enum AS ENUM (
  'Male',
  'Female'
);

-- Supported payment methods
CREATE TYPE paymentmethod_enum AS ENUM (
  'Cash',
  'Credit Card',
  'NETS',
  'PayNow',
  'eWallet',
  'Voucher'
);

-- ============================================================================
-- SECTION 3: LOOKUP TABLES
-- ============================================================================

-- ISO country codes with nationality mapping
-- Used for customer/employee registration and police compliance reporting
CREATE TABLE nationcode (
  country_code CHAR(2) PRIMARY KEY,
  country_name VARCHAR(64) NOT NULL,
  default_nationality VARCHAR(64) NOT NULL
);

COMMENT ON TABLE nationcode IS 'ISO 3166-1 alpha-2 country codes with nationality mapping for compliance reporting';

-- Treatment/service rooms
CREATE TABLE room (
  rid SERIAL PRIMARY KEY,
  room_name VARCHAR(30) UNIQUE NOT NULL
);

COMMENT ON TABLE room IS 'Physical treatment rooms for service delivery';

-- ============================================================================
-- SECTION 4: CORE ENTITY TABLES
-- ============================================================================

-- Customer records with NRIC/Passport for police compliance
CREATE TABLE customers (
  cid BIGSERIAL PRIMARY KEY,
  nric_fin_passport_no VARCHAR(64) UNIQUE NOT NULL,
  name VARCHAR(64) NOT NULL,
  gender gender_enum NOT NULL,
  mobile_number VARCHAR(32) NOT NULL,
  country_code CHAR(2) NOT NULL,
  FOREIGN KEY (country_code) REFERENCES nationcode(country_code),
  CONSTRAINT chk_customer_mobile_format CHECK (mobile_number ~ '^[0-9]+$')
);

COMMENT ON TABLE customers IS 'Customer profiles with identification for police logging requirements';

-- Employee records with employment tracking
-- work_name: Display name used for customer-facing interactions (privacy/professional branding)
CREATE TABLE employees (
  eid BIGSERIAL PRIMARY KEY,
  nric_fin_passport_no VARCHAR(64) UNIQUE NOT NULL,
  name VARCHAR(128) NOT NULL,           -- Legal name for HR/payroll
  work_name VARCHAR(128) NOT NULL,      -- Display name for customers/schedules
  gender gender_enum NOT NULL,
  mobile_number VARCHAR(32) NOT NULL,
  country_code CHAR(2) NOT NULL,
  employment_start DATE NOT NULL,
  employment_end DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (country_code) REFERENCES nationcode(country_code),
  CONSTRAINT chk_employee_employment_dates 
    CHECK (employment_end IS NULL OR employment_end >= employment_start)
);

COMMENT ON TABLE employees IS 'Employee profiles including therapists, cashiers, and management with work name for customer-facing display';

-- Role definitions (lookup table for flexibility)
CREATE TABLE role_definition (
  rdid SERIAL PRIMARY KEY,
  role_type VARCHAR(64) UNIQUE NOT NULL
);

COMMENT ON TABLE role_definition IS 'Master list of possible roles (Therapist, Cashier, Manager, etc.)';

-- Employee-role assignments (many-to-many with temporal validity)
CREATE TABLE roles (
  rid BIGSERIAL PRIMARY KEY,
  eid BIGINT NOT NULL,
  rdid INT NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE,
  FOREIGN KEY (eid) REFERENCES employees(eid) ON DELETE CASCADE,
  FOREIGN KEY (rdid) REFERENCES role_definition(rdid),
  CONSTRAINT chk_role_dates 
    CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE roles IS 'Employee role assignments with validity periods';

-- Service catalog with role requirements
CREATE TABLE services (
  sid BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  base_cost NUMERIC(10,2) NOT NULL,
  active_from DATE NOT NULL,
  active_until DATE,
  rdid INT NOT NULL,
  FOREIGN KEY (rdid) REFERENCES role_definition(rdid),
  CONSTRAINT chk_service_positive 
    CHECK (duration_minutes >= 0 AND base_cost >= 0),
  CONSTRAINT chk_service_date_range 
    CHECK (active_until IS NULL OR active_until >= active_from)
);

COMMENT ON TABLE services IS 'Service catalog with pricing, duration, and required therapist role';

-- ============================================================================
-- SECTION 5: TRANSACTION TABLES
-- ============================================================================

-- Master transaction record (invoice header)
CREATE TABLE transactions (
  tid BIGSERIAL PRIMARY KEY,
  cid BIGINT NOT NULL,
  cashier_eid BIGINT NOT NULL,
  billlevel_discount NUMERIC(10,2) NOT NULL DEFAULT 0,
  billlevel_discount_type discount_type_enum NOT NULL DEFAULT 'none',
  total_cost NUMERIC(10,2) DEFAULT 0,
  total_discount NUMERIC(10,2) DEFAULT 0,
  total_paid NUMERIC(10,2) DEFAULT 0,
  entry_time TIMESTAMPTZ,           -- Customer entry (police requirement)
  exit_time TIMESTAMPTZ,            -- Customer exit (police requirement)
  status status_enum NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (cid) REFERENCES customers(cid),
  FOREIGN KEY (cashier_eid) REFERENCES employees(eid),
  CONSTRAINT chk_txn_amounts_nonnegative 
    CHECK (
      total_cost >= 0 AND 
      total_discount >= 0 AND 
      total_paid >= 0 AND 
      billlevel_discount >= 0
    ),
  CONSTRAINT chk_txn_discount_not_exceed_cost 
    CHECK (billlevel_discount <= total_cost),
  CONSTRAINT chk_txn_time_order 
    CHECK (exit_time IS NULL OR exit_time > entry_time)
);

COMMENT ON TABLE transactions IS 'Master transaction/invoice with payment tracking and police compliance timestamps';

-- Transaction line items (scheduled services)
CREATE TABLE transaction_items (
  ttid BIGSERIAL PRIMARY KEY,
  tid BIGINT NOT NULL,
  sid BIGINT NOT NULL,
  therapist_eid BIGINT NOT NULL,
  scheduled_start TIMESTAMPTZ,
  scheduled_end TIMESTAMPTZ,        -- Auto-calculated from service duration
  actual_start TIMESTAMPTZ,         -- Actual service start time
  actual_end TIMESTAMPTZ,           -- Actual service end time
  cost NUMERIC(10,2) NOT NULL,      -- Price at time of booking (may differ from base_cost)
  item_discount NUMERIC(10,2) NOT NULL DEFAULT 0,
  item_discount_type discount_type_enum NOT NULL DEFAULT 'none',
  rid INT NOT NULL,                 -- Assigned room
  FOREIGN KEY (tid) REFERENCES transactions(tid) ON DELETE CASCADE,
  FOREIGN KEY (sid) REFERENCES services(sid),
  FOREIGN KEY (therapist_eid) REFERENCES employees(eid),
  FOREIGN KEY (rid) REFERENCES room(rid),
  CONSTRAINT chk_item_cost_positive 
    CHECK (cost > 0),
  CONSTRAINT chk_item_discount_valid 
    CHECK (item_discount >= 0 AND item_discount <= cost),
  CONSTRAINT chk_item_scheduled_order 
    CHECK (
      scheduled_end IS NULL OR 
      scheduled_start IS NULL OR 
      scheduled_end >= scheduled_start
    ),
  CONSTRAINT chk_item_actual_order 
    CHECK (
      actual_end IS NULL OR 
      actual_start IS NULL OR 
      actual_end >= actual_start
    )
);

COMMENT ON TABLE transaction_items IS 'Individual service line items with scheduling and room assignment';

-- Payment records (supports multiple payments per transaction)
CREATE TABLE payments (
  pid BIGSERIAL PRIMARY KEY,
  tid BIGINT NOT NULL,
  payment_method paymentmethod_enum NOT NULL,
  payment_amount NUMERIC(10,2) NOT NULL,
  payment_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (tid) REFERENCES transactions(tid) ON DELETE CASCADE,
  CONSTRAINT chk_payment_positive 
    CHECK (payment_amount >= 0)
);

COMMENT ON TABLE payments IS 'Payment records supporting partial payments and multiple methods';

-- Refund records (supports partial refunds)
CREATE TABLE refunds (
  refid BIGSERIAL PRIMARY KEY,
  tid BIGINT NOT NULL,
  refund_method paymentmethod_enum NOT NULL,
  refund_amount NUMERIC(10,2) NOT NULL,
  refund_reason TEXT,
  refund_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (tid) REFERENCES transactions(tid) ON DELETE CASCADE,
  CONSTRAINT chk_refund_positive 
    CHECK (refund_amount > 0)
);

COMMENT ON TABLE refunds IS 'Refund records for full or partial transaction refunds';

-- ============================================================================
-- SECTION 6: INDEXES (FIXED)
-- ============================================================================

-- ----------------------------------------
-- Foreign Key Indexes (PostgreSQL does not auto-index FKs)
-- ----------------------------------------
CREATE INDEX idx_customers_country_code ON customers(country_code);
CREATE INDEX idx_employees_country_code ON employees(country_code);
CREATE INDEX idx_roles_eid ON roles(eid);
CREATE INDEX idx_roles_rdid ON roles(rdid);
CREATE INDEX idx_services_rdid ON services(rdid);
CREATE INDEX idx_transactions_cid ON transactions(cid);
CREATE INDEX idx_transactions_cashier_eid ON transactions(cashier_eid);
CREATE INDEX idx_transaction_items_tid ON transaction_items(tid);
CREATE INDEX idx_transaction_items_sid ON transaction_items(sid);
CREATE INDEX idx_transaction_items_therapist_eid ON transaction_items(therapist_eid);
CREATE INDEX idx_transaction_items_rid ON transaction_items(rid);
CREATE INDEX idx_payments_tid ON payments(tid);
CREATE INDEX idx_refunds_tid ON refunds(tid);

-- ----------------------------------------
-- Search and Lookup Performance
-- ----------------------------------------
CREATE INDEX idx_customers_mobile ON customers(mobile_number);
CREATE INDEX idx_employees_mobile ON employees(mobile_number);
CREATE INDEX idx_employees_work_name ON employees(work_name);

-- ----------------------------------------
-- Date/Time Range Queries (Reports, Dashboards)
-- ----------------------------------------
CREATE INDEX idx_transactions_entry_time ON transactions(entry_time);
CREATE INDEX idx_transactions_created_at ON transactions(created_at);
CREATE INDEX idx_transaction_items_scheduled_start ON transaction_items(scheduled_start);
CREATE INDEX idx_payments_time ON payments(payment_time);

-- ----------------------------------------
-- Composite Indexes for Common Query Patterns
-- ----------------------------------------
CREATE INDEX idx_transactions_cid_entry ON transactions(cid, entry_time DESC NULLS LAST);
CREATE INDEX idx_transaction_items_therapist_schedule 
  ON transaction_items(therapist_eid, scheduled_start, scheduled_end);
CREATE INDEX idx_transaction_items_room_schedule 
  ON transaction_items(rid, scheduled_start, scheduled_end);
CREATE INDEX idx_payments_method_time ON payments(payment_method, payment_time);


-- ============================================================================
-- SECTION 7: TRIGGER FUNCTIONS
-- ============================================================================

-- Function: Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function: Auto-calculate scheduled_end from service duration
CREATE OR REPLACE FUNCTION calculate_scheduled_end()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.scheduled_start IS NOT NULL THEN
    NEW.scheduled_end := NEW.scheduled_start + (
      SELECT make_interval(mins => duration_minutes)
      FROM services
      WHERE sid = NEW.sid
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function: Update transaction totals (cost and discount)
CREATE OR REPLACE FUNCTION update_transaction_totals()
RETURNS TRIGGER AS $$
DECLARE
  v_tid BIGINT;
  v_items_cost NUMERIC(10,2);
  v_items_discount NUMERIC(10,2);
BEGIN
  IF TG_OP = 'DELETE' THEN
    v_tid := OLD.tid;
  ELSE
    v_tid := NEW.tid;
  END IF;

  SELECT 
    COALESCE(SUM(cost), 0),
    COALESCE(SUM(item_discount), 0)
  INTO v_items_cost, v_items_discount
  FROM transaction_items 
  WHERE tid = v_tid;

  UPDATE transactions
  SET 
    total_cost = v_items_cost,
    total_discount = v_items_discount + COALESCE(billlevel_discount, 0)
  WHERE tid = v_tid;

  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Function: Recalculate discount when bill-level discount changes
CREATE OR REPLACE FUNCTION update_discount_on_billlevel_change()
RETURNS TRIGGER AS $$
DECLARE
  v_items_discount NUMERIC(10,2);
BEGIN
  SELECT COALESCE(SUM(item_discount), 0)
  INTO v_items_discount
  FROM transaction_items 
  WHERE tid = NEW.tid;

  NEW.total_discount := v_items_discount + COALESCE(NEW.billlevel_discount, 0);
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function: Update total_paid from payments and refunds
CREATE OR REPLACE FUNCTION update_transaction_total_paid()
RETURNS TRIGGER AS $$
DECLARE
  v_tid BIGINT;
  v_paid NUMERIC(10,2);
  v_refunded NUMERIC(10,2);
BEGIN
  IF TG_OP = 'DELETE' THEN
    v_tid := OLD.tid;
  ELSE
    v_tid := NEW.tid;
  END IF;

  SELECT COALESCE(SUM(payment_amount), 0)
  INTO v_paid
  FROM payments 
  WHERE tid = v_tid;

  SELECT COALESCE(SUM(refund_amount), 0)
  INTO v_refunded
  FROM refunds 
  WHERE tid = v_tid;

  UPDATE transactions
  SET total_paid = v_paid - v_refunded
  WHERE tid = v_tid;

  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Function: Auto-update transaction status based on payment state
CREATE OR REPLACE FUNCTION update_transaction_status()
RETURNS TRIGGER AS $$
DECLARE
  v_amount_due NUMERIC(10,2);
BEGIN
  IF NEW.status IN ('pending', 'partial', 'paid') THEN
    v_amount_due := NEW.total_cost - NEW.total_discount;
    
    IF NEW.total_paid <= 0 THEN
      NEW.status := 'pending';
    ELSIF NEW.total_paid < v_amount_due THEN
      NEW.status := 'partial';
    ELSE
      NEW.status := 'paid';
    END IF;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SECTION 8: TRIGGER DEFINITIONS
-- ============================================================================

-- Auto-update updated_at on transactions and employees
CREATE TRIGGER trg_update_transactions_updated_at
  BEFORE UPDATE ON transactions
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_update_employees_updated_at
  BEFORE UPDATE ON employees
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

-- Auto-calculate scheduled_end when transaction_item is inserted/updated
CREATE TRIGGER trg_calculate_scheduled_end
  BEFORE INSERT OR UPDATE OF scheduled_start, sid ON transaction_items
  FOR EACH ROW
  EXECUTE FUNCTION calculate_scheduled_end();

-- Update transaction totals when items change
CREATE TRIGGER trg_update_transaction_totals
  AFTER INSERT OR UPDATE OR DELETE ON transaction_items
  FOR EACH ROW
  EXECUTE FUNCTION update_transaction_totals();

-- Recalculate discount when bill-level discount is modified
CREATE TRIGGER trg_update_discount_on_billlevel
  BEFORE UPDATE OF billlevel_discount ON transactions
  FOR EACH ROW
  EXECUTE FUNCTION update_discount_on_billlevel_change();

-- Update total_paid when payments change
CREATE TRIGGER trg_update_total_paid_payment
  AFTER INSERT OR UPDATE OR DELETE ON payments
  FOR EACH ROW
  EXECUTE FUNCTION update_transaction_total_paid();

-- Update total_paid when refunds change
CREATE TRIGGER trg_update_total_paid_refund
  AFTER INSERT OR UPDATE OR DELETE ON refunds
  FOR EACH ROW
  EXECUTE FUNCTION update_transaction_total_paid();

-- Auto-update status based on payment state (runs after total_paid updates)
CREATE TRIGGER trg_update_transaction_status
  BEFORE INSERT OR UPDATE ON transactions
  FOR EACH ROW
  EXECUTE FUNCTION update_transaction_status();

-- ============================================================================
-- SECTION 9: VERIFICATION QUERIES (Uncomment to test after creation)
-- ============================================================================
/*
-- Verify all tables created
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

-- Verify all indexes created
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE schemaname = 'public' 
ORDER BY tablename, indexname;

-- Verify all triggers created
SELECT trigger_name, event_manipulation, event_object_table
FROM information_schema.triggers
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;

-- Verify employees table structure
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'employees'
ORDER BY ordinal_position;
*/