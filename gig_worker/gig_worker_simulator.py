"""
gig_worker/gig_worker_simulator.py
─────────────────────────────────────────────────────────────────────────────
Standalone simulator for Indian gig worker profiles and weekly income streams.

Design philosophy
─────────────────
Unlike salaried workers who receive one monthly credit, gig workers earn income
in weekly platform settlements that are highly volatile.  The key stress signal
is a sudden week-over-week (WoW) income drop of more than 50%.

Stress criterion (hard rule):
    A gig worker is STRESSED if ANY of the last 4 weekly payouts shows a
    WoW income drop > 50% compared to the immediately preceding week.

Simulation window: 16 weeks
    • Weeks 1–12  (baseline)  : normal income with ±25% variation.
    • Weeks 13–16 (real-time) : stressed workers get an abrupt income shock
                                 that cuts earnings to 15–45% of their baseline.

Usage (standalone):
    python -m gig_worker.gig_worker_simulator
─────────────────────────────────────────────────────────────────────────────
"""
import random
import string
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple

import numpy as np

# ── Indian gig platform registry ─────────────────────────────────────────────
GIG_PLATFORMS: List[Tuple[str, str, str]] = [
    # (vpa,                      display_name,                    category)
    ("ubereats@upi",          "Uber Driver Payout",              "RIDE_SHARE"),
    ("oladriver@icicibank",   "Ola Driver Settlement",           "RIDE_SHARE"),
    ("swiggypartner@ybl",     "Swiggy Delivery Partner Payout",  "FOOD_DELIVERY"),
    ("zomatodeliver@axl",     "Zomato Delivery Partner Payout",  "FOOD_DELIVERY"),
    ("blinkitdelivery@upi",   "Blinkit Delivery Partner Payout", "QUICK_COMMERCE"),
    ("zepto@okaxis",          "Zepto Delivery Partner Payout",   "QUICK_COMMERCE"),
    ("dunzopartner@okaxis",   "Dunzo Partner Payout",            "QUICK_COMMERCE"),
    ("uclap@ybl",             "Urban Company Partner Payout",    "HOME_SERVICES"),
    ("porterpartner@upi",     "Porter Partner Payout",           "LOGISTICS"),
    ("rapidopartner@upi",     "Rapido Bike Partner Payout",      "RIDE_SHARE"),
    ("taskmo@icicibank",      "Taskmo Gig Payout",               "FIELD_SERVICES"),
    ("workindia@ybl",         "WorkIndia Gig Payout",            "GENERAL_GIG"),
    ("gigworks@upi",          "GigWorks Platform Payout",        "GENERAL_GIG"),
    ("meesho_partner@upi",    "Meesho Reseller Payout",          "ECOMMERCE_RESELLER"),
]

# ── Expected weekly income ranges by platform category (Indian 2024, ₹) ──────
WEEKLY_INCOME_BY_CATEGORY: Dict[str, Tuple[float, float]] = {
    "RIDE_SHARE":          (3_500, 12_000),   # Uber/Ola drivers, city-dependent
    "FOOD_DELIVERY":       (2_500,  9_000),   # Swiggy/Zomato delivery partners
    "QUICK_COMMERCE":      (2_000,  7_500),   # Blinkit/Zepto dark-store riders
    "HOME_SERVICES":       (4_000, 14_000),   # Urban Company plumbers/electricians
    "LOGISTICS":           (3_000, 10_000),   # Porter, Lalamove drivers
    "FIELD_SERVICES":      (2_000,  7_000),   # Taskmo survey/merchandising tasks
    "GENERAL_GIG":         (1_500,  6_500),   # WorkIndia, GigWorks varied tasks
    "ECOMMERCE_RESELLER":  (1_000,  5_000),   # Meesho resellers (low-end gig)
}

# Indian name pools for profile generation
FIRST_NAMES_MALE   = ["Rahul", "Ravi", "Amit", "Suresh", "Ramesh", "Vijay", "Arjun",
                       "Nikhil", "Deepak", "Sanjay", "Manoj", "Pradeep", "Arun", "Vinod"]
FIRST_NAMES_FEMALE = ["Priya", "Sunita", "Kavita", "Anita", "Rekha", "Meena", "Pooja",
                       "Savita", "Geeta", "Anjali", "Nisha", "Swati", "Divya", "Ritu"]
