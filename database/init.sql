-- =====================================================================
-- SENTINEL V2 — PostgreSQL Schema
-- Pre-Delinquency Intervention Engine
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =====================================================================
-- 1. CUSTOMERS
-- =====================================================================
CREATE TABLE IF NOT EXISTS customers (
    customer_id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    first_name              VARCHAR(100) NOT NULL,
    last_name               VARCHAR(100) NOT NULL,
    email                   VARCHAR(255),
    phone                   VARCHAR(15) NOT NULL,
    date_of_birth           DATE NOT NULL,
    gender                  VARCHAR(10) CHECK (gender IN ('Male', 'Female', 'Other')),
    pan_number              VARCHAR(10) UNIQUE,
    aadhaar_hash            VARCHAR(64),         -- SHA-256 hash only, never raw

    -- Employment & Income
    employment_type         VARCHAR(30) NOT NULL CHECK (employment_type IN (
                                'SALARIED', 'SELF_EMPLOYED', 'BUSINESS_OWNER', 'RETIRED')),
    employer_id             VARCHAR(50),
    employer_name           VARCHAR(200),
    monthly_income          DECIMAL(15,2) NOT NULL,
    expected_salary_day     INTEGER CHECK (expected_salary_day BETWEEN 1 AND 31),

    -- Geography & Segmentation
    state                   VARCHAR(50) NOT NULL,
    city                    VARCHAR(100) NOT NULL,
    pincode                 VARCHAR(6) NOT NULL,
    geography_risk_tier     INTEGER CHECK (geography_risk_tier BETWEEN 1 AND 4),
    customer_segment        VARCHAR(20) NOT NULL CHECK (customer_segment IN (
                                'RETAIL', 'HNI', 'SME', 'MICROFINANCE')),

    -- Bank Account Details
    account_id              VARCHAR(20) UNIQUE NOT NULL,   -- short reference ID
    account_number          VARCHAR(20) UNIQUE NOT NULL,   -- full 16-digit bank account number
    account_type            VARCHAR(20) CHECK (account_type IN ('SAVINGS', 'CURRENT')),
    account_open_date       DATE NOT NULL,
    customer_vintage_months INTEGER DEFAULT 0,
    upi_vpa                 VARCHAR(100),                  -- e.g. rahul.sharma@sbi
    ifsc_code               VARCHAR(11),                   -- e.g. HDFC0001234
    opening_balance         DECIMAL(15,2) DEFAULT 0,

    -- Credit Profile
    historical_delinquency_count INTEGER DEFAULT 0,
    credit_bureau_score     INTEGER,

    -- Audit
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    -- NOTE: is_stress_profile intentionally omitted — stress is not pre-assigned
);

CREATE INDEX idx_customers_segment ON customers(customer_segment);
CREATE INDEX idx_customers_state ON customers(state);
CREATE INDEX idx_customers_risk_tier ON customers(geography_risk_tier);
CREATE INDEX idx_customers_account ON customers(account_id);
CREATE INDEX idx_customers_account_number ON customers(account_number);


-- =====================================================================
-- 2. LOANS
-- =====================================================================
CREATE TABLE IF NOT EXISTS loans (
    loan_id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_account_number     VARCHAR(30) UNIQUE NOT NULL,   -- e.g. HDFC/PL/2024/00123456
    customer_id             UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    loan_type               VARCHAR(20) NOT NULL CHECK (loan_type IN (
                                'HOME', 'PERSONAL', 'AUTO', 'EDUCATION', 'BUSINESS', 'CREDIT_CARD')),

    -- Loan amounts
    sanctioned_amount       DECIMAL(15,2) NOT NULL,
    outstanding_principal   DECIMAL(15,2) NOT NULL,
    emi_amount              DECIMAL(15,2) NOT NULL,
    emi_due_date            INTEGER CHECK (emi_due_date BETWEEN 1 AND 31),
    interest_rate           DECIMAL(5,2) NOT NULL,
    tenure_months           INTEGER NOT NULL,
    remaining_tenure        INTEGER NOT NULL,
    disbursement_date       DATE NOT NULL,

    -- Delinquency tracking (source of truth for labels)
    days_past_due           INTEGER DEFAULT 0,
    failed_auto_debit_count_30d INTEGER DEFAULT 0,

    -- NACH auto-debit details (used by transaction classifier)
    nach_vpa                VARCHAR(100),   -- e.g. HDFCLOAN_1234567@nach
    nach_rrn_prefix         VARCHAR(20),    -- partial RRN prefix for matching

    status                  VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN (
                                'ACTIVE', 'CLOSED', 'NPA', 'RESTRUCTURED')),
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_loans_customer ON loans(customer_id);
CREATE INDEX idx_loans_type ON loans(loan_type);
CREATE INDEX idx_loans_status ON loans(status);
CREATE INDEX idx_loans_dpd ON loans(days_past_due);


