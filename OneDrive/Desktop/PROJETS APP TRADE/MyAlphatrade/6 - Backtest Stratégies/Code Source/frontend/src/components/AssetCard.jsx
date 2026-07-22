import React from "react";
import { getAssetStyle, getAssetIcon } from "@/lib/assets";
import { TrendingDown } from "lucide-react";

export default function AssetCard({ asset, onSelect, isActive }) {
  const style = getAssetStyle(asset.color);
  const Icon = getAssetIcon(asset.icon);

  return (
    <button
      onClick={onSelect}
      className={`group relative text-left p-5 rounded-2xl border transition-all duration-300 overflow-hidden ${
        isActive
          ? `${style.bg} ${style.border} ring-1 ${style.ring}`
          : "bg-[#0d1220] border-[#1a2332] hover:border-white/10"
      }`}
    >
      <div
        className={`absolute inset-0 bg-gradient-to-br ${style.gradient} opacity-0 ${
          isActive ? "opacity-100" : "group-hover:opacity-60"
        } transition-opacity`}
      />

      <div className="relative">
        <div className="flex items-start justify-between mb-4">
          <div className={`w-10 h-10 rounded-xl ${style.bg} flex items-center justify-center`}>
            <Icon className={`w-5 h-5 ${style.text}`} />
          </div>
          <span className="text-[9px] font-medium tracking-wider uppercase px-2 py-1 rounded-full bg-white/5 text-slate-500">
            {asset.category}
          </span>
        </div>

        <div className="flex items-center gap-2 mb-1">
          <span className={`w-2 h-2 rounded-full ${style.dot}`} />
          <h3 className="font-bold text-white text-base">{asset.symbol}</h3>
        </div>
        <p className="text-xs text-slate-400 mb-3">{asset.name}</p>
        {asset.description && (
          <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">
            {asset.description}
          </p>
        )}

        <div className="flex items-center gap-3 mt-4 pt-4 border-t border-white/5">
          <div>
            <p className="text-[9px] text-slate-600 uppercase tracking-wider">Digits</p>
            <p className="text-xs text-slate-300 font-medium">{asset.digits}</p>
          </div>
          <div>
            <p className="text-[9px] text-slate-600 uppercase tracking-wider">Default TF</p>
            <p className="text-xs text-slate-300 font-medium">{asset.default_timeframe}</p>
          </div>
          {asset.broker && (
            <div>
              <p className="text-[9px] text-slate-600 uppercase tracking-wider">Broker</p>
              <p className="text-xs text-slate-300 font-medium">{asset.broker}</p>
            </div>
          )}
        </div>
      </div>
    </button>
  );
}