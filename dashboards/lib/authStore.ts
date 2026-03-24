import { create } from 'zustand';

interface AuthState {
  token:           string | null;
  role:            string | null;
  fullName:        string | null;
  isAuthenticated: boolean;
  login:  (token: string, role: string, fullName: string) => void;
  logout: () => void;
}

const safe = (k: string) => typeof window !== 'undefined' ? localStorage.getItem(k) : null;

export const useAuthStore = create<AuthState>((set) => ({
  token:           safe('sentinel_token'),
  role:            safe('sentinel_role'),
  fullName:        safe('sentinel_name'),
  isAuthenticated: !!safe('sentinel_token'),

  login: (token, role, fullName) => {
    localStorage.setItem('sentinel_token', token);
    localStorage.setItem('sentinel_role',  role);
    localStorage.setItem('sentinel_name',  fullName);
    set({ token, role, fullName, isAuthenticated: true });
  },
  logout: () => {
    ['sentinel_token', 'sentinel_role', 'sentinel_name'].forEach(k => localStorage.removeItem(k));
    set({ token: null, role: null, fullName: null, isAuthenticated: false });
  },
}));