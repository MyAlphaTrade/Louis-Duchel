// Backtest engine — loads real historical OHLC data when available (imported
// via Module 1 / Données de marché), falls back to synthetic random-walk
// data otherwise, computes indicators, evaluates strategy conditions,
// simulates trades with trading costs, and returns comprehensive
// performance metrics.
//
// The per-bar decision logic (indicators, condition evaluation, entry/exit,
// position sizing) is exported as standalone primitives so it can be reused
// tick-by-tick outside of a full `runBacktest()` run — see
// `src/lib/paperTradingEngine.js` (Module 4 / Paper Trading, live + rejeu
// historique bougie par bougie). `runBacktest` itself is built out of these
// same primitives, so both consumers always evaluate a strategy identically.

import { computeIndicator } from "@/lib/indicatorCalculations";
import { base44 } from "@/api/base44Client";

export const TF_MINUTES = {
  M1: 1, M5: 5, M15: 15, M30: 30, H1: 60, H4: 240, D1: 1440,
};

// Generate synthetic OHLC bars (random walk with realistic volatility).
// Kept as an explicit fallback for assets/timeframes with no imported
// historical data — never delete, `runBacktest` calls this when
// base44.marketData.list() returns nothing.
function generateBars(symbol, timeframe, count, startPrice) {
  const minutes = TF_MINUTES[timeframe] || 15;
  const volatility = (minutes / 1440) * 0.02; // daily vol scaled to TF
  const bars = [];
  let price = startPrice || getBasePrice(symbol);
  const now = Date.now();
  const intervalMs = minutes * 60 * 1000;

  for (let i = 0; i < count; i++) {
    const open = price;
    const drift = (Math.random() - 0.48) * volatility * price;
    const close = Math.max(0.01, open + drift);
    const range = Math.abs(drift) + Math.random() * volatility * price * 0.5;
    const high = Math.max(open, close) + Math.random() * range * 0.3;
    const low = Math.min(open, close) - Math.random() * range * 0.3;
    const volume = Math.floor(500 + Math.random() * 2000);
    bars.push({
      open, high, low, close, volume,
      timestamp: new Date(now - (count - i) * intervalMs),
      index: i,
    });
    price = close;
  }
  return bars;
}

function getBasePrice(symbol) {
  const bases = {
    XAUUSD: 2000, EURUSD: 1.08, GBPUSD: 1.27, USDJPY: 150,
    BTCUSD: 65000, ETHUSD: 3500, GER30: 18500, US30: 39000,
  };
  return bases[symbol] || 100;
}

// Pre-compute all indicator series needed by the strategy
export function computeAllIndicators(bars, entryConditions) {
  const series = {};
  const all = [...(entryConditions?.buy || []), ...(entryConditions?.sell || [])];
  const collect = (cond) => {
    const key = cond.indicator + JSON.stringify(cond.params || {});
    if (!series[key] && cond.indicator) {
      series[key] = computeIndicator(cond.indicator, cond.params || {}, bars);
    }
    if (cond.target_indicator) {
      const tKey = cond.target_indicator + JSON.stringify(cond.target_params || {});
      if (!series[tKey]) {
        series[tKey] = computeIndicator(cond.target_indicator, cond.target_params || {}, bars);
      }
    }
  };
  all.forEach(collect);
  return series;
}