-- =====================================================================
-- 3. CREDIT CARDS
-- =====================================================================
CREATE TABLE IF NOT EXISTS credit_cards (
    card_id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    card_account_number     VARCHAR(30) UNIQUE NOT NULL,   -- e.g. HDFC/CC/2024/00123456
    customer_id             UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    credit_limit            DECIMAL(15,2) NOT NULL,
    current_balance         DECIMAL(15,2) DEFAULT 0,
    credit_utilization_pct  DECIMAL(5,2) DEFAULT 0,
    min_payment_due         DECIMAL(15,2) DEFAULT 0,
    min_payment_made        BOOLEAN DEFAULT FALSE,
    bureau_enquiry_count_90d INTEGER DEFAULT 0,
    payment_due_date        INTEGER CHECK (payment_due_date BETWEEN 1 AND 31),
    status                  VARCHAR(20) DEFAULT 'ACTIVE',
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_credit_cards_customer ON credit_cards(customer_id);


-- =====================================================================
-- 4. TRANSACTIONS
-- Raw-facts only. NO transaction_type column.
-- The classifier infers purpose from sender/receiver patterns.
-- =====================================================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id          UUID DEFAULT uuid_generate_v4(),
    customer_id             UUID NOT NULL REFERENCES customers(customer_id),
    account_number          VARCHAR(20) NOT NULL,

    -- Counterparty (raw observable facts)
    sender_id               VARCHAR(150),   -- UPI VPA, account number, or ATM location code
    sender_name             VARCHAR(200),   -- e.g. "TCS Payroll Services", "HDFC ATM MUM1234"
    receiver_id             VARCHAR(150),   -- UPI VPA, account number, or BBPS biller
    receiver_name           VARCHAR(200),   -- e.g. "Slice Fintech Pvt Ltd", "BESCOM"

    -- Transaction facts
    amount                  DECIMAL(15,2) NOT NULL CHECK (amount > 0),
    platform                VARCHAR(20) NOT NULL CHECK (platform IN (
                                'UPI', 'NEFT', 'IMPS', 'RTGS', 'ATM',
                                'NACH', 'ECS', 'BBPS', 'POS', 'MOBILE', 'BRANCH')),
    payment_status          VARCHAR(20) NOT NULL CHECK (payment_status IN (
                                'success', 'failed', 'pending', 'reversed')),
    reference_number        VARCHAR(60),    -- UTR for NEFT/RTGS, RRN for UPI, unique ID for NACH

    -- Balance tracking (before and after this transaction)
    balance_before          DECIMAL(15,2),
    balance_after           DECIMAL(15,2),

    -- Timing
    txn_timestamp           TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Audit
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    PRIMARY KEY (transaction_id, txn_timestamp)
) PARTITION BY RANGE (txn_timestamp);

-- Create monthly partitions (12 months back + 3 months forward)
DO $$
DECLARE
    start_date  DATE;
    end_date    DATE;
    part_name   TEXT;
BEGIN
    FOR i IN -12..3 LOOP
        start_date := DATE_TRUNC('month', CURRENT_DATE + (i || ' months')::INTERVAL);
        end_date   := DATE_TRUNC('month', CURRENT_DATE + ((i+1) || ' months')::INTERVAL);
        part_name  := 'transactions_' || TO_CHAR(start_date, 'YYYY_MM');
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF transactions
             FOR VALUES FROM (%L) TO (%L)',
            part_name, start_date, end_date
        );
        -- Create partition-level indexes (required — parent indexes don't inherit in PG15)
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (customer_id, txn_timestamp DESC)',
            'idx_' || part_name || '_cust_ts', part_name
        );
    END LOOP;
