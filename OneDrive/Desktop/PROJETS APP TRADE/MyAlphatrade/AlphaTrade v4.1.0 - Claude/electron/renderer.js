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
let planParamLocks = {}; // {param_key: true} -- verrous poussés par le forfait (17/07/2026)
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
  external_signals_allow_real: false,
  trade_origins: [
    { name: 'AlphaTrade AI', type: 'INTERNAL_BOT', magic_numbers: [20260607], comment_keywords: ['alphatrade', 'alphakaris'], enabled: true },
    { name: 'AVA Assistant', type: 'EXTERNAL_AI', magic_numbers: [7525001], comment_keywords: ['ava', 'bridge'], enabled: true }
  ],
  auto_max_positions: 6,
  session_target: 50,
  daily_target: 500,
  session_max_loss: -200,
  giveback: 100,
  gold_brain_enabled: false,
  caio_min_confidence: 60,
  pending_order_expire_min: 60,
  mission_weekly_target: 0,
  mission_monthly_target: 0,
  mission_consecutive_loss_defense: 3,
  economic_calendar_enabled: true,
  economic_calendar_block_hours: 2.0,
  slack_webhooks: [],
  slack_min_confidence: 70,
  fast_be_enabled: true,
  profit_protection_enabled: true,
  profit_drawdown_pct: 30,
  profit_warning_ratio: .75,
  risk_pct: 0.35,
  real_lot_cap: 0.20,
  demo_lot_cap: 0.20,
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
  rebond_min_loss_trigger: 2.0,
  rebond_target_pips: 1.50,
  rebond_stop_pips: 2.00,
  rebond_max_hold_sec: 90,
  rebond_max_active: 3,
  rebond_fort_enabled: false,
  rebond_fort_min_signal_pct: 80,
  rebond_fort_target_pips: 15.0,
  rebond_fort_stop_pips: 8.0,
  rebond_fort_max_hold_sec: 900,
  rebond_fort_max_attempts: 1,
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
      lot: .03, lot_min: .01, max_positions: 6,
      max_position_loss: 15, max_floating_loss: 50, timeframe: 'M1',
      confidence_min: 70, cadence_sec: 30, max_trades_hour: 120,
      max_hold_sec: 120, position_review_sec: 120,
      profit_target: 1.5,
      momentum_exit_score: 55,
      emergency_loss_limit: 15, min_positive_exit: .05,
      signal_reversal_margin: 7, cooldown_after_loss_sec: 60,
      session_filter_enabled: false, session_start_utc: 8, session_end_utc: 17, stop_before_end_min: 30,
      lot_multiplicateur_renfort: 1.0,
      lot_multiplicateur_rebond: 3.0,
      lot_multiplicateur_rebond_fort: 2.0,
      take_profit_enabled: false,
      take_profit_levels: [
        { threshold: 3.75, pct: 25 },
        { threshold: 7.50, pct: 25 },
        { threshold: 11.25, pct: 25 }
      ],
      take_profit_move_be: true
    }
  }
};

// v5.1.0 -- ces valeurs ne couvrent plus que les champs propres a l'UI
// (risque/session, jamais lus par STRATEGY_PROFILES cote Python). Les champs
// qui existent aussi dans le moteur (confidence_min, cadence_sec,
// position_review_sec, profit_target, max_hold_sec, timeframe) viennent
// desormais de currentStatus.strategy_profiles (source de verite unique
// envoyee par le moteur a chaque cycle) -- corrige la desync deja documentee
// dans l'audit Phase 3 (ces memes champs avaient ici des valeurs differentes
// du Python, silencieusement ecrites dans params.json a la sauvegarde).
const strategyProfilesUiExtras = {
  scalping_fast: { labelFr: 'Scalping rapide', labelEn: 'Fast scalping', values: { risk_pct: .35, auto_max_positions: 3, max_trades_hour: 80, session_target: 20 } },
  scalping_safe: { labelFr: 'Scalping prudent', labelEn: 'Safe scalping', values: { risk_pct: .15, auto_max_positions: 1, max_trades_hour: 25, session_target: 10 } },
  long_analysis: { labelFr: 'Analyse longue', labelEn: 'Long analysis', values: { risk_pct: .2, auto_max_positions: 1, max_trades_hour: 12, session_target: 15 } },
  combined: { labelFr: 'Mode combiné', labelEn: 'Combined mode', values: { risk_pct: .25, auto_max_positions: 2, max_trades_hour: 35, session_target: 15 } }
};

const ENTRY_POLICY_LABELS = {
  immediate: { fr: 'entrée immédiate (marché)', en: 'immediate entry (market)' },
  pending_limit: { fr: 'ordres en attente (limit)', en: 'pending orders (limit)' },
  adaptive: { fr: 'adaptative (le moteur choisit)', en: 'adaptive (engine decides)' },
};

function strategyProfileMeta(mode) {
  const extras = strategyProfilesUiExtras[mode] || strategyProfilesUiExtras.scalping_safe;
  const backend = currentStatus?.strategy_profiles?.[mode];
  const backendValues = backend?.symbols?.XAUUSD || {};
  return {
    labelFr: backend?.label || extras.labelFr,
    labelEn: extras.labelEn,
    entryPolicy: backend?.entry_policy || null,
    // Les valeurs backend (a droite) gagnent toujours sur les valeurs UI par
    // defaut pour les champs en commun -- jamais l'inverse.
    values: { ...extras.values, ...backendValues },
  };
}

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
    fr: ['Tableau de bord', 'Trades', 'Sessions IA', 'Microstructure', 'Sessions marché', 'Calendrier', 'Gold Brain', 'Paramètres', 'Journal', 'Assistant IA'],
    en: ['Dashboard', 'Trades', 'AI Sessions', 'Microstructure', 'Market Sessions', 'Calendar', 'Gold Brain', 'Settings', 'Journal', 'AI Assistant']
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

// ── Écran "Quoi de neuf" (v5.1.0) ──────────────────────────────────────────
// Affiché une fois par version, au premier lancement suivant une mise à jour
// (l'auto-updater installe au redémarrage -- ici on détecte simplement que
// s.version (source de vérité, moteur Python) est plus récente que la
// dernière version vue, mémorisée en localStorage comme alphatrade-language
// /alphatrade-theme). Pour publier une nouvelle version : ajouter une entrée
// en tête de WHATS_NEW_LOG (la plus récente en premier).
const WN_ICONS = {
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
};
const WN_CHECK = '<polyline points="20 6 9 17 4 12"/>';
const WN_CROSS = '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>';
const WN_INFO = '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>';