// Evaluate a single condition at bar i
export function evalCondition(condition, series, bars, i) {
  if (condition.enabled === false) return false;
  const key = condition.indicator + JSON.stringify(condition.params || {});
  const val = series[key]?.[i];
  if (val === null || val === undefined) return false;

  const prevVal = series[key]?.[i - 1];
  const op = condition.operator;

  switch (op) {
    case "crosses_above": {
      if (!condition.target_indicator) return false;
      const tKey = condition.target_indicator + JSON.stringify(condition.target_params || {});
      const target = series[tKey]?.[i];
      const prevTarget = series[tKey]?.[i - 1];
      if (target === null || target === undefined || prevVal === null || prevVal === undefined) return false;
      return prevVal <= prevTarget && val > target;
    }
    case "crosses_below": {
      if (!condition.target_indicator) return false;
      const tKey = condition.target_indicator + JSON.stringify(condition.target_params || {});
      const target = series[tKey]?.[i];
      const prevTarget = series[tKey]?.[i - 1];
      if (target === null || target === undefined || prevVal === null || prevVal === undefined) return false;
      return prevVal >= prevTarget && val < target;
    }
    case "greater_than":
      return val > (condition.target_value ?? 0);
    case "less_than":
      return val < (condition.target_value ?? 0);
    case "equals":
      return Math.abs(val - (condition.target_value ?? 0)) < 0.01;
    default:
      return false;
  }
}

// Check if all enabled conditions in a group are met
export function evalGroup(conditions, series, bars, i) {
  const enabled = (conditions || []).filter((c) => c.enabled !== false);
  if (enabled.length === 0) return false;
  return enabled.every((c) => evalCondition(c, series, bars, i));
}

export function getPipSize(symbol) {
  if (symbol?.includes("JPY")) return 0.01;
  if (symbol?.includes("XAU") || symbol?.includes("XAG")) return 0.01;
  return 0.0001;
}

// Fetches real imported candles for (symbol, timeframe) and converts them to
// the internal bar shape. Returns [] (not a throw) on any fetch error so
// callers can fall back to synthetic data without blocking the user.
export async function loadRealBars(symbol, timeframe) {
  try {
    const candles = await base44.marketData.list(symbol, timeframe);
    if (!Array.isArray(candles) || candles.length === 0) return [];
    return candles.map((c, idx) => ({
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
      volume: c.volume || 0,
      timestamp: new Date(c.timestamp),
      index: idx,
    }));
  } catch (err) {
    console.warn("[backtestEngine] Échec du chargement des données réelles, repli sur des données synthétiques :", err);
    return [];
  }
}

// ── Reusable per-bar engine primitives ──────────────────────────────────────
// Everything below operates on one (openTrade, bar, i) step at a time and
// carries no loop/session state of its own — `runBacktest` drives them bar
// by bar below, and `paperTradingEngine.js` drives the exact same functions
// one tick/bar at a time for live trading and the historical replay ("rejeu
// bougie par bougie") mode.

// Precomputes the cost/risk parameters shared by every bar of a session
// (constant for the whole run — mirrors runBacktest's pre-loop setup
// exactly). `capital` is the reference balance used for percent-of-capital
// risk sizing (the *initial* capital, not the live/running balance).
export function buildEngineContext(strategy, asset, config, capital) {
  const spread = config.spread || 0;
  const commission = config.commission || 0;
  const slippage = config.slippage || 0;
  const leverage = config.leverage || 1;
  const configLotSize = config.lotSize || 0.1;
  const configRiskPerTrade = config.riskPerTrade || 1;
  const tfMin = TF_MINUTES[config.timeframe] || 15;

  const pipSize = getPipSize(asset.symbol);
  const spreadCost = spread * pipSize;       // spread in price units
  const slippageCost = slippage * pipSize;   // slippage in price units
  const commissionPerSide = commission;      // $ per lot per side

  const exit = strategy.exit_conditions || {};
  const risk = strategy.risk_management || {};
  const slConfig = exit.stop_loss || {};
  const tpConfig = exit.take_profit || {};

  const riskAmount = risk.type === "percent"
    ? capital * ((configRiskPerTrade || risk.risk_value || 1) / 100)
    : risk.type === "fixed"
    ? risk.risk_value || 100
    : 0;

  return {
    pipSize,
    spreadCost,
    slippageCost,
    commissionPerSide,
    leverage,
    configLotSize,
    slConfig,
    tpConfig,
    exit,
    risk,
    riskAmount,
    maxPositions: risk.max_positions || 1,
    tfMin,
  };
}