END $$;

CREATE INDEX idx_transactions_customer_ts ON transactions(customer_id, txn_timestamp DESC);
CREATE INDEX idx_transactions_platform    ON transactions(platform);
CREATE INDEX idx_transactions_status      ON transactions(payment_status);
CREATE INDEX idx_transactions_receiver    ON transactions(receiver_id);


-- =====================================================================
-- 5. CUSTOMER BASELINES
-- Per-customer statistical baseline computed from historical window.
-- Written by baseline/baseline_builder.py, read by realtime/pulse_engine.py
-- =====================================================================
CREATE TABLE IF NOT EXISTS customer_baselines (
    baseline_id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id             UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    computed_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Window metadata
    window_days             INTEGER NOT NULL DEFAULT 90,
    history_start_date      DATE,
    history_end_date        DATE,
    transaction_count       INTEGER DEFAULT 0,
    low_confidence          BOOLEAN DEFAULT FALSE,  -- TRUE if < BASELINE_MIN_TRANSACTIONS

    -- Per-feature statistics (stored as JSONB for schema flexibility)
    feature_means           JSONB NOT NULL DEFAULT '{}',    -- {feature_name: mean}
    feature_stds            JSONB NOT NULL DEFAULT '{}',    -- {feature_name: std}
    feature_p25             JSONB NOT NULL DEFAULT '{}',    -- {feature_name: 25th percentile}
    feature_p75             JSONB NOT NULL DEFAULT '{}',    -- {feature_name: 75th percentile}
    feature_p95             JSONB NOT NULL DEFAULT '{}',    -- {feature_name: 95th percentile}

    is_active               BOOLEAN DEFAULT TRUE,
    model_version           VARCHAR(50)
);

CREATE INDEX idx_baselines_customer ON customer_baselines(customer_id);
-- Only one active baseline per customer at a time
CREATE UNIQUE INDEX idx_baselines_active
    ON customer_baselines(customer_id)
    WHERE is_active = TRUE;


-- =====================================================================
-- 6. TRANSACTION PULSE EVENTS
-- One row per real-time transaction scored by the pulse engine.
-- This is the audit trail of how the overall pulse score evolved.
-- =====================================================================
CREATE TABLE IF NOT EXISTS transaction_pulse_events (
    event_id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id             UUID NOT NULL REFERENCES customers(customer_id),
    transaction_id          UUID NOT NULL,
    event_ts                TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Raw transaction facts (denormalized for audit speed)
    amount                  DECIMAL(15,2) NOT NULL,
    platform                VARCHAR(20),
    receiver_id             VARCHAR(150),
    payment_status          VARCHAR(20),

    -- Enrichment output (inferred by classifier, ephemeral then stored here for audit)
    inferred_category       VARCHAR(50),
    classifier_confidence   DECIMAL(5,4),

    -- Delta features snapshot (what the model saw)
    delta_features          JSONB NOT NULL DEFAULT '{}',

    -- Pulse scoring output
    txn_severity            DECIMAL(6,5) NOT NULL,   -- [0.00000, 1.00000]
    severity_direction      VARCHAR(10) CHECK (severity_direction IN ('positive', 'negative', 'neutral')),
    delta_applied           DECIMAL(6,5) NOT NULL,   -- actual delta applied to overall score
    pulse_score_before      DECIMAL(6,5) NOT NULL,   -- customer overall score before this txn
    pulse_score_after       DECIMAL(6,5) NOT NULL,   -- customer overall score after this txn

    -- Top SHAP contributors for this transaction
    top_features            JSONB DEFAULT '[]',

    model_version           VARCHAR(50),
    scoring_latency_ms      INTEGER
);

