import React from 'react';
import { AlertTriangle, UserCheck } from 'lucide-react';

export default function AlertsPanel({ anomalies }) {
  return (
    <div className="card p-5 flex flex-col gap-4">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle size={14} className="text-amber-400" />
            <span className="font-display text-[12px] font-semibold text-white uppercase tracking-widest">
              Incident Feed
            </span>
          </div>
          {anomalies.length > 0 && (
            <span className="badge badge-red">{anomalies.length} active</span>
          )}
        </div>
        <p className="text-slate-600 text-[10px] mt-0.5">
          Queue bottlenecks, crowd spikes, and operational anomalies.
        </p>
      </div>

      {/* List */}
      <div className="space-y-2 overflow-y-auto max-h-60 pr-0.5">
        {anomalies.length > 0 ? (
          anomalies.map((a, idx) => {
            const isCrit = a.severity === 'CRITICAL';
            return (
              <div
                key={a.anomaly_id || idx}
                className={`rounded-xl p-3.5 border animate-fade-in-up ${
                  isCrit
                    ? 'bg-rose-950/10 border-rose-500/20'
                    : 'bg-amber-950/8 border-amber-500/15'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className={`badge ${isCrit ? 'badge-red' : 'badge-yellow'}`} style={{ fontSize: '8px' }}>
                    {a.severity}
                  </span>
                  <span className="text-slate-600 text-[9px] font-mono">{a.anomaly_type}</span>
                </div>
                <p className="text-slate-200 text-[11px] font-semibold leading-snug">{a.description}</p>
                {a.suggested_action && (
                  <p className="text-slate-500 text-[10px] mt-2 pl-2 border-l border-slate-700 leading-relaxed">
                    <span className="text-slate-400 font-semibold">Action: </span>
                    {a.suggested_action}
                  </p>
                )}
              </div>
            );
          })
        ) : (
          <div className="py-10 flex flex-col items-center justify-center text-center border border-dashed border-white/[0.05] rounded-xl">
            <UserCheck size={22} className="text-emerald-500/30 mb-2 animate-pulse" />
            <p className="text-slate-400 text-[11px] font-semibold">All Clear</p>
            <p className="text-slate-700 text-[10px] mt-0.5">No incidents detected</p>
          </div>
        )}
      </div>

      <p className="text-slate-700 text-[10px] font-mono pt-3 border-t border-white/[0.04]">
        Threat matrix online · auto-refresh every 8s
      </p>
    </div>
  );
}
