'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea, BarChart, Bar } from 'recharts';

export default function GigWorkerDetails() {
  const router = useRouter();
  const { id } = useParams();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.get(`/gig_workers/${id}/metrics`)
      .then(res => setData(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <div className="flex justify-center py-20"><div className="w-8 h-8 rounded-full border-4 border-blue-600 border-t-transparent animate-spin"/></div>;
  }

  if (!data) {
    return <div className="text-center py-20 text-slate-500">Could not load Gig Worker.</div>;
  }

  const { profile, income_history, avg_weekly_balance, avg_monthly_balance, recent_transactions } = data;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <button onClick={() => router.back()} className="text-sm text-blue-600 font-bold tracking-wide flex items-center gap-1 hover:text-blue-800 transition-colors">
        <span className="material-symbols-outlined text-sm">arrow_back</span>
        BACK TO DIRECTORY
      </button>

      {/* Header Profile */}
      <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm flex flex-col md:flex-row justify-between md:items-center gap-4">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-blue-600 to-indigo-800 flex items-center justify-center text-white font-bold text-2xl shadow-md">
            {profile.first_name[0]}{profile.last_name[0]}
          </div>
          <div>
            <h1 className="text-2xl font-headline font-bold text-gray-900 leading-tight">
              {profile.first_name} {profile.last_name}
            </h1>
            <p className="text-sm text-slate-500 font-medium">Gig Worker ({profile.platform_name || 'Various Platforms'}) • {profile.city}, {profile.state}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
            <span className={`px-3 py-1 rounded-full text-xs font-bold tracking-widest uppercase border ${
              profile.is_stressed 
                ? 'bg-red-50 text-red-600 border-red-200' 
                : 'bg-emerald-50 text-emerald-600 border-emerald-200'
            }`}>
              {profile.stress_label || 'NOT STRESSED'}
            </span>
            {profile.is_stressed && (
               <span className="text-xs font-bold text-red-500 whitespace-nowrap">
                   Peak Drop: {Number(profile.max_wow_drop_pct || 0)?.toFixed(1)}%
               </span>
            )}
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <span className="material-symbols-outlined text-6xl">account_balance_wallet</span>
          </div>
          <p className="text-xs uppercase tracking-widest text-slate-500 font-bold mb-1">Avg Balance (7 Days)</p>
          <p className="text-3xl font-headline font-extrabold text-[#005a82]">₹{avg_weekly_balance.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</p>
        </div>
        
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <span className="material-symbols-outlined text-6xl">account_balance</span>
          </div>
          <p className="text-xs uppercase tracking-widest text-slate-500 font-bold mb-1">Avg Balance (30 Days)</p>
          <p className="text-3xl font-headline font-extrabold text-[#005a82]">₹{avg_monthly_balance.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</p>
        </div>

        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <span className="material-symbols-outlined text-6xl">insights</span>
          </div>
          <p className="text-xs uppercase tracking-widest text-slate-500 font-bold mb-1">Baseline Weekly Income</p>
          <p className="text-3xl font-headline font-extrabold text-[#005a82]">₹{Number(profile.baseline_weekly_income || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
        </div>
      </div>

      {/* Income Graph */}
      <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
        <div className="mb-6">
          <h2 className="text-lg font-bold font-headline text-gray-900">Platform Income History (16 Weeks)</h2>
          <p className="text-sm text-slate-500">Visualizing payout volatility and pre-delinquency stress signals</p>
        </div>
        
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={income_history} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
              <XAxis dataKey="week_label" axisLine={false} tickLine={false} tick={{fill: '#64748B', fontSize: 12}} dy={10} />
              <YAxis 
                axisLine={false} 
                tickLine={false} 
                tickFormatter={(val) => `₹${val.toLocaleString()}`}
                tick={{fill: '#64748B', fontSize: 12}} 
              />
              <Tooltip 
                formatter={(value: number) => [`₹${value.toLocaleString()}`, 'Payout']}
                labelStyle={{color: '#64748B', fontWeight: 'bold'}}
                contentStyle={{borderRadius: '0.75rem', border: 'none', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)'}}
              />
              
              {/* Highlight stress window if any */}
              {profile.is_stressed && (
                 <ReferenceArea x1="W13" x2="W16" strokeOpacity={0.3} fill="#FECACA" fillOpacity={0.3} />
              )}
              
              <Line 
                type="monotone" 
                dataKey="payout_amount" 
                stroke="#2563EB" 
                strokeWidth={3}
                dot={{r: 4, strokeWidth: 2, fill: '#fff'}}
                activeDot={{r: 6, strokeWidth: 0, fill: '#2563EB'}}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        
        {profile.is_stressed && (
          <div className="mt-4 flex items-center gap-2 text-xs text-red-600 bg-red-50 p-3 rounded-lg border border-red-100">
            <span className="material-symbols-outlined text-sm">warning</span>
            Shaded area indicates a detected stress window (multi-week income collapse &gt; 50%).
          </div>
        )}
      </div>

      {/* Stress Classification Graph */}
      <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
        <div className="mb-6">
          <h2 className="text-lg font-bold font-headline text-gray-900">Stress Classification (1 = Stressed, 0 = Stable)</h2>
          <p className="text-sm text-slate-500">Binary indicator of detected pre-delinquency stress per week</p>
        </div>
        
        <div className="h-[150px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={income_history.map((d: any) => ({ ...d, stress_val: d.is_stress_week ? 1 : 0 }))} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
              <XAxis dataKey="week_label" axisLine={false} tickLine={false} tick={{fill: '#64748B', fontSize: 12}} dy={10} />
              <YAxis 
                axisLine={false} 
                tickLine={false}
                tickFormatter={(val) => Math.round(val).toString()}
                domain={[0, 1]}
                ticks={[0, 1]}
                tick={{fill: '#64748B', fontSize: 12}} 
              />
              <Tooltip 
                formatter={(value: number) => [value === 1 ? 'Stressed (1)' : 'Stable (0)', 'Status']}
                labelStyle={{color: '#64748B', fontWeight: 'bold'}}
                contentStyle={{borderRadius: '0.75rem', border: 'none', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)'}}
                cursor={{fill: '#F1F5F9'}}
              />
              <Bar dataKey="stress_val" fill="#EF4444" radius={[4, 4, 0, 0]} barSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Transactions Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-100">
          <h2 className="text-lg font-bold font-headline text-gray-900">Recent Transactions</h2>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-slate-500 uppercase bg-slate-50/80">
              <tr>
                <th className="px-6 py-4 font-bold tracking-wider">Date</th>
                <th className="px-6 py-4 font-bold tracking-wider">Counterparty</th>
                <th className="px-6 py-4 font-bold tracking-wider">Type</th>
                <th className="px-6 py-4 font-bold tracking-wider text-right">Amount (₹)</th>
                <th className="px-6 py-4 font-bold tracking-wider text-right">Balance After (₹)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {recent_transactions.map((t: any) => {
                const isDebit = t.sender_name === `${profile.first_name} ${profile.last_name}` || 
                                (t.balance_after !== null && t.balance_before !== null && t.balance_after < t.balance_before);
                
                return (
                  <tr key={t.transaction_id} className="hover:bg-slate-50/50 transition-colors">
                    <td className="px-6 py-4 text-slate-500">
                      {new Date(t.txn_timestamp).toLocaleDateString()} {new Date(t.txn_timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                    </td>
                    <td className="px-6 py-4 font-medium text-slate-900">
                      {isDebit ? t.receiver_name : t.sender_name || 'Counterparty'}
                    </td>
                    <td className="px-6 py-4">
                      {isDebit ? (
                        <span className="bg-slate-100 text-slate-600 px-2 py-1 rounded text-xs font-bold uppercase tracking-wider">Debit</span>
                      ) : (
                        <span className="bg-emerald-50 text-emerald-600 px-2 py-1 rounded text-xs font-bold uppercase tracking-wider">Credit</span>
                      )}
                    </td>
                    <td className={`px-6 py-4 text-right font-bold ${isDebit ? 'text-slate-900' : 'text-emerald-600'}`}>
                      {isDebit ? '-' : '+'}₹{t.amount.toLocaleString(undefined, {minimumFractionDigits: 2})}
                    </td>
                    <td className="px-6 py-4 text-right text-slate-500">
                      {t.balance_after ? `₹${t.balance_after.toLocaleString(undefined, {minimumFractionDigits: 2})}` : '-'}
                    </td>
                  </tr>
                );
              })}
              
              {recent_transactions.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500">
                    No transactions found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      
    </div>
  );
}
