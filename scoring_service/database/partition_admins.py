import os
import sys
import random
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import get_settings

def run():
    settings = get_settings()
    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    cursor = conn.cursor()

    admins = [
        "manjunathmurali20@gmail.com",
        "testuser1togethr@gmail.com",
        "tanmay06lko@gmail.com",
        "sanyogeetapradhan@gmail.com",
        "sanyogaming25@gmail.com",
        "sundranidevraj@gmail.com",
        "rajatdalalpaaji@gmail.com",
        "akshaysinghpaaji@gmail.com",
        "sohanj9106@gmail.com",
        "sohan2.9106@gmail.com"
    ]

    print("Adding admin_email to customers...")
    cursor.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS admin_email VARCHAR(255);")
    conn.commit()

    print("Checking customer count...")
    cursor.execute("SELECT COUNT(*) FROM customers")
    count = cursor.fetchone()[0]
    
    if count < 1500:
        needed = 1500 - count
        print(f"Duplicating {needed} customers to reach 1500 using SQL...")
        
        # We need a mapping table to duplicate pulse_scores cleanly. 
        # But we can just use a CTE to do everything.
        cursor.execute("""
            CREATE TEMP TABLE temp_dup_map AS
            SELECT 
                customer_id AS old_id,
                gen_random_uuid() AS new_id,
                UPPER(SUBSTRING(MD5(RANDOM()::TEXT) FROM 1 FOR 10)) AS new_pan,
                MD5(RANDOM()::TEXT) AS new_aadhaar,
                SUBSTRING(MD5(RANDOM()::TEXT) FROM 1 FOR 16) AS new_account_id,
                CAST((RANDOM() * 9000000000 + 1000000000) AS BIGINT)::TEXT AS new_account_number,
                '+91' || CAST((RANDOM() * 3999999999 + 6000000000) AS BIGINT)::TEXT AS new_phone,
                SUBSTRING(MD5(RANDOM()::TEXT) FROM 1 FOR 8) || '@bank' AS new_upi_vpa
            FROM customers LIMIT %s
        """, (needed,))
        
        # Insert duplicated customers
        # First we get the list of columns to exclude serial keys if any
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='customers' 
              AND column_name NOT IN ('customer_id', 'pan_number', 'aadhaar_hash', 'account_id', 'account_number', 'phone', 'upi_vpa', 'email')
        """)
        other_cols = [r[0] for r in cursor.fetchall()]
        
        cols_str = ", ".join(other_cols)
        
        cursor.execute(f"""
            INSERT INTO customers (customer_id, pan_number, aadhaar_hash, account_id, account_number, phone, upi_vpa, email, {cols_str})
            SELECT 
                m.new_id, m.new_pan, m.new_aadhaar, m.new_account_id, m.new_account_number, m.new_phone, m.new_upi_vpa,
                'dup_' || c.email,
                {', '.join(['c.' + c for c in other_cols])}
            FROM temp_dup_map m
            JOIN customers c ON c.customer_id = m.old_id;
        """)

        # Duplicate pulse_scores
        cursor.execute("""
            INSERT INTO pulse_scores (customer_id, pulse_score, risk_tier, risk_label, score_ts)
            SELECT 
                m.new_id,
                ps.pulse_score,
                ps.risk_tier,
                ps.risk_label,
                ps.score_ts
            FROM temp_dup_map m
            JOIN pulse_scores ps ON ps.customer_id = m.old_id;
        """)
            
        conn.commit()
        print("Duplication complete.")

    print("Checking customer count again...")
    cursor.execute("SELECT COUNT(*) FROM customers")
    new_count = cursor.fetchone()[0]
    print(f"Total customers now: {new_count}")

    print("Assigning exactly 150 customers per admin based on region...")
    cursor.execute("SELECT customer_id, state FROM customers")
    all_customers = cursor.fetchall()
    
    by_state = {}
    for cid, state in all_customers:
        by_state.setdefault(state, []).append(cid)
        
    states = list(by_state.keys())
    random.shuffle(states)
    
    assigned = set()
    update_tuples = []
    
    for admin in admins:
        admin_customers = []
        random.shuffle(states)
        for state in states:
            for cid in by_state[state]:
                if cid not in assigned:
                    admin_customers.append(cid)
                    assigned.add(cid)
                if len(admin_customers) == 150:
                    break
            if len(admin_customers) == 150:
                break
                
        if len(admin_customers) < 150:
            for cid, _ in all_customers:
                if cid not in assigned:
                    admin_customers.append(cid)
                    assigned.add(cid)
                if len(admin_customers) == 150:
                    break
                    
        for cid in admin_customers:
            update_tuples.append((admin, cid))

    print(f"Executing updates for {len(update_tuples)} customers...")
    psycopg2.extras.execute_values(
        cursor,
        "UPDATE customers SET admin_email = data.admin_email FROM (VALUES %s) AS data (admin_email, customer_id) WHERE customers.customer_id = data.customer_id::uuid",
        update_tuples
    )
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Successfully partitioned customers to 10 admins (150 each)!")

if __name__ == "__main__":
    run()
