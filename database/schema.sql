-- =====================================================================
-- SENTINEL V2 — Complete Database Schema
-- Pre-Delinquency Intervention Engine  |  Barclays Bank India
-- =====================================================================
--
-- Single authoritative schema file.  Merged from:
--   1. init.sql                  — core tables 1–11
--   2. grievances_migration.sql  — deduplicated into section 10 below
--   3. report_audit_tables.sql   — audit log, form responses, trigger, view
--   4. gig_worker_migration.sql  — gig worker assessment + weekly income
--
-- Safe to run on a blank database OR re-run on an existing one.
-- Every DDL statement uses IF NOT EXISTS / CREATE OR REPLACE so the
-- script is fully idempotent.
--
-- Execution order (dependency-safe):
--   Extensions
--    1.  customers
--    2.  loans
--    3.  credit_cards
--    4.  transactions            (range-partitioned by month)
--    5.  customer_baselines
--    6.  transaction_pulse_events
--    7.  pulse_scores
--    8.  model_monitoring
--    9.  interventions
--   10.  grievances
--   11.  intervention_emails
--   12.  report_audit_log        + immutability trigger + archival view
--   13.  intervention_form_responses
--   14.  gig_worker_stress_assessments
--   15.  gig_worker_weekly_income
--
-- Apply:
--   psql -U sentinel_user -d sentinel -f database/schema.sql
-- =====================================================================

BEGIN;

-- =====================================================================
-- EXTENSIONS
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
    phone                   VARCHAR(15)  NOT NULL,
    date_of_birth           DATE         NOT NULL,
    gender                  VARCHAR(10)  CHECK (gender IN ('Male', 'Female', 'Other')),
    pan_number              VARCHAR(10)  UNIQUE,
    aadhaar_hash            VARCHAR(64),                 -- SHA-256 hash only, never raw Aadhaar

    -- Employment & Income
    employment_type         VARCHAR(30)  NOT NULL CHECK (employment_type IN (
                                'SALARIED', 'SELF_EMPLOYED', 'BUSINESS_OWNER',
                                'RETIRED',  'GIG_WORKER')),
    employer_id             VARCHAR(50),
    employer_name           VARCHAR(200),
    monthly_income          DECIMAL(15,2) NOT NULL,
    expected_salary_day     INTEGER       CHECK (expected_salary_day BETWEEN 1 AND 31),

    -- Geography & Segmentation
    state                   VARCHAR(50)  NOT NULL,
    city                    VARCHAR(100) NOT NULL,
    pincode                 VARCHAR(6)   NOT NULL,
    geography_risk_tier     INTEGER      CHECK (geography_risk_tier BETWEEN 1 AND 4),
    customer_segment        VARCHAR(20)  NOT NULL CHECK (customer_segment IN (
                                'RETAIL', 'HNI', 'SME', 'MICROFINANCE')),

    -- Bank Account Details
    account_id              VARCHAR(20)  UNIQUE NOT NULL,   -- short reference ID e.g. ACC0000001
    account_number          VARCHAR(20)  UNIQUE NOT NULL,   -- full 16-digit bank account number
    account_type            VARCHAR(20)  CHECK (account_type IN ('SAVINGS', 'CURRENT')),
    account_open_date       DATE         NOT NULL,
    customer_vintage_months INTEGER      DEFAULT 0,
    upi_vpa                 VARCHAR(100),                   -- e.g. rahul.sharma@sbi
    ifsc_code               VARCHAR(11),                    -- e.g. HDFC0001234
    opening_balance         DECIMAL(15,2) DEFAULT 0,

    -- Credit Profile
    historical_delinquency_count INTEGER DEFAULT 0,
    credit_bureau_score          INTEGER,

    -- Audit
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    -- NOTE: is_stress_profile intentionally omitted — stress is not pre-assigned at creation
);

CREATE INDEX IF NOT EXISTS idx_customers_segment        ON customers(customer_segment);
CREATE INDEX IF NOT EXISTS idx_customers_state          ON customers(state);
CREATE INDEX IF NOT EXISTS idx_customers_risk_tier      ON customers(geography_risk_tier);
CREATE INDEX IF NOT EXISTS idx_customers_account        ON customers(account_id);
CREATE INDEX IF NOT EXISTS idx_customers_account_number ON customers(account_number);
CREATE INDEX IF NOT EXISTS idx_customers_employment     ON customers(employment_type);


