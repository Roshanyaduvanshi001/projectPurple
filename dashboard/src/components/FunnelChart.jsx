import React from 'react';
import { TrendingUp, Activity } from 'lucide-react';

const BAR_COLORS = [
  'bg-blue-600',
  'bg-sky-500',
  'bg-indigo-500',
  'bg-violet-500',
  'bg-emerald-500',
];

export default function FunnelChart({ funnelData }) {
  const base = funnelData[0]?.count || 0;

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <span className="label">Conversion Funnel</span>
        <span className="h-px flex-1 bg-white/[0.04]" />
      </div>

      <div className="card p-5">
        <div className="flex items-start justify-between mb-5">
          <div>
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-emerald-500" />
              <span className="font-display text-[12px] font-semibold text-white uppercase tracking-widest">
                Shopper Journey Stages
              </span>
            </div>
            <p className="text-slate-600 text-[10px] mt-0.5">
              Tracks the path from store entry through to completed purchase checkout.
            </p>
          </div>
          {base > 0 && (
            <span className="text-[11px] text-slate-500 font-mono">
              Base: <span className="text-slate-300 font-semibold">{base}</span>
            </span>
          )}
        </div>

        {funnelData.length > 0 ? (
          <div className="space-y-4">
            {funnelData.map((stage, idx) => {
              const pct = base > 0 ? (stage.count / base) * 100 : 0;
              const drop = idx > 0 && base > 0
                ? (((funnelData[idx - 1].count - stage.count) / funnelData[idx - 1].count) * 100).toFixed(1)
                : null;

              return (
                <div key={stage.stage}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${BAR_COLORS[idx % BAR_COLORS.length]}`} />
                      <span className="text-[12px] text-slate-300 font-semibold">{stage.stage}</span>
                      {drop !== null && (
                        <span className="text-[9px] text-rose-400 font-mono">-{drop}%</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-slate-500 text-[11px] font-mono">{stage.count}</span>
                      <span className="font-display font-bold text-white text-[13px] w-12 text-right">
                        {pct.toFixed(0)}%
                      </span>
                    </div>
                  </div>
                  <div className="progress-track">
                    <div
                      className={`progress-fill ${BAR_COLORS[idx % BAR_COLORS.length]}`}
                      style={{ width: `${Math.max(pct, 2)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="py-14 flex flex-col items-center justify-center text-center">
            <Activity size={24} className="text-blue-500/20 animate-spin mb-3" />
            <p className="text-slate-500 text-[12px]">Awaiting funnel data…</p>
            <p className="text-slate-700 text-[10px] mt-1">Inject visitor events using the Sandbox panel to start.</p>
          </div>
        )}

        <p className="text-slate-700 text-[10px] font-mono mt-5 pt-4 border-t border-white/[0.04]">
          Checkout conversion tracked within 5 min of queue entry.
        </p>
      </div>
    </section>
  );
}
