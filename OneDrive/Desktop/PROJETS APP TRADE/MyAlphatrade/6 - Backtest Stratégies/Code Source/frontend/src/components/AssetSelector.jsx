import React, { useState, useRef, useEffect } from "react";
import { useAsset } from "@/lib/AssetContext";
import { getAssetStyle, getAssetIcon } from "@/lib/assets";
import { ChevronDown, Check, Loader2 } from "lucide-react";

export default function AssetSelector({ compact = false }) {
  const { activeAssets, selectedAsset, setSelectedSymbol, loading } = useAsset();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const style = getAssetStyle(selectedAsset?.color || "amber");
  const SelectedIcon = getAssetIcon(selectedAsset?.icon || "TrendingUp");

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332]">
        <Loader2 className="w-4 h-4 text-slate-500 animate-spin" />
        <span className="text-sm text-slate-500">Chargement…</span>
      </div>
    );
  }

  if (!selectedAsset) {
    return (
      <div className="px-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332]">
        <span className="text-sm text-slate-500">Aucun actif</span>
      </div>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2.5 ${compact ? "px-3 py-2" : "px-4 py-2.5"} w-full rounded-xl ${style.bg} ${style.border} border hover:brightness-125 transition-all`}
      >
        <SelectedIcon className={`w-4 h-4 ${style.text} flex-shrink-0`} />
        <div className="flex-1 text-left min-w-0">
          <p className={`text-sm font-semibold ${style.text} leading-tight truncate`}>
            {selectedAsset.symbol}
          </p>
          {!compact && (
            <p className="text-[10px] text-slate-500 leading-tight truncate">
              {selectedAsset.name}
            </p>
          )}
        </div>
        <ChevronDown
          className={`w-4 h-4 ${style.text} flex-shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-[#0d1220] border border-[#1a2332] rounded-xl shadow-2xl shadow-black/50 z-50 overflow-hidden max-h-80 overflow-y-auto">
          {activeAssets.length === 0 ? (
            <p className="px-4 py-3 text-sm text-slate-500">Aucun actif actif</p>
          ) : (
            activeAssets.map((asset) => {
              const s = getAssetStyle(asset.color);
              const Icon = getAssetIcon(asset.icon);
              const isActive = asset.symbol === selectedAsset.symbol;
              return (
                <button
                  key={asset.id}
                  onClick={() => {
                    setSelectedSymbol(asset.symbol);
                    setOpen(false);
                  }}
                  className={`flex items-center gap-3 px-4 py-3 w-full text-left transition-colors ${
                    isActive ? "bg-white/5" : "hover:bg-white/5"
                  }`}
                >
                  <Icon className={`w-4 h-4 ${s.text} flex-shrink-0`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white leading-tight truncate">
                      {asset.symbol}
                    </p>
                    <p className="text-[10px] text-slate-500 leading-tight truncate">
                      {asset.name}
                    </p>
                  </div>
                  <span className="text-[10px] text-slate-600 px-2 py-0.5 rounded-full bg-white/5 flex-shrink-0">
                    {asset.category}
                  </span>
                  {isActive && <Check className={`w-3.5 h-3.5 ${s.text} flex-shrink-0`} />}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}