const WHATS_NEW_LOG = [
  {
    version: '5.1.1',
    items: [
      {
        icon: 'cpu', tag: 'new', title: 'Exécution réelle du Scenario Engine',
        body: `
          <p>Depuis la v5.1.1, le Scenario Engine ne se contente plus d'observer : quand le CAIO valide un scénario, AlphaTrade ouvre réellement une position d'ancrage sur MT5, avec un Stop-Loss et un Take-Profit calculés par le scénario lui-même (zone d'invalidation / cible la plus proche ou la plus loin) — pas les réglages fixes du moteur classique. Des scalps réels peuvent aussi s'ajouter tant que le scénario reste sain, avec un cooldown et un plafond pour ne jamais s'empiler sans limite.</p>
          <div class="wn-sublabel">Ce que ça change concrètement</div>
          <ul class="wn-mech">
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Chaque scénario n'ouvre sa position qu'une seule fois — jamais de tentative en boucle.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Toujours filtré par le bouton Démarrer, la protection de session et le Portfolio Brain — les mêmes garde-fous que le moteur classique.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Coupe-circuit dédié et indépendant : le désactiver ne coupe pas l'observation/l'apprentissage du Scenario Engine, juste l'exécution réelle.</li>
          </ul>`,
        howto: 'Réglable dans Paramètres → carte "Exécution réelle du Scenario Engine" — indépendant de l\'activation générale du Scenario Engine.',
      },
      {
        icon: 'shield', tag: 'new', title: 'Portfolio Brain et Trading Style Engine deviennent actifs',
        body: `
          <p>Ces deux agents, jusqu'ici en observation seule, agissent désormais réellement. Le Portfolio Brain bloque les nouvelles entrées — classiques et Scenario Engine — dès que l'exposition du panier XAUUSD (nombre de positions, lot total, perte flottante en % de l'équité) dépasse les limites configurées. Le Trading Style Engine change réellement le mode de stratégie actif quand le régime de marché et la volatilité réels le justifient, avec un délai minimum entre deux changements pour éviter les allers-retours.</p>
          <div class="wn-sublabel">Ce que ça change concrètement</div>
          <ul class="wn-mech">
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Le Portfolio Brain agit comme filet de sécurité commun entre le moteur classique et le Scenario Engine, pour qu'ils ne s'empilent jamais sans coordination.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Chaque changement automatique de mode est tracé dans le nouvel historique des adaptations IA, avec sa raison.</li>
          </ul>`,
        howto: 'Réglable dans Paramètres → cartes "Portfolio Brain" et "Trading Style Engine" (section pilotée par l\'intelligence).',
      },
      {
        icon: 'star', tag: 'new', title: 'Paramètres pilotés par l\'IA + historique + backtest automatique',
        body: `
          <p>L'onglet Paramètres s'ouvre maintenant sur une section "Piloté par l'intelligence" : les réglages calculés par le Scenario Engine, le CAIO, le Dynamic Position Manager et le Portfolio Brain s'affichent en lecture seule, avec leur valeur actuelle et pourquoi elle existe. Un nouvel historique des adaptations IA journalise chaque ajustement automatique réel (jamais de donnée inventée). Un backtest automatique se relance seul (au démarrage puis toutes les 24h), rejoue l'historique MT5 disponible et affiche trades, winrate, profit, drawdown et meilleures/pires conditions.</p>
          <div class="wn-sublabel">Ce que ça change concrètement</div>
          <ul class="wn-mech">
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Renfort &amp; Rebond et Take Profit / BE sont désormais verrouillés par défaut (le Scenario Engine calcule déjà son propre SL/TP) — un interrupteur "Activer le contrôle manuel" reste disponible sur chaque carte si besoin.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Les objectifs de session et journalier restent modifiables normalement — ce sont des limites de compte, pas des réglages d'analyse.</li>
          </ul>`,
        howto: 'Paramètres → en haut de la page, avant les cartes habituelles.',
      },
      {
        icon: 'shield', tag: 'fix', title: 'Correctifs trouvés en observation réelle',
        body: `
          <p>Deux bugs remontés en conditions réelles cette semaine, corrigés à la racine plutôt qu'en façade.</p>
          <div class="wn-sublabel">Avant / après</div>
          <ul class="wn-mech">
            <li class="before"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">${WN_CROSS}</svg>Avant : le Journal pouvait spammer la même ligne plusieurs fois par seconde — le throttle censé l'empêcher était effacé à chaque cycle par une relecture de fichier à schéma fixe.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Maintenant : le throttle vit en mémoire, plus jamais effacé — une même situation bloquée ne s'affiche plus qu'une fois toutes les 3 secondes.</li>
            <li class="before"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">${WN_CROSS}</svg>Avant : un échec d'envoi Slack (ex: mauvaise URL de Webhook) ne laissait aucune trace visible, nulle part.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Maintenant : ces échecs apparaissent dans le Journal, avec le détail de l'erreur.</li>
          </ul>`,
        howto: 'Aucune action requise — ces correctifs sont automatiques.',
      },
    ],
  },
  {
    version: '5.1.0',
    items: [
      {
        icon: 'cpu', tag: 'new', title: 'Gold AI Brain',
        body: `
          <p>Un nouvel onglet <b>Gold Brain</b> ajoute une couche d'arbitrage indépendante avant chaque entrée réelle sur XAUUSD. Quatre agents spécialisés analysent le marché en parallèle du signal classique, et un cinquième — le CAIO (Chief AI Officer) — arbitre entre leurs avis pour rendre une décision finale GO / NO_TRADE, visible en direct dans l'onglet.</p>
          <div class="wn-sublabel">Les 4 agents consultés</div>
          <ul class="wn-agentlist">
            <li><b>Structure Analyst</b> — identifie le régime de marché (tendance haussière/baissière/range) et les zones offre/demande.</li>
            <li><b>Smart Money Analyst</b> — repère les sweeps de liquidité, Order Blocks, Fair Value Gaps et cassures de structure (BOS/CHOCH).</li>
            <li><b>Risk Manager</b> — vérifie le budget de risque disponible avant d'autoriser toute nouvelle position.</li>
            <li><b>Trading Mission Manager</b> — suit vos objectifs jour/semaine/mois et adapte l'agressivité du système selon vos résultats en cours.</li>
          </ul>
          <div class="wn-sublabel">Ce que ça change concrètement</div>
          <ul class="wn-mech">
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Désactivé par défaut — tant que vous ne l'activez pas, AlphaTrade se comporte exactement comme avant, aucune différence.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Une fois activé, le CAIO n'ajoute qu'un filtre supplémentaire — il peut refuser une entrée, jamais en forcer une que le pipeline classique n'aurait pas déjà validée.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Le panneau se met à jour en continu (toutes les 0.5s) pour observation, même sans tentative d'entrée en cours.</li>
          </ul>`,
        howto: 'Comment l\'utiliser : Paramètres → section "Gold AI Brain" → activez le premier interrupteur. Puis ouvrez l\'onglet <b>Gold Brain</b> pour suivre en direct le raisonnement des 4 agents et la décision du CAIO.',
      },
      {
        icon: 'shield', tag: 'fix', title: 'Correctif de robustesse — Time Stop',
        body: `
          <p>Un audit statistique complet sur 465 trades réels a mis en évidence un cas où une position perdante pouvait rester ouverte indéfiniment — deux positions étaient restées ouvertes <b>127 heures</b> avant d'être stoppées en catastrophe, pour une perte combinée de plus de 500$. La cause : le paramètre "Max hold (s)" ne fermait une position que si elle était déjà en profit — jamais une position en perte.</p>
          <div class="wn-sublabel">Avant / après</div>
          <ul class="wn-mech">
            <li class="before"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">${WN_CROSS}</svg>Avant : une position en perte pouvait rester ouverte sans limite de temps, tant qu'elle ne touchait pas le plancher de protection catastrophique.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Maintenant : dès que "Max hold (s)" est dépassé sur une position toujours en perte, elle est fermée automatiquement — indépendamment du Take Profit, du renfort ou du module Rebond.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Ce filet de sécurité s'ajoute à ceux déjà existants (perte max par position, flottant max, protection catastrophe) — il ne les remplace pas.</li>
          </ul>`,
        howto: 'Réglable dans Paramètres → "Cible profit &amp; Protection" → "Max hold (s)". Valeur par défaut : 2700 secondes (45 minutes) pour le profil Scalping rapide.',
      },
      {
        icon: 'calendar', tag: 'new', title: 'Economic Calendar',
        body: `
          <p>Un 5ᵉ agent Gold Brain surveille les publications économiques à fort impact (NFP, CPI, décisions de la Fed...) sur le dollar — la devise qui influence le plus fortement l'or. Source publique gratuite, mise à jour toutes les 15 minutes.</p>
          <div class="wn-sublabel">Ce que ça change concrètement</div>
          <ul class="wn-mech">
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Ne propose jamais de direction (BUY/SELL) — seulement un niveau de risque.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Bloque toute nouvelle entrée dans la fenêtre configurée avant une publication à fort impact, quelle que soit la confiance des autres agents.</li>
          </ul>`,
        howto: 'Activable dans Paramètres → "Gold AI Brain" → "Activer l\'agent Economic Calendar". Fenêtre de blocage réglable ("Blocage avant publication").',
      },
      {
        icon: 'bell', tag: 'new', title: 'Notifications Slack',
        body: `
          <p>AlphaTrade peut désormais notifier un ou plusieurs canaux Slack — décisions CAIO GO, objectifs jour/semaine/mois atteints, démarrage/arrêt du trading. Chaque canal choisit lui-même quels événements il reçoit.</p>
          <div class="wn-sublabel">Ce que ça change concrètement</div>
          <ul class="wn-mech">
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Via un Webhook entrant Slack — aucune app à publier, aucun jeton à gérer.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Un seuil de confiance minimum filtre les décisions CAIO notifiées — évite d'être submergé si plusieurs dizaines de trades ont lieu dans la journée.</li>
            <li><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">${WN_CHECK}</svg>Aucun canal configuré = aucune notification envoyée, comportement inchangé.</li>
          </ul>`,
        howto: 'Mon compte → "Notifications Slack" → "+ Ajouter un canal Slack" → collez l\'URL de votre Webhook entrant Slack et cochez les événements voulus.',
      },
    ],
  },
];

function wnCompareVersions(a, b) {
  const pa = String(a || '0').split('.').map(n => parseInt(n, 10) || 0);
  const pb = String(b || '0').split('.').map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff > 0 ? 1 : -1;
  }
  return 0;
}

function renderWhatsNewItem(item) {
  const iconPath = WN_ICONS[item.icon] || WN_ICONS.star;
  const tagHtml = item.tag ? `<span class="wn-tag ${item.tag}">${item.tag === 'fix' ? 'Correctif' : 'Nouveau'}</span>` : '';
  return `
    <div class="wn-item">
      <div class="wn-item-head">
        <div class="wn-icon ${item.tag === 'fix' ? 'fix' : ''}">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${iconPath}</svg>
        </div>
        <h3>${item.title} ${tagHtml}</h3>
      </div>
      <div class="wn-body">
        ${item.body}
        <div class="wn-howto">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${WN_INFO}</svg>
          <span>${item.howto}</span>
        </div>
      </div>
    </div>`;
}

function showWhatsNew(entry) {
  const backdrop = $('whatsNewBackdrop');
  if (!backdrop) return;
  if ($('wnVersion')) $('wnVersion').textContent = `v${entry.version}`;
  if ($('wnList')) $('wnList').innerHTML = entry.items.map(renderWhatsNewItem).join('');
  const dots = $('wnDots');
  if (dots) dots.innerHTML = entry.items.map((_, i) => `<span class="${i === 0 ? 'on' : ''}"></span>`).join('');
  backdrop.style.display = 'flex';

  const dismiss = (markSeen) => {
    backdrop.style.display = 'none';
    if (markSeen) localStorage.setItem('alphatrade-whatsnew-seen', entry.version);
  };
  $('wnOkBtn').onclick = () => dismiss(true);
  $('wnLaterBtn').onclick = () => dismiss(false); // ferme sans marquer comme vu -- réapparaît au prochain lancement
  $('wnCloseBtn').onclick = () => dismiss(false);
}

let whatsNewChecked = false;
function maybeShowWhatsNew(version) {
  if (whatsNewChecked || !version) return;
  whatsNewChecked = true;
  const entry = WHATS_NEW_LOG.find(e => e.version === version);
  if (!entry) return; // pas de notes pour cette version -- ne rien afficher plutot que deviner
  const lastSeen = localStorage.getItem('alphatrade-whatsnew-seen') || '0.0.0';
  if (wnCompareVersions(version, lastSeen) > 0) showWhatsNew(entry);
}

function renderStatus(s) {
  if (!s) return;
  currentStatus = s;
  // 06/08/2026 -- Louis : "les écrans dans paramètres qui n'actualisent pas".
  // La carte "Piloté par l'IA" lisait le `params` global, rempli une seule
  // fois par fillSettings() au démarrage — un calibrage cote Python restait
  // invisible sans redémarrer l'app. s.live_params (voir status_payload())
  // porte les seuls champs affichés par cette carte ; on les fusionne dans
  // `params` a chaque tick avant de la re-rendre, sans toucher au reste du
  // formulaire (donc sans risque d'écraser une saisie en cours ailleurs).
  if (s.live_params && params) Object.assign(params, s.live_params);
  renderIntelCards(); // valeurs ET footers ("Calibré"/"Jamais ajusté") à jour à chaque tick
  if (s.version) maybeShowWhatsNew(s.version);
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
  // 05/08/2026 -- affichage en lecture seule du lot auto-calculé (voir carte
  // Renfort & Rebond > "Lot calculé (auto)") -- lotSafety.effective_lot est
  // désormais la SEULE source, plus aucun champ manuel ne l'influence.
  const lotCalcEl = $('lotCalculatedInfo');
  if (lotCalcEl) {
    lotCalcEl.textContent = lotSafety.rejected
      ? '0.00 (refusé)'
      : lotSafety.effective_lot ? Number(lotSafety.effective_lot).toFixed(3) : '—';
  }
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
  renderGoldBrain(s);
  renderAiAdaptations(s);
  renderAutoBacktest(s);
  if (currentLanguage === 'en') translateStatic('en');
}

