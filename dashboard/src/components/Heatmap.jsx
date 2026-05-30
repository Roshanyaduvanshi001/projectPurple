import React from 'react';
import { Grid, MapPin } from 'lucide-react';

const fmt = ms => {
  if (!ms) return '0s';
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
};

const ZONES = [
  { id: 'ENTRY',    label: 'Entryway',   num: '01', color: 'blue',   span: 'row-span-2' },
  { id: 'SKINCARE', label: 'Skincare',   num: '02', color: 'green',  span: '' },
  { id: 'HAIRCARE', label: 'Haircare',   num: '03', color: 'purple', span: '' },
  { id: 'PHARMACY', label: 'Pharmacy',   num: '04', color: 'sky',    span: '' },
  { id: 'BILLING',  label: 'Checkout',   num: '05', color: 'rose',   span: '' },
];

const DOT_COLOR = {
  blue:   'bg-blue-500',
  green:  'bg-emerald-500',
  purple: 'bg-violet-500',
  sky:    'bg-sky-400',
  rose:   'bg-rose-500',
};

const SELECTED_CLS = {
  blue:   'selected-blue',
  green:  'selected-green',
  purple: 'selected-purple',
  sky:    'selected-sky',
  rose:   'selected-rose',
};

export default function Heatmap({ heatmapData, selectedZone, setSelectedZone, metrics }) {
  const zoneData = id => heatmapData.find(z => z.zone_id === id) || {};

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <span className="label">Floor Intelligence</span>
        <span className="h-px flex-1 bg-white/[0.04]" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* ── Blueprint ── */}
        <div className="card p-5 lg:col-span-2 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Grid size={14} className="text-blue-500" />
                <span className="font-display text-[12px] font-semibold text-white uppercase tracking-widest">
                  Live Floorplan
                </span>
              </div>
              <p className="text-slate-600 text-[10px] mt-0.5">
                Shopper density · zone dwell times · realtime occupancy
              </p>
            </div>
            <div className="badge badge-green">
              <span className="status-dot status-dot-green" style={{ width: 5, height: 5 }} />
              Scanning
            </div>
          </div>

          {/* Zone grid */}
          <div className="bg-[#02040a] rounded-xl border border-white/[0.04] p-4 h-64">
            <div className="grid grid-cols-3 grid-rows-2 gap-3 h-full">
              {ZONES.map(zone => {
                const d = zoneData(zone.id);
                const isSelected = selectedZone === zone.id;
                const isBilling  = zone.id === 'BILLING';
                const count      = isBilling ? metrics.queue_depth_now : (d.visit_count ?? 0);
                const sub        = isBilling
                  ? `Abandon: ${((metrics.abandonment_rate || 0) * 100).toFixed(1)}%`
                  : `Dwell: ${fmt(d.avg_dwell_ms)}`;

                return (
                  <div
                    key={zone.id}
                    onClick={() => setSelectedZone(isSelected ? null : zone.id)}
                    className={`zone-tile ${zone.span} ${isSelected ? SELECTED_CLS[zone.color] : ''}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-slate-600 text-[9px] tracking-widest font-bold">
                        {zone.num} // {zone.id}
                      </span>
                      <span className={`status-dot ${DOT_COLOR[zone.color]} ${isBilling ? 'animate-pulse' : ''}`}
                        style={{ width: 6, height: 6 }} />
                    </div>
                    <div>
                      <span className="font-display text-xl font-bold text-white block">{count}</span>
                      <span className="text-[9px] font-mono text-slate-600 block mt-0.5">{sub}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-4">
            {ZONES.map(z => (
              <span key={z.id} className="flex items-center gap-1.5 text-[10px] text-slate-600 font-mono">
                <span className={`${DOT_COLOR[z.color]} rounded-full`} style={{ width: 6, height: 6, display: 'inline-block' }} />
                {z.label.toUpperCase()}
              </span>
            ))}
          </div>
        </div>

        {/* ── Zone Detail Panel ── */}
        <div className="card p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <MapPin size={14} className="text-violet-400" />
            <span className="font-display text-[12px] font-semibold text-white uppercase tracking-widest">
              Zone Detail
            </span>
          </div>

          {selectedZone ? (() => {
            const zone = ZONES.find(z => z.id === selectedZone);
            const d    = zoneData(selectedZone);
            const isBilling = selectedZone === 'BILLING';
            return (
              <div className="flex flex-col gap-4 animate-fade-in-up">
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.05]`}>
                  <span className={`${DOT_COLOR[zone.color]} rounded-full`} style={{ width: 8, height: 8, display: 'inline-block' }} />
                  <span className="font-display font-semibold text-white text-[13px]">{zone.label}</span>
                </div>

                {[
                  { label: 'Visit Count',   value: isBilling ? metrics.queue_depth_now : (d.visit_count ?? '—') },
                  { label: 'Avg Dwell',     value: isBilling ? '—' : fmt(d.avg_dwell_ms) },
                  { label: 'Max Occupancy', value: d.max_occupancy ?? '—' },
                  { label: 'Abandon Rate',  value: isBilling ? `${((metrics.abandonment_rate||0)*100).toFixed(1)}%` : '—' },
                ].map(row => (
                  <div key={row.label} className="flex items-center justify-between py-2 border-b border-white/[0.04]">
                    <span className="text-slate-500 text-[11px]">{row.label}</span>
                    <span className="font-display font-semibold text-white text-[13px]">{row.value}</span>
                  </div>
                ))}
              </div>
            );
          })() : (
            <div className="flex-1 flex flex-col items-center justify-center text-center">
              <Grid size={28} className="text-slate-800 mb-3" />
              <p className="text-slate-500 text-[12px] font-semibold">Select a zone</p>
              <p className="text-slate-700 text-[10px] mt-1">Click any tile on the floorplan to inspect its metrics.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
