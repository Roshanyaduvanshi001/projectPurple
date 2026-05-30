import React from 'react';
import { Terminal, Trash2, Play } from 'lucide-react';

const TAG_CLS = {
  WS_PUSH:     'log-tag-ws',
  SANDBOX:     'log-tag-sandbox',
  SANDBOX_RES: 'log-tag-ok',
  SANDBOX_ERR: 'log-tag-err',
  POLLING:     'log-tag-poll',
  SYSTEM:      'log-tag-sys',
};

export default function ConsolePanel({ rawLogs, clearLogs, activeStore }) {
  return (
    <div className="card p-5 flex flex-col gap-4 lg:col-span-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Terminal size={14} className="text-blue-400" />
            <span className="font-display text-[12px] font-semibold text-white uppercase tracking-widest">
              Telemetry Console
            </span>
          </div>
          <p className="text-slate-600 text-[10px] mt-0.5">
            Real-time packet logs from CCTV trackers and event simulators.
          </p>
        </div>
        <button
          onClick={clearLogs}
          title="Clear buffer"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02]
                     text-slate-500 hover:text-rose-400 hover:border-rose-500/30 hover:bg-rose-500/5
                     text-[10px] font-semibold transition-all"
        >
          <Trash2 size={11} />
          Clear
        </button>
      </div>

      {/* Log output */}
      <div className="console-wrap">
        {rawLogs.length > 0 ? (
          rawLogs.map((log, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2 py-1 border-b border-white/[0.03] hover:bg-white/[0.015] transition-colors"
            >
              <span className="text-slate-700 text-[10px] shrink-0 mt-0.5">[{log.time}]</span>
              <span className={`log-tag ${TAG_CLS[log.source] ?? 'log-tag-sys'} mt-0.5`}>
                {log.source}
              </span>
              <span className="text-slate-300 text-[10px] break-all leading-relaxed">{log.message}</span>
            </div>
          ))
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <Play size={20} className="text-blue-500/15 animate-pulse mb-2" />
            <p className="text-slate-500 text-[11px] font-semibold">Terminal Idle</p>
            <p className="text-slate-700 text-[10px] mt-0.5">Use the Sandbox panel to inject events.</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-3 border-t border-white/[0.04]">
        <span className="text-slate-700 text-[10px] font-mono">
          WS → /ws/live/{activeStore}
        </span>
        <span className="text-slate-700 text-[10px] font-mono">
          {rawLogs.length}/50 entries
        </span>
      </div>
    </div>
  );
}
