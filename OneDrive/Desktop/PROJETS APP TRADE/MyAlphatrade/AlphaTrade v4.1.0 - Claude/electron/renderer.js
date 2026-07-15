const $ = id => document.getElementById(id);
const money = value => `${Number(value || 0) >= 0 ? '+' : '-'}$${Math.abs(Number(value || 0)).toFixed(2)}`;
const plainMoney = value => `$${Number(value || 0).toFixed(2)}`;
const tone = (el, value) => {
  el.classList.remove('positive', 'negative');
  if (Number(value) > 0) el.classList.add('positive');
  if (Number(value) < 0) el.classList.add('negative');
};

let currentStatus = null;
let allTrades = [];
let params = null;
let activeSymbol = 'XAUUSD';
let pendingActiveSymbol = null;
let pendingActiveSymbolAt = 0;
let logLines = [];
let lastLogKey = '';
let lastLogAt = 0;
let repeatedLogCount = 0;
let blockedDecisionKey = '';
let blockedDecisionSince = 0;
let blockedDecisionCount = 0;
let calendarCursor = new Date();
let calendarSelected = null;
let calendarData = {};
let tradeFilter = 'all';
let tradeOriginFilter = 'all';
let currentLanguage = localStorage.getItem('alphatrade-language') || 'fr';

const defaults = {
  mt5_path: 'C:\\Program Files\\MetaTrader 5\\terminal64.exe',
  active_symbol: 'XAUUSD',
  strategy_mode: 'scalping_fast',
  active_engine: 'alphatrade_ai',
  kb1000_candles_per_level: 160,
  kb1000_coherence_min_pct: 60,
  kb1000_min_confirmations: 3,
  kb1000_entry_threshold: 70,
  trade_origins: [
    { name: 'AlphaTrade AI', type: 'INTERNAL_BOT', magic_numbers: [20260607], comment_keywords: ['alphatrade', 'alphakaris'], enabled: true },
    { name: 'AVA Assistant', type: 'EXTERNAL_AI', magic_numbers: [7525001], comment_keywords: ['ava', 'bridge'], enabled: true }
  ],
  mode: 'monitor',
  trading_enabled: false,
  demo_only: false,
  auto_max_positions: 6,
  session_target: 50,
  daily_target: 500,
  session_max_loss: -200,
  giveback: 100,
  profit_protection_enabled: true,
  profit_drawdown_pct: 30,
  profit_drawdown_min: 10,
  profit_warning_ratio: .75,
  risk_pct: 0.35,
  real_lot_cap: 0.20,
  demo_lot_cap: 0.20,
  max_trades_hour: 300,
  cadence_sec: 30,
  max_hold_sec: 45,
  position_review_sec: 120,
  confidence_min: 70,
  anti_top_bottom: true,
  lookback_candles: 200,
  edge_zone_pct: 20,
  min_score_gap: 12,
  reinforcement_enabled: true,
  reinforcement_min_confidence_margin: 5,
  reinforcement_min_score_gap: 8,
  reinforcement_cooldown_sec: 30,
  rebond_enabled: false,
  rebond_cooldown_sec: 60,
  rebond_min_signal_pct: 55,
  rebond_min_zone_strength: 28,
  rebond_stop_pips: 2.00,
  rebond_max_hold_sec: 90,
  rebond_max_active: 3,
  ai_server_enabled: true,
  ai_server_url: 'http://127.0.0.1:8765',
  ai_server_token: '',
  openai_api_key: '',
  anthropic_api_key: '',
  ai_server_trade_confirmation: false,
  ai_sync_interval_sec: 5,
  ai_retrain_interval_min: 360,
  microstructure_enabled: false,
  microstructure_interval_sec: 2,
  hyperliquid_observer_enabled: false,
  hyperliquid_symbols: ['BTC', 'ETH'],
  symbols: {
    XAUUSD: {
      lot: .03, lot_min: .01, lot_max: .20, max_positions: 6,
      max_position_loss: 15, max_floating_loss: 50, timeframe: 'M1',
      confidence_min: 70, cadence_sec: 30, max_trades_hour: 120,
      max_hold_sec: 120, position_review_sec: 120,
      profit_target: 1.5, profit_lock_trigger: 1.0, profit_lock_drawdown: 0.20,
      trail_l1_above: 0.50, trail_l1_pct: 0.20,
      trail_l2_above: 5.00, trail_l2_pct: 0.15,
      trail_l3_above: 10.00, trail_l3_pct: 0.10,
      trail_l4_above: 25.00, trail_l4_pct: 0.07,
      momentum_exit_score: 55,
      emergency_loss_limit: 15, min_positive_exit: .05,
      signal_reversal_margin: 7, cooldown_after_loss_sec: 60,
      session_filter_enabled: false, session_start_utc: 8, session_end_utc: 17, stop_before_end_min: 30,
      lot_multiplicateur_renfort: 1.0, renfort_high_confidence_min: 75,
      lot_multiplicateur_rebond: 3.0
    }
  }
};

const strategyProfiles = {
  scalping_fast: {
    labelFr: 'Scalping rapide', labelEn: 'Fast scalping',
    values: { risk_pct: .35, auto_max_positions: 3, max_trades_hour: 80, cadence_sec: 15, max_hold_sec: 90, confidence_min: 64, session_target: 20 }
  },
  scalping_safe: {
    labelFr: 'Scalping prudent', labelEn: 'Safe scalping',
    values: { risk_pct: .15, auto_max_positions: 1, max_trades_hour: 25, cadence_sec: 45, max_hold_sec: 180, confidence_min: 76, session_target: 10 }
  },
  long_analysis: {
    labelFr: 'Analyse longue', labelEn: 'Long analysis',
    values: { risk_pct: .2, auto_max_positions: 1, max_trades_hour: 12, cadence_sec: 120, max_hold_sec: 900, confidence_min: 74, session_target: 15 }
  },
  combined: {
    labelFr: 'Mode combiné', labelEn: 'Combined mode',
    values: { risk_pct: .25, auto_max_positions: 2, max_trades_hour: 35, cadence_sec: 30, max_hold_sec: 300, confidence_min: 70, session_target: 15 }
  }
};

function updateClock() {
  $('clock').textContent = new Intl.DateTimeFormat(currentLanguage === 'en' ? 'en-CA' : 'fr-CA', {
    weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'
  }).format(new Date());
}

function updateGmtClock() {
  const now = new Date();
  if (!$('gmtHeaderClock')) return;
  $('gmtHeaderClock').textContent = [
    now.getUTCHours(),
    now.getUTCMinutes(),
    now.getUTCSeconds()
  ].map(value => String(value).padStart(2, '0')).join(':');
}
setInterval(updateClock, 1000);
setInterval(updateGmtClock, 1000);
updateClock();
updateGmtClock();

document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
  btn.classList.add('active');
  $(btn.dataset.page).classList.add('active');
}));

function renderTradingView(force = false) {
  const container = $('tradingViewChart');
  if (!container) return;
  if (force) {
    container.dataset.loaded = '';
    container.innerHTML = '';
  }
  if (container.dataset.loaded === 'true') return;
  container.dataset.loaded = 'true';
  const symbol = encodeURIComponent('OANDA:XAUUSD');
  const locale = currentLanguage === 'en' ? 'en' : 'fr';
  container.innerHTML = `<iframe title="TradingView" allowtransparency="true" scrolling="no"
    src="https://s.tradingview.com/widgetembed/?symbol=${symbol}&interval=5&theme=dark&style=1&toolbar_bg=%23070d09&hide_side_toolbar=0&allow_symbol_change=1&save_image=1&locale=${locale}"></iframe>`;
}

function setLanguage(language) {
  currentLanguage = language;
  localStorage.setItem('alphatrade-language', language);
  $('langFr').classList.toggle('active', language === 'fr');
  $('langEn').classList.toggle('active', language === 'en');
  document.documentElement.lang = language;
  const nav = {
    fr: ['Tableau de bord', 'Trades', 'Sessions IA', 'Microstructure', 'Sessions marché', 'Calendrier', 'Paramètres', 'Journal', 'Assistant IA'],
    en: ['Dashboard', 'Trades', 'AI Sessions', 'Microstructure', 'Market Sessions', 'Calendar', 'Settings', 'Journal', 'AI Assistant']
  };
  document.querySelectorAll('.tabs button').forEach((button, index) => {
    button.textContent = nav[language][index];
  });
  const labels = language === 'en'
    ? ['Balance', 'Equity', 'Net profit', 'Floating profit', 'Accuracy', 'Expectancy']
    : ['Solde', 'Équité', 'Profit net', 'Profit flottant', 'Précision', 'Espérance'];
  document.querySelectorAll('.metrics article label').forEach((label, index) => {
    label.textContent = labels[index];
  });
  if (currentStatus) renderStatus(currentStatus);
  document.querySelector('[data-filter="month"]').textContent = language === 'en' ? 'Month' : 'Mois';
  document.querySelector('[data-filter="all"]').textContent = language === 'en' ? 'All' : 'Tous';
  translateStatic(language);
  updateClock();
  renderCurrentMarketSession();
  updateGmtClock();
  renderTradingView(true);
}

const frToEn = {
  'Réalisé MT5': 'MT5 realized',
  'Solde + flottant': 'Balance + floating',
  'Trades fermés': 'Closed trades',
  'Positions ouvertes': 'Open positions',
  'Trades fermés uniquement': 'Closed trades only',
  'Par trade': 'Per trade',
  'Contrôle': 'Control',
  'MT5 connecté': 'MT5 connected',
  'Déconnecté': 'Disconnected',
  'Protection de session': 'Session protection',
  'Session de marché actuelle': 'Current market session',
  'Temps avant fermeture': 'Time before close',
  'Observation IA externe': 'External AI observation',
  'Réalisé': 'Realized',
  'Flottant': 'Floating',
  'Objectif': 'Target',
  'Positions MT5': 'MT5 positions',
  'Aucune position ouverte': 'No open position',
  'Marchés': 'Markets',
  'Marge libre': 'Free margin',
  'Trades récents': 'Recent trades',
  'Analyse en temps réel': 'Real-time analysis',
  "Signal du marché calculé avec RSI, EMA, MACD et la zone récente. Il ne représente pas le volume réel des acheteurs et vendeurs.": 'Market signal calculated with RSI, EMA, MACD and the recent zone. It is not real buyer/seller volume.',
  'Qualité de la stratégie': 'Strategy quality',
  'Mesure la rentabilité: profit factor, gain moyen, perte moyenne et espérance par trade.': 'Measures profitability: profit factor, average win, average loss and expectancy per trade.',
  'Gain moyen': 'Average win',
  'Perte moyenne': 'Average loss',
  'Gagnés / Perdus': 'Wins / Losses',
  'Danger: les pertes moyennes sont trop grandes par rapport aux gains. Nouvelles prises de position bloquées.': 'Danger: average losses are too large compared with wins. New entries locked.',
  'Aucun trade sur cette période': 'No trade in this period',
  'Session AlphaTrade': 'AlphaTrade session',
  'Positions AlphaTrade': 'AlphaTrade positions',
  'Trades AlphaTrade fermés': 'Closed AlphaTrade trades',
  'Par trade AlphaTrade': 'Per AlphaTrade trade',
  'Décision IA': 'AI decision',
  'En attente': 'Waiting',
  'Connexion à MT5 en cours.': 'Connecting to MT5.',
  'Démarrer': 'Start',
  'Arrêter': 'Stop',
  'Protection de session AlphaTrade': 'AlphaTrade session protection',
  'Session courante': 'Current session',
  'Pic': 'Peak',
  'Plancher': 'Floor',
  'Nouvelle session': 'New session',
  'Marchés': 'Markets',
  'Trades MT5 récents': 'Recent MT5 trades',
  'toutes origines': 'all origins',
  'Qualité du compte MT5': 'MT5 account quality',
  'Historique MT5 réel': 'Real MT5 history',
  'Gains': 'Wins',
  'Pertes': 'Losses',
  'Total': 'Total',
  'Sessions IA et apprentissage contrôlé': 'AI sessions and controlled learning',
  'Serveur IA': 'AI server',
  'Connexion': 'Connection',
  'Adresse': 'Address',
  'Dernière synchronisation': 'Last synchronization',
  'Modèle XAU/USD': 'XAU/USD model',
  'Serveur': 'Server',
  'Version active': 'Active version',
  'Échantillon': 'Sample',
  'Score chronologique': 'Time-series score',
  'Signal observé': 'Observed signal',
  'Serveur IA - observation': 'AI server - observation',
  'Mode stratégie': 'Strategy mode',
  'Scalping rapide': 'Fast scalping',
  'Scalping prudent': 'Safe scalping',
  'Analyse longue': 'Long analysis',
  'Mode combiné': 'Combined mode',
  "Activer le serveur d'apprentissage": 'Enable learning server',
  'Adresse du serveur': 'Server address',
  'Synchronisation (s)': 'Synchronization (s)',
  'Réentraînement (min)': 'Retraining (min)',
  'Observation uniquement': 'Observation only',
  'Apprendre sans contourner les limites': 'Learn without bypassing limits',
  'Évaluation AlphaTrade': 'AlphaTrade evaluation',
  'Évaluation manuelle': 'Manual evaluation',
  'Note indicative': 'Indicative score',
  'Profit net': 'Net profit',
  'Gain / perte moyens': 'Average win / loss',
  'Échantillon appris': 'Learned sample',
  'Seuil adapté': 'Adapted threshold',
  'MAE / MFE moyens': 'Average MAE / MFE',
  'Garde-fous': 'Guardrails',
  'Réinitialiser la mémoire IA': 'Reset AI memory',
  'Performance cumulée par session GMT': 'Cumulative performance by GMT session',
  'Résumé de la journée': 'Daily summary',
  'Aujourd’hui': 'Today',
  'Connexion et profil actif': 'Connection and active profile',
  'Symbole actif': 'Active symbol',
  'Filtre de marché': 'Market filter',
  'Éviter achat au sommet / vente au creux': 'Avoid buying tops / selling bottoms',
  'Bougies analysées': 'Analyzed candles',
  'Zone de bord %': 'Edge zone %',
  'Écart BUY/SELL minimum': 'Minimum BUY/SELL gap',
  'Profit minimum $': 'Minimum profit $',
  'Apprentissage adaptatif actif': 'Adaptive learning enabled',
  'Risque et session': 'Risk and session',
  'Risque / trade %': 'Risk / trade %',
  'Objectif session $': 'Session target $',
  'Objectif journalier $': 'Daily target $',
  'Perte max session $': 'Maximum session loss $',
  'Lot max compte réel': 'Live account lot cap',
  'Lot max compte démo': 'Demo account lot cap',
  'Positions auto max': 'Maximum automatic positions',
  'Protection du profit active': 'Profit protection enabled',
  'Activation protection $': 'Protection activation $',
  'Recul depuis pic %': 'Drawdown from peak %',
  'Recul minimum $': 'Minimum drawdown $',
  'Délai IA max (s)': 'Maximum AI delay (s)',
  'Lot fixe': 'Fixed lot',
  'Lot minimum': 'Minimum lot',
  'Lot maximum': 'Maximum lot',
  'Positions max': 'Maximum positions',
  'Perte max / position $': 'Maximum loss / position $',
  'Flottant max $': 'Maximum floating loss $',
  'Seuil confiance %': 'Confidence threshold %',
  'Cadence min (s)': 'Minimum cadence (s)',
  'Max trades / heure': 'Maximum trades / hour',
  'Cible profit $': 'Profit target $',
  'Verrou profit dès $': 'Lock profit from $',
  'Recul du verrou $': 'Profit lock drawdown $',
  'Délai de réanalyse (s)': 'Position review delay (s)',
  'Protection catastrophe $': 'Catastrophic protection $',
  'Profit min. sortie $': 'Minimum exit profit $',
  'Pause après perte (s)': 'Pause after loss (s)',
  'Londres uniquement': 'London only',
  'Filtrer les horaires': 'Filter trading hours',
  'Ouverture UTC': 'UTC opening',
  'Fermeture UTC': 'UTC closing',
  'Stop avant fin (min)': 'Stop before close (min)',
  'Sauvegarder les paramètres': 'Save settings',
  'Journal AlphaTrade': 'AlphaTrade journal',
  'Assistant IA AlphaTrade': 'AlphaTrade AI assistant',
  'Parlez avec votre copilote de trading': 'Talk with your trading copilot',
  'Posez une question sur les signaux, les positions, les paramètres ou les raisons d’un blocage. Cette première version répond à partir des données locales AlphaTrade.': 'Ask a question about signals, positions, settings or blocking reasons. This first version answers from local AlphaTrade data.',
  'Voix': 'Voice',
  'Demander': 'Ask',
  'Reconnaissance vocale réelle et voix serveur prévues dans une prochaine version. Cette base prépare déjà la section dédiée.': 'Real speech recognition and server voice are planned for a future version. This base already prepares the dedicated section.'
};