CREATE INDEX idx_tpe_customer_ts ON transaction_pulse_events(customer_id, event_ts DESC);
CREATE INDEX idx_tpe_severity    ON transaction_pulse_events(txn_severity DESC);
CREATE INDEX idx_tpe_txn_id      ON transaction_pulse_events(transaction_id);


-- =====================================================================
-- 7. PULSE SCORES  (customer-level overall score, updated incrementally)
-- =====================================================================
CREATE TABLE IF NOT EXISTS pulse_scores (
    score_id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id             UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,

    -- Score (float [0.0, 1.0] — not integer, not percentage)
    pulse_score             DECIMAL(6,5) NOT NULL DEFAULT 0.0
                                CHECK (pulse_score BETWEEN 0.0 AND 1.0),
    risk_tier               INTEGER NOT NULL CHECK (risk_tier BETWEEN 1 AND 5),
    risk_label              VARCHAR(20) NOT NULL CHECK (risk_label IN (
                                'CRITICAL', 'HIGH', 'MODERATE', 'WATCH', 'STABLE')),

    -- Score components (stored for audit)
    top_shap_drivers        JSONB DEFAULT '[]',
    shap_values             JSONB DEFAULT '{}',

    -- Accumulation metadata
    transaction_count_since_baseline INTEGER DEFAULT 0,
    highest_txn_severity    DECIMAL(6,5) DEFAULT 0.0,
    consecutive_stress_txns INTEGER DEFAULT 0,

    model_version           VARCHAR(50),
    scoring_latency_ms      INTEGER,

    score_ts                TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_pulse_scores_customer ON pulse_scores(customer_id);
CREATE INDEX idx_pulse_scores_ts       ON pulse_scores(score_ts DESC);
CREATE INDEX idx_pulse_scores_score    ON pulse_scores(pulse_score DESC);


-- =====================================================================
-- 8. MODEL MONITORING
-- PSI and AIR monitoring results
-- =====================================================================
CREATE TABLE IF NOT EXISTS model_monitoring (
    monitor_id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    monitor_type            VARCHAR(20) CHECK (monitor_type IN ('PSI', 'AIR', 'SEVERITY_DIST')),
    feature_name            VARCHAR(100),
    metric_value            DECIMAL(10,6),
    status                  VARCHAR(20) CHECK (status IN ('STABLE', 'WATCH', 'RETRAIN', 'ALERT')),
    details                 JSONB DEFAULT '{}',
    monitored_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_monitoring_type ON model_monitoring(monitor_type);
CREATE INDEX idx_monitoring_ts   ON model_monitoring(monitored_at DESC);


-- =====================================================================
-- 9. INTERVENTIONS
-- Outbound communications sent to high-risk customers
-- =====================================================================
CREATE TABLE IF NOT EXISTS interventions (
    intervention_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id             UUID NOT NULL REFERENCES customers(customer_id),
    risk_tier               VARCHAR(20) NOT NULL,
    sent_at                 TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status                  VARCHAR(20) DEFAULT 'SENT' CHECK (status IN ('SENT', 'ACKNOWLEDGED')),
    acknowledged_at         TIMESTAMP WITH TIME ZONE,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_interventions_customer ON interventions(customer_id);



-- =====================================================================
-- 10. GRIEVANCES
-- Customer grievances raised after receiving a risk alert
-- =====================================================================
CREATE TABLE IF NOT EXISTS grievances (
    grievance_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intervention_id     UUID NOT NULL REFERENCES interventions(intervention_id),
    customer_id         UUID NOT NULL REFERENCES customers(customer_id),
    customer_name       VARCHAR(255) NOT NULL,
    message             TEXT NOT NULL,
    status              VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'REVIEWED', 'RESOLVED', 'CLOSED')),
    submitted_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_at         TIMESTAMP WITH TIME ZONE,
    resolved_at         TIMESTAMP WITH TIME ZONE,
    officer_notes       TEXT
);

CREATE INDEX idx_grievances_customer       ON grievances(customer_id);
CREATE INDEX idx_grievances_intervention   ON grievances(intervention_id);
CREATE INDEX idx_grievances_status         ON grievances(status);
CREATE INDEX idx_grievances_submitted_at   ON grievances(submitted_at DESC);
