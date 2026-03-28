'use client';
import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Shield, Eye, EyeOff } from 'lucide-react';
import { sentinelApi } from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

export default function LoginPage() {
  const router = useRouter();
  const login  = useAuthStore(s => s.login);

  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [showPwd,  setShowPwd]  = useState(false);
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);

  const admins = [
    "manjunathmurali20@gmail.com",
    "testuser1togethr@gmail.com",
    "tanmay06lko@gmail.com",
    "sanyogeetapradhan@gmail.com",
    "sanyogaming25@gmail.com",
    "sundranidevraj@gmail.com",
    "rajatdalalpaaji@gmail.com",
    "akshaysinghpaaji@gmail.com",
    "sohanj9106@gmail.com",
    "sohan2.9106@gmail.com"
  ];

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const res = await sentinelApi.login(email, password);
      login(res.data.access_token, res.data.role, res.data.full_name);
      router.push('/dashboard');
    } catch {
      setError('Invalid credentials. Check your admin email or password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center relative overflow-hidden font-body text-slate-800 selection:bg-primary-container selection:text-on-primary-container">

      {/* Abstract Background Elements (matching landing page) */}
      <div className="absolute top-0 left-0 w-full h-full -z-10 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] rounded-full bg-blue-600/5 blur-[120px]"></div>
        <div className="absolute bottom-[20%] right-[-5%] w-[40%] h-[40%] rounded-full bg-purple-600/10 blur-[100px]"></div>
      </div>

      {/* Main glass panel wrapper */}
      <div className="relative z-10 w-full max-w-md p-1"
           style={{ background: 'rgba(255, 255, 255, 0.4)', borderRadius: '2.5rem', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.05)', backdropFilter: 'blur(20px)' }}>
        
        <div className="bg-white/70 p-10 rounded-[2.4rem] border border-white/60">
          
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 rounded-2xl mx-auto mb-5 flex items-center justify-center bg-blue-600 shadow-xl shadow-blue-600/30 text-white">
              <Shield className="w-8 h-8" strokeWidth={2.5} />
            </div>
            <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">Sentinel V2</h1>
            <p className="text-sm font-medium text-slate-500 mt-2">Institutional Risk Intelligence</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-widest mb-2 ml-1">
                Admin Email
              </label>
              
              <div className="relative">
                <input 
                  type="email"
                  className="w-full rounded-xl px-4 py-3.5 text-sm font-medium text-slate-700 bg-white/60 border border-slate-200 placeholder-slate-400 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 transition-all shadow-sm"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="Enter admin email"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-widest mb-2 ml-1">
                Password
              </label>
              <div className="relative">
                <input 
                  type={showPwd ? 'text' : 'password'} 
                  value={password}
                  onChange={e => setPassword(e.target.value)} 
                  required
                  className="w-full rounded-xl px-4 py-3.5 pr-12 text-sm font-medium text-slate-700 bg-white/60 border border-slate-200 placeholder-slate-400 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 transition-all shadow-sm"
                  placeholder="Enter password"
                />
                <button type="button" onClick={() => setShowPwd(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors">
                  {showPwd ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-xl px-4 py-3 text-sm font-medium bg-red-50 text-red-600 border border-red-100 animate-in fade-in zoom-in duration-200">
                <span className="material-symbols-outlined text-[18px]">error</span>
                {error}
              </div>
            )}

            <button type="submit" disabled={loading}
              className="group w-full py-4 mt-2 font-headline font-bold text-sm tracking-wide rounded-xl text-white transition-all active:scale-[0.98] disabled:opacity-50 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-600/25 hover:shadow-blue-600/40">
              {loading
                ? <>
                    <span className="animate-spin h-4 w-4 rounded-full border-2 border-white/20 border-t-white" />
                    <span>Authenticating…</span>
                  </>
                : <>
                    <span>Secure Sign In</span>
                    <span className="material-symbols-outlined text-[18px] transition-transform group-hover:translate-x-1">arrow_forward</span>
                  </>
              }
            </button>
          </form>

        </div>
      </div>
      
      {/* Decorative Glow Elements */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-blue-400/10 blur-[100px] rounded-full -z-10 mix-blend-multiply flex items-center justify-center pointer-events-none"></div>

      <div className="absolute bottom-6 left-0 right-0 text-center pointer-events-none">
        <p className="font-label text-xs font-bold text-slate-400 uppercase tracking-widest">
          End-to-end encrypted · Sentinel Security
        </p>
      </div>
    </div>
  );
}