// v5.1.1, 05/08/2026 -- Backtest automatique intelligent (section 7 de la
// refonte Paramètres). `s.auto_backtest` vient de auto_backtest_result.json
// cote Python -- reutilise le Scenario Replay/Learning deja existants et
// testes, pas de resultat invente cote UI.
const SESSION_LABELS_BT = { london: 'Londres', new_york: 'New York', asian: 'Asiatique', london_ny_overlap: 'Chevauchement Londres/NY' };
const TREND_LABELS_BT = { UPTREND: 'Haussière', DOWNTREND: 'Baissière', RANGE: 'Range', CORRECTION: 'Correction' };
function renderAutoBacktest(s) {
  const body = $('autoBacktestBody');
  if (!body) return;
  const bt = s?.auto_backtest;
  if (!bt) {
    body.innerHTML = '<div class="history-empty"><span class="he-icon">⏳</span><span>Premier rejeu pas encore terminé — se déclenche automatiquement au démarrage puis toutes les 24h.</span></div>';
    return;
  }
  const fmtLabel = (map, key) => key ? (map[key] || key) : '—';
  body.innerHTML = `
    <div class="backtest-period">Période testée : ${bt.period_from || '—'} → ${bt.period_to || '—'} (${bt.period_days || '—'} j) · calculé le ${bt.computed_at ? new Date(bt.computed_at).toLocaleString('fr-FR') : '—'}</div>
    <div class="backtest-stats">
      <div class="bs-item"><label>Trades résolus</label><strong>${bt.n_trades ?? '—'}</strong></div>
      <div class="bs-item"><label>Winrate</label><strong>${bt.winrate != null ? bt.winrate + ' %' : '—'}</strong></div>
      <div class="bs-item"><label>Profit (pts)</label><strong style="color:${(bt.total_profit_points || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${bt.total_profit_points ?? '—'}</strong></div>
      <div class="bs-item"><label>Drawdown max (pts)</label><strong style="color:var(--red)">${bt.max_drawdown_points ?? '—'}</strong></div>
    </div>
    <div class="backtest-conditions">
      <span>Meilleure session : <b>${fmtLabel(SESSION_LABELS_BT, bt.best_session)}</b></span>
      <span>Pire session : <b>${fmtLabel(SESSION_LABELS_BT, bt.worst_session)}</b></span>
      <span>Meilleure tendance : <b>${fmtLabel(TREND_LABELS_BT, bt.best_trend)}</b></span>
      <span>Pire tendance : <b>${fmtLabel(TREND_LABELS_BT, bt.worst_trend)}</b></span>
    </div>`;
}

// v5.1.1, 05/08/2026 -- Historique reel des adaptations IA (section 6 de la
// refonte Parametres demandee par Louis). `s.ai_adaptations` vient de
// recent_ai_adaptations() cote Python -- jamais fabrique, uniquement des
// evenements reellement journalises (log_ai_adaptation()).
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function renderAiAdaptations(s) {
  const list = $('aiAdaptationsList');
  if (!list) return;
  const entries = Array.isArray(s?.ai_adaptations) ? s.ai_adaptations : [];
  if (!entries.length) {
    list.innerHTML = '<div class="history-empty"><span class="he-icon">📭</span><span>Aucun ajustement automatique appliqué pour l\'instant.</span></div>';
    return;
  }
  const moduleLabels = {
    trading_style_engine: 'Trading Style Engine',
    scenario_learning: 'Scenario Learning',
  };
  list.innerHTML = entries.map(e => {
    const at = e.at ? new Date(e.at) : null;
    const dateStr = at ? at.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) : '--';
    const timeStr = at ? at.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '--:--';
    return `
      <div class="history-row">
        <span class="hr-date">${dateStr}<br>${timeStr}</span>
        <div class="hr-body">
          <strong>${escapeHtml(e.parameter || '')}</strong>
          <span class="arrow">→</span>
          <strong>${escapeHtml(String(e.old_value))} → ${escapeHtml(String(e.new_value))}</strong>
          <p>${escapeHtml(e.reason || '')}</p>
        </div>
        <span class="hr-source">${escapeHtml(moduleLabels[e.module] || e.module || '')}</span>
      </div>`;
  }).join('');
}