-- =====================================================================
-- 2. LOANS
-- =====================================================================
CREATE TABLE IF NOT EXISTS loans (
    loan_id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_account_number     VARCHAR(30)  UNIQUE NOT NULL,  -- e.g. HDFC/PL/2024/00123456
    customer_id             UUID         NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    loan_type               VARCHAR(20)  NOT NULL CHECK (loan_type IN (
                                'HOME', 'PERSONAL', 'AUTO', 'EDUCATION', 'BUSINESS', 'CREDIT_CARD')),

    -- Loan amounts
    sanctioned_amount       DECIMAL(15,2) NOT NULL,
    outstanding_principal   DECIMAL(15,2) NOT NULL,
    emi_amount              DECIMAL(15,2) NOT NULL,
    emi_due_date            INTEGER       CHECK (emi_due_date BETWEEN 1 AND 31),
    interest_rate           DECIMAL(5,2)  NOT NULL,
    tenure_months           INTEGER       NOT NULL,
    remaining_tenure        INTEGER       NOT NULL,
    disbursement_date       DATE          NOT NULL,

    -- Delinquency tracking (source of truth for labels)
    days_past_due               INTEGER DEFAULT 0,
    failed_auto_debit_count_30d INTEGER DEFAULT 0,

    -- NACH auto-debit details (used by transaction classifier)
    nach_vpa                VARCHAR(100),   -- e.g. HDFCLOAN_1234567@nach
    nach_rrn_prefix         VARCHAR(20),    -- partial RRN prefix for matching

    status                  VARCHAR(20)  DEFAULT 'ACTIVE' CHECK (status IN (
                                'ACTIVE', 'CLOSED', 'NPA', 'RESTRUCTURED')),
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loans_customer ON loans(customer_id);
CREATE INDEX IF NOT EXISTS idx_loans_type     ON loans(loan_type);
CREATE INDEX IF NOT EXISTS idx_loans_status   ON loans(status);
CREATE INDEX IF NOT EXISTS idx_loans_dpd      ON loans(days_past_due);


-- =====================================================================
-- 3. CREDIT CARDS
-- =====================================================================
CREATE TABLE IF NOT EXISTS credit_cards (
    card_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    card_account_number      VARCHAR(30)   UNIQUE NOT NULL,  -- e.g. HDFC/CC/2024/00123456
    customer_id              UUID          NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    credit_limit             DECIMAL(15,2) NOT NULL,
    current_balance          DECIMAL(15,2) DEFAULT 0,
    credit_utilization_pct   DECIMAL(5,2)  DEFAULT 0,
    min_payment_due          DECIMAL(15,2) DEFAULT 0,
    min_payment_made         BOOLEAN       DEFAULT FALSE,
    bureau_enquiry_count_90d INTEGER       DEFAULT 0,
    payment_due_date         INTEGER       CHECK (payment_due_date BETWEEN 1 AND 31),
    status                   VARCHAR(20)   DEFAULT 'ACTIVE',
    created_at               TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at               TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_cards_customer ON credit_cards(customer_id);


-- =====================================================================
-- 4. TRANSACTIONS
-- Raw-facts only.  NO transaction_type column.
-- The classifier infers purpose from sender/receiver VPA patterns.
-- Partitioned by month for query performance on large transaction volumes.
-- =====================================================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  UUID DEFAULT uuid_generate_v4(),
    customer_id     UUID         NOT NULL REFERENCES customers(customer_id),
    account_number  VARCHAR(20)  NOT NULL,

    -- Counterparty (raw observable facts)
    sender_id       VARCHAR(150),  -- UPI VPA, account number, or ATM location code
    sender_name     VARCHAR(200),  -- e.g. "TCS Payroll Services", "HDFC ATM MUM1234"
    receiver_id     VARCHAR(150),  -- UPI VPA, account number, or BBPS biller
    receiver_name   VARCHAR(200),  -- e.g. "Slice Fintech Pvt Ltd", "BESCOM"

    -- Transaction facts
    amount          DECIMAL(15,2) NOT NULL CHECK (amount > 0),
    platform        VARCHAR(20)   NOT NULL CHECK (platform IN (
                        'UPI', 'NEFT', 'IMPS', 'RTGS', 'ATM',
                        'NACH', 'ECS', 'BBPS', 'POS', 'MOBILE', 'BRANCH')),
    payment_status  VARCHAR(20)   NOT NULL CHECK (payment_status IN (
                        'success', 'failed', 'pending', 'reversed')),
    reference_number VARCHAR(60),   -- UTR for NEFT/RTGS, RRN for UPI, unique ID for NACH

    -- Balance tracking (before and after this transaction)
    balance_before  DECIMAL(15,2),
    balance_after   DECIMAL(15,2),

    -- Timing
    txn_timestamp   TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Audit
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    PRIMARY KEY (transaction_id, txn_timestamp)
) PARTITION BY RANGE (txn_timestamp);

-- Create monthly partitions: 12 months back through 3 months forward
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
        -- Partition-level indexes required — parent indexes do not inherit in PG 15+
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (customer_id, txn_timestamp DESC)',
            'idx_' || part_name || '_cust_ts', part_name
        );
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_transactions_customer_ts ON transactions(customer_id, txn_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_platform    ON transactions(platform);
CREATE INDEX IF NOT EXISTS idx_transactions_status      ON transactions(payment_status);
CREATE INDEX IF NOT EXISTS idx_transactions_receiver    ON transactions(receiver_id);


-- =====================================================================
-- 5. CUSTOMER BASELINES
-- Per-customer statistical baseline computed from the 90-day history window.
-- Written by baseline/baseline_builder.py, read by realtime/pulse_engine.py.
-- =====================================================================
CREATE TABLE IF NOT EXISTS customer_baselines (
    baseline_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id         UUID    NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    computed_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Window metadata
    window_days         INTEGER NOT NULL DEFAULT 90,
    history_start_date  DATE,
    history_end_date    DATE,
    transaction_count   INTEGER DEFAULT 0,
    low_confidence      BOOLEAN DEFAULT FALSE,  -- TRUE if < BASELINE_MIN_TRANSACTIONS

    -- Per-feature statistics (JSONB for schema flexibility)
    feature_means       JSONB NOT NULL DEFAULT '{}',   -- {feature_name: mean}
    feature_stds        JSONB NOT NULL DEFAULT '{}',   -- {feature_name: std}
    feature_p25         JSONB NOT NULL DEFAULT '{}',   -- {feature_name: 25th percentile}
    feature_p75         JSONB NOT NULL DEFAULT '{}',   -- {feature_name: 75th percentile}
    feature_p95         JSONB NOT NULL DEFAULT '{}',   -- {feature_name: 95th percentile}

    is_active           BOOLEAN DEFAULT TRUE,
    model_version       VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_baselines_customer ON customer_baselines(customer_id);
-- Only one active baseline per customer at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_baselines_active
    ON customer_baselines(customer_id)
    WHERE is_active = TRUE;


-- =====================================================================
-- 6. TRANSACTION PULSE EVENTS
-- One row per real-time transaction scored by the pulse engine.
-- Audit trail showing exactly how the customer's pulse score evolved.
-- =====================================================================
CREATE TABLE IF NOT EXISTS transaction_pulse_events (
    event_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id         UUID NOT NULL REFERENCES customers(customer_id),
    transaction_id      UUID NOT NULL,
    event_ts            TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Raw transaction facts (denormalised for fast audit queries)
    amount              DECIMAL(15,2) NOT NULL,
    platform            VARCHAR(20),
    receiver_id         VARCHAR(150),
    payment_status      VARCHAR(20),

    -- Enrichment output (inferred by classifier, stored here for audit)
    inferred_category       VARCHAR(50),
    classifier_confidence   DECIMAL(5,4),

    -- Delta features snapshot (what the model saw at scoring time)
    delta_features      JSONB NOT NULL DEFAULT '{}',

    -- Pulse scoring output
    txn_severity        DECIMAL(6,5) NOT NULL,   -- [0.00000, 1.00000]
    severity_direction  VARCHAR(10)  CHECK (severity_direction IN ('positive', 'negative', 'neutral')),
    delta_applied       DECIMAL(6,5) NOT NULL,   -- delta actually applied to overall score
    pulse_score_before  DECIMAL(6,5) NOT NULL,   -- customer score before this transaction
    pulse_score_after   DECIMAL(6,5) NOT NULL,   -- customer score after this transaction

    -- Top SHAP contributors for this transaction
    top_features        JSONB DEFAULT '[]',

    model_version       VARCHAR(50),
    scoring_latency_ms  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tpe_customer_ts ON transaction_pulse_events(customer_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_tpe_severity    ON transaction_pulse_events(txn_severity DESC);
CREATE INDEX IF NOT EXISTS idx_tpe_txn_id      ON transaction_pulse_events(transaction_id);


-- =====================================================================
-- 7. PULSE SCORES
-- Customer-level overall risk score, updated incrementally per transaction.
-- =====================================================================
CREATE TABLE IF NOT EXISTS pulse_scores (
    score_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id         UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,

    -- Score on [0.0, 1.0] — not integer, not percentage
    pulse_score         DECIMAL(6,5) NOT NULL DEFAULT 0.0
                            CHECK (pulse_score BETWEEN 0.0 AND 1.0),
    risk_tier           INTEGER      NOT NULL CHECK (risk_tier BETWEEN 1 AND 5),
    risk_label          VARCHAR(20)  NOT NULL CHECK (risk_label IN (
                            'CRITICAL', 'HIGH', 'MODERATE', 'WATCH', 'STABLE')),

    -- Score components stored for audit
    top_shap_drivers    JSONB DEFAULT '[]',
    shap_values         JSONB DEFAULT '{}',

    -- Accumulation metadata
    transaction_count_since_baseline INTEGER    DEFAULT 0,
    highest_txn_severity             DECIMAL(6,5) DEFAULT 0.0,
    consecutive_stress_txns          INTEGER    DEFAULT 0,

    model_version       VARCHAR(50),
    scoring_latency_ms  INTEGER,

    score_ts            TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated        TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pulse_scores_customer ON pulse_scores(customer_id);
CREATE INDEX IF NOT EXISTS idx_pulse_scores_ts       ON pulse_scores(score_ts DESC);
CREATE INDEX IF NOT EXISTS idx_pulse_scores_score    ON pulse_scores(pulse_score DESC);


-- =====================================================================
-- 8. MODEL MONITORING
-- PSI drift and AIR fairness monitoring results.
-- =====================================================================
CREATE TABLE IF NOT EXISTS model_monitoring (
    monitor_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    monitor_type    VARCHAR(20)   CHECK (monitor_type IN ('PSI', 'AIR', 'SEVERITY_DIST')),
    feature_name    VARCHAR(100),
    metric_value    DECIMAL(10,6),
    status          VARCHAR(20)   CHECK (status IN ('STABLE', 'WATCH', 'RETRAIN', 'ALERT')),
    details         JSONB DEFAULT '{}',
    monitored_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monitoring_type ON model_monitoring(monitor_type);
CREATE INDEX IF NOT EXISTS idx_monitoring_ts   ON model_monitoring(monitored_at DESC);


-- =====================================================================
-- 9. INTERVENTIONS
-- Outbound communications dispatched to high-risk customers.
-- =====================================================================
CREATE TABLE IF NOT EXISTS interventions (
    intervention_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id     UUID        NOT NULL REFERENCES customers(customer_id),
    risk_tier       VARCHAR(20) NOT NULL,
    sent_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status          VARCHAR(20) DEFAULT 'SENT' CHECK (status IN ('SENT', 'ACKNOWLEDGED')),
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interventions_customer ON interventions(customer_id);


-- =====================================================================
-- 10. GRIEVANCES
-- Customer grievances raised after receiving a risk alert.
-- Source: init.sql (section 10) + grievances_migration.sql (identical definition,
-- deduplicated here — the migration file is now superseded by this schema).
-- =====================================================================
CREATE TABLE IF NOT EXISTS grievances (
    grievance_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intervention_id UUID         NOT NULL REFERENCES interventions(intervention_id),
    customer_id     UUID         NOT NULL REFERENCES customers(customer_id),
    customer_name   VARCHAR(255) NOT NULL,
    message         TEXT         NOT NULL,
    status          VARCHAR(20)  DEFAULT 'OPEN' CHECK (status IN (
                        'OPEN', 'REVIEWED', 'RESOLVED', 'CLOSED')),
    submitted_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_at     TIMESTAMP WITH TIME ZONE,
    resolved_at     TIMESTAMP WITH TIME ZONE,
    officer_notes   TEXT
);

CREATE INDEX IF NOT EXISTS idx_grievances_customer      ON grievances(customer_id);
CREATE INDEX IF NOT EXISTS idx_grievances_intervention  ON grievances(intervention_id);
CREATE INDEX IF NOT EXISTS idx_grievances_status        ON grievances(status);
CREATE INDEX IF NOT EXISTS idx_grievances_submitted_at  ON grievances(submitted_at DESC);


-- =====================================================================
-- 11. INTERVENTION EMAILS
-- Tracks every email sent to a HIGH / CRITICAL risk customer.
-- Includes acknowledgement token for the customer self-service portal.
-- =====================================================================
CREATE TABLE IF NOT EXISTS intervention_emails (
    email_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id     UUID         NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    risk_tier       INTEGER      NOT NULL,
    risk_label      VARCHAR(20)  NOT NULL CHECK (risk_label IN ('HIGH', 'CRITICAL')),
    pulse_score     DECIMAL(6,5) NOT NULL,
    sent_to         VARCHAR(255) NOT NULL,
    sent_by_officer VARCHAR(100),
    sent_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_acknowledged BOOLEAN      DEFAULT FALSE,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    ack_token       UUID         DEFAULT uuid_generate_v4(),
    status          VARCHAR(20)  DEFAULT 'SENT' CHECK (status IN (
                        'SENT', 'ACKNOWLEDGED', 'FAILED')),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intervention_emails_customer ON intervention_emails(customer_id);
CREATE INDEX IF NOT EXISTS idx_intervention_emails_sent_at  ON intervention_emails(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_intervention_emails_ack      ON intervention_emails(ack_token);
CREATE INDEX IF NOT EXISTS idx_intervention_emails_status   ON intervention_emails(status);


-- =====================================================================
-- 12. REPORT AUDIT LOG
-- Immutable record of every generated Sentinel V2 pre-delinquency report.
-- Legal basis:
--   Indian Evidence Act 1872, Section 65B
--   PMLA 2002, Section 12 (record-keeping obligation)
--   RBI Master Direction on Fraud Classification (6-year retention)
-- Source: report_audit_tables.sql
-- =====================================================================
CREATE TABLE IF NOT EXISTS report_audit_log (
    report_id           TEXT         NOT NULL,
    reference_number    TEXT         NOT NULL,
    customer_id         UUID         NOT NULL,

    -- Risk snapshot at time of generation
    risk_tier           TEXT         NOT NULL CHECK (risk_tier IN (
                            'CRITICAL', 'HIGH', 'MODERATE', 'WATCH', 'STABLE')),
    pulse_score         NUMERIC(6,4) NOT NULL CHECK (pulse_score >= 0 AND pulse_score <= 1),

    -- Generation metadata
    generated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    llm_model           TEXT         NOT NULL,
    llm_provider        TEXT         NOT NULL DEFAULT 'Anthropic PBC',
    sentinel_version    TEXT         NOT NULL DEFAULT '2.0.0',

    -- Compliance verification
    checklist_passed    BOOLEAN      NOT NULL,
    human_review_req    BOOLEAN      NOT NULL DEFAULT FALSE,

    -- Full report stored as JSONB for audit trail
    report_json         JSONB        NOT NULL,

    -- Immutability enforcement
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_report_audit PRIMARY KEY (report_id)
);

CREATE INDEX IF NOT EXISTS idx_ral_customer_id  ON report_audit_log(customer_id);
CREATE INDEX IF NOT EXISTS idx_ral_generated_at ON report_audit_log(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ral_risk_tier    ON report_audit_log(risk_tier);
CREATE INDEX IF NOT EXISTS idx_ral_reference    ON report_audit_log(reference_number);

COMMENT ON TABLE report_audit_log IS
    'Immutable audit log of every Sentinel V2 Pre-Delinquency Report. '
    'Retention: 6 years per RBI Master Direction on Fraud Classification. '
    'Section 65B certified electronic record.';

-- Immutability enforcement trigger (prevents UPDATE or DELETE on audit rows)
CREATE OR REPLACE FUNCTION enforce_report_immutability()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'Report audit records are immutable. Report ID: %. '
        'Contact compliance@barclays.in to dispute.', OLD.report_id;
END;
$$;

DROP TRIGGER IF EXISTS trg_report_immutable ON report_audit_log;
CREATE TRIGGER trg_report_immutable
    BEFORE UPDATE OR DELETE ON report_audit_log
    FOR EACH ROW EXECUTE FUNCTION enforce_report_immutability();

-- Data retention policy view — reports approaching 6-year RBI deadline
CREATE OR REPLACE VIEW v_reports_due_for_archival AS
    SELECT
        report_id,
        reference_number,
        customer_id,
        generated_at,
        NOW() - generated_at                      AS age,
        'Archive after 6 years per RBI policy'    AS retention_note
    FROM report_audit_log
    WHERE generated_at < NOW() - INTERVAL '5 years 9 months';  -- 3 months before deadline

COMMENT ON VIEW v_reports_due_for_archival IS
    'Reports approaching their 6-year RBI retention deadline. '
    'Review and archive before deletion.';


-- =====================================================================
-- 13. INTERVENTION FORM RESPONSES
-- Customer self-declaration submissions from the digital intervention portal.
-- Required by RBI Consumer Protection Framework RBI/2023-24/18.
-- Retention: 3 years.
-- Source: report_audit_tables.sql
-- =====================================================================
CREATE TABLE IF NOT EXISTS intervention_form_responses (
    form_id                   TEXT         NOT NULL,
    customer_id               UUID         NOT NULL,
    report_reference          TEXT         NOT NULL,

    -- Customer self-declaration
    explanation               TEXT         NOT NULL,
    current_income            NUMERIC(14,2),
    current_outstanding_loans NUMERIC(14,2),
    preferred_contact         TEXT         NOT NULL CHECK (preferred_contact IN (
                                  'email', 'sms', 'whatsapp', 'branch')),
    consent_to_contact        BOOLEAN      NOT NULL,
    additional_notes          TEXT,

    -- Metadata
    submitted_at              TIMESTAMPTZ  NOT NULL,
    received_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip_address                TEXT,        -- for fraud prevention audit
    processed                 BOOLEAN      NOT NULL DEFAULT FALSE,
    assigned_officer          TEXT,

    CONSTRAINT pk_form_response PRIMARY KEY (form_id)
);

CREATE INDEX IF NOT EXISTS idx_ifr_customer_id     ON intervention_form_responses(customer_id);
CREATE INDEX IF NOT EXISTS idx_ifr_report_reference ON intervention_form_responses(report_reference);
CREATE INDEX IF NOT EXISTS idx_ifr_submitted_at    ON intervention_form_responses(submitted_at DESC);

COMMENT ON TABLE intervention_form_responses IS
    'Customer self-declaration form submissions for the Barclays Digital '
    'Intervention Portal. Required by RBI Consumer Protection Framework '
    'RBI/2023-24/18. Retention: 3 years.';


-- =====================================================================
-- 14. GIG WORKER STRESS ASSESSMENTS
-- One row per stress-classification run on a gig worker.
-- Written by gig_worker/gig_realtime_injector.py and run_gig_pipeline.py.
-- Stress criterion: week-over-week platform income drop > 50%.
-- Source: gig_worker_migration.sql
-- =====================================================================
CREATE TABLE IF NOT EXISTS gig_worker_stress_assessments (
    assessment_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Links to the customers table record created for this worker
    customer_id             UUID         NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,

    -- Gig platform details
    platform_vpa            VARCHAR(150) NOT NULL,
    platform_name           VARCHAR(200) NOT NULL,
    platform_category       VARCHAR(50)  NOT NULL,  -- RIDE_SHARE, FOOD_DELIVERY, etc.

    -- Income profile at time of assessment
    baseline_weekly_income  DECIMAL(15,2) NOT NULL,  -- expected normal weekly earnings (INR)
    weeks_simulated         INTEGER       NOT NULL DEFAULT 16,

    -- Weekly income history — last 8 weeks stored as JSONB for audit / re-scoring
    -- Format: [{"week": "W13", "amount": 3200.00, "wow_change": -62.5, "is_stress_week": true}, ...]
    weekly_income_snapshot  JSONB NOT NULL DEFAULT '[]',

    -- WoW change series — last 7 values for quick dashboard rendering
    -- Format: [{"week": "W13", "wow_change_pct": -62.5}, ...]
    wow_changes_snapshot    JSONB NOT NULL DEFAULT '[]',

    -- Stress classification output
    max_wow_drop_pct        DECIMAL(8,4),
        -- Largest single-week income drop in last 4 weeks (positive value: 62.5 = 62.5% drop).
        -- NULL if no drop detected.
    stress_probability      DECIMAL(6,5) DEFAULT 0.0
        CHECK (stress_probability BETWEEN 0.0 AND 1.0),
        -- Raw LightGBM classifier output probability.
    is_stressed             BOOLEAN NOT NULL DEFAULT FALSE,
        -- TRUE if stress_probability >= 0.50.
    stress_label            VARCHAR(20) CHECK (stress_label IN ('STRESSED', 'NOT_STRESSED')),
        -- Human-readable label.
    stress_trigger_week     INTEGER,
        -- Week number that FIRST crossed the WoW > 50% threshold. NULL if never triggered.

    -- Metadata
    model_version           VARCHAR(50) DEFAULT 'gig_stress_v1',
    injected_txn_count      INTEGER DEFAULT 0,  -- rows written to transactions table

    -- Audit
    assessed_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gig_stress_customer
    ON gig_worker_stress_assessments(customer_id);
CREATE INDEX IF NOT EXISTS idx_gig_stress_label
    ON gig_worker_stress_assessments(stress_label);
CREATE INDEX IF NOT EXISTS idx_gig_stress_category
    ON gig_worker_stress_assessments(platform_category);
CREATE INDEX IF NOT EXISTS idx_gig_stress_assessed
    ON gig_worker_stress_assessments(assessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_gig_stress_probability
    ON gig_worker_stress_assessments(stress_probability DESC);


-- =====================================================================
-- 15. GIG WORKER WEEKLY INCOME HISTORY
-- Normalised week-by-week payout rows for every assessed gig worker.
-- One row per week per worker — easier to query/chart than JSONB snapshots.
-- Written by run_gig_pipeline.py alongside each assessment record.
-- Source: gig_worker_migration.sql
-- =====================================================================
CREATE TABLE IF NOT EXISTS gig_worker_weekly_income (
    income_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id         UUID    NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    assessment_id       UUID    REFERENCES gig_worker_stress_assessments(assessment_id) ON DELETE CASCADE,

    week_num            INTEGER      NOT NULL,   -- 1–16
    week_label          VARCHAR(10)  NOT NULL,   -- e.g. "W01", "W16"
    week_start_date     DATE,                    -- calendar date of week start

    payout_amount       DECIMAL(15,2) NOT NULL,  -- platform credit amount (INR)
    platform_vpa        VARCHAR(150),
    platform_name       VARCHAR(200),

    -- WoW change: (this_week - prev_week) / prev_week × 100.
    -- Negative = income drop. NULL for week 1 (no prior reference).
    wow_change_pct      DECIMAL(8,4),

    is_stress_week      BOOLEAN DEFAULT FALSE,
        -- TRUE for stress-window weeks (13–16) of a stressed worker.
    triggered_stress    BOOLEAN DEFAULT FALSE,
        -- TRUE if this specific week's WoW drop crossed the 50% threshold.

    recorded_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gig_weekly_customer
    ON gig_worker_weekly_income(customer_id, week_num);
CREATE INDEX IF NOT EXISTS idx_gig_weekly_assessment
    ON gig_worker_weekly_income(assessment_id);
CREATE INDEX IF NOT EXISTS idx_gig_weekly_stress_trigger
    ON gig_worker_weekly_income(triggered_stress)
    WHERE triggered_stress = TRUE;
CREATE INDEX IF NOT EXISTS idx_gig_weekly_wow
    ON gig_worker_weekly_income(wow_change_pct);


-- =====================================================================
-- END OF SCHEMA
-- =====================================================================
ALTER TABLE customers
ADD COLUMN IF NOT EXISTS admin_email TEXT;

UPDATE customers
SET admin_email = emails[
    floor(random()*array_length(emails, 1))::int + 1
]
FROM (
    SELECT ARRAY[
        'manjunathmurali20@gmail.com',
        'testuser1togethr@gmail.com',
        'tanmay06lko@gmail.com',
        'sanyogeetapradhan@gmail.com',
        'sanyogaming25@gmail.com',
        'sundranidevraj@gmail.com',
        'rajatdalalpaaji@gmail.com',
        'akshaysinghpaaji@gmail.com',
        'sohanj9106@gmail.com',
        'sohan2.9106@gmail.com'
    ] AS emails
) t;    


COMMIT;

