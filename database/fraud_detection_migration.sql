-- =====================================================================
-- SENTINEL V2 — Probable Fault Detection (PFD) Migration
-- Run once: psql -U sentinel_user -d sentinel -f database/fraud_detection_migration.sql
-- =====================================================================

-- ─────────────────────────────────────────────────────────────────────
-- 1. Add currency, receiver_country, receiver_vpa to ALL transaction
--    partitions (ALTER on parent propagates to all children in PG)
-- ─────────────────────────────────────────────────────────────────────
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS currency         VARCHAR(3)    DEFAULT 'INR',
    ADD COLUMN IF NOT EXISTS receiver_country VARCHAR(2)    DEFAULT 'IN',
    ADD COLUMN IF NOT EXISTS receiver_vpa     VARCHAR(150);

-- Note: receiver_vpa intentionally has no DEFAULT — it is NULL for
-- non-UPI transactions (ATM, NACH, RTGS, etc.) and populated only
-- when the receiver is identified by a UPI VPA.

-- ─────────────────────────────────────────────────────────────────────
-- 2. fraud_alerts — one row per fraud-flagged transaction
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id             UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,

    -- The transaction that triggered this alert
    -- No FK to transactions — partitioned tables don't support cross-table FKs in PG
    transaction_id          UUID                     NOT NULL,
    txn_timestamp           TIMESTAMP WITH TIME ZONE NOT NULL,
    txn_amount              DECIMAL(15,2)            NOT NULL,
    platform                VARCHAR(20)              NOT NULL,

    -- Receiver identity snapshot (captured at alert time for audit trail)
    receiver_vpa            VARCHAR(150),   -- e.g. "unknown.payee@ybl", "intl-merchant@swift"
    receiver_name           VARCHAR(200),   -- e.g. "Stripe Payments UK Ltd"
    receiver_country        VARCHAR(2)      DEFAULT 'IN',  -- ISO 3166-1 alpha-2
    currency                VARCHAR(3)      DEFAULT 'INR', -- ISO 4217

    -- ── Fraud signals (which of the 3 fired) ─────────────────────
    signal_international    BOOLEAN DEFAULT FALSE,  -- non-INR or non-IN receiver
    signal_amount_spike     BOOLEAN DEFAULT FALSE,  -- amount Z-score exceeded threshold
    signal_freq_spike       BOOLEAN DEFAULT FALSE,  -- hourly txn count spike detected

    -- ── Composite fraud score + audit numbers ────────────────────
    fraud_score             DECIMAL(5,4) NOT NULL,  -- weighted composite, 0.0–1.0
    fraud_reason            TEXT         NOT NULL,  -- human-readable, e.g.
                                                    -- "International txn to unknown@ybl (USD);
                                                    --  amount ₹84,000 is 4.2σ above baseline;
                                                    --  12 txns in last hour vs avg 1.8"

    -- Z-score trail
    amount_zscore           DECIMAL(8,4),           -- (txn_amount - baseline_avg) / baseline_std
    baseline_amount_avg     DECIMAL(15,2),          -- customer's 30d average txn amount
    baseline_amount_std     DECIMAL(15,2),          -- customer's 30d std dev of txn amount

    -- Frequency trail
    hourly_txn_count        INTEGER,                -- txns in the last 60 minutes
    baseline_hourly_avg     DECIMAL(8,4),           -- customer's baseline hourly txn rate

    -- ── Alert lifecycle ──────────────────────────────────────────
    status                  VARCHAR(20) DEFAULT 'OPEN'
                                CHECK (status IN ('OPEN', 'REVIEWED', 'DISMISSED', 'CONFIRMED')),
    alert_email_sent        BOOLEAN      DEFAULT FALSE,
    alert_email_sent_at     TIMESTAMP WITH TIME ZONE,
    reviewed_by             VARCHAR(100),
    reviewed_at             TIMESTAMP WITH TIME ZONE,
    review_notes            TEXT,

    -- ── EMI context (populated if next EMI is within 7 days) ─────
    next_emi_due_date       DATE,
    emi_amount              DECIMAL(15,2),
    payment_holiday_suggested BOOLEAN DEFAULT FALSE,

    -- ── Audit ────────────────────────────────────────────────────
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────
-- 3. Indexes
-- ─────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_customer     ON fraud_alerts(customer_id);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_status       ON fraud_alerts(status);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_created      ON fraud_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_transaction  ON fraud_alerts(transaction_id);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_receiver_vpa ON fraud_alerts(receiver_vpa)
    WHERE receiver_vpa IS NOT NULL;

-- Partial index — fast lookup of all unresolved alerts per customer
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_open         ON fraud_alerts(customer_id, created_at DESC)
    WHERE status = 'OPEN';

-- ─────────────────────────────────────────────────────────────────────
-- 4. Auto-update updated_at on every row change
-- ─────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_fraud_alert_timestamp()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_fraud_alert_updated_at ON fraud_alerts;
CREATE TRIGGER trg_fraud_alert_updated_at
    BEFORE UPDATE ON fraud_alerts
    FOR EACH ROW EXECUTE FUNCTION update_fraud_alert_timestamp();