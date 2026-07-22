import React, { useState, useMemo } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, Cell,
} from "recharts";
import { Dice5, Loader2, X, Skull, TrendingUp, AlertTriangle } from "lucide-react";
import { runBacktest, bootstrapTradeSimulation } from "@/lib/backtestEngine";

function getPercentile(sortedArr, p) {
  if (sortedArr.length === 0) return 0;
  const idx = Math.floor((p / 100) * (sortedArr.length - 1));
  return sortedArr[idx];
}

const ITERATION_OPTIONS = [25, 50, 100];
// En-dessous de ce nombre de trades reels, un rééchantillonnage (bootstrap)
// n'a pas assez de matière première pour être statistiquement parlant.
const MIN_TRADES_FOR_BOOTSTRAP = 5;

export default function MonteCarloAnalysis({ strategy, asset, config, trades, dataSource, onClose }) {
  const [iterations, setIterations] = useState(50);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState([]);

  const closedTradeCount = (trades || []).filter((t) => typeof t.profit === "number").length;
  const canBootstrap = dataSource === "real" && closedTradeCount >= MIN_TRADES_FOR_BOOTSTRAP;
  const bootstrapBlocked = dataSource === "real" && closedTradeCount > 0 && closedTradeCount < MIN_TRADES_FOR_BOOTSTRAP;

  const handleRun = () => {
    // Mode donnees reelles : rééchantillonnage des trades deja obtenus
    // (tirage avec remise) — purement arithmetique, donc instantane, pas
    // besoin de decouper en chunks async comme pour le mode synthetique.
    if (canBootstrap) {
      setRunning(true);
      setResults(bootstrapTradeSimulation(trades, config.initialCapital, iterations));
      setRunning(false);
      return;
    }

    // Mode donnees synthetiques : chaque iteration re-simule le moteur
    // complet sur de nouvelles bougies aleatoires -- plus lent, decoupe en
    // chunks pour ne pas geler l'interface.
    setRunning(true);
    setResults([]);
    setTimeout(() => {
      const all = [];
      const chunkSize = 5;
      const runChunk = async (start) => {
        if (start >= iterations) {
          setResults(all);
          setRunning(false);
          return;
        }
        const end = Math.min(start + chunkSize, iterations);
        for (let i = start; i < end; i++) {
          try {
            const res = await runBacktest(strategy, asset, config);
            all.push({
              iteration: i + 1,
              netProfit: res.metrics.netProfit,
              maxDrawdown: res.metrics.maxDrawdown,
              winRate: res.metrics.winRate,
              profitFactor: res.metrics.profitFactor,
              finalEquity: res.metrics.finalEquity,
              returnPct: res.metrics.returnPct,
            });
          } catch {
            // skip
          }
        }
        setResults([...all]);
        if (end < iterations) {
          setTimeout(() => runChunk(end), 0);
        } else {
          setRunning(false);
        }
      };
      runChunk(0);
    }, 100);
  };

  const sortedProfits = useMemo(() => [...results].sort((a, b) => a.netProfit - b.netProfit), [results]);
  const sortedDD = useMemo(() => [...results].sort((a, b) => a.maxDrawdown - b.maxDrawdown), [results]);
  // getPercentile expects an array of numbers — extract the relevant field
  // from the sorted result objects before computing percentiles (pre-existing
  // bug: passing the objects directly made stats.median etc. an object, not
  // a number, crashing .toFixed() calls below).
  const sortedProfitValues = useMemo(() => sortedProfits.map((r) => r.netProfit), [sortedProfits]);
  const sortedDDValues = useMemo(() => sortedDD.map((r) => r.maxDrawdown), [sortedDD]);

  const stats = {
    median: getPercentile(sortedProfitValues, 50),
    p5: getPercentile(sortedProfitValues, 5),
    p25: getPercentile(sortedProfitValues, 25),
    p75: getPercentile(sortedProfitValues, 75),
    p95: getPercentile(sortedProfitValues, 95),
    worst: sortedProfits[0]?.netProfit || 0,
    best: sortedProfits[sortedProfits.length - 1]?.netProfit || 0,
    mean: results.length > 0 ? results.reduce((s, r) => s + r.netProfit, 0) / results.length : 0,
    medianDD: getPercentile(sortedDDValues, 50),
    ruinCount: results.filter((r) => r.netProfit <= -(config.initialCapital * 0.5)).length,
  };

  const riskOfRuin = results.length > 0 ? (stats.ruinCount / results.length) * 100 : 0;
  const profitProb = results.length > 0
    ? (results.filter((r) => r.netProfit > 0).length / results.length) * 100
    : 0;

  const histogram = useMemo(() => {
    if (results.length === 0) return [];
    const min = Math.min(...results.map((r) => r.netProfit));
    const max = Math.max(...results.map((r) => r.netProfit));
    const bins = 10;
    const binSize = (max - min) / bins || 1;
    const buckets = Array(bins).fill(0).map((_, i) => ({
      range: `${(min + i * binSize).toFixed(0)}`,
      rangeFull: `$${(min + i * binSize).toFixed(0)} → $${(min + (i + 1) * binSize).toFixed(0)}`,
      count: 0,
      midpoint: (min + i * binSize + binSize / 2),
    }));
    results.forEach((r) => {
      let idx = Math.floor((r.netProfit - min) / binSize);
      if (idx >= bins) idx = bins - 1;
      if (idx < 0) idx = 0;
      buckets[idx].count++;
    });
    return buckets;
  }, [results]);

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1a2332] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Dice5 className="w-4 h-4 text-violet-400/70" />
          <h3 className="text-sm font-bold text-white">Analyse Monte Carlo</h3>
        </div>
        <button onClick={onClose} className="text-slate-600 hover:text-slate-400 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-5">
        <p className="text-xs text-slate-400 mb-4">
          {canBootstrap
            ? `Rééchantillonne les ${closedTradeCount} trades réels obtenus (tirage avec remise, ${iterations} tirages) pour estimer la distribution des résultats possibles selon l'ordre dans lequel ces trades auraient pu survenir.`
            : bootstrapBlocked
            ? `Seulement ${closedTradeCount} trade(s) réel(s) obtenu(s) — pas assez pour une analyse statistique fiable (minimum ${MIN_TRADES_FOR_BOOTSTRAP}).`
            : `Simule la stratégie ${iterations} fois avec des données de marché aléatoires pour estimer la distribution des résultats et le risque de ruine.`}
        </p>

        {bootstrapBlocked ? (
          <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-amber-500/5 border border-amber-500/20 text-[11px] text-amber-400 mb-2">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            Relancez le backtest sur une période plus longue pour obtenir davantage de trades, puis réessayez.
          </div>
        ) : (
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-600 uppercase tracking-wider">Itérations</span>
              {ITERATION_OPTIONS.map((n) => (
                <button
                  key={n}
                  onClick={() => setIterations(n)}
                  disabled={running}
                  className={`text-[10px] px-3 py-1 rounded-lg border transition-colors ${
                    iterations === n
                      ? "bg-violet-500/10 border-violet-500/20 text-violet-400"
                      : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
            <button
              onClick={handleRun}
              disabled={running}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-violet-500 to-violet-600 text-white font-semibold text-sm hover:from-violet-400 hover:to-violet-500 disabled:opacity-50 transition-all"
            >
              {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Dice5 className="w-3.5 h-3.5" />}
              {running ? `Simulation… (${results.length}/${iterations})` : "Lancer"}
            </button>
          </div>
        )}

        {results.length > 0 && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              <div className={`p-3 rounded-xl border ${profitProb >= 50 ? "bg-emerald-500/5 border-emerald-500/20" : "bg-rose-500/5 border-rose-500/20"}`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <TrendingUp className={`w-3 h-3 ${profitProb >= 50 ? "text-emerald-400" : "text-rose-400"}`} />
                  <span className="text-[9px] text-slate-600 uppercase tracking-wider">Probabilité de profit</span>
                </div>
                <p className={`text-lg font-bold ${profitProb >= 50 ? "text-emerald-400" : "text-rose-400"}`}>{profitProb.toFixed(1)}%</p>
              </div>
              <div className="p-3 rounded-xl border bg-amber-500/5 border-amber-500/20">
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[9px] text-slate-600 uppercase tracking-wider">Profit médian</span>
                </div>
                <p className={`text-lg font-bold ${stats.median >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {stats.median >= 0 ? "+" : ""}${stats.median.toFixed(0)}
                </p>
              </div>
              <div className="p-3 rounded-xl border bg-rose-500/5 border-rose-500/20">
                <div className="flex items-center gap-1.5 mb-1">
                  <Skull className="w-3 h-3 text-rose-400" />
                  <span className="text-[9px] text-slate-600 uppercase tracking-wider">Risque de ruine</span>
                </div>
                <p className="text-lg font-bold text-rose-400">{riskOfRuin.toFixed(1)}%</p>
                <p className="text-[9px] text-slate-600">perte &gt; 50%</p>
              </div>
              <div className="p-3 rounded-xl border bg-blue-500/5 border-blue-500/20">
                <div className="flex items-center gap-1.5 mb-1">
                  <AlertTriangle className="w-3 h-3 text-blue-400" />
                  <span className="text-[9px] text-slate-600 uppercase tracking-wider">DD médian</span>
                </div>
                <p className="text-lg font-bold text-blue-400">{stats.medianDD.toFixed(1)}%</p>
              </div>
            </div>

            {histogram.length > 0 && (
              <div className="mb-4">
                <h4 className="text-[10px] text-slate-600 uppercase tracking-wider mb-2">Distribution des profits</h4>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={histogram} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1a2332" />
                    <XAxis
                      dataKey="range"
                      tick={{ fill: "#475569", fontSize: 9 }}
                      stroke="#1a2332"
                      tickFormatter={(v) => `$${v}`}
                    />
                    <YAxis
                      tick={{ fill: "#475569", fontSize: 10 }}
                      stroke="#1a2332"
                      width={30}
                      tickFormatter={(v) => `${v}`}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#0a0e17",
                        border: "1px solid #1a2332",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      labelStyle={{ color: "#64748b" }}
                      formatter={(value) => [`${value} simulations`, "Occurrences"]}
                      labelFormatter={(_, payload) => payload?.[0]?.payload?.rangeFull || ""}
                    />
                    <ReferenceLine x={histogram.find((h) => h.midpoint >= 0)?.range} stroke="#334155" strokeDasharray="4 4" />
                    <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                      {histogram.map((entry, i) => (
                        <Cell key={i} fill={entry.midpoint >= 0 ? "#34d399" : "#f43f5e"} fillOpacity={0.6} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
              {[
                { label: "Pire", value: stats.worst, color: "text-rose-400" },
                { label: "P5 (5%)", value: stats.p5, color: "text-rose-400" },
                { label: "P25", value: stats.p25, color: "text-amber-400" },
                { label: "Médiane", value: stats.median, color: "text-amber-400" },
                { label: "P75", value: stats.p75, color: "text-emerald-400" },
                { label: "Meilleur", value: stats.best, color: "text-emerald-400" },
              ].map((p) => (
                <div key={p.label} className="p-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-center">
                  <p className="text-[9px] text-slate-600 uppercase tracking-wider">{p.label}</p>
                  <p className={`text-xs font-bold font-mono ${p.color}`}>
                    {p.value >= 0 ? "+" : ""}${p.value.toFixed(0)}
                  </p>
                </div>
              ))}
            </div>

            {canBootstrap && (
              <p className="text-[9px] text-slate-600 mt-3">
                Le drawdown ci-dessus est mesuré entre les clôtures de trades (à partir des {closedTradeCount} trades
                réels rééchantillonnés), pas bougie par bougie comme la courbe de capital du run principal ci-dessus —
                légèrement moins précis, mais représentatif du risque de séquence.
              </p>
            )}
          </>
        )}

        {results.length === 0 && !running && (
          <div className="text-center py-8">
            <Dice5 className="w-8 h-8 text-slate-700 mx-auto mb-2" />
            <p className="text-xs text-slate-600">Lancez la simulation pour voir la distribution des résultats.</p>
          </div>
        )}
      </div>
    </div>
  );
}