function translateStatic(language) {
  const pairs = Object.entries(frToEn);
  const source = language === 'en' ? pairs : pairs.map(([fr, en]) => [en, fr]);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(node => {
    let text = node.nodeValue;
    source.forEach(([from, to]) => {
      text = text.split(from).join(to);
    });
    node.nodeValue = text;
  });
}

$('langFr').addEventListener('click', () => setLanguage('fr'));
$('langEn').addEventListener('click', () => setLanguage('en'));

$('monitorBtn').addEventListener('click', async () => {
  const button = $('monitorBtn');
  button.classList.add('busy');
  button.textContent = currentLanguage === 'en' ? 'Starting...' : 'Démarrage...';
  const resetTimer = setTimeout(() => {
    if (button.classList.contains('busy')) {
      button.classList.remove('busy');
      if (currentStatus) renderStatus(currentStatus);
    }
  }, 6000);
  if (!currentStatus || currentStatus.state !== 'connected') {
    alpha.command('START_MONITOR');
    addLogs(['[INFO] Connexion MT5 demandée. Recliquez sur Démarrer quand le compte est connecté.']);
    return;
  }
  clearTimeout(resetTimer);
  const mode = String(currentStatus.mode || '').toUpperCase();
  let confirmReal = false;
  if (mode === 'REAL') {
    confirmReal = window.confirm('Compte RÉEL détecté. Confirmer le démarrage de l’IA et des prises de position sur ce compte ?');
    if (!confirmReal) {
      button.classList.remove('busy');
      renderStatus(currentStatus);
      return;
    }
  }
  if (params && params.active_symbol !== activeSymbol) {
    params.active_symbol = activeSymbol;
    await alpha.saveParams(params);
  }
  alpha.command('ENABLE_TRADING', { confirm_real: confirmReal, active_symbol: activeSymbol });
});
$('tradeBtn').addEventListener('click', () => {
  const button = $('tradeBtn');
  button.classList.add('busy');
  button.textContent = currentLanguage === 'en' ? 'Pausing...' : 'Pause...';
  alpha.command('DISABLE_TRADING');
});
$('newSessionBtn').addEventListener('click', () => {
  const positions = (currentStatus?.positions || []).filter(position =>
    String(position.origin || '').toUpperCase() === 'BOT'
  );
  if (positions.length) {
    const msg = `${positions.length} position(s) AlphaTrade en cours.\nÊtes-vous sûr de vouloir démarrer une nouvelle session ?`;
    if (!window.confirm(msg)) return;
  }
  alpha.command('NEW_SESSION');
  addLogs(['[INFO] Demande de nouvelle session envoyée.']);
});
$('resetLearningBtn')?.addEventListener('click', () => {
  const message = currentLanguage === 'en'
    ? 'Reset the learned XAUUSD memory? Trading history will remain available.'
    : 'Réinitialiser la mémoire apprise XAUUSD ? L’historique des trades sera conservé.';
  if (!window.confirm(message)) return;
  alpha.command('RESET_LEARNING');
  addLogs([currentLanguage === 'en' ? '[INFO] AI memory reset requested.' : '[INFO] Réinitialisation de la mémoire IA demandée.']);
});

function assistantLine(text, role = 'bot') {
  const chat = $('assistantChat');
  if (!chat) return;
  const message = document.createElement('div');
  message.className = `assistant-message ${role}`;
  message.textContent = text;
  chat.appendChild(message);
  chat.scrollTop = chat.scrollHeight;
}

const ADMIN_ACCESS_PHRASE = 'ALPHATRADE-ADMIN-2026';

const alphaTradeKnowledge = {
  identity:
    "Je suis AlphaTradeIA, l'assistant intégré au projet AlphaTrade. Mon rôle est d'expliquer l'application, les signaux, les paramètres, les protections, l'historique, la logique BUY/SELL, le site web et les prochaines améliorations.",
  project:
    "AlphaTrade Gold est une application de trading assisté par IA connectée à MetaTrader 5, dédiée exclusivement à l'or (XAU/USD). Elle vise à analyser XAU/USD, suivre les positions, protéger les sessions et apprendre progressivement des décisions prises.",
  markets:
    "Le marché tradé est exclusivement XAU/USD (or). L'actif garde ses propres paramètres, horaires, limites et mémoire d'apprentissage.",
  strategy:
    "La logique recherchée n'est pas d'acheter seulement. AlphaTrade doit savoir acheter au creux, vendre au sommet, lire le momentum, les bougies, les zones hautes et basses, puis décider BUY, SELL ou WAIT selon le contexte.",
  candles:
    "L'analyse doit combiner un contexte large, par exemple 200 bougies, avec une fenêtre courte pour le signal immédiat. Les bougies de rejet, mèches longues, retournements, cassures, retests, supports, résistances et order blocks simplifiés font partie de la feuille de route.",
  protections:
    "Les protections servent à limiter les pertes, protéger les gains, suivre l'objectif de session, contrôler le flottant et éviter qu'une décision IA contourne les limites de sécurité définies par l'utilisateur.",
  website:
    "Le site web AlphaTrade est prévu pour présenter le projet, les fonctionnalités, la FAQ, le téléchargement, les licences, les tarifs, l'inscription, la connexion et les moyens de paiement. Les paiements réels nécessiteront des comptes marchands et clés API.",
  pricing:
    "Les offres prévues sont Découverte 1 jour, Débutant 49,99 $, Pro 99,99 $, Custom 499,99 $, puis Élite 999,99 $ à venir pour les services avancés et serveur IA.",
  roadmap:
    "La reconnaissance vocale est déjà intégrée (bouton micro pour poser une question à l'oral). Les prochaines étapes prévues incluent un serveur IA en ligne plus complet, une meilleure lecture des bougies, l'amélioration du BUY/SELL, le site commercial, puis plus tard la licence, le paiement, le support et éventuellement une application mobile.",
  premium:
    "La version premium serveur pourra être réservée aux forfaits élevés, par exemple Custom ou Élite. Elle pourra utiliser une IA plus puissante pour diagnostiquer les refus, expliquer les erreurs, proposer des réglages et assister les correctifs, sous contrôle de l'utilisateur.",
  access:
    "L'assistant avance de diagnostic et de correction sera reserve aux forfaits Custom et Elite. Les forfaits Decouverte, Debutant et Pro auront acces aux informations publiques, a l'aide d'utilisation et aux explications generales.",
  privacy:
    "Les informations personnelles du fondateur, les decisions internes, les donnees confidentielles, les collaborateurs et les strategies non publiques ne doivent pas etre communiques a un utilisateur externe.",
  admin:
    "Mode administrateur local active. Vous pouvez poser des questions internes sur la logique du projet, les decisions produit, les refus de trade, les axes de correction, les forfaits et la feuille de route.",
  risk:
    "Important: AlphaTrade ne garantit pas de profits. Le trading comporte des risques réels. Le mode démo reste recommandé avant toute utilisation sur compte réel."
};

function localAssistantAnswer(question) {
  const s = currentStatus || {};
  const decision = s.simulated_decision || {};
  const analysis = (s.analysis || {})[s.active_symbol || activeSymbol] || {};
  const protection = s.protection || {};
  const positions = (s.positions || []).filter(position => String(position.origin || '').toUpperCase() === 'BOT');
  const q = String(question || '').toLowerCase();
  const has = (...words) => words.some(word => q.includes(word));
  const active = s.active_symbol || activeSymbol;
  const symbolParams = params?.symbols?.[active] || {};
  const state = String(s.state || '').toLowerCase();
  const canTrade = Boolean(params?.trading_enabled || s.trading_enabled || s.trading_allowed || decision.trading_enabled);
  const signal = decision.signal || analysis.signal || 'WAIT';
  const confidence = Number(decision.confidence || analysis.confidence || 0);
  const threshold = Number(analysis.learned_threshold || symbolParams.confidence_min || params?.confidence_min || 62);
  const reasonText = decision.reason || 'aucune raison disponible';
  const openCount = positions.length;
  const maxPositions = Number(symbolParams.max_positions || params?.auto_max_positions || 2);
  const buyScore = Number(analysis.score_buy || 0);
  const sellScore = Number(analysis.score_sell || 0);
  const rsi = analysis.rsi ?? '-';
  const trend = analysis.trend || '-';
  const edge = analysis.edge_position != null ? `${analysis.edge_position}%` : '-';
  const marketSummary = `Actif ${active}. Signal actuel: ${signal} ${confidence.toFixed(1)}% contre seuil ${threshold.toFixed(1)}%. BUY ${buyScore.toFixed(0)}%, SELL ${sellScore.toFixed(0)}%, RSI ${rsi}, tendance ${trend}, zone ${edge}.`;
  const adminMode = q.includes(ADMIN_ACCESS_PHRASE.toLowerCase());
  const privateQuestion = [
    'adresse personnelle', 'adresse privee', 'adresse privée', 'fondateur',
    'collaborateur', 'partenaire', 'revenu personnel', 'document interne',
    'secret', 'code source complet', 'strategie secrete', 'stratégie secrète'
  ].some(keyword => q.includes(keyword));
  if (adminMode) {
    return `${alphaTradeKnowledge.admin} ${alphaTradeKnowledge.privacy}`;
  }
  if (privateQuestion) {
    return `Je ne peux pas communiquer ces informations en mode public. ${alphaTradeKnowledge.privacy} Si vous etes l'administrateur, utilisez la phrase d'acces administrateur configuree localement.`;
  }
  if (!s.state) {
    return "Je ne peux pas encore raisonner sur une prise de position parce que je n'ai pas de donnees MT5 synchronisees. Ouvrez MetaTrader 5, connectez le compte, puis relancez AlphaTrade.";
  }
  if (has('prendre position', 'prends position', 'ouvrir position', 'ouvrir un trade', 'prendre un trade', 'trader le gold', 'marché du gold', 'marche du gold') || (has('capable', 'peux-tu', 'peux tu', 'est-ce que tu peux') && has('gold', 'xau', 'vix', 'position', 'trade', 'marché', 'marche'))) {
    const checks = [];
    if (state !== 'connected') checks.push("MT5 n'est pas encore confirme connecte.");
    if (!canTrade) checks.push("le bouton Demarrer n'autorise pas encore les nouvelles positions.");
    if (signal === 'WAIT') checks.push("le signal est encore WAIT, donc je dois attendre une meilleure confirmation.");
    if (confidence < threshold) checks.push(`la confiance ${confidence.toFixed(1)}% est sous le seuil ${threshold.toFixed(1)}%.`);
    if (openCount >= maxPositions) checks.push(`la limite de positions AlphaTrade est atteinte: ${openCount}/${maxPositions}.`);
    if (protection.state && ['HARD_LOCK', 'TARGET_REACHED', 'WARNING'].includes(String(protection.state))) checks.push(`la protection bloque ou surveille la session: ${protection.reason || protection.state}.`);
    if (!checks.length && ['BUY', 'SELL'].includes(signal)) {
      return `Oui, je suis capable de prendre position sur ${active}. D'apres les donnees actuelles, l'entree possible serait ${signal}, avec ${confidence.toFixed(1)}% de confiance. ${marketSummary} Je ne declenche l'ordre que si Demarrer est actif, que MT5 accepte AutoTrading et que les protections restent ouvertes.`;
    }
    return `Pas encore. Je peux analyser ${active}, mais je ne dois pas ouvrir maintenant pour cette raison: ${checks.join(' ')} ${marketSummary}`;
  }
  if (has('pourquoi', 'bloqu', 'refus', 'refusé', 'refuse', 'corrige', 'corriger', 'réparer', 'reparer')) {
    const suggestions = [];
    const lowerReason = String(reasonText).toLowerCase();
    if (lowerReason.includes('rsi')) suggestions.push("Le RSI est en zone extreme; je dois chercher une confirmation plus forte ou un retournement clair avant d'entrer.");
    if (lowerReason.includes('zone haute') || lowerReason.includes('zone basse') || lowerReason.includes('sommet') || lowerReason.includes('creux')) suggestions.push("Le prix est en bord de zone; la correction logique est de verifier le sens inverse: vendre au sommet ou acheter au creux si les bougies confirment.");
    if (lowerReason.includes('trading algo') || lowerReason.includes('10027')) suggestions.push("MT5 bloque les ordres: activez Trading Algo dans MetaTrader 5.");
    if (lowerReason.includes('session')) suggestions.push("Un filtre horaire bloque l'entree; verifiez le filtre Londres uniquement dans les parametres de l'actif.");
    if (confidence < threshold) suggestions.push(`La confiance doit monter au-dessus de ${threshold.toFixed(1)}% ou le seuil doit etre ajuste avec prudence.`);
    if (!suggestions.length) suggestions.push("Je dois garder le diagnostic local: lire le signal, les protections, les positions et le journal. La correction automatique complete sera pour le module serveur Custom/Elite.");
    return `Diagnostic AlphaTradeIA: ${reasonText}. ${marketSummary} Correction proposee: ${suggestions.join(' ')} Mode actuel: je conseille et j'explique. Mode futur Custom/Elite: je pourrai assister une correction plus avancee via serveur IA.`;
  }
  if (q.includes('qui es') || q.includes('tu es') || q.includes('alphatradeia') || q.includes('assistant')) {
    return `${alphaTradeKnowledge.identity} ${alphaTradeKnowledge.access} ${alphaTradeKnowledge.risk}`;
  }
  if (q.includes('projet') || q.includes('application') || q.includes('alphatrade') || q.includes('objectif')) {
    return `${alphaTradeKnowledge.project} ${alphaTradeKnowledge.roadmap}`;
  }
  if (q.includes('site') || q.includes('web') || q.includes('tarif') || q.includes('prix') || q.includes('forfait') || q.includes('paiement')) {
    return `${alphaTradeKnowledge.website} ${alphaTradeKnowledge.pricing}`;
  }
  if (q.includes('gold') || q.includes('xau') || q.includes('vix') || q.includes('volatility') || q.includes('marché') || q.includes('marche')) {
    return `${alphaTradeKnowledge.markets} ${alphaTradeKnowledge.strategy}`;
  }
  if (q.includes('bougie') || q.includes('candle') || q.includes('order block') || q.includes('support') || q.includes('résistance') || q.includes('resistance')) {
    return alphaTradeKnowledge.candles;
  }
  if (q.includes('amélior') || q.includes('amelior') || q.includes('technologie') || q.includes('serveur') || q.includes('vocal') || q.includes('voix')) {
    return `${alphaTradeKnowledge.roadmap} ${alphaTradeKnowledge.premium} ${alphaTradeKnowledge.access}`;
  }
  if (!s.state) {
    return 'Je n’ai pas encore de données MT5 synchronisées. Ouvrez MetaTrader 5, connectez le compte, puis relancez AlphaTrade.';
  }
  if (q.includes('refus') || q.includes('refusé') || q.includes('refuse') || q.includes('corrige') || q.includes('corriger') || q.includes('réparer') || q.includes('reparer')) {
    const reason = String(decision.reason || '').toLowerCase();
    const suggestions = [];
    if (reason.includes('rsi')) {
      suggestions.push('Le RSI est en zone extrême. Je vérifie si le signal reste fort avec la tendance, la confirmation rapide et l’écart BUY/SELL. Si tout est concordant, la nouvelle logique peut autoriser le trade malgré le RSI.');
    }
    if (reason.includes('zone haute') || reason.includes('zone basse') || reason.includes('sommet') || reason.includes('creux')) {
      suggestions.push('Le prix est en zone extrême. Je dois maintenant réanalyser le sens inverse: vendre au sommet si les bougies montrent un rejet, ou acheter au creux si elles montrent un rebond.');
    }
    if (reason.includes('trading algo') || reason.includes('10027')) {
      suggestions.push('MT5 refuse les ordres parce que Trading Algo est désactivé. Activez le bouton Trading Algo dans MetaTrader 5.');
    }
    if (reason.includes('session')) {
      suggestions.push('La session horaire bloque l’entrée. Vérifiez si le filtre Londres uniquement est activé pour XAU/USD.');
    }
    if (!suggestions.length) {
      suggestions.push('Je peux expliquer le refus avec la raison disponible, mais la correction automatique complète demandera le module serveur AlphaTradeIA.');
    }
    return `Dernier refus: ${decision.reason || 'raison indisponible'}. Correction proposée: ${suggestions.join(' ')} Mode actuel: diagnostic local. Mode futur premium Custom/Élite: correction assistée via serveur IA, avec accès limité aux informations publiques pour les utilisateurs externes.`;
  }
  if (q.includes('position') || q.includes('trade') || q.includes('bloqu') || q.includes('pourquoi')) {
    return `Décision actuelle: ${decision.signal || 'WAIT'} à ${Number(decision.confidence || 0).toFixed(1)}%. Raison: ${decision.reason || 'aucune raison disponible'}. Positions AlphaTrade ouvertes: ${positions.length}.`;
  }
  if (q.includes('rsi') || q.includes('signal') || q.includes('buy') || q.includes('sell')) {
    return `Signal ${analysis.signal || 'WAIT'}: BUY ${Number(analysis.score_buy || 0).toFixed(1)}%, SELL ${Number(analysis.score_sell || 0).toFixed(1)}%, RSI ${analysis.rsi ?? '-'}, tendance ${analysis.trend || '-'}.`;
  }
  if (q.includes('protection') || q.includes('session') || q.includes('objectif')) {
    return `Protection: ${protection.state || 'INACTIVE'}. Profit session: ${money(protection.session_profit || 0)}, pic: ${money(protection.peak || 0)}. ${protection.reason || ''}`;
  }
  if (q.includes('appris') || q.includes('apprentissage') || q.includes('mémoire') || q.includes('memoire')) {
    const learned = ((s.learning || {}).symbols || {})[s.active_symbol || activeSymbol] || {};
    return `Mémoire ${s.active_symbol || activeSymbol}: ${Number(learned.samples || 0)} échantillons, ${Number(learned.wins || 0)} gains, ${Number(learned.losses || 0)} pertes, résultat total ${money(learned.total_profit || 0)}.`;
  }
  return `Je surveille ${s.active_symbol || activeSymbol}. Le dernier signal est ${decision.signal || analysis.signal || 'WAIT'} et la raison principale est: ${decision.reason || 'en attente de données exploitables'}.`;
}

