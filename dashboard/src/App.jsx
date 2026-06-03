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

  /* ── Pre-seed dummy data on mount so zone details are never empty ── */
  useEffect(() => {
    loadDummyData(STORES[0].id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

  const loadDummyData = (storeId) => {
    let hash = 0;
    for (let i = 0; i < storeId.length; i++) {
      hash = storeId.charCodeAt(i) + ((hash << 5) - hash);
    }
    const seed = Math.abs(hash);
    
    const visitors = 100 + (seed % 180);
    const browseCount = Math.round(visitors * (0.80 + (seed % 10) / 100));
    const queueCount = Math.round(browseCount * (0.65 + (seed % 15) / 100));
    const purchaseCount = Math.round(queueCount * (0.82 + (seed % 10) / 100));
    
    const conversion = parseFloat((purchaseCount / visitors).toFixed(4));
    const abandonment = parseFloat(((queueCount - purchaseCount) / queueCount).toFixed(4));
    const avgBasket = 1400 + (seed % 1600);
    const queueDepth = Math.max(0, seed % 4);
    
    const dummyMetrics = {
      store_id: storeId,
      window_start: new Date(Date.now() - 3600000).toISOString(),
      window_end: new Date().toISOString(),
      unique_visitors: visitors,
      conversion_rate: conversion,
      avg_basket_inr: avgBasket,
      queue_depth_now: queueDepth,
      abandonment_rate: abandonment,
      zone_dwell: [
        { zone_id: "SKINCARE", avg_dwell_ms: 110000 + (seed % 90000), visit_count: Math.round(browseCount * 0.45) },
        { zone_id: "HAIRCARE", avg_dwell_ms: 95000 + (seed % 75000), visit_count: Math.round(browseCount * 0.35) },
        { zone_id: "PHARMACY", avg_dwell_ms: 70000 + (seed % 50000), visit_count: Math.round(browseCount * 0.20) },
        { zone_id: "BILLING", avg_dwell_ms: 160000 + (seed % 80000), visit_count: queueCount }
      ]
    };

    const dummyFunnel = [
      { stage: "Entry", count: visitors, drop_pct: 0.0 },
      { stage: "Browse Zones", count: browseCount, drop_pct: parseFloat(((visitors - browseCount) / visitors * 100).toFixed(1)) },
      { stage: "Billing Queue", count: queueCount, drop_pct: parseFloat(((browseCount - queueCount) / browseCount * 100).toFixed(1)) },
      { stage: "Purchase Completed", count: purchaseCount, drop_pct: parseFloat(((queueCount - purchaseCount) / queueCount * 100).toFixed(1)) }
    ];

    const dummyHeatmap = [
      { zone_id: "ENTRY",    visit_count: visitors,                         avg_dwell_ms: 8000   + (seed % 6000),  normalised_score: 100, data_confidence: true, max_occupancy: 4  + (seed % 6) },
      { zone_id: "SKINCARE", visit_count: Math.round(browseCount * 0.45),   avg_dwell_ms: 110000 + (seed % 90000), normalised_score: 75,  data_confidence: true, max_occupancy: 8  + (seed % 7) },
      { zone_id: "HAIRCARE", visit_count: Math.round(browseCount * 0.35),   avg_dwell_ms: 95000  + (seed % 75000), normalised_score: 60,  data_confidence: true, max_occupancy: 6  + (seed % 5) },
      { zone_id: "PHARMACY", visit_count: Math.round(browseCount * 0.20),   avg_dwell_ms: 70000  + (seed % 50000), normalised_score: 40,  data_confidence: true, max_occupancy: 3  + (seed % 4) },
      { zone_id: "BILLING",  visit_count: queueCount,                       avg_dwell_ms: 160000 + (seed % 80000), normalised_score: 85,  data_confidence: true, max_occupancy: 12 + (seed % 8) },
    ];

    const dummyAnomalies = (seed % 2 === 0) ? [
      {
        anomaly_id: `dummy_anom_${seed % 100}`,
        anomaly_type: "BILLING_QUEUE_SPIKE",
        severity: "WARN",
        detected_at: new Date(Date.now() - 300000).toISOString(),
        description: `Checkout queue depth exceeded threshold in ${storeId}.`,
        suggested_action: "Open an additional billing register to handle high traffic volume."
      }
    ] : [];

    setMetrics(dummyMetrics);
    setFunnelData(dummyFunnel);
    setHeatmapData(dummyHeatmap);
    setAnomalies(dummyAnomalies);
  };

  const loadDummyHealth = () => {
    setHealth({
      status: 'degraded',
      version: '1.0.0 (offline)',
      uptime_seconds: 3600,
      db_connected: false,
      stores: STORES.map(s => ({
        store_id: s.id,
        last_event_at: new Date().toISOString(),
        lag_seconds: 0,
        stale_feed: false,
        event_count_24h: 300 + (s.id.charCodeAt(6) * 15)
      }))
    });
  };

  const getWsUrl = () => {
    if (import.meta.env.VITE_WS_URL) {
      return import.meta.env.VITE_WS_URL;
    }
    if (import.meta.env.VITE_API_URL) {
      return import.meta.env.VITE_API_URL.replace(/^http/, 'ws');
    }
    const hostname = window.location.hostname || "localhost";
    return `ws://${hostname}:8000`;
  };

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
    const wsBase = getWsUrl().replace(/\/$/, '');
    const ws = new WebSocket(`${wsBase}/ws/live/${activeStore}`);
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
      loadDummyData(activeStore);
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
    } catch {
      loadDummyData(activeStore);
    }
  };

  /* ── Health ── */
  const fetchHealthData = async () => {
    try {
      const healthRes = await request('GET', '/health');
      if (healthRes) setHealth(healthRes);
    } catch {
      loadDummyHealth();
    }
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
      addLog('SANDBOX_ERR', 'Ingestion endpoint unreachable (offline mode)');
      setMetrics(prev => {
        const next = { ...prev };
        if (eventType === 'ENTRY') {
          next.unique_visitors += 1;
        } else if (eventType === 'BILLING_QUEUE_JOIN') {
          next.queue_depth_now += 1;
        } else if (eventType === 'EXIT' || eventType === 'BILLING_QUEUE_ABANDON') {
          if (next.queue_depth_now > 0) next.queue_depth_now -= 1;
        } else if (eventType === 'ZONE_ENTER') {
          const zoneId = customParams.zone_id || 'SKINCARE';
          next.zone_dwell = next.zone_dwell.map(z => 
            z.zone_id === zoneId ? { ...z, visit_count: z.visit_count + 1 } : z
          );
        }
        return next;
      });
      setHeatmapData(prev => prev.map(z => {
        if (eventType === 'ZONE_ENTER' && z.zone_id === (customParams.zone_id || 'SKINCARE')) {
          return { ...z, visit_count: z.visit_count + 1 };
        }
        if ((eventType === 'ENTRY' || eventType === 'REENTRY') && z.zone_id === 'ENTRY') {
          return { ...z, visit_count: z.visit_count + 1 };
        }
        if (eventType === 'BILLING_QUEUE_JOIN' && z.zone_id === 'BILLING') {
          return { ...z, visit_count: z.visit_count + 1 };
        }
        return z;
      }));
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
