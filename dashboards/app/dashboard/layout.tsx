'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/authStore';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router         = useRouter();
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) router.replace('/login');
    else setReady(true);
  }, [isAuthenticated, router]);

  if (!ready) return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="animate-spin h-8 w-8 rounded-full border-2 border-blue-600 border-t-transparent" />
    </div>
  );

  return <>{children}</>;
}