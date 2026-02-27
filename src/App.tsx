import { useState, useEffect, useRef } from 'react';
import './index.css';

// ═════════════════════════════════════════════════════════════════
// Types
// ═════════════════════════════════════════════════════════════════

const API = 'http://127.0.0.1:9876';
const WS_URL = 'ws://127.0.0.1:9877';

type Page = 'clicker' | 'agent' | 'settings' | 'debug';

interface ScannerStatus {
  running: boolean; paused: boolean; clicks_total: number;
  detected_profile: string; detected_window: string | null;
  scan_region: number[] | null; last_click_types: Record<string, number>;
  last_click_ago: number | null; kill_switch: boolean;
  smart_pause: boolean; focus_paused: boolean;
}
interface AgentStatus {
  running: boolean; state: string; mode: string; task: string;
  step_count: number; errors: number; recoveries: number;
  elapsed_seconds: number; smart_pause_enabled: boolean;
  workspace_root: string | null;
  llm: { provider: string; provider_name: string; model: string;
    available: boolean; has_key: boolean; total_tokens: number;
    session_cost_usd: number; };
}
interface ChatMsg { role: string; msg: string; time: string; }
interface LogEntry { time: string; msg: string; tag: string; }

// ═════════════════════════════════════════════════════════════════
// Helpers
// ═════════════════════════════════════════════════════════════════

const api = async (path: string, method = 'GET', body?: any) => {
  const opts: RequestInit = { method };
  if (body) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(body); }
  const r = await fetch(`${API}${path}`, opts);
  return r.json();
};

// ═════════════════════════════════════════════════════════════════
// App
// ═════════════════════════════════════════════════════════════════