async function assistantAnswer(question) {
  const context = {
    status: currentStatus,
    trades: allTrades.slice(0, 40),
    params
  };
  try {
    const response = await fetch('http://127.0.0.1:8765/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, context })
    });
    const payload = await response.json();
    if (payload?.ok && payload.answer) {
      return payload.answer;
    }
    const fallback = localAssistantAnswer(question);
    return `${fallback}\n\nNote serveur IA: ${payload?.error || 'reponse OpenAI indisponible'}`;
  } catch (error) {
    const fallback = localAssistantAnswer(question);
    return `${fallback}\n\nNote serveur IA: impossible de joindre AlphaTradeIA-DEV (${error.message}).`;
  }
}

$('assistantForm')?.addEventListener('submit', event => {
  event.preventDefault();
  const input = $('assistantQuestion');
  const question = String(input.value || '').trim();
  if (!question) return;
  assistantLine(question, 'user');
  input.value = '';
  assistantLine('Analyse AlphaTradeIA en cours...', 'bot');
  assistantAnswer(question).then(answer => {
    const chat = $('assistantChat');
    const waiting = chat?.lastElementChild;
    if (waiting?.textContent === 'Analyse AlphaTradeIA en cours...') waiting.remove();
    assistantLine(answer, 'bot');
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(answer);
      utterance.lang = currentLanguage === 'en' ? 'en-CA' : 'fr-CA';
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    }
  });
});

// ── Reconnaissance vocale (Web Speech API, native Chromium/Electron) ──────────
const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
let voiceRecognition = null;
let voiceListening = false;

function initVoiceRecognition() {
  if (!SpeechRecognitionCtor || voiceRecognition) return voiceRecognition;
  voiceRecognition = new SpeechRecognitionCtor();
  voiceRecognition.continuous = false;
  voiceRecognition.interimResults = false;
  voiceRecognition.maxAlternatives = 1;
  voiceRecognition.onresult = event => {
    const transcript = event.results?.[0]?.[0]?.transcript || '';
    const input = $('assistantQuestion');
    if (input && transcript) input.value = transcript;
  };
  voiceRecognition.onerror = () => {
    assistantLine(currentLanguage === 'en'
      ? 'Voice recognition error — please try again or type your question.'
      : 'Erreur de reconnaissance vocale — réessayez ou écrivez votre question.', 'bot');
  };
  voiceRecognition.onend = () => {
    voiceListening = false;
    $('voiceOrb')?.classList.remove('listening');
    $('voiceButton')?.classList.remove('listening');
  };
  return voiceRecognition;
}

$('voiceButton')?.addEventListener('click', () => {
  const recognition = initVoiceRecognition();
  if (!recognition) {
    assistantLine(currentLanguage === 'en'
      ? 'Voice recognition is not available in this environment.'
      : "La reconnaissance vocale n'est pas disponible dans cet environnement.", 'bot');
    return;
  }
  if (voiceListening) {
    recognition.stop();
    return;
  }
  recognition.lang = currentLanguage === 'en' ? 'en-US' : 'fr-FR';
  voiceListening = true;
  $('voiceOrb')?.classList.add('listening');
  $('voiceButton')?.classList.add('listening');
  try {
    recognition.start();
  } catch (_) {
    voiceListening = false;
    $('voiceOrb')?.classList.remove('listening');
    $('voiceButton')?.classList.remove('listening');
  }
});

function renderStatus(s) {
  if (!s) return;
  currentStatus = s;
  if (s.version) {
    const vStr = `v${s.version}`;
    ['appVersionNavbar', 'appVersionLogin', 'appVersionInfo'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = vStr;
    });
  }
  const pendingIsFresh = pendingActiveSymbol && Date.now() - pendingActiveSymbolAt < 5000;
  if (pendingActiveSymbol && s.active_symbol === pendingActiveSymbol) {
    pendingActiveSymbol = null;
    pendingActiveSymbolAt = 0;
  }
  if (!pendingIsFresh && s.active_symbol && activeSymbol !== s.active_symbol) {
    activeSymbol = s.active_symbol;
  }
  const connected = s.state === 'connected';
  $('monitorBtn').classList.remove('running');
  $('monitorBtn').classList.remove('busy');
  $('connectionState').className = `state ${connected ? 'online' : 'offline'}`;
  $('connectionState').innerHTML = `<i></i> ${connected ? 'MT5 connecté' : s.state === 'missing_mt5' ? 'Module MT5 manquant' : 'Déconnecté'}`;
  const mode = String(s.mode || '').toUpperCase();
  $('demoBadge').className = `badge ${mode === 'DEMO' ? 'active demo' : ''}`;
  $('realBadge').className = `badge ${mode === 'REAL' ? 'active real' : ''}`;
  $('accountNumber').textContent = s.account ? `#${s.account}` : 'Compte -';
  $('serverName').textContent = s.server || '';
  const auto = s.auto_trading || {};
  const tradeButton = $('tradeBtn');
  const startButton = $('monitorBtn');
  tradeButton.classList.remove('busy', 'demo-ready', 'trade-active');
  startButton.classList.toggle('running', Boolean(auto.enabled));
  startButton.disabled = Boolean(auto.enabled);
  tradeButton.disabled = !connected || !auto.enabled;
  if (auto.enabled) {
    startButton.textContent = currentLanguage === 'en' ? 'Trading active' : 'Trading actif';
    tradeButton.classList.add('trade-active');
    tradeButton.textContent = currentLanguage === 'en' ? 'Stop' : 'Arrêter';
  } else {
    startButton.textContent = currentLanguage === 'en' ? 'Start' : 'Démarrer';
    tradeButton.textContent = currentLanguage === 'en' ? 'Stop' : 'Arrêter';
  }
  $('balance').textContent = plainMoney(s.balance);
  $('equity').textContent = plainMoney(s.equity);
  tone($('equity'), Number(s.equity) - Number(s.balance));

  const st = s.stats || {};
  const session = s.session_stats || {};
  const openBotPositions = (s.positions || []).filter(position => position.origin === 'BOT').length;
  const closedBotTrades = Number(session.trades || 0);
  $('netProfit').textContent = money(session.profit_closed);
  $('floating').textContent = money(session.profit_floating);
  $('winrate').textContent = closedBotTrades
    ? `${Number(session.winrate || 0).toFixed(1)}%`
    : '—';
  $('expectancy').textContent = closedBotTrades
    ? money(session.expectancy || 0).replace('.00', '.000')
    : '—';
  $('netProfitDetail').textContent = currentLanguage === 'en'
    ? `${closedBotTrades} closed · ${openBotPositions} open`
    : `${closedBotTrades} fermé(s) · ${openBotPositions} ouverte(s)`;
  $('winrateDetail').textContent = closedBotTrades
    ? (currentLanguage === 'en' ? 'Closed AlphaTrade trades' : 'Trades AlphaTrade fermés')
    : (currentLanguage === 'en' ? 'No AlphaTrade trade closed' : 'Aucun trade AlphaTrade fermé');
  $('expectancyDetail').textContent = closedBotTrades
    ? (currentLanguage === 'en' ? 'Average expected result per trade' : 'Résultat moyen attendu par trade')
    : (currentLanguage === 'en' ? 'Available after a trade closes' : 'Disponible après une fermeture');
  tone($('netProfit'), session.profit_closed);
  tone($('floating'), session.profit_floating);
  tone($('expectancy'), session.expectancy);

  const decision = s.simulated_decision || {};
  const access = s.session_access?.[activeSymbol] || {};
  const lotSafety = s.lot_safety?.[activeSymbol] || {};
  $('simulationDecision').textContent = decision.eligible
    ? `${decision.signal} - ${Number(decision.confidence || 0).toFixed(1)}%`
    : `${decision.signal || 'WAIT'} - entrée bloquée`;
  const lotText = lotSafety.effective_lot
    ? ` Lot sécurisé: ${Number(lotSafety.effective_lot).toFixed(3)}.`
    : lotSafety.rejected ? ` Trade refusé: ${lotSafety.reason}` : '';
  const autoError = String(auto.last_error || '');
  const autoText = autoError
    ? ` MT5: ${autoError}`
    : auto.enabled
      ? ' IA démarrée: prises de position autorisées.'
      : ' Signal observé seulement; cliquez sur Démarrer pour autoriser une entrée.';
  const strategyProfile = s.strategy_profile || {};
  const profileText = strategyProfile.label
    ? ` Profil: ${strategyProfile.label}.`
    : '';
  const mtfText = decision.multi_timeframe_bias
    ? ` Tendance large: ${decision.multi_timeframe_bias}.`
    : '';
  $('simulationReason').textContent = `${decision.reason || access.reason || 'En attente des règles de session.'}${profileText}${mtfText}${lotText}${autoText}`;
  $('simulationDecision').className = decision.eligible ? 'positive' : decision.signal === 'WAIT' ? '' : 'negative';

  $('sessionRealized').textContent = money(session.profit_closed);
  $('sessionFloating').textContent = money(session.profit_floating);
  $('sessionTarget').textContent = plainMoney(params?.session_target || 25);
  const protection = s.protection || {};
  $('currentSessionProfit').textContent = money(protection.session_profit || 0);
  $('sessionPeak').textContent = money(protection.peak || 0);
  $('sessionFloor').textContent = protection.activated ? money(protection.floor || 0) : '-';
  $('protectionBadge').textContent = {
    INACTIVE: 'Protection inactive',
    ARMED: 'Protection armée',
    WARNING: 'Avertissement',
    HARD_LOCK: 'Session verrouillée',
    TARGET_REACHED: 'Objectif atteint'
  }[protection.state] || 'Protection inactive';
  $('protectionBadge').className = `protection-badge ${String(protection.state || 'inactive').toLowerCase()}`;
  $('protectionReason').textContent = protection.reason || 'En attente des données de session.';
  $('newSessionBtn').hidden = !(protection.session_locked && !protection.daily_locked);
  const pct = Math.max(0, Math.min(100, Number(protection.session_profit || 0) / Number(params?.session_target || 25) * 100));
  $('targetProgress').style.width = `${pct}%`;

  renderPositions(s.positions || []);
  renderQuality(st);
  renderLearning();
  renderMarketSessions();
  renderCalendar();
  renderActiveMarket();
  renderMicrostructurePage();
  if (currentLanguage === 'en') translateStatic('en');
}