// Returns "BUY", "SELL" or null for bar i. BUY takes priority over SELL if
// both fire on the same bar (matches runBacktest's historical behaviour).
export function getEntrySignal(strategy, series, bars, i) {
  const buySignal = evalGroup(strategy.entry_conditions?.buy, series, bars, i);
  const sellSignal = evalGroup(strategy.entry_conditions?.sell, series, bars, i);
  if (!buySignal && !sellSignal) return null;
  return buySignal ? "BUY" : "SELL";
}

// Builds a fresh open-position object from an entry signal — applies
// spread/slippage to the entry price, computes SL/TP (pips/percent/ATR) and
// position size (risk-based, capped by leveraged buying power).
export function computeEntryOrder(direction, bar, i, series, ctx, balance) {
  const { pipSize, spreadCost, slippageCost, slConfig, tpConfig, riskAmount, configLotSize, leverage } = ctx;
  const rawEntry = bar.close;

  // Apply spread + slippage on entry (unfavorable direction)
  const entryPrice = direction === "BUY"
    ? rawEntry + spreadCost / 2 + slippageCost
    : rawEntry - spreadCost / 2 - slippageCost;

  const atrVal = series["atr" + JSON.stringify({ period: 14 })]?.[i] || pipSize * 10;

  const slValue = slConfig.type === "atr"
    ? atrVal * (slConfig.value || 1.5)
    : slConfig.type === "percent"
    ? entryPrice * ((slConfig.value || 1) / 100)
    : (slConfig.value || 15) * pipSize;

  const tpValue = tpConfig.type === "atr"
    ? atrVal * (tpConfig.value || 2)
    : tpConfig.type === "percent"
    ? entryPrice * ((tpConfig.value || 2) / 100)
    : (tpConfig.value || 30) * pipSize;

  const stopLoss = direction === "BUY"
    ? entryPrice - slValue
    : entryPrice + slValue;
  const takeProfit = direction === "BUY"
    ? entryPrice + tpValue
    : entryPrice - tpValue;

  // Position sizing: risk-based, capped by leveraged buying power
  let lotSize = riskAmount > 0 && slValue > 0
    ? riskAmount / slValue
    : configLotSize;

  const maxPositionValue = (balance * leverage) / entryPrice;
  lotSize = Math.min(lotSize, maxPositionValue);
  lotSize = Math.max(0.01, lotSize);

  return {
    direction,
    entry_price: entryPrice,
    stop_loss: stopLoss,
    take_profit: takeProfit,
    volume: lotSize,
    entry_time: bar.timestamp,
    entry_bar: i,
  };
}

// Checks SL/TP, time-based exit and signal-based (opposite entry) exit for
// an already-open trade at bar i. Returns { closePrice, closeReason } or
// null if the trade should stay open.
export function checkExitSignal(openTrade, bar, i, strategy, series, bars, ctx) {
  const { slConfig, tpConfig, exit } = ctx;
  let closePrice = null;
  let closeReason = "";

  if (openTrade.direction === "BUY") {
    if (slConfig.value && bar.low <= openTrade.stop_loss) {
      closePrice = openTrade.stop_loss;
      closeReason = "SL";
    } else if (tpConfig.value && bar.high >= openTrade.take_profit) {
      closePrice = openTrade.take_profit;
      closeReason = "TP";
    }
  } else {
    if (slConfig.value && bar.high >= openTrade.stop_loss) {
      closePrice = openTrade.stop_loss;
      closeReason = "SL";
    } else if (tpConfig.value && bar.low <= openTrade.take_profit) {
      closePrice = openTrade.take_profit;
      closeReason = "TP";
    }
  }

  // Time-based exit
  if (!closePrice && exit.time_exit?.enabled) {
    const barsHeld = i - openTrade.entry_bar;
    if (barsHeld >= (exit.time_exit.max_bars || 60)) {
      closePrice = bar.close;
      closeReason = "TIME";
    }
  }

  // Signal-based exit (close on opposite entry signal)
  if (!closePrice && exit.indicator_exit?.enabled) {
    const oppositeKey = openTrade.direction === "BUY" ? "sell" : "buy";
    const oppositeSignal = evalGroup(strategy.entry_conditions?.[oppositeKey], series, bars, i);
    if (oppositeSignal) {
      closePrice = bar.close;
      closeReason = "SIGNAL";
    }
  }

  return closePrice ? { closePrice, closeReason } : null;
}