LAST_NAMES = ["Kumar", "Singh", "Sharma", "Verma", "Yadav", "Gupta", "Patel", "Shah",
              "Mehta", "Joshi", "Nair", "Reddy", "Pillai", "Iyer", "Das", "Mishra"]

INDIAN_CITIES = [
    ("Mumbai", "Maharashtra"), ("Delhi", "Delhi"), ("Bengaluru", "Karnataka"),
    ("Hyderabad", "Telangana"), ("Chennai", "Tamil Nadu"), ("Pune", "Maharashtra"),
    ("Ahmedabad", "Gujarat"), ("Kolkata", "West Bengal"), ("Jaipur", "Rajasthan"),
    ("Lucknow", "Uttar Pradesh"), ("Surat", "Gujarat"), ("Kochi", "Kerala"),
    ("Chandigarh", "Punjab"), ("Indore", "Madhya Pradesh"), ("Nagpur", "Maharashtra"),
]

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class WeeklyPayoutRecord:
    """One week's platform payout for a gig worker."""
    week_num:      int         # 1–16
    week_label:    str         # e.g. "W01"
    payout_amount: float       # ₹ credited this week
    platform_vpa:  str
    platform_name: str
    is_stress_week: bool       # True for weeks 13–16 of stressed workers
    wow_change:    float = 0.0 # (this_week - last_week) / last_week; 0.0 for week 1


@dataclass
class GigWorkerProfile:
    """Synthetic Indian gig worker profile."""
    worker_id:          str
    first_name:         str
    last_name:          str
    gender:             str
    city:               str
    state:              str
    phone:              str
    upi_vpa:            str
    platform_vpa:       str
    platform_name:      str
    platform_category:  str
    baseline_weekly_income: float   # expected normal weekly earnings (₹)
    develops_stress:    bool        # True → gets income shock in weeks 13–16
    weekly_payouts:     List[WeeklyPayoutRecord] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_stressed(self) -> bool:
        """
        Stress criterion: WoW income drop > 50% in ANY of weeks 13–16.
        This is the ground-truth label used to train/evaluate the classifier.
        """
        for record in self.weekly_payouts:
            if record.week_num >= 13 and record.wow_change < -0.50:
                return True
        return False

    @property
    def max_wow_drop(self) -> float:
        """Most negative WoW change seen in weeks 13–16 (positive = bigger drop)."""
        drops = [
            -r.wow_change
            for r in self.weekly_payouts
            if r.week_num >= 13 and r.wow_change < 0
        ]
        return max(drops) if drops else 0.0

    def recent_weekly_incomes(self, n: int = 8) -> List[float]:
        """Last n weekly payout amounts (most recent last)."""
        amounts = [r.payout_amount for r in self.weekly_payouts]
        return amounts[-n:]

    def recent_wow_changes(self, n: int = 7) -> List[float]:
        """Last n WoW changes (most recent last), skipping week 1."""
        changes = [r.wow_change for r in self.weekly_payouts if r.week_num > 1]
        return changes[-n:]


# ── Core simulation functions ─────────────────────────────────────────────────

def _generate_profile(rng: random.Random, idx: int) -> GigWorkerProfile:
    """Generate one synthetic Indian gig worker profile."""
    gender     = rng.choice(["Male", "Female"])
    first_name = rng.choice(FIRST_NAMES_MALE if gender == "Male" else FIRST_NAMES_FEMALE)
    last_name  = rng.choice(LAST_NAMES)
    city, state = rng.choice(INDIAN_CITIES)

    # Pick platform
    vpa, name, category = rng.choice(GIG_PLATFORMS)
    lo, hi = WEEKLY_INCOME_BY_CATEGORY[category]
    baseline_weekly = round(rng.uniform(lo, hi) / 100) * 100  # ₹100 increments

    # Phone (Indian mobile)
    phone = rng.choice("6789") + "".join(rng.choices(string.digits, k=9))

    # UPI VPA  (e.g. rahul.kumar4@oksbi)
    bank_codes = ["oksbi", "okaxis", "ybl", "icicibank", "upi", "okicici"]
    slug = f"{first_name.lower()}.{last_name.lower()}{rng.randint(1, 99)}"
    upi_vpa = f"{slug}@{rng.choice(bank_codes)}"

    # Stress flag: deterministic from worker_id hash (mirrors Sentinel's approach)
    worker_id = str(uuid.uuid4())
    seed_val  = hash(worker_id) % (2 ** 31)
    stress_rng = random.Random(seed_val)
    develops_stress = stress_rng.random() < 0.35   # 35% stress prevalence for gig workers

    return GigWorkerProfile(
        worker_id=worker_id,
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        city=city,
        state=state,
        phone=phone,
        upi_vpa=upi_vpa,
        platform_vpa=vpa,
        platform_name=name,
        platform_category=category,
        baseline_weekly_income=baseline_weekly,
        develops_stress=develops_stress,
    )


