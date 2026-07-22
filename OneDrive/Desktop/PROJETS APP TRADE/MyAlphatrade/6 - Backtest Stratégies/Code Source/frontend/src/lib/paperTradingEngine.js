// Paper Trading engine (Module 4) — 100% virtual positions, never sends a
// real order anywhere. Reuses the exact per-bar decision primitives from
// `backtestEngine.js` (same indicator computation, same condition
// evaluation, same entry/exit/sizing math) so a strategy behaves
// identically whether it's classic-backtested, replayed candle-by-candle,
// or evaluated live — only the source of the "next bar" differs.
//
// Two modes:
//  - Live: polls the backend's MT5 price bridge (GET /market-data/live) on
//    an interval, appends the latest tick as a synthetic "still forming"
//    bar on top of recently imported real history, and evaluates entry/exit
//    on that. Only runs while this page is open — there is no persistent
//    server-side worker in this v1 (see PaperTrading.jsx banner).
//  - Rejeu historique: steps through already-imported real candles one at a
//    time with a pacing delay, using the very same primitives, so the
//    final result matches a classic backtest over the same candles.

import {
  loadRealBars,
  computeAllIndicators,
  buildEngineContext,
  getEntrySignal,
  computeEntryOrder,
  checkExitSignal,
  closeOpenTrade,
  computeUnrealizedPnl,
  computeMetrics,
  TF_MINUTES,
} from "@/lib/backtestEngine";
import { base44 } from "@/api/base44Client";

// How many recent real candles are kept as lookback context for indicator
// computation in Live mode (the live tick is appended on top of this
// window each poll). Large enough for slow-moving indicators (e.g. EMA200,
// ADX) without refetching/recomputing the full history on every poll.
export const LIVE_LOOKBACK_BARS = 300;

// Live mode polls this often while the page stays open (see the honesty
// banner in PaperTrading.jsx — this is NOT a persistent background worker).
export const LIVE_POLL_INTERVAL_MS = 20000;

// Replay animation speeds: delay (ms) between two consecutive candles.
export const REPLAY_SPEEDS = {
  "1x": 400,
  "5x": 120,
  "20x": 30,
};

// ── Live mode ────────────────────────────────────────────────────────────

// Loads the rolling lookback window of real candles used as indicator
// context for Live mode. Throws a clear, user-facing error (caught by the
// caller) if nothing has been imported yet for this (symbol, timeframe) —
// live evaluation is meaningless without any history to compute
// indicators on.
export async function loadLiveContext(symbol, timeframe) {
  const bars = await loadRealBars(symbol, timeframe);
  if (bars.length < 2) {
    throw new Error(
      `Aucun historique importé pour ${symbol} en ${timeframe}. Importez des données depuis "Données de marché" avant d'utiliser le mode live.`
    );
  }
  return bars.slice(Math.max(0, bars.length - LIVE_LOOKBACK_BARS));
}

// Fetches the current bid/ask from the backend's MT5 bridge. Throws with
// the backend's own error message on failure (503 MT5 closed, 404 unknown
// symbol, etc.) — callers must surface this to the user, never crash.
export async function fetchLiveTick(symbol) {
  return base44.marketData.getLive(symbol);
}

// Appends the live tick as a synthetic "currently forming" bar on top of
// the lookback window. We only have a single price (no real OHLC for the
// bar still forming), so open = high = low = close = mid price — SL/TP
// checks against this bar degrade gracefully to "has price crossed the
// level", never phantom-trigger from an intrabar wick we don't actually
// have data for.
export function appendLiveBar(lookbackBars, tick) {
  const mid = (tick.bid + tick.ask) / 2;
  const bar = {
    open: mid,
    high: mid,
    low: mid,
    close: mid,
    volume: 0,
    timestamp: new Date(tick.timestamp),
    index: lookbackBars.length,
  };
  return [...lookbackBars, bar];
}

// One live evaluation step: given the current open PaperTrade (or null),
// the lookback window + fresh tick, and the strategy/asset/config, decides
// whether to close the open position or open a new one. Returns a plain
// decision object — PaperTrading.jsx is responsible for actually
// persisting the outcome via base44.entities.PaperTrade (this module never
// touches the DB, keeping the decision logic tick-agnostic and testable).
export function evaluateLiveStep({ openTrade, lookbackBars, tick, strategy, asset, config }) {
  if (!Array.isArray(lookbackBars)) {
    // Ne devrait jamais arriver si l'appelant a bien attendu loadLiveContext()
    // avant de poller — garde defensive pour transformer un crash cryptique
    // (`null.length`) en message clair si ce contrat est un jour violé.
    throw new Error("Contexte d'historique non chargé — relancez le mode live.");
  }
  const bars = appendLiveBar(lookbackBars, tick);
  const i = bars.length - 1;
  const series = computeAllIndicators(bars, strategy.entry_conditions);
  const capital = config.initialCapital || 10000;
  const ctx = buildEngineContext(strategy, asset, config, capital);
  const bar = bars[i];

  if (openTrade) {
    const exitSignal = checkExitSignal(openTrade, bar, i, strategy, series, bars, ctx);
    if (exitSignal) {
      const closed = closeOpenTrade(openTrade, exitSignal.closePrice, exitSignal.closeReason, bar, i, ctx);
      return { action: "close", trade: closed, price: mid(tick) };
    }
    return { action: "hold", unrealizedPnl: computeUnrealizedPnl(openTrade, bar), price: mid(tick) };
  }

  const direction = getEntrySignal(strategy, series, bars, i);
  if (direction) {
    const order = computeEntryOrder(direction, bar, i, series, ctx, capital);
    return { action: "open", order, price: mid(tick) };
  }
  return { action: "none", price: mid(tick) };
}

