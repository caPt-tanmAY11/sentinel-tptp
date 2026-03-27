-- =====================================================================
-- SENTINEL V2 — Grievances Table Migration
-- Run once against your existing database
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