def _simulate_weekly_payouts(
    profile: GigWorkerProfile,
    n_weeks: int = 16,
    rng: random.Random = None,
    np_rng: np.random.Generator = None,
) -> List[WeeklyPayoutRecord]:
    """
    Simulate n_weeks of weekly platform payouts for one gig worker.

    Weeks 1–12  : normal income ± 25% variation.
    Weeks 13–16 : for stressed workers, abrupt shock cuts income to 15–45%
                  of baseline — creating WoW drops > 50% immediately.

    Returns list of WeeklyPayoutRecord (one per week).
    """
    if rng is None:
        seed = hash(profile.worker_id) % (2 ** 31)
        rng = random.Random(seed + 1)          # +1 so it differs from stress seed
    if np_rng is None:
        seed = hash(profile.worker_id) % (2 ** 31)
        np_rng = np.random.default_rng(seed + 1)

    base = profile.baseline_weekly_income
    records: List[WeeklyPayoutRecord] = []
    prev_amount: float = base  # for WoW calculation

    STRESS_WINDOW_START = 13

    for week in range(1, n_weeks + 1):
        is_stress_week = profile.develops_stress and week >= STRESS_WINDOW_START

        if is_stress_week:
            # Ramp from week 13: ramp goes 0→1 over the 4 stress weeks
            ramp = (week - STRESS_WINDOW_START) / max(1, (n_weeks - STRESS_WINDOW_START))
            # shock_floor: 0.44 at start of stress window → 0.15 at end.
            # Multiplier capped at 0.92 so week-13 payout is at most 0.40*base,
            # guaranteeing WoW > 50% drop even if previous week was near-baseline.
            shock_floor = max(0.15, 0.44 - ramp * 0.29)
            amount = round(base * shock_floor * np_rng.uniform(0.78, 0.92))
        else:
            amount = round(base * np_rng.uniform(0.75, 1.25))

        amount = max(amount, 300)   # ₹300 floor (even worst week has some income)

        # Week-over-week change
        wow = (amount - prev_amount) / prev_amount if prev_amount > 0 else 0.0
        # Week 1 has no prior reference — WoW = 0.0 by convention
        wow = round(wow, 4) if week > 1 else 0.0

        records.append(WeeklyPayoutRecord(
            week_num=week,
            week_label=f"W{week:02d}",
            payout_amount=float(amount),
            platform_vpa=profile.platform_vpa,
            platform_name=profile.platform_name,
            is_stress_week=is_stress_week,
            wow_change=wow,
        ))
        prev_amount = amount

    return records


def simulate_gig_workers(
    n: int = 300,
    seed: int = 42,
    n_weeks: int = 16,
) -> List[GigWorkerProfile]:
    """
    Generate and simulate n Indian gig worker profiles.

    Args:
        n:       Number of gig workers to simulate.
        seed:    Master random seed for reproducibility.
        n_weeks: Weeks of income history per worker.

    Returns:
        List of fully populated GigWorkerProfile objects.
    """
    master_rng = random.Random(seed)
    profiles: List[GigWorkerProfile] = []

    for i in range(n):
        profile = _generate_profile(master_rng, idx=i)
        payout_rng    = random.Random(master_rng.randint(0, 2 ** 31))
        payout_np_rng = np.random.default_rng(master_rng.randint(0, 2 ** 31))
        profile.weekly_payouts = _simulate_weekly_payouts(
            profile, n_weeks=n_weeks,
            rng=payout_rng, np_rng=payout_np_rng,
        )
        profiles.append(profile)

    return profiles


