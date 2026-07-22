import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { useToast } from "@/components/ui/use-toast";
import { History, Trash2, TrendingUp, TrendingDown, ChevronRight } from "lucide-react";

function formatDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

export default function SavedBacktests({ strategies, onSelect }) {
  const { toast } = useToast();
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await base44.entities.BacktestResult.list("-created_date", 20);
        if (mounted) { setResults(data); setLoading(false); }
      } catch {
        if (mounted) setLoading(false);
      }
    };
    load();
    const unsub = base44.entities.BacktestResult.subscribe((event) => {
      if (!mounted) return;
      if (event.type === "create") setResults((prev) => [event.data, ...prev].slice(0, 20));
      else if (event.type === "update") setResults((prev) => prev.map((r) => (r.id === event.data.id ? event.data : r)));
      else if (event.type === "delete") setResults((prev) => prev.filter((r) => r.id !== event.id));
    });
    return () => { mounted = false; unsub(); };
  }, []);

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    try {
      await base44.entities.BacktestResult.delete(id);
      toast({ title: "Backtest supprimé" });
    } catch (err) {
      toast({ title: "Erreur", description: err.message, variant: "destructive" });
    }
  };

  if (loading) {
    return (
      <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
        <div className="flex items-center gap-2 text-slate-500">
          <div className="w-4 h-4 border-2 border-amber-500/20 border-t-amber-500 rounded-full animate-spin" />
          <span className="text-xs">Chargement de l'historique…</span>
        </div>
      </div>
    );
  }

  if (results.length === 0) return null;

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1a2332] flex items-center gap-2">
        <History className="w-4 h-4 text-amber-400/70" />
        <h3 className="text-sm font-bold text-white">Backtests sauvegardés</h3>
        <span className="text-[10px] text-slate-600 ml-1">{results.length}</span>
      </div>
      <div className="divide-y divide-[#1a2332] max-h-[300px] overflow-y-auto">
        {results.map((r) => {
          const strategy = strategies.find((s) => s.id === r.strategy_id);
          const isProfit = (r.total_profit || 0) >= 0;
          return (
            <div
              key={r.id}
              onClick={() => onSelect?.(r)}
              className="px-5 py-3 flex items-center gap-3 hover:bg-white/[0.02] cursor-pointer transition-colors group"
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                isProfit ? "bg-emerald-500/10" : "bg-rose-500/10"
              }`}>
                {isProfit
                  ? <TrendingUp className="w-4 h-4 text-emerald-400" />
                  : <TrendingDown className="w-4 h-4 text-rose-400" />
                }
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-white truncate">
                  {strategy?.name || "Stratégie supprimée"}
                </p>
                <p className="text-[10px] text-slate-600">
                  {formatDate(r.start_date)} → {formatDate(r.end_date)} · {r.total_trades} trades
                </p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className={`text-xs font-bold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                  {isProfit ? "+" : ""}${(r.total_profit || 0).toFixed(2)}
                </p>
                <p className="text-[10px] text-slate-600">{(r.win_rate || 0).toFixed(0)}% · PF {r.profit_factor?.toFixed(2)}</p>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-amber-400 transition-colors flex-shrink-0" />
              <button
                onClick={(e) => handleDelete(r.id, e)}
                className="p-1 text-slate-600 hover:text-rose-400 transition-colors flex-shrink-0"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}