import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { useToast } from "@/components/ui/use-toast";
import { GitCompare, X, TrendingUp, TrendingDown, Trophy } from "lucide-react";

const COMPARE_FIELDS = [
  { key: "total_profit", label: "Profit net", format: (v) => `${v >= 0 ? "+" : ""}$${(v || 0).toFixed(2)}`, type: "currency" },
  { key: "win_rate", label: "Win Rate", format: (v) => `${(v || 0).toFixed(1)}%`, type: "percent" },
  { key: "profit_factor", label: "Profit Factor", format: (v) => (v || 0).toFixed(2), type: "number" },
  { key: "max_drawdown", label: "Drawdown max", format: (v) => `${(v || 0).toFixed(2)}%`, type: "percent" },
  { key: "total_trades", label: "Trades", format: (v) => `${v || 0}`, type: "count" },
  { key: "winning_trades", label: "Gagnants", format: (v) => `${v || 0}`, type: "count" },
  { key: "losing_trades", label: "Perdants", format: (v) => `${v || 0}`, type: "count" },
];

function formatDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
}

export default function BacktestComparison({ strategies, currentResult, onClose }) {
  const { toast } = useToast();
  const [saved, setSaved] = useState([]);
  const [selected, setSelected] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await base44.entities.BacktestResult.list("-created_date", 50);
        if (mounted) { setSaved(data); setLoading(false); }
      } catch {
        if (mounted) setLoading(false);
      }
    };
    load();
    return () => { mounted = false; };
  }, []);

  const toggleSelect = (item) => {
    setSelected((prev) => {
      const exists = prev.find((p) => p.id === item.id);
      if (exists) return prev.filter((p) => p.id !== item.id);
      if (prev.length >= 4) {
        toast({ title: "Maximum 4 backtests", description: "Désélectionnez-en un pour comparer.", variant: "destructive" });
        return prev;
      }
      return [...prev, item];
    });
  };

  const allItems = [...selected];
  if (currentResult && !allItems.find((i) => i.id === "current")) {
    allItems.unshift({ id: "current", ...currentResult, _isCurrent: true });
  }

  // Find best value for each metric across all selected
  const bestByField = {};
  COMPARE_FIELDS.forEach((f) => {
    if (f.type === "count" && f.key === "losing_trades") {
      bestByField[f.key] = Math.min(...allItems.map((i) => i[f.key] || 0));
    } else if (f.key === "max_drawdown") {
      bestByField[f.key] = Math.min(...allItems.map((i) => i[f.key] || 999));
    } else if (f.type === "currency" || f.type === "number" || f.type === "percent") {
      bestByField[f.key] = Math.max(...allItems.map((i) => i[f.key] || -999));
    } else {
      bestByField[f.key] = Math.max(...allItems.map((i) => i[f.key] || 0));
    }
  });

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1a2332] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitCompare className="w-4 h-4 text-amber-400/70" />
          <h3 className="text-sm font-bold text-white">Comparaison de backtests</h3>
        </div>
        <button onClick={onClose} className="text-slate-600 hover:text-slate-400 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-5">
        {/* Selected backtests comparison table */}
        {allItems.length > 1 && (
          <div className="overflow-x-auto mb-4">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#1a2332]">
                  <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 sticky left-0 bg-[#0d1220]">Métrique</th>
                  {allItems.map((item) => (
                    <th key={item.id} className="text-center text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 min-w-[120px]">
                      <div className="flex flex-col items-center gap-1">
                        <span className={`px-2 py-0.5 rounded-full text-[9px] ${item._isCurrent ? "bg-amber-500/10 text-amber-400" : "bg-white/5 text-slate-400"}`}>
                          {item._isCurrent ? "Actuel" : formatDate(item.start_date)}
                        </span>
                        <span className="text-[10px] text-slate-500 truncate max-w-[100px]">
                          {strategies.find((s) => s.id === item.strategy_id)?.name || "—"}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARE_FIELDS.map((f) => (
                  <tr key={f.key} className="border-b border-[#1a2332] last:border-0 hover:bg-white/[0.02]">
                    <td className="text-left text-[10px] text-slate-500 px-3 py-2.5 sticky left-0 bg-[#0d1220]">{f.label}</td>
                    {allItems.map((item) => {
                      const val = item[f.key];
                      const isBest = val === bestByField[f.key];
                      const display = f.format(val);
                      return (
                        <td key={item.id} className="text-center px-3 py-2.5">
                          <span className={`text-xs font-mono ${isBest ? "text-amber-400 font-bold" : "text-slate-400"}`}>
                            {isBest && "★ "}{display}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Selection from saved backtests */}
        <div>
          <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-2">
            Sélectionnez des backtests sauvegardés à comparer {currentResult ? "(+ le résultat actuel)" : ""}
          </p>
          {loading ? (
            <div className="flex items-center gap-2 text-slate-500 py-4">
              <div className="w-4 h-4 border-2 border-amber-500/20 border-t-amber-500 rounded-full animate-spin" />
              <span className="text-xs">Chargement…</span>
            </div>
          ) : saved.length === 0 ? (
            <p className="text-xs text-slate-600 py-4">Aucun backtest sauvegardé à comparer.</p>
          ) : (
            <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
              {saved.map((item) => {
                const isSelected = selected.find((p) => p.id === item.id);
                const strategy = strategies.find((s) => s.id === item.strategy_id);
                const isProfit = (item.total_profit || 0) >= 0;
                return (
                  <button
                    key={item.id}
                    onClick={() => toggleSelect(item)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors text-left ${
                      isSelected
                        ? "bg-amber-500/10 border-amber-500/20"
                        : "bg-[#0a0e17] border-[#1a2332] hover:border-[#2a3548]"
                    }`}
                  >
                    <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${isProfit ? "bg-emerald-500/10" : "bg-rose-500/10"}`}>
                      {isProfit ? <TrendingUp className="w-3.5 h-3.5 text-emerald-400" /> : <TrendingDown className="w-3.5 h-3.5 text-rose-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-slate-300 truncate">{strategy?.name || "—"}</p>
                      <p className="text-[10px] text-slate-600">{formatDate(item.start_date)} → {formatDate(item.end_date)} · {item.total_trades} trades</p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p className={`text-xs font-bold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        {isProfit ? "+" : ""}${(item.total_profit || 0).toFixed(0)}
                      </p>
                      <p className="text-[10px] text-slate-600">PF {item.profit_factor?.toFixed(2)}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}