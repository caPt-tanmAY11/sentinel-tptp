// dashboards/lib/api.ts

import axios from 'axios';

const BASE      = process.env.NEXT_PUBLIC_API_URL  || 'http://localhost:8001';
const NEXT_BASE = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';

// For FastAPI backend calls
export const api = axios.create({ baseURL: BASE, timeout: 15_000 });

// For Next.js internal API route calls (nodemailer lives here)
export const nextApi = axios.create({ baseURL: NEXT_BASE, timeout: 15_000 });

api.interceptors.request.use(cfg => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('sentinel_token');
    if (token) cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

api.interceptors.response.use(
  r => r,
  err => {
    if (typeof window !== 'undefined' && err.response?.status === 401) {
      localStorage.removeItem('sentinel_token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  },
);

export const sentinelApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { username: email, password }),

  getPortfolioMetrics: () =>
    api.get('/portfolio/metrics'),

  getCustomers: (params?: { risk_label?: string; search?: string; limit?: number; offset?: number }) =>
    api.get('/customers', { params }),

  getCustomerPulse: (id: string) =>
    api.get(`/customer/${id}/pulse`),

  getCustomerPulseHistory: (id: string, lastN = 60) =>
    api.get(`/customer/${id}/pulse_history`, { params: { last_n: lastN } }),

  getCustomerBaseline: (id: string) =>
    api.get(`/customer/${id}/baseline`),

  getCustomerProfile: (id: string) =>
    api.get(`/customer/${id}/profile`),

  getCustomerLoans: (id: string) =>
    api.get(`/customer/${id}/loans`),

  getCustomerCreditCards: (id: string) =>
    api.get(`/customer/${id}/credit_cards`),

  getCustomerTransactions: (id: string, limit = 50) =>
    api.get(`/customer/${id}/transactions`, { params: { limit } }),

  getHighRisk: (minScore = 0.55, limit = 20) =>
    api.get('/scores/high_risk', { params: { min_score: minScore, limit } }),

  getLiveTransactions: (limit = 50) =>
    api.get('/transactions/live', { params: { limit } }),

  getInterventions: () =>
    api.get('/interventions'),

  getPendingInterventions: () =>
    api.get('/interventions/pending'),

  processInterventions: () =>
    nextApi.post('/api/interventions/process'),

  createIntervention: (customerId: string, riskTier: string, interventionId?: string) =>
    api.post('/interventions', { customer_id: customerId, risk_tier: riskTier, intervention_id: interventionId }),

  acknowledgeIntervention: (interventionId: string) =>
    api.post(`/interventions/${interventionId}/acknowledge`),

  getHealth: () =>
    api.get('/health'),

  // Returns 3 AI-generated relief suggestions for a customer (uses GROQ)
  getReliefSuggestions: (customer: {
    customer_id: string;
    first_name: string;
    last_name: string;
    risk_tier: string;
    risk_score?: number;
    anomaly_score?: number;
    txn_severity?: number;
  }) =>
    nextApi.post('/api/interventions/suggest', customer),

  // Now also accepts the officer's chosen relief + optional comment
  sendInterventionEmail: (payload: {
    customer_id: string;
    first_name: string;
    last_name: string;
    risk_tier: string;
    selected_relief?: { id: number; title: string; description: string };
    officer_comment?: string;
  }) =>
    nextApi.post('/api/interventions/send', payload),

  getGrievances: () =>
    api.get('/grievances'),

  // Monitoring & Audit endpoints
  getPsiAirMonitoring: () =>
    api.get('/monitoring/psi-air'),

  getFullAuditTrail: (customerId?: string, limit = 500) =>
    api.get('/audit/full-trail', { params: { customer_id: customerId, limit } }),

  // ── Probable Fault Detection (PFD) ──────────────────────────────────────

  // All fraud alerts across the portfolio (dashboard panel)
  getFraudAlerts: (status = 'OPEN', limit = 100) =>
    api.get('/fraud_alerts', { params: { status, limit } }),

  // Fraud alerts for one specific customer
  getCustomerFraudAlerts: (customerId: string, status?: string) =>
    api.get(`/customer/${customerId}/fraud_alerts`, {
      params: status ? { status } : {},
    }),

  // Officer reviews an alert (REVIEWED | DISMISSED | CONFIRMED)
  reviewFraudAlert: (
    alertId:     string,
    status:      string,
    reviewedBy:  string,
    reviewNotes?: string,
  ) =>
    api.patch(`/fraud_alerts/${alertId}/review`, {
      status,
      reviewed_by:  reviewedBy,
      review_notes: reviewNotes,
    }),

  // Next.js stamps email sent after nodemailer success
  markFraudAlertEmailSent: (alertId: string) =>
    api.post(`/fraud_alerts/${alertId}/email_sent`),

  // Send fraud alert email (calls the Next.js nodemailer route above)
  sendFraudAlertEmail: (payload: {
    alert_id:                string;
    customer_id:             string;
    first_name:              string;
    last_name:               string;
    txn_amount:              number;
    platform:                string;
    receiver_vpa?:           string | null;
    receiver_country:        string;
    currency:                string;
    fraud_score:             number;
    fraud_reason:            string;
    signal_international:    boolean;
    signal_amount_spike:     boolean;
    signal_freq_spike:       boolean;
    payment_holiday_suggested: boolean;
    next_emi_due_date?:      string | null;
    emi_amount?:             number | null;
  }) =>
    nextApi.post('/api/fraud/alert', payload),
};