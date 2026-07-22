import React, { useMemo } from "react";
import { useAsset } from "@/lib/AssetContext";
import { TIMEFRAMES } from "@/lib/assets";
import InfoLabel from "@/components/InfoLabel";
import { Lock, Wallet } from "lucide-react";

const inputCls =
  "w-full px-3 py-2.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors";

// Strategie + actif + timeframe + parametres moteur, partages par les modes
// Live et Rejeu historique du Paper Trading. Meme logique de compatibilite
// strategie/actif que BacktestConfig.jsx (Module 3) pour rester coherent.
export default function PaperTradingConfig({ strategies, config, setConfig, disabled }) {
  const { assets } = useAsset();
  const activeAssets = assets.filter((a) => a.status === "active");

  const selectedStrategy = useMemo(
    () => strategies.find((s) => s.id === config.strategyId),
    [strategies, config.strategyId]
  );

  const availableAssets = useMemo(() => {
    if (!selectedStrategy) return activeAssets;
    if (selectedStrategy.asset_scope === "specific") {
      return activeAssets.filter((a) => selectedStrategy.asset_symbols?.includes(a.symbol));
    }
    if (selectedStrategy.asset_scope === "category") {
      return activeAssets.filter((a) => a.category === selectedStrategy.asset_category);
    }
    return activeAssets;
  }, [selectedStrategy, activeAssets]);

  const canChangeAsset = useMemo(() => {
    if (!selectedStrategy) return true;
    if (selectedStrategy.asset_scope === "specific") {
      return (selectedStrategy.asset_symbols?.length || 0) > 1;
    }
    return true;
  }, [selectedStrategy]);

  const handleStrategyChange = (strategyId) => {
    const strat = strategies.find((s) => s.id === strategyId);
    let assetSymbol = config.assetSymbol;
    let timeframe = config.timeframe;

    if (strat) {
      if (strat.asset_scope === "specific" && strat.asset_symbols?.length > 0) {
        const match = activeAssets.find((a) => strat.asset_symbols.includes(a.symbol));
        assetSymbol = match?.symbol || strat.asset_symbols[0];
      } else if (strat.asset_scope === "category") {
        const match = activeAssets.find((a) => a.category === strat.asset_category);
        assetSymbol = match?.symbol || "";
      }
      timeframe = strat.primary_timeframe || timeframe;
    }

    setConfig({ ...config, strategyId, assetSymbol, timeframe });
  };

  return (
    <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
      <div className="grid sm:grid-cols-3 gap-4 mb-4">
        <div>
          <InfoLabel label="Stratégie" tooltip="La stratégie dont les conditions d'entrée/sortie seront évaluées.">
            <select
              className={inputCls}
              value={config.strategyId}
              onChange={(e) => handleStrategyChange(e.target.value)}
              disabled={disabled}
            >
              <option value="">Sélectionner une stratégie…</option>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} {s.version ? `(v${s.version})` : ""}
                </option>
              ))}
            </select>
          </InfoLabel>
        </div>

        <div>
          <InfoLabel label="Actif" tooltip="Déterminé par la stratégie ; modifiable seulement si elle supporte plusieurs actifs.">
            <div className="relative">
              <select
                className={`${inputCls} ${!canChangeAsset ? "cursor-not-allowed opacity-80" : ""}`}
                value={config.assetSymbol}
                onChange={(e) => setConfig({ ...config, assetSymbol: e.target.value })}
                disabled={disabled || !canChangeAsset}
              >
                {config.assetSymbol && !availableAssets.find((a) => a.symbol === config.assetSymbol) && (
                  <option value={config.assetSymbol}>{config.assetSymbol}</option>
                )}
                <option value="">Sélectionner un actif…</option>
                {availableAssets.map((a) => (
                  <option key={a.id} value={a.symbol}>
                    {a.symbol} — {a.name}
                  </option>
                ))}
              </select>
              {!canChangeAsset && (
                <Lock className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600 pointer-events-none" />
              )}
            </div>
          </InfoLabel>
        </div>

        <div>
          <InfoLabel label="Timeframe" tooltip="Unité de temps des bougies utilisées pour calculer les indicateurs.">
            <select
              className={inputCls}
              value={config.timeframe}
              onChange={(e) => setConfig({ ...config, timeframe: e.target.value })}
              disabled={disabled}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </InfoLabel>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <Wallet className="w-3.5 h-3.5 text-amber-400/60" />
        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
          Paramètres du compte virtuel
        </span>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-6 gap-4">
        <div>
          <InfoLabel label="Capital ($)" tooltip="Capital de référence virtuel, utilisé pour le calcul du risque par trade.">
            <input
              type="number" step="100" className={inputCls} disabled={disabled}
              value={config.initialCapital}
              onChange={(e) => setConfig({ ...config, initialCapital: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
        <div>
          <InfoLabel label="Risque/trade (%)" tooltip="Pourcentage du capital risqué par position si la stratégie sizes en 'percent'.">
            <input
              type="number" step="0.1" min="0" className={inputCls} disabled={disabled}
              value={config.riskPerTrade}
              onChange={(e) => setConfig({ ...config, riskPerTrade: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
        <div>
          <InfoLabel label="Lot fixe" tooltip="Taille de lot utilisée si la stratégie ne calcule pas automatiquement la taille de position.">
            <input
              type="number" step="0.01" min="0.01" className={inputCls} disabled={disabled}
              value={config.lotSize}
              onChange={(e) => setConfig({ ...config, lotSize: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
        <div>
          <InfoLabel label="Levier" tooltip="Effet de levier simulé (ex: 100 = 1:100).">
            <input
              type="number" step="1" min="1" className={inputCls} disabled={disabled}
              value={config.leverage}
              onChange={(e) => setConfig({ ...config, leverage: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
        <div>
          <InfoLabel label="Spread (pips)" tooltip="Coût de spread simulé, appliqué à chaque ouverture de position virtuelle.">
            <input
              type="number" step="0.1" min="0" className={inputCls} disabled={disabled}
              value={config.spread}
              onChange={(e) => setConfig({ ...config, spread: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
        <div>
          <InfoLabel label="Slippage (pips)" tooltip="Glissement de prix simulé à l'exécution.">
            <input
              type="number" step="0.1" min="0" className={inputCls} disabled={disabled}
              value={config.slippage}
              onChange={(e) => setConfig({ ...config, slippage: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
      </div>
    </div>
  );
}
