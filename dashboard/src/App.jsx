import React, { useState, useEffect, useRef } from 'react';
import { 
  Users, 
  ShoppingBag, 
  TrendingUp, 
  Clock, 
  AlertTriangle, 
  Activity, 
  Wifi, 
  WifiOff, 
  Database, 
  MapPin, 
  UserCheck, 
  Server, 
  TrendingDown, 
  ChevronRight, 
  Play
} from 'lucide-react';

const STORES = [
  { id: 'STORE_BLR_001', name: 'Bengaluru Flagship', city: 'Bangalore' },
  { id: 'STORE_DEL_002', name: 'Delhi NCR Hub', city: 'New Delhi' },
  { id: 'STORE_MUM_003', name: 'Mumbai Retail Arena', city: 'Mumbai' }
];

export default function App() {
  const [activeStore, setActiveStore] = useState(STORES[0].id);
  const [metrics, setMetrics] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [health, setHealth] = useState(null);
  const [wsStatus, setWsStatus] = useState('connecting'); // 'connected' | 'polling' | 'disconnected'
  const [rawLogs, setRawLogs] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [funnelData, setFunnelData] = useState(null);
  const [heatmapData, setHeatmapData] = useState(null);
  
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const pollingIntervalRef = useRef(null);

  // 1. Establish WebSocket Connection
  useEffect(() => {
    connectWebSocket();
    fetchStaticData(); // Fetch funnel/heatmap static stats on store load
    fetchHealthData();

    // Set up polling for health API regardless
    const healthInterval = setInterval(fetchHealthData, 10000);

    return () => {
      cleanupConnections();
      clearInterval(healthInterval);
    };
  }, [activeStore]);

  const cleanupConnections = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }
  };

  const connectWebSocket = () => {
    cleanupConnections();
    setWsStatus('connecting');
    
    const wsUrl = `ws://${window.location.hostname}:8000/ws/live/${activeStore}`;
    console.log(`Connecting to WebSocket: ${wsUrl}`);
    
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket connection established.');
      setWsStatus('connected');
      addRawLog('SYSTEM', `Connected to live feed for ${activeStore}`);
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'metrics_update') {
          setMetrics(payload.metrics);
          setAnomalies(payload.anomalies || []);
          setLastUpdate(new Date(payload.ts * 1000));
          
          addRawLog('WS_PUSH', `Received live metrics batch | Visitors: ${payload.metrics.unique_visitors} | Queue: ${payload.metrics.queue_depth_now}`);
          
          // Dynamically refresh funnel and heatmap charts
          fetchStaticData();
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    ws.onerror = (err) => {
      console.error('WebSocket encountered an error:', err);
    };

    ws.onclose = () => {
      console.warn('WebSocket connection closed. Transitioning to fallback polling mode...');
      setWsStatus('polling');
      addRawLog('SYSTEM', 'WebSocket disconnected. Falling back to secure HTTP Polling.');
      
      // Start REST Polling fallback immediately
      startPollingFallback();
      
      // Attempt WebSocket reconnect in 10s
      reconnectTimeoutRef.current = setTimeout(() => {
        if (wsStatus !== 'connected') {
          connectWebSocket();
        }
      }, 10000);
    };
  };

  const startPollingFallback = () => {
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
    
    // Immediately fetch once
    fetchPollingData();
    
    pollingIntervalRef.current = setInterval(fetchPollingData, 5000);
  };

  const fetchPollingData = async () => {
    const host = window.location.hostname;
    try {
      // Fetch Metrics
      const resMetrics = await fetch(`http://${host}:8000/stores/${activeStore}/metrics`);
      if (resMetrics.ok) {
        const data = await resMetrics.json();
        setMetrics(data);
        setLastUpdate(new Date());
        addRawLog('POLLING', `Polled REST metrics | Visitors: ${data.unique_visitors}`);
      }
      
      // Fetch Anomalies
      const resAnomalies = await fetch(`http://${host}:8000/stores/${activeStore}/anomalies`);
      if (resAnomalies.ok) {
        const data = await resAnomalies.json();
        setAnomalies(data.anomalies || []);
      }
      
      fetchStaticData();
    } catch (err) {
      console.error('HTTP Polling failed:', err);
      setWsStatus('disconnected');
    }
  };

  const fetchStaticData = async () => {
    const host = window.location.hostname;
    try {
      const resFunnel = await fetch(`http://${host}:8000/stores/${activeStore}/funnel`);
      if (resFunnel.ok) {
        const data = await resFunnel.json();
        setFunnelData(data.stages);
      }
      
      const resHeatmap = await fetch(`http://${host}:8000/stores/${activeStore}/heatmap`);
      if (resHeatmap.ok) {
        const data = await resHeatmap.json();
        setHeatmapData(data.zones);
      }
    } catch (err) {
      console.error('Failed to fetch funnel/heatmap static data:', err);
    }
  };

  const fetchHealthData = async () => {
    const host = window.location.hostname;
    try {
      const res = await fetch(`http://${host}:8000/health`);
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch (err) {
      console.error('Failed to fetch health check metrics:', err);
    }
  };

  const addRawLog = (source, message) => {
    const timeStr = new Date().toLocaleTimeString();
    setRawLogs(prev => [
      { time: timeStr, source, message },
      ...prev.slice(0, 49) // Keep last 50 logs
    ]);
  };

  // Helper formatting values
  const formatCurrency = (val) => {
    if (val === null || val === undefined) return '₹0.00';
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(val);
  };

  const formatPercent = (val) => {
    return `${(val * 100).toFixed(1)}%`;
  };

  const formatDwellTime = (ms) => {
    if (!ms) return '0s';
    const sec = Math.round(ms / 1000);
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  };

  const activeStoreObj = STORES.find(s => s.id === activeStore);

  return (
    <div className="min-h-screen text-slate-100 p-4 lg:p-8">
      {/* ────────────────────────────────────────────────────────────────────────
          Header Panel
          ──────────────────────────────────────────────────────────────────────── */}
      <header className="glass-panel rounded-2xl p-6 mb-6 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-blue-600/20 text-blue-400 rounded-xl border border-blue-500/20">
            <Activity className="w-8 h-8 animate-pulse text-blue-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              Store Intelligence Dashboard
              <span className="text-xs font-semibold py-0.5 px-2 bg-blue-500/20 text-blue-400 rounded-full border border-blue-500/30">
                v1.0.0
              </span>
            </h1>
            <p className="text-sm text-slate-400">
              Live CCTV Video Analytics & Machine Learning Event Stream
            </p>
          </div>
        </div>

        {/* Store Selector & Connection Badge */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Connection Status Badge */}
          <div className="flex items-center gap-2">
            {wsStatus === 'connected' && (
              <span className="flex items-center gap-1.5 py-1 px-3 bg-emerald-500/10 text-emerald-400 text-xs font-medium rounded-lg border border-emerald-500/20">
                <Wifi className="w-4 h-4 pulse-glowing rounded-full p-0.5" />
                Live WebSocket
              </span>
            )}
            {wsStatus === 'polling' && (
              <span className="flex items-center gap-1.5 py-1 px-3 bg-amber-500/10 text-amber-400 text-xs font-medium rounded-lg border border-amber-500/20 animate-pulse">
                <Wifi className="w-4 h-4" />
                HTTP Polling (Fallback)
              </span>
            )}
            {wsStatus === 'connecting' && (
              <span className="flex items-center gap-1.5 py-1 px-3 bg-sky-500/10 text-sky-400 text-xs font-medium rounded-lg border border-sky-500/20 animate-pulse">
                <Server className="w-4 h-4" />
                Connecting...
              </span>
            )}
            {wsStatus === 'disconnected' && (
              <span className="flex items-center gap-1.5 py-1 px-3 bg-rose-500/10 text-rose-400 text-xs font-medium rounded-lg border border-rose-500/20">
                <WifiOff className="w-4 h-4" />
                Offline
              </span>
            )}
          </div>

          {/* Active Store Picker */}
          <div className="flex bg-slate-900/60 p-1 rounded-xl border border-slate-800">
            {STORES.map((store) => (
              <button
                key={store.id}
                onClick={() => setActiveStore(store.id)}
                className={`py-1.5 px-3 rounded-lg text-xs font-medium transition-all ${
                  activeStore === store.id 
                    ? 'bg-blue-600 text-white shadow-md shadow-blue-500/10'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {store.city}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* ────────────────────────────────────────────────────────────────────────
          Key Performance Indicators Grid
          ──────────────────────────────────────────────────────────────────────── */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        
        {/* Card 1: Unique Customer Visitors */}
        <div className="glass-panel rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between h-32 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
            <Users className="w-20 h-20 text-white" />
          </div>
          <div className="flex justify-between items-start">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Total Visitors</span>
            <div className="p-1.5 bg-blue-500/10 text-blue-400 rounded-lg">
              <Users className="w-4 h-4" />
            </div>
          </div>
          <div>
            <h3 className="text-2xl font-bold tracking-tight text-white">
              {metrics ? metrics.unique_visitors : '0'}
            </h3>
            <p className="text-[10px] text-slate-500 flex items-center gap-1 mt-0.5">
              <UserCheck className="w-3 h-3 text-emerald-500" />
              Excludes uniform staff
            </p>
          </div>
        </div>

        {/* Card 2: Conversion Rate */}
        <div className="glass-panel rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between h-32 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
            <TrendingUp className="w-20 h-20 text-white" />
          </div>
          <div className="flex justify-between items-start">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Conversion Rate</span>
            <div className="p-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <div>
            <h3 className="text-2xl font-bold tracking-tight text-white">
              {metrics ? formatPercent(metrics.conversion_rate) : '0.0%'}
            </h3>
            <div className="w-full bg-slate-800 rounded-full h-1.5 mt-2">
              <div 
                className="bg-emerald-500 h-1.5 rounded-full transition-all duration-500" 
                style={{ width: metrics ? `${metrics.conversion_rate * 100}%` : '0%' }}
              ></div>
            </div>
          </div>
        </div>

        {/* Card 3: Avg Basket Value */}
        <div className="glass-panel rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between h-32 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
            <ShoppingBag className="w-20 h-20 text-white" />
          </div>
          <div className="flex justify-between items-start">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Avg Basket Value</span>
            <div className="p-1.5 bg-sky-500/10 text-sky-400 rounded-lg">
              <ShoppingBag className="w-4 h-4" />
            </div>
          </div>
          <div>
            <h3 className="text-2xl font-bold tracking-tight text-white">
              {metrics ? formatCurrency(metrics.avg_basket_inr) : '₹0'}
            </h3>
            <p className="text-[10px] text-slate-500 flex items-center gap-1 mt-0.5">
              Synced with POS systems
            </p>
          </div>
        </div>

        {/* Card 4: Queue Depth Now */}
        <div className={`glass-panel rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between h-32 relative overflow-hidden group ${
          metrics && metrics.queue_depth_now > 5 ? 'border-red-500/40 bg-red-950/10' : ''
        }`}>
          <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
            <Clock className="w-20 h-20 text-white" />
          </div>
          <div className="flex justify-between items-start">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Queue Depth Now</span>
            <div className={`p-1.5 rounded-lg ${
              metrics && metrics.queue_depth_now > 5 ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/10 text-amber-400'
            }`}>
              <Clock className="w-4 h-4" />
            </div>
          </div>
          <div>
            <h3 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              {metrics ? metrics.queue_depth_now : '0'}
              {metrics && metrics.queue_depth_now > 5 && (
                <span className="text-[10px] py-0.5 px-1.5 bg-red-500 text-white rounded font-bold uppercase tracking-wider animate-pulse">
                  Spike
                </span>
              )}
            </h3>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {metrics && metrics.queue_depth_now > 5 ? 'Queue delay > 5 min. Counter bottleneck.' : 'Normal checkout latency'}
            </p>
          </div>
        </div>

        {/* Card 5: Abandonment Rate */}
        <div className="glass-panel rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between h-32 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
            <TrendingDown className="w-20 h-20 text-white" />
          </div>
          <div className="flex justify-between items-start">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Abandonment Rate</span>
            <div className="p-1.5 bg-purple-500/10 text-purple-400 rounded-lg">
              <TrendingDown className="w-4 h-4" />
            </div>
          </div>
          <div>
            <h3 className="text-2xl font-bold tracking-tight text-white">
              {metrics ? formatPercent(metrics.abandonment_rate) : '0.0%'}
            </h3>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Shoppers left without purchasing
            </p>
          </div>
        </div>
      </section>

      {/* ────────────────────────────────────────────────────────────────────────
          Main Analysis Row
          ──────────────────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        
        {/* Store Conversion Funnel Visualizer */}
        <div className="glass-panel rounded-2xl p-6 lg:col-span-2 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Database className="w-5 h-5 text-blue-500" />
                  Store Conversion Funnel
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Flow rates mapping entry to checkouts. Session-deduplicated.
                </p>
              </div>
              {lastUpdate && (
                <span className="text-[10px] text-slate-500">
                  Updated: {lastUpdate.toLocaleTimeString()}
                </span>
              )}
            </div>

            {/* Funnel Stage Render */}
            <div className="space-y-4">
              {funnelData ? (
                funnelData.map((stage, idx) => {
                  // Calculate stage percentage from base stage (index 0)
                  const baseCount = funnelData[0].count;
                  const pctOfBase = baseCount > 0 ? (stage.count / baseCount) * 100 : 0;
                  
                  return (
                    <div key={stage.stage} className="relative">
                      {/* Step Indicator & Metrics */}
                      <div className="flex justify-between items-center mb-1 text-sm">
                        <div className="flex items-center gap-2">
                          <span className="flex items-center justify-center w-5 h-5 text-xs font-bold bg-slate-800 text-slate-300 rounded-full">
                            {idx + 1}
                          </span>
                          <span className="font-semibold text-slate-200">{stage.stage}</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-xs text-slate-400">{stage.count} visitors</span>
                          <span className="text-xs font-bold text-blue-400">{pctOfBase.toFixed(1)}%</span>
                        </div>
                      </div>

                      {/* Bar indicator */}
                      <div className="w-full bg-slate-900 rounded-xl h-7 p-1 border border-slate-800 relative overflow-hidden flex items-center">
                        <div 
                          className={`h-full rounded-lg transition-all duration-700 flex items-center pl-3 ${
                            idx === 0 ? 'bg-gradient-to-r from-blue-600/50 to-blue-500/70 border border-blue-500/30' :
                            idx === 1 ? 'bg-gradient-to-r from-sky-600/50 to-sky-500/70 border border-sky-500/30' :
                            idx === 2 ? 'bg-gradient-to-r from-indigo-600/50 to-indigo-500/70 border border-indigo-500/30' :
                            'bg-gradient-to-r from-emerald-600/50 to-emerald-500/70 border border-emerald-500/30'
                          }`}
                          style={{ width: `${pctOfBase}%`, minWidth: '4%' }}
                        >
                          <span className="text-[10px] text-white font-bold opacity-80 uppercase tracking-wider">
                            {stage.stage}
                          </span>
                        </div>

                        {/* Dropoff Indicator */}
                        {idx > 0 && stage.drop_pct > 0 && (
                          <div className="absolute right-3 text-[10px] font-bold text-rose-400 flex items-center gap-0.5">
                            <TrendingDown className="w-3.5 h-3.5" />
                            Drop: {formatPercent(stage.drop_pct)}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="py-20 text-center text-slate-500">
                  <Activity className="w-8 h-8 animate-spin mx-auto mb-2 opacity-50" />
                  Generating conversion funnel data...
                </div>
              )}
            </div>
          </div>
          
          <div className="mt-4 pt-4 border-t border-slate-800/60 flex items-center justify-between text-xs text-slate-400">
            <span>Source: Camera Entry + Zone Floor triggers</span>
            <span className="flex items-center gap-1 text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
              Live calculations
            </span>
          </div>
        </div>

        {/* Heatmap Visualizer */}
        <div className="glass-panel rounded-2xl p-6 flex flex-col justify-between">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2 mb-1">
              <MapPin className="w-5 h-5 text-emerald-500" />
              Zone Activity Map
            </h2>
            <p className="text-xs text-slate-400 mb-6">
              Visitor density and average dwell times by store zone.
            </p>

            <div className="space-y-3">
              {heatmapData ? (
                heatmapData.map((zone) => {
                  // Classify density score colors
                  const isHot = zone.normalised_score >= 70;
                  const isWarm = zone.normalised_score >= 35 && zone.normalised_score < 70;
                  
                  return (
                    <div 
                      key={zone.zone_id} 
                      className="p-4 bg-slate-900/60 rounded-xl border border-slate-800 flex justify-between items-center hover:bg-slate-900 transition-all"
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-3 h-3 rounded-full ${
                          isHot ? 'bg-red-500 shadow-md shadow-red-500/50' : 
                          isWarm ? 'bg-amber-400 shadow-md shadow-amber-400/50' : 
                          'bg-blue-400 shadow-md shadow-blue-400/50'
                        }`} />
                        <div>
                          <h4 className="text-sm font-semibold text-slate-200">{zone.zone_id}</h4>
                          <span className="text-[10px] text-slate-500 flex items-center gap-1">
                            Avg Dwell: {formatDwellTime(zone.avg_dwell_ms)}
                          </span>
                        </div>
                      </div>

                      <div className="text-right">
                        <span className="text-sm font-bold text-slate-200">{zone.visit_count} visits</span>
                        <div className="w-16 bg-slate-800 rounded-full h-1 mt-1">
                          <div 
                            className={`h-1 rounded-full ${
                              isHot ? 'bg-red-500' : isWarm ? 'bg-amber-400' : 'bg-blue-400'
                            }`}
                            style={{ width: `${zone.normalised_score}%` }}
                          ></div>
                        </div>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="py-14 text-center text-slate-500">
                  <Activity className="w-8 h-8 animate-spin mx-auto mb-2 opacity-50" />
                  Building heatmap logs...
                </div>
              )}
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-slate-800/60 text-[10px] text-slate-500">
            Dwell metrics ignore static/unmoving objects and uniform staff.
          </div>
        </div>
      </div>

      {/* ────────────────────────────────────────────────────────────────────────
          Bottom Row: Live Feed Anomalies & Raw Event Log
          ──────────────────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Real-time Anomalies & Insights */}
        <div className="glass-panel rounded-2xl p-6 lg:col-span-1 flex flex-col justify-between min-h-[350px]">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2 mb-1">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
              Intelligence & Anomalies
            </h2>
            <p className="text-xs text-slate-400 mb-4">
              Real-time warning spikes and retail operational alerts.
            </p>

            <div className="space-y-3 overflow-y-auto max-h-[260px] pr-1">
              {anomalies.length > 0 ? (
                anomalies.map((anom, idx) => (
                  <div 
                    key={anom.anomaly_id || idx} 
                    className={`p-4 rounded-xl border transition-all animate-fade-in ${
                      anom.severity === 'CRITICAL' 
                        ? 'bg-rose-950/20 border-rose-500/30' 
                        : anom.severity === 'WARN' 
                          ? 'bg-amber-950/15 border-amber-500/30' 
                          : 'bg-blue-950/10 border-blue-500/20'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-[9px] py-0.5 px-1.5 rounded font-bold uppercase tracking-wider ${
                        anom.severity === 'CRITICAL' 
                          ? 'bg-rose-600 text-white' 
                          : anom.severity === 'WARN' 
                            ? 'bg-amber-500 text-slate-900' 
                            : 'bg-blue-500 text-white'
                      }`}>
                        {anom.severity}
                      </span>
                      <span className="text-[10px] text-slate-400">
                        {anom.anomaly_type}
                      </span>
                    </div>
                    <h4 className="text-sm font-semibold text-slate-200">{anom.description}</h4>
                    <div className="mt-2 pl-2 border-l border-slate-700 text-[11px] text-slate-400">
                      <span className="text-slate-300 font-medium">Suggestion:</span> {anom.suggested_action}
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-12 border border-dashed border-slate-800 rounded-xl text-center text-slate-500">
                  <Activity className="w-6 h-6 text-emerald-500/40 mx-auto mb-2 animate-pulse" />
                  <p className="text-xs">No active anomalies detected.</p>
                  <p className="text-[10px] text-slate-600 mt-0.5">Continuous threat monitoring active.</p>
                </div>
              )}
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-500">
            <span>Rule Engine: Statistical Outliers</span>
            <span>Uptime: {health ? `${Math.round(health.uptime_seconds)}s` : '0s'}</span>
          </div>
        </div>

        {/* Live Raw Event Stream Ticker */}
        <div className="glass-panel rounded-2xl p-6 lg:col-span-2 flex flex-col justify-between min-h-[350px]">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2 mb-1">
              <Server className="w-5 h-5 text-blue-400" />
              CCTV Event Stream Monitor
            </h2>
            <p className="text-xs text-slate-400 mb-4">
              Real-time feed showing active WebSocket pushes and ingest packets.
            </p>

            <div className="bg-slate-950/80 rounded-xl p-4 font-mono text-[11px] text-slate-300 border border-slate-900 h-[210px] overflow-y-auto flex flex-col-reverse">
              {rawLogs.length > 0 ? (
                rawLogs.map((log, idx) => (
                  <div key={idx} className="py-1 border-b border-slate-900/60 flex items-start gap-2 hover:bg-slate-900/40 px-1 rounded transition-colors">
                    <span className="text-slate-500 shrink-0">[{log.time}]</span>
                    <span className={`px-1.5 rounded text-[9px] font-bold tracking-tight shrink-0 ${
                      log.source === 'WS_PUSH' ? 'bg-blue-900/40 text-blue-300 border border-blue-700/30' :
                      log.source === 'SYSTEM' ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700/30' :
                      log.source === 'POLLING' ? 'bg-amber-900/30 text-amber-300 border border-amber-600/20' :
                      'bg-slate-800 text-slate-400'
                    }`}>
                      {log.source}
                    </span>
                    <span className="text-slate-300 truncate">{log.message}</span>
                  </div>
                ))
              ) : (
                <div className="h-full flex items-center justify-center text-slate-600">
                  <div className="text-center">
                    <Play className="w-6 h-6 mx-auto mb-1 animate-pulse opacity-40" />
                    Waiting for events. Run `simulate.py` to stream live feed.
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-slate-800/60 flex items-center justify-between text-xs text-slate-400">
            <span>WebSocket Channel: /ws/live/{activeStore}</span>
            <span className="text-[10px] text-slate-500 font-mono">
              DB Connected: {health?.db_connected ? 'TRUE' : 'FALSE'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