function renderMicrostructurePage() {
  if (!currentStatus) return;
  const micro = currentStatus.microstructure || {};
  const snapshots = micro.snapshots || {};
  const snapshot = snapshots[`MT5:${activeSymbol}`] || {};
  const hyperOnline = Object.keys(snapshots).some(key => key.startsWith('HYPERLIQUID:'));
  const decision = currentStatus.simulated_decision || {};
  const now = Date.now();
  const reason = String(decision.reason || '');
  const decisionKey = decision.eligible ? '' : `${decision.signal || 'WAIT'}|${reason}`;
  if (decisionKey && decisionKey !== blockedDecisionKey) {
    blockedDecisionKey = decisionKey;
    blockedDecisionSince = now;
    blockedDecisionCount += 1;
  } else if (!decisionKey) {
    blockedDecisionKey = '';
    blockedDecisionSince = 0;
  }
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  const obi = Number(snapshot.obi);
  const ofi = Number(snapshot.ofi);
  const domActive = (micro.dom_status || {})[activeSymbol];
  // OBI/Kyle λ/POC exigent un vrai carnet d'ordres multi-niveaux (Depth of
  // Market). Sans DOM (dépend du broker/compte), ils sont mathématiquement
  // à 0 en permanence — afficher "N/D" plutôt qu'un 0.000 qui ressemblerait
  // à une vraie lecture de marché équilibré. OFI reste valide sans DOM (basé
  // sur le mouvement de prix bid/ask, pas sur la profondeur).
  const domDataOk = Boolean(snapshot.source) && Boolean(domActive);
  set('microPageMode', micro.mode === 'OBSERVATION_ONLY' ? 'OBSERVATION UNIQUEMENT' : 'INACTIF');
  set('microPageSource', snapshot.source ? `${snapshot.source} · ${snapshot.symbol} · ${snapshot.venue}` : 'En attente du flux MT5');
  set('microPageFreshness', snapshot.timestamp
    ? `Dernière mise à jour : ${new Date(Number(snapshot.timestamp) * 1000).toLocaleTimeString()}`
    : 'Dernière mise à jour : -');
  set('microPageObi', domDataOk && Number.isFinite(obi) ? obi.toFixed(3) : 'N/D');
  set('microPageOfi', Number.isFinite(ofi) ? ofi.toFixed(3) : '-');
  set('microPageKyle', domDataOk && snapshot.kyle_lambda != null ? Number(snapshot.kyle_lambda).toExponential(2) : 'N/D');
  set('microPagePoc', domDataOk && snapshot.poc ? Number(snapshot.poc).toFixed(2) : 'N/D');
  set('microObiMeaning', !domDataOk ? 'Carnet d\'ordres réel indisponible pour ce broker/compte' : obi > .15 ? 'Pression acheteuse observée' : obi < -.15 ? 'Pression vendeuse observée' : 'Carnet local équilibré');
  set('microOfiMeaning', !Number.isFinite(ofi) ? 'Variation indéterminée' : ofi > .15 ? 'Flux récent favorable aux acheteurs' : ofi < -.15 ? 'Flux récent favorable aux vendeurs' : 'Flux récent neutre');
  if ($('microObiMeter')) $('microObiMeter').style.width = `${domDataOk && Number.isFinite(obi) ? Math.max(0, Math.min(100, (obi + 1) * 50)) : 50}%`;
  if ($('microOfiMeter')) $('microOfiMeter').style.width = `${Number.isFinite(ofi) ? Math.max(0, Math.min(100, (ofi + 1) * 50)) : 50}%`;
  set('microDecisionSignal', `${decision.signal || 'WAIT'} ${decision.confidence != null ? `${Number(decision.confidence).toFixed(1)}%` : ''}`);
  set('microDecisionState', decision.eligible ? 'Entrée autorisée' : 'Entrée bloquée');
  set('microBlockedCount', blockedDecisionCount);
  set('microBlockedDuration', blockedDecisionSince ? formatDuration(Math.floor((now - blockedDecisionSince) / 1000)) : '-');
  set('microDecisionReason', reason || 'Aucune décision disponible.');
  set('microMt5State', !snapshot.source ? 'En attente' : domActive ? 'Actif (carnet réel)' : 'Actif (approximation, DOM indisponible)');
  set('microHyperState', hyperOnline ? 'Actif' : params?.hyperliquid_observer_enabled ? 'Connexion en attente' : 'Désactivé');
  set('microError', micro.last_error ? `Erreur de collecte : ${micro.last_error}` : 'Aucune erreur de collecte.');
}

function renderActiveMarket() {
  if (!currentStatus) return;
  const analysis = currentStatus.analysis?.[activeSymbol] || {};
  $('signalBanner').textContent = `${analysis.signal || 'WAIT'} ${analysis.confidence ? `- ${analysis.confidence}%` : ''}`;
  $('signalBanner').className = `signal ${(analysis.signal || 'WAIT').toLowerCase()}`;
  const isCollecting = analysis.trend === 'COLLECTING';
  $('buyScore').textContent = isCollecting ? '—' : `${Number(analysis.score_buy || 0).toFixed(0)}%`;
  $('sellScore').textContent = isCollecting ? '—' : `${Number(analysis.score_sell || 0).toFixed(0)}%`;
  $('buyBar').style.width = isCollecting ? '0%' : `${analysis.score_buy || 0}%`;
  $('sellBar').style.width = isCollecting ? '0%' : `${analysis.score_sell || 0}%`;
  $('rsi').textContent = analysis.rsi ?? '-';
  $('trend').textContent = analysis.trend ?? '-';
  $('ema9').textContent = analysis.ema9 ?? '-';
  $('ema21').textContent = analysis.ema21 ?? '-';
  $('macd').textContent = analysis.macd ?? '-';
  $('edge').textContent = analysis.edge_position != null ? `${analysis.edge_position}%` : '-';
  const aiOnline = Boolean(currentStatus?.ai_server?.connected);
  const quantSig = analysis.quant_signal || (aiOnline ? 'WAIT' : analysis.signal || 'WAIT');
  const quantConf = analysis.quant_confidence ?? (aiOnline ? null : (analysis.confidence ?? null));
  $('quantSignal').textContent = `${quantSig} ${quantConf != null ? `${Number(quantConf).toFixed(0)}%` : ''}`;
  $('quantSignal').className = String(quantSig).toLowerCase();
  $('quantReason').textContent = aiOnline
    ? (analysis.quant_reason || 'Collecte des données')
    : (analysis.quant_reason || 'Signal local — serveur IA hors ligne');
  $('quantRisk').textContent = analysis.quant_regime_risk != null ? `${analysis.quant_regime_risk}%` : '-';
  const micro = currentStatus.microstructure || {};
  const snapshot = micro.snapshots?.[`MT5:${activeSymbol}`] || {};
  $('microMode').textContent = micro.mode === 'OBSERVATION_ONLY' ? 'OBSERVATION' : 'INACTIF';
  $('microSource').textContent = snapshot.source
    ? `${snapshot.source} · ${snapshot.symbol} · ${snapshot.venue}`
    : (micro.last_error || 'En attente du flux MT5');
  $('microObi').textContent = snapshot.obi != null ? Number(snapshot.obi).toFixed(3) : '-';
  $('microOfi').textContent = snapshot.ofi != null ? Number(snapshot.ofi).toFixed(3) : '-';
  $('microKyle').textContent = snapshot.kyle_lambda != null ? Number(snapshot.kyle_lambda).toExponential(2) : '-';
  $('microPoc').textContent = snapshot.poc ? Number(snapshot.poc).toFixed(2) : '-';
}

function renderMarketChart(candles) {
  const canvas = document.getElementById('marketChart');
  if (!canvas || !candles.length) return;
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  const ctx = canvas.getContext('2d');
  ctx.scale(scale, scale);
  const width = rect.width;
  const height = rect.height;
  const pad = { left: 12, right: 66, top: 14, bottom: 24 };
  const values = candles.flatMap(c => [Number(c.high), Number(c.low)]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const y = value => pad.top + (max - value) / range * plotH;

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = 'rgba(61,95,75,.35)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) {
    const gy = pad.top + plotH * i / 5;
    ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(width - pad.right, gy); ctx.stroke();
  }
  for (let i = 0; i <= 8; i += 1) {
    const gx = pad.left + plotW * i / 8;
    ctx.beginPath(); ctx.moveTo(gx, pad.top); ctx.lineTo(gx, height - pad.bottom); ctx.stroke();
  }

  const step = plotW / candles.length;
  const bodyWidth = Math.max(2, Math.min(8, step * .62));
  candles.forEach((c, index) => {
    const x = pad.left + step * index + step / 2;
    const open = Number(c.open);
    const close = Number(c.close);
    const rising = close >= open;
    ctx.strokeStyle = rising ? '#38e29b' : '#ff6178';
    ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath(); ctx.moveTo(x, y(Number(c.high))); ctx.lineTo(x, y(Number(c.low))); ctx.stroke();
    const top = Math.min(y(open), y(close));
    const bodyHeight = Math.max(1, Math.abs(y(open) - y(close)));
    ctx.fillRect(x - bodyWidth / 2, top, bodyWidth, bodyHeight);
  });

  ctx.fillStyle = '#68a38e';
  ctx.font = '10px Consolas';
  ctx.textAlign = 'left';
  for (let i = 0; i <= 4; i += 1) {
    const value = max - range * i / 4;
    ctx.fillText(value.toFixed(2), width - pad.right + 7, pad.top + plotH * i / 4 + 3);
  }
}

window.addEventListener('resize', () => {
  const market = currentStatus?.symbols?.[activeSymbol] || {};
  renderMarketChart(market.candles || []);
});

function renderPositions(positions) {
  $('positionCount').textContent = positions.length;
  if (!positions.length) {
    $('positionCards').innerHTML = '<p class="empty">Aucune position ouverte</p>';
    return;
  }
  $('positionCards').innerHTML = positions.map(p => `
    <div class="position ${p.direction.toLowerCase()}">
      <strong>${p.direction} ${p.symbol_key}</strong>
      <div class="row"><span>${originLabel(p)} · lot ${Number(p.lot).toFixed(2)}</span><b class="${p.profit >= 0 ? 'positive' : 'negative'}">${money(p.profit)}</b></div>
      <div class="row"><span>${Number(p.open_price).toFixed(2)}</span><span>${Number(p.current_price).toFixed(2)}</span></div>
    </div>`).join('');
}

function originLabel(row) {
  // Le backend calcule desormais le vrai nom via le registre "trade_origins"
  // (Phase 8) -- on ne devine plus jamais "AVA" pour une origine inconnue.
  if (row && typeof row === 'object' && row.origin_name) return row.origin_name;
  const key = String((row && row.origin) || row || 'MANUAL').toUpperCase();
  if (key === 'BOT') return 'ALPHATRADE';
  if (key === 'EXTERNAL_AI') return currentLanguage === 'en' ? 'External EA' : 'EA externe';
  return currentLanguage === 'en' ? 'MANUAL' : 'MANUEL';
}

function renderQuality(st) {
  $('profitFactor').textContent = Number(st.profit_factor || 0).toFixed(2);
  $('avgWin').textContent = money(st.avg_win);
  $('avgLoss').textContent = `-$${Math.abs(Number(st.avg_loss || 0)).toFixed(2)}`;
  $('winsLosses').textContent = `${st.wins || 0} / ${st.losses || 0}`;
  const bot = currentStatus?.origin_stats?.ALPHATRADE || {};
  $('iaWinrate').textContent = `${Number(bot.winrate || 0).toFixed(1)}%`;
  $('iaProfitFactor').textContent = Number(bot.profit_factor || 0).toFixed(2);
  $('iaExpectancy').textContent = money(bot.expectancy);
  const pf = Number(st.profit_factor || 0);
  const exp = Number(st.expectancy || 0);
  const avgWin = Number(st.avg_win || 0);
  const avgLoss = Number(st.avg_loss || 0);
  $('qualityMessage').textContent = !st.trades
    ? (currentLanguage === 'en' ? 'Not enough closed trades yet.' : 'Pas encore assez de trades fermés.')
    : exp > 0 && pf >= 1.2 && avgWin >= avgLoss * 0.45
      ? (currentLanguage === 'en' ? 'The strategy is positive on the observed sample.' : 'Stratégie actuellement positive sur l’échantillon observé.')
      : avgLoss > avgWin * 3
        ? (currentLanguage === 'en' ? 'Danger: average losses are too large compared with wins.' : 'Danger: les pertes moyennes sont trop grandes par rapport aux gains.')
        : (currentLanguage === 'en' ? 'The strategy still needs calibration.' : 'La stratégie doit encore être recalibrée.');
}

function symbolStats(symbolKey, origin = 'BOT') {
  const filtered = allTrades.filter(t =>
    (t.symbol_key || '').toUpperCase() === symbolKey &&
    (t.origin || 'MANUAL').toUpperCase() === origin
  );
  const wins = filtered.filter(t => Number(t.profit) > 0);
  const losses = filtered.filter(t => Number(t.profit) < 0);
  const total = filtered.reduce((sum, t) => sum + Number(t.profit || 0), 0);
  const winrate = filtered.length ? wins.length / filtered.length * 100 : 0;
  return { trades: filtered.length, wins: wins.length, losses: losses.length, total, winrate };
}

function sampleQuality(st) {
  if (!st.trades) return 'Aucun trade';
  if (st.trades < 30) return 'Faible';
  if (st.total > 0 && st.winrate >= 55) return 'Positive';
  if (st.total < 0) return 'À corriger';
  return 'Neutre';
}

function renderLearning() {
  const xau = symbolStats('XAUUSD');
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  set('iaXauTrades', xau.trades);
  set('iaXauWinrate', `${xau.winrate.toFixed(1)}%`);
  set('iaXauProfit', money(xau.total));
  const learnedXau = currentStatus?.learning?.symbols?.XAUUSD || {};
  const analysisXau = currentStatus?.analysis?.XAUUSD || {};
  set('learningState', params?.reinforcement_enabled === false ? (currentLanguage === 'en' ? 'Paused' : 'En pause') : (currentLanguage === 'en' ? 'Active' : 'Actif'));
  set('iaXauQuality', `${learnedXau.samples || 0} ${currentLanguage === 'en' ? 'decisions' : 'décisions'}`);
  set('iaXauThreshold', `${Number(analysisXau.learned_threshold || params?.symbols?.XAUUSD?.confidence_min || 62).toFixed(1)}%`);
  set('iaXauExcursions', `-$${Number(learnedXau.avg_mae || 0).toFixed(2)} / +$${Number(learnedXau.avg_mfe || 0).toFixed(2)}`);
  renderLearningReport(learnedXau, analysisXau, xau);
  const elProfit = $('iaXauProfit');
  if (elProfit) tone(elProfit, xau.total);
  renderOriginEvaluation('bot', currentStatus?.origin_stats?.ALPHATRADE || {});
  renderOriginEvaluation('external', currentStatus?.origin_stats?.EXTERNAL_AI || {});
  renderOriginEvaluation('manual', currentStatus?.origin_stats?.MANUAL || {});
  renderServerLearning();
}

