"""
SENTINEL V2 — Central Configuration
All settings read from .env via Pydantic. Nothing hardcoded.
"""

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # ── PostgreSQL ──────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "sentinel"
    POSTGRES_USER: str = "sentinel_user"
    POSTGRES_PASSWORD: str = "sentinel_secure_2024"

    @property
    def POSTGRES_URL(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def ASYNC_POSTGRES_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # ── Kafka ────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # Kafka topics
    TOPIC_RAW_TRANSACTIONS: str = "sentinel.raw.transactions"
    TOPIC_TRANSACTION_PULSE: str = "sentinel.transaction.pulse"
    TOPIC_SCORES_PULSE: str = "sentinel.scores.pulse"
    TOPIC_ALERTS_HIGH: str = "sentinel.alerts.high-risk"
    TOPIC_INTERVENTIONS_SENT: str = "sentinel.interventions.sent"
    TOPIC_DLQ_ERRORS: str = "sentinel.dlq.errors"

    # ── Application ──────────────────────────────────────────────
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SCORING_SERVICE_PORT: int = 8001

    # ── External AI APIs ─────────────────────────────────────────
    GROQ_API_KEY: str = ""

    # ── Synthetic Data ───────────────────────────────────────────
    NUM_CUSTOMERS: int = 1500

    # ── Pulse Score Accumulator ──────────────────────────────────
    # All values are configuration — nothing is hardcoded in the engine itself.
    PULSE_DAMPING_NOISE_FLOOR: float = 0.10        # severity below this → delta = 0
    PULSE_HIGH_SCORE_DAMPING: float = 0.30          # damping factor when score is near-critical
    PULSE_HIGH_SCORE_THRESHOLD: float = 0.80        # score above this → apply high-score damping
    PULSE_RECOVERY_AMPLIFICATION: float = 1.50      # amplification for recovering customers
    PULSE_LOW_SCORE_THRESHOLD: float = 0.20         # score below this → apply recovery amplification
    PULSE_MAX_SINGLE_DELTA: float = 0.15            # max delta per transaction (normal)
    PULSE_MAX_HEINOUS_DELTA: float = 0.30           # max delta for heinous events
    PULSE_HEINOUS_THRESHOLD: float = 0.90           # severity >= this → heinous classification

    # ── Baseline Builder ─────────────────────────────────────────
    BASELINE_WINDOW_DAYS: int = 90                  # days used for baseline computation
    BASELINE_HISTORY_TOTAL_DAYS: int = 120          # total history generated per customer
    BASELINE_SNAPSHOT_INTERVAL_DAYS: int = 7        # interval between feature snapshots
    BASELINE_MIN_TRANSACTIONS: int = 10             # minimum txns to build a valid baseline
    BASELINE_REDIS_TTL_HOURS: int = 168             # 7 days in hours

    # ── Model Settings ───────────────────────────────────────────
    PULSE_SCORER_FEATURES: int = 48                 # total input features to PulseScorer
    PULSE_SCORER_MIN_CONFIDENCE: float = 0.55       # min model confidence to act on score
    MODEL_RETRAIN_PSI_THRESHOLD: float = 0.25       # PSI above this → trigger retrain

    # ── Risk Tier Thresholds (on [0.0, 1.0] scale) ───────────────
    RISK_TIER_CRITICAL: float = 0.75
    RISK_TIER_HIGH: float = 0.55
    RISK_TIER_MODERATE: float = 0.40
    RISK_TIER_WATCH: float = 0.25
    # Below WATCH = STABLE (Tier 5)

    class Config:
        env_file = os.path.join(Path(__file__).resolve().parent.parent, ".env")
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()


# ── Domain Constants ─────────────────────────────────────────────
# These are domain knowledge constants, not ML parameters.
# They are used by the transaction classifier and feature engine.

# LGD (Loss Given Default) by loan type — Indian banking norms
LGD_BY_LOAN_TYPE: dict = {
    "HOME": 0.20,
    "PERSONAL": 0.40,
    "AUTO": 0.30,
    "EDUCATION": 0.35,
    "BUSINESS": 0.45,
    "CREDIT_CARD": 0.60,
}

# Known UPI VPA patterns for lending apps
# Format: partial VPA string used for ILIKE matching
UPI_LENDING_APP_VPAS: list = [
    "slice@",
    "lazypay@",
    "simpl@",
    "postpe@",
    "kissht@",
    "zestmoney@",
    "flexmoney@",
    "earlysalary@",
    "moneyview@",
    "navi@",
    "fibe@",
    "cashe@",
    "kreditbee@",
    "mpokket@",
    "payrupik@",
    "stashfin@",
    "ringplus@",
    "smytten@",
]

# BBPS biller VPA patterns for utility detection
BBPS_UTILITY_VPAS: list = [
    "bescom@bbps",
    "tatapower@bbps",
    "adanigas@bbps",
    "bsnl@bbps",
    "airtel@bbps",
    "jio@bbps",
    "mahanagar@bbps",
    "torrentpower@bbps",
    "mseb@bbps",
    "tneb@bbps",
    "cesc@bbps",
    "dgvcl@bbps",
    "pgvcl@bbps",
]

# NACH/ECS EMI auto-debit patterns (partial receiver_id)
NACH_EMI_PATTERNS: list = [
    "@nach",
    "@ecs",
    "_NACH_",
    "_EMI_",
    "AUTODEBIT",
    "ECS_DEBIT",
]

# Employer payroll sender_id patterns (used by transaction classifier)
PAYROLL_SENDER_PATTERNS: list = [
    "payroll",
    "salary",
    "_sal@",
    "pension",
    "stipend",
    "tcspayroll",
    "infosys_payroll",
    "wipropayroll",
    "hclpay",
    "cognizant_payroll",
    "cgg_salary",
    "stategov_sal",
    "irctcpayroll",
    "apollohr",
    "iitd_salary",
    "amity_payroll",
]

# Indian states with geographic risk tiers (based on delinquency data)
GEO_RISK_TIERS: dict = {
    1: ["Maharashtra", "Karnataka", "Tamil Nadu", "Gujarat", "Delhi", "Telangana"],
    2: ["Kerala", "Haryana", "Punjab", "West Bengal", "Andhra Pradesh", "Rajasthan"],
    3: ["Madhya Pradesh", "Uttar Pradesh", "Odisha", "Chhattisgarh", "Jharkhand"],
    4: ["Bihar", "Assam", "Manipur", "Meghalaya", "Tripura", "Nagaland", "Mizoram"],
}

# Reverse lookup: state → risk tier
STATE_TO_RISK_TIER: dict = {}
for _tier, _states in GEO_RISK_TIERS.items():
    for _state in _states:
        STATE_TO_RISK_TIER[_state] = _tier

# Indian cities by state
CITIES_BY_STATE: dict = {
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Thane", "Nashik", "Aurangabad", "Solapur"],
    "Karnataka": ["Bengaluru", "Mysuru", "Hubli", "Mangaluru", "Belagavi"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Salem", "Tiruchirappalli"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar"],
    "Delhi": ["New Delhi", "Dwarka", "Rohini", "Saket", "Janakpuri", "Noida Extension"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar"],
    "Kerala": ["Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur"],
    "Haryana": ["Gurugram", "Faridabad", "Panipat", "Ambala", "Karnal"],
    "Punjab": ["Chandigarh", "Ludhiana", "Amritsar", "Jalandhar", "Patiala"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Siliguri", "Asansol"],
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Tirupati", "Guntur"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota", "Ajmer"],
    "Madhya Pradesh": ["Bhopal", "Indore", "Gwalior", "Jabalpur"],
    "Uttar Pradesh": ["Lucknow", "Noida", "Kanpur", "Agra", "Varanasi", "Ghaziabad"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela"],
    "Chhattisgarh": ["Raipur", "Bhilai", "Bilaspur"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad"],
    "Bihar": ["Patna", "Gaya", "Muzaffarpur"],
    "Assam": ["Guwahati", "Silchar", "Dibrugarh"],
    "Manipur": ["Imphal"],
    "Meghalaya": ["Shillong"],
    "Tripura": ["Agartala"],
    "Nagaland": ["Kohima", "Dimapur"],
    "Mizoram": ["Aizawl"],
}