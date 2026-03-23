"""
tests/test_normal_vs_stress_transactions.py
─────────────────────────────────────────────────────────────────────────────
Verifies that:
  1. Normal transactions classified correctly (GROCERY, FOOD_DELIVERY, etc.)
  2. Normal transactions produce delta = 0.0 — score unchanged
  3. Stress transactions DO increase the pulse score
  4. Recovery transactions (salary, on-time EMI) decrease the score
  5. Injector generates diverse realistic everyday transactions

Run: python tests/test_normal_vs_stress_transactions.py
─────────────────────────────────────────────────────────────────────────────
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from enrichment.transaction_classifier import classify_transaction
from realtime.pulse_accumulator import (
    compute_direction, compute_delta, apply_delta, assign_risk_tier,
    RELIEF_CATEGORIES, STRESS_CATEGORIES,
)
from data_generator.realtime_injector import RealTimeInjector

PASS_COUNT = 0
FAIL_COUNT = 0

def check(label, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS  {label}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL  {label}  ← {detail}")


# ── Section 1: Classifier ────────────────────────────────────────────────────
print()
print("=" * 65)
print("  SECTION 1: Classifier — normal transactions")
print("=" * 65)

NORMAL_TEST_CASES = [
    # P2P
    ("Rs50 P2P to friend",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"rahul.sharma@hdfcbank","receiver_name":"Rahul Sharma",
      "amount":50.0,"balance_before":15000.0,"balance_after":14950.0},
     "GENERAL_DEBIT"),
    ("Rs650 dinner bill split",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"priya.menon99@ybl","receiver_name":"Priya Menon",
      "amount":650.0,"balance_before":14950.0,"balance_after":14300.0},
     "GENERAL_DEBIT"),
    ("Rs2000 P2P family transfer",
     {"platform":"NEFT","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"mom.sharma@sbi","receiver_name":"Anita Sharma",
      "amount":2000.0,"balance_before":50000.0,"balance_after":48000.0},
     "GENERAL_DEBIT"),
    # Food
    ("Rs350 Zomato food order",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"zomato@axl","receiver_name":"Zomato",
      "amount":350.0,"balance_before":14300.0,"balance_after":13950.0},
     "FOOD_DELIVERY"),
    ("Rs280 Swiggy lunch",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"swiggy@icicibank","receiver_name":"Swiggy",
      "amount":280.0,"balance_before":13950.0,"balance_after":13670.0},
     "FOOD_DELIVERY"),
    # Grocery
    ("Rs800 BigBasket grocery",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"bigbasket@okaxis","receiver_name":"BigBasket",
      "amount":800.0,"balance_before":13670.0,"balance_after":12870.0},
     "GROCERY"),
    ("Rs1200 DMart grocery",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"dmartrewards@upi","receiver_name":"DMart",
      "amount":1200.0,"balance_before":12870.0,"balance_after":11670.0},
     "GROCERY"),
    # Utilities
    ("Rs1200 BESCOM electricity",
     {"platform":"BBPS","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"bescom@bbps","receiver_name":"BESCOM",
      "amount":1200.0,"balance_before":11670.0,"balance_after":10470.0},
     "UTILITY_PAYMENT"),
    ("Rs299 Jio recharge",
     {"platform":"BBPS","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"jio@bbps","receiver_name":"Jio",
      "amount":299.0,"balance_before":10470.0,"balance_after":10171.0},
     "UTILITY_PAYMENT"),
    # Fuel
    ("Rs2000 HPCL petrol",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"hpcl@upi","receiver_name":"HPCL",
      "amount":2000.0,"balance_before":10171.0,"balance_after":8171.0},
     "FUEL"),
    # E-commerce
    ("Rs1500 Amazon purchase",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"amazon@axisbank","receiver_name":"Amazon India",
      "amount":1500.0,"balance_before":8171.0,"balance_after":6671.0},
     "ECOMMERCE"),
    # OTT
    ("Rs499 Netflix subscription",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"netflix@ybl","receiver_name":"Netflix India",
      "amount":499.0,"balance_before":6671.0,"balance_after":6172.0},
     "OTT"),
    # Coffee POS
    ("Rs180 coffee POS",
     {"platform":"POS","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"cafecoffe@pos","receiver_name":"Cafe Coffee Day",
      "amount":180.0,"balance_before":6172.0,"balance_after":5992.0},
     "GENERAL_DEBIT"),
    # Medical
    ("Rs500 Apollo Pharmacy",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"apollopharmacy@upi","receiver_name":"Apollo Pharmacy",
      "amount":500.0,"balance_before":5992.0,"balance_after":5492.0},
     "GENERAL_DEBIT"),
]

for desc, txn, expected_cat in NORMAL_TEST_CASES:
    cat = classify_transaction(txn)
    check(
        f"{desc:<45}  cat={cat.category}",
        cat.category == expected_cat,
        f"expected {expected_cat}, got {cat.category}",
    )


# ── Section 2: Accumulator — normal txns must produce delta = 0 ────────────
print()
print("=" * 65)
print("  SECTION 2: Accumulator — normal txns must not change score")
print("=" * 65)

STARTING_SCORE = 0.20
score = STARTING_SCORE
print(f"  Starting pulse score: {STARTING_SCORE}")
print()

for desc, txn, _ in NORMAL_TEST_CASES:
    cat       = classify_transaction(txn)
    direction = compute_direction(cat.category, cat.stress_weight)
    delta     = compute_delta(cat.stress_weight, direction, score)
    score     = apply_delta(score, delta)

    check(
        f"{desc[:45]:<45}  delta={delta:+.4f}  dir={direction}",
        delta == 0.0,
        f"Expected delta=0.0, got {delta}  (category={cat.category})",
    )

print()
check(
    f"Score unchanged after {len(NORMAL_TEST_CASES)} normal transactions: {score:.4f}",
    score == STARTING_SCORE,
    f"Score moved from {STARTING_SCORE} to {score}",
)


# ── Section 3: Stress transactions raise the score ────────────────────────
print()
print("=" * 65)
print("  SECTION 3: Stress transactions raise the score")
print("=" * 65)

STRESS_TEST_CASES = [
    ("Rs5000 to slice@upi (lending)",
     {"platform":"UPI","payment_status":"success","sender_id":"user@sbi",
      "receiver_id":"slice@upi","receiver_name":"Slice Fintech",
      "amount":5000.0,"balance_before":8000.0,"balance_after":3000.0},
     "positive"),
    ("Failed NACH EMI bounce",
     {"platform":"NACH","payment_status":"failed","sender_id":"1234567890",
      "receiver_id":"HDFC_NACH_EMI_HDFC_PL_2022_00000001@nach",
      "receiver_name":"EMI Auto-debit",
      "amount":8500.0,"balance_before":3000.0,"balance_after":3000.0},
     "positive"),
    ("Rs10000 disbursement from fibe@ybl",
     {"platform":"UPI","payment_status":"success",
      "sender_id":"fibe@ybl","sender_name":"Fibe EarlySalary",
      "receiver_id":"user@sbi",
      "amount":10000.0,"balance_before":3000.0,"balance_after":13000.0},
     "positive"),
    ("Second failed NACH",
     {"platform":"NACH","payment_status":"failed","sender_id":"1234567890",
      "receiver_id":"HDFC_NACH_EMI_HDFC_PL_2022_00000001@nach",
      "receiver_name":"EMI Auto-debit",
      "amount":8500.0,"balance_before":13000.0,"balance_after":13000.0},
     "positive"),
]

score_stress = STARTING_SCORE
print(f"  Starting from: {score_stress}")
print()

for desc, txn, exp_dir in STRESS_TEST_CASES:
    cat       = classify_transaction(txn)
    direction = compute_direction(cat.category, cat.stress_weight)
    delta     = compute_delta(cat.stress_weight, direction, score_stress)
    score_stress = apply_delta(score_stress, delta)
    check(
        f"{desc[:45]:<45}  dir={direction}  delta={delta:+.4f}",
        direction == exp_dir and delta > 0.0,
        f"expected direction={exp_dir} delta>0, got dir={direction} delta={delta}",
    )

check(
    f"Score raised: {STARTING_SCORE:.4f} → {score_stress:.4f}  tier={assign_risk_tier(score_stress)['label']}",
    score_stress > STARTING_SCORE,
    "Score should have increased",
)


# ── Section 4: Recovery transactions lower the score ─────────────────────
print()
print("=" * 65)
print("  SECTION 4: Recovery — salary + on-time EMI lower the score")
print("=" * 65)

RECOVERY_TEST_CASES = [
    ("Salary credit from TCS payroll",
     {"platform":"NEFT","payment_status":"success",
      "sender_id":"tcspayroll@neft","sender_name":"TCS Payroll",
      "receiver_id":"1234567890",
      "amount":60000.0,"balance_before":5000.0,"balance_after":65000.0},
     "negative"),
    ("Successful NACH EMI paid",
     {"platform":"NACH","payment_status":"success","sender_id":"1234567890",
      "receiver_id":"HDFC_NACH_EMI_HDFC_PL_2022_00000001@nach",
      "receiver_name":"EMI Auto-debit",
      "amount":8500.0,"balance_before":65000.0,"balance_after":56500.0},
     "negative"),
]

score_recovery = score_stress
print(f"  Starting from elevated: {score_recovery:.4f}")
print()

for desc, txn, exp_dir in RECOVERY_TEST_CASES:
    cat       = classify_transaction(txn)
    direction = compute_direction(cat.category, cat.stress_weight)
    delta     = compute_delta(cat.stress_weight, direction, score_recovery)
    score_recovery = apply_delta(score_recovery, delta)
    check(
        f"{desc[:45]:<45}  dir={direction}  delta={delta:+.4f}",
        direction == exp_dir and delta < 0.0,
        f"expected direction={exp_dir} delta<0, got dir={direction} delta={delta}",
    )

check(
    f"Score lowered: {score_stress:.4f} → {score_recovery:.4f}",
    score_recovery < score_stress,
    "Score should have decreased",
)


# ── Section 5: Injector diversity ─────────────────────────────────────────
print()
print("=" * 65)
print("  SECTION 5: Injector generates diverse everyday transactions")
print("=" * 65)

mock_customer = {
    "customer_id":"test-001","account_number":"1234567890",
    "upi_vpa":"rahul.sharma@sbi","monthly_income":60000,
    "first_name":"Rahul","last_name":"Sharma",
}
inj = RealTimeInjector(mode="random")
samples = [inj._build_random(mock_customer) for _ in range(200)]

recv_ids  = [t.receiver_id for t in samples]
platforms = [t.platform    for t in samples]
amounts   = [t.amount      for t in samples]

check(f"60+ unique merchants across 200 txns: {len(set(recv_ids))}",
      len(set(recv_ids)) >= 20)
check(f"Multiple platforms: {set(platforms)}",
      len(set(platforms)) >= 2)
check(f"Small amounts exist (P2P Rs10-100): min=Rs{min(amounts):.0f}",
      min(amounts) < 100)
check(f"Larger amounts exist: max=Rs{max(amounts):.0f}",
      max(amounts) > 1000)
check("All amounts positive",
      all(a > 0 for a in amounts))
valid_platforms = {"UPI","NEFT","IMPS","RTGS","ATM","NACH","ECS","BBPS","POS","MOBILE","BRANCH"}
check("All platforms valid",
      all(t.platform in valid_platforms for t in samples))

# Check direction distribution
direction_counts: Counter = Counter()
for t in samples:
    td = {"platform":t.platform,"payment_status":t.payment_status,
          "sender_id":t.sender_id,"receiver_id":t.receiver_id,
          "receiver_name":t.receiver_name,"amount":t.amount,
          "balance_before":t.balance_before,"balance_after":t.balance_after}
    cat = classify_transaction(td)
    direction_counts[compute_direction(cat.category, cat.stress_weight)] += 1

print()
print("  Direction distribution (200 random transactions):")
for d, cnt in direction_counts.most_common():
    pct = cnt / 200 * 100
    print(f"    {d:<10} {cnt:>4} ({pct:.0f}%)")

neutral_pct = direction_counts.get("neutral",0) / 200 * 100
check(f"≥95% of everyday transactions are neutral: {neutral_pct:.0f}%",
      neutral_pct >= 95,
      f"Expected ≥95%, got {neutral_pct:.0f}%")

print()
print("  Top 15 merchants from 200 random transactions:")
for rid, cnt in sorted(Counter(recv_ids).items(), key=lambda x: -x[1])[:15]:
    print(f"    {rid:<40} {cnt}x")


# ── Summary ───────────────────────────────────────────────────────────────
print()
print("=" * 65)
total = PASS_COUNT + FAIL_COUNT
print(f"  RESULTS: {PASS_COUNT}/{total} passed  |  {FAIL_COUNT} failed")
print("=" * 65)
sys.exit(0 if FAIL_COUNT == 0 else 1)