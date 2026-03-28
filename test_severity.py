import psycopg2
from psycopg2.extras import RealDictCursor
from realtime.pulse_engine import PulseEngine
from schemas.transaction_event import TransactionEvent
from config.settings import get_settings
import json

s = get_settings()
engine = PulseEngine()

conn = psycopg2.connect(
    dbname=s.POSTGRES_DB, user=s.POSTGRES_USER, 
    password=s.POSTGRES_PASSWORD, host=s.POSTGRES_HOST
)
c = conn.cursor(cursor_factory=RealDictCursor)

c.execute("SELECT customer_id, MAX(days_past_due) as max_dpd FROM loans GROUP BY customer_id")
cids = {}
for r in c.fetchall():
    if not isinstance(r, dict): r = dict(r)
    if (r.get('max_dpd') or 0) >= 1: 
        cids['stress'] = r['customer_id']
        break

c.execute("SELECT customer_id FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM loans WHERE days_past_due >= 1) LIMIT 1")
normal_r = c.fetchone()
if normal_r:
    if not isinstance(normal_r, dict): normal_r = dict(normal_r)
    cids['normal'] = normal_r['customer_id']

for role, cid in cids.items():
    print(f'\n--- {role.upper()} CUSTOMER {cid} ---')
    c.execute('SELECT * FROM transactions WHERE customer_id = %s ORDER BY txn_timestamp DESC LIMIT 1', (cid,))
    t = dict(c.fetchone())
    event = TransactionEvent(**t)
    
    # fake general debit
    event.amount = 50.0
    event.platform = 'UPI'
    
    res = engine.process(event, conn=conn)
    print(f'General Debit Severity: {res["severity"]}')
    
    # print the raw input vector the model saw
    delta = engine._latest_delta if hasattr(engine, "_latest_delta") else None
    
    print(f"Top 5 features pushing severity:")
    from feature_engine.delta_features import DELTA_FEATURE_NAMES
    x_arr = [delta.get(f, 0.0) for f in DELTA_FEATURE_NAMES]
    import numpy as np
    x_arr = np.array(x_arr, dtype=np.float32)
    shap_vals = engine._model.get_shap_values(x_arr.reshape(1, -1))[0]
    # shap_vals holds the impact of each feature
    top_idx = np.argsort(-np.abs(shap_vals))[:5]
    for i in top_idx:
        fname = DELTA_FEATURE_NAMES[i]
        val = x_arr[i]
        impact = shap_vals[i]
        print(f"  {fname}: val={val:.4f}, impact={impact:.4f}")