function renderLearningReport(learned, analysis, observed) {
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  const samples = Number(learned.samples || 0);
  const wins = Number(learned.wins || 0);
  const losses = Number(learned.losses || 0);
  const avgMae = Number(learned.avg_mae || 0);
  const avgMfe = Number(learned.avg_mfe || 0);
  const offset = Number(learned.confidence_offset || 0);
  const weights = learned.weights || {};
  const ranked = Object.entries(weights)
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  const strongest = ranked[0]?.[0] || 'aucun composant';
  const weakest = ranked.at(-1)?.[0] || 'aucun composant';
  const winrate = samples ? wins / samples * 100 : 0;
  set('learningReportState', samples ? `${samples} décisions analysées` : 'En attente');
  set('learningObserved', samples
    ? `Sur XAU/USD, ${samples} décisions ont été évaluées : ${wins} gains et ${losses} pertes (${winrate.toFixed(1)} %). Le dernier résultat enregistré est ${learned.last_outcome === 'LOSS' ? 'une perte' : 'un gain'}.`
    : 'Les observations apparaîtront après les premiers trades AlphaTrade.');
  set('learningLearned', samples
    ? `Le composant actuellement le plus renforcé est « ${strongest} » et le moins renforcé est « ${weakest} ». Le seuil de confiance a été ajusté de ${offset >= 0 ? '+' : ''}${offset.toFixed(2)} point(s).`
    : 'Aucun ajustement mesurable pour le moment.');
  set('learningDifficulties', samples
    ? (avgMae > Math.max(1, avgMfe * 3)
      ? `Les positions ont subi une excursion défavorable moyenne de $${avgMae.toFixed(2)}, nettement supérieure à l'excursion favorable moyenne de $${avgMfe.toFixed(2)}. Les pertes rares restent donc potentiellement dangereuses.`
      : `L'excursion défavorable moyenne est de $${avgMae.toFixed(2)} contre $${avgMfe.toFixed(2)} favorable. Aucune anomalie majeure n'est encore confirmée.`)
    : 'Aucune difficulté évaluée pour le moment.');
  set('learningNextStep', samples
    ? (losses
      ? `Étudier les ${losses} perte(s), renforcer la protection individuelle et conserver l'arrêt des nouvelles entrées dès l'objectif atteint, sans liquider automatiquement les positions ouvertes.`
      : 'Continuer la collecte sur plusieurs régimes de marché avant toute augmentation du risque.')
    : 'Continuer la collecte sans modifier les garde-fous.');
}

function renderServerLearning() {
  const server = currentStatus?.ai_server || {};
  const models = server.models || {};
  const predictions = server.predictions || {};
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  set('aiServerMode', 'Observation');
  set('aiServerConnection', server.connected
    ? (currentLanguage === 'en' ? 'Online' : 'Connecté')
    : (currentLanguage === 'en' ? 'Offline' : 'Hors ligne'));
  set('aiServerUrl', server.url || params?.ai_server_url || 'http://127.0.0.1:8765');
  set('aiServerSync', server.last_sync ? new Date(server.last_sync).toLocaleTimeString() : '-');
  set('aiServerMessage', server.connected
    ? (currentLanguage === 'en'
      ? 'Server signals are observed only. Local execution remains in control.'
      : 'Les signaux serveur sont observés uniquement. L’exécution locale garde le contrôle.')
    : (server.error || (currentLanguage === 'en'
      ? 'The local engine continues to work without the AI server.'
      : 'Le moteur local continue de fonctionner sans le serveur IA.')));
  [['XAUUSD', 'serverXau']].forEach(([symbol, prefix]) => {
    const model = models[symbol] || predictions[symbol]?.model || {};
    const prediction = predictions[symbol] || {};
    set(`${prefix}Version`, model.version ? `v${model.version}` : '-');
    set(`${prefix}Samples`, model.samples || 0);
    set(`${prefix}Score`, model.score != null ? `${(Number(model.score) * 100).toFixed(1)}%` : '-');
    set(`${prefix}Signal`, prediction.available
      ? `${prediction.signal} ${Number(prediction.confidence || 0).toFixed(1)}%`
      : 'WAIT');
  });
}

function performanceScore(st) {
  const trades = Number(st.trades || 0);
  if (!trades) return 0;
  const sample = Math.min(1, trades / 50);
  const winrate = Math.min(100, Number(st.winrate || 0));
  const pf = Math.min(2, Number(st.profit_factor || 0));
  const expectancy = Number(st.expectancy || 0);
  const profitability = expectancy > 0 ? 15 : expectancy < 0 ? 0 : 7;
  return Math.round((winrate * .55 + pf / 2 * 30 + profitability) * (.65 + sample * .35));
}

function evaluationAdvice(st, source) {
  const trades = Number(st.trades || 0);
  if (!trades) {
    if (source === 'bot') return 'L’apprentissage commencera après les premiers trades automatiques.';
    if (source === 'external') return 'Aucun trade d’une IA externe n’a encore été identifié.';
    return 'Aucun trade manuel fermé dans la période analysée.';
  }
  if (trades < 20) return 'Échantillon encore faible: poursuivre les tests avant de modifier la stratégie.';
  if (Number(st.avg_loss || 0) > Number(st.avg_win || 0) * 2.5) {
    return 'Priorité: réduire la perte moyenne et fermer plus tôt les scénarios invalidés.';
  }
  if (Number(st.profit_factor || 0) < 1) {
    return 'La stratégie observée perd davantage qu’elle ne gagne; revoir les filtres et la cadence.';
  }
  if (Number(st.expectancy || 0) > 0) {
    return 'Résultat positif sur cet échantillon; maintenir les limites et poursuivre la validation.';
  }
  return 'Résultat neutre: davantage de données sont nécessaires.';
}

function renderOriginEvaluation(prefix, st) {
  const set = (suffix, value) => {
    const el = $(`${prefix}${suffix}`);
    if (el) el.textContent = value;
  };
  set('Score', `${performanceScore(st)}%`);
  set('Record', `${st.trades || 0} / ${st.wins || 0} / ${st.losses || 0}`);
  set('Profit', money(st.profit_closed || 0));
  set('Averages', `${money(st.avg_win || 0)} / -$${Math.abs(Number(st.avg_loss || 0)).toFixed(2)}`);
  set('Advice', evaluationAdvice(st, prefix));
  tone($(`${prefix}Profit`), st.profit_closed || 0);
}

function sessionDefinitions() {
  return [
    { key: 'Sydney', id: 'Sydney', perf: 'perfSydney', start: 22, end: 7, label: '22h-07h GMT' },
    { key: 'Tokyo', id: 'Tokyo', perf: 'perfTokyo', start: 0, end: 9, label: '00h-09h GMT' },
    { key: 'London', id: 'Londres', perf: 'perfLondon', start: 8, end: 17, label: '08h-17h GMT' },
    { key: 'NewYork', id: 'New York', perf: 'perfNewYork', start: 13, end: 22, label: '13h-22h GMT' }
  ];
}

function primaryMarketSession(now = new Date()) {
  const current = now.getUTCHours() * 3600 + now.getUTCMinutes() * 60 + now.getUTCSeconds();
  const opened = sessionDefinitions().filter(session => isHourInSession(now.getUTCHours(), session));
  if (!opened.length) return null;
  return opened
    .map(session => {
      const start = session.start * 3600;
      const elapsed = current >= start ? current - start : 86400 - start + current;
      return { session, elapsed };
    })
    .sort((a, b) => a.elapsed - b.elapsed)[0].session;
}

function isHourInSession(hour, s) {
  return s.start < s.end ? hour >= s.start && hour < s.end : hour >= s.start || hour < s.end;
}

function secondsToSessionBoundary(now, s, open) {
  const hour = now.getUTCHours();
  const minute = now.getUTCMinutes();
  const second = now.getUTCSeconds();
  const current = hour * 3600 + minute * 60 + second;
  const targetHour = open ? s.start : s.end;
  const target = targetHour * 3600;
  return target > current ? target - current : 86400 - current + target;
}

function formatDuration(total) {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function renderCurrentMarketSession() {
  if (!$('currentMarketSession')) return;
  const now = new Date();
  const session = primaryMarketSession(now);
  $('currentMarketClock').textContent = `${String(now.getUTCHours()).padStart(2, '0')}:${String(now.getUTCMinutes()).padStart(2, '0')}:${String(now.getUTCSeconds()).padStart(2, '0')} GMT`;
  if (!session) {
    $('currentMarketSession').textContent = currentLanguage === 'en' ? 'Outside session' : 'Hors session';
    $('currentMarketHours').textContent = '--';
    $('currentMarketState').textContent = currentLanguage === 'en' ? 'Closed' : 'Fermée';
    $('currentMarketCountdown').textContent = '--:--:--';
    // Mettre à jour le header
    if ($('headerSessionName')) $('headerSessionName').textContent = 'Hors session';
    if ($('headerSessionState')) $('headerSessionState').textContent = '';
    return;
  }
  const sessionName = currentLanguage === 'en' && session.key === 'London' ? 'London' : session.id;
  $('currentMarketSession').textContent = `${currentLanguage === 'en' ? 'Session' : 'Session'} ${sessionName}`;
  $('currentMarketHours').textContent = session.label;
  $('currentMarketState').textContent = currentLanguage === 'en' ? 'Open' : 'Ouverte';
  $('currentMarketCountdown').textContent = formatDuration(secondsToSessionBoundary(now, session, false));
  // Mettre à jour le header
  if ($('headerSessionName')) $('headerSessionName').textContent = `Session ${sessionName}`;
  if ($('headerSessionState')) {
    const remaining = formatDuration(secondsToSessionBoundary(now, session, false));
    $('headerSessionState').textContent = remaining;
  }
}

function tradeSession(t) {
  const d = new Date(t.open_time || t.close_time || 0);
  const hour = d.getUTCHours();
  return sessionDefinitions().find(s => isHourInSession(hour, s))?.key || 'Hors session';
}

function sessionPeriodTrades() {
  const from = $('sessionDateFrom')?.value;
  const to = $('sessionDateTo')?.value;
  return allTrades.filter(trade => {
    const key = String(trade.open_time || trade.close_time || '').slice(0, 10);
    if (from && key < from) return false;
    if (to && key > to) return false;
    return true;
  });
}

function renderMarketSessions() {
  const container = $('sessionCards');
  if (!container) return;
  const now = new Date();
  const defs = sessionDefinitions();
  container.innerHTML = defs.map(s => {
    const open = isHourInSession(now.getUTCHours(), s);
    const seconds = secondsToSessionBoundary(now, s, !open);
    return `<article class="session-card ${open ? 'open' : ''}">
      <h3>${s.id}</h3>
      <p>${s.label}</p>
      <span class="session-state">${open ? (currentLanguage === 'en' ? 'Open' : 'Ouverte') : (currentLanguage === 'en' ? 'Closed' : 'Fermée')}</span>
      <span class="countdown">${formatDuration(seconds)}</span>
      <p>${open ? (currentLanguage === 'en' ? 'before close' : 'avant fermeture') : (currentLanguage === 'en' ? 'before open' : 'avant ouverture')}</p>
    </article>`;
  }).join('');
  const totals = { Sydney: 0, Tokyo: 0, London: 0, NewYork: 0 };
  sessionPeriodTrades().forEach(t => {
    const key = tradeSession(t);
    if (Object.prototype.hasOwnProperty.call(totals, key)) totals[key] += Number(t.profit || 0);
  });
  defs.forEach(s => {
    const el = $(s.perf);
    if (!el) return;
    el.textContent = money(totals[s.key]);
    tone(el, totals[s.key]);
  });
}

$('sessionDateFrom')?.addEventListener('change', renderMarketSessions);
$('sessionDateTo')?.addEventListener('change', renderMarketSessions);
$('sessionPeriodReset')?.addEventListener('click', () => {
  $('sessionDateFrom').value = '';
  $('sessionDateTo').value = '';
  renderMarketSessions();
});

setInterval(renderMarketSessions, 1000);
setInterval(renderCurrentMarketSession, 1000);
renderCurrentMarketSession();

function monthName(date) {
  return new Intl.DateTimeFormat(currentLanguage === 'en' ? 'en-CA' : 'fr-CA', { month: 'long', year: 'numeric' }).format(date);
}

function dayKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function tradeDay(t) {
  return String(t.open_time || t.close_time || '').slice(0, 10);
}

// Filtre session pour le calendrier
const SESSION_RANGES_CAL = {
  all: null,
  sydney: { start: 22, end: 7 },
  tokyo: { start: 0, end: 9 },
  london: { start: 8, end: 17 },
  newyork: { start: 13, end: 22 },
};

function tradeInSessionFilter(t, session) {
  if (!session || session === 'all') return true;
  const s = SESSION_RANGES_CAL[session];
  if (!s) return true;
  const h = new Date(t.open_time || t.close_time || 0).getUTCHours();
  return s.start < s.end ? h >= s.start && h < s.end : h >= s.start || h < s.end;
}

let calendarRangeStart = null;
let calendarRangeEnd = null;

function calendarStats(key) {
  const session = $('calendarSessionFilter')?.value || 'all';
  // Trades récents disponibles en mémoire (pour la vue détail)
  const recentTrades = allTrades.filter(t => tradeDay(t) === key && tradeInSessionFilter(t, session));

  // Pour la grille du calendrier : priorité aux données persistantes (toutes périodes)
  // On n'applique le filtre session que si on a les trades individuels
  const persisted = calendarData[key];
  if (persisted && !recentTrades.length) {
    // Jour hors fenêtre des trades récents → utiliser le résumé persistant
    return {
      trades: Array(persisted.trades).fill(null), // proxy pour .length uniquement
      total: persisted.profit,
      wins: persisted.wins,
      losses: persisted.losses,
      summaryOnly: true,
    };
  }
  const total = recentTrades.reduce((sum, t) => sum + Number(t.profit || 0), 0);
  const wins = recentTrades.filter(t => Number(t.profit) > 0).length;
  const losses = recentTrades.filter(t => Number(t.profit) < 0).length;
  return { trades: recentTrades, total, wins, losses, summaryOnly: false };
}

function renderCalendar() {
  const grid = $('calendarGrid');
  if (!grid) return;
  const title = $('calendarTitle');
  const first = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  if (title) {
    title.textContent = monthName(first);
    title.onclick = () => {
      // Clic sur le mois = sélectionner tout le mois
      const last = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + 1, 0);
      calendarRangeStart = dayKey(first);
      calendarRangeEnd = dayKey(last);
      calendarSelected = calendarRangeStart;
      renderCalendar();
      renderCalendarRange(calendarRangeStart, calendarRangeEnd);
    };
  }
  const todayKey = dayKey(new Date());
  const cells = [];
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const key = dayKey(d);
    const st = calendarStats(key);
    const outside = d.getMonth() !== calendarCursor.getMonth();
    const inRange = calendarRangeStart && calendarRangeEnd
      ? key >= calendarRangeStart && key <= calendarRangeEnd
      : key === calendarSelected;
    const cls = ['calendar-day', outside ? 'outside' : '', key === todayKey ? 'today' : '', inRange ? 'selected' : '', st.trades.length ? (st.total >= 0 ? 'profit' : 'loss') : ''].filter(Boolean).join(' ');
    cells.push(`<button class="${cls}" data-day="${key}" type="button">
      <span>${d.getDate()}</span>
      ${st.trades.length ? `<b class="${st.total >= 0 ? 'positive' : 'negative'}">${money(st.total)}</b><small>${st.trades.length} trades</small>` : ''}
    </button>`);
  }
  grid.innerHTML = cells.join('');
  grid.querySelectorAll('[data-day]').forEach(btn => btn.addEventListener('click', (e) => {
    const key = btn.dataset.day;
    if (e.shiftKey && calendarSelected) {
      // Shift+clic = sélectionner une plage
      calendarRangeStart = calendarSelected < key ? calendarSelected : key;
      calendarRangeEnd = calendarSelected < key ? key : calendarSelected;
      renderCalendar();
      renderCalendarRange(calendarRangeStart, calendarRangeEnd);
    } else {
      calendarSelected = key;
      calendarRangeStart = null;
      calendarRangeEnd = null;
      renderCalendar();
      renderCalendarDetail(key);
    }
  }));
  if (calendarRangeStart && calendarRangeEnd) {
    renderCalendarRange(calendarRangeStart, calendarRangeEnd);
  } else if (calendarSelected) {
    renderCalendarDetail(calendarSelected);
  }
}

