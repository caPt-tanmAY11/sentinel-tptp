"""
demo_report.py
─────────────────────────────────────────────────────────────────────────────
SENTINEL V2 — Full Demo with Officer Review Workflow

Demonstrates the complete dual-report pipeline:

  Step 1 — Generate Report A (Bank Internal Compliance Record)
  Step 2 — Get AI intervention suggestions (for reviewing officer)
  Step 3 — Officer reviews suggestions and picks intervention method
  Step 4 — Generate Report B (Customer Wellness Notice) with officer's plan

Run with:
  $env:PYTHONPATH="."
  $env:GROQ_API_KEY="your-key-here"
  py -m report_generator.demo_report
─────────────────────────────────────────────────────────────────────────────
"""

import os
import json
from report_generator.report_generator import SentinelReportGenerator, INTERVENTION_METHODS
from report_generator.pdf_builder import BankReportPDFBuilder, CustomerNoticePDFBuilder


# ── Mock Data ──────────────────────────────────────────────────────────────

CUSTOMER_DATA = {
    "customer_id":         "CUST-004821",
    "name":                "Rajesh Kumar Sharma",
    "account_type":        "Savings / Overdraft",
    "pan":                 "ABCDE1234F",
    "mobile_masked":       "XXXXXX4821",
    "branch":              "Mumbai Bandra",
    "account_opened_date": "2020-01-15",
    "credit_limit":        500000.00,
}

PULSE_DATA = {
    "pulse_score":          0.8241,
    "risk_tier":            {"label": "CRITICAL", "tier": 1},
    "trend_7d":             "Deteriorating",
    "trend_30d":            "Volatile",
    "total_events_scored":  150,
    "stress_events_count":  3,
}

TRANSACTIONS = [
    {
        "event_id":          "TXN-20240315-001",
        "timestamp":         "2024-03-15T09:32:11",
        "amount":            12500.00,
        "platform":          "KreditBee",
        "inferred_category": "LENDING_APP_DEBIT",
        "pulse_delta":       0.18,
        "new_pulse_score":   0.7100,
        "severity":          0.8200,
    },
    {
        "event_id":          "TXN-20240318-007",
        "timestamp":         "2024-03-18T14:05:43",
        "amount":            8750.00,
        "platform":          "MoneyTap",
        "inferred_category": "LENDING_APP_DEBIT",
        "pulse_delta":       0.12,
        "new_pulse_score":   0.7741,
        "severity":          0.7100,
    },
    {
        "event_id":          "TXN-20240321-003",
        "timestamp":         "2024-03-21T08:17:59",
        "amount":            5000.00,
        "platform":          "NACH/ECS",
        "inferred_category": "FAILED_EMI_DEBIT",
        "pulse_delta":       0.05,
        "new_pulse_score":   0.8241,
        "severity":          0.9300,
    },
]

BASELINE_DATA = {
    "baseline_period":     "Oct 2023 – Dec 2023",
    "avg_monthly_credits": 85000.00,
    "avg_monthly_debits":  72000.00,
    "typical_platforms":   ["HDFC NetBanking", "GPay", "NACH/ECS"],
    "salary_regularity":   "Regular (1st–5th of month)",
    "emi_compliance_rate": "98%",
}

MODEL_STATS = {
    "total_transactions_processed": "1,42,308",
    "total_customers_scored":       "18,724",
    "customers_flagged":            "342",
    "flag_rate":                    "1.83%",
    "avg_pulse_score":              "0.21",
    "avg_latency_ms":               "87ms",
    "false_positive_rate":          "~9.2%",
    "psi":                          "0.038 — Stable",
    "air":                          "0.93 — Within RBI threshold",
    "last_retrain":                 "January 2024",
    "next_audit":                   "July 2024",
}


def save_json(data: dict, filename: str):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"  📄 JSON → {filename}")


def save_pdf(pdf_bytes: bytes, filename: str):
    with open(filename, "wb") as f:
        f.write(pdf_bytes)
    print(f"  📑 PDF  → {filename}")


def officer_review(suggestions: dict) -> tuple[str, str]:
    """
    Simulate the officer review step.
    In production, this would be a UI / API call.
    Returns (chosen_method_key, officer_notes).
    """
    print("\n" + "═" * 65)
    print("  OFFICER REVIEW — AI INTERVENTION SUGGESTIONS")
    print("═" * 65)
    print(f"\n  Customer : {suggestions['customer_name']}")
    print(f"  Tier     : {suggestions['tier']}")
    print(f"  Score    : {suggestions['pulse_score']:.4f}\n")
    print("  AI RECOMMENDATION:")
    print("  " + "-" * 60)
    for line in suggestions["ai_suggestion_text"].split("\n"):
        print(f"  {line}")
    print("  " + "-" * 60)

    print("\n  SUITABLE INTERVENTION METHODS:")
    suitable = suggestions["suitable_methods"]
    method_keys = list(suitable.keys())
    for i, (key, method) in enumerate(suitable.items(), 1):
        print(f"\n  [{i}] {method['name']}")
        print(f"      {method['description']}")

    print("\n" + "═" * 65)

    # In a real system, officer picks via UI.
    # For demo: auto-select based on AI suggestion or default.
    # We simulate the officer choosing option 1 (top recommendation).
    chosen_key = method_keys[0] if method_keys else "WELLNESS_CHECKIN"

    print(f"\n  [DEMO] Officer selected: [{chosen_key}] "
          f"{suitable.get(chosen_key, {}).get('name', chosen_key)}")

    officer_notes = (
        "Customer has been with Barclays for 4+ years with strong EMI compliance history. "
        "The digital lending activity is recent. Recommend empathetic first contact. "
        "Do not initiate formal restructuring unless customer requests it."
    )
    print(f"\n  [DEMO] Officer notes added.")
    print("═" * 65)

    return chosen_key, officer_notes


