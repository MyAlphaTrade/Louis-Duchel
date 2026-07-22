import React from "react";
import { useAsset } from "@/lib/AssetContext";
import { getAssetStyle } from "@/lib/assets";
import { Loader2 } from "lucide-react";

export default function ModulePage({ module, title, description, features }) {
  const { selectedAsset, loading } = useAsset();
  const style = getAssetStyle(selectedAsset?.color || "amber");

  return (
    <div className="p-6 lg:p-10 max-w-5xl">
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-1">
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Module {module}
          </span>
          {selectedAsset && (
            <span
              className={`inline-flex items-center gap-1.5 text-[10px] font-medium px-2.5 py-1 rounded-full ${style.bg} ${style.text} ${style.border} border`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
              {selectedAsset.symbol}
            </span>
          )}
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          {title}
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-xl">{description}</p>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Chargement des actifs…</span>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {features.map((feature, i) => (
            <div
              key={i}
              className="group relative p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332] hover:border-amber-500/20 transition-all duration-300"
            >
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center mb-4">
                <feature.icon className="w-5 h-5 text-amber-400" />
              </div>
              <h3 className="font-semibold text-white text-sm mb-1">{feature.title}</h3>
              <p className="text-xs text-slate-500 leading-relaxed">{feature.description}</p>
              <div className="mt-4">
                <span className="inline-flex items-center gap-1.5 text-[10px] font-medium tracking-wider uppercase px-2.5 py-1 rounded-full bg-white/5 text-slate-500">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
                  Bientôt disponible
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}