const { app, BrowserWindow, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const fs   = require('fs');
const path = require('path');
const os   = require('os');

// electron-updater — disponible seulement en mode packagé
let autoUpdater = null;
try {
  autoUpdater = require('electron-updater').autoUpdater;
  autoUpdater.autoDownload = false;     // on demande confirmation avant dl
  autoUpdater.autoInstallOnAppQuit = true;
} catch (_) {}

const APP_VERSION = '4.0.1';
const DATA_DIR    = process.env.ALPHATRADE_DATA_DIR || path.join(os.homedir(), 'AlphaTrade', 'v4.0.0');

let win    = null;
let engine = null;
let engineStarting = false;

/* ── Utilitaires ──────────────────────────────────── */

function ensureDir(d) { fs.mkdirSync(d, { recursive: true }); }

function readJSON(name, fallback = null) {
  try {
    const f = path.join(DATA_DIR, name);
    return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : fallback;
  } catch { return fallback; }
}

function writeJSON(name, data) {
  ensureDir(DATA_DIR);
  try { fs.writeFileSync(path.join(DATA_DIR, name), JSON.stringify(data, null, 2), 'utf8'); }
  catch (e) { console.error(`[writeJSON] ${name}:`, e.message); }
}

/* Traduit les baskets Claude → tableau de trades plat attendu par l'UI Codex */
function flattenBaskets(data) {
  const raw = (data && (data.baskets || data.trades)) || [];
  return raw.map(b => ({
    ticket:     b.basket_id  || b.ticket     || '',
    type:       (b.direction || b.type       || 'BUY').toUpperCase(),
    origin:     b.origin     || 'ALPHATRADE',
    symbol:     b.symbol     || 'XAUUSD',
    lot:        b.lot        || 0.03,
    open_time:  b.created_at || b.open_time  || '',
    close_time: b.closed_at  || b.close_time || '',
    movement:   b.movement   || 0,
    profit:     b.net_pnl    ?? b.profit     ?? 0,
  }));
}

/* Traduit le status.json Claude → format compatible UI Codex.
   Si le moteur a déjà écrit la structure imbriquée, on passe directement. */
function translateStatus(s) {
  if (!s) return {};
  // Le moteur v4 écrit déjà decision/analysis/protection — retour direct
  if (s.decision && s.analysis && s.protection) return s;

  // Fallback pour états sans structure complète (warmup initial, erreur)
  const state   = s.state || 'disconnected';
  const signal  = s.signal || 'WAIT';
  const isWarmup = state === 'warmup';
  return {
    ...s,
    state:         isWarmup ? 'warmup' : state,
    active_symbol: s.symbol || s.active_symbol || 'XAUUSD',
    version:       APP_VERSION,
    decision: {
      signal:     signal,
      confidence: s.confidence || 0,
      eligible:   false,
      reason:     isWarmup ? 'Démarrage du moteur...' : (s.reason || 'En attente'),
    },
    analysis: {
      signal:     signal,
      confidence: s.confidence || 0,
      score_buy:  s.buy_pct   || 0,
      score_sell: s.sell_pct  || 0,
      rsi:        s.rsi       || null,
      ema9:       s.ema9      || null,
      ema21:      s.ema21     || null,
      trend:      s.trend     || 'RANGE',
      fast_signal: signal,
    },
    protection: {
      state:          'INACTIVE',
      session_profit: s.daily_profit || 0,
      peak:           s.peak         || 0,
      floor:          s.floor        || null,
      reason:         '',
    },
    stats: s.stats || {},
  };
}

/* ── Chemins Python ───────────────────────────────── */

function appRoot() {
  return app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');
}

function pythonExe() {
  const root = appRoot();
  const candidates = app.isPackaged
    ? [path.join(root, 'python', 'python-win', 'python.exe')]
    : [
        path.join(root, 'python', 'python-win', 'python.exe'),
        'python'
      ];
  return candidates.find(c => fs.existsSync(c)) || 'python';
}

function engineScript() {
  const root = appRoot();
  const candidates = [
    path.join(root, 'python', 'alphatrade_engine.py'),
    path.join(process.resourcesPath || '', 'python', 'alphatrade_engine.py'),
  ];
  return candidates.find(p => fs.existsSync(p)) || candidates[0];
}

function aiServerScript() {
  const root = appRoot();
  const candidates = [
    path.join(root, 'python', 'alphatrade_ai_server.py'),
    path.join(process.resourcesPath || '', 'python', 'alphatrade_ai_server.py'),
  ];
  return candidates.find(p => fs.existsSync(p)) || candidates[0];
}

let aiServer = null;

function startAIServer() {
  if (aiServer && aiServer.exitCode === null && !aiServer.killed) return;
  const script = aiServerScript();
  if (!fs.existsSync(script)) return;
  const exe = pythonExe();
  const savedParams = readJSON('params.json', {});
  const aiEnv = {
    ...process.env,
    ALPHATRADE_DATA_DIR: DATA_DIR,
    OPENAI_API_KEY:    savedParams.openai_api_key    || process.env.OPENAI_API_KEY    || '',
    ANTHROPIC_API_KEY: savedParams.anthropic_api_key || process.env.ANTHROPIC_API_KEY || '',
  };
  aiServer = spawn(exe, [script, '--port', '8765'], {
    cwd: path.dirname(script),
    windowsHide: true,
    env: aiEnv,
  });
  aiServer.stdout.on('data', d => {
    const lines = d.toString().split(/\r?\n/).filter(Boolean).map(x => `[AI] ${x}`);
    if (lines.length) win?.webContents.send('log-update', lines);
  });
  aiServer.stderr.on('data', d => {
    const lines = d.toString().split(/\r?\n/).filter(Boolean).map(x => `[AI] ${x}`);
    if (lines.length) win?.webContents.send('log-update', lines);
  });
  aiServer.on('exit', () => { aiServer = null; });
}

/* ── Moteur Python ────────────────────────────────── */

function startEngine() {
  if (engineStarting) return;
  if (engine && engine.exitCode === null && !engine.killed) return;
  engineStarting = true;

  const script = engineScript();
  if (!fs.existsSync(script)) {
    win?.webContents.send('log-update', [`[ERREUR] Moteur introuvable: ${script}`]);
    engineStarting = false;
    return;
  }

  const exe = pythonExe();
  engine = spawn(exe, [script], {
    cwd: path.dirname(script),
    windowsHide: true,
    env: {
      ...process.env,
      ALPHATRADE_DATA_DIR: DATA_DIR,
      ALPHATRADE_VERSION:  APP_VERSION,
    }
  });

  engine.stdout.on('data', d => {
    const lines = d.toString().split(/\r?\n/).filter(Boolean);
    if (lines.length) win?.webContents.send('log-update', lines);
  });
  engine.stderr.on('data', d => {
    const lines = d.toString().split(/\r?\n/).filter(Boolean).map(x => `[ENGINE] ${x}`);
    if (lines.length) win?.webContents.send('log-update', lines);
  });
  engine.on('exit', code => {
    win?.webContents.send('log-update', [`[INFO] Moteur arrêté (code ${code})`]);
    win?.webContents.send('status-update', { state: 'disconnected', version: APP_VERSION });
    engine = null;
  });
  engine.on('error', err => {
    win?.webContents.send('log-update', [`[ERREUR] ${err.message}`]);
    engine = null;
  });
  engineStarting = false;
}

function disableTradingOnExit() {
  const state = readJSON('trading_state.json', {}) || {};
  writeJSON('trading_state.json', {
    ...state,
    enabled: false,
    real_confirmed: false,
    reason: 'Application fermée: nouvelles prises de position désactivées.',
    last_error: ''
  });
}

/* ── Fenêtre ──────────────────────────────────────── */

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900,
    minWidth: 860, minHeight: 620,
    frame: false,
    backgroundColor: '#070a12',
    icon: path.join(appRoot(), 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

/* ── Surveillance fichiers data ───────────────────── */

function watchData() {
  let mStatus = 0, mTrades = 0, mLog = 0, mCalendar = 0;

  setInterval(() => {
    const sf = path.join(DATA_DIR, 'status.json');
    if (fs.existsSync(sf)) {
      const m = fs.statSync(sf).mtimeMs;
      if (m !== mStatus) {
        mStatus = m;
        let s = readJSON('status.json', {});
        const now = Math.floor(Date.now() / 1000);
        if (s.timestamp && now - s.timestamp > 8) s.state = 'disconnected';
        win?.webContents.send('status-update', translateStatus(s));
      }
    }

    // trades.json (moteur Codex) — format plat direct
    const tf = path.join(DATA_DIR, 'trades.json');
    if (fs.existsSync(tf)) {
      const m = fs.statSync(tf).mtimeMs;
      if (m !== mTrades) {
        mTrades = m;
        const data = readJSON('trades.json', { trades: [] });
        win?.webContents.send('trades-update', data.trades || []);
      }
    }

    // calendar_data.json — résumés journaliers persistants (infinis)
    const cf = path.join(DATA_DIR, 'calendar_data.json');
    if (fs.existsSync(cf)) {
      const m = fs.statSync(cf).mtimeMs;
      if (m !== mCalendar) {
        mCalendar = m;
        const data = readJSON('calendar_data.json', { daily: {} });
        win?.webContents.send('calendar-data-update', data.daily || {});
      }
    }

    const lf = path.join(DATA_DIR, 'alphatrade.log');
    if (fs.existsSync(lf)) {
      const sz = fs.statSync(lf).size;
      if (sz !== mLog) {
        mLog = sz;
        const lines = fs.readFileSync(lf, 'utf8')
          .split(/\r?\n/).filter(Boolean).slice(-160);
        win?.webContents.send('log-update', lines);
      }
    }
  }, 500);
}

/* ── IPC handlers ─────────────────────────────────── */

// Noms Codex (preload.js copié depuis Codex)
ipcMain.on('window-minimize', () => win?.minimize());
ipcMain.on('window-maximize', () => win?.isMaximized() ? win.unmaximize() : win?.maximize());
ipcMain.on('window-close',    () => app.quit());
ipcMain.on('open-external',   (_, url) => { if (url && url.startsWith('https://')) shell.openExternal(url); });
ipcMain.on('update-download', ()      => { autoUpdater?.downloadUpdate().catch(() => {}); });
ipcMain.on('update-install',  ()      => { autoUpdater?.quitAndInstall(); });

ipcMain.on('alpha-command', (_, msg) => {
  ensureDir(DATA_DIR);
  if (msg.cmd === 'START_MONITOR') startEngine();
  writeJSON('command.json', { command: msg.cmd, payload: msg.payload || {}, timestamp: Date.now() });
  if (msg.cmd === 'STOP_MONITOR') {
    setTimeout(() => {
      try { engine?.kill(); } catch {}
      engine = null;
      win?.webContents.send('status-update', { state: 'disconnected', version: APP_VERSION });
    }, 1500);
  }
});

ipcMain.handle('save-params', (_, p) => {
  const prev = readJSON('params.json', {});
  writeJSON('params.json', p);
  const keysChanged = (prev.openai_api_key !== p.openai_api_key) || (prev.anthropic_api_key !== p.anthropic_api_key);
  if (keysChanged && (p.openai_api_key || p.anthropic_api_key)) {
    try { aiServer?.kill(); } catch {}
    aiServer = null;
    setTimeout(startAIServer, 800);
  }
  return { ok: true, savedAt: Date.now() };
});
ipcMain.handle('load-params',         ()     => readJSON('params.json', null));
ipcMain.handle('save-default-params', (_, p) => { writeJSON('params.defaults.json', p); return { ok: true, savedAt: Date.now() }; });
ipcMain.handle('load-default-params', ()     => readJSON('params.defaults.json', null));

ipcMain.handle('load-snapshot', () => ({
  status: translateStatus(readJSON('status.json', null)),
  trades: readJSON('trades.json', { trades: [] }).trades || [],
  params: readJSON('params.json', null),
  calendarData: readJSON('calendar_data.json', { daily: {} }).daily || {},
}));

/* ── Cycle de vie ─────────────────────────────────── */

app.whenReady().then(() => {
  ensureDir(DATA_DIR);
  disableTradingOnExit();
  writeJSON('command.json', { command: 'NONE', payload: {}, timestamp: 0 });

  const staleStatus = readJSON('status.json', null);
  if (staleStatus?.version && staleStatus.version !== APP_VERSION) {
    try { fs.unlinkSync(path.join(DATA_DIR, 'status.json')); } catch {}
  }

  createWindow();
  watchData();
  startAIServer();
  setTimeout(startEngine, 1200);

  // ── Auto-update (seulement en mode packagé) ────────────────────────────
  if (app.isPackaged && autoUpdater) {
    autoUpdater.on('update-available', info => {
      win?.webContents.send('update-available', {
        version: info.version,
        releaseNotes: info.releaseNotes || '',
      });
    });
    autoUpdater.on('download-progress', progress => {
      win?.webContents.send('update-progress', {
        percent: Math.round(progress.percent || 0),
        transferred: progress.transferred,
        total: progress.total,
      });
    });
    autoUpdater.on('update-downloaded', info => {
      win?.webContents.send('update-downloaded', { version: info.version });
    });
    autoUpdater.on('error', err => {
      win?.webContents.send('log-update', [`[UPDATE] Erreur: ${err.message}`]);
    });
    // Vérification 10s après démarrage, puis toutes les 4h
    setTimeout(() => autoUpdater.checkForUpdates().catch(() => {}), 10000);
    setInterval(() => autoUpdater.checkForUpdates().catch(() => {}), 4 * 3600 * 1000);
  }
});

app.on('window-all-closed', () => {
  disableTradingOnExit();
  if (engine) {
    writeJSON('command.json', { command: 'STOP_MONITOR', timestamp: Date.now() });
    setTimeout(() => { try { engine.kill(); } catch {} }, 500);
  }
  if (aiServer) {
    setTimeout(() => { try { aiServer.kill(); } catch {} }, 300);
  }
  if (process.platform !== 'darwin') app.quit();
});