// Closes an open trade at `closePrice`, applying slippage + commission.
// Returns the completed trade record (without `equity_after` — the caller
// adds it once the running balance has been updated, since that depends on
// session state this function doesn't carry).
export function closeOpenTrade(openTrade, closePrice, closeReason, bar, i, ctx) {
  const { slippageCost, commissionPerSide, tfMin } = ctx;

  const exitPrice = openTrade.direction === "BUY"
    ? closePrice - slippageCost
    : closePrice + slippageCost;

  let pnl = openTrade.direction === "BUY"
    ? (exitPrice - openTrade.entry_price) * openTrade.volume
    : (openTrade.entry_price - exitPrice) * openTrade.volume;

  // Deduct commission (both entry + exit sides)
  pnl -= commissionPerSide * openTrade.volume * 2;

  return {
    ...openTrade,
    exit_price: exitPrice,
    exit_time: bar.timestamp,
    exit_bar: i,
    profit: pnl,
    close_reason: closeReason,
    duration_bars: i - openTrade.entry_bar,
    duration_minutes: (i - openTrade.entry_bar) * tfMin,
  };
}

// Floating P&L of an open trade against the current bar's close.
export function computeUnrealizedPnl(openTrade, bar) {
  return openTrade.direction === "BUY"
    ? (bar.close - openTrade.entry_price) * openTrade.volume
    : (openTrade.entry_price - bar.close) * openTrade.volume;
}

// Same aggregate performance metrics `runBacktest` returns, factored out so
// other consumers driving the same per-bar primitives over time (e.g. the
// historical replay in paperTradingEngine.js) end up with identical stats
// once their run completes, instead of a second hand-rolled computation
// that could silently drift from this one. `maxDrawdown` is NOT recomputed
// here — it must be the value tracked bar-by-bar by the caller's own loop
// (as runBacktest's does), since a trade-close-only reconstruction would
// miss intrabar floating drawdown and not match runBacktest's number.
export function computeMetrics(trades, finalEquity, capital, periodDays, maxDrawdown) {
  const totalTrades = trades.length;
  const winningTrades = trades.filter((t) => t.profit > 0);
  const losingTrades = trades.filter((t) => t.profit <= 0);
  const grossProfit = winningTrades.reduce((s, t) => s + t.profit, 0);
  const grossLoss = Math.abs(losingTrades.reduce((s, t) => s + t.profit, 0));
  const netProfit = grossProfit - grossLoss;
  const winRate = totalTrades > 0 ? (winningTrades.length / totalTrades) * 100 : 0;
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 99 : 0;
  const avgWin = winningTrades.length > 0 ? grossProfit / winningTrades.length : 0;
  const avgLoss = losingTrades.length > 0 ? grossLoss / losingTrades.length : 0;
  const expectancy = totalTrades > 0 ? netProfit / totalTrades : 0;
  const winLossRatio = avgLoss > 0 ? avgWin / avgLoss : avgWin > 0 ? 99 : 0;
  const tradesPerDay = periodDays > 0 ? totalTrades / periodDays : 0;
  const avgDurationMin = totalTrades > 0
    ? trades.reduce((s, t) => s + (t.duration_minutes || 0), 0) / totalTrades
    : 0;

  return {
    totalTrades,
    winningTrades: winningTrades.length,
    losingTrades: losingTrades.length,
    winRate: Math.round(winRate * 100) / 100,
    netProfit: Math.round(netProfit * 100) / 100,
    grossProfit: Math.round(grossProfit * 100) / 100,
    grossLoss: Math.round(grossLoss * 100) / 100,
    profitFactor: Math.round(profitFactor * 100) / 100,
    maxDrawdown: Math.round(maxDrawdown * 100) / 100,
    expectancy: Math.round(expectancy * 100) / 100,
    winLossRatio: Math.round(winLossRatio * 100) / 100,
    avgWin: Math.round(avgWin * 100) / 100,
    avgLoss: Math.round(avgLoss * 100) / 100,
    finalEquity: Math.round(finalEquity * 100) / 100,
    initialCapital: capital,
    returnPct: Math.round(((finalEquity - capital) / capital * 100) * 100) / 100,
    tradesPerDay: Math.round(tradesPerDay * 100) / 100,
    avgDurationMin: Math.round(avgDurationMin),
  };
}

