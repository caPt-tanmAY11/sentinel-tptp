import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config.settings import get_settings

settings = get_settings()

def truncate_transactions():
    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    cursor = conn.cursor()
    print("Truncating pulse_scores, transaction_pulse_events, and transactions...")
    cursor.execute("""
        TRUNCATE TABLE
            transaction_pulse_events,
            pulse_scores,
            transactions
        RESTART IDENTITY CASCADE
    """)
    conn.commit()
    cursor.close()
    conn.close()
    print("Truncation complete.")

if __name__ == "__main__":
    truncate_transactions()
