import React from 'react';
import { Cpu, AlertTriangle, Sliders } from 'lucide-react';

const STORES = [
  { id: 'STORE_BLR_001', name: 'Bengaluru Flagship', city: 'Bangalore', location: 'Indiranagar' },
  { id: 'STORE_DEL_002', name: 'Delhi NCR Hub',      city: 'New Delhi',  location: 'Connaught Place' },
  { id: 'STORE_MUM_003', name: 'Mumbai Retail Arena', city: 'Mumbai',    location: 'Colaba' },
  { id: 'STORE_HYD_004', name: 'Hyderabad Innovation', city: 'Hyderabad', location: 'Gachibowli' },
  { id: 'STORE_CHN_005', name: 'Chennai Coastline',   city: 'Chennai',   location: 'Nungambakkam' },
];

export { STORES };

export default function Sidebar({ activeStore, setActiveStore, health, injectEvent, triggerQueueSpike, simVisitors }) {
  return (
    <aside className="w-72 shrink-0 flex flex-col bg-[var(--bg-panel)] border-r border-white/[0.04] h-screen sticky top-0 overflow-y-auto">
      
      {/* ── Brand ── */}
      <div className="px-6 pt-7 pb-6 border-b border-white/[0.04]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-700 flex items-center justify-center shadow-lg shadow-blue-900/40 shrink-0">
            <Cpu size={16} className="text-white" />
          </div>
          <div>
            <span className="font-display font-bold text-white tracking-widest text-[11px] uppercase block">
              StoreSense
            </span>
            <span className="label text-blue-500 mt-0.5 block" style={{ fontSize: '9px' }}>
              AI Vision Core v2.0
            </span>
          </div>
        </div>
      </div>

      {/* ── Store Selector ── */}
      <div className="px-4 pt-6">
        <p className="label px-2 mb-3">Monitored Sites</p>
        <nav className="space-y-1">
          {STORES.map(store => (
            <button
              key={store.id}
              onClick={() => setActiveStore(store.id)}
              className={`store-btn ${activeStore === store.id ? 'active' : ''}`}
            >
              <div className="min-w-0">
                <span className={`store-name block text-[12px] font-semibold truncate ${activeStore === store.id ? 'text-white' : 'text-slate-400'}`}>
                  {store.name}
                </span>
                <span className="text-slate-600 text-[10px] block mt-0.5">
                  {store.city} · {store.location}
                </span>
              </div>
              {activeStore === store.id && (
                <span className="status-dot status-dot-blue shrink-0" />
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* ── Sandbox ── */}
      <div className="px-4 pt-6 mt-4 border-t border-white/[0.04]">
        <div className="flex items-center justify-between px-2 mb-3">
          <p className="label flex items-center gap-1.5">
            <Sliders size={11} className="text-blue-500" />
            Sandbox
          </p>
          <span className="badge badge-blue" style={{ fontSize: '8px' }}>Ready</span>
        </div>
        <p className="text-slate-600 text-[10px] leading-relaxed px-2 mb-4">
          Inject synthetic events to test analytical updates in real-time.
        </p>
        <div className="grid grid-cols-2 gap-2">
          <button className="sandbox-btn" onClick={() => injectEvent('ENTRY')}>
            + Visitor
          </button>
          <button className="sandbox-btn" disabled={simVisitors.length === 0} onClick={() => injectEvent('ZONE_ENTER', { zone_id: 'SKINCARE' })}>
            Shop Zone
          </button>
          <button className="sandbox-btn" disabled={simVisitors.length === 0} onClick={() => injectEvent('BILLING_QUEUE_JOIN')}>
            Join Queue
          </button>
          <button className="sandbox-btn" disabled={simVisitors.length === 0} onClick={() => injectEvent('EXIT')}>
            Checkout
          </button>
        </div>
        <button className="sandbox-btn btn-danger w-full mt-2" onClick={triggerQueueSpike}>
          <AlertTriangle size={12} />
          Simulate Queue Spike
        </button>
      </div>

      {/* ── System Status ── */}
      <div className="px-6 py-5 mt-auto border-t border-white/[0.04]">
        <p className="label mb-3">System Status</p>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-500 text-[11px]">Detection Core</span>
            <div className="flex items-center gap-1.5">
              <span className="status-dot status-dot-green" style={{ width: 6, height: 6 }} />
              <span className="text-emerald-400 text-[10px] font-semibold">Online</span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500 text-[11px]">Database</span>
            <div className="flex items-center gap-1.5">
              <span className={`status-dot ${health.db_connected ? 'status-dot-blue' : 'status-dot-red'}`} style={{ width: 6, height: 6 }} />
              <span className={`text-[10px] font-semibold ${health.db_connected ? 'text-blue-400' : 'text-red-400'}`}>
                {health.db_connected ? 'Synced' : 'Offline'}
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500 text-[11px]">API v{health.version || '1.0.0'}</span>
            <span className="text-slate-600 text-[10px]">
              {Math.floor((health.uptime_seconds || 0) / 60)}m uptime
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