export async function runBacktest(strategy, asset, config) {
  const { timeframe, periodDays, initialCapital } = config;

  const tfMin = TF_MINUTES[timeframe] || 15;
  const barsPerDay = (24 * 60) / tfMin;
  const requestedBars = Math.max(1, Math.ceil(periodDays * barsPerDay));

  let bars;
  let dataSource;
  let warning;

  const realBars = await loadRealBars(asset.symbol, timeframe);

  if (realBars.length > 0) {
    dataSource = "real";
    if (realBars.length < requestedBars) {
      const availableDays = Math.max(1, Math.floor(realBars.length / barsPerDay));
      warning = `Historique disponible plus court que la période demandée (${availableDays} jours sur ${periodDays} demandés).`;
      bars = realBars;
    } else {
      // Keep the most recent `requestedBars` bars (chronological order preserved).
      bars = realBars.slice(realBars.length - requestedBars).map((b, idx) => ({ ...b, index: idx }));
    }
  } else {
    dataSource = "synthetic";
    const totalBars = Math.min(requestedBars, 5000);
    bars = generateBars(asset.symbol, timeframe, totalBars, asset.basePrice);
  }

  const series = computeAllIndicators(bars, strategy.entry_conditions);
  const capital = initialCapital || 10000;
  const ctx = buildEngineContext(strategy, asset, config, capital);

  const trades = [];
  let openTrade = null;
  let balance = capital;     // realized P&L only
  let equity = capital;       // balance + unrealized P&L
  const equityCurve = [];
  let maxEquity = capital;
  let maxDrawdown = 0;

  for (let i = 1; i < bars.length; i++) {
    const bar = bars[i];

    // ── Manage open trade: check SL, TP, time exit, signal exit ──
    if (openTrade) {
      const exitSignal = checkExitSignal(openTrade, bar, i, strategy, series, bars, ctx);
      if (exitSignal) {
        const closedTrade = closeOpenTrade(openTrade, exitSignal.closePrice, exitSignal.closeReason, bar, i, ctx);

        balance += closedTrade.profit;
        equity = balance;
        maxEquity = Math.max(maxEquity, equity);
        maxDrawdown = Math.max(maxDrawdown, (maxEquity - equity) / maxEquity * 100);

        trades.push({ ...closedTrade, equity_after: equity });
        openTrade = null;
      }
    }

    // ── Check entry signals ──
    if (!openTrade || trades.length < ctx.maxPositions) {
      if (!openTrade) {
        const direction = getEntrySignal(strategy, series, bars, i);
        if (direction) {
          openTrade = computeEntryOrder(direction, bar, i, series, ctx, balance);
        }
      }
    }

    // Compute equity (balance + unrealized P&L of open trade)
    const unrealizedPnl = openTrade ? computeUnrealizedPnl(openTrade, bar) : 0;

    equity = balance + unrealizedPnl;
    maxEquity = Math.max(maxEquity, equity);
    maxDrawdown = Math.max(maxDrawdown, (maxEquity - equity) / maxEquity * 100);

    equityCurve.push({
      bar: i,
      timestamp: bar.timestamp,
      balance: Math.round(balance * 100) / 100,
      equity: Math.round(equity * 100) / 100,
      drawdown: maxEquity > 0 ? ((maxEquity - equity) / maxEquity * 100) : 0,
    });
  }

  // Close any remaining open trade at last bar
  if (openTrade) {
    const lastBar = bars[bars.length - 1];
    const closedTrade = closeOpenTrade(openTrade, lastBar.close, "EOD", lastBar, bars.length - 1, ctx);

    balance += closedTrade.profit;
    equity = balance;

    trades.push({ ...closedTrade, equity_after: equity });
  }

  // ── Calculate performance metrics ──
  const metrics = computeMetrics(trades, equity, capital, periodDays, maxDrawdown);

  return {
    trades,
    equityCurve,
    metrics,
    bars: bars.length,
    dataSource,
    ...(warning ? { warning } : {}),
  };
}

