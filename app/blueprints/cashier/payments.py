from flask import request, redirect, url_for, flash, current_app, session
from . import cashier_bp
from db import get_db
from .cache_utils import invalidate_transactions_cache
import traceback

@cashier_bp.route('/cashier/add-payment/<int:tid>', methods=['POST'])
def add_payment(tid):
    """Process one or more payments for a transaction"""
    current_app.logger.info(f"=== PAYMENT DEBUG: Called add_payment for tid={tid} ===")
    
    payment_methods = request.form.getlist('payment_method[]')
    payment_amounts = request.form.getlist('payment_amount[]')
    
    if not payment_methods or not payment_amounts:
        flash('No payment data provided', 'error')
        return redirect(url_for('cashier.transaction_detail', tid=tid))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        total_inserted = 0
        
        # Insert each payment - triggers will update total_paid
        for method, amount in zip(payment_methods, payment_amounts):
            amount = float(amount)
            if amount > 0:
                cur.execute("""
                    INSERT INTO payments (tid, payment_method, payment_amount, payment_time)
                    VALUES (%s, %s::paymentmethod_enum, %s, CURRENT_TIMESTAMP)
                """, (tid, method, amount))
                total_inserted += amount
        
        # COMMIT so triggers fire and update transaction totals
        conn.commit()
        
        # NOW query the final state after triggers have run
        # Let database calculate outstanding with GREATEST
        cur.execute("""
            SELECT 
                total_cost,
                total_discount,
                total_paid,
                GREATEST(0, total_cost - total_discount - total_paid) as outstanding,
                exit_time,
                status
            FROM transactions
            WHERE tid = %s
        """, (tid,))
        
        txn = cur.fetchone()
        outstanding = float(txn[3])  # Database-calculated outstanding
        
        current_app.logger.info(f"=== PAYMENT DEBUG: total_inserted={total_inserted}, outstanding={outstanding} ===")
        
        # Determine if we should mark as completed
        # (Only if fully paid AND customer has already exited)
        if outstanding <= 0 and txn[4] is not None and txn[5] != 'completed':
            cur.execute("""
                UPDATE transactions
                SET status = 'completed'
                WHERE tid = %s
            """, (tid,))
            conn.commit()
            flash(f'Payment of ${total_inserted:.2f} processed. Transaction completed!', 'success')
            
            # Invalidate cache since status changed to completed
            try:
                invalidate_transactions_cache()
            except Exception as e:
                current_app.logger.error(f"Cache invalidation failed: {e}")
        else:
            flash(f'Payment of ${total_inserted:.2f} processed successfully!', 'success')
            if outstanding > 0:
                flash(f'Outstanding balance: ${outstanding:.2f}', 'info')
        
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Payment failed: {str(e)}")
        flash(f'Payment failed: {str(e)}', 'error')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('cashier.transaction_detail', tid=tid))