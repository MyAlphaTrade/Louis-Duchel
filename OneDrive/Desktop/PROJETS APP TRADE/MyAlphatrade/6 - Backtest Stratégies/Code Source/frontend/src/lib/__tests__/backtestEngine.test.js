// Tests de non-régression -- Phase 1 Strategy Lab (2026-09-12).
// Couvre : SL/TP, spread/slippage/commission, sizing (convention unifiée
// sur le capital initial), Sharpe (réel ou null), priorité intrabar,
// positions multiples, reproductibilité, marquage réel/synthétique.
import { describe, it, expect, vi, beforeEach } from "vitest";

// base44 est mocké AVANT l'import du moteur -- runBacktest() appelle
// loadRealBars() -> base44.marketData.list(), c'est le seul point de
// contact du moteur avec le "monde extérieur".
const listMock = vi.fn();
vi.mock("@/api/base44Client", () => ({
  base44: { marketData: { list: (...args) => listMock(...args) } },
}));

const {
  buildEngineContext,
  computeEntryOrder,
  checkExitSignal,
  closeOpenTrade,
  computeSharpeRatio,
  computeMetrics,
  runBacktest,
  RISK_MODEL,
  INTRABAR_EXIT_POLICY,
  MIN_TRADES_FOR_SHARPE,
} = await import("../backtestEngine");

function baseStrategy(overrides = {}) {
  return {
    entry_conditions: {
      buy: [{ indicator: "price", operator: "greater_than", target_value: -1e9, enabled: true }],
      sell: [],
    },
    exit_conditions: {
      stop_loss: { type: "pips", value: 10 },
      take_profit: { type: "pips", value: 20 },
    },
    risk_management: { type: "fixed", risk_value: 100, max_positions: 1 },
    ...overrides,
  };
}

function makeCandles(closes, startIso = "2026-01-01T00:00:00Z") {
  const start = new Date(startIso).getTime();
  return closes.map((c, i) => ({
    timestamp: new Date(start + i * 15 * 60 * 1000).toISOString(),
    open: c, high: c + 0.5, low: c - 0.5, close: c, volume: 100,
  }));
}

beforeEach(() => {
  listMock.mockReset();
});

describe("conventions explicites (Phase 1)", () => {
  it("RISK_MODEL et INTRABAR_EXIT_POLICY sont des constantes nommées, pas des valeurs devinées", () => {
    expect(RISK_MODEL).toBe("FIXED_FRACTIONAL_INITIAL_CAPITAL");
    expect(INTRABAR_EXIT_POLICY).toBe("SL_FIRST");
  });
});

describe("sizing -- capital initial, jamais le solde courant", () => {
  it("le plafond de levier ignore le paramètre balance et utilise ctx.capital", () => {
    const strategy = baseStrategy({ risk_management: { type: "percent", risk_value: 1, max_positions: 1 } });
    const asset = { symbol: "XAUUSD" };
    const ctx = buildEngineContext(strategy, asset, { leverage: 10 }, /* capital */ 10000);
    const bar = { close: 4000, timestamp: new Date() };
    const series = { ["atr" + JSON.stringify({ period: 14 })]: [5] };

    // Deux appels, SEUL `balance` (5e argument) change -- si le sizing
    // dépendait encore du solde courant (bug Phase B), les deux résultats
    // différeraient. Convention Phase 1 : ils doivent être identiques.
    const orderWithLowBalance = computeEntryOrder("BUY", bar, 0, series, ctx, /* balance */ 500);
    const orderWithHighBalance = computeEntryOrder("BUY", bar, 0, series, ctx, /* balance */ 999999);
    expect(orderWithLowBalance.volume).toBe(orderWithHighBalance.volume);
  });
});

describe("spread / slippage / commission", () => {
  const strategy = baseStrategy();
  const asset = { symbol: "XAUUSD" };
  const ctx = buildEngineContext(strategy, asset, { spread: 10, slippage: 2, commission: 3 }, 10000);
  const series = { ["atr" + JSON.stringify({ period: 14 })]: [1] };

  it("BUY : spread et slippage renchérissent le prix d'entrée", () => {
    const bar = { close: 4000, timestamp: new Date() };
    const order = computeEntryOrder("BUY", bar, 0, series, ctx, 10000);
    // pipSize XAUUSD = 0.01 -> spreadCost=0.1, slippageCost=0.02
    expect(order.entry_price).toBeCloseTo(4000 + 0.1 / 2 + 0.02, 6);
  });

  it("SELL : spread et slippage pénalisent le prix d'entrée dans l'autre sens", () => {
    const bar = { close: 4000, timestamp: new Date() };
    const order = computeEntryOrder("SELL", bar, 0, series, ctx, 10000);
    expect(order.entry_price).toBeCloseTo(4000 - 0.1 / 2 - 0.02, 6);
  });

  it("la commission est déduite deux fois (entrée + sortie) à la clôture", () => {
    const bar = { close: 4000, timestamp: new Date() };
    const openTrade = computeEntryOrder("BUY", bar, 0, series, ctx, 10000);
    const closed = closeOpenTrade(openTrade, 4010, "TP", { close: 4010, timestamp: new Date() }, 5, ctx);
    const grossPnl = (closed.exit_price - openTrade.entry_price) * openTrade.volume;
    expect(closed.profit).toBeCloseTo(grossPnl - 3 * openTrade.volume * 2, 6);
  });
});