function renderCalendarRange(from, to) {
  const detail = $('calendarDetail');
  if (!detail) return;
  const session = $('calendarSessionFilter')?.value || 'all';
  const trades = allTrades.filter(t => {
    const d = tradeDay(t);
    return d >= from && d <= to && tradeInSessionFilter(t, session);
  });
  if (!trades.length) {
    detail.innerHTML = `<div class="calendar-empty">Aucun trade du ${from} au ${to}.</div>`;
    return;
  }
  const total = trades.reduce((s, t) => s + Number(t.profit || 0), 0);
  const wins = trades.filter(t => Number(t.profit) > 0).length;
  const losses = trades.filter(t => Number(t.profit) < 0).length;
  detail.innerHTML = `<div class="day-summary">
    <div><label>Période</label><b>${from} → ${to}</b></div>
    <div><label>Profit total</label><b class="${total >= 0 ? 'positive' : 'negative'}">${money(total)}</b></div>
    <div><label>Gains / Pertes</label><b>${wins} / ${losses}</b></div>
    <div><label>Total trades</label><b>${trades.length}</b></div>
  </div>
  ${trades.slice(0, 50).map(t => {
    const profit = Number(t.profit || 0);
    const time = (t.open_time || '').replace('T', ' ').slice(5, 16);
    return `<div class="day-trade">
      <span class="pill ${String(t.direction).toLowerCase()}">${t.direction}</span>
      <span>${time}</span>
      <span>${Number(t.lot || 0).toFixed(2)} lot</span>
      <strong class="${profit >= 0 ? 'positive' : 'negative'}">${money(profit)}</strong>
    </div>`;
  }).join('')}`;
}

function renderCalendarDetail(key) {
  const detail = $('calendarDetail');
  if (!detail) return;
  const st = calendarStats(key);
  if (!st.trades.length) {
    detail.innerHTML = `<div class="calendar-empty">${currentLanguage === 'en' ? 'No closed trade on' : 'Aucun trade fermé le'} ${key}.</div>`;
    return;
  }
  if (st.summaryOnly) {
    // Résumé persistant disponible mais trades individuels non chargés (jour ancien)
    detail.innerHTML = `<div class="day-summary">
      <div><label>Date</label><b>${key}</b></div>
      <div><label>Profit</label><b class="${st.total >= 0 ? 'positive' : 'negative'}">${money(st.total)}</b></div>
      <div><label>Wins / Losses</label><b>${st.wins} / ${st.losses}</b></div>
      <div><label>Trades</label><b>${st.trades.length}</b></div>
    </div>
    <div class="calendar-empty" style="font-size:0.82em;opacity:0.6;margin-top:8px">
      Détail individuel disponible uniquement sur les trades récents synchronisés.
    </div>`;
    return;
  }
  const lots = st.trades.reduce((sum, t) => sum + Number(t.lot || 0), 0);
  detail.innerHTML = `<div class="day-summary">
    <div><label>Date</label><b>${key}</b></div>
    <div><label>Profit</label><b class="${st.total >= 0 ? 'positive' : 'negative'}">${money(st.total)}</b></div>
    <div><label>Wins / Losses</label><b>${st.wins} / ${st.losses}</b></div>
    <div><label>Lots</label><b>${lots.toFixed(3)}</b></div>
  </div>
  ${st.trades.map(t => {
    const profit = Number(t.profit || 0);
    const time = (t.open_time || '').replace('T', ' ').slice(11, 19);
    return `<div class="day-trade">
      <span class="pill ${String(t.direction).toLowerCase()}">${t.direction}</span>
      <span>${time} ${t.symbol_key || ''}</span>
      <span>${Number(t.lot || 0).toFixed(2)} lot</span>
      <strong class="${profit >= 0 ? 'positive' : 'negative'}">${money(profit)}</strong>
    </div>`;
  }).join('')}`;
}

$('calendarPrev')?.addEventListener('click', () => {
  calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() - 1, 1);
  calendarSelected = null; calendarRangeStart = null; calendarRangeEnd = null;
  renderCalendar();
});
$('calendarNext')?.addEventListener('click', () => {
  calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + 1, 1);
  calendarSelected = null; calendarRangeStart = null; calendarRangeEnd = null;
  renderCalendar();
});
$('calendarToday')?.addEventListener('click', () => {
  calendarCursor = new Date();
  calendarSelected = dayKey(new Date());
  calendarRangeStart = null; calendarRangeEnd = null;
  renderCalendar();
});
$('calendarSessionFilter')?.addEventListener('change', () => {
  calendarRangeStart = null; calendarRangeEnd = null;
  renderCalendar();
});

function tradeRow(t, withTime = false, idx = null) {
  const profit = Number(t.profit || 0);
  const time = (t.close_time || t.open_time || '').replace('T', ' ').slice(5, 19);
  const idxAttr = idx !== null ? ` data-idx="${idx}"` : '';
  return `<tr${idxAttr}>
    ${withTime ? `<td>${time || '-'}</td>` : ''}
    <td><span class="pill ${String(t.direction).toLowerCase()}">${t.direction}</span></td>
    <td>${originLabel(t)}</td>
    <td>${Number(t.lot || 0).toFixed(2)}</td>
    <td>${Number(t.open_price || 0).toFixed(2)}</td>
    <td>${Number(t.close_price || 0).toFixed(2)}</td>
    <td class="${Number(t.move) >= 0 ? 'positive' : 'negative'}">${Number(t.move || 0).toFixed(2)}</td>
    <td class="${profit >= 0 ? 'positive' : 'negative'}">${money(profit)}</td>
  </tr>`;
}

function filteredTrades() {
  const now = Date.now();
  const todayStr = new Date().toISOString().slice(0, 10);
  const yesterdayStr = new Date(now - 86400000).toISOString().slice(0, 10);
  return allTrades.filter(t => {
    const originOk = tradeOriginFilter === 'all'
      || String(t.origin || 'MANUAL').toUpperCase() === tradeOriginFilter;
    if (!originOk) return false;
    if (tradeFilter === 'all') return true;
    const tradeDate = String(t.close_time || t.open_time || '').slice(0, 10);
    if (tradeFilter === 'today') return tradeDate === todayStr;
    if (tradeFilter === 'yesterday') return tradeDate === yesterdayStr;
    if (tradeFilter === 'month') {
      const timestamp = new Date(t.close_time || t.open_time || 0).getTime();
      return Number.isFinite(timestamp) && now - timestamp <= 30 * 24 * 60 * 60e3;
    }
    const ms = Number(tradeFilter);
    const timestamp = new Date(t.close_time || t.open_time || 0).getTime();
    return Number.isFinite(ms) && Number.isFinite(timestamp) && now - timestamp <= ms;
  });
}

let selectedTradeIdx = null;
let selectedTradeRangeStart = null;
let selectedTradeRangeEnd = null;

function renderFilteredTrades() {
  const trades = filteredTrades();
  $('allTrades').innerHTML = trades.length
    ? trades.map((t, i) => tradeRow(t, true, i)).join('')
    : '<tr><td colspan="8" class="empty">Aucun trade sur cette période</td></tr>';
  const wins = trades.filter(t => Number(t.profit) > 0).length;
  const losses = trades.filter(t => Number(t.profit) < 0).length;
  const total = trades.reduce((sum, t) => sum + Number(t.profit || 0), 0);
  $('tradeCount').textContent = trades.length;
  $('tradeWins').textContent = wins;
  $('tradeLosses').textContent = losses;
  $('tradeTotal').textContent = money(total);
  tone($('tradeTotal'), total);
  // Ajouter événements clic sur chaque ligne
  $('allTrades')?.querySelectorAll('tr[data-idx]').forEach(row => {
    row.addEventListener('click', (e) => {
      const idx = parseInt(row.dataset.idx);
      if (e.shiftKey && selectedTradeIdx !== null) {
        // Shift+clic = plage
        selectedTradeRangeStart = Math.min(selectedTradeIdx, idx);
        selectedTradeRangeEnd = Math.max(selectedTradeIdx, idx);
        // Highlight la plage
        $('allTrades').querySelectorAll('tr[data-idx]').forEach(r => {
          const ri = parseInt(r.dataset.idx);
          r.classList.toggle('range-trade', ri >= selectedTradeRangeStart && ri <= selectedTradeRangeEnd);
          r.classList.remove('selected-trade');
        });
        renderTradeRangeDetail(trades, selectedTradeRangeStart, selectedTradeRangeEnd);
      } else {
        // Clic simple = détail du trade
        selectedTradeIdx = idx;
        selectedTradeRangeStart = null;
        selectedTradeRangeEnd = null;
        $('allTrades').querySelectorAll('tr').forEach(r => {
          r.classList.remove('selected-trade', 'range-trade');
        });
        row.classList.add('selected-trade');
        renderTradeDetail(trades[idx]);
      }
    });
  });
}

function renderTradeDetail(t) {
  const detail = $('tradeDetail');
  if (!detail || !t) return;
  const profit = Number(t.profit || 0);
  const time = (t.open_time || '').replace('T', ' ').slice(0, 19);
  const closeTime = (t.close_time || '').replace('T', ' ').slice(0, 19);
  detail.innerHTML = `
    <div class="kv"><span>Date ouverture</span><b>${time}</b></div>
    <div class="kv"><span>Date fermeture</span><b>${closeTime}</b></div>
    <div class="kv"><span>Type</span><b class="${String(t.direction).toLowerCase()}">${t.direction}</b></div>
    <div class="kv"><span>Symbole</span><b>${t.symbol || t.symbol_key || 'XAUUSD'}</b></div>
    <div class="kv"><span>Lot</span><b>${Number(t.lot || 0).toFixed(2)}</b></div>
    <div class="kv"><span>Prix ouverture</span><b>${Number(t.open_price || 0).toFixed(2)}</b></div>
    <div class="kv"><span>Prix fermeture</span><b>${Number(t.close_price || t.price || 0).toFixed(2)}</b></div>
    <div class="kv"><span>Mouvement</span><b>${Number(t.movement || 0).toFixed(2)} pts</b></div>
    <div class="kv"><span>Profit</span><b class="${profit >= 0 ? 'positive' : 'negative'}">${money(profit)}</b></div>
    <div class="kv"><span>Origine</span><b>${t.origin || 'ALPHATRADE'}</b></div>
  `;
}

function renderTradeRangeDetail(trades, from, to) {
  const detail = $('tradeDetail');
  if (!detail) return;
  const range = trades.slice(from, to + 1);
  const total = range.reduce((s, t) => s + Number(t.profit || 0), 0);
  const wins = range.filter(t => Number(t.profit) > 0).length;
  const losses = range.filter(t => Number(t.profit) < 0).length;
  const lots = range.reduce((s, t) => s + Number(t.lot || 0), 0);
  detail.innerHTML = `
    <div class="range-summary">
      <div class="title">Sélection ${range.length} trades</div>
      <div class="kv"><span>Profit total</span><b class="${total >= 0 ? 'positive' : 'negative'}">${money(total)}</b></div>
      <div class="kv"><span>Gains / Pertes</span><b>${wins} / ${losses}</b></div>
      <div class="kv"><span>Lots totaux</span><b>${lots.toFixed(3)}</b></div>
    </div>
    ${range.map(t => {
      const profit = Number(t.profit || 0);
      const time = (t.open_time || '').slice(5, 16);
      return `<div class="day-trade">
        <span class="pill ${String(t.direction).toLowerCase()}">${t.direction}</span>
        <span>${time}</span>
        <span>${Number(t.lot || 0).toFixed(2)}L</span>
        <strong class="${profit >= 0 ? 'positive' : 'negative'}">${money(profit)}</strong>
      </div>`;
    }).join('')}
  `;
}

document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-filter]').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  tradeFilter = button.dataset.filter;
  const selMin = document.getElementById('filterMin');
  const selHour = document.getElementById('filterHour');
  if (selMin) { selMin.value = ''; selMin.classList.remove('active'); }
  if (selHour) { selHour.value = ''; selHour.classList.remove('active'); }
  renderFilteredTrades();
}));

document.getElementById('filterMin').addEventListener('change', function () {
  if (!this.value) return;
  tradeFilter = String(Number(this.value) * 60 * 1000);
  document.getElementById('filterHour').value = '';
  document.getElementById('filterHour').classList.remove('active');
  document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
  this.classList.add('active');
  renderFilteredTrades();
});

document.getElementById('filterHour').addEventListener('change', function () {
  if (!this.value) return;
  tradeFilter = String(Number(this.value) * 60 * 60 * 1000);
  document.getElementById('filterMin').value = '';
  document.getElementById('filterMin').classList.remove('active');
  document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
  this.classList.add('active');
  renderFilteredTrades();
});

document.querySelectorAll('[data-origin-filter]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-origin-filter]').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  tradeOriginFilter = button.dataset.originFilter || 'all';
  renderFilteredTrades();
}));

function renderTrades(trades) {
  allTrades = trades || [];
  const body = allTrades.length ? allTrades.slice(0, 12).map(t => tradeRow(t)).join('') : '<tr><td colspan="7" class="empty">Aucun trade MT5 synchronisé</td></tr>';
  $('recentTrades').innerHTML = body;
  renderFilteredTrades();
  renderLearning();
  renderMarketSessions();
  renderCalendar();
}

