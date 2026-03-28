'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';

export default function GigWorkersPage() {
  const router = useRouter();
  const [workers, setWorkers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/gig_workers')
      .then(res => setWorkers(res.data.gig_workers))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col mb-8">
        <h1 className="text-3xl font-headline font-bold text-gray-900 mb-2">Gig Workers</h1>
        <p className="text-slate-500">Monitor platform payouts, income volatility, and stress risk factors</p>
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><div className="w-8 h-8 rounded-full border-4 border-blue-600 border-t-transparent animate-spin"/></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {workers.map(w => (
            <div key={w.customer_id} onClick={() => router.push(`/dashboard/gig-workers/${w.customer_id}`)}
                 className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm cursor-pointer hover:shadow-lg transition-all hover:-translate-y-1">
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-700 font-bold text-lg">
                    {w.first_name[0]}{w.last_name[0]}
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900 leading-tight">{w.first_name} {w.last_name}</h3>
                    <p className="text-xs text-slate-500">{w.city}, {w.state}</p>
                  </div>
                </div>
                {w.is_stressed ? (
                  <span className="bg-red-50 text-red-600 border border-red-200 px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase">
                    Stressed
                  </span>
                ) : (
                  <span className="bg-emerald-50 text-emerald-600 border border-emerald-200 px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase">
                    Stable
                  </span>
                )}
              </div>

              <div className="space-y-3 mt-6">
                <div className="flex justify-between text-sm items-center border-b border-slate-50 pb-2">
                  <span className="text-slate-500 text-xs uppercase tracking-wider">Platform</span>
                  <span className="font-semibold text-slate-800">{w.platform_name || 'Various'} ({w.platform_category || 'N/A'})</span>
                </div>
                <div className="flex justify-between text-sm items-center">
                  <span className="text-slate-500 text-xs uppercase tracking-wider">Baseline Income</span>
                  <span className="font-headline font-bold text-slate-800">₹{(w.baseline_weekly_income || 0).toLocaleString()} <span className="text-xs font-normal text-slate-400">/wk</span></span>
                </div>
              </div>
            </div>
          ))}
          {workers.length === 0 && (
             <div className="col-span-3 text-center py-20 text-slate-500">
                <span className="material-symbols-outlined text-4xl mb-4 opacity-50">person_off</span>
                <p>No gig workers found in the database. Run the Simulator first.</p>
             </div>
          )}
        </div>
      )}
    </div>
  );
}
