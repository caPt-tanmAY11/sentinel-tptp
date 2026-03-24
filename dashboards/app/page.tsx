import Link from 'next/link';

export default function LandingPage() {
  return (
    <div className="bg-background text-on-background font-body selection:bg-primary-container selection:text-on-primary-container text-slate-800">
      {/* TopNavBar */}
      <nav className="fixed top-0 w-full z-50 bg-white/40 backdrop-blur-xl shadow-sm bg-opacity-30">
        <div className="flex justify-between items-center max-w-7xl mx-auto px-6 h-20">
          <div className="text-xl font-bold tracking-tighter text-blue-700 font-headline">Sentinel AI</div>
          <div className="hidden md:flex items-center gap-8">
            <Link className="text-blue-700 border-b-2 border-blue-600 pb-1 font-headline tracking-tight text-sm font-semibold" href="#">Solutions</Link>
            <Link className="text-slate-600 hover:text-blue-600 transition-colors font-headline tracking-tight text-sm font-semibold" href="#">Risk Engine</Link>
            <Link className="text-slate-600 hover:text-blue-600 transition-colors font-headline tracking-tight text-sm font-semibold" href="#">Intelligence</Link>
            <Link className="text-slate-600 hover:text-blue-600 transition-colors font-headline tracking-tight text-sm font-semibold" href="#">Institutional</Link>
            <Link className="text-slate-600 hover:text-blue-600 transition-colors font-headline tracking-tight text-sm font-semibold" href="#">Pricing</Link>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/login" className="text-slate-600 font-headline text-sm font-semibold px-4 py-2 hover:opacity-80 transition-opacity">Login</Link>
            <Link href="/dashboard" className="bg-primary text-on-primary px-6 py-2.5 rounded-xl font-headline text-sm font-bold shadow-lg shadow-primary/20 active:scale-95 transition-all">Get Started</Link>
          </div>
        </div>
      </nav>

      <main className="relative pt-20">
        {/* Abstract Background Elements */}
        <div className="absolute top-0 left-0 w-full h-full -z-10 overflow-hidden pointer-events-none">
          <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] rounded-full bg-primary/5 blur-[120px]"></div>
          <div className="absolute bottom-[20%] right-[-5%] w-[40%] h-[40%] rounded-full bg-tertiary/10 blur-[100px]"></div>
        </div>

        {/* Hero Section */}
        <section className="max-w-7xl mx-auto px-6 pt-24 pb-32">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-16 items-center">
            <div className="lg:col-span-7 space-y-8">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary font-label text-xs font-bold tracking-widest uppercase">
                <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>verified_user</span>
                Next-Gen Risk Engine
              </div>
              <h1 className="text-6xl lg:text-7xl font-headline font-extrabold tracking-tighter text-on-surface leading-[1.05]">
                Smart Risk <br/>
                <span className="text-primary">Intervention</span> <br/>
                Solutions
              </h1>
              <p className="text-xl text-on-secondary-container max-w-xl leading-relaxed">
                Quantify behavioral drift and institutional risk with real-time AI. Precision-engineered for modern financial ecosystems.
              </p>
              <div className="flex flex-wrap gap-4 pt-4">
                <Link href="/dashboard" className="bg-primary text-on-primary px-8 py-4 rounded-xl font-headline font-bold text-lg shadow-xl shadow-primary/25 hover:shadow-primary/40 transition-all flex items-center gap-3">
                  Launch Engine
                  <span className="material-symbols-outlined">arrow_forward</span>
                </Link>
                <div className="flex items-center gap-4 px-6">
                  <div className="flex -space-x-3">
                    <div className="w-10 h-10 rounded-full border-2 border-white bg-slate-200"></div>
                    <div className="w-10 h-10 rounded-full border-2 border-white bg-slate-300"></div>
                    <div className="w-10 h-10 rounded-full border-2 border-white bg-slate-400"></div>
                  </div>
                  <span className="text-sm font-semibold text-secondary">Joined by 400+ Institutions</span>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5 relative">
              {/* Glassmorphic Hero Card */}
              <div className="glass-panel rounded-[2.5rem] p-8 shadow-2xl relative z-10">
                <div className="flex justify-between items-start mb-12">
                  <div className="bg-primary-container/20 p-4 rounded-2xl">
                    <span className="material-symbols-outlined text-primary text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>query_stats</span>
                  </div>
                  <div className="text-right">
                    <div className="text-xs font-bold text-primary tracking-widest uppercase mb-1">Efficiency</div>
                    <div className="text-4xl font-headline font-extrabold text-on-surface">70%</div>
                  </div>
                </div>
                <div className="space-y-6">
                  <div className="h-2 w-full bg-surface-container-high rounded-full overflow-hidden">
                    <div className="h-full bg-primary w-[70%]"></div>
                  </div>
                  <h3 className="font-headline font-bold text-xl text-on-surface">Optimization Metric</h3>
                  <p className="text-sm text-on-secondary-container leading-relaxed">
                    Automated intervention protocols increased operational efficiency by 70% across tier-1 portfolios.
                  </p>
                  <div className="pt-4 border-t border-white/20 flex justify-between items-center">
                    <span className="text-xs font-bold text-secondary uppercase tracking-widest">Real-time status</span>
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-tertiary animate-pulse"></div>
                      <span className="text-xs font-semibold text-tertiary">Live Processing</span>
                    </div>
                  </div>
                </div>
              </div>
              {/* Decorative Glow */}
              <div className="absolute -top-10 -right-10 w-40 h-40 bg-primary/20 blur-[80px] rounded-full"></div>
            </div>
          </div>
        </section>

        {/* Stats Strip */}
        <section className="bg-surface-container-low/50 py-16 text-slate-800">
          <div className="max-w-7xl mx-auto px-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-12 text-center">
              <div className="space-y-2">
                <div className="text-5xl font-headline font-extrabold text-primary">25%</div>
                <div className="text-sm font-bold text-secondary uppercase tracking-widest">NPL Reduction</div>
              </div>
              <div className="space-y-2">
                <div className="text-5xl font-headline font-extrabold text-primary">15%</div>
                <div className="text-sm font-bold text-secondary uppercase tracking-widest">Lower Collection Costs</div>
              </div>
              <div className="space-y-2">
                <div className="text-5xl font-headline font-extrabold text-primary">9.2 Days</div>
                <div className="text-sm font-bold text-secondary uppercase tracking-widest">Earlier Detection</div>
              </div>
            </div>
          </div>
        </section>

        {/* Dashboard Preview Section */}
        <section className="max-w-7xl mx-auto px-6 py-32">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-24 items-center">
            <div className="order-2 lg:order-1 relative">
              {/* Glass Dashboard UI */}
              <div className="glass-panel rounded-[2rem] p-1 shadow-2xl overflow-hidden">
                <div className="bg-white/60 p-6 flex items-center justify-between border-b border-white/20">
                  <div className="flex items-center gap-3">
                    <div className="w-3 h-3 rounded-full bg-error/40"></div>
                    <div className="w-3 h-3 rounded-full bg-tertiary/40"></div>
                    <div className="w-3 h-3 rounded-full bg-primary/40"></div>
                    <span className="ml-4 text-xs font-bold text-on-surface-variant uppercase tracking-widest">Pulse Monitoring</span>
                  </div>
                  <span className="material-symbols-outlined text-on-surface-variant">more_horiz</span>
                </div>
                <div className="p-8 space-y-8">
                  {/* Dashboard Content Mock */}
                  <div className="grid grid-cols-2 gap-6">
                    <div className="bg-white/40 p-5 rounded-2xl border border-white/40">
                      <div className="text-xs font-bold text-secondary uppercase mb-2">Behavioral Drift</div>
                      <div className="text-2xl font-headline font-bold text-on-surface">+12.4%</div>
                      <div className="mt-4 h-12 w-full">
                        <svg className="w-full h-full text-primary" preserveAspectRatio="none" viewBox="0 0 100 30">
                          <path d="M0 25 L20 15 L40 20 L60 5 L80 18 L100 10" fill="none" stroke="currentColor" strokeWidth="2"></path>
                        </svg>
                      </div>
                    </div>
                    <div className="bg-white/40 p-5 rounded-2xl border border-white/40">
                      <div className="text-xs font-bold text-secondary uppercase mb-2">Pulse Score</div>
                      <div className="flex items-center justify-center py-2">
                        <div className="relative w-16 h-16 flex items-center justify-center">
                          <svg className="w-full h-full transform -rotate-90">
                            <circle className="text-surface-container-high" cx="32" cy="32" fill="transparent" r="28" stroke="currentColor" strokeWidth="6"></circle>
                            <circle className="text-primary" cx="32" cy="32" fill="transparent" r="28" stroke="currentColor" strokeDasharray="176" strokeDashoffset="35" strokeWidth="6"></circle>
                          </svg>
                          <span className="absolute text-sm font-bold">82</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="bg-white/40 p-6 rounded-2xl border border-white/40 space-y-4">
                    <div className="flex justify-between items-center">
                      <span className="text-sm font-bold text-on-surface">Critical Anomalies</span>
                      <span className="text-xs bg-error/10 text-error px-2 py-1 rounded-md font-bold">Action Required</span>
                    </div>
                    <div className="space-y-3">
                      <div className="flex items-center gap-4 text-sm p-3 bg-white/60 rounded-xl">
                        <span className="material-symbols-outlined text-error" style={{ fontVariationSettings: "'FILL' 1" }}>warning</span>
                        <span className="font-medium text-slate-800">Unusual sequence in APAC Tier 2</span>
                        <span className="ml-auto text-xs text-secondary">2m ago</span>
                      </div>
                      <div className="flex items-center gap-4 text-sm p-3 bg-white/60 rounded-xl">
                        <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>info</span>
                        <span className="font-medium text-slate-800">Intervention threshold met</span>
                        <span className="ml-auto text-xs text-secondary">15m ago</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="order-1 lg:order-2 space-y-8">
              <h2 className="text-5xl font-headline font-extrabold tracking-tight text-on-surface leading-tight">
                Institutional Grade <br/>
                <span className="text-primary">Intelligence</span>
              </h2>
              <p className="text-lg text-on-secondary-container leading-relaxed">
                Our behavioral engine monitors every transaction pulse, detecting micro-shifts in risk profiles days before traditional models. Secure, scalable, and built for complex regulatory environments.
              </p>
              <ul className="space-y-4">
                <li className="flex items-center gap-3 text-on-surface font-semibold">
                  <span className="material-symbols-outlined text-primary">check_circle</span>
                  End-to-end data encryption
                </li>
                <li className="flex items-center gap-3 text-on-surface font-semibold">
                  <span className="material-symbols-outlined text-primary">check_circle</span>
                  Multi-agent AI risk simulation
                </li>
                <li className="flex items-center gap-3 text-on-surface font-semibold">
                  <span className="material-symbols-outlined text-primary">check_circle</span>
                  Automated regulatory reporting
                </li>
              </ul>
              <div className="pt-6">
                <Link href="/dashboard" className="group inline-flex items-center gap-4 text-primary font-headline font-extrabold text-lg tracking-widest uppercase">
                  Explore More
                  <span className="w-12 h-12 rounded-full border border-primary/20 flex items-center justify-center group-hover:bg-primary group-hover:text-on-primary transition-all">
                    <span className="material-symbols-outlined">arrow_right_alt</span>
                  </span>
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* CTA Section */}
        <section className="max-w-7xl mx-auto px-6 py-24">
          <div className="bg-primary-container rounded-[3rem] p-12 lg:p-20 text-center relative overflow-hidden">
            <div className="relative z-10 space-y-8">
              <h2 className="text-4xl lg:text-5xl font-headline font-extrabold text-on-primary-container">Ready to harden your risk posture?</h2>
              <p className="text-on-primary-container/80 text-xl max-w-2xl mx-auto">
                Deploy Sentinel AI in under 48 hours with our seamless API integration.
              </p>
              <div className="flex flex-col sm:flex-row justify-center gap-4 pt-6">
                <Link href="/dashboard" className="bg-on-primary-container text-primary px-10 py-4 rounded-2xl font-headline font-bold text-lg hover:scale-105 transition-transform inline-block">Get Started Now</Link>
                <button className="border border-on-primary-container/30 text-on-primary-container px-10 py-4 rounded-2xl font-headline font-bold text-lg hover:bg-white/10 transition-colors">Book a Demo</button>
              </div>
            </div>
            {/* Abstract Glow */}
            <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-white/10 blur-[100px] -translate-y-1/2 translate-x-1/2 rounded-full"></div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-slate-50 w-full py-12 px-8 border-t border-slate-200/50 mt-20">
        <div className="flex flex-col md:flex-row justify-between items-center max-w-7xl mx-auto gap-8">
          <div className="space-y-4 text-center md:text-left">
            <div className="text-lg font-black text-slate-900 font-headline">SENTINEL AI</div>
            <p className="text-slate-500 font-medium font-body text-xs uppercase tracking-widest">© 2024 Sentinel AI. Institutional Risk Intelligence.</p>
          </div>
          <div className="flex flex-wrap justify-center gap-8">
            <Link className="text-slate-500 hover:text-blue-500 transition-colors font-label text-xs font-medium uppercase tracking-widest" href="#">Privacy Policy</Link>
            <Link className="text-slate-500 hover:text-blue-500 transition-colors font-label text-xs font-medium uppercase tracking-widest" href="#">Terms of Service</Link>
            <Link className="text-slate-500 hover:text-blue-500 transition-colors font-label text-xs font-medium uppercase tracking-widest" href="#">Security</Link>
            <Link className="text-slate-500 hover:text-blue-500 transition-colors font-label text-xs font-medium uppercase tracking-widest" href="#">API Documentation</Link>
          </div>
          <div className="flex gap-4">
            <div className="w-10 h-10 rounded-full bg-slate-200/50 flex items-center justify-center hover:bg-primary/10 hover:text-primary transition-all cursor-pointer">
              <span className="material-symbols-outlined text-xl">share</span>
            </div>
            <div className="w-10 h-10 rounded-full bg-slate-200/50 flex items-center justify-center hover:bg-primary/10 hover:text-primary transition-all cursor-pointer">
              <span className="material-symbols-outlined text-xl">database</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}