"""
tests/test_integration_layer6.py
─────────────────────────────────────────────────────────────────────────────
Integration test for Layer 6. No DB required — tests logic correctness.
Tests:
  1. PSI math correctness
  2. PSI classification thresholds
  3. AIR calculation formula
  4. run_pipeline.py imports cleanly
  5. All 9 pipeline steps are registered
  6. Monitoring module imports cleanly
─────────────────────────────────────────────────────────────────────────────
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from monitoring.psi_air_monitor import compute_psi, classify_psi

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

rng = np.random.default_rng(42)

print()
print("=" * 60)
print("  SECTION 1: PSI Math")
print("=" * 60)

# Identical distributions → PSI near 0
a = rng.normal(50000, 10000, 1000)
b_same = rng.normal(50000, 10000, 1000)
psi_same = compute_psi(a, b_same)
check(f"Identical dist PSI < 0.10: {psi_same:.4f}", psi_same < 0.10)

# Moderate shift → PSI in WATCH or RETRAIN range
b_mod = rng.normal(60000, 12000, 1000)
psi_mod = compute_psi(a, b_mod)
check(f"Moderate shift PSI > same: {psi_mod:.4f} > {psi_same:.4f}", psi_mod > psi_same)

# Large shift → PSI > 0.25 → RETRAIN
b_large = rng.normal(100000, 30000, 1000)
psi_large = compute_psi(a, b_large)
check(f"Large drift PSI > 0.25: {psi_large:.4f}", psi_large > 0.25)

# Monotonicity: psi_same < psi_mod < psi_large
check(f"PSI monotonic with drift: {psi_same:.3f} < {psi_mod:.3f} < {psi_large:.3f}",
      psi_same < psi_mod < psi_large)

# Edge case: tiny array
psi_tiny = compute_psi(np.array([1.0]), np.array([2.0]))
check(f"Tiny array returns 0.0: {psi_tiny}", psi_tiny == 0.0)

# Edge case: all same value
psi_const = compute_psi(np.ones(100), np.ones(100) * 2)
check(f"Constant arrays don't crash: {psi_const}", isinstance(psi_const, float))

print()
print("=" * 60)
print("  SECTION 2: PSI Classification")
print("=" * 60)

check("PSI 0.05 → STABLE",  classify_psi(0.05)  == "STABLE")
check("PSI 0.09 → STABLE",  classify_psi(0.09)  == "STABLE")
check("PSI 0.10 → WATCH",   classify_psi(0.10)  == "WATCH")
check("PSI 0.20 → WATCH",   classify_psi(0.20)  == "WATCH")
check("PSI 0.25 → RETRAIN", classify_psi(0.25)  == "RETRAIN")
check("PSI 0.80 → RETRAIN", classify_psi(0.80)  == "RETRAIN")

print()
print("=" * 60)
print("  SECTION 3: AIR Formula")
print("=" * 60)

# AIR = group_rate / reference_rate
def calc_air(group_rate, ref_rate):
    return round(group_rate / max(ref_rate, 0.001), 4)

# Group flagged same as reference → AIR = 1.0 → PASS
air_equal = calc_air(0.10, 0.10)
status = "PASS" if 0.80 <= air_equal <= 1.25 else "ALERT"
check(f"Equal rates AIR=1.0 → PASS: {air_equal}", status == "PASS")

# Group flagged at 50% of reference → AIR = 0.50 → ALERT
air_low = calc_air(0.05, 0.10)
status_low = "PASS" if 0.80 <= air_low <= 1.25 else "ALERT"
check(f"Low rate AIR=0.50 → ALERT: {air_low}", status_low == "ALERT")

# Group flagged at 200% of reference → AIR = 2.0 → ALERT
air_high = calc_air(0.20, 0.10)
status_high = "PASS" if 0.80 <= air_high <= 1.25 else "ALERT"
check(f"High rate AIR=2.0 → ALERT: {air_high}", status_high == "ALERT")

# Boundary: AIR = 0.80 → PASS
air_boundary = calc_air(0.08, 0.10)
status_boundary = "PASS" if 0.80 <= air_boundary <= 1.25 else "ALERT"
check(f"Boundary AIR=0.80 → PASS: {air_boundary}", status_boundary == "PASS")

print()
print("=" * 60)
print("  SECTION 4: Pipeline Steps")
print("=" * 60)

# Import run_pipeline and verify steps
import importlib.util
spec = importlib.util.spec_from_file_location("run_pipeline", "run_pipeline.py")
rp   = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

check("run_pipeline.py imports OK",    hasattr(rp, "STEPS"))
check("seed step registered",          "seed"           in rp.STEPS)
check("baselines step registered",     "baselines"      in rp.STEPS)
check("train step registered",         "train"          in rp.STEPS)
check("validate step registered",      "validate"       in rp.STEPS)
check("score step registered",         "score"          in rp.STEPS)
check("monitor step registered",       "monitor"        in rp.STEPS)
check("start-api step registered",     "start-api"      in rp.STEPS)
check("start-consumer step registered","start-consumer" in rp.STEPS)
check("all step registered",           "all"            in rp.STEPS)
check("9 steps total",                 len(rp.STEPS) == 9, f"got {len(rp.STEPS)}")

print()
print("=" * 60)
print("  SECTION 5: Module imports")
print("=" * 60)

try:
    from monitoring.psi_air_monitor import (
        compute_psi, classify_psi,
        run_feature_psi_monitoring, run_score_distribution_psi,
        run_severity_distribution_psi, run_air_monitoring,
        save_monitoring_results, run_all_monitoring,
    )
    check("monitoring.psi_air_monitor imports OK", True)
except ImportError as e:
    check("monitoring.psi_air_monitor imports OK", False, str(e))

try:
    from realtime.pulse_accumulator import (
        compute_direction, compute_delta, apply_delta, assign_risk_tier,
        RELIEF_CATEGORIES, STRESS_CATEGORIES,
    )
    check("realtime.pulse_accumulator imports OK", True)
    check("RELIEF has exactly 2 categories",       len(RELIEF_CATEGORIES) == 2,
          f"got {RELIEF_CATEGORIES}")
    check("STRESS has exactly 3 categories",       len(STRESS_CATEGORIES) == 3,
          f"got {STRESS_CATEGORIES}")
except ImportError as e:
    check("realtime.pulse_accumulator imports OK", False, str(e))

try:
    from scoring_service.app import app
    routes = [r.path for r in app.routes if hasattr(r, "methods")]
    check("scoring_service.app imports OK",          True)
    check("/ingest/transaction endpoint exists",     "/ingest/transaction"             in routes)
    check("/customer/{id}/pulse endpoint exists",    "/customer/{customer_id}/pulse"   in routes)
    check("/customer/{id}/pulse_history exists",     "/customer/{customer_id}/pulse_history" in routes)
    check("/scores/high_risk endpoint exists",       "/scores/high_risk"               in routes)
    check("/health endpoint exists",                 "/health"                         in routes)
except ImportError as e:
    check("scoring_service.app imports OK", False, str(e))

print()
print("=" * 60)
total = PASS_COUNT + FAIL_COUNT
print(f"  RESULTS: {PASS_COUNT}/{total} passed  |  {FAIL_COUNT} failed")
print("=" * 60)
print()
sys.exit(0 if FAIL_COUNT == 0 else 1)