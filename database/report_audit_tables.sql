-- database/report_audit_tables.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- SENTINEL V2 — Report Generation Audit Tables
-- Bank: Barclays Bank India Private Limited
--
-- Run this migration ONCE after the main init.sql has been applied:
--   psql -U sentinel_user -d sentinel -f database/report_audit_tables.sql
--
-- These tables store:
--   1. report_audit_log         — Every generated report (full JSON + metadata)
--   2. intervention_form_responses — Customer self-declaration submissions
--
-- Both tables are designed to be legally admissible records under:
--   - Indian Evidence Act 1872, Section 65B
--   - PMLA 2002, Section 12 (record-keeping obligation)
--   - RBI Master Direction on Fraud Classification (6-year retention)
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── Report Audit Log ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS report_audit_log (
    report_id           TEXT        NOT NULL,
    reference_number    TEXT        NOT NULL,
    customer_id         UUID        NOT NULL,

    -- Risk snapshot at time of generation
    risk_tier           TEXT        NOT NULL
                            CHECK (risk_tier IN ('CRITICAL','HIGH','MODERATE','WATCH','STABLE')),
    pulse_score         NUMERIC(6,4) NOT NULL
                            CHECK (pulse_score >= 0 AND pulse_score <= 1),

    -- Generation metadata
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_model           TEXT        NOT NULL,
    llm_provider        TEXT        NOT NULL DEFAULT 'Anthropic PBC',
    sentinel_version    TEXT        NOT NULL DEFAULT '2.0.0',

    -- Compliance verification
    checklist_passed    BOOLEAN     NOT NULL,
    human_review_req    BOOLEAN     NOT NULL DEFAULT false,

    -- Full report stored as JSONB for audit trail
    report_json         JSONB       NOT NULL,

    -- Immutability enforcement
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_report_audit PRIMARY KEY (report_id)
);

-- Indexes for regulatory query patterns
CREATE INDEX IF NOT EXISTS idx_ral_customer_id
    ON report_audit_log (customer_id);

CREATE INDEX IF NOT EXISTS idx_ral_generated_at
    ON report_audit_log (generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ral_risk_tier
    ON report_audit_log (risk_tier);

CREATE INDEX IF NOT EXISTS idx_ral_reference
    ON report_audit_log (reference_number);

-- Prevent row updates (audit immutability)
-- In production, back this with a PostgreSQL trigger:
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

COMMENT ON TABLE report_audit_log IS
    'Immutable audit log of every Sentinel V2 Pre-Delinquency Report. '
    'Retention: 6 years per RBI Master Direction on Fraud Classification. '
    'Section 65B certified electronic record.';

-- ── Intervention Form Responses ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS intervention_form_responses (
    form_id             TEXT        NOT NULL,
    customer_id         UUID        NOT NULL,
    report_reference    TEXT        NOT NULL,

    -- Customer self-declaration
    explanation         TEXT        NOT NULL,
    current_income      NUMERIC(14,2),
    current_outstanding_loans NUMERIC(14,2),
    preferred_contact   TEXT        NOT NULL
                            CHECK (preferred_contact IN ('email','sms','whatsapp','branch')),
    consent_to_contact  BOOLEAN     NOT NULL,
    additional_notes    TEXT,

    -- Metadata
    submitted_at        TIMESTAMPTZ NOT NULL,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address          TEXT,                   -- for fraud prevention audit
    processed           BOOLEAN     NOT NULL DEFAULT false,
    assigned_officer    TEXT,

    CONSTRAINT pk_form_response PRIMARY KEY (form_id)
);

CREATE INDEX IF NOT EXISTS idx_ifr_customer_id
    ON intervention_form_responses (customer_id);

CREATE INDEX IF NOT EXISTS idx_ifr_report_reference
    ON intervention_form_responses (report_reference);

CREATE INDEX IF NOT EXISTS idx_ifr_submitted_at
    ON intervention_form_responses (submitted_at DESC);

COMMENT ON TABLE intervention_form_responses IS
    'Customer self-declaration form submissions for the Barclays Digital '
    'Intervention Portal. Required by RBI Consumer Protection Framework '
    'RBI/2023-24/18. Retention: 3 years.';

-- ── Data Retention Policy View ───────────────────────────────────────────────

CREATE OR REPLACE VIEW v_reports_due_for_archival AS
    SELECT report_id, reference_number, customer_id, generated_at,
           NOW() - generated_at AS age,
           'Archive after 6 years per RBI policy' AS retention_note
    FROM report_audit_log
    WHERE generated_at < NOW() - INTERVAL '5 years 9 months'; -- 3 months before deadline

COMMENT ON VIEW v_reports_due_for_archival IS
    'Reports approaching their 6-year RBI retention deadline. '
    'Review and archive before deletion.';

COMMIT;