import React, { useState, useMemo } from "react";
import {
  ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, Brush,
} from "recharts";
import { ZoomIn, Activity, TrendingDown } from "lucide-react";

function formatDuration(minutes) {
  if (!minutes) return "—";
  if (minutes < 60) return `${Math.round(minutes)}min`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h${m > 0 ? m : ""}`;
}

// Recharts (SVG) rend chaque point comme un noeud du chemin -- au-dela de
// quelques milliers de points, le calcul de la geometrie peut geler l'onglet
// (constate en pratique sur un an de bougies M15, ~23 500 points). La courbe
// reste visuellement identique bien en dessous de cette resolution, donc on
// sous-echantillonne par pas fixe plutot que de tout tracer -- le dernier
// point est toujours garde pour ne pas tronquer le solde final affiche.
const MAX_CHART_POINTS = 1200;
function downsample(points, maxPoints) {
  if (points.length <= maxPoints) return points;
  const stride = Math.ceil(points.length / maxPoints);
  const sampled = points.filter((_, i) => i % stride === 0);
  const last = points[points.length - 1];
  if (sampled[sampled.length - 1] !== last) sampled.push(last);
  return sampled;
}

export default function EquityCurve({ equityCurve, initialCapital }) {
  const [showDrawdown, setShowDrawdown] = useState(false);

  const data = useMemo(() =>
    downsample(equityCurve, MAX_CHART_POINTS).map((p) => ({
      bar: p.bar,
      equity: p.equity,
      balance: p.balance,
      drawdown: p.drawdown || 0,
      time: p.timestamp,
    })),
  [equityCurve]);

  const minEquity = data.reduce((m, d) => Math.min(m, d.equity), initialCapital);
  const maxEquity = data.reduce((m, d) => Math.max(m, d.equity), initialCapital);
  const padding = (maxEquity - minEquity) * 0.1 || 100;

  const maxDrawdown = data.reduce((m, d) => Math.max(m, d.drawdown), 0);
  const finalEquity = data.length > 0 ? data[data.length - 1].equity : initialCapital;
  const isProfit = finalEquity >= initialCapital;
  const lineColor = isProfit ? "#34d399" : "#f43f5e";
  const gradientId = isProfit ? "equityGradientProfit" : "equityGradientLoss";

  const visibleStart = data[0]?.bar || 0;
  const visibleEnd = data[data.length - 1]?.bar || 0;
  const barCount = Math.min(data.length, Math.max(50, Math.floor(data.length / 3)));

  return (
    <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-white">Courbe de capital</h3>
          <span className="text-[10px] text-slate-600 uppercase tracking-wider">
            {equityCurve.length} bars{data.length < equityCurve.length ? ` (${data.length} affichées)` : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowDrawdown(!showDrawdown)}
            className={`flex items-center gap-1.5 text-[10px] font-medium px-2.5 py-1 rounded-lg border transition-colors ${
              showDrawdown
                ? "bg-rose-500/10 border-rose-500/20 text-rose-400"
                : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-slate-300"
            }`}
          >
            <TrendingDown className="w-3 h-3" />
            Drawdown
          </button>
          <span className="text-[10px] text-slate-600 flex items-center gap-1">
            <Activity className="w-3 h-3" />
            DD max: {maxDrawdown.toFixed(1)}%
          </span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 5, right: 5, bottom: showDrawdown ? 5 : 5, left: 0 }}>
          <defs>
            <linearGradient id="equityGradientProfit" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity={0.35} />
              <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="equityGradientLoss" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity={0.35} />
              <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a2332" />
          <XAxis
            dataKey="bar"
            tick={{ fill: "#475569", fontSize: 10 }}
            stroke="#1a2332"
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="equity"
            domain={[minEquity - padding, maxEquity + padding]}
            tick={{ fill: "#475569", fontSize: 10 }}
            stroke="#1a2332"
            tickFormatter={(v) => `$${v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(0)}`}
            width={60}
          />
          {showDrawdown && (
            <YAxis
              yAxisId="drawdown"
              orientation="right"
              domain={[maxDrawdown + 1, 0]}
              tick={{ fill: "#475569", fontSize: 10 }}
              stroke="#1a2332"
              tickFormatter={(v) => `${v.toFixed(0)}%`}
              width={40}
            />
          )}
          <Tooltip
            contentStyle={{
              backgroundColor: "#0a0e17",
              border: "1px solid #1a2332",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            labelStyle={{ color: "#64748b" }}
            labelFormatter={(v) => {
              const pt = data.find((d) => d.bar === v);
              return pt?.time
                ? new Date(pt.time).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
                : `Bar ${v}`;
            }}
            formatter={(value, name) => {
              if (name === "equity") return [`$${value.toLocaleString()}`, "Capital"];
              if (name === "balance") return [`$${value.toLocaleString()}`, "Solde réalisé"];
              if (name === "drawdown") return [`${value.toFixed(2)}%`, "Drawdown"];
              return [value, name];
            }}
          />
          <ReferenceLine yAxisId="equity" y={initialCapital} stroke="#334155" strokeDasharray="5 5" />
          <Area
            yAxisId="equity"
            type="monotone"
            dataKey="equity"
            stroke={lineColor}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
          />
          <Line
            yAxisId="equity"
            type="monotone"
            dataKey="balance"
            stroke="#64748b"
            strokeWidth={1}
            strokeDasharray="4 4"
            dot={false}
          />
          {showDrawdown && (
            <Area
              yAxisId="drawdown"
              type="monotone"
              dataKey="drawdown"
              stroke="#f43f5e"
              strokeWidth={1}
              fill="url(#drawdownGradient)"
            />
          )}
          <Brush
            dataKey="bar"
            height={showDrawdown ? 25 : 0}
            stroke="#f59e0b"
            fill="#0a0e17"
            travellerWidth={8}
            startIndex={visibleStart}
            endIndex={visibleEnd}
            tickFormatter={() => ""}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="flex items-center gap-4 mt-3 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ backgroundColor: lineColor }} />
          <span className="text-[10px] text-slate-500">Equity (réalisé + non réalisé)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded bg-slate-500" style={{ borderTop: "1px dashed #64748b" }} />
          <span className="text-[10px] text-slate-500">Solde réalisé</span>
        </div>
        {showDrawdown && (
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-2 rounded-sm bg-rose-500/30" />
            <span className="text-[10px] text-slate-500">Drawdown</span>
          </div>
        )}
        <div className="ml-auto flex items-center gap-1 text-[10px] text-slate-600">
          <ZoomIn className="w-3 h-3" />
          Glissez le curseur pour zoomer
        </div>
      </div>
    </div>
  );
}