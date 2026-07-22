import React from "react";
import { useAsset } from "@/lib/AssetContext";
import { getAssetStyle } from "@/lib/assets";
import { ASSET_CATEGORIES, TIMEFRAMES } from "@/lib/assets";
import { Check } from "lucide-react";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

function Field({ label, children, optional }) {
  return (
    <div>
      <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">
        {label}
        {optional && <span className="text-slate-600 ml-1">(optionnel)</span>}
      </label>
      {children}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <h4 className="text-xs font-semibold text-amber-400/70 tracking-widest uppercase mb-4">
      {children}
    </h4>
  );
}

export default function GeneralInfo({ form, set }) {
  const { activeAssets } = useAsset();

  const toggleAsset = (symbol) => {
    const current = form.asset_symbols || [];
    const next = current.includes(symbol)
      ? current.filter((s) => s !== symbol)
      : [...current, symbol];
    set("asset_symbols", next);
  };

  const toggleSecondaryTF = (tf) => {
    const current = form.secondary_timeframes || [];
    const next = current.includes(tf)
      ? current.filter((s) => s !== tf)
      : [...current, tf];
    set("secondary_timeframes", next);
  };

  return (
    <div className="space-y-8">
      {/* Informations générales */}
      <div>
        <SectionTitle>Informations générales</SectionTitle>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Nom de la stratégie">
            <input
              className={inputCls}
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Scalping London Gold"
              required
            />
          </Field>
          <Field label="Version">
            <input
              className={inputCls}
              value={form.version}
              onChange={(e) => set("version", e.target.value)}
              placeholder="1.0"
            />
          </Field>
          <Field label="Auteur" optional>
            <input
              className={inputCls}
              value={form.author}
              onChange={(e) => set("author", e.target.value)}
              placeholder="AlphaTrade"
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Description" optional>
              <textarea
                className={inputCls}
                rows={2}
                value={form.description}
                onChange={(e) => set("description", e.target.value)}
                placeholder="Description de la stratégie…"
              />
            </Field>
          </div>
        </div>
      </div>

      {/* Actifs */}
      <div>
        <SectionTitle>Actifs ciblés</SectionTitle>
        <div className="mb-3">
          <div className="flex gap-2">
            {[
              { value: "specific", label: "Actifs spécifiques" },
              { value: "category", label: "Par catégorie" },
              { value: "all", label: "Tous les actifs" },
            ].map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => set("asset_scope", opt.value)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  form.asset_scope === opt.value
                    ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                    : "bg-[#0a0e17] text-slate-500 border border-[#1a2332] hover:text-white"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {form.asset_scope === "specific" && (
          <div className="flex flex-wrap gap-2">
            {activeAssets.map((asset) => {
              const style = getAssetStyle(asset.color);
              const selected = form.asset_symbols?.includes(asset.symbol);
              return (
                <button
                  key={asset.id}
                  type="button"
                  onClick={() => toggleAsset(asset.symbol)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm border transition-all ${
                    selected
                      ? `${style.bg} ${style.text} ${style.border}`
                      : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-white"
                  }`}
                >
                  {selected && <Check className="w-3 h-3" />}
                  {asset.symbol}
                </button>
              );
            })}
          </div>
        )}

        {form.asset_scope === "category" && (
          <select
            value={form.asset_category || ""}
            onChange={(e) => set("asset_category", e.target.value)}
            className={inputCls}
          >
            <option value="">Sélectionner une catégorie</option>
            {ASSET_CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        )}

        {form.asset_scope === "all" && (
          <p className="text-sm text-slate-500 px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332]">
            La stratégie s'appliquera à tous les actifs actifs.
          </p>
        )}
      </div>

      {/* Timeframes */}
      <div>
        <SectionTitle>Timeframes</SectionTitle>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Timeframe principal">
            <select
              className={inputCls}
              value={form.primary_timeframe}
              onChange={(e) => set("primary_timeframe", e.target.value)}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="mt-3">
          <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">
            Timeframes secondaires (multi-TF optionnel)
          </label>
          <div className="flex flex-wrap gap-2">
            {TIMEFRAMES.filter((tf) => tf !== form.primary_timeframe).map((tf) => {
              const selected = form.secondary_timeframes?.includes(tf);
              return (
                <button
                  key={tf}
                  type="button"
                  onClick={() => toggleSecondaryTF(tf)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                    selected
                      ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                      : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-white"
                  }`}
                >
                  {selected && <Check className="w-3 h-3 inline mr-1" />}
                  {tf}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}