import React, { useState, useEffect, useMemo } from "react";
import { base44 } from "@/api/base44Client";
import { useToast } from "@/components/ui/use-toast";
import SummaryStats, { StatCard, STAT_CARD_COLORS } from "@/components/backtesting/SummaryStats";
import EquityCurve from "@/components/backtesting/EquityCurve";
import TradeJournal from "@/components/backtesting/TradeJournal";
import { hasFullTradeDetail, deriveMetricsFromSavedResult } from "@/lib/backtestResultMetrics";
import {
  Layers, Search, X, TrendingUp, TrendingDown, Target, Scale, Activity, BarChart3,
  Bookmark, ChevronDown, Loader2, Info,
} from "lucide-react";

// Seuils PUREMENT indicatifs pour colorer une colonne dans ce tableau
// comparatif -- jamais un mecanisme de declenchement. Voir la correction de
// Louis (17/09/2026, memoire project_strategy_lab_global_contract) : un
// score/seuil de confiance ne doit jamais decider d'une execution, mais
// trier visuellement des resultats de backtest deja clos pour l'oeil humain
// reste un usage different et accepte.
function gradeSharpe(v) {
  if (v == null) return "neutral";
  return v >= 1.2 ? "profit" : v >= 0.7 ? "amber" : "loss";
}
function gradeDrawdown(v) {
  if (v == null) return "neutral";
  return v <= 8 ? "profit" : v <= 15 ? "amber" : "loss";
}
function gradeWinRate(v) {
  if (v == null) return "neutral";
  return v >= 50 ? "profit" : v >= 40 ? "amber" : "loss";
}

const CHIP_CLASS = {
  profit: "bg-emerald-500/10 text-emerald-400",
  amber: "bg-amber-500/10 text-amber-400",
  loss: "bg-rose-500/10 text-rose-400",
  neutral: "bg-slate-500/10 text-slate-400",
};

