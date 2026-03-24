import axios from 'axios';

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

export const api = axios.create({ baseURL: BASE, timeout: 15_000 });

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

  getHealth: () =>
    api.get('/health'),
};