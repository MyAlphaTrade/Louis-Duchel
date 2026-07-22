import React, { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, Download, Filter, ArrowUpDown } from "lucide-react";

const REASON_STYLES = {
  TP: { bg: "bg-emerald-500/10", text: "text-emerald-400", label: "TP" },
  SL: { bg: "bg-rose-500/10", text: "text-rose-400", label: "SL" },
  SIGNAL: { bg: "bg-violet-500/10", text: "text-violet-400", label: "SIGNAL" },
  TIME: { bg: "bg-amber-500/10", text: "text-amber-400", label: "TIME" },
  EOD: { bg: "bg-slate-500/10", text: "text-slate-400", label: "EOD" },
};

function formatDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function formatDuration(minutes) {
  if (!minutes) return "—";
  if (minutes < 60) return `${Math.round(minutes)}min`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h${m > 0 ? m : ""}`;
}

function exportCSV(trades) {
  const headers = ["#", "Direction", "Entry Time", "Exit Time", "Entry Price", "Exit Price", "Volume", "Stop Loss", "Take Profit", "Close Reason", "Duration (bars)", "Duration (min)", "P&L", "Equity After"];
  const rows = trades.map((t, i) => [
    i + 1, t.direction,
    t.entry_time ? new Date(t.entry_time).toISOString() : "",
    t.exit_time ? new Date(t.exit_time).toISOString() : "",
    t.entry_price, t.exit_price, t.volume, t.stop_loss, t.take_profit,
    t.close_reason, t.duration_bars, t.duration_minutes,
    t.profit, t.equity_after,
  ]);
  const csv = [headers, ...rows]
    .map((row) => row.map((cell) => `"${cell ?? ""}"`).join(","))
    .join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `backtest_trades_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function TradeRow({ trade, index }) {
  const [expanded, setExpanded] = useState(false);
  const isBuy = trade.direction === "BUY";
  const isWin = trade.profit > 0;
  const reason = REASON_STYLES[trade.close_reason] || REASON_STYLES.EOD;
  const rMultiple = trade.stop_loss && trade.entry_price
    ? Math.abs(trade.profit / Math.abs(trade.entry_price - trade.stop_loss) / (trade.volume || 1))
    : null;

  return (
    <>
      <tr
        className="border-b border-[#1a2332] last:border-0 hover:bg-white/[0.02] cursor-pointer transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="px-3 py-2.5">
          <span className="text-xs text-slate-500">#{index + 1}</span>
        </td>
        <td className="px-3 py-2.5">
          <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full ${
            isBuy ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
          }`}>
            {isBuy ? "BUY" : "SELL"}
          </span>
        </td>
        <td className="px-3 py-2.5 hidden sm:table-cell">
          <span className="text-xs text-slate-400">{formatDate(trade.entry_time)}</span>
        </td>
        <td className="px-3 py-2.5 hidden md:table-cell">
          <span className="text-xs text-slate-400 font-mono">{trade.entry_price?.toFixed(4)}</span>
        </td>
        <td className="px-3 py-2.5 hidden md:table-cell">
          <span className="text-xs text-slate-400 font-mono">{trade.exit_price?.toFixed(4)}</span>
        </td>
        <td className="px-3 py-2.5 hidden lg:table-cell">
          <span className="text-xs text-slate-500 font-mono">{trade.volume?.toFixed(2)}</span>
        </td>
        <td className="px-3 py-2.5">
          <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full ${reason.bg} ${reason.text}`}>
            {reason.label}
          </span>
        </td>
        <td className="px-3 py-2.5 text-right">
          <span className={`text-xs font-bold ${isWin ? "text-emerald-400" : "text-rose-400"}`}>
            {isWin ? "+" : ""}${trade.profit?.toFixed(2)}
          </span>
        </td>
        <td className="px-3 py-2.5 text-right hidden lg:table-cell">
          <span className="text-xs text-slate-500 font-mono">${trade.equity_after?.toFixed(2)}</span>
        </td>
        <td className="px-3 py-2.5 text-center">
          {expanded ? <ChevronDown className="w-3 h-3 text-slate-600 mx-auto" /> : <ChevronRight className="w-3 h-3 text-slate-600 mx-auto" />}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-[#0a0e17]">
          <td colSpan={10} className="px-6 py-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 text-xs">
              <div>
                <span className="text-slate-600 block text-[9px] uppercase tracking-wider mb-0.5">Volume</span>
                <span className="text-slate-300 font-mono">{trade.volume?.toFixed(2)} lots</span>
              </div>
              <div>
                <span className="text-slate-600 block text-[9px] uppercase tracking-wider mb-0.5">Stop Loss</span>
                <span className="text-rose-400 font-mono">{trade.stop_loss?.toFixed(4)}</span>
              </div>
              <div>
                <span className="text-slate-600 block text-[9px] uppercase tracking-wider mb-0.5">Take Profit</span>
                <span className="text-emerald-400 font-mono">{trade.take_profit?.toFixed(4)}</span>
              </div>
              <div>
                <span className="text-slate-600 block text-[9px] uppercase tracking-wider mb-0.5">Durée</span>
                <span className="text-slate-300">{formatDuration(trade.duration_minutes)} ({trade.duration_bars} bars)</span>
              </div>
              <div>
                <span className="text-slate-600 block text-[9px] uppercase tracking-wider mb-0.5">Sortie</span>
                <span className="text-slate-300">{formatDate(trade.exit_time)}</span>
              </div>
              <div>
                <span className="text-slate-600 block text-[9px] uppercase tracking-wider mb-0.5">Multiple R</span>
                <span className={`font-mono ${rMultiple >= 1 ? "text-emerald-400" : "text-rose-400"}`}>
                  {rMultiple ? `${rMultiple.toFixed(2)}R` : "—"}
                </span>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function TradeJournal({ trades }) {
  const [dirFilter, setDirFilter] = useState("");
  const [resultFilter, setResultFilter] = useState("");
  const [reasonFilter, setReasonFilter] = useState("");
  const [sortBy, setSortBy] = useState("index");
  const [sortAsc, setSortAsc] = useState(true);

  const filtered = useMemo(() => {
    let result = [...trades];
    if (dirFilter) result = result.filter((t) => t.direction === dirFilter);
    if (resultFilter === "win") result = result.filter((t) => t.profit > 0);
    if (resultFilter === "loss") result = result.filter((t) => t.profit <= 0);
    if (reasonFilter) result = result.filter((t) => t.close_reason === reasonFilter);

    if (sortBy === "profit") result.sort((a, b) => b.profit - a.profit);
    else if (sortBy === "date") result.sort((a, b) => new Date(a.entry_time) - new Date(b.entry_time));
    else if (sortBy === "duration") result.sort((a, b) => (b.duration_minutes || 0) - (a.duration_minutes || 0));

    if (!sortAsc && sortBy !== "index") result.reverse();
    return result;
  }, [trades, dirFilter, resultFilter, reasonFilter, sortBy, sortAsc]);

  const reasons = [...new Set(trades.map((t) => t.close_reason).filter(Boolean))];

  const toggleSort = (field) => {
    if (sortBy === field) setSortAsc(!sortAsc);
    else { setSortBy(field); setSortAsc(true); }
  };

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1a2332]">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h3 className="text-sm font-bold text-white">Journal des opérations</h3>
            <p className="text-[10px] text-slate-600 mt-0.5">
              {filtered.length} / {trades.length} trade{trades.length !== 1 ? "s" : ""}
            </p>
          </div>
          <button
            onClick={() => exportCSV(trades)}
            className="flex items-center gap-1.5 text-[10px] font-medium px-3 py-1.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-400 hover:text-amber-400 hover:border-amber-500/20 transition-colors"
          >
            <Download className="w-3 h-3" />
            Export CSV
          </button>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-2 mt-3 flex-wrap">
          <Filter className="w-3 h-3 text-slate-600" />
          <select
            value={dirFilter}
            onChange={(e) => setDirFilter(e.target.value)}
            className="px-2.5 py-1 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-400 text-[10px] focus:outline-none focus:border-amber-500/30 cursor-pointer"
          >
            <option value="">Toutes directions</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
          <select
            value={resultFilter}
            onChange={(e) => setResultFilter(e.target.value)}
            className="px-2.5 py-1 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-400 text-[10px] focus:outline-none focus:border-amber-500/30 cursor-pointer"
          >
            <option value="">Gains + pertes</option>
            <option value="win">Gagnants</option>
            <option value="loss">Perdants</option>
          </select>
          <select
            value={reasonFilter}
            onChange={(e) => setReasonFilter(e.target.value)}
            className="px-2.5 py-1 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-400 text-[10px] focus:outline-none focus:border-amber-500/30 cursor-pointer"
          >
            <option value="">Tous motifs</option>
            {reasons.map((r) => (
              <option key={r} value={r}>{REASON_STYLES[r]?.label || r}</option>
            ))}
          </select>
          <div className="flex items-center gap-1 ml-auto">
            <ArrowUpDown className="w-3 h-3 text-slate-600" />
            {["index", "profit", "date", "duration"].map((field) => (
              <button
                key={field}
                onClick={() => toggleSort(field)}
                className={`text-[10px] px-2 py-1 rounded-lg transition-colors ${
                  sortBy === field
                    ? "bg-amber-500/10 text-amber-400"
                    : "text-slate-600 hover:text-slate-400"
                }`}
              >
                {field === "index" ? "#" : field === "profit" ? "P&L" : field === "date" ? "Date" : "Durée"}
                {sortBy === field && (sortAsc ? " ↑" : " ↓")}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-[#0d1220] z-10">
            <tr className="border-b border-[#1a2332]">
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">#</th>
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Dir</th>
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden sm:table-cell">Entrée</th>
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden md:table-cell">Px entrée</th>
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden md:table-cell">Px sortie</th>
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden lg:table-cell">Lots</th>
              <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Motif</th>
              <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">P&L</th>
              <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden lg:table-cell">Capital</th>
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((trade, i) => (
              <TradeRow key={i} trade={trade} index={trades.indexOf(trade)} />
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="py-8 text-center">
            <p className="text-xs text-slate-600">Aucun trade ne correspond aux filtres.</p>
          </div>
        )}
      </div>
    </div>
  );
}