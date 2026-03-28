import sys
import os
sys.path.append(os.getcwd())
from config.settings import get_settings
import psycopg2
from psycopg2.extras import RealDictCursor

s = get_settings()
conn = psycopg2.connect(
    host=s.POSTGRES_HOST, port=s.POSTGRES_PORT,
    database=s.POSTGRES_DB, user=s.POSTGRES_USER,
    password=s.POSTGRES_PASSWORD,
)
cur = conn.cursor(cursor_factory=RealDictCursor)

customer_id = '152037bf-ed20-4977-a5db-94ab99d4d9ee'
cur.execute("SELECT severity_direction, COUNT(*) FROM transaction_pulse_events WHERE customer_id = %s GROUP BY severity_direction", (customer_id,))
print("Directions:", cur.fetchall())

cur.execute("SELECT sent_at FROM interventions WHERE intervention_id = 'e83d153b-21bc-43d7-a0d2-4fe5b5aefa5f'")
r = cur.fetchone()
print("Sent at:", r)

conn.close()
