import axios from 'axios';

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
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
  login:              (email: string, password: string) =>
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

  sendInterventionEmail: (customer: { customer_id: string; first_name: string; last_name: string; risk_tier: string }) =>
    nextApi.post('/api/interventions/send', customer),
};