// ── Bootstrap Monte Carlo (rejoue les trades reels, pas les bougies) ───────
// Utilise quand runBacktest a deja produit un run reel (dataSource==='real').
// Rejouer le moteur complet N fois sur les memes bougies importees donnerait
// toujours exactement le meme resultat (aucun hasard dans les donnees) -- au
// lieu de ca, on reechantillonne (tirage avec remise) la liste de trades deja
// obtenue pour estimer la distribution des resultats possibles selon l'ordre
// dans lequel ces memes trades auraient pu survenir. Purement arithmetique
// (pas de recalcul d'indicateurs ni de rechargement de bougies) donc quasi
// instantane, contrairement au mode synthetique qui doit re-simuler bougie
// par bougie a chaque iteration.
//
// Limite assumee : le drawdown ici est mesure entre les clotures de trades,
// pas bougie par bougie (on n'a que le P&L final de chaque trade, pas son
// chemin intra-trade) -- legerement moins precis que la courbe de capital du
// run principal, qui elle marche bougie par bougie.
export function bootstrapTradeSimulation(trades, initialCapital, iterations) {
  const closed = (trades || []).filter((t) => typeof t.profit === "number");
  const n = closed.length;
  if (n === 0) return [];

  const capital = initialCapital || 10000;
  const results = [];

  for (let iter = 0; iter < iterations; iter++) {
    let balance = capital;
    let maxEquity = capital;
    let maxDrawdown = 0;
    let grossProfit = 0;
    let grossLoss = 0;
    let wins = 0;

    for (let i = 0; i < n; i++) {
      const t = closed[Math.floor(Math.random() * n)];
      balance += t.profit;
      if (t.profit > 0) {
        grossProfit += t.profit;
        wins += 1;
      } else {
        grossLoss += Math.abs(t.profit);
      }
      maxEquity = Math.max(maxEquity, balance);
      maxDrawdown = Math.max(maxDrawdown, maxEquity > 0 ? ((maxEquity - balance) / maxEquity) * 100 : 0);
    }

    const netProfit = balance - capital;
    results.push({
      iteration: iter + 1,
      netProfit: Math.round(netProfit * 100) / 100,
      maxDrawdown: Math.round(maxDrawdown * 100) / 100,
      winRate: Math.round((wins / n) * 100 * 100) / 100,
      profitFactor: grossLoss > 0 ? Math.round((grossProfit / grossLoss) * 100) / 100 : grossProfit > 0 ? 99 : 0,
      finalEquity: Math.round(balance * 100) / 100,
      returnPct: Math.round((netProfit / capital) * 100 * 100) / 100,
    });
  }

  return results;
}