function Chip({ grade, children }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-bold tabular-nums ${CHIP_CLASS[grade]}`}>
      {children}
    </span>
  );
}

const SORT_KEYS = {
  sharpe: (r) => r.sharpe_ratio,
  dd: (r) => r.max_drawdown,
  trades: (r) => r.total_trades,
  winRate: (r) => r.win_rate,
  pnl: (r) => r.total_profit,
};

function SortHeader({ label, sortKey, sort, setSort }) {
  const active = sort.key === sortKey;
  return (
    <th
      className="px-3 pb-2.5 text-left text-[10px] font-bold tracking-wider text-slate-500 uppercase cursor-pointer select-none hover:text-slate-300 transition-colors"
      onClick={() => setSort((s) => ({ key: sortKey, dir: s.key === sortKey ? -s.dir : 1 }))}
    >
      {label}
      <span className={`ml-1 ${active ? "text-amber-400" : "text-slate-700"}`}>
        {active && sort.dir === -1 ? "▴" : "▾"}
      </span>
    </th>
  );
}

function DetailOverlay({ result, strategy, onClose }) {
  const full = hasFullTradeDetail(result) ? deriveMetricsFromSavedResult(result) : null;
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center overflow-y-auto p-6 lg:p-10" onClick={onClose}>
      <div
        className="w-full max-w-5xl rounded-2xl bg-[#0a0e17] border border-[#1a2332] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-5">
          <div>
            <h2 className="text-xl font-bold text-white">{strategy?.name || "Stratégie supprimée"}</h2>
            <p className="text-xs text-slate-500 mt-1">
              {result.asset_symbol || strategy?.asset_symbols?.[0] || "?"} · {result.start_date} → {result.end_date} · {result.total_trades} trades
            </p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg bg-white/5 text-slate-400 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {full ? (
          <div className="space-y-4">
            <SummaryStats metrics={full.metrics} />
            <EquityCurve equityCurve={full.equityCurve} initialCapital={full.metrics.initialCapital} />
            <TradeJournal trades={result.trades} />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              <StatCard icon={TrendingUp} label="Profit total" value={`${result.total_profit >= 0 ? "+" : ""}$${(result.total_profit ?? 0).toFixed(2)}`} color={result.total_profit >= 0 ? STAT_CARD_COLORS.profit : STAT_CARD_COLORS.loss} />
              <StatCard icon={BarChart3} label="Trades totaux" value={result.total_trades} color={STAT_CARD_COLORS.neutral} />
              <StatCard icon={Target} label="Taux de réussite" value={`${result.win_rate ?? "—"}%`} color={result.win_rate >= 50 ? STAT_CARD_COLORS.profit : STAT_CARD_COLORS.loss} />
              <StatCard icon={Scale} label="Profit Factor" value={result.profit_factor ?? "—"} color={result.profit_factor >= 1 ? STAT_CARD_COLORS.profit : STAT_CARD_COLORS.loss} />
              <StatCard icon={Activity} label="Drawdown max" value={`${result.max_drawdown ?? "—"}%`} color={STAT_CARD_COLORS.loss} />
              <StatCard icon={TrendingDown} label="Sharpe" value={result.sharpe_ratio ?? "—"} color={STAT_CARD_COLORS.blue} />
            </div>
            <div className="flex items-start gap-2 p-4 rounded-xl bg-amber-500/5 border border-amber-500/15 text-xs text-slate-400">
              <Info className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              Résultat sauvegardé avant la mise à jour du 17/09/2026 — le détail complet (courbe de capital, journal des opérations)
              n'a pas été conservé pour cet enregistrement. Relancez ce backtest pour obtenir le détail complet.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function StrategiesDiscovered() {
  const { toast } = useToast();
  const [strategies, setStrategies] = useState([]);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [assetFilter, setAssetFilter] = useState("");
  const [sort, setSort] = useState({ key: "pnl", dir: -1 });
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [s, r] = await Promise.all([
          base44.entities.Strategy.list("-created_date", 500),
          base44.entities.BacktestResult.list("-created_date", 500),
        ]);
        if (mounted) { setStrategies(s); setResults(r); setLoading(false); }
      } catch (err) {
        if (mounted) setLoading(false);
        toast({ title: "Erreur de chargement", description: err.message, variant: "destructive" });
      }
    })();
    return () => { mounted = false; };
  }, []);

  // Une ligne par strategie testee = son resultat de backtest le PLUS
  // RECENT (results deja tries -created_date). Une strategie jamais
  // backtestee n'apparait pas ici -- "decouverte" suppose un resultat reel.
  const rows = useMemo(() => {
    const latestByStrategy = new Map();
    for (const r of results) {
      if (!latestByStrategy.has(r.strategy_id)) latestByStrategy.set(r.strategy_id, r);
    }
    let list = [...latestByStrategy.entries()].map(([strategyId, result]) => ({
      strategy: strategies.find((s) => s.id === strategyId) || null,
      result,
    }));
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(({ strategy }) => strategy?.name?.toLowerCase().includes(q));
    }
    if (assetFilter) {
      list = list.filter(({ result, strategy }) => (result.asset_symbol || strategy?.asset_symbols?.[0]) === assetFilter);
    }
    const keyFn = SORT_KEYS[sort.key];
    list.sort((a, b) => {
      const av = keyFn(a.result), bv = keyFn(b.result);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * sort.dir;
    });
    return list;
  }, [strategies, results, search, assetFilter, sort]);

  const assetOptions = useMemo(() => {
    const set = new Set();
    for (const r of results) if (r.asset_symbol) set.add(r.asset_symbol);
    return [...set].sort();
  }, [results]);

  const toggleShortlist = async (strategy, e) => {
    e.stopPropagation();
    if (!strategy) return;
    try {
      const updated = await base44.entities.Strategy.update(strategy.id, { shortlisted: !strategy.shortlisted });
      setStrategies((prev) => prev.map((s) => (s.id === strategy.id ? updated : s)));
    } catch (err) {
      toast({ title: "Erreur", description: err.message, variant: "destructive" });
    }
  };

  return (
    <div className="p-6 lg:p-10">
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Layers className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">Module 8</span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Stratégies découvertes
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-2xl">
          Vue d'ensemble de toutes les stratégies déjà backtestées, triable pour comparer en un coup d'œil. Cliquez une ligne pour ouvrir le détail complet.
        </p>
      </div>

      <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] p-5">
        <div className="flex items-center gap-3 flex-wrap mb-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="w-4 h-4 text-slate-600 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher une stratégie…"
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40"
            />
          </div>
          <div className="relative">
            <select
              value={assetFilter}
              onChange={(e) => setAssetFilter(e.target.value)}
              className="appearance-none pl-3 pr-8 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-sm text-slate-300 focus:outline-none focus:border-amber-500/40"
            >
              <option value="">Tous les actifs</option>
              {assetOptions.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-600 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>
        <p className="text-[11px] text-slate-600 mb-4 flex items-center gap-1.5">
          <Bookmark className="w-3 h-3" />
          Le bascule "Suivi" est un simple repère manuel pour toi — il ne déclenche ni n'active aucune exécution automatique.
        </p>

        {loading ? (
          <div className="flex items-center gap-2 text-slate-500 py-8 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-xs">Chargement…</span>
          </div>
        ) : rows.length === 0 ? (
          <div className="text-center py-10 text-slate-500 text-sm">
            Aucune stratégie backtestée pour l'instant — lancez un backtest depuis le Module 3 puis sauvegardez le résultat.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="px-3 pb-2.5 text-left text-[10px] font-bold tracking-wider text-slate-500 uppercase">Stratégie</th>
                  <th className="px-3 pb-2.5 text-left text-[10px] font-bold tracking-wider text-slate-500 uppercase">Actif</th>
                  <SortHeader label="Sharpe" sortKey="sharpe" sort={sort} setSort={setSort} />
                  <SortHeader label="Max DD" sortKey="dd" sort={sort} setSort={setSort} />
                  <SortHeader label="Trades" sortKey="trades" sort={sort} setSort={setSort} />
                  <SortHeader label="Win Rate" sortKey="winRate" sort={sort} setSort={setSort} />
                  <SortHeader label="Net P&L" sortKey="pnl" sort={sort} setSort={setSort} />
                  <th className="px-3 pb-2.5 text-left text-[10px] font-bold tracking-wider text-slate-500 uppercase">Suivi</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ strategy, result }) => {
                  const isProfit = (result.total_profit ?? 0) >= 0;
                  return (
                    <tr
                      key={result.id}
                      onClick={() => setSelected({ strategy, result })}
                      className="border-t border-[#1a2332] hover:bg-white/[0.02] cursor-pointer transition-colors"
                    >
                      <td className="px-3 py-3">
                        <p className="text-sm font-medium text-white">{strategy?.name || "Stratégie supprimée"}</p>
                        <p className="text-[10px] text-slate-600">{strategy?.primary_timeframe || "—"}</p>
                      </td>
                      <td className="px-3 py-3 text-sm text-slate-400">{result.asset_symbol || strategy?.asset_symbols?.[0] || "—"}</td>
                      <td className="px-3 py-3"><Chip grade={gradeSharpe(result.sharpe_ratio)}>{result.sharpe_ratio != null ? result.sharpe_ratio.toFixed(2) : "—"}</Chip></td>
                      <td className="px-3 py-3"><Chip grade={gradeDrawdown(result.max_drawdown)}>{result.max_drawdown != null ? `${result.max_drawdown}%` : "—"}</Chip></td>
                      <td className="px-3 py-3 text-sm text-slate-300 tabular-nums">{result.total_trades}</td>
                      <td className="px-3 py-3"><Chip grade={gradeWinRate(result.win_rate)}>{result.win_rate != null ? `${result.win_rate}%` : "—"}</Chip></td>
                      <td className={`px-3 py-3 text-sm font-bold tabular-nums ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        {isProfit ? "+" : ""}${(result.total_profit ?? 0).toFixed(2)}
                      </td>
                      <td className="px-3 py-3">
                        <button
                          onClick={(e) => toggleShortlist(strategy, e)}
                          className={`w-9 h-5 rounded-full border transition-colors relative ${
                            strategy?.shortlisted ? "bg-emerald-500/25 border-emerald-500/30" : "bg-[#1a2332] border-[#2a3548]"
                          }`}
                        >
                          <span className={`absolute top-0.5 w-3.5 h-3.5 rounded-full transition-all ${
                            strategy?.shortlisted ? "left-4.5 bg-emerald-400" : "left-0.5 bg-slate-500"
                          }`} style={strategy?.shortlisted ? { left: "1.15rem" } : undefined} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <DetailOverlay result={selected.result} strategy={selected.strategy} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
