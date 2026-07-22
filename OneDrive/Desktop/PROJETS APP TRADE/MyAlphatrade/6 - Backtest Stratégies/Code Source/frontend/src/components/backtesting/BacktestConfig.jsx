import React, { useMemo } from "react";
import { useAsset } from "@/lib/AssetContext";
import { TIMEFRAMES } from "@/lib/assets";
import InfoLabel from "@/components/InfoLabel";
import { Play, Loader2, Calendar, Clock, FlaskConical, Lock } from "lucide-react";

const inputCls =
  "w-full px-3 py-2.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors";

export default function BacktestConfig({ strategies, config, setConfig, onRun, running }) {
  const { assets } = useAsset();
  const activeAssets = assets.filter((a) => a.status === "active");

  const selectedStrategy = useMemo(
    () => strategies.find((s) => s.id === config.strategyId),
    [strategies, config.strategyId]
  );

  // Determine which assets are compatible with the selected strategy
  const availableAssets = useMemo(() => {
    if (!selectedStrategy) return activeAssets;
    if (selectedStrategy.asset_scope === "specific") {
      return activeAssets.filter((a) => selectedStrategy.asset_symbols?.includes(a.symbol));
    }
    if (selectedStrategy.asset_scope === "category") {
      return activeAssets.filter((a) => a.category === selectedStrategy.asset_category);
    }
    return activeAssets; // "all"
  }, [selectedStrategy, activeAssets]);

  // Can the user freely change the asset?
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

    if (strat) {
      if (strat.asset_scope === "specific" && strat.asset_symbols?.length > 0) {
        // Auto-select first compatible active asset
        const match = activeAssets.find((a) => strat.asset_symbols.includes(a.symbol));
        assetSymbol = match?.symbol || strat.asset_symbols[0];
      } else if (strat.asset_scope === "category") {
        const match = activeAssets.find((a) => a.category === strat.asset_category);
        assetSymbol = match?.symbol || "";
      }
      // If "all", keep current selection
    }

    setConfig({ ...config, strategyId, assetSymbol });
  };

  // Summary of period in days
  const periodDays = useMemo(() => {
    if (!config.startDate || !config.endDate) return 0;
    return Math.max(1, Math.ceil((new Date(config.endDate) - new Date(config.startDate)) / 86400000));
  }, [config.startDate, config.endDate]);

  return (
    <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
      <div className="flex items-center gap-2 mb-5">
        <FlaskConical className="w-4 h-4 text-amber-400" />
        <h3 className="text-sm font-bold text-white">Configuration du backtest</h3>
      </div>

      {/* ── Section 1: Stratégie & Actif ── */}
      <div className="grid sm:grid-cols-2 gap-4 mb-4">
        {/* Strategy */}
        <div>
          <InfoLabel
            label="Stratégie"
            tooltip="Sélectionnez une stratégie créée dans le Module 2. L'actif associé sera chargé automatiquement."
          >
            <select
              className={inputCls}
              value={config.strategyId}
              onChange={(e) => handleStrategyChange(e.target.value)}
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

        {/* Asset */}
        <div>
          <InfoLabel
            label="Actif"
            tooltip="L'actif est déterminé par la stratégie. Vous pouvez le changer uniquement si la stratégie supporte plusieurs actifs."
          >
            <div className="relative">
              <select
                className={`${inputCls} ${!canChangeAsset ? "cursor-not-allowed opacity-80" : ""}`}
                value={config.assetSymbol}
                onChange={(e) => setConfig({ ...config, assetSymbol: e.target.value })}
                disabled={!canChangeAsset}
              >
                {config.assetSymbol && !availableAssets.find(a => a.symbol === config.assetSymbol) && (
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
      </div>

      {/* Strategy compatibility badge */}
      {selectedStrategy && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-[10px]">
          <span className="text-slate-600">Portée de la stratégie :</span>
          {selectedStrategy.asset_scope === "specific" && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <Lock className="w-2.5 h-2.5" />
              {selectedStrategy.asset_symbols?.length || 0} actif(s) spécifique(s)
            </span>
          )}
          {selectedStrategy.asset_scope === "category" && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20">
              Catégorie : {selectedStrategy.asset_category}
            </span>
          )}
          {selectedStrategy.asset_scope === "all" && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Tous les actifs compatibles
            </span>
          )}
        </div>
      )}

      {/* ── Section 2: Période & Timeframe ── */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {/* Start date */}
        <div>
          <InfoLabel
            label="Date de début"
            tooltip="Date à laquelle la simulation commence. Les premières bougies servent au pré-calcul des indicateurs."
          >
            <input
              type="date"
              className={inputCls}
              value={config.startDate}
              onChange={(e) => setConfig({ ...config, startDate: e.target.value })}
            />
          </InfoLabel>
        </div>

        {/* End date */}
        <div>
          <InfoLabel
            label="Date de fin"
            tooltip="Date à laquelle la simulation s'arrête. Tous les trades ouverts seront clôturés à la dernière bougie."
          >
            <input
              type="date"
              className={inputCls}
              value={config.endDate}
              onChange={(e) => setConfig({ ...config, endDate: e.target.value })}
            />
          </InfoLabel>
        </div>

        {/* Timeframe */}
        <div>
          <InfoLabel
            label="Timeframe"
            tooltip="Unité de temps de chaque bougie (M1 = 1 minute, H1 = 1 heure, D1 = 1 jour). Plus le TF est court, plus la simulation est précise mais consomme plus de données."
          >
            <select
              className={inputCls}
              value={config.timeframe}
              onChange={(e) => setConfig({ ...config, timeframe: e.target.value })}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </InfoLabel>
        </div>

        {/* Period summary */}
        <div className="flex items-end">
          <div className="flex items-center gap-3 text-xs text-slate-500 px-3 py-2.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] w-full">
            <Calendar className="w-3.5 h-3.5 text-amber-400/60" />
            <span>{periodDays} jours</span>
            <span className="text-slate-700">|</span>
            <Clock className="w-3.5 h-3.5 text-amber-400/60" />
            <span>TF {config.timeframe}</span>
          </div>
        </div>
      </div>

      {/* ── Section 3: Capital & Risque ── */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {/* Initial capital */}
        <div>
          <InfoLabel
            label="Capital initial ($)"
            tooltip="Montant de départ virtuel pour la simulation. Sert de base au calcul du risque et de la courbe de capital."
          >
            <input
              type="number"
              step="100"
              className={inputCls}
              value={config.initialCapital}
              onChange={(e) => setConfig({ ...config, initialCapital: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>

        {/* Risk per trade */}
        <div>
          <InfoLabel
            label="Risque par trade (%)"
            tooltip="Pourcentage du capital risqué par trade. Utilisé pour calculer la taille de position si la stratégie est en mode 'percent'."
          >
            <input
              type="number"
              step="0.1"
              min="0"
              className={inputCls}
              value={config.riskPerTrade}
              onChange={(e) => setConfig({ ...config, riskPerTrade: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>

        {/* Lot size */}
        <div>
          <InfoLabel
            label="Taille du lot"
            tooltip="Taille fixe du lot par trade. Sert si la stratégie ne calcule pas automatiquement la taille de position."
          >
            <input
              type="number"
              step="0.01"
              min="0.01"
              className={inputCls}
              value={config.lotSize}
              onChange={(e) => setConfig({ ...config, lotSize: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>

        {/* Leverage */}
        <div>
          <InfoLabel
            label="Levier"
            tooltip="Effet de levier appliqué (ex: 100 = 1:100). Plus le levier est élevé, plus les gains et pertes sont amplifiés."
          >
            <input
              type="number"
              step="1"
              min="1"
              className={inputCls}
              value={config.leverage}
              onChange={(e) => setConfig({ ...config, leverage: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
      </div>

      {/* ── Section 4: Coûts de transaction ── */}
      <div className="grid sm:grid-cols-3 gap-4 mb-5">
        {/* Spread */}
        <div>
          <InfoLabel
            label="Spread (pips)"
            tooltip="Différence entre prix d'achat et prix de vente. Simule le coût du spread appliqué à chaque entrée et sortie de trade."
          >
            <input
              type="number"
              step="0.1"
              min="0"
              className={inputCls}
              value={config.spread}
              onChange={(e) => setConfig({ ...config, spread: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>

        {/* Commission */}
        <div>
          <InfoLabel
            label="Commission ($/lot)"
            tooltip="Frais de courtage par lot, appliqués à chaque trade (entrée + sortie). Ex: 7$ par lot chez certains brokers."
          >
            <input
              type="number"
              step="0.5"
              min="0"
              className={inputCls}
              value={config.commission}
              onChange={(e) => setConfig({ ...config, commission: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>

        {/* Slippage */}
        <div>
          <InfoLabel
            label="Slippage (pips)"
            tooltip="Glissement de prix simulé à l'exécution. Représente la différence entre le prix attendu et le prix réellement obtenu."
          >
            <input
              type="number"
              step="0.1"
              min="0"
              className={inputCls}
              value={config.slippage}
              onChange={(e) => setConfig({ ...config, slippage: Number(e.target.value) })}
            />
          </InfoLabel>
        </div>
      </div>

      <button
        onClick={onRun}
        disabled={running || !config.strategyId || !config.assetSymbol}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-bold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
      >
        {running ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Backtest en cours…
          </>
        ) : (
          <>
            <Play className="w-4 h-4" />
            Lancer le backtest
          </>
        )}
      </button>
    </div>
  );
}