function addLogs(lines) {
  const now = Date.now();
  (lines || []).forEach(line => {
    const key = String(line).replace(/^\[[^\]]+\]\s*/, '').trim();
    if (key === lastLogKey && now - lastLogAt < 30000) {
      repeatedLogCount += 1;
      const suffix = ` [répété ${repeatedLogCount + 1} fois]`;
      logLines[logLines.length - 1] = String(logLines[logLines.length - 1]).replace(/ \[répété \d+ fois\]$/, '') + suffix;
      return;
    }
    lastLogKey = key;
    lastLogAt = now;
    repeatedLogCount = 0;
    logLines.push(line);
  });
  logLines = logLines.slice(-300);
  $('journalText').textContent = logLines.join('\n');
  $('journalText').scrollTop = $('journalText').scrollHeight;
}

function fillSettings(values) {
  const source = values || {};
  params = {
    ...JSON.parse(JSON.stringify(defaults)),
    ...JSON.parse(JSON.stringify(source)),
    symbols: {
      XAUUSD: { ...defaults.symbols.XAUUSD, ...(source.symbols?.XAUUSD || {}) }
    }
  };
  const form = $('settingsForm');
  Object.entries(params).forEach(([key, value]) => {
    if (key === 'symbols') return;
    // Cibler uniquement les inputs sans data-sym pour éviter le conflit RadioNodeList
    const input = form.querySelector(`[name="${key}"]:not([data-sym])`);
    if (!input) return;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value;
  });
  document.querySelectorAll('[data-sym]').forEach(input => {
    const value = params.symbols?.[input.dataset.sym]?.[input.name];
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value ?? '';
  });
  if ($('strategyModeToolbar')) $('strategyModeToolbar').value = params.strategy_mode || 'scalping_safe';
  updateStrategyAppliedState(params.strategy_mode || 'scalping_safe');
  updateAssetCards();
  selectEngine(params.active_engine || 'alphatrade_ai');
  renderOriginsTable();
}

const ORIGIN_TYPE_LABELS = {
  INTERNAL_BOT: 'BOT INTERNE', EXTERNAL_AI: 'IA EXTERNE', EXTERNAL_EA: 'EA EXTERNE', MANUAL: 'MANUEL'
};

function renderOriginsTable() {
  const body = $('tradeOriginsBody');
  if (!body || !params) return;
  const origins = params.trade_origins || [];
  body.innerHTML = origins.length ? origins.map((o, i) => `
    <tr>
      <td><span class="origin-name-cell">${o.name}</span></td>
      <td><span class="origin-type-badge ${o.type}">${ORIGIN_TYPE_LABELS[o.type] || o.type}</span></td>
      <td>${(o.magic_numbers || []).join(', ') || '—'}</td>
      <td>${(o.comment_keywords || []).join(', ') || '—'}</td>
      <td><span class="origin-switch ${o.enabled ? 'on' : ''}" data-toggle-origin="${i}"></span></td>
      <td>
        <span class="origin-icon-btn" data-edit-origin="${i}" title="Modifier">✏</span>
        <span class="origin-icon-btn danger" data-delete-origin="${i}" title="Supprimer">🗑</span>
      </td>
    </tr>
  `).join('') : '<tr><td colspan="6" class="empty">Aucune origine configurée</td></tr>';
}

let originModalEditIndex = null;

function openOriginModal(index) {
  originModalEditIndex = index;
  const origin = index === null ? null : (params.trade_origins || [])[index];
  $('originModalTitle').firstChild.textContent = origin ? 'Modifier une origine ' : 'Ajouter une origine ';
  $('originModalSub').textContent = origin ? origin.name : '';
  $('originFieldName').value = origin ? origin.name : '';
  $('originFieldType').value = origin ? origin.type : 'EXTERNAL_AI';
  $('originFieldMagic').value = origin ? (origin.magic_numbers || []).join(', ') : '';
  $('originFieldKeywords').value = origin ? (origin.comment_keywords || []).join(', ') : '';
  $('originFieldEnabled').checked = origin ? Boolean(origin.enabled) : true;
  $('originModal').classList.add('open');
}

function closeOriginModal() {
  $('originModal').classList.remove('open');
  originModalEditIndex = null;
}

$('addOriginBtn')?.addEventListener('click', () => openOriginModal(null));
$('originModalClose')?.addEventListener('click', closeOriginModal);
$('originCancelBtn')?.addEventListener('click', closeOriginModal);
$('originModal')?.addEventListener('click', event => { if (event.target.id === 'originModal') closeOriginModal(); });

$('originSaveBtn')?.addEventListener('click', () => {
  const name = $('originFieldName').value.trim();
  if (!name) return;
  const entry = {
    name,
    type: $('originFieldType').value,
    magic_numbers: $('originFieldMagic').value.split(',').map(v => parseInt(v.trim(), 10)).filter(v => Number.isFinite(v)),
    comment_keywords: $('originFieldKeywords').value.split(',').map(v => v.trim().toLowerCase()).filter(Boolean),
    enabled: $('originFieldEnabled').checked
  };
  if (!params.trade_origins) params.trade_origins = [];
  if (originModalEditIndex === null) params.trade_origins.push(entry);
  else params.trade_origins[originModalEditIndex] = entry;
  renderOriginsTable();
  closeOriginModal();
});

document.getElementById('tradeOriginsBody')?.addEventListener('click', event => {
  const editIdx = event.target.dataset.editOrigin;
  const delIdx = event.target.dataset.deleteOrigin;
  const toggleIdx = event.target.dataset.toggleOrigin;
  if (editIdx !== undefined) openOriginModal(Number(editIdx));
  else if (delIdx !== undefined) {
    params.trade_origins.splice(Number(delIdx), 1);
    renderOriginsTable();
  } else if (toggleIdx !== undefined) {
    const o = params.trade_origins[Number(toggleIdx)];
    o.enabled = !o.enabled;
    renderOriginsTable();
  }
});

function selectEngine(engine) {
  if ($('activeEngineSelect')) $('activeEngineSelect').value = engine;
  document.querySelectorAll('.engine-card[data-engine]').forEach(card => {
    card.classList.toggle('selected', card.dataset.engine === engine);
  });
  if ($('strategieOrPanel')) $('strategieOrPanel').style.display = engine === 'alphatrade_ai' ? '' : 'none';
  if ($('kb1000Panel')) $('kb1000Panel').style.display = engine === 'kb1000_gold_ai' ? '' : 'none';
  if (params) params.active_engine = engine;
}

document.querySelectorAll('.engine-card[data-engine]').forEach(card => {
  card.addEventListener('click', () => selectEngine(card.dataset.engine));
});

function updateAssetCards() {
  const active = $('settingsForm')?.elements.namedItem('active_symbol')?.value || params?.active_symbol || 'XAUUSD';
  document.querySelectorAll('[data-asset-card]').forEach(card => {
    const isActive = card.dataset.assetCard === active;
    card.classList.toggle('active-asset', isActive);
    card.classList.toggle('inactive', !isActive);
    card.querySelectorAll('input, select').forEach(el => { el.disabled = !isActive; });
  });
}

function updateStrategyAppliedState(mode) {
  const profile = strategyProfiles[mode] || strategyProfiles.scalping_safe;
  const label = currentLanguage === 'en' ? profile.labelEn : profile.labelFr;
  if ($('strategyAppliedState')) {
    $('strategyAppliedState').textContent = currentLanguage === 'en'
      ? `Active: ${label}`
      : `Actif : ${label}`;
  }
}

function applyStrategyProfile(mode) {
  const profile = strategyProfiles[mode];
  if (!profile || !params) return;
  params.strategy_mode = mode;
  Object.assign(params, profile.values);
  const form = $('settingsForm');
  Object.entries(profile.values).forEach(([key, value]) => {
    const input = form.elements.namedItem(key);
    if (input) input.value = value;
  });
  if ($('strategyModeToolbar')) $('strategyModeToolbar').value = mode;
  updateStrategyAppliedState(mode);
  const label = currentLanguage === 'en' ? profile.labelEn : profile.labelFr;
  addLogs([currentLanguage === 'en'
    ? `[STRATEGY] ${label} applied: risk, cadence, positions, confidence, duration and target updated.`
    : `[STRATÉGIE] ${label} appliqué : risque, cadence, positions, confiance, durée et objectif mis à jour.`]);
}

function collectSettings(form = $('settingsForm')) {
  const next = JSON.parse(JSON.stringify(params || defaults));
  [...form.elements].forEach(input => {
    if (!input.name || input.dataset.sym || input.disabled) return;
    next[input.name] = input.type === 'checkbox'
      ? input.checked
      : input.type === 'number'
        ? Number(input.value)
        : input.value;
  });
  document.querySelectorAll('[data-sym]').forEach(input => {
    next.symbols[input.dataset.sym][input.name] = input.type === 'checkbox'
      ? input.checked
      : input.type === 'number'
        ? Number(input.value)
        : input.value;
  });
  return next;
}

$('settingsForm').elements.namedItem('active_symbol')?.addEventListener('change', event => {
  activeSymbol = event.target.value;
  if (params) params.active_symbol = activeSymbol;
  updateAssetCards();
  renderTradingView(true);
  renderActiveMarket();
});

$('strategyModeToolbar')?.addEventListener('change', event => {
  applyStrategyProfile(event.target.value);
});

$('advancedSettingsToggle')?.addEventListener('click', event => {
  const scroll = document.querySelector('.settings-scroll');
  const visible = scroll.classList.toggle('show-advanced');
  event.currentTarget.textContent = visible
    ? (currentLanguage === 'en' ? 'Hide advanced settings' : 'Masquer les réglages avancés')
    : (currentLanguage === 'en' ? 'Show advanced settings' : 'Afficher les réglages avancés');
  const label = $('essentialsLabel');
  if (label) {
    label.textContent = visible
      ? (currentLanguage === 'en' ? 'Advanced settings shown' : 'Réglages avancés affichés')
      : (currentLanguage === 'en' ? 'Essential settings shown' : 'Réglages essentiels affichés');
  }
});

$('paramsDocBtn')?.addEventListener('click', () => {
  $('paramsDocModal')?.classList.add('open');
});
$('paramsDocModal')?.addEventListener('click', event => {
  if (event.target.id === 'paramsDocModal') event.target.classList.remove('open');
});

$('settingsForm').addEventListener('submit', async event => {
  event.preventDefault();
  const saveButton = event.currentTarget.querySelector('.save-settings');
  saveButton.classList.remove('saved');
  saveButton.classList.add('saving');
  saveButton.disabled = true;
  saveButton.textContent = currentLanguage === 'en' ? 'Saving...' : 'Enregistrement...';
  const form = event.currentTarget;
  const next = collectSettings(form);
  params = next;
  activeSymbol = next.active_symbol;
  try {
    await alpha.saveParams(next);
    saveButton.classList.remove('saving');
    saveButton.classList.add('saved');
    saveButton.textContent = currentLanguage === 'en' ? 'Settings saved ✓' : 'Paramètres enregistrés ✓';
    addLogs(['[SUCCESS] Paramètres AlphaTrade sauvegardés.']);
    renderStatus(currentStatus);
    setTimeout(() => {
      saveButton.classList.remove('saved');
      saveButton.textContent = currentLanguage === 'en' ? 'Save settings' : 'Sauvegarder les paramètres';
    }, 1800);
  } catch (error) {
    saveButton.classList.remove('saving');
    saveButton.textContent = currentLanguage === 'en' ? 'Save failed' : 'Échec de sauvegarde';
    addLogs([`[ERROR] Sauvegarde impossible: ${error?.message || error}`]);
  } finally {
    saveButton.disabled = false;
  }
});

$('saveDefaultSettings')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  const next = collectSettings();
  button.disabled = true;
  button.textContent = currentLanguage === 'en' ? 'Saving default...' : 'Définition...';
  try {
    await alpha.saveDefaultParams(next);
    await alpha.saveParams(next);
    params = next;
    button.textContent = currentLanguage === 'en' ? 'Default saved ✓' : 'Défaut enregistré ✓';
    addLogs(['[SUCCESS] Paramètres personnels définis comme valeurs par défaut.']);
  } catch (error) {
    button.textContent = currentLanguage === 'en' ? 'Default failed' : 'Échec du défaut';
    addLogs([`[ERROR] Valeurs par défaut impossibles à enregistrer: ${error?.message || error}`]);
  } finally {
    setTimeout(() => {
      button.disabled = false;
      button.textContent = currentLanguage === 'en' ? 'Set as default' : 'Définir par défaut';
    }, 1600);
  }
});

$('resetSettings')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = currentLanguage === 'en' ? 'Resetting...' : 'Réinitialisation...';
  try {
    const personalDefaults = await alpha.loadDefaultParams();
    const restored = personalDefaults || defaults;
    fillSettings(restored);
    await alpha.saveParams(params);
    button.textContent = currentLanguage === 'en' ? 'Settings reset ✓' : 'Paramètres réinitialisés ✓';
    addLogs(['[SUCCESS] Paramètres réinitialisés avec les dernières valeurs définies par défaut.']);
  } catch (error) {
    button.textContent = currentLanguage === 'en' ? 'Reset failed' : 'Échec';
    addLogs([`[ERROR] Réinitialisation impossible: ${error?.message || error}`]);
  } finally {
    setTimeout(() => {
      button.disabled = false;
      button.textContent = currentLanguage === 'en' ? 'Reset' : 'Réinitialiser';
    }, 1600);
  }
});

alpha.onStatus(renderStatus);
alpha.onTrades(renderTrades);
alpha.onLog(addLogs);
if (typeof alpha.onCalendarData === 'function') {
  alpha.onCalendarData(data => { calendarData = data || {}; renderCalendar(); });
}

// ── AUTH ──────────────────────────────────────────────────────────────────────
const API_BASE = 'https://web-production-9312ae.up.railway.app';

async function checkServerStatus() {
  const dot = document.getElementById('serverDot');
  const label = document.getElementById('serverLabel');
  if (!dot || !label) return;
  try {
    const r = await fetch(API_BASE + '/', { signal: AbortSignal.timeout(5000) });
    if (r.ok) {
      dot.style.background = '#00C896';
      label.style.color = '#00C896';
      label.textContent = 'Serveur connecté';
    } else { throw new Error(); }
  } catch {
    dot.style.background = '#FF4444';
    label.style.color = '#FF4444';
    label.textContent = 'Hors ligne';
  }
}
checkServerStatus();
setInterval(checkServerStatus, 30000);

function showLoginOverlay() {
  const ol = document.getElementById('loginOverlay');
  if (ol) ol.classList.remove('hidden');
}

function hideLoginOverlay() {
  const ol = document.getElementById('loginOverlay');
  if (ol) ol.classList.add('hidden');
}

