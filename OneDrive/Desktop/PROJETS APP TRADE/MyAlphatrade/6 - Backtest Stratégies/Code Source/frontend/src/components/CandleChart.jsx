import React, { useEffect, useMemo, useState } from "react";
import { ResponsiveContainer, ComposedChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell } from "recharts";
import { base44 } from "@/api/base44Client";
import { TIMEFRAMES } from "@/lib/assets";
import { CandlestickChart, Loader2 } from "lucide-react";

const MAX_CANDLES = 250;
const UP_COLOR = "#34d399";
const DOWN_COLOR = "#f43f5e";

function formatTick(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// Recharts n'a pas de type "chandelier" natif -- on le compose avec deux
// Bar en "range" (dataKey retournant [min, max], supporté nativement par
// Recharts pour dessiner une barre flottante entre deux valeurs) : une
// meche fine (low -> high) et un corps plus large (open/close), colore par
// bougie via <Cell>.
export default function CandleChart({ symbol, timeframe: initialTimeframe }) {
  const [timeframe, setTimeframe] = useState(initialTimeframe || "M15");
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (initialTimeframe) setTimeframe(initialTimeframe);
  }, [initialTimeframe, symbol]);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    base44.marketData
      .list(symbol, timeframe, MAX_CANDLES)
      .then((data) => {
        if (cancelled) return;
        const arr = Array.isArray(data) ? data : [];
        setCandles(arr.length > MAX_CANDLES ? arr.slice(arr.length - MAX_CANDLES) : arr);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Erreur de chargement des bougies.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, timeframe]);

  const data = useMemo(
    () =>
      candles.map((c, i) => ({
        index: i,
        time: c.timestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        wick: [c.low, c.high],
        body: [Math.min(c.open, c.close), Math.max(c.open, c.close)],
        up: c.close >= c.open,
      })),
    [candles]
  );

  return (
    <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center flex-shrink-0">
            <CandlestickChart className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h4 className="font-semibold text-white text-sm">Bougies — {symbol || "—"}</h4>
            <p className="text-[11px] text-slate-500">Dernières {MAX_CANDLES} bougies importées, par timeframe.</p>
          </div>
        </div>
        <select
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          className="px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors"
        >
          {TIMEFRAMES.map((tf) => (
            <option key={tf} value={tf}>{tf}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-xs">Chargement…</span>
        </div>
      ) : error ? (
        <p className="text-xs text-rose-400 py-8 text-center">{error}</p>
      ) : data.length === 0 ? (
        <p className="text-xs text-slate-500 py-12 text-center">
          Aucune bougie importée pour {symbol} en {timeframe} — importez un historique depuis la carte ci-dessus.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a2332" />
            <XAxis
              dataKey="time"
              tickFormatter={formatTick}
              tick={{ fill: "#475569", fontSize: 10 }}
              stroke="#1a2332"
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#475569", fontSize: 10 }}
              stroke="#1a2332"
              width={65}
              tickFormatter={(v) => v.toFixed(2)}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#0a0e17", border: "1px solid #1a2332", borderRadius: "8px", fontSize: "12px" }}
              labelStyle={{ color: "#64748b" }}
              labelFormatter={(v) => new Date(v).toLocaleString("fr-FR")}
              formatter={(value, name, props) => {
                const p = props.payload;
                if (name === "wick") return [`H ${p.high.toFixed(2)} / L ${p.low.toFixed(2)}`, "Mèche"];
                if (name === "body") return [`O ${p.open.toFixed(2)} / C ${p.close.toFixed(2)}`, "Corps"];
                return [value, name];
              }}
            />
            <Bar dataKey="wick" barSize={1.5} isAnimationActive={false}>
              {data.map((d, i) => (
                <Cell key={`wick-${i}`} fill={d.up ? UP_COLOR : DOWN_COLOR} />
              ))}
            </Bar>
            <Bar dataKey="body" barSize={6} isAnimationActive={false}>
              {data.map((d, i) => (
                <Cell key={`body-${i}`} fill={d.up ? UP_COLOR : DOWN_COLOR} />
              ))}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