describe("intrabar SL/TP -- SL_FIRST, comportement inchangé mais désormais nommé", () => {
  it("si SL et TP sont tous les deux techniquement atteints sur la même bougie, le SL gagne", () => {
    const strategy = baseStrategy();
    const ctx = buildEngineContext(strategy, { symbol: "XAUUSD" }, {}, 10000);
    const openTrade = { direction: "BUY", entry_price: 4000, stop_loss: 3990, take_profit: 4020, entry_bar: 0 };
    // La bougie touche à la fois le SL (low<=3990) et le TP (high>=4020).
    const bar = { low: 3985, high: 4025, close: 4000, timestamp: new Date() };
    const result = checkExitSignal(openTrade, bar, 1, strategy, {}, [], ctx);
    expect(result.closeReason).toBe("SL");
  });
});

describe("Sharpe ratio -- réel ou null, jamais un faux 0", () => {
  it("null en dessous de MIN_TRADES_FOR_SHARPE", () => {
    const trades = Array.from({ length: MIN_TRADES_FOR_SHARPE - 1 }, (_, i) => ({ profit: i + 1 }));
    expect(computeSharpeRatio(trades, 10000)).toBeNull();
  });

  it("null si l'écart-type des rendements est nul (tous les trades identiques)", () => {
    const trades = Array.from({ length: 10 }, () => ({ profit: 50 }));
    expect(computeSharpeRatio(trades, 10000)).toBeNull();
  });

  it("une vraie valeur numérique finie quand c'est statistiquement calculable", () => {
    const trades = [10, -5, 20, -8, 15, -3, 12].map((profit) => ({ profit }));
    const sharpe = computeSharpeRatio(trades, 10000);
    expect(sharpe).not.toBeNull();
    expect(Number.isFinite(sharpe)).toBe(true);
  });

  it("computeMetrics expose sharpeRatio (plus jamais codé en dur à 0)", () => {
    const trades = [10, -5, 20, -8, 15, -3, 12].map((profit) => ({ profit, duration_minutes: 15 }));
    const metrics = computeMetrics(trades, 10041, 10000, 30, 5);
    expect(typeof metrics.sharpeRatio).toBe("number");
  });
});

describe("runBacktest -- provenance et reproductibilité", () => {
  it("dataSource = synthetic quand aucune donnée réelle n'est trouvée", async () => {
    listMock.mockResolvedValue([]);
    const result = await runBacktest(baseStrategy(), { symbol: "XAUUSD" }, {
      timeframe: "M15", periodDays: 1, initialCapital: 10000,
    });
    expect(result.dataSource).toBe("synthetic");
  });

  it("dataSource = real + dataset exact quand des bougies réelles existent, et les conventions sont exposées", async () => {
    const closes = Array.from({ length: 60 }, (_, i) => 4000 + Math.sin(i / 3) * 10);
    listMock.mockResolvedValue(makeCandles(closes));
    const result = await runBacktest(baseStrategy(), { symbol: "XAUUSD" }, {
      timeframe: "M15", periodDays: 1, initialCapital: 10000,
    });
    expect(result.dataSource).toBe("real");
    expect(result.dataset.symbol).toBe("XAUUSD");
    expect(result.dataset.timeframe).toBe("M15");
    expect(result.dataset.barsUsed).toBe(result.bars);
    expect(result.riskModel).toBe(RISK_MODEL);
    expect(result.intrabarExitPolicy).toBe(INTRABAR_EXIT_POLICY);
  });

  it("même dataset + même stratégie + même config => même résultat (Test 1 demandé)", async () => {
    const closes = Array.from({ length: 60 }, (_, i) => 4000 + Math.sin(i / 3) * 10);
    listMock.mockResolvedValue(makeCandles(closes));
    const config = { timeframe: "M15", periodDays: 1, initialCapital: 10000 };
    const strategy = baseStrategy();
    const asset = { symbol: "XAUUSD" };

    const runA = await runBacktest(strategy, asset, config);
    const runB = await runBacktest(strategy, asset, config);
    expect(runB.metrics).toEqual(runA.metrics);
    expect(runB.trades.length).toBe(runA.trades.length);
  });

  it("positions multiples : plusieurs trades concurrents si max_positions > 1", async () => {
    // Bougies plates : le signal BUY (price > -1e9) est vrai à chaque bougie,
    // et sans exit rapide, plusieurs positions doivent pouvoir s'accumuler
    // jusqu'à max_positions avant que la première ne se ferme.
    const closes = Array.from({ length: 30 }, () => 4000);
    listMock.mockResolvedValue(makeCandles(closes));
    const strategy = baseStrategy({
      exit_conditions: { stop_loss: { type: "pips", value: 1000 }, take_profit: { type: "pips", value: 1000 } },
      risk_management: { type: "fixed", risk_value: 100, max_positions: 3 },
    });
    const result = await runBacktest(strategy, { symbol: "XAUUSD" }, {
      timeframe: "M15", periodDays: 1, initialCapital: 10000,
    });
    // 3 positions ouvertes simultanément puis toutes fermées en fin de run (EOD)
    // => au moins 3 trades clos avec des entry_bar distincts et rapprochés.
    const entryBars = result.trades.map((t) => t.entry_bar);
    expect(new Set(entryBars).size).toBeGreaterThanOrEqual(3);
  });
});
