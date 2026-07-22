import React, { useState, useEffect, useRef, useCallback } from "react";
import { useAsset } from "@/lib/AssetContext";
import { getAssetStyle, TIMEFRAMES } from "@/lib/assets";
import { parseMt5Csv } from "@/lib/csvImport";
import { base44 } from "@/api/base44Client";
import AssetCard from "@/components/AssetCard";
import {
  Upload,
  Layers,
  CandlestickChart,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  FileText,
} from "lucide-react";

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MarketData() {
  const { activeAssets, selectedSymbol, setSelectedSymbol, selectedAsset, loading } =
    useAsset();
  const style = getAssetStyle(selectedAsset?.color || "amber");
  const fileInputRef = useRef(null);

  const [timeframe, setTimeframe] = useState("M15");
  const [importStatus, setImportStatus] = useState("idle"); // idle | reading | importing | success | error
  const [importMessage, setImportMessage] = useState("");
  const [parsedCount, setParsedCount] = useState(0);
  const [summary, setSummary] = useState([]);
  const [summaryLoading, setSummaryLoading] = useState(true);

  // Default the timeframe selector to the selected asset's default TF.
  useEffect(() => {
    if (selectedAsset?.default_timeframe) {
      setTimeframe(selectedAsset.default_timeframe);
    }
  }, [selectedAsset?.symbol]);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const data = await base44.marketData.summary();
      setSummary(Array.isArray(data) ? data : []);
    } catch {
      setSummary([]);
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const assetSummary = summary.filter((s) => s.symbol === selectedAsset?.symbol);

  const handlePickFile = () => {
    if (!selectedAsset) return;
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file || !selectedAsset) return;

    setImportStatus("reading");
    setImportMessage("Lecture du fichier…");
    setParsedCount(0);

    try {
      const text = await file.text();
      const candles = parseMt5Csv(text);
      setParsedCount(candles.length);

      setImportStatus("importing");
      setImportMessage(`Import de ${candles.length} bougie(s) en cours…`);

      const result = await base44.marketData.import(selectedAsset.symbol, timeframe, candles);

      setImportStatus("success");
      setImportMessage(
        `${result?.imported ?? candles.length} bougies importées pour ${selectedAsset.symbol} (${timeframe}).`
      );
      loadSummary();
    } catch (err) {
      setImportStatus("error");
      setImportMessage(err?.message || "Échec de l'import. Vérifiez le format du fichier.");
    }
  };

  const isBusy = importStatus === "reading" || importStatus === "importing";

  return (
    <div className="p-6 lg:p-10 max-w-6xl">
      <div className="mb-8">
        <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
          Module 1
        </span>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight mt-1">
          Données de marché
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-xl">
          Sélectionnez un actif pour gérer ses données historiques. Chaque actif dispose d'un
          stockage et de paramètres indépendants.
        </p>
      </div>

      {/* Asset cards grid */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">Actifs disponibles</h3>
          <span className="text-xs text-slate-500">{activeAssets.length} actifs</span>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-slate-500 py-8">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">Chargement des actifs…</span>
          </div>
        ) : activeAssets.length === 0 ? (
          <div className="text-center py-12 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
            <p className="text-sm text-slate-500">
              Aucun actif actif. Ajoutez-en depuis la Gestion des actifs.
            </p>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {activeAssets.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                isActive={asset.symbol === selectedSymbol}
                onSelect={() => setSelectedSymbol(asset.symbol)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Selected asset panel */}
      {selectedAsset && (
        <div className={`rounded-2xl border ${style.border} ${style.bg} p-6`}>
          <div className="flex items-center gap-3 mb-1">
            <span className={`w-2.5 h-2.5 rounded-full ${style.dot}`} />
            <h3 className={`text-lg font-bold ${style.text}`}>{selectedAsset.symbol}</h3>
            <span className="text-xs text-slate-500">— {selectedAsset.name}</span>
          </div>
          <p className="text-sm text-slate-400 mb-6">{selectedAsset.description}</p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-xl bg-black/20 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Catégorie</p>
              <p className="text-sm text-white font-medium">{selectedAsset.category}</p>
            </div>
            <div className="rounded-xl bg-black/20 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Digits</p>
              <p className="text-sm text-white font-medium">{selectedAsset.digits}</p>
            </div>
            <div className="rounded-xl bg-black/20 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Pip size</p>
              <p className="text-sm text-white font-medium">{selectedAsset.pip_size}</p>
            </div>
            <div className="rounded-xl bg-black/20 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                Timeframe par défaut
              </p>
              <p className="text-sm text-white font-medium">{selectedAsset.default_timeframe}</p>
            </div>
          </div>
        </div>
      )}

      {/* Import + Storage */}
      <div className="mt-8 grid lg:grid-cols-2 gap-4">
        {/* Import card */}
        <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <Upload className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h4 className="font-semibold text-white text-sm">Import historique MT5</h4>
              <p className="text-[11px] text-slate-500">
                Fichier CSV exporté depuis MetaTrader 5 (colonnes séparées par tabulations).
              </p>
            </div>
          </div>

          {!selectedAsset ? (
            <p className="text-xs text-slate-500 mt-4">
              Sélectionnez un actif ci-dessus pour importer son historique.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              <div className="flex items-center gap-3">
                <label className="text-[11px] font-medium text-slate-400 whitespace-nowrap">
                  Timeframe
                </label>
                <select
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  disabled={isBusy}
                  className="flex-1 px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors disabled:opacity-50"
                >
                  {TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>
                      {tf}
                    </option>
                  ))}
                </select>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleFileChange}
                className="hidden"
              />

              <button
                onClick={handlePickFile}
                disabled={isBusy}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-bold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                {isBusy ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {importMessage}
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4" />
                    Importer un fichier CSV pour {selectedAsset.symbol}
                  </>
                )}
              </button>

              {importStatus === "success" && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-emerald-300">{importMessage}</p>
                </div>
              )}

              {importStatus === "error" && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20">
                  <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-rose-300 break-words">{importMessage}</p>
                </div>
              )}

              {parsedCount > 0 && importStatus === "importing" && (
                <p className="text-[11px] text-slate-500">{parsedCount} bougie(s) parsée(s), envoi au serveur…</p>
              )}
            </div>
          )}
        </div>

        {/* Storage card */}
        <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <Layers className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h4 className="font-semibold text-white text-sm">Stockage — {selectedAsset?.symbol || "—"}</h4>
              <p className="text-[11px] text-slate-500">Historiques déjà importés pour cet actif.</p>
            </div>
          </div>

          <div className="mt-4">
            {summaryLoading ? (
              <div className="flex items-center gap-2 text-slate-500 py-4">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-xs">Chargement…</span>
              </div>
            ) : !selectedAsset ? (
              <p className="text-xs text-slate-500">Sélectionnez un actif pour voir son historique.</p>
            ) : assetSummary.length === 0 ? (
              <div className="flex items-center gap-2 text-slate-500 py-4">
                <FileText className="w-4 h-4" />
                <span className="text-xs">Aucune donnée importée pour {selectedAsset.symbol}.</span>
              </div>
            ) : (
              <div className="space-y-2">
                {assetSummary.map((s) => (
                  <div
                    key={`${s.symbol}-${s.timeframe}`}
                    className="flex items-center justify-between p-3 rounded-lg bg-black/20"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-amber-400 w-10">{s.timeframe}</span>
                      <span className="text-[11px] text-slate-400">{s.count} bougies</span>
                    </div>
                    <span className="text-[10px] text-slate-500">
                      {formatDate(s.start)} → {formatDate(s.end)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Features */}
      <div className="mt-8">
        <h3 className="text-sm font-semibold text-white mb-4">Fonctionnalités</h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div className="group relative p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332] hover:border-amber-500/20 transition-all duration-300">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center mb-4">
              <Upload className="w-5 h-5 text-amber-400" />
            </div>
            <h4 className="font-semibold text-white text-sm mb-1">Import historique MT5</h4>
            <p className="text-xs text-slate-500 leading-relaxed">
              Importez les données historiques de chaque actif depuis MetaTrader 5 au format CSV.
            </p>
            <div className="mt-4">
              <span className="inline-flex items-center gap-1.5 text-[10px] font-medium tracking-wider uppercase px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Disponible
              </span>
            </div>
          </div>

          <div className="group relative p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332] hover:border-amber-500/20 transition-all duration-300">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center mb-4">
              <Layers className="w-5 h-5 text-amber-400" />
            </div>
            <h4 className="font-semibold text-white text-sm mb-1">Stockage par actif</h4>
            <p className="text-xs text-slate-500 leading-relaxed">
              Historiques et paramètres gérés indépendamment pour chaque actif, sans interférence.
            </p>
            <div className="mt-4">
              <span className="inline-flex items-center gap-1.5 text-[10px] font-medium tracking-wider uppercase px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Disponible
              </span>
            </div>
          </div>

          <div className="group relative p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332] hover:border-amber-500/20 transition-all duration-300">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center mb-4">
              <CandlestickChart className="w-5 h-5 text-amber-400" />
            </div>
            <h4 className="font-semibold text-white text-sm mb-1">Bougies multi-timeframe</h4>
            <p className="text-xs text-slate-500 leading-relaxed">
              Visualisation des bougies M1, M5, M15, H1, H4 et D1 avec filtrage avancé par actif.
            </p>
            <div className="mt-4">
              <span className="inline-flex items-center gap-1.5 text-[10px] font-medium tracking-wider uppercase px-2.5 py-1 rounded-full bg-white/5 text-slate-500">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
                Bientôt disponible
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
