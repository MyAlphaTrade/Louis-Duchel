import { describe, it, expect } from "vitest";
import {
  hasFullTradeDetail,
  equityCurveFromTrades,
  deriveMetricsFromSavedResult,
} from "../backtestResultMetrics";

const fullTrade = (overrides) => ({
  direction: "BUY",
  entry_price: 100,
  exit_price: 101,
  volume: 1,
  stop_loss: 99,
  take_profit: 102,
  close_reason: "TP",
  profit: 100,
  equity_after: 10100,
  entry_time: "2026-01-05T00:00:00Z",
  exit_time: "2026-01-05T01:00:00Z",
  ...overrides,
});

describe("hasFullTradeDetail", () => {
  it("returns false for a legacy record (no initial_capital, no direction)", () => {
    const legacy = {
      total_trades: 2,
      trades: [{ type: "BUY", profit: 10, entry_price: 1, exit_price: 1.1 }],
    };
    expect(hasFullTradeDetail(legacy)).toBe(false);
  });

  it("returns false when trades array is empty even with initial_capital set", () => {
    expect(hasFullTradeDetail({ initial_capital: 10000, trades: [] })).toBe(false);
  });

  it("returns true for a complete record saved after the 2026-09-17 fix", () => {
    expect(hasFullTradeDetail({ initial_capital: 10000, trades: [fullTrade()] })).toBe(true);
  });
});

describe("deriveMetricsFromSavedResult", () => {
  it("returns null rather than a half-filled object for a legacy record", () => {
    expect(deriveMetricsFromSavedResult({ trades: [{ type: "BUY", profit: 10 }] })).toBeNull();
  });

  it("recomputes avgWin/avgLoss/expectancy/winLossRatio from real trade profits", () => {
    const result = {
      initial_capital: 10000,
      total_profit: 100,
      total_trades: 2,
      winning_trades: 1,
      losing_trades: 1,
      win_rate: 50,
      profit_factor: 2,
      max_drawdown: 5,
      start_date: "2026-01-01",
      end_date: "2026-01-03",
      trades: [
        fullTrade({ profit: 200, exit_time: "2026-01-02T00:00:00Z" }),
        fullTrade({ direction: "SELL", profit: -100, exit_time: "2026-01-03T00:00:00Z" }),
      ],
    };
    const { metrics } = deriveMetricsFromSavedResult(result);
    expect(metrics.avgWin).toBe(200);
    expect(metrics.avgLoss).toBe(100);
    expect(metrics.expectancy).toBe(50);
    expect(metrics.winLossRatio).toBe(2);
    expect(metrics.finalEquity).toBe(10100);
    expect(metrics.returnPct).toBe(1);
    // 2 jours calendaires entre start_date et end_date, 2 trades -> 1/jour
    expect(metrics.tradesPerDay).toBe(1);
  });

  it("never fabricates winLossRatio when there are no losing trades to divide by", () => {
    const result = {
      initial_capital: 10000,
      total_profit: 200,
      total_trades: 1,
      trades: [fullTrade({ profit: 200 })],
    };
    const { metrics } = deriveMetricsFromSavedResult(result);
    expect(metrics.avgLoss).toBe(0);
    expect(metrics.winLossRatio).toBeNull();
  });
});

describe("equityCurveFromTrades", () => {
  it("returns an empty curve rather than guessing when initialCapital is missing", () => {
    expect(equityCurveFromTrades([fullTrade()], null)).toEqual([]);
  });

  it("builds a real cumulative step curve ordered by exit_time, independent of input order", () => {
    const trades = [
      fullTrade({ profit: -50, exit_time: "2026-01-06T00:00:00Z" }),
      fullTrade({ profit: 100, exit_time: "2026-01-05T00:00:00Z" }),
    ];
    const curve = equityCurveFromTrades(trades, 10000);
    expect(curve.map((p) => p.equity)).toEqual([10100, 10050]);
    expect(curve[0].timestamp).toBe("2026-01-05T00:00:00Z");
  });

  it("tracks drawdown from the running peak, not from the initial capital", () => {
    const trades = [
      fullTrade({ profit: 1000, exit_time: "2026-01-05T00:00:00Z" }), // peak 11000
      fullTrade({ profit: -1100, exit_time: "2026-01-06T00:00:00Z" }), // equity 9900, DD vs peak 11000
    ];
    const curve = equityCurveFromTrades(trades, 10000);
    expect(curve[1].equity).toBe(9900);
    expect(curve[1].drawdown).toBeCloseTo(10, 5); // (11000-9900)/11000*100
  });
});
