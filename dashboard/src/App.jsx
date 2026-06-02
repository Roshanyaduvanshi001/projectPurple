import React, { useState, useEffect, useRef } from 'react';

import Sidebar, { STORES } from './components/Sidebar';
import Header from './components/Header';
import MetricsGrid from './components/MetricsGrid';
import Heatmap from './components/Heatmap';
import FunnelChart from './components/FunnelChart';
import AlertsPanel from './components/AlertsPanel';
import ConsolePanel from './components/ConsolePanel';

/* ─────────────────────────────────────────────────── */
/*  App – state management + data fetching only        */
/* ─────────────────────────────────────────────────── */
export default function App() {
  const [activeStore, setActiveStore] = useState(STORES[0].id);

  const [metrics, setMetrics] = useState({
    store_id: STORES[0].id,
    unique_visitors: 0,
    conversion_rate: 0.0,
    avg_basket_inr: null,
    queue_depth_now: 0,
    abandonment_rate: 0.0,
    zone_dwell: [],
  });
  const [anomalies, setAnomalies] = useState([]);
  const [health, setHealth] = useState({ status: 'ok', version: '1.0.0', uptime_seconds: 0, db_connected: true, stores: [] });
  const [wsStatus, setWsStatus] = useState('connecting');
  const [rawLogs, setRawLogs] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [funnelData, setFunnelData] = useState([]);
  const [heatmapData, setHeatmapData] = useState([]);
  const [selectedZone, setSelectedZone] = useState(null);
  const [currentTime, setCurrentTime] = useState(new Date().toLocaleTimeString());
  const [simVisitors, setSimVisitors] = useState([]);

  const wsRef = useRef(null);
  const reconnectRef = useRef(null);
  const pollingIntervalRef = useRef(null);

  /* ── Clock ── */
  useEffect(() => {
    const t = setInterval(() => setCurrentTime(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(t);
  }, []);

  /* ── Store Switch ── */
  useEffect(() => {
    connectWebSocket();
    fetchStaticData();
    fetchHealthData();
    const hi = setInterval(fetchHealthData, 8000);
    return () => { cleanupConnections(); clearInterval(hi); };
  }, [activeStore]);

  /* ── Helpers ── */
  const addLog = (source, message) =>
    setRawLogs(prev => [{ time: new Date().toLocaleTimeString(), source, message }, ...prev.slice(0, 49)]);

  const clearLogs = () => {
    setRawLogs([]);
    addLog('SYSTEM', 'Log buffer cleared by administrator.');
  };

  const host = () => window.location.hostname;

  /* ── Cleanup ── */
  const cleanupConnections = () => {
    wsRef.current?.close(); wsRef.current = null;
    if (reconnectRef.current) clearTimeout(reconnectRef.current);
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
  };

  /* ── WebSocket ── */
  const connectWebSocket = () => {
    cleanupConnections();
    setWsStatus('connecting');
    const ws = new WebSocket(`ws://${host()}:8000/ws/live/${activeStore}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('connected');
      addLog('SYSTEM', `WebSocket secured for ${activeStore}`);
    };

    ws.onmessage = ({ data }) => {
      try {
        const p = JSON.parse(data);
        if (p.type === 'metrics_update') {
          setMetrics(p.metrics);
          setAnomalies(p.anomalies || []);
          setLastUpdate(new Date(p.ts * 1000));
          addLog('WS_PUSH', `Metrics ingested · visitors: ${p.metrics.unique_visitors}`);
          fetchStaticData();
        }
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      setWsStatus('polling');
      addLog('SYSTEM', 'WebSocket closed — REST fallback active');
      startPolling();
      reconnectRef.current = setTimeout(() => {
        if (wsStatus !== 'connected') connectWebSocket();
      }, 10_000);
    };
  };

  /* ── REST Polling ── */
  const startPolling = () => {
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
    pollOnce();
    pollingIntervalRef.current = setInterval(pollOnce, 5000);
  };

  const pollOnce = async () => {
    try {
      const [metricsRes, anomaliesRes] = await Promise.all([
        request('GET', `/stores/${activeStore}/metrics`),
        request('GET', `/stores/${activeStore}/anomalies`),
      ]);
      setMetrics(metricsRes);
      setAnomalies(anomaliesRes.anomalies || []);
      setLastUpdate(new Date());
      addLog('POLLING', `Metrics polled · visitors: ${metricsRes.unique_visitors}`);
      fetchStaticData();
    } catch {
      setWsStatus('disconnected');
    }
  };

  /* ── Static data (funnel + heatmap) ── */
  const fetchStaticData = async () => {
    try {
      const [funnelRes, heatmapRes] = await Promise.all([
        request('GET', `/stores/${activeStore}/funnel`),
        request('GET', `/stores/${activeStore}/heatmap`),
      ]);
      if (funnelRes) setFunnelData(funnelRes.stages || []);
      if (heatmapRes) setHeatmapData(heatmapRes.zones || []);
    } catch { /* silent */ }
  };

  /* ── Health ── */
  const fetchHealthData = async () => {
    try {
      const healthRes = await request('GET', '/health');
      if (healthRes) setHealth(healthRes);

    } catch { /* silent */ }
  };

  /* ── Event Injection ── */
  const injectEvent = async (eventType, customParams = {}) => {
    let visitorId = customParams.visitor_id;
    if (!visitorId) {
      if (simVisitors.length > 0 && eventType !== 'ENTRY') {
        visitorId = simVisitors[Math.floor(Math.random() * simVisitors.length)];
      } else {
        visitorId = `v_sim_${Math.floor(Math.random() * 9000 + 1000)}`;
        setSimVisitors(prev => [...prev, visitorId]);
      }
    }
    if (eventType === 'EXIT') setSimVisitors(prev => prev.filter(v => v !== visitorId));

    const event = {
      event_id: crypto.randomUUID(),
      store_id: activeStore,
      camera_id: eventType.includes('BILLING') ? 'CAM_BILLING_01'
        : (eventType === 'ENTRY' || eventType === 'EXIT') ? 'CAM_ENTRY_01'
          : 'CAM_FLOOR_01',
      visitor_id: visitorId,
      event_type: eventType,
      timestamp: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      zone_id: customParams.zone_id || (eventType.includes('BILLING') ? 'BILLING' : null),
      dwell_ms: customParams.dwell_ms || 0,
      is_staff: false,
      confidence: 0.99,
      metadata: { session_seq: 0, queue_depth: eventType === 'BILLING_QUEUE_JOIN' ? metrics.queue_depth_now + 1 : null },
    };

    addLog('SANDBOX', `→ ${eventType} for ${visitorId}`);
    try {
      const ingestRes = await request('POST', '/events/ingest', { events: [event] });
      if (ingestRes) { addLog('SANDBOX_RES', `${eventType} accepted ✓`); pollOnce(); }
      else { addLog('SANDBOX_ERR', `Rejected: HTTP ${ingestRes?.status || 'unknown'}`); }
    } catch {
      addLog('SANDBOX_ERR', 'Ingestion endpoint unreachable');
    }
  };

  const triggerQueueSpike = async () => {
    addLog('SANDBOX', 'Simulating rush hour — injecting 6 queue-join events…');
    for (let i = 0; i < 6; i++) {
      await injectEvent('BILLING_QUEUE_JOIN', { visitor_id: `v_spike_${100 + i}` });
      await new Promise(r => setTimeout(r, 150));
    }
  };

  const activeStoreObj = STORES.find(s => s.id === activeStore);

  /* ── Layout ── */
  return (
    <div className="flex w-full h-screen overflow-hidden" style={{ fontFamily: 'var(--font-sans)' }}>

      {/* Sidebar */}
      <Sidebar
        activeStore={activeStore}
        setActiveStore={setActiveStore}
        health={health}
        injectEvent={injectEvent}
        triggerQueueSpike={triggerQueueSpike}
        simVisitors={simVisitors}
      />

      {/* Main content */}
      <div className="flex-1 flex flex-col w-full overflow-hidden">
        <Header
          activeStoreObj={activeStoreObj}
          currentTime={currentTime}
          wsStatus={wsStatus}
          lastUpdate={lastUpdate}
        />

        {/* Scrollable workspace */}
        <main className="flex-1 overflow-y-auto px-6 py-6 lg:px-8 lg:py-7 space-y-7">
          <MetricsGrid metrics={metrics} />

          <Heatmap
            heatmapData={heatmapData}
            selectedZone={selectedZone}
            setSelectedZone={setSelectedZone}
            metrics={metrics}
          />

          {/* Conversion & Incidents Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <FunnelChart funnelData={funnelData} />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2 mb-4">
                <span className="label">Incidents</span>
                <span className="h-px flex-1 bg-white/[0.04]" />
              </div>
              <AlertsPanel anomalies={anomalies} />
            </div>
          </div>

          {/* Bottom row – Console */}
          <section>
            <div className="flex items-center gap-2 mb-4">
              <span className="label">Telemetry Console</span>
              <span className="h-px flex-1 bg-white/[0.04]" />
            </div>
            <ConsolePanel
              rawLogs={rawLogs}
              clearLogs={clearLogs}
              activeStore={activeStore}
            />
          </section>
        </main>
      </div>
    </div>
  );
}