function renderMicrostructurePage() {
  if (!currentStatus) return;
  const micro = currentStatus.microstructure || {};
  const snapshots = micro.snapshots || {};
  // OBI/OFI/Kyle λ/POC XAUUSD retires le 05/08/2026 (carnet d'ordres non
  // fourni par ce broker, restait N/D en permanence, jamais lu par une
  // decision) -- remplaces par le bloc Gold Microstructure Engine plus bas.
  // Hyperliquid (laboratoire crypto separe) reste observe ici.
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
  set('microPageMode', micro.mode === 'OBSERVATION_ONLY' ? 'OBSERVATION UNIQUEMENT' : 'INACTIF');
  set('microDecisionSignal', `${decision.signal || 'WAIT'} ${decision.confidence != null ? `${Number(decision.confidence).toFixed(1)}%` : ''}`);
  set('microDecisionState', decision.eligible ? 'Entrée autorisée' : 'Entrée bloquée');
  set('microBlockedCount', blockedDecisionCount);
  set('microBlockedDuration', blockedDecisionSince ? formatDuration(Math.floor((now - blockedDecisionSince) / 1000)) : '-');
  set('microDecisionReason', reason || 'Aucune décision disponible.');
  set('microHyperState', hyperOnline ? 'Actif' : params?.hyperliquid_observer_enabled ? 'Connexion en attente' : 'Désactivé');
  set('microError', micro.last_error ? `Erreur de collecte : ${micro.last_error}` : 'Aucune erreur de collecte.');

  // Gold Microstructure Engine (v5.1.1, chantier 2) -- alimente reellement
  // scenario_confidence/evaluate_scalp_opportunity().
  const gold = micro.gold || {};
  const goldUnavailable = $('microGoldUnavailable');
  const goldContent = $('microGoldContent');
  if (!gold.available) {
    if (goldUnavailable) { goldUnavailable.style.display = 'block'; goldUnavailable.textContent = gold.reason || 'En attente de bougies XAUUSD récentes.'; }
    if (goldContent) goldContent.style.display = 'none';
  } else {
    if (goldUnavailable) goldUnavailable.style.display = 'none';
    if (goldContent) goldContent.style.display = 'block';
    set('microGoldVelocity', `${gold.velocity > 0 ? '+' : ''}${Number(gold.velocity).toFixed(3)}`);
    set('microGoldAcceleration', `${gold.acceleration > 0 ? '+' : ''}${Number(gold.acceleration).toFixed(3)}`);
    const sizeTrend = Number(gold.size_trend);
    set('microGoldSizeTrend', `${sizeTrend.toFixed(2)}× ${sizeTrend < 0.85 ? '(contraction)' : sizeTrend > 1.15 ? '(expansion)' : '(stable)'}`);
    set('microGoldTimeframe', gold.timeframe || '—');
    const buy = gold.buy || {};
    const sell = gold.sell || {};
    if ($('microGoldBuyScore')) $('microGoldBuyScore').innerHTML = `${Math.round(buy.score || 0)}<small>/100</small>`;
    if ($('microGoldBuyBar')) $('microGoldBuyBar').style.width = `${Math.max(0, Math.min(100, buy.score || 0))}%`;
    set('microGoldBuyRejection', `${Math.round(buy.rejection || 0)}/100`);
    if ($('microGoldSellScore')) $('microGoldSellScore').innerHTML = `${Math.round(sell.score || 0)}<small>/100</small>`;
    if ($('microGoldSellBar')) $('microGoldSellBar').style.width = `${Math.max(0, Math.min(100, sell.score || 0))}%`;
    set('microGoldSellRejection', `${Math.round(sell.rejection || 0)}/100`);
  }
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

// 05/08/2026 -- calendarStats() faisait un allTrades.filter() COMPLET pour
// CHAQUE jour de la grille (42 cellules) à chaque rendu -- donc jusqu'à
// 42 balayages entiers de l'historique par clic, plus l'historique grossit
// plus c'est lent. Constat de Louis en direct : "il faut cliquer plusieurs
// fois, comme si ça pèse". groupTradesByDay() ne fait plus qu'UN seul
// passage sur allTrades ; calendarStats() accepte ce regroupement en
// paramètre optionnel (rétrocompatible avec les appels hors grille,
// renderCalendarDetail/renderCalendarRange, qui n'appellent que sur UNE clé).
function groupTradesByDay(trades) {
  const map = new Map();
  for (const t of trades) {
    const key = tradeDay(t);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(t);
  }
  return map;
}

function calendarStats(key, tradesByDay) {
  const session = $('calendarSessionFilter')?.value || 'all';
  const dayTrades = tradesByDay ? (tradesByDay.get(key) || []) : allTrades.filter(t => tradeDay(t) === key);
  // Trades récents disponibles en mémoire (pour la vue détail)
  const recentTrades = dayTrades.filter(t => tradeInSessionFilter(t, session));

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

// 05/08/2026 -- root cause reel du "il faut cliquer plusieurs fois" (constat
// de Louis en direct) : renderStatus() appelle renderCalendar() a CHAQUE
// status-update, et status.json est reecrit par le moteur Python toutes les
// 100ms (voir watchData() dans main.js) -- la grille entiere (42 boutons)
// etait donc detruite et reconstruite ~10 fois par seconde, en continu,
// meme quand rien de pertinent pour le calendrier n'avait change. Un clic
// utilisateur dure largement plus de 100ms : il tombait tres souvent sur un
// bouton en train d'etre remplace, d'ou l'impression de clic qui "ne prend
// pas". Fix : ne reconstruire que si quelque chose de reellement pertinent
// a change depuis le dernier rendu (empreinte legere, pas une comparaison
// profonde) -- les clics/navigations, qui changent forcement l'empreinte
// (selection/plage/mois), continuent de re-rendre normalement.
let lastCalendarFingerprint = null;

function renderCalendar() {
  const grid = $('calendarGrid');
  if (!grid) return;
  const lastTrade = allTrades[allTrades.length - 1];
  const fingerprint = [
    calendarCursor.getFullYear(), calendarCursor.getMonth(),
    calendarSelected || '', calendarRangeStart || '', calendarRangeEnd || '',
    allTrades.length, lastTrade ? (lastTrade.close_time || lastTrade.open_time || '') : '',
    Object.keys(calendarData || {}).length,
    $('calendarSessionFilter')?.value || 'all',
  ].join('|');
  if (fingerprint === lastCalendarFingerprint && grid.children.length) return;
  lastCalendarFingerprint = fingerprint;
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
  const tradesByDay = groupTradesByDay(allTrades); // un seul passage pour les 42 cellules, pas 42
  const cells = [];
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const key = dayKey(d);
    const st = calendarStats(key, tradesByDay);
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
    } else if (!calendarRangeStart && key === calendarSelected) {
      // 05/08/2026, demande de Louis : re-cliquer sur le jour déjà sélectionné
      // le désélectionne (avant : impossible de désélectionner sans en
      // choisir un autre).
      calendarSelected = null;
      renderCalendar();
      const detail = $('calendarDetail');
      if (detail) detail.innerHTML = `<div class="calendar-empty">${currentLanguage === 'en' ? 'Select a day to see its detail.' : 'Sélectionnez un jour pour voir son détail.'}</div>`;
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
  renderSlackWebhooksTable();
  renderTakeProfitLevels();
  applyParamLocksToUI();
  syncGoldBrainToggle();
  renderIntelCards();
  initLegacyLocks();
}

// v5.1.1, 05/08/2026 -- carte "Piloté par l'intelligence" (section 5 de la
// refonte Paramètres demandée par Louis). Valeurs REELLES lues dans params
// (defauts DEFAULT_PARAMS cote Python, ou override utilisateur si present) --
// jamais de valeur inventee cote UI.
// 05/08/2026 -- footers "Défaut / Jamais ajusté" branchés sur les VRAIES
// adaptations (currentStatus.ai_adaptations, alimenté par
// calibrate_scenario_thresholds() cote Python) au lieu du texte statique
// d'origine (bug releve par Louis : "ça ne doit pas être un message
// statique"). Ne couvre que les 4 seuils reellement calibres aujourd'hui --
// les autres cartes restent honnetement "Réglage fixe" (voir
// scenario_threshold_adjustments() pour pourquoi).
// icScalpCooldownFoot/icScalpMaxFoot/icPortfolioWarnFoot/icPortfolioCriticalFoot
// ajoutés le 06/08/2026 (tasks #173/#174) : ces 4 seuils sont désormais
// réellement calibrables (voir calibrate_scenario_thresholds(), blocs 2/3,
// alphatrade_engine.py) -- scenario_scalp_lot_ratio reste volontairement
// "Réglage fixe" (aucune clé ici), voir scalp_threshold_adjustments()
// pour pourquoi.
const IC_CALIBRATED_FOOTERS = {
  icCaioConfidenceFoot: 'scenario_caio_min_confidence',
  icLondonConfidenceFoot: 'scenario_london_min_confidence',
  icHealthThresholdFoot: 'scenario_health_degradation_threshold',
  icCorrectionBlockedFoot: 'scenario_block_correction_regime',
  icScalpCooldownFoot: 'scenario_scalp_cooldown_sec',
  icScalpMaxFoot: 'scenario_scalp_max_count',
  icPortfolioWarnFoot: 'portfolio_floating_loss_warn_pct',
  icPortfolioCriticalFoot: 'portfolio_floating_loss_critical_pct',
};

function renderIntelCardFooters() {
  const adaptations = currentStatus?.ai_adaptations || [];
  Object.entries(IC_CALIBRATED_FOOTERS).forEach(([footId, paramKey]) => {
    const foot = $(footId);
    if (!foot) return;
    // Le plus recent en dernier dans le tableau -- on cherche a partir de la fin.
    let last = null;
    for (let i = adaptations.length - 1; i >= 0; i--) {
      if (adaptations[i]?.parameter === paramKey) { last = adaptations[i]; break; }
    }
    if (last) {
      const d = new Date(last.at);
      const dateStr = isNaN(d) ? last.at : d.toLocaleDateString(currentLanguage === 'en' ? 'en-US' : 'fr-FR');
      foot.innerHTML = `<span>Calibré (58j réels)</span><span title="${escapeHtml(last.reason || '')}">${dateStr}</span>`;
    } else {
      foot.innerHTML = `<span>Défaut</span><span>Jamais ajusté</span>`;
    }
  });
}

function renderIntelCards() {
  if (!params) return;
  const set = (id, text) => { const el = $(id); if (el) el.textContent = text; };
  set('icCaioConfidence', `${Number(params.scenario_caio_min_confidence ?? 60).toFixed(1)}`);
  set('icLondonConfidence', `${Number(params.scenario_london_min_confidence ?? 70).toFixed(1)}`);
  set('icHealthThreshold', `${Number(params.scenario_health_degradation_threshold ?? 45).toFixed(1)}`);
  set('icScalpCooldown', `${Number(params.scenario_scalp_cooldown_sec ?? 45)} sec`);
  set('icScalpMax', `${Number(params.scenario_scalp_max_count ?? 3)}`);
  set('icScalpLot', `${Math.round(Number(params.scenario_scalp_lot_ratio ?? 0.5) * 100)} %`);
  set('icCorrectionBlocked', params.scenario_block_correction_regime === false ? 'Autorisé' : 'Bloqué');
  set('icPortfolioWarn', `${Number(params.portfolio_floating_loss_warn_pct ?? 2.0).toFixed(1)} %`);
  set('icPortfolioCritical', `${Number(params.portfolio_floating_loss_critical_pct ?? 5.0).toFixed(1)} %`);
  renderIntelCardFooters();

  const execOn = params.scenario_engine_execution_enabled !== false && params.scenario_engine_enabled === true;
  const dot = $('scenarioExecDot');
  const pill = $('scenarioExecPill');
  const detail = $('scenarioExecDetail');
  if (dot) dot.classList.toggle('off', !execOn);
  if (pill) {
    pill.classList.toggle('off', !execOn);
    pill.textContent = execOn ? 'Active' : 'Inactive';
  }
  if (detail) {
    detail.textContent = execOn
      ? 'Un scénario validé par le CAIO peut ouvrir une vraie position MT5.'
      : (params.scenario_engine_enabled ? 'Génère et journalise des scénarios, mais n\'exécute aucun ordre réel.' : 'Scenario Engine désactivé.');
  }
}

// v5.1.1, 05/08/2026 -- verrouillage manuel/auto (proposition de Louis) pour
// Renfort/Rebond et Take Profit : verrouille par defaut au demarrage de
// chaque session app (jamais persiste -- un choix reflechi a chaque fois,
// pas un etat oublie).
function initLegacyLocks() {
  document.querySelectorAll('.legacy-lock-wrap').forEach(wrap => wrap.classList.remove('unlocked'));
}
document.addEventListener('click', event => {
  const unlockId = event.target.closest('[data-unlock]')?.dataset.unlock;
  if (unlockId) { document.getElementById(unlockId)?.classList.add('unlocked'); return; }
  const relockId = event.target.closest('[data-relock]')?.dataset.relock;
  if (relockId) { document.getElementById(relockId)?.classList.remove('unlocked'); }
});

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

// ── Notifications Slack (v5.1.0) — table dynamique, meme pattern que les origines de trades ──
const SLACK_EVENT_LABELS = {
  caio_go: 'Décision CAIO GO',
  mission_target: 'Objectif atteint',
  trading_toggle: 'Démarrage/arrêt',
};

// Ce panneau vit sur la page Mon compte, hors du formulaire Paramètres (dont
// la sauvegarde se fait via un bouton global) -- chaque modification doit
// donc se sauvegarder elle-même immédiatement, comme le fait déjà le
// bouton Gold Brain sur le tableau de bord.
async function persistSlackParams() {
  if (!params) return;
  try {
    await alpha.saveParams(params);
  } catch (error) {
    addLogs([`[ERROR] Sauvegarde Slack impossible: ${error?.message || error}`]);
  }
}

function renderSlackWebhooksTable() {
  const body = $('slackWebhooksBody');
  if (!body || !params) return;
  const slider = $('slackMinConfidence');
  if (slider) {
    slider.value = params.slack_min_confidence ?? 70;
    if ($('slackMinConfVal')) $('slackMinConfVal').textContent = `${slider.value}%`;
  }
  const webhooks = params.slack_webhooks || [];
  body.innerHTML = webhooks.length ? webhooks.map((w, i) => `
    <tr>
      <td><span class="origin-name-cell">${w.name || '—'}</span></td>
      <td>${(w.events || []).map(e => SLACK_EVENT_LABELS[e] || e).join(', ') || '—'}</td>
      <td><span class="origin-switch ${w.enabled ? 'on' : ''}" data-toggle-slack="${i}"></span></td>
      <td>
        <span class="origin-icon-btn" data-edit-slack="${i}" title="Modifier">✏</span>
        <span class="origin-icon-btn danger" data-delete-slack="${i}" title="Supprimer">🗑</span>
      </td>
    </tr>
  `).join('') : '<tr><td colspan="4" class="empty">Aucun canal Slack configuré</td></tr>';
}

let slackModalEditIndex = null;

function openSlackModal(index) {
  slackModalEditIndex = index;
  const w = index === null ? null : (params.slack_webhooks || [])[index];
  $('slackModalTitle').firstChild.textContent = w ? 'Modifier un canal Slack ' : 'Ajouter un canal Slack ';
  $('slackModalSub').textContent = w ? w.name : '';
  $('slackFieldName').value = w ? w.name : '';
  $('slackFieldUrl').value = w ? w.webhook_url : '';
  const events = w ? (w.events || []) : [];
  $('slackEventGo').checked = events.includes('caio_go');
  $('slackEventMission').checked = events.includes('mission_target');
  $('slackEventToggle').checked = events.includes('trading_toggle');
  $('slackFieldEnabled').checked = w ? Boolean(w.enabled) : true;
  $('slackModal').classList.add('open');
}

function closeSlackModal() {
  $('slackModal').classList.remove('open');
  slackModalEditIndex = null;
}

$('addSlackWebhookBtn')?.addEventListener('click', () => openSlackModal(null));
$('slackModalClose')?.addEventListener('click', closeSlackModal);
$('slackCancelBtn')?.addEventListener('click', closeSlackModal);
$('slackModal')?.addEventListener('click', event => { if (event.target.id === 'slackModal') closeSlackModal(); });

$('slackSaveBtn')?.addEventListener('click', () => {
  const name = $('slackFieldName').value.trim();
  const webhookUrl = $('slackFieldUrl').value.trim();
  if (!name || !webhookUrl) return;
  const events = [];
  if ($('slackEventGo').checked) events.push('caio_go');
  if ($('slackEventMission').checked) events.push('mission_target');
  if ($('slackEventToggle').checked) events.push('trading_toggle');
  const entry = { name, webhook_url: webhookUrl, events, enabled: $('slackFieldEnabled').checked };
  if (!params.slack_webhooks) params.slack_webhooks = [];
  if (slackModalEditIndex === null) params.slack_webhooks.push(entry);
  else params.slack_webhooks[slackModalEditIndex] = entry;
  renderSlackWebhooksTable();
  closeSlackModal();
  persistSlackParams();
});

document.getElementById('slackWebhooksBody')?.addEventListener('click', event => {
  const editIdx = event.target.dataset.editSlack;
  const delIdx = event.target.dataset.deleteSlack;
  const toggleIdx = event.target.dataset.toggleSlack;
  if (editIdx !== undefined) openSlackModal(Number(editIdx));
  else if (delIdx !== undefined) {
    params.slack_webhooks.splice(Number(delIdx), 1);
    renderSlackWebhooksTable();
    persistSlackParams();
  } else if (toggleIdx !== undefined) {
    const w = params.slack_webhooks[Number(toggleIdx)];
    w.enabled = !w.enabled;
    renderSlackWebhooksTable();
    persistSlackParams();
  }
});

$('slackMinConfidence')?.addEventListener('input', event => {
  if ($('slackMinConfVal')) $('slackMinConfVal').textContent = `${event.currentTarget.value}%`;
});
$('slackMinConfidence')?.addEventListener('change', event => {
  if (!params) return;
  params.slack_min_confidence = Number(event.currentTarget.value);
  persistSlackParams();
});

let PLAN_MAX_TP_LEVELS = 6; // plafonné par forfait via applyPlanParamsToEngine() (17/07/2026)

function renderTakeProfitLevels() {
  const wrap = $('takeProfitLevels');
  if (!wrap || !params) return;
  const sym = params.symbols.XAUUSD;
  if (!sym.take_profit_levels) sym.take_profit_levels = [];
  const levels = sym.take_profit_levels;
  wrap.innerHTML = levels.length ? levels.map((lvl, i) => `
    <div class="tp-level-row">
      <span class="tp-level-num">TP${i + 1}</span>
      <label>Seuil $<input type="number" step="0.05" min="0.05" value="${lvl.threshold}" data-tp-field="threshold" data-tp-index="${i}"></label>
      <label>% fermé<input type="number" step="5" min="5" max="100" value="${lvl.pct}" data-tp-field="pct" data-tp-index="${i}"></label>
      <label>Trailing $<input type="number" step="0.05" min="0" value="${lvl.trailing || 0}" data-tp-field="trailing" data-tp-index="${i}" title="Ferme ce palier si le profit retombe de ce montant depuis son pic, avant même d'atteindre le seuil. 0 = désactivé, Break-Even reste alors le seul filet de secours."></label>
      <button type="button" class="tp-level-remove" data-tp-remove="${i}" ${levels.length <= 1 ? 'disabled' : ''}>✕</button>
    </div>
  `).join('') : '<p class="mini-help">Aucun Take Profit configuré.</p>';
  const addBtn = $('addTakeProfitLevelBtn');
  if (addBtn) {
    addBtn.disabled = levels.length >= PLAN_MAX_TP_LEVELS;
    addBtn.textContent = levels.length >= PLAN_MAX_TP_LEVELS
      ? `Maximum ${PLAN_MAX_TP_LEVELS} Take Profit atteint`
      : '+ Ajouter un Take Profit';
  }
}

$('takeProfitLevels')?.addEventListener('input', event => {
  const index = event.target.dataset.tpIndex;
  const field = event.target.dataset.tpField;
  if (index === undefined || !field || !params) return;
  const level = params.symbols.XAUUSD.take_profit_levels?.[Number(index)];
  if (!level) return;
  level[field] = Number(event.target.value) || 0;
});

$('takeProfitLevels')?.addEventListener('click', event => {
  const removeIdx = event.target.dataset.tpRemove;
  if (removeIdx === undefined || !params) return;
  const levels = params.symbols.XAUUSD.take_profit_levels;
  if (!levels || levels.length <= 1) return;
  levels.splice(Number(removeIdx), 1);
  renderTakeProfitLevels();
});

$('addTakeProfitLevelBtn')?.addEventListener('click', () => {
  if (!params) return;
  const sym = params.symbols.XAUUSD;
  if (!sym.take_profit_levels) sym.take_profit_levels = [];
  if (sym.take_profit_levels.length >= PLAN_MAX_TP_LEVELS) return;
  const last = sym.take_profit_levels[sym.take_profit_levels.length - 1] || { threshold: 0, pct: 20, trailing: 0 };
  sym.take_profit_levels.push({ threshold: Math.round((last.threshold + 3.75) * 100) / 100, pct: 20, trailing: 0 });
  renderTakeProfitLevels();
});

// Accordéon des cartes Paramètres — ajouté le 17/07/2026 (demande de Louis,
// évite le mur de champs visible d'un coup). État persistant par carte.
document.querySelectorAll('.settings-scroll .panel-title.collapsible').forEach(title => {
  const panel = title.closest('.panel');
  if (!panel) return;
  const key = `alphatrade-acc-${title.textContent.trim().replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`;
  const stored = localStorage.getItem(key);
  const collapsed = stored === null ? true : stored === '1';
  panel.classList.toggle('collapsed', collapsed);
  title.addEventListener('click', () => {
    const nowCollapsed = panel.classList.toggle('collapsed');
    localStorage.setItem(key, nowCollapsed ? '1' : '0');
  });
});

function selectEngine(engine) {
  if ($('activeEngineSelect')) $('activeEngineSelect').value = engine;
  document.querySelectorAll('.engine-card[data-engine]').forEach(card => {
    card.classList.toggle('selected', card.dataset.engine === engine);
  });
  // Seule la génération du signal reste propre à chaque moteur (Stratégie Or
  // ci-dessous) — lot, TP, trailing et protections sont partagés (plus de
  // classe ata-engine-only dessus).
  document.querySelectorAll('.ata-engine-only').forEach(panel => {
    panel.style.display = engine === 'alphatrade_ai' ? '' : 'none';
  });
  if ($('externalSignalPanel')) $('externalSignalPanel').style.display = engine === 'external_signal' ? '' : 'none';
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
  const profile = strategyProfileMeta(mode);
  const label = currentLanguage === 'en' ? profile.labelEn : profile.labelFr;
  if ($('strategyAppliedState')) {
    $('strategyAppliedState').textContent = currentLanguage === 'en'
      ? `Active: ${label}`
      : `Actif : ${label}`;
  }
}

function applyStrategyProfile(mode) {
  const profile = strategyProfileMeta(mode);
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
  const policyLabel = profile.entryPolicy
    ? (ENTRY_POLICY_LABELS[profile.entryPolicy]?.[currentLanguage === 'en' ? 'en' : 'fr'] || profile.entryPolicy)
    : null;
  addLogs([currentLanguage === 'en'
    ? `[STRATEGY] ${label} applied: risk, cadence, positions, confidence, duration and target updated.${policyLabel ? ` Entry policy: ${policyLabel}.` : ''}`
    : `[STRATÉGIE] ${label} appliqué : risque, cadence, positions, confiance, durée et objectif mis à jour.${policyLabel ? ` Politique d'entrée : ${policyLabel}.` : ''}`]);
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
  try {
    // collectSettings() deplace a l'interieur du try (05/08/2026) : si elle
    // levait une exception (DOM inattendu), le bouton restait bloque sur
    // "Enregistrement..." sans aucun message d'erreur -- exactement le
    // symptome "je clique, rien ne se passe" remonte par Louis.
    const next = collectSettings(form);
    params = next;
    activeSymbol = next.active_symbol;
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

// ── Gold AI Brain (v5.1.0) ──────────────────────────────────────────────────
const GB_PRIO_CLASS = { CRITICAL: 'critical', HIGH: 'high', MEDIUM: 'medium', LOW: 'low' };
const GB_MODE_CLASS = { Normal: 'normal', Prudent: 'prudent', Defense: 'defense', Protection: 'protection' };
const GB_ACTION_LABEL = {
  BUY_MARKET: 'BUY MARCHÉ', SELL_MARKET: 'SELL MARCHÉ',
  BUY_LIMIT: 'BUY LIMIT', SELL_LIMIT: 'SELL LIMIT',
  BUY_STOP: 'BUY STOP', SELL_STOP: 'SELL STOP',
  WAIT: 'WAIT',
};

function gbActionHtml(recommendation) {
  const action = recommendation?.action || 'WAIT';
  const label = GB_ACTION_LABEL[action] || action;
  const priceTxt = recommendation?.price != null ? ` · ${Number(recommendation.price).toFixed(2)}` : '';
  const cls = action.startsWith('BUY') ? 'gb-action-buy' : action.startsWith('SELL') ? 'gb-action-sell' : 'gb-action-wait';
  return `<span class="${cls}">${label}${priceTxt}</span>`;
}

function gbTimeAgo(iso) {
  if (!iso) return '';
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return currentLanguage === 'en' ? `${seconds}s ago` : `il y a ${seconds}s`;
  const minutes = Math.round(seconds / 60);
  return currentLanguage === 'en' ? `${minutes}min ago` : `il y a ${minutes}min`;
}

function gbFillPct(value, target) {
  const t = Number(target || 0);
  if (t <= 0) return 0;
  return Math.max(0, Math.min(100, (Number(value || 0) / t) * 100));
}

function syncGoldBrainToggle() {
  const toggle = $('goldBrainToggle');
  if (!toggle || !params) return;
  const enabled = Boolean(params.gold_brain_enabled);
  toggle.checked = enabled;
  const state = $('goldBrainState');
  if (state) {
    state.textContent = enabled
      ? (currentLanguage === 'en' ? 'Enabled' : 'Activé')
      : (currentLanguage === 'en' ? 'Disabled' : 'Désactivé');
    state.className = `gb-state ${enabled ? 'on' : 'off'}`;
  }
  if ($('goldBrainOffNotice')) $('goldBrainOffNotice').style.display = enabled ? 'none' : 'block';
  if ($('goldBrainContent')) $('goldBrainContent').style.display = enabled ? 'block' : 'none';
}

$('goldBrainToggle')?.addEventListener('change', async event => {
  if (!params) return;
  const enabled = event.currentTarget.checked;
  const updated = { ...params, gold_brain_enabled: enabled };
  try {
    await alpha.saveParams(updated);
    params = updated;
    addLogs([enabled
      ? '[GOLD BRAIN] Activé — le CAIO arbitre désormais en dernier ressort avant chaque entrée.'
      : '[GOLD BRAIN] Désactivé — retour immédiat au pipeline classique, sans redémarrage.']);
  } catch (error) {
    event.currentTarget.checked = !enabled;
    addLogs([`[ERROR] Bascule Gold Brain impossible: ${error?.message || error}`]);
  }
  syncGoldBrainToggle();
});

function renderGoldBrain(s) {
  if (s?.gold_brain_version && $('goldBrainVersion')) $('goldBrainVersion').textContent = `v${s.gold_brain_version}`;
  // Scenario Engine / Portfolio Brain sont derriere leurs propres flags,
  // independants de gold_brain_enabled (voir alphatrade_engine.py) -- doivent
  // s'actualiser meme si `gb` (snapshot classique) est encore vide au premier cycle.
  renderScenario(s);
  renderPortfolioBrain(s);

  const gb = s?.auto_trading?.gold_brain;
  const emptyEl = $('gbEmptyState');
  const wrapEl = $('gbDecisionWrap');
  if (!gb) {
    if (emptyEl) emptyEl.style.display = 'block';
    if (wrapEl) wrapEl.style.display = 'none';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  if (wrapEl) wrapEl.style.display = 'block';

  const isGo = gb.decision === 'GO';
  const badge = $('gbDecisionBadge');
  if (badge) {
    badge.textContent = gb.decision || '—';
    badge.className = `gb-decision-badge ${isGo ? 'go' : 'notrade'}`;
  }
  if ($('gbTimestamp')) $('gbTimestamp').textContent = gbTimeAgo(gb.timestamp);
  if ($('gbOrderType')) $('gbOrderType').textContent = gb.order_type ? (GB_ACTION_LABEL[gb.order_type] || gb.order_type) : '—';
  if ($('gbPrice')) $('gbPrice').textContent = gb.price != null ? Number(gb.price).toFixed(2) : '—';
  if ($('gbSource')) $('gbSource').textContent = gb.source_agent || '—';
  if ($('gbReason')) $('gbReason').textContent = gb.raison || '';
  const overridesEl = $('gbOverrides');
  if (overridesEl) {
    if (gb.overrides && gb.overrides.length) {
      overridesEl.style.display = 'block';
      overridesEl.textContent = `⚠ ${gb.overrides.join(' ')}`;
    } else {
      overridesEl.style.display = 'none';
    }
  }

  // Mission Manager
  const mission = gb.mission || {};
  const mode = mission.mode || 'Normal';
  if ($('gbMissionMode')) {
    $('gbMissionMode').textContent = { Normal: 'Normal', Prudent: 'Prudent', Defense: 'Défense', Protection: 'Protection' }[mode] || mode;
    $('gbMissionMode').className = `gb-mm-mode ${GB_MODE_CLASS[mode] || 'normal'}`;
  }
  if ($('gbMissionPsy')) $('gbMissionPsy').textContent = mission.psychological_state || '—';
  if ($('gbMissionPrio')) {
    $('gbMissionPrio').textContent = mission.priority || 'LOW';
    $('gbMissionPrio').className = `gb-prio ${GB_PRIO_CLASS[mission.priority] || 'low'}`;
  }
  if ($('gbDayVal')) $('gbDayVal').textContent = `${money(mission.daily_profit)} / ${plainMoney(mission.daily_target)}`;
  if ($('gbDayBar')) $('gbDayBar').style.width = `${gbFillPct(mission.daily_profit, mission.daily_target)}%`;
  if ($('gbWeekVal')) $('gbWeekVal').textContent = `${money(mission.weekly_profit)} / ${plainMoney(mission.weekly_target)}`;
  if ($('gbWeekBar')) $('gbWeekBar').style.width = `${gbFillPct(mission.weekly_profit, mission.weekly_target)}%`;
  if ($('gbWeekAuto')) $('gbWeekAuto').style.display = mission.weekly_target_auto ? 'inline' : 'none';
  if ($('gbMonthVal')) $('gbMonthVal').textContent = `${money(mission.monthly_profit)} / ${plainMoney(mission.monthly_target)}`;
  if ($('gbMonthBar')) $('gbMonthBar').style.width = `${gbFillPct(mission.monthly_profit, mission.monthly_target)}%`;
  if ($('gbMonthAuto')) $('gbMonthAuto').style.display = mission.monthly_target_auto ? 'inline' : 'none';
  if ($('gbAggVal')) $('gbAggVal').textContent = `${Math.round(Number(mission.aggressiveness_level || 0))} / 100`;
  if ($('gbAggBar')) $('gbAggBar').style.width = `${Math.max(0, Math.min(100, Number(mission.aggressiveness_level || 0)))}%`;
  if ($('gbLosses')) $('gbLosses').textContent = mission.consecutive_losses ?? '0';
  if ($('gbRiskAppetite')) $('gbRiskAppetite').textContent = plainMoney(mission.risk_appetite);

  // Structure Analyst / Smart Money Analyst / Risk Manager
  const reports = gb.reports || {};
  const structure = reports.structure_analyst;
  if (structure) {
    if ($('gbStructurePrio')) {
      $('gbStructurePrio').textContent = structure.priority;
      $('gbStructurePrio').className = `gb-prio ${GB_PRIO_CLASS[structure.priority] || 'low'}`;
    }
    if ($('gbStructureConf')) $('gbStructureConf').textContent = `${Math.round(structure.confidence)}%`;
    if ($('gbStructureConfBar')) $('gbStructureConfBar').style.width = `${structure.confidence}%`;
    if ($('gbStructureAction')) $('gbStructureAction').innerHTML = gbActionHtml(structure.recommendation);
    if ($('gbStructureArgs')) $('gbStructureArgs').innerHTML = (structure.arguments || []).map(a => `<li>${a}</li>`).join('');
    if ($('gbStructureRegime')) $('gbStructureRegime').textContent = structure.metadata?.regime || '—';
    if ($('gbStructureSwings')) $('gbStructureSwings').textContent = structure.metadata?.swing_count ?? '—';
    if ($('gbStructureInst')) $('gbStructureInst').textContent = structure.metadata?.institutional_zones ?? '—';
  }
  const smartMoney = reports.smart_money_analyst;
  if (smartMoney) {
    if ($('gbSmartMoneyPrio')) {
      $('gbSmartMoneyPrio').textContent = smartMoney.priority;
      $('gbSmartMoneyPrio').className = `gb-prio ${GB_PRIO_CLASS[smartMoney.priority] || 'low'}`;
    }
    if ($('gbSmartMoneyConf')) $('gbSmartMoneyConf').textContent = `${Math.round(smartMoney.confidence)}%`;
    if ($('gbSmartMoneyConfBar')) $('gbSmartMoneyConfBar').style.width = `${smartMoney.confidence}%`;
    if ($('gbSmartMoneyAction')) $('gbSmartMoneyAction').innerHTML = gbActionHtml(smartMoney.recommendation);
    const smArgs = [...(smartMoney.arguments || []), ...(smartMoney.risks || [])];
    if ($('gbSmartMoneyArgs')) $('gbSmartMoneyArgs').innerHTML = smArgs.map(a => `<li>${a}</li>`).join('');
    if ($('gbSmFvg')) $('gbSmFvg').textContent = smartMoney.metadata?.fvg_count ?? '—';
    if ($('gbSmOb')) $('gbSmOb').textContent = smartMoney.metadata?.order_block_count ?? '—';
    if ($('gbSmBc')) $('gbSmBc').textContent = smartMoney.metadata?.bos_choch_count ?? '—';
    if ($('gbSmPd')) $('gbSmPd').textContent = smartMoney.metadata?.premium_discount?.zone || '—';
  }
  const risk = reports.risk_manager;
  if (risk) {
    if ($('gbRiskPrio')) {
      $('gbRiskPrio').textContent = risk.priority;
      $('gbRiskPrio').className = `gb-prio ${GB_PRIO_CLASS[risk.priority] || 'low'}`;
    }
    if ($('gbRiskConf')) $('gbRiskConf').textContent = `${Math.round(risk.confidence)}%`;
    if ($('gbRiskConfBar')) $('gbRiskConfBar').style.width = `${risk.confidence}%`;
    const xauLot = risk.recommendation?.lots?.XAUUSD;
    if ($('gbRiskLine')) {
      $('gbRiskLine').textContent = xauLot
        ? `Lot effectif : ${Number(xauLot.effective_lot || 0).toFixed(3)} (XAUUSD)`
        : '—';
    }
    if ($('gbRiskArgs')) $('gbRiskArgs').innerHTML = (risk.arguments || risk.risks || []).map(a => `<li>${a}</li>`).join('');
    if ($('gbRiskStatus')) {
      $('gbRiskStatus').textContent = risk.status;
      $('gbRiskStatus').style.color = risk.status === 'OK' ? 'var(--green)' : 'var(--red)';
    }
    if ($('gbRiskRejected')) $('gbRiskRejected').textContent = risk.recommendation?.any_rejected
      ? (currentLanguage === 'en' ? 'Yes' : 'Oui')
      : (currentLanguage === 'en' ? 'No' : 'Non');
  }
  const econ = reports.economic_calendar;
  if (econ) {
    if ($('gbEconPrio')) {
      $('gbEconPrio').textContent = econ.priority;
      $('gbEconPrio').className = `gb-prio ${GB_PRIO_CLASS[econ.priority] || 'low'}`;
    }
    if ($('gbEconConf')) $('gbEconConf').textContent = `${Math.round(econ.confidence)}%`;
    if ($('gbEconConfBar')) $('gbEconConfBar').style.width = `${econ.confidence}%`;
    if ($('gbEconLine')) {
      $('gbEconLine').textContent = econ.recommendation?.any_rejected
        ? 'Entrée bloquée — publication imminente'
        : 'Aucun blocage actif';
    }
    if ($('gbEconArgs')) $('gbEconArgs').innerHTML = (econ.arguments || econ.risks || []).map(a => `<li>${a}</li>`).join('');
  }
}

// ── Panneau Scénario -- Market Scenario Engine (v5.1.1, chantier 5) ─────────
// Fidèle à Maquette_ScenarioEngine_v5.1.1.html. Données réelles :
// s.auto_trading.scenario (Scenario.to_dict(), voir python/scenario.py).
const SCN_STATUS_CLASS = {
  CANDIDATE: 'candidate', VALIDATED: 'validated', ACTIVE: 'active', DEGRADED: 'degraded',
  INVALIDATED: 'invalidated', EXPIRED: 'invalidated', COMPLETED: 'active',
};
const SCN_FACTOR_LABELS = {
  structure: 'Structure', smart_money: 'Smart Money', zone_history: 'Zone historique',
  volatility: 'Volatilité', momentum: 'Momentum', session: 'Session', microstructure: 'Microstructure',
};
const SCN_VOLATILITY_LABEL = { low: 'Basse', medium: 'Moyenne', high: 'Élevée' };
const SCN_TREND_LABEL = { UPTREND: 'Bullish', DOWNTREND: 'Bearish', RANGE: 'Range', CORRECTION: 'Correction' };

function scnTimeHM(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString(currentLanguage === 'en' ? 'en-US' : 'fr-FR', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

function renderScenario(s) {
  const scenario = s?.auto_trading?.scenario;
  const emptyEl = $('scnEmptyState');
  const sectionEl = $('scnSection');
  if (!scenario) {
    if (sectionEl) sectionEl.style.display = 'none';
    if (emptyEl) {
      emptyEl.style.display = 'block';
      emptyEl.textContent = params?.scenario_engine_enabled
        ? 'Scenario Engine activé — en attente du premier scénario généré (aucune position réelle tant que l’exécution reste en observation).'
        : 'Scenario Engine désactivé — activez-le dans Paramètres pour observer les scénarios générés en continu (aucune position réelle tant que cette phase reste en observation).';
    }
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  if (sectionEl) sectionEl.style.display = 'block';

  const status = scenario.status || 'CANDIDATE';
  const badge = $('scnStatus');
  if (badge) {
    badge.textContent = status;
    badge.className = `scn-status ${SCN_STATUS_CLASS[status] || 'candidate'}`;
  }

  const dir = $('scnDir');
  if (dir) {
    dir.textContent = scenario.direction || '—';
    dir.className = `dir ${scenario.direction === 'BUY' ? 'buy' : scenario.direction === 'SELL' ? 'sell' : ''}`;
  }
  if ($('scnZone')) {
    const z = scenario.zone || {};
    $('scnZone').textContent = (z.low != null && z.high != null) ? `${Number(z.low).toFixed(2)} – ${Number(z.high).toFixed(2)}` : '—';
  }

  if ($('scnConfVal')) $('scnConfVal').innerHTML = `${Math.round(scenario.scenario_confidence || 0)}<small>/100</small>`;
  if ($('scnConfBar')) $('scnConfBar').style.width = `${Math.max(0, Math.min(100, scenario.scenario_confidence || 0))}%`;

  const healthBlock = $('scnHealthBlock');
  const hasHealth = scenario.scenario_health != null;
  if (healthBlock) healthBlock.style.display = hasHealth ? 'block' : 'none';
  if (hasHealth) {
    const health = Number(scenario.scenario_health);
    if ($('scnHealthVal')) $('scnHealthVal').innerHTML = `${Math.round(health)}<small>/100</small>`;
    const hb = $('scnHealthBar');
    if (hb) {
      hb.style.width = `${Math.max(0, Math.min(100, health))}%`;
      hb.className = `fill ${health < 45 ? 'crit' : health < 65 ? 'warn' : ''}`.trim();
    }
    const entry = scenario.scenario_confidence_at_entry;
    const curve = scenario.health_curve || [];
    const tr = $('scnTrend');
    if (tr) {
      if (curve.length >= 2 && entry != null) {
        const delta = Math.round(health - entry);
        tr.textContent = delta === 0
          ? `Stable depuis l’activation (${Math.round(entry)}/100)`
          : `${delta > 0 ? '▲' : '▼'} ${delta > 0 ? '+' : ''}${delta} pts depuis l’activation (${Math.round(entry)} → ${Math.round(health)})`;
        tr.className = `scn-trend ${delta > 2 ? 'up' : delta < -2 ? 'down' : 'stable'}`;
      } else {
        tr.textContent = `Confiance à l’entrée : ${Math.round(entry != null ? entry : health)}/100 — scénario tout juste activé`;
        tr.className = 'scn-trend stable';
      }
    }
  }

  const factorsEl = $('scnFactors');
  if (factorsEl) {
    // Poids actuels SCENARIO_WEIGHTS (v5.1.1 chantier 2, 7 facteurs) -- affichage
    // informatif ; les poids réellement appliqués peuvent différer une fois
    // scenario_learned_weights.json chargé (voir load_scenario_weights()).
    const weights = { structure: 25, smart_money: 25, zone_history: 15, volatility: 15, momentum: 5, session: 5, microstructure: 10 };
    factorsEl.innerHTML = Object.entries(weights).map(([k, v]) =>
      `<span class="factor-chip">${SCN_FACTOR_LABELS[k] || k} <b>${v}%</b></span>`
    ).join('');
  }

  if ($('scnConfluences')) {
    $('scnConfluences').innerHTML = (scenario.confluences || []).map(c => `<li>${c}</li>`).join('') || '<li>—</li>';
  }

  if ($('scnAge')) $('scnAge').textContent = gbTimeAgo(scenario.created_at) || '—';
  if ($('scnMaxValidity')) $('scnMaxValidity').textContent = `${scenario.maximum_validity_min ?? '—'} min`;
  if ($('scnExpiry')) $('scnExpiry').textContent = scnTimeHM(scenario.expires_at);
  if ($('scnValidityBar')) {
    const created = scenario.created_at ? new Date(scenario.created_at).getTime() : null;
    const expires = scenario.expires_at ? new Date(scenario.expires_at).getTime() : null;
    let pct = 0;
    if (created && expires && expires > created) pct = ((Date.now() - created) / (expires - created)) * 100;
    $('scnValidityBar').style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  const plan = $('scnPlan');
  if (plan) {
    const anchor = scenario.anchor_plan || {};
    const rows = [
      `<div class="pr"><span class="k">Entrée</span><span class="v">${anchor.entry != null ? Number(anchor.entry).toFixed(2) : '—'}</span></div>`,
      `<div class="pr"><span class="k">Invalidation (SL)</span><span class="v inv">${scenario.invalidation_price != null ? Number(scenario.invalidation_price).toFixed(2) : '—'}</span></div>`,
    ];
    (scenario.targets || []).forEach((t, i) => {
      rows.push(`<div class="pr"><span class="k">${t.label || `Target ${i + 1}`}</span><span class="v tgt">${t.price != null ? Number(t.price).toFixed(2) : '—'}</span></div>`);
    });
    plan.innerHTML = rows.join('');
  }

  const ctx = scenario.market_context || {};
  const ctxGrid = $('scnCtxGrid');
  if (ctxGrid) {
    const trendLabel = SCN_TREND_LABEL[ctx.trend] || ctx.trend || '—';
    const trendColor = ctx.trend === 'UPTREND' ? 'var(--green)' : ctx.trend === 'DOWNTREND' ? 'var(--red)' : 'var(--text)';
    const tfKey = Object.keys(ctx.timeframe_alignment || {})[0] || '—';
    ctxGrid.innerHTML = `
      <div class="ctx-item"><div class="k">Tendance</div><div class="v" style="color:${trendColor}">${trendLabel}</div></div>
      <div class="ctx-item"><div class="k">Volatilité</div><div class="v">${SCN_VOLATILITY_LABEL[ctx.volatility] || ctx.volatility || '—'}${ctx.atr != null ? ` (ATR ${Number(ctx.atr).toFixed(1)})` : ''}</div></div>
      <div class="ctx-item"><div class="k">Session</div><div class="v">${ctx.session || '—'}</div></div>
      <div class="ctx-item"><div class="k">Timeframe</div><div class="v">${tfKey}</div></div>`;
  }
  const tfRow = $('scnTfRow');
  if (tfRow) {
    const alignment = ctx.timeframe_alignment || {};
    tfRow.innerHTML = Object.entries(alignment).map(([tf, regime]) => {
      const cls = regime === 'UPTREND' ? 'bullish' : regime === 'DOWNTREND' ? 'bearish' : 'neutral';
      return `<span class="tf-chip ${cls}">${tf} ${SCN_TREND_LABEL[regime] || regime || 'neutral'}</span>`;
    }).join('');
  }

  const scalpSection = $('scnScalpSection');
  const showScalp = status === 'ACTIVE' || status === 'DEGRADED' || status === 'COMPLETED';
  if (scalpSection) scalpSection.style.display = showScalp ? 'block' : 'none';
  if (showScalp && $('scnGateNote')) {
    const count = scenario.simulated_scalp_count || 0;
    const health = scenario.scenario_health;
    const note = scenario.scalp_allowed
      ? `<span class="ok">✓</span> Scalp autorisé — scénario ${status}, ${count} opportunité(s) simulée(s) détectée(s) jusqu’ici. Aucune position réelle (observation).`
      : `<span class="no">✗</span> Scalp refusé — ${health != null ? `scenario_health (${Math.round(health)}) sous le seuil de dégradation` : 'scénario non actif'}. scalp_allowed=false.`;
    $('scnGateNote').innerHTML = note;
  }

  // Pipeline -- niveau atteint deduit de l'historique reel (un statut terminal
  // peut avoir ete atteint sans jamais passer par ACTIVE, ex: CANDIDATE -> EXPIRED).
  const history = scenario.history || [];
  const statuses = new Set(history.map(h => h.status));
  let pipeStep = 'gen';
  if (statuses.has('ACTIVE') || statuses.has('DEGRADED') || statuses.has('COMPLETED')) pipeStep = 'exec';
  else if (statuses.has('VALIDATED')) pipeStep = 'val';
  const order = ['Gen', 'Val', 'Caio', 'Exec'];
  const upTo = { gen: 0, val: 1, caio: 2, exec: 3 }[pipeStep];
  order.forEach((step, i) => {
    const el = $('scnPipe' + step);
    if (el) el.classList.toggle('on', i <= upTo);
  });

  const checks = scenario.validation || {};
  const chkMap = { Zone: 'zone_touched', Reaction: 'reaction', Risk: 'risk_ok', Market: 'market_ok' };
  Object.entries(chkMap).forEach(([suffix, key]) => {
    const el = $('scnChk' + suffix);
    if (!el) return;
    if (!(key in checks)) { el.textContent = '—'; el.style.color = 'var(--muted)'; return; }
    const ok = Boolean(checks[key]);
    el.textContent = ok ? '✓ Oui' : '✗ Non';
    el.style.color = ok ? 'var(--green)' : 'var(--red)';
  });
}

// ── Carte agent Portfolio Brain (v5.1.1, chantier 4) -- s.auto_trading.portfolio ──
function renderPortfolioBrain(s) {
  const report = s?.auto_trading?.portfolio;
  const card = $('gbPortfolioCard');
  if (!card) return;
  if (!report) { card.style.display = 'none'; return; }
  card.style.display = '';
  if ($('gbPortfolioPrio')) {
    $('gbPortfolioPrio').textContent = report.priority || 'LOW';
    $('gbPortfolioPrio').className = `gb-prio ${GB_PRIO_CLASS[report.priority] || 'low'}`;
  }
  if ($('gbPortfolioConf')) $('gbPortfolioConf').textContent = `${Math.round(report.confidence || 0)}%`;
  if ($('gbPortfolioConfBar')) $('gbPortfolioConfBar').style.width = `${Math.max(0, Math.min(100, report.confidence || 0))}%`;
  const exposure = report.recommendation?.exposure || {};
  if ($('gbPortfolioLine')) {
    const action = report.recommendation?.action || 'OK';
    const label = action === 'OK'
      ? `Panier dans les limites (${exposure.position_count ?? 0} position(s))`
      : action === 'LIMIT_NEW_ENTRIES' ? 'Limiter les nouvelles entrées'
      : action === 'REDUCE_EXPOSURE' ? 'Réduire l’exposition' : action;
    const color = action === 'OK' ? 'var(--text)' : action === 'REDUCE_EXPOSURE' ? 'var(--red)' : 'var(--orange)';
    $('gbPortfolioLine').innerHTML = `<span style="color:${color}">${label}</span>`;
  }
  if ($('gbPortfolioArgs')) $('gbPortfolioArgs').innerHTML = (report.arguments || []).map(a => `<li>${a}</li>`).join('');
  if ($('gbPortfolioLot')) $('gbPortfolioLot').textContent = exposure.total_lot != null ? Number(exposure.total_lot).toFixed(2) : '—';
  if ($('gbPortfolioDir')) $('gbPortfolioDir').textContent = exposure.hedged ? 'Couvert (hedge)' : (exposure.net_direction || '—');
  if ($('gbPortfolioPnl')) {
    $('gbPortfolioPnl').textContent = exposure.floating_pnl_pct != null
      ? `${exposure.floating_pnl_pct > 0 ? '+' : ''}${exposure.floating_pnl_pct}%`
      : '—';
  }
}

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

// Refonte du 17/07/2026 (demande de Louis, Phase 2) : applique TOUS les
// paramètres poussés par le forfait (avant : 8 clés codées en dur), et
// mémorise les verrous pour que la page Paramètres grise réellement les
// champs correspondants (avant : la valeur n'était poussée qu'une fois au
// login, sans verrou visuel — le client pouvait la remodifier aussitôt).
async function applyPlanParamsToEngine(planParams) {
  planParamLocks = {};
  if (!planParams || !alpha) return;
  const current = await alpha.loadParams();
  if (!current) return;
  const updated = JSON.parse(JSON.stringify(current));
  const symKey = updated.active_symbol || 'XAUUSD';
  const sym = updated.symbols?.[symKey];

  for (const [key, entry] of Object.entries(planParams)) {
    const raw = entry?.val ?? entry;
    const locked = entry?.is_locked ?? entry?.locked ?? false;
    if (raw === undefined || raw === null || raw === '') continue;
    if (locked) planParamLocks[key] = true;

    if (key === 'take_profit_max_levels') {
      const maxLevels = Math.max(1, Math.min(6, parseInt(raw) || 6));
      PLAN_MAX_TP_LEVELS = maxLevels;
      if (sym?.take_profit_levels?.length > maxLevels) {
        sym.take_profit_levels = sym.take_profit_levels.slice(0, maxLevels);
      }
      continue;
    }
    const coerce = v => (v === 'true' || v === true) ? true : (v === 'false' || v === false) ? false
      : (typeof v === 'string' && v.trim() !== '' && !isNaN(v)) ? parseFloat(v) : v;
    if (Object.prototype.hasOwnProperty.call(updated, key)) {
      updated[key] = coerce(raw);
    } else if (sym && Object.prototype.hasOwnProperty.call(sym, key)) {
      sym[key] = coerce(raw);
    }
  }
  await alpha.saveParams(updated);
  applyParamLocksToUI();
}

// Grise (disabled + style) les champs de la page Paramètres correspondant à
// des paramètres verrouillés par le forfait actif. Visible mais non
// modifiable (décision de Louis le 17/07/2026) -- jamais masqué.
function applyParamLocksToUI() {
  const form = $('settingsForm');
  if (!form) return;
  form.querySelectorAll('[name]').forEach(input => {
    const locked = !!planParamLocks[input.name];
    input.classList.toggle('plan-locked', locked);
    input.disabled = locked;
    input.title = locked ? 'Réservé aux forfaits supérieurs' : '';
  });
  const addBtn = $('addTakeProfitLevelBtn');
  if (addBtn && planParamLocks['take_profit_max_levels']) {
    addBtn.title = `Nombre de Take Profit limité par votre forfait (max ${PLAN_MAX_TP_LEVELS})`;
  }
  renderTakeProfitLevels();
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
    if (typeof alpha.sendSessionToken === 'function') alpha.sendSessionToken(data.token);
    hideLoginOverlay();
    showPlanBadge(data.user, data.plan);
    if (data.plan && data.plan.params) applyPlanParamsToEngine(data.plan.params).catch(() => {});
    loadFullProfile();
    loadReferral();
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
  if (!token) return;
  try {
    const res = await fetch(`${API_BASE}/user/profile`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const data = await res.json();
    const el = id => document.getElementById(id);
    if (el('acEditName')) el('acEditName').value = data.full_name || '';
    if (el('acEditEmail')) el('acEditEmail').value = data.email || '';
    if (el('acEditPhone')) el('acEditPhone').value = data.phone || '';
    if (el('acEditCountry')) el('acEditCountry').value = data.country || '';
    // Corrigé le 17/07/2026 : ces infos n'apparaissaient nulle part en
    // lecture seule (seulement dans le formulaire d'édition, invisible tant
    // qu'on ne l'ouvrait pas).
    if (el('acInfoName')) el('acInfoName').textContent = data.full_name || '—';
    if (el('acInfoPhone')) el('acInfoPhone').textContent = data.phone || '—';
    if (el('acInfoCountry')) el('acInfoCountry').textContent = data.country || '—';
  } catch (_) {}
}

let acReferralLink = '';

async function loadReferral() {
  const token = sessionStorage.getItem('at_token');
  if (!token) return;
  try {
    const res = await fetch(`${API_BASE}/client/referral-code`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const data = await res.json();
    const el = id => document.getElementById(id);
    if (el('acRefCode')) el('acRefCode').textContent = data.code;
    acReferralLink = data.share_url;
    if (el('acRefLink')) el('acRefLink').value = acReferralLink;
    if (el('acRefStatTotal')) el('acRefStatTotal').textContent = data.stats.total;
    if (el('acRefStatPending')) el('acRefStatPending').textContent = Math.max(0, data.stats.total - data.stats.rewarded);
    if (el('acRefStatRewarded')) el('acRefStatRewarded').textContent = data.stats.rewarded;
    const qrBox = el('acRefQR');
    if (qrBox && typeof QRCode !== 'undefined') {
      qrBox.innerHTML = '';
      new QRCode(qrBox, { text: acReferralLink, width: 104, height: 104, colorDark: '#111111', colorLight: '#ffffff', correctLevel: QRCode.CorrectLevel.M });
    }
  } catch (_) {}
}

function flashCopyBtn(btn) {
  if (!btn) return;
  const original = btn.textContent;
  btn.textContent = '✓ Copié';
  setTimeout(() => { btn.textContent = original; }, 1500);
}

function copyReferralCode(ev) {
  const code = document.getElementById('acRefCode')?.textContent;
  if (!code || code === '—') return;
  navigator.clipboard.writeText(code).then(() => flashCopyBtn(ev && ev.target));
}

function copyReferralLink(ev) {
  if (!acReferralLink) return;
  navigator.clipboard.writeText(acReferralLink).then(() => flashCopyBtn(ev && ev.target));
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
    Object.assign(user, { full_name: data.user.full_name, email: data.user.email, phone: data.user.phone, country: data.user.country });
    sessionStorage.setItem('at_user', JSON.stringify(user));
    const el = id => document.getElementById(id);
    if (el('acHeroName')) el('acHeroName').textContent = data.user.full_name || data.user.email;
    if (el('acHeroEmail')) el('acHeroEmail').textContent = data.user.email;
    if (el('acEmail')) el('acEmail').textContent = data.user.email;
    if (el('acInfoEmail')) el('acInfoEmail').textContent = data.user.email;
    if (el('acInfoName')) el('acInfoName').textContent = data.user.full_name || '—';
    if (el('acInfoPhone')) el('acInfoPhone').textContent = data.user.phone || '—';
    if (el('acInfoCountry')) el('acInfoCountry').textContent = data.user.country || '—';
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
  if (typeof alpha.sendSessionToken === 'function') alpha.sendSessionToken(null);
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
          if (typeof alpha.sendSessionToken === 'function') alpha.sendSessionToken(token);
          loadFullProfile();
          loadReferral();
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
