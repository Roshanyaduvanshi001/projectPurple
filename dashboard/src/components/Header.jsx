import React from 'react';
import { Radio, WifiOff, Clock } from 'lucide-react';

export default function Header({ activeStoreObj, currentTime, wsStatus, lastUpdate }) {
  const wsConfig = {
    connected:    { label: 'Live Stream',    cls: 'badge-green',  dot: 'status-dot-green'  },
    polling:      { label: 'REST Fallback',  cls: 'badge-yellow', dot: 'status-dot-yellow' },
    connecting:   { label: 'Connecting…',   cls: 'badge-blue',   dot: 'status-dot-blue'   },
    disconnected: { label: 'Disconnected',  cls: 'badge-red',    dot: 'status-dot-red'    },
  }[wsStatus] || { label: wsStatus, cls: 'badge-blue', dot: 'status-dot-blue' };

  return (
    <header className="h-14 shrink-0 px-7 flex items-center justify-between border-b border-white/[0.04] bg-[var(--bg-panel)]/60 backdrop-blur-xl sticky top-0 z-10">
      
      {/* Left – breadcrumb */}
      <div className="flex items-center gap-3">
        <Radio size={14} className="text-blue-500 animate-pulse" />
        <div>
          <span className="font-display font-semibold text-white text-[13px] tracking-wide">
            {activeStoreObj?.name ?? 'Select Store'}
          </span>
          <span className="text-slate-600 text-[11px] ml-2">
            / {activeStoreObj?.city}
          </span>
        </div>
      </div>

      {/* Right – stats + badge */}
      <div className="flex items-center gap-5">
        <div className="hidden md:flex items-center gap-4">
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <Clock size={11} className="text-slate-600" />
            <span className="font-mono text-slate-300">{currentTime}</span>
          </div>
          {lastUpdate && (
            <span className="text-[10px] text-slate-600 hidden lg:block">
              Updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* Connection badge */}
        <div className={`badge ${wsConfig.cls}`}>
          <span className={`status-dot ${wsConfig.dot}`} style={{ width: 6, height: 6 }} />
          {wsConfig.label}
        </div>
      </div>
    </header>
  );
}
