import React from 'react';
import { Users, ShoppingBag, TrendingUp, Clock, TrendingDown, UserCheck } from 'lucide-react';

/* ── helpers ── */
const fmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const formatINR     = v  => (v == null ? '₹0' : fmt.format(v));
const formatPct     = v  => `${(v * 100).toFixed(1)}%`;

/* ── Single metric card ── */
function MetricCard({ accent, icon: Icon, iconColor, label, value, sub, subColor = 'text-slate-500', ring }) {
  return (
    <div className={`card card-lift ${accent} p-5 flex flex-col justify-between h-[120px] relative overflow-hidden group`}>
      {/* Ghost icon watermark */}
      <div className="absolute -right-3 -top-3 opacity-[0.04] group-hover:opacity-[0.07] transition-opacity pointer-events-none">
        <Icon size={72} />
      </div>

      {/* Top row */}
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        <Icon size={14} className={iconColor} />
      </div>

      {/* Value */}
      <div>
        <div className="flex items-end gap-2">
          <span className="metric-value">{value}</span>
          {ring}
        </div>
        <span className={`text-[10px] font-mono mt-1 block ${subColor}`}>{sub}</span>
      </div>
    </div>
  );
}

/* ── SVG ring for conversion rate ── */
function ConversionRing({ rate }) {
  const r = 18, circ = 2 * Math.PI * r;
  const offset = circ - (rate * circ);
  return (
    <div className="relative w-10 h-10 shrink-0 mb-1">
      <svg viewBox="0 0 40 40" className="w-10 h-10 -rotate-90">
        <circle cx="20" cy="20" r={r} stroke="rgba(255,255,255,0.04)" strokeWidth="3" fill="none" />
        <circle
          cx="20" cy="20" r={r}
          stroke="#10b981" strokeWidth="3" fill="none"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.7s ease', filter: 'drop-shadow(0 0 4px rgba(16,185,129,0.5))' }}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-slate-300">
        {(rate * 100).toFixed(0)}%
      </span>
    </div>
  );
}

/* ── Grid ── */
export default function MetricsGrid({ metrics }) {
  const queueAlert = metrics.queue_depth_now > 5;

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <span className="label">Live Metrics</span>
        <span className="h-px flex-1 bg-white/[0.04]" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">

        {/* Visitors */}
        <MetricCard
          accent="card-accent-blue"
          icon={Users} iconColor="text-blue-500"
          label="Active Visitors"
          value={metrics.unique_visitors}
          sub="Excludes staff uniforms"
          subColor="text-blue-500/60"
        />

        {/* Conversion */}
        <MetricCard
          accent="card-accent-green"
          icon={TrendingUp} iconColor="text-emerald-500"
          label="Conversion Rate"
          value={formatPct(metrics.conversion_rate)}
          sub="Target: 25.0%"
          subColor="text-emerald-500/70"
          ring={<ConversionRing rate={metrics.conversion_rate} />}
        />

        {/* Basket */}
        <MetricCard
          accent="card-accent-sky"
          icon={ShoppingBag} iconColor="text-sky-400"
          label="Avg Basket (INR)"
          value={formatINR(metrics.avg_basket_inr)}
          sub="POS integrated"
        />

        {/* Queue */}
        <div className={`card card-lift ${queueAlert ? 'card-accent-rose' : 'card-accent-amber'} p-5 flex flex-col justify-between h-[120px] relative overflow-hidden group`}>
          <div className="absolute -right-3 -top-3 opacity-[0.04] group-hover:opacity-[0.07] transition-opacity pointer-events-none">
            <Clock size={72} />
          </div>
          <div className="flex items-center justify-between">
            <span className="label">Queue Depth</span>
            <div className="flex items-center gap-1.5">
              {queueAlert && <span className="badge badge-red animate-pulse" style={{ fontSize: '8px' }}>Spike</span>}
              <Clock size={14} className={queueAlert ? 'text-rose-500' : 'text-amber-400'} />
            </div>
          </div>
          <div>
            <span className="metric-value">{metrics.queue_depth_now}</span>
            <span className="text-[10px] font-mono mt-1 block text-slate-500">
              {queueAlert ? '⚠ Open new checkout counter' : 'Optimal wait time'}
            </span>
          </div>
        </div>

        {/* Abandonment */}
        <MetricCard
          accent="card-accent-purple"
          icon={TrendingDown} iconColor="text-violet-400"
          label="Abandonment"
          value={formatPct(metrics.abandonment_rate)}
          sub="Shoppers walked out of line"
          subColor="text-violet-400/60"
        />

      </div>
    </section>
  );
}