export default function App() {
  const [page, setPage] = useState<Page>('clicker');
  const [scanner, setScanner] = useState<ScannerStatus | null>(null);
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [connected, setConnected] = useState(false);
  const [killActive, setKillActive] = useState(false);
  const [notification, setNotification] = useState('');
  const [changedFiles, setChangedFiles] = useState<string[]>([]);
  const [showRestartModal, setShowRestartModal] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pollPausedUntil = useRef(0); // Suppress polling after button press

  // ── WebSocket connection ──────────────────────────────────────
  useEffect(() => {
    let ws: WebSocket;
    let retryTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => { setConnected(true); };
      ws.onclose = () => { setConnected(false); retryTimer = setTimeout(connect, 3000); };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'log') {
            setLogs(prev => [...prev.slice(-200), { time: data.time, msg: data.msg, tag: data.tag }]);
          } else if (data.type === 'chat') {
            setChat(prev => [...prev, { role: data.role, msg: data.msg, time: data.time }]);
          } else if (data.type === 'event') {
            if (data.type === 'kill_switch') setKillActive(data.data?.active || false);
            if (['agent_stop', 'agent_complete'].includes(data.type)) {
              showNotification('Agent completed task');
            }
          }
        } catch { }
      };
      wsRef.current = ws;
    };
    connect();
    return () => { ws?.close(); clearTimeout(retryTimer); };
  }, []);

  // ── HTTP Polling fallback (for when WS isn't available) ───────
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const [s, a] = await Promise.all([
          api('/api/scanner/status'),
          api('/api/agent/status'),
        ]);
        // Skip scanner update if we just pressed a button (prevents flicker)
        if (Date.now() < pollPausedUntil.current) {
          setAgent(a);
        } else {
          setScanner(s); setAgent(a);
          setKillActive(s.kill_switch);
        }
      } catch { }
    }, 800);
    return () => clearInterval(poll);
  }, []);

  // Load initial chat/logs
  useEffect(() => {
    api('/api/logs').then(d => setLogs(d.logs || [])).catch(() => {});
    api('/api/agent/messages').then(d => setChat(d.messages || [])).catch(() => {});
  }, []);

  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(''), 4000);
  };

  // ── Kill switch ───────────────────────────────────────────────
  const toggleKillSwitch = async () => {
    if (killActive) {
      await api('/api/killswitch/deactivate', 'POST');
      setKillActive(false);
      showNotification('Kill switch deactivated');
    } else {
      await api('/api/killswitch/activate', 'POST');
      setKillActive(true);
      showNotification('🛑 KILL SWITCH ACTIVATED');
    }
  };

  // Listen for Tauri kill-switch event
  useEffect(() => {
    try {
      // @ts-ignore
      if (window.__TAURI__) {
        // @ts-ignore
        window.__TAURI__.event.listen('kill-switch', () => {
          setKillActive(true);
          showNotification('🛑 F12 KILL SWITCH ACTIVATED');
        });
      }
    } catch { }
  }, []);

  // ── File change detection ──────────────────────────────────────
  useEffect(() => {
    const checkFiles = setInterval(async () => {
      try {
        const r = await api('/api/system/file-changes');
        setChangedFiles(r.changed || []);
      } catch { }
    }, 10000);
    return () => clearInterval(checkFiles);
  }, []);

  const doRestart = async () => {
    setShowRestartModal(false);
    showNotification('🔄 Restarting backend...');
    try { await api('/api/system/restart', 'POST'); } catch { }
    // Wait for restart then reconnect
    setTimeout(() => window.location.reload(), 3000);
  };

  return (
    <div className="app" data-kill={killActive}>
      {/* Kill Switch Banner */}
      {killActive && (
        <div className="kill-banner" onClick={toggleKillSwitch}>
          🛑 KILL SWITCH ACTIVE — All operations stopped. Click to deactivate.
        </div>
      )}

      {/* Toast Notification */}
      {notification && <div className="toast">{notification}</div>}

      {/* Update Detected Banner */}
      {changedFiles.length > 0 && (
        <div className="update-banner" onClick={() => setShowRestartModal(true)}>
          🔄 Update detected: {changedFiles.slice(0, 3).join(', ')}
          {changedFiles.length > 3 && ` +${changedFiles.length - 3} more`}
          — Click to restart
        </div>
      )}

      {/* Restart Confirmation Modal */}
      {showRestartModal && (
        <div className="modal-overlay" onClick={() => setShowRestartModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>🔄 Restart Backend?</h2>
            {changedFiles.length > 0 ? (
              <>
                <p>The following files have changed since startup:</p>
                <ul className="change-list">
                  {changedFiles.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
                <p>Restart to apply changes?</p>
              </>
            ) : (
              <p>This will restart the Python backend. The scanner and agent will be stopped.</p>
            )}
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setShowRestartModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={doRestart}>🔄 Restart Now</button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar */}
      <nav className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-icon">⚡</span>
          <span className="brand-text">Antigravity</span>
          <span className={`ws-dot ${connected ? 'on' : 'off'}`} title={connected ? 'WebSocket connected' : 'Polling mode'} />
        </div>

        {(['clicker', 'agent', 'settings', 'debug'] as Page[]).map(p => (
          <button key={p} className={`nav-btn ${page === p ? 'active' : ''}`} onClick={() => setPage(p)}>
            {{ clicker: '🖱️', agent: '🤖', settings: '⚙️', debug: '🐛' }[p]}
            <span>{p.charAt(0).toUpperCase() + p.slice(1)}</span>
          </button>
        ))}

        <div className="sidebar-footer">
          <button className={`kill-btn ${killActive ? 'active' : ''}`} onClick={toggleKillSwitch}
            title="F12 — Emergency stop all operations">
            {killActive ? '🟢 Resume' : '🛑 Kill All'}
          </button>
          <button className="kill-btn" style={{ borderColor: 'var(--blue)', color: 'var(--blue)', background: 'rgba(61,157,255,0.12)' }}
            onClick={() => setShowRestartModal(true)} title="Restart the Python backend">
            🔄 Restart
          </button>
          <div className="sidebar-status">
            {scanner?.running ? '🟢 Scanning' : '⚫ Idle'}
            {agent?.running && <span> · 🤖 {agent.state}</span>}
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="content">
        {page === 'clicker' && <ClickerPage scanner={scanner} setScanner={setScanner} killActive={killActive} showNotification={showNotification} pollPausedUntil={pollPausedUntil} />}
        {page === 'agent' && <AgentPage agent={agent} chat={chat} killActive={killActive} showNotification={showNotification} />}
        {page === 'settings' && <SettingsPage showNotification={showNotification} />}
        {page === 'debug' && <DebugPage logs={logs} />}
      </main>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════
// Clicker Page
// ═════════════════════════════════════════════════════════════════

function ClickerPage({ scanner, setScanner, killActive, showNotification, pollPausedUntil }: {
  scanner: ScannerStatus | null; setScanner: React.Dispatch<React.SetStateAction<ScannerStatus | null>>;
  killActive: boolean; showNotification: (m: string) => void;
  pollPausedUntil: React.MutableRefObject<number>;
}) {
  const [previewVisible, setPreviewVisible] = useState(false);

  const toggleScanner = async () => {
    if (killActive) { showNotification('Kill switch is active'); return; }
    // Suppress polling so it doesn't fight with our update
    pollPausedUntil.current = Date.now() + 2000;
    try {
      if (scanner?.running) {
        await api('/api/scanner/stop', 'POST');
      } else {
        await api('/api/scanner/start', 'POST');
      }
      // Immediately fetch the real state after the action completes
      const fresh = await api('/api/scanner/status');
      setScanner(fresh);
    } catch { }
  };

  const togglePause = async () => {
    // Suppress polling so it doesn't fight with our update
    pollPausedUntil.current = Date.now() + 2000;
    await api('/api/scanner/pause', 'POST');
    // Immediately fetch the real state after the action completes
    const fresh = await api('/api/scanner/status');
    setScanner(fresh);
  };

  const toggleSmartPause = async () => {
    await api('/api/smartpause/toggle', 'POST');
    showNotification(`Smart pause ${scanner?.smart_pause ? 'disabled' : 'enabled'}`);
  };

  const formatRegion = (r: number[] | null) => {
    if (!r || r.length < 4) return '-';
    return `(${r[0]},${r[1]}) → (${r[2]},${r[3]})`;
  };

  const formatAgo = (s: number | null) => {
    if (s === null || s === undefined) return 'Never';
    if (s < 60) return `${Math.floor(s)}s ago`;
    return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s ago`;
  };

  return (
    <div className="page">
      <h1>🖱️ Autoclicker Scanner</h1>

      <div className="card-grid">
        <div className="stat-card accent">
          <div className="stat-label">Status</div>
          <div className="stat-value">
            {scanner?.running
              ? (scanner.paused ? '⏸️ Paused' : scanner.focus_paused ? '�️ Focus Hold' : '�🟢 Running')
              : '⚫ Stopped'}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Clicks</div>
          <div className="stat-value">{scanner?.clicks_total ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Last Click</div>
          <div className="stat-value small">{formatAgo(scanner?.last_click_ago ?? null)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Profile</div>
          <div className="stat-value small">{scanner?.detected_profile ?? '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Smart Pause</div>
          <div className="stat-value">{scanner?.smart_pause ? '✅ On' : '❌ Off'}</div>
        </div>
      </div>

      <div className="btn-row">
        <button className={`btn ${scanner?.running ? 'btn-danger' : 'btn-primary'}`} onClick={toggleScanner}>
          {scanner?.running ? '⏹ Stop Scanner' : '▶ Start Scanner'}
        </button>
        {scanner?.running && (
          <button className="btn btn-secondary" onClick={togglePause}>
            {scanner.paused ? '▶ Resume' : '⏸ Pause'}
          </button>
        )}
        <button className={`btn ${scanner?.smart_pause ? 'btn-accent' : 'btn-ghost'}`} onClick={toggleSmartPause}>
          🧠 Smart Pause
        </button>
        <button className={`btn btn-ghost`} onClick={() => setPreviewVisible(v => !v)}>
          👁️ {previewVisible ? 'Hide' : 'Show'} Preview
        </button>
      </div>

      {/* Scanner Readings */}
      {scanner?.running && (
        <div className="settings-section" style={{ marginBottom: 16 }}>
          <h3>📊 Scanner Readings</h3>
          <label>
            <span>Target Window</span>
            <span style={{ color: scanner.detected_window ? 'var(--green)' : 'var(--text-3)', fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {scanner.detected_window ? scanner.detected_window.substring(0, 40) : 'Searching...'}
            </span>
          </label>
          <label>
            <span>Scan Region</span>
            <span style={{ fontSize: 12, fontFamily: 'monospace' }}>{formatRegion(scanner.scan_region)}</span>
          </label>
          <label>
            <span>Focus Paused</span>
            <span>{scanner.focus_paused ? '⏸️ Yes (window focused)' : '▶ No'}</span>
          </label>
          {scanner.last_click_types && Object.keys(scanner.last_click_types).length > 0 && (
            <label>
              <span>Recent Clicks</span>
              <span style={{ fontSize: 12 }}>
                {Object.entries(scanner.last_click_types).map(([type, ago]) =>
                  `${type}: ${formatAgo(ago as number)}`
                ).join(', ')}
              </span>
            </label>
          )}
        </div>
      )}

      {/* Live Scan Preview */}
      {previewVisible && (
        <div className="preview-panel">
          <h3>📷 Live Scan Preview</h3>
          <ScanPreview active={scanner?.running || false} />
        </div>
      )}
    </div>
  );
}

function ScanPreview({ active }: { active: boolean }) {
  const [src, setSrc] = useState('');
  useEffect(() => {
    if (!active) { setSrc(''); return; }
    const interval = setInterval(() => {
      setSrc(`${API}/api/scanner/preview?t=${Date.now()}`);
    }, 500);
    return () => clearInterval(interval);
  }, [active]);

  if (!active) return <div className="preview-placeholder">Scanner is not running</div>;
  return <img className="preview-img" src={src} alt="Scan preview" />;
}

// ═════════════════════════════════════════════════════════════════
// Agent Page
// ═════════════════════════════════════════════════════════════════

function AgentPage({ agent, chat, killActive, showNotification }: {
  agent: AgentStatus | null; chat: ChatMsg[];
  killActive: boolean; showNotification: (m: string) => void;
}) {
  const [task, setTask] = useState('');
  const [mode, setMode] = useState('build');
  const [chatInput, setChatInput] = useState('');
  const [providers, setProviders] = useState<any>({});
  const [provider, setProvider] = useState('ollama');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [workspacePath, setWorkspacePath] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Load providers + models
  useEffect(() => {
    api('/api/llm/providers').then(p => { setProviders(p); }).catch(() => {});
    api('/api/llm/status').then(s => {
      setProvider(s.provider); setModel(s.model);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (provider === 'ollama') {
      api('/api/llm/models').then(d => setModels(d.models || [])).catch(() => {});
    } else if (providers[provider]?.models) {
      setModels(providers[provider].models);
    }
  }, [provider, providers]);

  // Auto-scroll chat
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chat]);

  const startAgent = async () => {
    if (killActive) { showNotification('Kill switch is active'); return; }
    if (!task) { showNotification('Enter a task first'); return; }
    await api('/api/agent/start', 'POST', { task, mode, provider, model });
    showNotification('Agent started');
  };

  const stopAgent = async () => {
    await api('/api/agent/stop', 'POST');
    showNotification('Agent stopped');
  };

  const sendChat = async () => {
    if (!chatInput.trim()) return;
    await api('/api/agent/chat', 'POST', { message: chatInput });
    setChatInput('');
  };

  const switchProvider = async (p: string) => {
    setProvider(p);
    const m = providers[p]?.default_model || '';
    setModel(m);
    await api('/api/llm/switch', 'POST', { provider: p, model: m });
    showNotification(`Switched to ${p}`);
  };

  const scanWorkspace = async () => {
    const path = workspacePath || undefined;
    const result = await api('/api/workspace/scan', 'POST', { path });
    if (result.ok) showNotification(`Scanned: ${result.file_count} files (${result.framework})`);
    else showNotification(result.error || 'Scan failed');
  };

  return (
    <div className="page">
      <h1>🤖 AI Agent</h1>

      {/* LLM Status Bar */}
      <div className="llm-bar">
        <div className="llm-info">
          <span className={`llm-dot ${agent?.llm?.available ? 'on' : 'off'}`} />
          <strong>{agent?.llm?.provider_name || 'Unknown'}</strong>
          <span className="llm-model">{agent?.llm?.modeml}</span>
        </div>
        <div className="llm-stats">
          <span>🪙 {agent?.llm?.total_tokens || 0} tokens</span>
          {(agent?.llm?.session_cost_usd || 0) > 0 && (
            <span>💰 ${agent?.llm?.session_cost_usd?.toFixed(4)}</span>
          )}
        </div>
      </div>

      {/* Provider Selector */}
      <div className="provider-row">
        {Object.entries(providers).map(([key, p]: [string, any]) => (
          <button key={key} className={`provider-btn ${provider === key ? 'active' : ''}`}
            onClick={() => switchProvider(key)}>
            {p.name}
            {p.needs_key && <span className="key-badge">{agent?.llm?.has_key ? '🔑' : '❌'}</span>}
          </button>
        ))}

        <select className="model-select" value={model}
          onChange={e => { setModel(e.target.value); api('/api/llm/switch', 'POST', { provider, model: e.target.value }); }}>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      {/* Agent Controls */}
      <div className="agent-controls">
        <div className="agent-status-bar">
          <span className={`state-badge ${agent?.state || 'idle'}`}>{agent?.state || 'idle'}</span>
          <span>Steps: {agent?.step_count || 0}/{50}</span>
          <span>Errors: {agent?.errors || 0}</span>
          {agent?.elapsed_seconds ? <span>⏱ {Math.floor(agent.elapsed_seconds / 60)}m {agent.elapsed_seconds % 60}s</span> : null}
        </div>

        <div className="task-input-row">
          <select className="mode-select" value={mode} onChange={e => setMode(e.target.value)}>
            <option value="build">🏗️ Build</option>
            <option value="design">🏛️ Design</option>
            <option value="test">🧪 Test</option>
            <option value="refactor">🧹 Refactor</option>
          </select>
          <input className="task-input" placeholder="Describe the task for the agent..."
            value={task} onChange={e => setTask(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !agent?.running && startAgent()} />
          {agent?.running ? (
            <button className="btn btn-danger" onClick={stopAgent}>⏹ Stop</button>
          ) : (
            <button className="btn btn-primary" onClick={startAgent}>▶ Start Agent</button>
          )}
        </div>

        {/* Workspace Scanner */}
        <div className="workspace-row">
          <input className="workspace-input" placeholder="Workspace path (auto-detect if empty)"
            value={workspacePath} onChange={e => setWorkspacePath(e.target.value)} />
          <button className="btn btn-ghost" onClick={scanWorkspace}>📂 Scan Workspace</button>
          {agent?.workspace_root && <span className="workspace-label">📁 {agent.workspace_root}</span>}
        </div>
      </div>

      {/* Chat Panel */}
      <div className="chat-panel">
        <div className="chat-messages">
          {chat.map((msg, i) => (
            <div key={i} className={`chat-msg ${msg.role}`}>
              <span className="msg-role">
                {{ user: '👤', agent: '🤖', system: '⚙️' }[msg.role] || '📝'}
              </span>
              <span className="msg-time">{msg.time}</span>
              <div className="msg-content">{msg.msg}</div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>
        <div className="chat-input-row">
          <input className="chat-input" placeholder="Chat with the agent..."
            value={chatInput} onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendChat()} />
          <button className="btn btn-primary" onClick={sendChat}>Send</button>
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════
// Settings Page
// ═════════════════════════════════════════════════════════════════

function SettingsPage({ showNotification }: { showNotification: (m: string) => void }) {
  const [settings, setSettings] = useState<any>({});
  const [profiles, setProfiles] = useState<any>({});

  useEffect(() => {
    api('/api/settings').then(setSettings).catch(() => {});
    api('/api/profiles').then(setProfiles).catch(() => {});
  }, []);

  const updateSetting = async (key: string, val: any) => {
    const updated = { ...settings, [key]: val };
    setSettings(updated);
    await api('/api/settings', 'POST', { [key]: val });
  };

  const save = async () => {
    await api('/api/settings', 'POST', settings);
    showNotification('Settings saved');
  };

  return (
    <div className="page">
      <h1>⚙️ Settings</h1>

      <div className="settings-grid">
        <div className="settings-section">
          <h3>🖱️ Scanner</h3>
          <label>
            <span>Profile</span>
            <select value={settings.profile || 'antigravity'}
              onChange={e => updateSetting('profile', e.target.value)}>
              {Object.entries(profiles).map(([k, v]: [string, any]) => (
                <option key={k} value={k}>{v.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Scan Interval (ms)</span>
            <input type="number" value={settings.scan_interval_ms ?? 1000}
              onChange={e => updateSetting('scan_interval_ms', Number(e.target.value))} />
          </label>
          <label>
            <span>Min Confidence</span>
            <input type="number" step="0.05" min="0" max="1" value={settings.min_confidence ?? 0.6}
              onChange={e => updateSetting('min_confidence', Number(e.target.value))} />
          </label>
          <label className="toggle-label">
            <span>Smart Pause</span>
            <input type="checkbox" checked={settings.smart_pause_enabled ?? true}
              onChange={e => updateSetting('smart_pause_enabled', e.target.checked)} />
          </label>
          <label className="toggle-label">
            <span>Auto-detect Profile</span>
            <input type="checkbox" checked={settings.auto_profile ?? true}
              onChange={e => updateSetting('auto_profile', e.target.checked)} />
          </label>
        </div>

        <div className="settings-section">
          <h3>🤖 AI Agent</h3>
          <label>
            <span>LLM Provider</span>
            <select value={settings.llm_provider || 'ollama'}
              onChange={e => updateSetting('llm_provider', e.target.value)}>
              <option value="ollama">Ollama (Local)</option>
              <option value="deepseek">DeepSeek</option>
              <option value="kimi">Kimi (Moonshot)</option>
            </select>
          </label>
          <label>
            <span>Model</span>
            <input value={settings.llm_model || settings.agent_model || ''}
              onChange={e => updateSetting('llm_model', e.target.value)} />
          </label>
          <label>
            <span>Max Agent Steps</span>
            <input type="number" value={settings.agent_max_steps ?? 50}
              onChange={e => updateSetting('agent_max_steps', Number(e.target.value))} />
          </label>
        </div>

        <div className="settings-section">
          <h3>⌨️ Hotkeys</h3>
          <div className="hotkey-info">
            <p><kbd>F12</kbd> — Kill switch (stop all operations)</p>
            <p className="muted">Global hotkeys work even when the app is not focused.</p>
          </div>
        </div>

        <div className="settings-section">
          <h3>🔑 API Keys</h3>
          <p className="muted">
            Edit the <code>.env</code> file in the project root to set your API keys.
            Restart the backend after making changes.
          </p>
          <code className="env-hint">
            DEEPSEEK_API_KEY=sk-...<br />
            KIMI_API_KEY=sk-...
          </code>
        </div>
      </div>

      <div className="btn-row">
        <button className="btn btn-primary" onClick={save}>💾 Save Settings</button>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════
// Debug Page
// ═════════════════════════════════════════════════════════════════

function DebugPage({ logs }: {
  logs: LogEntry[];
}) {
  const [sysInfo, setSysInfo] = useState<any>({});
  const [llmStatus, setLlmStatus] = useState<any>({});
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api('/api/system/info').then(setSysInfo).catch(() => {});
    api('/api/llm/status').then(setLlmStatus).catch(() => {});
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="page">
      <h1>🐛 Debug & System Info</h1>

      <div className="card-grid">
        <div className="stat-card">
          <div className="stat-label">Python</div>
          <div className="stat-value small">{sysInfo.python_version?.split(' ')[0] || '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">OCR</div>
          <div className="stat-value">{sysInfo.ocr_available ? '✅' : '❌'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">LLM</div>
          <div className="stat-value small">{llmStatus.provider_name || '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">WebSocket</div>
          <div className="stat-value">:{sysInfo.websocket_port || '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Tokens Used</div>
          <div className="stat-value">{llmStatus.total_tokens || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Session Cost</div>
          <div className="stat-value">${(llmStatus.session_cost_usd || 0).toFixed(4)}</div>
        </div>
      </div>

      <div className="log-panel">
        <div className="log-header">
          <h3>📋 Activity Log</h3>
          <button className="btn btn-ghost btn-sm" onClick={() => api('/api/logs/clear', 'POST')}>Clear</button>
        </div>
        <div className="log-scroll">
          {logs.map((l, i) => (
            <div key={i} className={`log-line tag-${l.tag}`}>
              <span className="log-time">{l.time}</span>
              <span className="log-msg">{l.msg}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}