def main():
    print("\n" + "═" * 65)
    print("  SENTINEL V2 — DUAL REPORT GENERATOR")
    print("  Barclays Bank India — Customer Wellness Programme")
    print("═" * 65)

    # ── Initialise ─────────────────────────────────────────────────────
    try:
        generator = SentinelReportGenerator()
        print("\n  ✅ Generator initialised (Groq / Llama 3.3 70B)")
    except ValueError as e:
        print(f"\n  ❌ {e}")
        return

    customer_id = CUSTOMER_DATA["customer_id"]

    # ══════════════════════════════════════════════════════════════════
    #  STEP 1 — Generate Report A (Bank Internal Compliance Record)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "─" * 65)
    print("  STEP 1/4 — Generating Report A: Bank Internal Compliance Record")
    print("─" * 65)

    try:
        bank_report = generator.generate_bank_report(
            customer_data=CUSTOMER_DATA,
            pulse_data=PULSE_DATA,
            transactions=TRANSACTIONS,
            model_stats=MODEL_STATS,
            officer_name="Ananya Krishnamurthy",
        )
        print("  ✅ Bank report data generated")
        save_json(bank_report, f"bank_report_{customer_id}.json")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback; traceback.print_exc()
        return

    print("  Building Bank Report PDF...")
    try:
        bank_pdf = BankReportPDFBuilder().build(bank_report)
        save_pdf(bank_pdf, f"bank_report_{customer_id}.pdf")
    except Exception as e:
        print(f"  ❌ PDF error: {e}")
        import traceback; traceback.print_exc()
        return

    # ══════════════════════════════════════════════════════════════════
    #  STEP 2 — Get AI Intervention Suggestions for Officer
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "─" * 65)
    print("  STEP 2/4 — Getting AI Intervention Suggestions for Reviewing Officer")
    print("─" * 65)

    try:
        suggestions = generator.get_intervention_suggestions(
            customer_data=CUSTOMER_DATA,
            pulse_data=PULSE_DATA,
            transactions=TRANSACTIONS,
        )
        print("  ✅ AI suggestions generated")
        save_json(suggestions, f"officer_brief_{customer_id}.json")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback; traceback.print_exc()
        return

    # ══════════════════════════════════════════════════════════════════
    #  STEP 3 — Officer Review (interactive / simulated)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "─" * 65)
    print("  STEP 3/4 — Officer Reviews Suggestions & Picks Intervention Method")
    print("─" * 65)

    chosen_method, officer_notes = officer_review(suggestions)

    # ══════════════════════════════════════════════════════════════════
    #  STEP 4 — Generate Report B (Customer Wellness Notice)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "─" * 65)
    print("  STEP 4/4 — Generating Report B: Customer Wellness Notice")
    print("─" * 65)

    try:
        customer_notice = generator.generate_customer_notice(
            customer_data=CUSTOMER_DATA,
            pulse_data=PULSE_DATA,
            transactions=TRANSACTIONS,
            baseline_data=BASELINE_DATA,
            chosen_method_key=chosen_method,
            officer_notes=officer_notes,
            officer_name="Ananya Krishnamurthy",
        )
        print("  ✅ Customer notice data generated")
        save_json(customer_notice, f"customer_notice_{customer_id}.json")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback; traceback.print_exc()
        return

    print("  Building Customer Notice PDF...")
    try:
        cust_pdf = CustomerNoticePDFBuilder().build(customer_notice)
        save_pdf(cust_pdf, f"customer_notice_{customer_id}.pdf")
    except Exception as e:
        print(f"  ❌ PDF error: {e}")
        import traceback; traceback.print_exc()
        return

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  ✅ ALL DONE — Files generated:")
    print(f"\n  REPORT A (Internal — keep with bank):")
    print(f"    bank_report_{customer_id}.pdf")
    print(f"    bank_report_{customer_id}.json")
    print(f"\n  OFFICER BRIEF (for review process):")
    print(f"    officer_brief_{customer_id}.json")
    print(f"\n  REPORT B (Send to customer):")
    print(f"    customer_notice_{customer_id}.pdf")
    print(f"    customer_notice_{customer_id}.json")
    print("\n" + "═" * 65)


if __name__ == "__main__":
    main()