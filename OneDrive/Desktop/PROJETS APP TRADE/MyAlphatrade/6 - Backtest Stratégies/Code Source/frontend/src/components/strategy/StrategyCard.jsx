import React from "react";
import { useAsset } from "@/lib/AssetContext";
import { getAssetStyle, getAssetIcon } from "@/lib/assets";
import {
  MARKET_TYPES,
  VOLATILITY_LEVELS,
  TRADING_SESSIONS,
} from "@/lib/indicators";
import {
  Clock,
  Shield,
  TrendingUp,
  TrendingDown,
  Layers,
  Activity,
  Globe,
  GitBranch,
  Copy,
  Trash2,
} from "lucide-react";

const STATUS_STYLES = {
  draft: { bg: "bg-slate-500/10", text: "text-slate-400", dot: "bg-slate-500", label: "Brouillon" },
  tested: { bg: "bg-blue-500/10", text: "text-blue-400", dot: "bg-blue-400", label: "Testée" },
  active: { bg: "bg-emerald-500/10", text: "text-emerald-400", dot: "bg-emerald-400", label: "Active" },
  archived: { bg: "bg-amber-500/10", text: "text-amber-400", dot: "bg-amber-400", label: "Archivée" },
};

function MiniBadge({ icon: Icon, label, color = "text-slate-400" }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-500">
      <Icon className={`w-3 h-3 ${color}`} />
      {label}
    </span>
  );
}

export default function StrategyCard({ strategy, onClick, onNewVersion, onDelete, parentStrategy }) {
  const { assets } = useAsset();
  const status = STATUS_STYLES[strategy.status] || STATUS_STYLES.draft;

  // Resolve assets to display
  let assetDisplay = [];
  if (strategy.asset_scope === "all") {
    assetDisplay = [{ symbol: "Tous", color: "amber", icon: "Globe" }];
  } else if (strategy.asset_scope === "category") {
    assetDisplay = [{ symbol: strategy.asset_category, color: "violet", icon: "Layers" }];
  } else {
    assetDisplay = (strategy.asset_symbols || [])
      .map((sym) => assets.find((a) => a.symbol === sym))
      .filter(Boolean);
  }

  const buyCount = strategy.entry_conditions?.buy?.filter((c) => c.enabled !== false).length || 0;
  const sellCount = strategy.entry_conditions?.sell?.filter((c) => c.enabled !== false).length || 0;
  const sessions = (strategy.market_profile?.sessions || [])
    .map((s) => TRADING_SESSIONS.find((ts) => ts.id === s))
    .filter(Boolean);
  const marketType = MARKET_TYPES.find((m) => m.id === strategy.market_profile?.market_type);
  const volatility = VOLATILITY_LEVELS.find((v) => v.id === strategy.market_profile?.volatility);
  const risk = strategy.risk_management || {};

  const riskLabel = risk.type === "percent"
    ? `${risk.risk_value || 1}%`
    : risk.type === "lots"
    ? `${risk.risk_value || 0.01} lots`
    : `${risk.risk_value || 0}`;

  return (
    <button
      onClick={onClick}
      className="group text-left p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332] hover:border-amber-500/20 transition-all duration-300 w-full"
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className={`inline-flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-full ${status.bg} ${status.text}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`} />
          {status.label}
        </span>
        {strategy.version && (
          <span className="inline-flex items-center gap-1 text-[10px] font-mono text-slate-600 px-2 py-1 rounded-full bg-white/5">
            <GitBranch className="w-2.5 h-2.5" />
            v{strategy.version}
          </span>
        )}
        {parentStrategy && (
          <span className="text-[10px] text-slate-600 px-2 py-1 rounded-full bg-white/5">
            ← v{parentStrategy.version}
          </span>
        )}
      </div>

      {/* Name + description */}
      <h3 className="font-bold text-white text-base mb-1 group-hover:text-amber-400 transition-colors">
        {strategy.name}
      </h3>
      {strategy.description && (
        <p className="text-xs text-slate-500 leading-relaxed line-clamp-2 mb-4">
          {strategy.description}
        </p>
      )}

      {/* Assets */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {assetDisplay.map((asset, i) => {
          const style = getAssetStyle(asset.color || "amber");
          const Icon = getAssetIcon(asset.icon || "TrendingUp");
          return (
            <span
              key={i}
              className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-full ${style.bg} ${style.text} ${style.border} border`}
            >
              <Icon className="w-3 h-3" />
              {asset.symbol}
            </span>
          );
        })}
      </div>

      {/* Timeframes + market profile */}
      <div className="flex flex-wrap items-center gap-3 mb-4 pb-4 border-b border-[#1a2332]">
        <MiniBadge icon={Clock} label={strategy.primary_timeframe} color="text-amber-400" />
        {strategy.secondary_timeframes?.length > 0 && (
          <MiniBadge icon={Clock} label={`+${strategy.secondary_timeframes.join(", ")}`} />
        )}
        {marketType && <MiniBadge icon={Layers} label={marketType.label} />}
        {volatility && <MiniBadge icon={Activity} label={`Vol: ${volatility.label}`} />}
      </div>

      {/* Sessions */}
      {sessions.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-4">
          {sessions.map((s) => (
            <span key={s.id} className="text-[10px] text-slate-500 px-2 py-0.5 rounded bg-white/5">
              {s.label}
            </span>
          ))}
        </div>
      )}

      {/* Conditions + Risk */}
      <div className="flex items-center justify-between text-[10px]">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1 text-emerald-400">
            <TrendingUp className="w-3 h-3" />
            {buyCount} BUY
          </span>
          <span className="inline-flex items-center gap-1 text-rose-400">
            <TrendingDown className="w-3 h-3" />
            {sellCount} SELL
          </span>
        </div>
        <div className="flex items-center gap-2 text-slate-500">
          <Shield className="w-3 h-3" />
          <span>{riskLabel}</span>
          {risk.min_rr && (
            <>
              <span className="text-slate-600">|</span>
              <span>RR {risk.min_rr}</span>
            </>
          )}
        </div>
      </div>

      {/* Actions */}
      {onNewVersion && (
        <div
          className="mt-4 pt-3 border-t border-[#1a2332] flex items-center justify-between"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={(e) => {
              e.stopPropagation();
              onNewVersion(strategy);
            }}
            className="flex items-center gap-1.5 text-[10px] font-medium text-slate-500 hover:text-amber-400 transition-colors"
          >
            <Copy className="w-3 h-3" />
            Nouvelle version
          </button>
          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(strategy);
              }}
              className="flex items-center gap-1.5 text-[10px] font-medium text-slate-600 hover:text-rose-400 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              Supprimer
            </button>
          )}
        </div>
      )}
    </button>
  );
}