def profiles_to_feature_records(
    profiles: List[GigWorkerProfile],
    n_income_weeks: int = 8,
) -> List[Dict[str, Any]]:
    """
    Convert profiles into flat feature dicts for ML training/inference.

    The model receives raw weekly income amounts (week_1 … week_N) as features.
    WoW ratios are NOT explicit feature columns.  Instead, the stress-signal
    aggregate max_recent_wow_drop is derived mathematically from consecutive
    (prev_week_income, curr_week_income) pairs using the formula:

        drop_i = (prev_week_income - curr_week_income) / prev_week_income

    This is applied to each consecutive pair in the last 4 weeks; the maximum
    such drop is stored as max_recent_wow_drop.

    Features (per worker):
      week_1 … week_N          : last N raw weekly payout amounts (₹ income)
                                   N = n_income_weeks (set via --weeks-span)
      income_cv                : coefficient of variation of last N weeks
      max_recent_wow_drop      : largest (prev-curr)/prev drop in last 4 weeks
                                   (0→1 scale; >0.50 = stressed territory)
      recent_income_trend      : normalised linear slope of last 4 weekly incomes
      income_vs_8w_avg         : latest week / N-week rolling average
      platform_category_code   : integer encoding of platform category

    Label:
      is_stressed (int 0/1): 1 if WoW drop > 50% in any of the last 4 weeks.
    """
    CATEGORY_CODES = {
        "RIDE_SHARE": 0, "FOOD_DELIVERY": 1, "QUICK_COMMERCE": 2,
        "HOME_SERVICES": 3, "LOGISTICS": 4, "FIELD_SERVICES": 5,
        "GENERAL_GIG": 6, "ECOMMERCE_RESELLER": 7,
    }
    records = []
    for p in profiles:
        incomes = p.recent_weekly_incomes(n_income_weeks)

        # Pad to fixed length if fewer weeks were generated
        while len(incomes) < n_income_weeks:
            incomes.insert(0, incomes[0] if incomes else 0.0)

        arr = np.array(incomes, dtype=float)
        cv  = float(np.std(arr) / np.mean(arr)) if np.mean(arr) > 0 else 0.0

        # max_recent_wow_drop — mathematical formula on raw (prev, curr) income pairs
        # For each consecutive pair in the last 4 weeks:
        #   drop = (prev_week_income - curr_week_income) / prev_week_income
        # We take the maximum drop (largest income fall), capped at 1.0.
        last4_inc = list(arr[-4:])
        drops: List[float] = []
        for i in range(1, len(last4_inc)):
            prev_w, curr_w = last4_inc[i - 1], last4_inc[i]
            if prev_w > 0 and curr_w < prev_w:
                drops.append((prev_w - curr_w) / prev_w)
        max_drop = min(max(drops) if drops else 0.0, 1.0)

        # Trend: linear regression slope on last 4 weeks (normalised)
        if len(last4_inc) >= 2 and arr[-1] > 0:
            xs = np.arange(len(last4_inc), dtype=float)
            slope = float(np.polyfit(xs, last4_inc, 1)[0])
            trend = slope / float(arr[-1])
        else:
            trend = 0.0

        income_vs_avg = (
            float(arr[-1]) / float(np.mean(arr)) if np.mean(arr) > 0 else 1.0
        )

        row: Dict[str, Any] = {}
        # Raw weekly incomes — model sees each week's income directly
        for i, val in enumerate(incomes, start=1):
            row[f"week_{i}"] = round(val, 2)
        # WoW ratios intentionally omitted; drop signal captured in max_recent_wow_drop
        row["income_cv"]           = round(cv, 4)
        row["max_recent_wow_drop"] = round(max_drop, 4)
        row["recent_income_trend"] = round(trend, 6)
        row["income_vs_8w_avg"]    = round(income_vs_avg, 4)
        row["platform_category_code"] = CATEGORY_CODES.get(p.platform_category, 6)
        row["is_stressed"]         = int(p.is_stressed)
        # Metadata (not features — for reporting only)
        row["_worker_id"]    = p.worker_id
        row["_name"]         = p.full_name
        row["_city"]         = p.city
        row["_platform"]     = p.platform_name
        row["_category"]     = p.platform_category
        row["_max_wow_drop"] = round(p.max_wow_drop, 4)
        row["_baseline_weekly_income"] = p.baseline_weekly_income
        records.append(row)
    return records


