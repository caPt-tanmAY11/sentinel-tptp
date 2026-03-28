'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/authStore';

function NavItem({ icon, label, href, active, onClick }: {
  icon: string; label: string; href?: string; active?: boolean; onClick?: () => void;
}) {
  const router = useRouter();
  const handleClick = () => {
    if (onClick) onClick();
    else if (href) router.push(href);
  };
  return (
    <button onClick={handleClick}
      className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm transition-all duration-200 ${
        active
          ? 'bg-white/80 text-blue-700 font-bold ambient-shadow-sm'
          : 'text-slate-500 hover:bg-white/50 hover:translate-x-0.5'
      }`}>
      <span className="material-symbols-outlined text-xl"
        style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}>
        {icon}
      </span>
      <span className="font-label">{label}</span>
    </button>
  );
}

export function Sidebar() {
  const router    = useRouter();
  const pathname  = usePathname();
  const logout    = useAuthStore(s => s.logout);
  const fullName  = useAuthStore(s => s.fullName);

  const handleLogout = () => { logout(); router.push('/login'); };

  return (
    <aside className="sidebar-glass h-screen w-64 fixed left-0 top-0 z-40 flex flex-col p-4 gap-2"
      style={{ background: 'linear-gradient(to bottom, rgba(247,249,251,0.5), rgba(242,244,246,0.5))' }}>
      {/* Brand */}
      <div className="flex items-center gap-3 px-2 mb-8 mt-2">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white"
          style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)' }}>
          <span className="material-symbols-outlined text-xl"
            style={{ fontVariationSettings: "'FILL' 1" }}>security</span>
        </div>
        <div>
          <h1 className="font-headline font-extrabold tracking-tighter text-blue-800 text-lg leading-tight">Sentinel AI</h1>
          <p className="text-[10px] font-label uppercase tracking-widest text-slate-400">Institutional Risk</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1">
        <NavItem icon="dashboard"   label="Overview"       href="/dashboard" active={pathname === '/dashboard'} />
        <NavItem icon="security"    label="Fraud Detection" href="/dashboard/fraud-alerts" active={pathname?.startsWith('/dashboard/fraud-alerts')} />
        <NavItem icon="receipt_long" label="Transactions"  href="/dashboard/transactions" active={pathname?.startsWith('/dashboard/transactions')} />
        <NavItem icon="bolt"        label="Interventions"  href="/dashboard/interventions" active={pathname?.startsWith('/dashboard/interventions')} />
        <NavItem icon="assessment"  label="Reports"        href="/dashboard/report" active={pathname?.startsWith('/dashboard/report')} />
        <NavItem icon="forum"       label="Grievances"     href="/dashboard/grievances" active={pathname?.startsWith('/dashboard/grievances')} />
        <NavItem icon="delivery_dining" label="Gig Workers"   href="/dashboard/gig-workers" active={pathname?.startsWith('/dashboard/gig-workers')} />
      </nav>



      {/* System status */}
      <div className="pt-4 space-y-1" style={{ borderTop: '1px solid rgba(195,198,215,0.2)' }}>
        <div className="px-4 py-2">
          <div className="flex items-center gap-2 text-[10px] font-bold text-[#005a82] bg-[#e4f2ff] px-2.5 py-1 rounded-full w-fit">
            <span className="w-1.5 h-1.5 rounded-full bg-[#005a82] animate-pulse" />
            System Status: Normal
          </div>
        </div>
        <NavItem icon="help"   label="Support" />
        <button onClick={handleLogout}
          className="w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm text-slate-500 hover:bg-white/50 transition-all">
          <span className="material-symbols-outlined text-xl">logout</span>
          <span className="font-label">Sign Out</span>
        </button>
      </div>

      {/* User */}
      <div className="flex items-center gap-3 px-2 pt-3 mt-1" style={{ borderTop: '1px solid rgba(195,198,215,0.2)' }}>
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-700 flex items-center justify-center text-white text-xs font-bold">
          {fullName?.[0] ?? 'A'}
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-on-surface truncate">{fullName}</p>
          <p className="text-[10px] text-slate-400">Credit Officer</p>
        </div>
      </div>
    </aside>
  );
}
