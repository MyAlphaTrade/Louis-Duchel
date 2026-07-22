import React, { useState, useMemo } from "react";
import { runBacktest } from "@/lib/backtestEngine";
import { Sliders, Loader2, Trophy, TrendingUp, X } from "lucide-react";

const OPTIMIZABLE_FIELDS = [
  { key: "riskPerTrade", label: "Risque par trade (%)", min: 0.5, max: 5, step: 0.5, default: 1 },
  { key: "spread", label: "Spread (pips)", min: 0, max: 5, step: 0.5, default: 0 },
  { key: "slippage", label: "Slippage (pips)", min: 0, max: 3, step: 0.5, default: 0 },
  { key: "commission", label: "Commission ($/lot)", min: 0, max: 10, step: 1, default: 0 },
  { key: "leverage", label: "Levier", min: 1, max: 500, step: 1, default: 100 },
];

function generateValueRange(min, max, step) {
  const values = [];
  for (let v = min; v <= max; v += step) {
    values.push(Math.round(v * 100) / 100);
  }
  return values;
}

async function optimize(strategy, asset, baseConfig, field, metric) {
  const fieldDef = OPTIMIZABLE_FIELDS.find((f) => f.key === field);
  if (!fieldDef) return [];
  const values = generateValueRange(fieldDef.min, fieldDef.max, fieldDef.step);
  const results = [];

  for (const val of values) {
    const cfg = { ...baseConfig, [field]: val };
    try {
      const res = await runBacktest(strategy, asset, cfg);
      results.push({
        field: field,
        value: val,
        netProfit: res.metrics.netProfit,
        profitFactor: res.metrics.profitFactor,
        winRate: res.metrics.winRate,
        maxDrawdown: res.metrics.maxDrawdown,
        expectancy: res.metrics.expectancy,
        totalTrades: res.metrics.totalTrades,
        returnPct: res.metrics.returnPct,
        score: metric === "profitFactor" ? res.metrics.profitFactor
          : metric === "winRate" ? res.metrics.winRate
          : metric === "expectancy" ? res.metrics.expectancy
          : metric === "maxDrawdown" ? -res.metrics.maxDrawdown
          : res.metrics.netProfit,
      });
    } catch {
      // skip
    }
  }
  results.sort((a, b) => b.score - a.score);
  return results;
}

const METRIC_OPTIONS = [
  { value: "netProfit", label: "Profit net" },
  { value: "profitFactor", label: "Profit Factor" },
  { value: "winRate", label: "Taux de réussite" },
  { value: "expectancy", label: "Espérance" },
  { value: "maxDrawdown", label: "Drawdown (min)" },
];

export default function Optimizer({ strategy, asset, config, onClose }) {
  const [field, setField] = useState("riskPerTrade");
  const [metric, setMetric] = useState("netProfit");
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState([]);

  const fieldDef = OPTIMIZABLE_FIELDS.find((f) => f.key === field);

  const handleRun = () => {
    setRunning(true);
    setResults([]);
    setTimeout(async () => {
      try {
        const res = await optimize(strategy, asset, config, field, metric);
        setResults(res);
      } finally {
        setRunning(false);
      }
    }, 100);
  };

  const bestResult = results.length > 0 ? results[0] : null;
  const worstResult = results.length > 0 ? results[results.length - 1] : null;

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1a2332] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sliders className="w-4 h-4 text-amber-400/70" />
          <h3 className="text-sm font-bold text-white">Optimisation de paramètres</h3>
        </div>
        <button onClick={onClose} className="text-slate-600 hover:text-slate-400 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-5">
        <p className="text-xs text-slate-400 mb-4">
          Testez automatiquement une plage de valeurs pour un paramètre et identifiez la configuration optimale
          selon la métrique de votre choix.
        </p>

        <div className="flex flex-wrap gap-3 mb-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-[10px] text-slate-600 uppercase tracking-wider mb-1">Paramètre à tester</label>
            <select
              value={field}
              onChange={(e) => setField(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/30 cursor-pointer"
            >
              {OPTIMIZABLE_FIELDS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="block text-[10px] text-slate-600 uppercase tracking-wider mb-1">Métrique à maximiser</label>
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/30 cursor-pointer"
            >
              {METRIC_OPTIONS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button
              onClick={handleRun}
              disabled={running}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-50 transition-all"
            >
              {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sliders className="w-3.5 h-3.5" />}
              {running ? "Optimisation…" : "Optimiser"}
            </button>
          </div>
        </div>

        {fieldDef && (
          <p className="text-[10px] text-slate-600 mb-4">
            Plage: {fieldDef.min} → {fieldDef.max} (pas de {fieldDef.step})
          </p>
        )}

        {/* Best result */}
        {bestResult && !running && (
          <div className="mb-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center gap-3">
            <Trophy className="w-5 h-5 text-amber-400 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-xs font-bold text-white">
                Optimal: {fieldDef.label} = {bestResult.value}
              </p>
              <div className="flex flex-wrap gap-3 mt-1 text-[10px] text-slate-400">
                <span>Profit: <span className={bestResult.netProfit >= 0 ? "text-emerald-400" : "text-rose-400"}>${bestResult.netProfit.toFixed(2)}</span></span>
                <span>PF: <span className="text-amber-400">{bestResult.profitFactor}</span></span>
                <span>WR: <span className="text-blue-400">{bestResult.winRate}%</span></span>
                <span>DD: <span className="text-rose-400">{bestResult.maxDrawdown}%</span></span>
                <span>Return: <span className={bestResult.returnPct >= 0 ? "text-emerald-400" : "text-rose-400"}>{bestResult.returnPct}%</span></span>
              </div>
            </div>
          </div>
        )}

        {/* Results table */}
        {results.length > 0 && !running && (
          <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-[#0d1220]">
                <tr className="border-b border-[#1a2332]">
                  <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Rang</th>
                  <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Valeur</th>
                  <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Profit</th>
                  <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">PF</th>
                  <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">WR%</th>
                  <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">DD%</th>
                  <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Trades</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className={`border-b border-[#1a2332] last:border-0 hover:bg-white/[0.02] transition-colors ${i === 0 ? "bg-amber-500/5" : ""}`}>
                    <td className="px-3 py-2">
                      <span className={`text-xs font-bold ${i === 0 ? "text-amber-400" : "text-slate-500"}`}>
                        {i === 0 ? "★" : `#${i + 1}`}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-xs text-slate-300 font-mono">{r.value}</span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className={`text-xs font-mono ${r.netProfit >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {r.netProfit >= 0 ? "+" : ""}${r.netProfit.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className={`text-xs font-mono ${r.profitFactor >= 1 ? "text-emerald-400" : "text-rose-400"}`}>{r.profitFactor}</span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="text-xs text-slate-400 font-mono">{r.winRate}%</span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="text-xs text-rose-400 font-mono">{r.maxDrawdown}%</span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="text-xs text-slate-500 font-mono">{r.totalTrades}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {running && (
          <div className="flex flex-col items-center py-12">
            <Loader2 className="w-6 h-6 text-amber-400 animate-spin mb-3" />
            <p className="text-xs text-slate-500">Test des combinaisons en cours…</p>
            <p className="text-[10px] text-slate-600 mt-1">
              {fieldDef ? `Plage: ${fieldDef.min} → ${fieldDef.max}` : ""}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}