def pairs_to_feature_records(
    weekly_payouts: List[WeeklyPayoutRecord],
) -> List[Dict[str, Any]]:
    """
    Convert a worker's weekly payout list into one record per consecutive
    (prev_week_income, curr_week_income) pair.

    The model receives only the raw prev and curr income amounts.
    The stress label for each pair is computed as:
        drop = (prev_week_income - curr_week_income) / prev_week_income
        is_stress_transition = 1  if  drop > 0.50

    Args:
        weekly_payouts: Ordered list of WeeklyPayoutRecord (week 1 first).

    Returns:
        List of dicts, one per consecutive pair (N-1 entries for N weeks):
          prev_week_income     : payout amount of the earlier week  (₹)
          curr_week_income     : payout amount of the later week    (₹)
          prev_week_num        : week index of the prev record
          curr_week_num        : week index of the curr record
          drop_pct             : (prev - curr) / prev × 100  (positive = drop)
          is_stress_transition : 1 if drop > 50%, else 0  (ground-truth label)
    """
    records: List[Dict[str, Any]] = []
    for i in range(1, len(weekly_payouts)):
        prev = weekly_payouts[i - 1]
        curr = weekly_payouts[i]
        prev_inc = float(prev.payout_amount)
        curr_inc = float(curr.payout_amount)
        drop = (prev_inc - curr_inc) / prev_inc if prev_inc > 0 else 0.0
        records.append({
            "prev_week_income":     round(prev_inc, 2),
            "curr_week_income":     round(curr_inc, 2),
            "prev_week_num":        prev.week_num,
            "curr_week_num":        curr.week_num,
            "drop_pct":             round(drop * 100, 4),
            "is_stress_transition": int(drop > 0.50),
        })
    return records


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """
    Run the gig worker simulation and print a summary report.
    Useful for quick manual validation without the ML classifier.
    """
    print("=" * 70)
    print("  SENTINEL V2 — Gig Worker Simulator")
    print("  Simulating 300 Indian gig workers × 16 weeks of income data")
    print("=" * 70)

    profiles = simulate_gig_workers(n=300, seed=42)

    total       = len(profiles)
    stressed    = sum(1 for p in profiles if p.is_stressed)
    not_stressed = total - stressed

    print(f"\n  Total gig workers simulated : {total}")
    print(f"  Stressed (WoW drop > 50%)   : {stressed}  ({stressed/total*100:.1f}%)")
    print(f"  Not stressed                : {not_stressed} ({not_stressed/total*100:.1f}%)")

    # Platform distribution
    from collections import Counter
    cat_counts = Counter(p.platform_category for p in profiles)
    print("\n  Platform category breakdown:")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<25} {cnt:>4} workers")

    # Sample: show 5 stressed + 5 not-stressed workers
    print("\n  ── Sample STRESSED workers (first 5) ──────────────────────────")
    shown = 0
    for p in profiles:
        if p.is_stressed and shown < 5:
            worst = min(r.wow_change for r in p.weekly_payouts if r.week_num >= 13)
            print(
                f"  {p.full_name:<22} | {p.platform_category:<20} | "
                f"{p.city:<12} | Worst WoW: {worst*100:+.1f}%  "
                f"| Baseline ₹{p.baseline_weekly_income:,.0f}/wk"
            )
            shown += 1

    print("\n  ── Sample NOT-STRESSED workers (first 5) ─────────────────────")
    shown = 0
    for p in profiles:
        if not p.is_stressed and shown < 5:
            wows = [r.wow_change for r in p.weekly_payouts if r.week_num >= 13]
            best_wow = max(wows) if wows else 0.0
            print(
                f"  {p.full_name:<22} | {p.platform_category:<20} | "
                f"{p.city:<12} | Best WoW: {best_wow*100:+.1f}%  "
                f"| Baseline ₹{p.baseline_weekly_income:,.0f}/wk"
            )
            shown += 1

    print("\n" + "=" * 70)
    print("  Simulation complete. Run gig_stress_classifier.py to train model.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
