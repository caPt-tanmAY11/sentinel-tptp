'use client';
import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Shield, Eye, EyeOff } from 'lucide-react';
import { sentinelApi } from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

export default function LoginPage() {
  const router = useRouter();
  const login  = useAuthStore(s => s.login);

  const [email,    setEmail]    = useState('admin@sentinel.bank');
  const [password, setPassword] = useState('sentinel_admin');
  const [showPwd,  setShowPwd]  = useState(false);
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const res = await sentinelApi.login(email, password);
      login(res.data.access_token, res.data.role, res.data.full_name);
      router.push('/dashboard');
    } catch {
      setError('Invalid credentials. Use admin@sentinel.bank / sentinel_admin');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden"
      style={{ background: 'linear-gradient(135deg,#0B1120 0%,#0F172A 40%,#1E1B4B 100%)' }}>

      {/* Ambient glows */}
      <div className="absolute -top-40 -left-40 w-96 h-96 rounded-full opacity-20"
        style={{ background: 'radial-gradient(circle,#3B82F6,transparent 70%)' }} />
      <div className="absolute bottom-0 right-0 w-80 h-80 rounded-full opacity-15"
        style={{ background: 'radial-gradient(circle,#8B5CF6,transparent 70%)' }} />

      <div className="relative z-10 w-full max-w-sm rounded-2xl p-8"
        style={{ background:'rgba(255,255,255,0.05)', border:'1px solid rgba(255,255,255,0.08)', backdropFilter:'blur(20px)' }}>

        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl mx-auto mb-4 flex items-center justify-center"
            style={{ background:'linear-gradient(135deg,#3B82F6,#8B5CF6)', boxShadow:'0 8px 32px rgba(59,130,246,0.4)' }}>
            <Shield className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">SENTINEL V2</h1>
          <p className="text-sm text-slate-400 mt-1">Pre-Delinquency Intelligence Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
              Email
            </label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
              className="w-full rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:ring-2 focus:ring-blue-500 transition"
              style={{ background:'rgba(255,255,255,0.07)', border:'1px solid rgba(255,255,255,0.1)' }}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
              Password
            </label>
            <div className="relative">
              <input type={showPwd ? 'text' : 'password'} value={password}
                onChange={e => setPassword(e.target.value)} required
                className="w-full rounded-xl px-4 py-3 pr-10 text-sm text-white placeholder-slate-500 outline-none focus:ring-2 focus:ring-blue-500 transition"
                style={{ background:'rgba(255,255,255,0.07)', border:'1px solid rgba(255,255,255,0.1)' }}
              />
              <button type="button" onClick={() => setShowPwd(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200">
                {showPwd ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {error && (
            <div className="rounded-lg px-3 py-2 text-xs text-red-300"
              style={{ background:'rgba(220,38,38,0.15)', border:'1px solid rgba(220,38,38,0.3)' }}>
              {error}
            </div>
          )}

          <button type="submit" disabled={loading}
            className="w-full py-3 text-sm font-bold rounded-xl text-white transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
            style={{ background:'linear-gradient(135deg,#3B82F6,#6366F1)', boxShadow:'0 4px 20px rgba(59,130,246,0.35)' }}>
            {loading
              ? <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin h-4 w-4 rounded-full border-2 border-white border-t-transparent" />
                  Authenticating…
                </span>
              : 'Sign In'
            }
          </button>
        </form>

        <p className="text-center text-xs text-slate-500 mt-6">
          Sentinel V2 · Pre-Delinquency Engine
        </p>
      </div>
    </div>
  );
}