# SENTINEL V2 — Pre-Delinquency Intelligence Platform

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=nextdotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)
![LightGBM](https://img.shields.io/badge/LightGBM-4.3-lightgreen?style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Kafka](https://img.shields.io/badge/Apache_Kafka-3.7-231F20?style=flat-square&logo=apachekafka&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)

**A real-time behavioral stress scoring engine for Indian retail banking.**  
Detects pre-delinquency signals from raw transaction streams — before a single EMI is missed.

[Architecture](#architecture) · [Quick Start](#quick-start) · [Pipeline](#pipeline) · [API Reference](#api-reference) · [Dashboard](#dashboard) · [Configuration](#configuration) · [Testing](#testing)

</div>

---

## Table of Contents

1. [What is Sentinel V2?](#1-what-is-sentinel-v2)
2. [Key Design Principles](#2-key-design-principles)
3. [Architecture](#3-architecture)
4. [Tech Stack](#4-tech-stack)
5. [Project Structure](#5-project-structure)
6. [Prerequisites](#6-prerequisites)
7. [Quick Start](#7-quick-start)
8. [Pipeline — Step by Step](#8-pipeline--step-by-step)
9. [How the Scoring Works](#9-how-the-scoring-works)
10. [Feature Catalog](#10-feature-catalog)
11. [API Reference](#11-api-reference)
12. [Dashboard](#12-dashboard)
13. [Configuration](#13-configuration)
14. [Real-Time Injection & Testing](#14-real-time-injection--testing)
15. [Monitoring](#15-monitoring)
16. [Indian Banking Context](#16-indian-banking-context)
17. [Testing](#17-testing)
18. [Roadmap](#18-roadmap)
19. [Contributing](#19-contributing)
20. [License](#20-license)

---

## 1. What is Sentinel V2?

Sentinel V2 is a **real-time pre-delinquency detection system** built for Indian retail banking. It continuously monitors customer transaction behaviour, builds a personalised statistical baseline for each customer, and assigns a **Pulse Score** [0.0 – 1.0] to every incoming transaction.

The Pulse Score answers one question:

> *"Based on how this customer normally behaves, does today's transaction signal that they are heading toward a missed payment?"*

### Why "pre-delinquency"?

Traditional credit risk models score customers monthly or quarterly, **after** stress has already manifested. Sentinel operates at the **transaction level** — it detects the behavioural shift (salary arriving late, EMI bouncing, borrowing from digital lenders) **before** the first DPD appears.

### What makes it different from V1?

| Problem in V1 | How V2 fixes it |
|---|---|
| `transaction_type` labels hardcoded — model saw pre-classified data | V2 stores raw facts only. Classifier infers purpose from VPA patterns at runtime |
| `is_stress_profile` boolean leaked into training labels | V2 labels come purely from `days_past_due` and `failed_auto_debit_count` |
| Single customer-level score, no per-transaction scoring | Every transaction gets its own severity score + bounded delta |
| Population-level thresholds — no per-customer baseline | Every customer gets a personal μ/σ baseline built from their own 90-day history |
| Pulse score = PD × 100 (no damping) | Bounded incremental accumulator with heinous/normal/recovery tiers |
| `salary_records` table queried but never existed | Salary detection via NEFT sender VPA pattern matching |
| 20+ DB roundtrips per customer in feature engine | Single bulk CTE query — one roundtrip per customer |

---

## 2. Key Design Principles

### Raw Facts Only
Transaction events carry only observable facts: `sender_id`, `receiver_id`, `platform`, `amount`, `payment_status`, `balance_before`, `balance_after`. **No `transaction_type` label is ever stored.** The enrichment layer infers purpose from VPA patterns at scoring time.

### Personal Baseline as Ground Zero
Each customer's 90-day history is used to compute a personal μ/σ/percentile baseline. The model never sees absolute feature values — it sees **z-scores** (how many standard deviations from that customer's own normal).

### No Hardcoded Thresholds
Every parameter that influences scoring — noise floor, damping coefficients, delta caps, risk tier boundaries — lives in `.env` / `config/settings.py`. Nothing is hardcoded in business logic.

### Bounded Score Accumulation
A single transaction can raise the Pulse Score by at most 0.15 (normal) or 0.30 (heinous event, severity ≥ 0.90). This prevents a single data anomaly from producing a false CRITICAL flag.

### Normal Life is Neutral
Paying for groceries, Zomato, Netflix, petrol, or splitting a restaurant bill with a friend produces **zero delta**. The score only moves when the model detects a pattern that deviates significantly from the customer's own history.

---

## 3. Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OFFLINE PIPELINE                              │
│                                                                      │
│  Synthetic Data Generator                                            │
│  (1500 customers, 120 days, Indian banking context)                  │
│         │                                                            │
│         ▼                                                            │
│  PostgreSQL ──► Baseline Builder ──► Redis Cache                    │
│  (raw txns,      (days 1–90 only,    (baseline:{cid})               │
│   no labels)      μ/σ/p25/p75/p95)                                  │
│         │                                                            │
│         ▼                                                            │
│  LightGBM Training                                                   │
│  (labels from DPD + failed NACH, days 91–120 only)                  │
│  ──► ml_models/saved_models/lgbm_pulse_scorer.txt                   │
│  ──► config/feature_weights.json                                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     REAL-TIME PIPELINE                               │
│                                                                      │
│  Raw Transaction                                                     │
│  (Kafka: sentinel.raw.transactions)                                  │
│         │                                                            │
│         ├─ 1. TransactionClassifier                                  │
│         │      UPI VPA → SALARY / EMI / LENDING_APP / GROCERY …    │
│         │                                                            │
│         ├─ 2. FeatureEngine (42 features, as_of = txn_timestamp)   │
│         │      Single bulk SQL query                                 │
│         │                                                            │
│         ├─ 3. DeltaFeatures (48 dimensions)                         │
│         │      42 z-scores vs baseline + 6 txn-specific features    │
│         │                                                            │
│         ├─ 4. LightGBM inference → severity [0.0, 1.0]             │
│         │                                                            │
│         ├─ 5. PulseAccumulator                                      │
│         │      direction + bounded delta → new overall score        │
│         │                                                            │
│         ├─ 6. PostgreSQL: transaction_pulse_events                  │
│         └─ 7. Kafka: sentinel.transaction.pulse                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram

```
Producer / API
     │
     │  TransactionEvent (raw facts only)
     ▼
Kafka: sentinel.raw.transactions
     │
     ▼
SentinelConsumer
     │
     ▼
PulseEngine.process()
  │
  ├── get_baseline(customer_id)       → Redis → PostgreSQL
  ├── classify_transaction(txn)       → VPA pattern matching
  ├── compute_all_features(as_of=ts)  → 1 SQL query, 42 features
  ├── compute_delta_features()        → 48 z-scores
  ├── model.predict_single(x)         → severity [0.0, 1.0]
  ├── compute_direction + delta       → bounded update
  ├── upsert pulse_scores             → PostgreSQL
  ├── cache pulse:{customer_id}       → Redis TTL 24h
  └── insert transaction_pulse_event → PostgreSQL audit trail
     │
     ▼
Kafka: sentinel.transaction.pulse
     │
     ▼
Dashboard / Monitoring
```

### Time Boundary (Critical)

```
│← Day 1 ──────────────── Day 90 ─│─ Day 91 ──────── Day 120 →│
│                                  │                            │
│      BASELINE WINDOW             │    REAL-TIME WINDOW        │
│      (build μ/σ/percentiles)     │    (training + scoring)    │
│                                  │                            │
baseline_start = now − 120d    baseline_end = now − 30d        now
```

The baseline is computed from days 1–90 **only**. Training examples come from days 91–120. These two windows **never overlap**.

---

## 4. Tech Stack

| Layer | Technology |
|---|---|
| **ML Model** | LightGBM 4.3 (binary classifier), SHAP explainability |
| **Feature Engine** | Python + psycopg2, single bulk CTE per customer |
| **Streaming** | Apache Kafka 3.7 (KRaft mode — no Zookeeper) |
| **API** | FastAPI 0.111, Pydantic V2, Uvicorn |
| **Database** | PostgreSQL 15 (partitioned transactions table) |
| **Cache** | Redis 7 (baselines + pulse scores, TTL-based) |
| **Dashboard** | Next.js 14, TypeScript, TailwindCSS, Recharts |
| **Data Generation** | Faker (en_IN locale), custom Indian name pools |
| **Class Balance** | SMOTE + Tomek Links (imbalanced-learn) |
| **Monitoring** | PSI (Population Stability Index) + AIR (Adverse Impact Ratio) |
| **Containerisation** | Docker Compose (PostgreSQL + Redis + Kafka) |

---

## 5. Project Structure

```
sentinel-v2/
│
├── config/
│   ├── settings.py               # All config via .env (Pydantic Settings)
│   ├── feature_weights.json      # SHAP feature importance (written by training)
│   └── intervention_policy.json  # Tier rules, cooldowns, channels (Layer 8)
│
├── database/
│   ├── init.sql                  # Full schema: customers, loans, transactions,
│   │                             #   customer_baselines, transaction_pulse_events,
│   │                             #   pulse_scores, model_monitoring
│   └── seed.py                   # Seeds PostgreSQL with synthetic Indian banking data
│
├── schemas/
│   └── transaction_event.py      # Pydantic: raw-facts-only transaction schema
│
├── data_generator/
│   ├── indian_names.py           # Indian name pools, UPI VPA, PAN, IFSC generators
│   ├── customer_generator.py     # Customer + loan + credit card profiles
│   ├── raw_transaction_generator.py  # 120-day raw transaction history (no labels)
│   └── realtime_injector.py      # Kafka injection: random/stress/recovery modes
│                                 #   60+ Indian merchant VPAs (Zomato, BigBasket,
│                                 #   slice@upi, failed NACH, salary credits…)
│
├── enrichment/
│   ├── transaction_category.py   # Pydantic schema for classifier output
│   └── transaction_classifier.py # VPA pattern → SALARY/EMI/LENDING_APP/GROCERY…
│                                 #   Ephemeral — never written to transactions table
│
├── baseline/
│   ├── baseline_schema.py        # CustomerBaseline Pydantic model + z_score()
│   └── baseline_builder.py       # Builds μ/σ/p25/p75/p95 from days 1–90
│                                 #   Writes to PostgreSQL + Redis
│
├── feature_engine/
│   ├── features.py               # 42 behavioural features (single bulk SQL)
│   └── delta_features.py         # 48-dim input vector (42 z-scores + 6 txn-specific)
│
├── ml_models/
│   ├── lightgbm_model.py         # LightGBM wrapper: train / predict / SHAP / save / load
│   ├── training_pipeline.py      # Clean training: DPD+NACH labels, SMOTE, temporal split
│   └── saved_models/
│       ├── lgbm_pulse_scorer.txt # Trained model (generated by --step train)
│       └── lgbm_meta.json        # Model version + feature names
│
├── realtime/
│   ├── pulse_accumulator.py      # Bounded delta logic, all params from config
│   ├── pulse_engine.py           # 9-step real-time pipeline per transaction
│   └── kafka_consumer.py         # Consumes sentinel.raw.transactions
│
├── scoring_service/
│   └── app.py                    # FastAPI: 13 endpoints including /ingest/transaction,
│                                 #   /customer/{id}/pulse, /portfolio/metrics, /health
│
├── monitoring/
│   └── psi_air_monitor.py        # PSI drift (42 features + score + severity)
│                                 #   AIR fairness (geo tier + segment)
│
├── scripts/
│   ├── build_baselines.py        # Batch: build baselines for all 1500 customers
│   ├── train_model.py            # Runs full training pipeline
│   └── init_kafka_topics.py      # Creates all 6 Kafka topics
│
├── dashboards/                   # Next.js 14 dashboard
│   ├── app/
│   │   ├── login/page.tsx        # Glassmorphism login
│   │   └── dashboard/
│   │       ├── page.tsx          # Portfolio: KPIs, pie chart, customer table
│   │       └── [customerId]/page.tsx  # Pulse gauge, timeline, SHAP, txn history
│   └── lib/
│       ├── api.ts                # Axios client, all API methods
│       ├── authStore.ts          # Zustand auth state
│       └── providers.tsx         # React Query provider
│
├── tests/
│   ├── test_normal_vs_stress_transactions.py  # 44 tests: normal txns don't move score
│   └── test_integration_layer6.py             # 37 tests: PSI math, AIR, pipeline steps
│
├── docker-compose.yml            # PostgreSQL 15 + Redis 7 + Kafka 3.7 (KRaft)
├── requirements.txt              # Python dependencies
├── run_pipeline.py               # Master orchestrator (9 steps)
└── .env.example                  # All environment variables documented
```

---

## 6. Prerequisites

### System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.11 | 3.11+ |
| Node.js | 18.x | 20.x |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB free | 10 GB free |
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 | Any |

### Required Tools

```bash
# Docker Desktop (includes Docker Compose)
# https://www.docker.com/products/docker-desktop/

# Python 3.11+
python --version   # must be 3.11+

# Node.js 18+
node --version     # must be 18+
npm --version
```

---

## 7. Quick Start

### Step 1 — Clone and configure

```bash
git clone https://github.com/yourorg/sentinel-v2.git
cd sentinel-v2

# Copy environment template
cp .env.example .env
# Edit .env if you want to change ports or credentials (defaults work out of the box)
```

### Step 2 — Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### Step 3 — Start infrastructure

```bash
docker compose up -d
# Wait ~30 seconds for all services to initialise

docker compose ps
# All 3 services should show (healthy)
```

Expected output:
```
NAME                STATUS          PORTS
sentinel-postgres   Up (healthy)    0.0.0.0:5432->5432/tcp
sentinel-redis      Up (healthy)    0.0.0.0:6379->6379/tcp
sentinel-kafka      Up (healthy)    0.0.0.0:9092->9092/tcp
```

### Step 4 — Run the full offline pipeline

```bash
# Seeds DB → builds baselines → trains model → scores all customers → monitors
python run_pipeline.py --step all
```

This takes **10–20 minutes** for 1500 customers. You can speed it up with:
```bash
python run_pipeline.py --step all --customers 200
```

### Step 5 — Start the API

```bash
# Terminal 1
python run_pipeline.py --step start-api
# API running at http://localhost:8001
# Swagger UI at http://localhost:8001/docs
```

### Step 6 — Start the dashboard

```bash
# Terminal 2
cd dashboards
npm install
npm run dev
# Dashboard at http://localhost:3000
```

Login: `admin@sentinel.bank` / `sentinel_admin`

### Step 7 — Inject live transactions (optional)

```bash
# Terminal 3

# Normal everyday transactions (should NOT change pulse score)
python data_generator/realtime_injector.py --mode random --total 50 --tps 2

# Stress transactions (lending apps + failed EMIs → score climbs)
python data_generator/realtime_injector.py --mode stress --total 20 --tps 1

# Recovery transactions (salary credit + on-time EMI → score drops)
python data_generator/realtime_injector.py --mode recovery --total 10 --tps 1
```

To process injected transactions through the real-time pipeline, start the Kafka consumer:
```bash
# Terminal 4
python run_pipeline.py --step start-consumer
```

---

## 8. Pipeline — Step by Step

The orchestrator supports 9 individual steps:

```bash
python run_pipeline.py --step <step_name> [options]
```

| Step | Command | What it does | Time (1500 customers) |
|---|---|---|---|
| `seed` | `--step seed` | Generates 1500 customers + 120 days raw transactions → PostgreSQL | 3–5 min |
| `baselines` | `--step baselines` | Builds per-customer μ/σ baselines from days 1–90 → PostgreSQL + Redis | 8–15 min |
| `train` | `--step train` | Trains LightGBM on days 91–120 with DPD/NACH labels, SMOTE, saves model | 3–8 min |
| `validate` | `--step validate` | Loads model, prints AUC + top 10 features, sanity-checks inference | < 1 min |
| `score` | `--step score` | Batch-scores all customers, prints tier distribution | 5–10 min |
| `monitor` | `--step monitor` | PSI drift check + AIR fairness audit → saves to model_monitoring table | 1–2 min |
| `start-api` | `--step start-api` | Starts FastAPI scoring service on port 8001 | — |
| `start-consumer` | `--step start-consumer` | Starts Kafka consumer for real-time transaction processing | — |
| `all` | `--step all` | Runs: seed → baselines → train → validate → score → monitor | 20–40 min |

### Options

| Flag | Description |
|---|---|
| `--customers N` | Override `NUM_CUSTOMERS` from `.env` (useful for quick testing) |
| `--truncate` | Truncate all tables before seeding (use with `--step seed`) |
| `--dry-run` | Consumer: score but do not write to DB |

### Example: Quick test with 100 customers

```bash
python run_pipeline.py --step seed --customers 100 --truncate
python run_pipeline.py --step baselines --customers 100
python run_pipeline.py --step train --customers 100
python run_pipeline.py --step validate
```

---

## 9. How the Scoring Works

### Transaction Classification

Every incoming transaction is classified by pattern-matching on raw VPA fields. No labels are ever stored on the transaction row.

| Category | Detection Rule | Stress Signal |
|---|---|---|
| `SALARY_CREDIT` | `platform=NEFT/IMPS` + `sender_id` matches payroll VPA patterns | Relief — score ↓ |
| `EMI_DEBIT` | `platform=NACH` + `receiver_id` contains `@nach` + `status=success` | Relief — score ↓ |
| `FAILED_EMI_DEBIT` | `platform=NACH` + `receiver_id` contains `@nach` + `status=failed` | **Stress — score ↑** |
| `LENDING_APP_DEBIT` | `receiver_id` matches known lending app VPAs (slice@upi, fibe@ybl, etc.) | **Stress — score ↑** |
| `LENDING_APP_CREDIT` | `sender_id` matches lending app VPAs | **Stress — score ↑** |
| `UTILITY_PAYMENT` | `platform=BBPS` | Neutral |
| `GROCERY` | `receiver_id` matches grocery VPAs | Neutral |
| `FOOD_DELIVERY` | `receiver_id` matches Zomato/Swiggy VPAs | Neutral |
| `GENERAL_DEBIT` | All other UPI/POS debits (P2P, dining, shopping) | Neutral |

### Delta Feature Vector (48 dimensions)

```
42 z-score features (current value − baseline_mean) / baseline_std
  │
  ├── Group 1: Balance & Liquidity    (6 features)
  ├── Group 2: Income / Salary        (5 features)
  ├── Group 3: EMI / NACH Payments    (6 features)
  ├── Group 4: ATM / Cash             (4 features)
  ├── Group 5: Lending App Activity   (4 features)
  ├── Group 6: Spending Behaviour     (8 features)
  └── Group 7: Cross-product          (9 features)

6 transaction-specific features
  ├── inferred_category_encoded   (0–14 ordinal)
  ├── amount_vs_baseline_ratio    (txn amount / avg daily spend)
  ├── time_of_day_risk            (0=day, 1=evening, 2=night)
  ├── day_of_month_risk           (proximity to EMI due dates)
  ├── balance_depletion_pct       (fraction of balance consumed)
  └── is_failed                   (1.0 if status=failed/reversed)
```

### Pulse Score Accumulation

```
For each transaction:
  1. severity = model.predict(delta_vector)            → [0.0, 1.0]
  2. direction = classify(category, severity)          → positive / negative / neutral
  3. delta    = compute_delta(severity, direction, current_score)

Damping rules (all configurable):
  • severity < 0.10     → delta = 0  (noise floor)
  • severity ≥ 0.90     → max_delta = 0.30  (heinous event)
  • severity < 0.90     → max_delta = 0.15  (normal event)
  • score > 0.80 AND severity < 0.50  → delta × 0.30  (high-score damping)
  • score < 0.20 AND direction=negative → delta × 1.50  (recovery amplification)

  4. new_score = clip(current_score + delta, 0.0, 1.0)
```

### Risk Tiers

| Tier | Label | Pulse Score Range | Meaning |
|---|---|---|---|
| 1 | **CRITICAL** | ≥ 0.75 | Immediate intervention required |
| 2 | **HIGH** | 0.55 – 0.74 | Strong pre-delinquency signals |
| 3 | **MODERATE** | 0.40 – 0.54 | Multiple stress indicators |
| 4 | **WATCH** | 0.25 – 0.39 | Early warning signals |
| 5 | **STABLE** | 0.00 – 0.24 | No significant stress detected |

---

## 10. Feature Catalog

### Group 1 — Balance & Liquidity (6 features)

| Feature | Description |
|---|---|
| `balance_7d_avg` | Average account balance over past 7 days |
| `balance_wow_change_pct` | Week-over-week balance % change |
| `balance_mom_change_pct` | Month-over-month balance % change |
| `net_cash_flow_7d` | Credits minus debits in past 7 days (₹) |
| `liquidity_buffer_days` | Days of spending the current balance can cover |
| `balance_depletion_rate` | Rate at which balance is declining vs monthly income |

### Group 2 — Income / Salary (5 features)

| Feature | Description |
|---|---|
| `salary_credit_count_90d` | Number of salary credits in 90 days |
| `salary_delay_days` | Days between expected and actual salary credit |
| `salary_amount_deviation_pct` | % deviation of latest salary vs 90-day average |
| `income_irregularity` | Coefficient of variation of salary arrival gaps |
| `partial_salary_flag` | 1 if latest salary < 80% of historical average |

### Group 3 — EMI / NACH Payments (6 features)

| Feature | Description |
|---|---|
| `failed_nach_count_30d` | NACH/ECS failures in 30 days |
| `total_nach_count_30d` | Total NACH attempts in 30 days |
| `nach_failure_rate` | Ratio of failed / total NACH |
| `emi_payment_delay_days` | Average days between EMI due date and payment |
| `consecutive_failed_nach` | Longest streak of consecutive NACH failures |
| `bounce_count_30d` | All failed transactions in 30 days |

### Group 4 — ATM / Cash (4 features)

| Feature | Description |
|---|---|
| `atm_withdrawal_amount_7d` | Total ATM cash withdrawn in 7 days (₹) |
| `atm_withdrawal_count_7d` | Number of ATM withdrawals in 7 days |
| `atm_amount_30d` | Total ATM cash in 30 days (₹) |
| `atm_frequency_trend` | Change in ATM frequency: recent 15d vs prior 15d |

### Group 5 — Lending App Activity (4 features)

| Feature | Description |
|---|---|
| `lending_app_transfer_count_30d` | Payments TO digital lending apps in 30 days |
| `lending_app_transfer_amount_30d` | Total amount paid to lending apps (₹) |
| `lending_disbursement_count_30d` | Loans received FROM digital lending apps |
| `lending_app_dependency_score` | Lending transfer amount / monthly income |

### Group 6 — Spending Behaviour (8 features)

| Feature | Description |
|---|---|
| `discretionary_spend_7d` | Food delivery + e-commerce + OTT in 7 days |
| `grocery_spend_7d` | Grocery spend in 7 days (₹) |
| `discretionary_wow_change_pct` | Week-over-week % change in discretionary spend |
| `food_delivery_spend_7d` | Zomato + Swiggy + food apps in 7 days (₹) |
| `online_spend_7d` | All successful debit transactions in 7 days (₹) |
| `total_debit_30d` | Total outflows in 30 days (₹) |
| `spending_velocity_7d` | Number of transactions per day in 7 days |
| `large_debit_flag` | 1 if any single debit > 2× average daily spend |

### Group 7 — Cross-product & Context (9 features)

| Feature | Description |
|---|---|
| `total_outstanding_debt` | Sum of all active loan principals (₹) |
| `debt_to_income_ratio` | Outstanding debt / annual income |
| `emi_to_income_ratio` | Total monthly EMI / monthly income |
| `credit_utilization_pct` | Average credit card utilisation % |
| `active_product_count` | Number of active loans + credit cards |
| `historical_delinquency_count` | Past delinquency events on record |
| `customer_vintage_months` | Account age in months |
| `geography_risk_tier` | State-level credit risk tier (1=low, 4=high) |
| `inflow_outflow_ratio_30d` | Total credits / total debits in 30 days |

---

## 11. API Reference

Base URL: `http://localhost:8001`  
Interactive docs: `http://localhost:8001/docs`

### Authentication

```http
POST /auth/login
Content-Type: application/json

{
  "username": "admin@sentinel.bank",
  "password": "sentinel_admin"
}
```

### Score a Transaction

```http
POST /ingest/transaction
Content-Type: application/json

{
  "customer_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "account_number": "1234567890123456",
  "sender_id": "rahul.sharma@sbi",
  "sender_name": "Rahul Sharma",
  "receiver_id": "slice@upi",
  "receiver_name": "Slice Fintech Pvt Ltd",
  "amount": 5000.00,
  "platform": "UPI",
  "payment_status": "success",
  "balance_before": 8000.00,
  "balance_after": 3000.00
}
```

Response:
```json
{
  "event_id": "...",
  "customer_id": "...",
  "inferred_category": "LENDING_APP_DEBIT",
  "classifier_confidence": 0.95,
  "txn_severity": 0.7812,
  "severity_direction": "positive",
  "delta_applied": 0.117,
  "pulse_score_before": 0.143,
  "pulse_score_after": 0.260,
  "risk_tier": 4,
  "risk_label": "WATCH",
  "top_features": [
    { "feature": "lending_app_transfer_count_30d", "shap": 0.42, "direction": "stress" },
    { "feature": "balance_depletion_pct",          "shap": 0.31, "direction": "stress" }
  ],
  "scoring_latency_ms": 47
}
```

### Get Customer Pulse Score

```http
GET /customer/{customer_id}/pulse
```

### Get Transaction History

```http
GET /customer/{customer_id}/pulse_history?last_n=50
```

### Get Statistical Baseline

```http
GET /customer/{customer_id}/baseline
```

### Portfolio Metrics

```http
GET /portfolio/metrics
```

Response:
```json
{
  "total_customers": 1500,
  "scored_customers": 1497,
  "avg_pulse_score": 0.1823,
  "critical_count": 23,
  "high_count": 87,
  "moderate_count": 134,
  "watch_count": 298,
  "stable_count": 955,
  "high_severity_24h": 12
}
```

### Customer List (with filters)

```http
GET /customers?risk_label=CRITICAL&search=sharma&limit=50&offset=0
```

### High-Risk Customers

```http
GET /scores/high_risk?min_score=0.55&limit=20
```

### Health Check

```http
GET /health
```

Response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "redis_connected": true,
  "postgres_ok": true,
  "timestamp": "2026-03-22T10:30:00Z"
}
```

### Valid Platforms

`UPI` · `NEFT` · `IMPS` · `RTGS` · `ATM` · `NACH` · `ECS` · `BBPS` · `POS` · `MOBILE` · `BRANCH`

### Valid Payment Statuses

`success` · `failed` · `pending` · `reversed`

---

## 12. Dashboard

### Access

```
URL:      http://localhost:3000
Email:    admin@sentinel.bank
Password: sentinel_admin
```

### Portfolio Overview (`/dashboard`)

- **KPI cards** — Total customers, High risk count, Average pulse score, High-severity alerts in 24h
- **Risk distribution pie chart** — CRITICAL / HIGH / MODERATE / WATCH / STABLE breakdown
- **Customer table** — Sortable by pulse score, filterable by tier, searchable by name or account ID
- **Auto-refresh** — Metrics and table refresh every 30 seconds

### Customer Detail (`/dashboard/{customer_id}`)

- **Pulse Score Gauge** — Circular progress indicator colour-coded by risk tier
- **Baseline metadata** — Window dates, transaction count, confidence level
- **Score Timeline** — Line chart of pulse score across last 60 transaction events with tier reference lines
- **Top SHAP Drivers** — Horizontal bar chart of top 5 features driving the current score
- **Transaction Pulse Events** — Chronological list of events with category, severity badge, delta applied, and before/after scores
- **Auto-refresh** — Score and history refresh every 15 seconds

---

## 13. Configuration

All configuration is loaded from `.env` via Pydantic Settings. No hardcoded values exist in business logic.

### Database

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sentinel
POSTGRES_USER=sentinel_user
POSTGRES_PASSWORD=sentinel_secure_2024
```

### Cache

```env
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Kafka

```env
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

### Synthetic Data

```env
NUM_CUSTOMERS=1500
```

### Pulse Score Accumulator

```env
PULSE_DAMPING_NOISE_FLOOR=0.10     # Severity below this → no delta
PULSE_HIGH_SCORE_THRESHOLD=0.80    # High-score damping kicks in above here
PULSE_HIGH_SCORE_DAMPING=0.30      # Multiply raw_delta by this when near-critical
PULSE_RECOVERY_AMPLIFICATION=1.50  # Amplify relief for recovering customers
PULSE_LOW_SCORE_THRESHOLD=0.20     # Recovery amplification kicks in below here
PULSE_MAX_SINGLE_DELTA=0.15        # Maximum delta per normal transaction
PULSE_MAX_HEINOUS_DELTA=0.30       # Maximum delta for severity ≥ 0.90
PULSE_HEINOUS_THRESHOLD=0.90       # Above this → heinous classification
```

### Baseline Builder

```env
BASELINE_WINDOW_DAYS=90            # Days of history used for baseline stats
BASELINE_HISTORY_TOTAL_DAYS=120    # Total history generated per customer
BASELINE_SNAPSHOT_INTERVAL_DAYS=7  # How often to take feature snapshots
BASELINE_MIN_TRANSACTIONS=10       # Minimum txns to build a valid baseline
BASELINE_REDIS_TTL_HOURS=168       # Baseline cache TTL (7 days)
```

### Risk Tier Thresholds

```env
RISK_TIER_CRITICAL=0.75
RISK_TIER_HIGH=0.55
RISK_TIER_MODERATE=0.40
RISK_TIER_WATCH=0.25
```

### Model

```env
PULSE_SCORER_FEATURES=48
PULSE_SCORER_MIN_CONFIDENCE=0.55
MODEL_RETRAIN_PSI_THRESHOLD=0.25
```

---

## 14. Real-Time Injection & Testing

### Transaction Injector Modes

```bash
# Random everyday transactions — should NOT move pulse score
python data_generator/realtime_injector.py --mode random --total 100 --tps 2

# Stress transactions — lending app transfers + failed NACH EMIs
python data_generator/realtime_injector.py --mode stress --total 20 --tps 1

# Recovery transactions — salary credit + on-time EMI
python data_generator/realtime_injector.py --mode recovery --total 10 --tps 1
```

### Custom Transaction (for specific scenario testing)

```python
from data_generator.realtime_injector import RealTimeInjector

# Override specific fields
inj = RealTimeInjector()
inj.inject_transaction(
    customer=my_customer_dict,
    override={
        "receiver_id":    "slice@upi",
        "receiver_name":  "Slice Fintech Pvt Ltd",
        "amount":         8000,
        "platform":       "UPI",
        "payment_status": "success",
        "balance_before": 5000,
        "balance_after":  0,
    }
)
```

### Merchant Pool Coverage

The random injector covers 60+ Indian merchant VPAs across:

| Category | Examples |
|---|---|
| P2P transfers | `friend_rahul@ybl`, `priya.menon@hdfcbank`, `amit.kumar99@okaxis` |
| Food delivery | `zomato@axl`, `swiggy@icicibank`, `eatsure@ybl` |
| Grocery | `bigbasket@okaxis`, `blinkit@icicibank`, `dmartrewards@upi` |
| Medical | `apollopharmacy@upi`, `medplus@okaxis`, `1mghealth@ybl` |
| Travel | `oladriver@upi`, `uber@razorpay`, `irctc@upi`, `delhimetro@bbps` |
| Entertainment | `bookmyshow@hdfcbank`, `netflix@ybl`, `hotstar@icicibank` |
| Fuel | `hpcl@upi`, `iocl@upi`, `bpcl@okaxis` |
| Utilities | `bescom@bbps`, `airtel@bbps`, `jio@bbps` |
| E-commerce | `amazon@axisbank`, `flipkart@axisbank`, `myntra@upi` |

---

## 15. Monitoring

### PSI (Population Stability Index)

Measures how much feature distributions have shifted between the baseline window and recent production.

```bash
python run_pipeline.py --step monitor
```

| PSI Value | Status | Action |
|---|---|---|
| < 0.10 | **STABLE** | No action needed |
| 0.10 – 0.25 | **WATCH** | Investigate the drifting features |
| > 0.25 | **RETRAIN** | Trigger model retraining |

Monitored distributions:
- **42 behavioural features** — compared via stored baseline means vs recent delta features from `transaction_pulse_events`
- **Pulse score distribution** — early scores vs recent scores
- **Transaction severity distribution** — flag if > 40% of recent transactions score ≥ 0.80

### AIR (Adverse Impact Ratio)

Measures fairness across demographic groups.

```
AIR = high_risk_rate(group) / high_risk_rate(reference_group)
```

| AIR | Status | Meaning |
|---|---|---|
| 0.80 – 1.25 | **STABLE** | Within 80/125 rule — acceptable |
| < 0.80 or > 1.25 | **ALERT** | Group is flagged disproportionately |

Groups monitored:
- **Geography risk tier** (1–4) — reference: Tier 1 (lowest risk states)
- **Customer segment** (RETAIL / HNI / SME / MICROFINANCE) — reference: RETAIL

All monitoring results are saved to the `model_monitoring` table for audit.

---

## 16. Indian Banking Context

Sentinel V2 is built specifically for Indian retail banking. Key domain details:

### Account Formats

| Field | Format | Example |
|---|---|---|
| Account number | 11–16 digit numeric | `1452367890123456` |
| UPI VPA | `name@bankcode` | `rahul.sharma@sbi` |
| Loan account | `BANK/TYPE/YEAR/SEQ` | `HDFC/PL/2024/00123456` |
| IFSC code | `BBBB0NNNNNN` | `HDFC0001234` |
| NACH VPA | `BANK_NACH_EMI_LOANREF@nach` | `HDFC_NACH_EMI_HDFC_PL_2024_00123456@nach` |
| PAN number | `AAAAA9999A` | `ABCPS1234X` |

### Payment Platforms

| Platform | Use Case |
|---|---|
| UPI | Peer-to-peer, merchant payments, lending apps |
| NEFT / IMPS | Salary credits, large transfers |
| NACH / ECS | EMI auto-debits |
| BBPS | Utility bill payments (electricity, telecom, gas) |
| ATM | Cash withdrawals |
| POS | Physical merchant terminals |

### Known Digital Lending App VPAs

`slice@upi` · `lazypay@upi` · `simpl@upi` · `fibe@ybl` · `cashe@upi` · `kreditbee@upi` · `mpokket@upi` · `navi@hdfcbank` · `moneyview@ybl` · `zestmoney@okaxis` · `postpe@icicibank` · `kissht@upi` and more

### Geography Risk Tiers

| Tier | States |
|---|---|
| 1 (Lowest risk) | Maharashtra, Karnataka, Tamil Nadu, Gujarat, Delhi, Telangana |
| 2 | Kerala, Haryana, Punjab, West Bengal, Andhra Pradesh, Rajasthan |
| 3 | Madhya Pradesh, Uttar Pradesh, Odisha, Chhattisgarh, Jharkhand |
| 4 (Highest risk) | Bihar, Assam, Manipur, Meghalaya, Tripura, Nagaland, Mizoram |

### Income Distributions (Monthly, INR)

| Segment + Employment | Mean | Range |
|---|---|---|
| RETAIL / SALARIED | ₹45,000 | ₹15,000 – ₹2,00,000 |
| HNI / SALARIED | ₹2,50,000 | ₹1,50,000 – ₹10,00,000 |
| SME / BUSINESS_OWNER | ₹1,20,000 | ₹30,000 – ₹7,00,000 |
| MICROFINANCE / SELF_EMPLOYED | ₹15,000 | ₹5,000 – ₹35,000 |

---

## 17. Testing

### Run all tests

```bash
# Normal vs stress transaction scoring (44 tests)
python tests/test_normal_vs_stress_transactions.py

# Integration test — PSI math, AIR formula, pipeline steps, API endpoints (37 tests)
python tests/test_integration_layer6.py
```

### What the tests verify

**`test_normal_vs_stress_transactions.py`** (44 tests):
- Rs50 P2P transfer → `GENERAL_DEBIT` → `delta = 0.0`
- Zomato food order → `FOOD_DELIVERY` → `delta = 0.0`
- BigBasket grocery → `GROCERY` → `delta = 0.0`
- BESCOM electricity → `UTILITY_PAYMENT` → `delta = 0.0`
- Netflix subscription → `OTT` → `delta = 0.0`
- Score unchanged after 14 normal transactions
- `slice@upi` transfer → `LENDING_APP_DEBIT` → `direction=positive`  → `delta > 0`
- Failed NACH EMI → `FAILED_EMI_DEBIT` → `direction=positive` → `delta > 0`
- Salary credit → `SALARY_CREDIT` → `direction=negative` → `delta < 0`
- 200 random injector transactions → 100% neutral direction

**`test_integration_layer6.py`** (37 tests):
- PSI = 0.024 for identical distribution
- PSI > 0.25 for large drift → RETRAIN
- PSI monotonically increases with drift severity
- AIR = 1.0 for equal rates → STABLE
- AIR = 0.5 for low group rate → ALERT
- All 9 pipeline steps registered
- All 5 API endpoints present

---

## 18. Roadmap

### Layer 8 — Intervention Engine (Planned)
- Jinja2 message templates per risk tier (SMS / WhatsApp / Push)
- Cooldown management — no more than 2 messages per week
- No-contact hours (10 PM – 8 AM, Sundays)
- Batch intervention runner
- Dashboard: intervention status on customer detail page

### Future Enhancements
- LSTM temporal encoder for sequential transaction patterns
- Real bureau score integration (CIBIL/Experian API)
- A/B testing framework for intervention message variants
- Multi-tenant support (multiple bank instances)
- Kubernetes deployment manifests
- Prometheus + Grafana metrics dashboard

---

## 19. Contributing

Contributions are welcome. Please follow these guidelines:

### Branch naming

```
feature/short-description
fix/bug-description
docs/what-changed
```

### Before submitting a PR

```bash
# Run both test suites
python tests/test_normal_vs_stress_transactions.py
python tests/test_integration_layer6.py

# Check no is_stress_profile anywhere in pipeline code
grep -r "is_stress_profile" --include="*.py" config/ baseline/ feature_engine/ ml_models/ realtime/ scoring_service/ monitoring/
# Must return zero results

# Check no transaction_type anywhere in pipeline code
grep -r "transaction_type" --include="*.py" config/ baseline/ feature_engine/ ml_models/ realtime/ scoring_service/ monitoring/
# Must return zero results
```

### Coding standards

- All financial parameters must come from `config/settings.py` via `.env` — no hardcoded numbers in business logic
- Transaction events must remain raw facts only — classifier output is always ephemeral
- Baseline window (days 1–90) and training window (days 91–120) must never overlap

---

## 20. License

```
MIT License

Copyright (c) 2026 Sentinel V2 Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

---

<div align="center">

Built with ❤️ for Indian retail banking  
**Sentinel V2** — Detecting financial stress before it becomes delinquency

</div>
