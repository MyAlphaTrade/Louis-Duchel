import React from "react";
import {
  Target, Shield, TrendingUp, Clock, Layers, AlertCircle,
  CheckCircle2, XCircle, Settings2,
} from "lucide-react";

/**
 * StrategyPreview — Affiche un aperçu structuré de la stratégie générée par l'IA.
 * Montre les champs clés et le statut de validation.
 */
function PreviewSection({ icon: Icon, title, children, accent = "amber" }) {
  const accents = {
    amber: "text-amber-400/70 border-amber-500/20 bg-amber-500/5",
    emerald: "text-emerald-400/70 border-emerald-500/20 bg-emerald-500/5",
    rose: "text-rose-400/70 border-rose-500/20 bg-rose-500/5",
    blue: "text-blue-400/70 border-blue-500/20 bg-blue-500/5",
    violet: "text-violet-400/70 border-violet-500/20 bg-violet-500/5",
  };
  return (
    <div className={`rounded-xl border p-3 ${accents[accent]}`}>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon className="w-3.5 h-3.5" />
        <span className="text-[10px] font-bold uppercase tracking-wider">{title}</span>
      </div>
      <div className="text-xs text-slate-300 space-y-1">{children}</div>
    </div>
  );
}

function Tag({ children, color = "slate" }) {
  const colors = {
    slate: "bg-white/5 text-slate-400",
    amber: "bg-amber-500/10 text-amber-400",
    emerald: "bg-emerald-500/10 text-emerald-400",
    rose: "bg-rose-500/10 text-rose-400",
    blue: "bg-blue-500/10 text-blue-400",
    violet: "bg-violet-500/10 text-violet-400",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-[9px] font-medium ${colors[color]}`}>
      {children}
    </span>
  );
}

export default function StrategyPreview({ strategy, validation, isLoading }) {
  if (isLoading) {
    return (
      <div className="h-full flex flex-col items-center justify-center py-16">
        <div className="w-8 h-8 border-4 border-amber-500/20 border-t-amber-500 rounded-full animate-spin mb-3" />
        <p className="text-xs text-slate-500">Génération de la stratégie…</p>
      </div>
    );
  }

  if (!strategy) {
    return (
      <div className="h-full flex flex-col items-center justify-center py-16 px-4 text-center">
        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-amber-400/10 to-amber-600/10 flex items-center justify-center mb-3">
          <Target className="w-5 h-5 text-amber-400/50" />
        </div>
        <p className="text-sm font-medium text-slate-400 mb-1">Aperçu de la stratégie</p>
        <p className="text-xs text-slate-600 max-w-[200px]">
          Décrivez votre idée dans la conversation, puis cliquez sur « Générer la stratégie ».
        </p>
      </div>
    );
  }

  const s = strategy;
  const isComplete = validation?.isValid;

  return (
    <div className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 mb-1">
            {isComplete ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            ) : (
              <AlertCircle className="w-4 h-4 text-amber-400" />
            )}
            <h3 className="text-sm font-bold text-white">{s.name || "Stratégie sans nom"}</h3>
          </div>
          {s.description && (
            <p className="text-[11px] text-slate-500 leading-relaxed">{s.description}</p>
          )}
        </div>
      </div>

      {/* Validation badge */}
      {validation && (
        <div className={`flex items-center gap-1.5 text-[10px] px-2.5 py-1.5 rounded-lg ${
          isComplete
            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
            : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
        }`}>
          {isComplete ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
          <span>{isComplete ? "Stratégie validée" : `${validation.missingFields.length} champ(s) manquant(s)`}</span>
        </div>
      )}

      {/* Asset & Timeframe */}
      <PreviewSection icon={Layers} title="Marché & Timeframe" accent="blue">
        <div className="flex flex-wrap gap-1">
          {s.asset_scope === "all" && <Tag color="emerald">Tous les actifs</Tag>}
          {s.asset_scope === "category" && <Tag color="violet">Catégorie: {s.asset_category}</Tag>}
          {s.asset_scope === "specific" && s.asset_symbols?.map((sym) => (
            <Tag key={sym} color="amber">{sym}</Tag>
          ))}
          <Tag color="blue">TF: {s.primary_timeframe}</Tag>
          {s.secondary_timeframes?.map((tf) => (
            <Tag key={tf} color="slate">+{tf}</Tag>
          ))}
        </div>
      </PreviewSection>

      {/* Entry conditions */}
      <PreviewSection icon={TrendingUp} title="Conditions d'entrée" accent="emerald">
        <div className="flex items-center gap-2">
          <Tag color="emerald">BUY: {s.entry_conditions?.buy?.length || 0}</Tag>
          <Tag color="rose">SELL: {s.entry_conditions?.sell?.length || 0}</Tag>
        </div>
      </PreviewSection>

      {/* Exit conditions */}
      <div className="grid grid-cols-2 gap-2">
        <PreviewSection icon={Shield} title="Stop Loss" accent="rose">
          <p className="font-mono">
            {s.exit_conditions?.stop_loss?.value > 0
              ? `${s.exit_conditions.stop_loss.value} ${s.exit_conditions.stop_loss.type}`
              : "—"}
          </p>
        </PreviewSection>
        <PreviewSection icon={Target} title="Take Profit" accent="emerald">
          <p className="font-mono">
            {s.exit_conditions?.take_profit?.value > 0
              ? `${s.exit_conditions.take_profit.value} ${s.exit_conditions.take_profit.type}`
              : "—"}
          </p>
        </PreviewSection>
      </div>

      {/* Risk management */}
      <PreviewSection icon={Settings2} title="Gestion du risque" accent="violet">
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          <span>Risque: <strong className="text-slate-200">{s.risk_management?.risk_value}%</strong></span>
          <span>Min R/R: <strong className="text-slate-200">{s.risk_management?.min_rr}</strong></span>
          <span>Max positions: <strong className="text-slate-200">{s.risk_management?.max_positions}</strong></span>
          <span>Max DD: <strong className="text-slate-200">{s.risk_management?.max_drawdown}%</strong></span>
        </div>
      </PreviewSection>

      {/* Indicators & Filters */}
      {(s.indicators?.length > 0 || s.filters?.length > 0) && (
        <PreviewSection icon={Clock} title="Indicateurs & Filtres" accent="amber">
          <div className="flex flex-wrap gap-1">
            {s.indicators?.map((ind, i) => (
              <Tag key={i} color="amber">{ind}</Tag>
            ))}
            {s.filters?.map((f, i) => (
              <Tag key={`f${i}`} color="slate">{f}</Tag>
            ))}
          </div>
        </PreviewSection>
      )}
    </div>
  );
}