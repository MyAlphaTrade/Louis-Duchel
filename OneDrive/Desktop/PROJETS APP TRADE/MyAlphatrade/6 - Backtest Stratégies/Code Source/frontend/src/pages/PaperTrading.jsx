import React, { useEffect, useMemo, useState } from "react";
import { base44 } from "@/api/base44Client";
import { useAsset } from "@/lib/AssetContext";
import PaperTradingConfig from "@/components/paperTrading/PaperTradingConfig";
import LivePanel from "@/components/paperTrading/LivePanel";
import ReplayPanel from "@/components/paperTrading/ReplayPanel";
import { Wallet, Radio, Film, ShieldCheck } from "lucide-react";

export default function PaperTrading() {
  const { assets } = useAsset();
  const [mode, setMode] = useState("live");
  const [strategies, setStrategies] = useState([]);
  const [config, setConfig] = useState({
    strategyId: "",
    assetSymbol: "",
    timeframe: "M15",
    initialCapital: 10000,
    riskPerTrade: 1,
    lotSize: 0.1,
    leverage: 100,
    spread: 0,
    commission: 0,
    slippage: 0,
  });

  useEffect(() => {
    base44.entities.Strategy.list("-created_date", 500)
      .then((data) => setStrategies(data.filter((s) => s.status !== "archived")))
      .catch(() => {});
  }, []);

  const strategy = useMemo(
    () => strategies.find((s) => s.id === config.strategyId) || null,
    [strategies, config.strategyId]
  );
  const asset = useMemo(
    () => assets.find((a) => a.symbol === config.assetSymbol) || null,
    [assets, config.assetSymbol]
  );

  return (
    <div className="p-6 lg:p-10 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Wallet className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Module 4
          </span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Paper Trading
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-2xl">
          Testez vos stratégies en positions 100% virtuelles — aucun ordre réel n'est jamais envoyé, aucun capital
          n'est jamais risqué.
        </p>
        <div className="mt-3 flex items-center gap-2 text-[11px] text-emerald-400/80">
          <ShieldCheck className="w-3.5 h-3.5" />
          Positions purement virtuelles, sans connexion à un compte de trading réel.
        </div>
      </div>

      {/* Mode tabs */}
      <div className="flex items-center gap-2 mb-6">
        <button
          onClick={() => setMode("live")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border text-sm font-medium transition-colors ${
            mode === "live"
              ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
              : "bg-[#0d1220] border-[#1a2332] text-slate-400 hover:text-slate-200"
          }`}
        >
          <Radio className="w-4 h-4" />
          Live
        </button>
        <button
          onClick={() => setMode("replay")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border text-sm font-medium transition-colors ${
            mode === "replay"
              ? "bg-violet-500/10 border-violet-500/30 text-violet-400"
              : "bg-[#0d1220] border-[#1a2332] text-slate-400 hover:text-slate-200"
          }`}
        >
          <Film className="w-4 h-4" />
          Rejeu historique
        </button>
      </div>

      {/* Shared config */}
      <div className="mb-6">
        <PaperTradingConfig strategies={strategies} config={config} setConfig={setConfig} />
      </div>

      {mode === "live" ? (
        <LivePanel strategy={strategy} asset={asset} config={config} />
      ) : (
        <ReplayPanel strategy={strategy} asset={asset} config={config} />
      )}
    </div>
  );
}