async function applyPlanParamsToEngine(planParams) {
  if (!planParams || !alpha) return;
  const current = await alpha.loadParams();
  if (!current) return;
  const get = (key, altKey) => {
    const v = planParams[key]?.val ?? planParams[altKey]?.val;
    return v !== undefined && v !== null && v !== '' ? v : null;
  };
  const updated = JSON.parse(JSON.stringify(current));
  const dailyTarget = get('daily_target', 'gain_daily');
  if (dailyTarget !== null) updated.daily_target = parseFloat(dailyTarget);
  const sessionLoss = get('session_max_loss', 'seuil_perte_alerte');
  if (sessionLoss !== null) updated.session_max_loss = parseFloat(sessionLoss);
  const confMin = get('confidence_min', 'scalping_confidence_min');
  if (confMin !== null) updated.confidence_min = parseFloat(confMin);
  const lotMax = get('lot_max');
  if (lotMax !== null) {
    for (const sym of Object.keys(updated.symbols || {})) {
      updated.symbols[sym].lot_max = parseFloat(lotMax);
    }
  }
  const maxPos = get('max_positions');
  if (maxPos !== null) updated.auto_max_positions = parseInt(maxPos);
  const rebondEnabled = get('rebond_enabled');
  if (rebondEnabled !== null) updated.rebond_enabled = rebondEnabled === 'true' || rebondEnabled === true;
  const rebondMax = get('rebond_max_active');
  if (rebondMax !== null) updated.rebond_max_active = parseInt(rebondMax);
  const capMin = get('capital_min');
  if (capMin !== null) updated.capital_min = parseFloat(capMin);
  await alpha.saveParams(updated);
}

async function doLogin() {
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');
  const status = document.getElementById('loginStatus');
  errEl.textContent = '';
  if (!email || !password) { errEl.textContent = 'Veuillez remplir tous les champs.'; return; }
  btn.disabled = true;
  btn.textContent = 'Connexion…';
  status.style.display = 'block';
  status.textContent = 'Vérification…';
  // Bypass administrateur local (fonctionne sans API)
  const ADMIN_EMAIL = 'admin@alphatrade.com';
  const ADMIN_PASS  = 'admin1234';
  if (email.toLowerCase() === ADMIN_EMAIL && password === ADMIN_PASS) {
    const adminUser = { id: 1, email: ADMIN_EMAIL, full_name: 'Administrateur', is_admin: true };
    const adminPlan = { name: 'Elite', plan_key: 'elite', active: true, expires_at: null };
    sessionStorage.setItem('at_token', 'local-admin');
    sessionStorage.setItem('at_user', JSON.stringify(adminUser));
    sessionStorage.setItem('at_plan', JSON.stringify(adminPlan));
    hideLoginOverlay();
    showPlanBadge(adminUser, adminPlan);
    btn.disabled = false; btn.textContent = 'Se connecter'; status.style.display = 'none';
    return;
  }
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || 'Identifiants incorrects.'; return; }
    if (!data.user.is_admin && (!data.plan || !data.plan.active)) {
      errEl.textContent = 'Votre abonnement est expiré ou inactif. Contactez le support.';
      return;
    }
    sessionStorage.setItem('at_token', data.token);
    sessionStorage.setItem('at_user', JSON.stringify(data.user));
    sessionStorage.setItem('at_plan', JSON.stringify(data.plan));
    hideLoginOverlay();
    showPlanBadge(data.user, data.plan);
    if (data.plan && data.plan.params) applyPlanParamsToEngine(data.plan.params).catch(() => {});
    loadFullProfile();
  } catch (e) {
    errEl.textContent = 'Impossible de contacter le serveur. Vérifiez votre connexion.';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Se connecter';
    status.style.display = 'none';
  }
}

const PLAN_LIMITS = {
  starter:  { capital_min: '$350',   lot_max: '0.03', max_positions: '2',  gain_session: '$10', gain_daily: '$50',  rebond: 'Non' },
  standard: { capital_min: '$1 000', lot_max: '0.05', max_positions: '4',  gain_session: '$25', gain_daily: '$100', rebond: 'Oui' },
  pro:      { capital_min: '$1 000', lot_max: '0.05', max_positions: '4',  gain_session: '$25', gain_daily: '$100', rebond: 'Oui' },
  premium:  { capital_min: '$2 500', lot_max: '0.10', max_positions: '6',  gain_session: '$40', gain_daily: '$250', rebond: 'Oui' },
  elite:    { capital_min: '$5 000', lot_max: '0.20', max_positions: '8',  gain_session: '$50', gain_daily: '$500', rebond: 'Oui' },
};

function showPlanBadge(user, plan) {
  const isAdmin = Boolean(user && user.is_admin);
  const expires = plan.expires_at ? new Date(plan.expires_at).toLocaleDateString('fr-FR') : '—';
  const planName = isAdmin ? 'Admin' : (plan.name || plan.plan_key || 'Elite');
  const planKey = isAdmin ? 'elite' : (plan.plan_key || 'elite').toLowerCase();
  const limits = PLAN_LIMITS[planKey] || PLAN_LIMITS['elite'];
  const soonExpiring = !isAdmin && plan.expires_at && (new Date(plan.expires_at) - new Date()) < 7 * 24 * 3600 * 1000;

  // Carte colonne gauche
  const card = document.getElementById('accountCard');
  if (card) {
    card.style.display = 'block';
    const el = id => document.getElementById(id);
    if (el('acPlanName')) el('acPlanName').textContent = planName;
    if (el('acEmail')) el('acEmail').textContent = user.email;
    if (el('acExpires')) el('acExpires').textContent = expires;
    if (el('acExpireWarn')) el('acExpireWarn').style.display = soonExpiring ? 'block' : 'none';
  }

  // Page Mon compte
  const el = id => document.getElementById(id);
  const initial = (user.full_name || user.email || 'A')[0].toUpperCase();
  if (el('acAvatar')) el('acAvatar').textContent = initial;
  if (el('acHeroName')) el('acHeroName').textContent = user.full_name || user.email;
  if (el('acHeroEmail')) el('acHeroEmail').textContent = user.email;
  if (el('acHeroPlan')) el('acHeroPlan').textContent = planName;
  if (el('acHeroExpires')) el('acHeroExpires').textContent = expires;
  if (el('acHeroWarn')) el('acHeroWarn').style.display = soonExpiring ? 'flex' : 'none';
  if (el('acCapitalMin')) el('acCapitalMin').textContent = limits.capital_min;
  if (el('acLotMax')) el('acLotMax').textContent = limits.lot_max;
  if (el('acMaxPos')) el('acMaxPos').textContent = limits.max_positions;
  if (el('acGainSession')) el('acGainSession').textContent = limits.gain_session;
  if (el('acGainDaily')) el('acGainDaily').textContent = limits.gain_daily;
  if (el('acRebond')) el('acRebond').textContent = limits.rebond;

  // Bouton Upgrade — visible si pas admin et pas sur le plan le plus haut
  const upgradeBtn = el('acUpgradeBtn');
  if (upgradeBtn) {
    const isTopPlan = isAdmin || planKey === 'elite';
    upgradeBtn.style.display = isTopPlan ? 'none' : 'flex';
  }

  if (el('acInfoEmail')) el('acInfoEmail').textContent = user.email;
  if (el('acInfoPlan')) el('acInfoPlan').textContent = planName;
  if (el('acInfoExpires')) el('acInfoExpires').textContent = expires;

  // Badge titlebar
  const tbCard = document.getElementById('tbAccountCard');
  const tbLogout = document.getElementById('tbLogoutBtn');
  const tbAvatar = document.getElementById('tbAccountAvatar');
  const tbLabel = document.getElementById('tbAccountLabel');
  if (tbCard) { tbCard.style.display = 'flex'; }
  if (tbLogout) { tbLogout.style.display = 'flex'; }
  if (tbAvatar) tbAvatar.textContent = initial;
  if (tbLabel) tbLabel.textContent = user.full_name || user.email || 'Mon compte';
}

async function loadFullProfile() {
  const token = sessionStorage.getItem('at_token');
  if (!token || token === 'local-admin') return;
  try {
    const res = await fetch(`${API_BASE}/user/profile`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const data = await res.json();
    const el = id => document.getElementById(id);
    if (el('acEditName')) el('acEditName').value = data.full_name || '';
    if (el('acEditEmail')) el('acEditEmail').value = data.email || '';
    if (el('acEditPhone')) el('acEditPhone').value = data.phone || '';
    if (el('acEditCountry')) el('acEditCountry').value = data.country || '';
  } catch (_) {}
}

async function saveProfile() {
  const token = sessionStorage.getItem('at_token');
  const errEl = document.getElementById('acEditError');
  const okEl = document.getElementById('acEditSuccess');
  const btn = document.querySelector('.ac-save-btn');
  errEl.textContent = ''; okEl.textContent = '';
  const body = {
    full_name: document.getElementById('acEditName')?.value.trim(),
    email: document.getElementById('acEditEmail')?.value.trim(),
    phone: document.getElementById('acEditPhone')?.value.trim(),
    country: document.getElementById('acEditCountry')?.value.trim(),
  };
  const currentPwd = document.getElementById('acEditCurrentPwd')?.value;
  const newPwd = document.getElementById('acEditNewPwd')?.value;
  if (newPwd) { body.current_password = currentPwd; body.new_password = newPwd; }

  if (token === 'local-admin') {
    okEl.textContent = 'Profil administrateur — modifications locales uniquement.'; return;
  }
  btn.disabled = true; btn.textContent = 'Enregistrement…';
  try {
    const res = await fetch(`${API_BASE}/user/profile`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || 'Erreur lors de la mise à jour.'; return; }
    okEl.textContent = 'Profil enregistré avec succès.';
    // Mettre à jour la carte gauche et les infos héros
    const user = JSON.parse(sessionStorage.getItem('at_user') || '{}');
    Object.assign(user, { full_name: data.user.full_name, email: data.user.email });
    sessionStorage.setItem('at_user', JSON.stringify(user));
    const el = id => document.getElementById(id);
    if (el('acHeroName')) el('acHeroName').textContent = data.user.full_name || data.user.email;
    if (el('acHeroEmail')) el('acHeroEmail').textContent = data.user.email;
    if (el('acEmail')) el('acEmail').textContent = data.user.email;
    if (el('acInfoEmail')) el('acInfoEmail').textContent = data.user.email;
    if (el('acEditCurrentPwd')) el('acEditCurrentPwd').value = '';
    if (el('acEditNewPwd')) el('acEditNewPwd').value = '';
  } catch (_) {
    errEl.textContent = 'Impossible de contacter le serveur.';
  } finally {
    btn.disabled = false; btn.textContent = 'Enregistrer les modifications';
  }
}

window.saveProfile = saveProfile;

function doLogout() {
  sessionStorage.removeItem('at_token');
  sessionStorage.removeItem('at_user');
  sessionStorage.removeItem('at_plan');
  const card = document.getElementById('accountCard');
  if (card) card.style.display = 'none';
  const tbCard = document.getElementById('tbAccountCard');
  const tbLogout = document.getElementById('tbLogoutBtn');
  if (tbCard) tbCard.style.display = 'none';
  if (tbLogout) tbLogout.style.display = 'none';
  showLoginOverlay();
}
window.doLogout = doLogout;

window.showAccountSection = function() {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
  const page = document.getElementById('account');
  if (page) page.classList.add('active');
};

// ── Thème dark / green ────────────────────────────────────────────────────────
let currentTheme = localStorage.getItem('alphatrade-theme') || 'dark';

const THEME_CYCLE = ['dark', 'green', 'red', 'cyan', 'gold'];
const THEME_ICONS = { dark: 'themeIconMoon', green: 'themeIconSun', red: 'themeIconFire', cyan: 'themeIconCyan', gold: 'themeIconGold' };

function applyTheme(theme) {
  currentTheme = theme;
  document.body.classList.remove('theme-green', 'theme-red', 'theme-cyan', 'theme-gold');
  if (theme !== 'dark') document.body.classList.add(`theme-${theme}`);
  localStorage.setItem('alphatrade-theme', theme);
  Object.entries(THEME_ICONS).forEach(([t, id]) => {
    const el = document.getElementById(id);
    if (el) el.style.display = t === theme ? 'block' : 'none';
  });
}

window.toggleTheme = function() {
  const idx = THEME_CYCLE.indexOf(currentTheme);
  applyTheme(THEME_CYCLE[(idx + 1) % THEME_CYCLE.length]);
};

// Appliquer le thème mémorisé au chargement
applyTheme(currentTheme);

// ── Bouton Upgrade ────────────────────────────────────────────────────────────
window.openUpgradePage = function() {
  alpha.openExternal('https://www.myalphatrade.com/tarifs');
};

// ── Auto-update ────────────────────────────────────────────────────────────────
window.startUpdateDownload = function() {
  const btn = $('updateDownloadBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Téléchargement…'; }
  const wrap = $('updateProgressWrap');
  const pct  = $('updateProgressPct');
  if (wrap) wrap.style.display = 'block';
  if (pct)  pct.style.display  = 'inline';
  if (typeof alpha.downloadUpdate === 'function') alpha.downloadUpdate();
};

window.installUpdate = function() {
  if (typeof alpha.installUpdate === 'function') alpha.installUpdate();
};

async function initAuth() {
  const token = sessionStorage.getItem('at_token');
  if (token) {
    try {
      const res = await fetch(`${API_BASE}/auth/verify`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        if (data.valid) {
          hideLoginOverlay();
          const user = JSON.parse(sessionStorage.getItem('at_user') || '{}');
          showPlanBadge(user, data.plan);
          loadFullProfile();
          return;
        }
      }
    } catch (_) {}
    sessionStorage.removeItem('at_token');
  }
  showLoginOverlay();
}

document.addEventListener('DOMContentLoaded', () => {
  initAuth();
  const loginInput = document.getElementById('loginPassword');
  if (loginInput) loginInput.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

  // Listeners mise à jour automatique
  if (typeof alpha.onUpdateAvailable === 'function') {
    alpha.onUpdateAvailable(info => {
      const banner = $('updateBanner');
      const text   = $('updateBannerText');
      if (!banner) return;
      if (text) text.textContent = `Nouvelle version v${info.version} disponible`;
      banner.style.display = 'flex';
    });
  }
  if (typeof alpha.onUpdateProgress === 'function') {
    alpha.onUpdateProgress(prog => {
      const fill = $('updateProgressFill');
      const pct  = $('updateProgressPct');
      if (fill) fill.style.width  = `${prog.percent}%`;
      if (pct)  pct.textContent   = `${prog.percent}%`;
    });
  }
  if (typeof alpha.onUpdateDownloaded === 'function') {
    alpha.onUpdateDownloaded(info => {
      const dl   = $('updateDownloadBtn');
      const inst = $('updateInstallBtn');
      const text = $('updateBannerText');
      const wrap = $('updateProgressWrap');
      const pct  = $('updateProgressPct');
      if (text) text.textContent      = `v${info.version} prête — redémarrez pour installer`;
      if (dl)   dl.style.display      = 'none';
      if (inst) inst.style.display    = 'inline-flex';
      if (wrap) wrap.style.display    = 'none';
      if (pct)  pct.style.display     = 'none';
    });
  }
});

window.doLogin = doLogin;

(async () => {
  const snapshot = await alpha.loadSnapshot();
  fillSettings(snapshot.params || defaults);
  activeSymbol = params.active_symbol || 'XAUUSD';
  if (snapshot.calendarData) { calendarData = snapshot.calendarData; }
  renderTrades(snapshot.trades || []);
  if (snapshot.status) renderStatus(snapshot.status);
  setLanguage(currentLanguage);
})();