function mid(tick) {
  return (tick.bid + tick.ask) / 2;
}

// ── Rejeu historique (candle-by-candle replay) ──────────────────────────

// Loads the full imported history for (symbol, timeframe) and precomputes
// everything a replay run needs once (indicators, cost/risk context) — the
// per-step function below is then a pure, cheap reducer.
export async function createReplaySession(strategy, asset, config) {
  const bars = await loadRealBars(asset.symbol, config.timeframe);
  if (bars.length < 2) {
    throw new Error(
      `Aucun historique importé pour ${asset.symbol} en ${config.timeframe}. Importez des données depuis "Données de marché" avant de lancer un rejeu.`
    );
  }
  const series = computeAllIndicators(bars, strategy.entry_conditions);
  const capital = config.initialCapital || 10000;
  const ctx = buildEngineContext(strategy, asset, config, capital);
  const tfMin = TF_MINUTES[config.timeframe] || 15;
  const periodDays = Math.max(1, (bars.length * tfMin) / (24 * 60));

  return { strategy, bars, series, ctx, capital, periodDays };
}

export function initReplayState(capital) {
  return {
    i: 1,
    openTrade: null,
    trades: [],
    equityCurve: [],
    balance: capital,
    equity: capital,
    maxEquity: capital,
    maxDrawdown: 0,
    done: false,
  };
}

// Advances the replay by exactly one candle. Pure function — returns a new
// state object, never mutates `state`. Mirrors runBacktest's per-bar loop
// body exactly (same primitives, same order of operations) so a replay run
// to completion reproduces the same trades/metrics as a classic backtest
// over the same candles.
export function stepReplay(state, session) {
  if (state.done) return state;
  const { bars, series, ctx, strategy } = session;
  const i = state.i;
  if (i >= bars.length) return { ...state, done: true };

  const bar = bars[i];
  let { openTrade, trades, balance, equity, maxEquity, maxDrawdown } = state;

  if (openTrade) {
    const exitSignal = checkExitSignal(openTrade, bar, i, strategy, series, bars, ctx);
    if (exitSignal) {
      const closedTrade = closeOpenTrade(openTrade, exitSignal.closePrice, exitSignal.closeReason, bar, i, ctx);
      balance += closedTrade.profit;
      equity = balance;
      maxEquity = Math.max(maxEquity, equity);
      maxDrawdown = Math.max(maxDrawdown, (maxEquity - equity) / maxEquity * 100);
      trades = [...trades, { ...closedTrade, equity_after: equity }];
      openTrade = null;
    }
  }

  if (!openTrade || trades.length < ctx.maxPositions) {
    if (!openTrade) {
      const direction = getEntrySignal(strategy, series, bars, i);
      if (direction) {
        openTrade = computeEntryOrder(direction, bar, i, series, ctx, balance);
      }
    }
  }

  const unrealizedPnl = openTrade ? computeUnrealizedPnl(openTrade, bar) : 0;
  equity = balance + unrealizedPnl;
  maxEquity = Math.max(maxEquity, equity);
  maxDrawdown = Math.max(maxDrawdown, (maxEquity - equity) / maxEquity * 100);

  const equityCurve = [
    ...state.equityCurve,
    {
      bar: i,
      timestamp: bar.timestamp,
      balance: Math.round(balance * 100) / 100,
      equity: Math.round(equity * 100) / 100,
      drawdown: maxEquity > 0 ? ((maxEquity - equity) / maxEquity * 100) : 0,
    },
  ];

  const isLast = i === bars.length - 1;
  if (isLast && openTrade) {
    const closedTrade = closeOpenTrade(openTrade, bar.close, "EOD", bar, i, ctx);
    balance += closedTrade.profit;
    equity = balance;
    trades = [...trades, { ...closedTrade, equity_after: equity }];
    openTrade = null;
  }

  return {
    i: i + 1,
    openTrade,
    trades,
    equityCurve,
    balance,
    equity,
    maxEquity,
    maxDrawdown,
    done: isLast,
  };
}

// Advances the replay all the way to completion in one synchronous call —
// used by the "aller directement à la fin" button. Same reducer as the
// animated path (`stepReplay`), just driven in a tight loop instead of one
// step per animation frame, so the instant result is guaranteed to match
// what letting the animation play out would have produced.
export function fastForwardReplay(session) {
  let state = initReplayState(session.capital);
  while (!state.done) {
    state = stepReplay(state, session);
  }
  return state;
}

// Converts a replay state (partial or done) into the same shape
// `runBacktest()` returns (trades/equityCurve/metrics/bars/dataSource), so
// the existing BacktestResults-style components (SummaryStats, EquityCurve,
// TradeJournal) can render it unchanged at any point during the replay.
export function replayStateToResult(state, session) {
  const metrics = computeMetrics(state.trades, state.equity, session.capital, session.periodDays, state.maxDrawdown);
  return {
    trades: state.trades,
    equityCurve: state.equityCurve,
    metrics,
    bars: session.bars.length,
    dataSource: "real",
  };
}
