-- =====================================================================
-- SENTINEL V2 — Gig Worker Stress Assessment Table
-- Run once after init.sql to add gig worker support.
-- =====================================================================
-- Safe to run multiple times (IF NOT EXISTS guards on all DDL).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================================
-- GIG WORKER STRESS ASSESSMENTS
-- One row per assessment run on a gig worker.
-- Written by gig_worker/gig_realtime_injector.py.
-- =====================================================================

-- =====================================================================
-- FIX MISSING CASCADES ON EXISTING TABLES
-- Required so that auto-clearing gig workers doesn't fail with FK violations.
-- =====================================================================
ALTER TABLE transactions
    DROP CONSTRAINT IF EXISTS transactions_customer_id_fkey;
ALTER TABLE transactions
    ADD CONSTRAINT transactions_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE;

ALTER TABLE transaction_pulse_events
    DROP CONSTRAINT IF EXISTS transaction_pulse_events_customer_id_fkey;
ALTER TABLE transaction_pulse_events
    ADD CONSTRAINT transaction_pulse_events_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE;

-- =====================================================================
-- Written by gig_worker/gig_realtime_injector.py.
-- =====================================================================
CREATE TABLE IF NOT EXISTS gig_worker_stress_assessments (
    assessment_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Links to the customers table record created for this worker
    customer_id             UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,

    -- Platform the worker earns from
    platform_vpa            VARCHAR(150) NOT NULL,
    platform_name           VARCHAR(200) NOT NULL,
    platform_category       VARCHAR(50)  NOT NULL,    -- e.g. RIDE_SHARE, FOOD_DELIVERY

    -- Income profile at time of assessment
    baseline_weekly_income  DECIMAL(15,2) NOT NULL,   -- expected normal weekly earnings (INR)
    weeks_simulated         INTEGER NOT NULL DEFAULT 16,

    -- Weekly income history (last 8 weeks, stored for audit / re-scoring)
    -- Format: [{"week": N, "amount": X, "wow_change": Y, "is_stress_week": bool}, ...]
    weekly_income_snapshot  JSONB NOT NULL DEFAULT '[]',

    -- WoW change series (last 7 values, for quick dashboard rendering)
    -- Format: [{"week": N, "wow_change": Y}, ...]
    wow_changes_snapshot    JSONB NOT NULL DEFAULT '[]',

    -- ── Stress classification output ──────────────────────────────────
    max_wow_drop_pct        DECIMAL(8,4),
        -- Largest single-week income drop observed in last 4 weeks.
        -- Stored as a POSITIVE percentage: 62.5 means a 62.5% drop.
        -- NULL means no drop detected.

    stress_probability      DECIMAL(6,5) DEFAULT 0.0
        CHECK (stress_probability BETWEEN 0.0 AND 1.0),
        -- Raw probability output from the LightGBM classifier.

    is_stressed             BOOLEAN NOT NULL DEFAULT FALSE,
        -- TRUE if stress_probability >= 0.50 (model threshold).

    stress_label            VARCHAR(20) CHECK (stress_label IN ('STRESSED', 'NOT_STRESSED')),
        -- Human-readable label derived from is_stressed.

    stress_trigger_week     INTEGER,
        -- Week number that FIRST crossed the WoW > 50% threshold.
        -- NULL if the criterion was never triggered.

    -- ── Metadata ──────────────────────────────────────────────────────
    model_version           VARCHAR(50) DEFAULT 'gig_stress_v1',
    injected_txn_count      INTEGER DEFAULT 0,  -- transactions written to transactions table

    -- ── Audit ─────────────────────────────────────────────────────────
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
-- GIG WORKER WEEKLY INCOME HISTORY
-- Normalized week-by-week payout rows for every assessed gig worker.
-- One row per week per worker — easier to query than JSONB snapshots.
-- Written by run_gig_pipeline.py alongside the assessment record.
-- =====================================================================
CREATE TABLE IF NOT EXISTS gig_worker_weekly_income (
    income_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id         UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    assessment_id       UUID REFERENCES gig_worker_stress_assessments(assessment_id) ON DELETE CASCADE,

    week_num            INTEGER NOT NULL,          -- 1–16
    week_label          VARCHAR(10) NOT NULL,      -- e.g. "W01", "W16"
    week_start_date     DATE,                      -- calendar date of this week's start

    payout_amount       DECIMAL(15,2) NOT NULL,    -- platform credit amount (INR)
    platform_vpa        VARCHAR(150),
    platform_name       VARCHAR(200),

    wow_change_pct      DECIMAL(8,4),
        -- (this_week - prev_week) / prev_week × 100.
        -- Negative = income drop. NULL for week 1 (no prior reference).

    is_stress_week      BOOLEAN DEFAULT FALSE,
        -- TRUE for the stress-window weeks (13–16) of a stressed worker.

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
