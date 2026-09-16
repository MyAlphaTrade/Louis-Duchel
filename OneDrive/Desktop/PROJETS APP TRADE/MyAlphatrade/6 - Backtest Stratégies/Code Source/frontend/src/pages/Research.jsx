import React, { useState, useEffect, useMemo } from "react";
import { base44 } from "@/api/base44Client";
import { useAsset } from "@/lib/AssetContext";
import { bucketFillTimes } from "@/lib/gapHistogram";
import { StatCard, STAT_CARD_COLORS } from "@/components/backtesting/SummaryStats";
import {
  Microscope, CheckCircle2, Clock, TrendingUp, Sigma, Loader2, AlertTriangle,
  Lock,
} from "lucide-react";

// Feuille de route affichee honnetement -- rien ici n'est calcule par le
// backend pour l'instant (seule l'analyse de gap, ci-dessus dans la page,
// est reelle). Louis (16-17/09/2026) veut TOUS les indicateurs/correlations
// possibles a terme ; ces cartes montrent la cible sans jamais pretendre
// qu'elle est deja implementee.
const ROADMAP_INDICATORS = [
  { name: "EMA 9/21 cross", note: "Deja disponible comme regle de stratégie (Module 2) — pas encore agrege ici en indicateur de marché." },
  { name: "RSI (14)", note: "À venir." },
  { name: "ADX / force de tendance", note: "À venir." },
  { name: "Fair Value Gaps (FVG)", note: "À venir." },
  { name: "Order Blocks", note: "À venir." },
  { name: "Corrélations D1 → M15/M5", note: "À venir." },
];

function GapSection({ title, data, note }) {
  if (data?.error) {
    return (
      <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] p-5">
        <h3 className="text-sm font-bold text-white mb-2">{title}</h3>
        <p className="text-xs text-amber-400/80 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5" /> {data.error}
        </p>
      </div>
    );
  }
  if (!data) return null;
  const stats = data.stats.all;
  const buckets = bucketFillTimes(data.gaps);
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] p-5">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-bold text-white">{title}</h3>
      </div>
      {note && <p className="text-[11px] text-slate-600 mb-4">{note}</p>}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard
          icon={CheckCircle2}
          label="Gaps comblés"
          value={stats.filled_pct != null ? `${stats.filled_pct}%` : "—"}
          color={stats.filled_pct >= 50 ? STAT_CARD_COLORS.profit : STAT_CARD_COLORS.loss}
          tooltip="Part des gaps qui reviennent toucher le close précédent, dans l'horizon d'analyse."
        />
        <StatCard
          icon={Clock}
          label="Délai médian"
          value={stats.fill_minutes_median != null ? `${stats.fill_minutes_median} min` : "—"}
          color={STAT_CARD_COLORS.amber}
          tooltip="Médiane du temps de comblement parmi les gaps effectivement comblés."
        />
        <StatCard
          icon={TrendingUp}
          label="Délai max observé"
          value={stats.fill_minutes_max != null ? `${stats.fill_minutes_max} min` : "—"}
          color={STAT_CARD_COLORS.violet}
          tooltip="Le plus long temps de comblement observé — indique une éventuelle traîne à droite."
        />
        <StatCard
          icon={Sigma}
          label="Gaps analysés"
          value={stats.count}
          color={STAT_CARD_COLORS.neutral}
          tooltip="Nombre total de gaps mesurés sur l'historique importé."
        />
      </div>

      <div className="p-4 rounded-xl bg-[#0a0e17] border border-[#1a2332]">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-bold text-slate-300">Répartition du délai de comblement</span>
          <span className="text-[10px] text-slate-600">{stats.count} gaps</span>
        </div>
        <div className="flex items-end gap-1.5 h-28">
          {buckets.map((b) => (
            <div key={b.key} className="flex-1 flex flex-col items-center justify-end h-full">
              <span className="text-[9px] text-slate-500 mb-1">{b.count > 0 ? `${b.pct}%` : ""}</span>
              <div
                className={`w-full rounded-t ${b.key === "jamais" ? "bg-slate-700 border border-dashed border-slate-600" : "bg-gradient-to-t from-emerald-600 to-emerald-400"}`}
                style={{ height: `${Math.max(4, (b.count / maxCount) * 100)}%`, opacity: b.key === "jamais" ? 1 : 0.5 + 0.5 * (b.count / maxCount) }}
              />
            </div>
          ))}
        </div>
        <div className="flex gap-1.5 mt-2">
          {buckets.map((b) => (
            <div key={b.key} className="flex-1 text-center text-[9px] text-slate-600">{b.label}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Research() {
  const { selectedAsset } = useAsset();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!selectedAsset?.symbol) return;
    let mounted = true;
    setLoading(true);
    setError(null);
    setData(null);
    base44.research
      .gapAnalysis(selectedAsset.symbol)
      .then((res) => { if (mounted) { setData(res); setLoading(false); } })
      .catch((err) => { if (mounted) { setError(err); setLoading(false); } });
    return () => { mounted = false; };
  }, [selectedAsset?.symbol]);

  return (
    <div className="p-6 lg:p-10">
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Microscope className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">Module 7</span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Recherche
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-2xl">
          Analyse automatique de l'historique complet de <span className="text-amber-400/90 font-medium">{selectedAsset?.symbol || "l'actif sélectionné"}</span> :
          comportement après chaque ouverture de session et chaque week-end, avec en cible tous les indicateurs et corrélations inter-timeframes.
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 py-10 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-xs">Analyse en cours…</span>
        </div>
      )}

      {error && (
        <div className="rounded-2xl bg-amber-500/5 border border-amber-500/20 p-5 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-white font-medium mb-1">Analyse impossible pour l'instant</p>
            <p className="text-xs text-slate-400">{error.message}</p>
          </div>
        </div>
      )}

      {data && (
        <div className="space-y-5">
          <GapSection title={`Ouverture de journée (gap D1) — ${data.symbol}`} data={data.d1} />
          <GapSection
            title={`Ouverture de session cash — ${data.symbol}`}
            data={data.cash_session}
            note={!data.cash_session ? "Aucune heure de session cash connue pour cet actif (n'est calculé que pour les indices dont la session boursière réelle est enregistrée)." : undefined}
          />
          {!data.cash_session && (
            <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] p-5 text-xs text-slate-500">
              Aucune heure de session cash réelle n'est enregistrée pour {data.symbol} — seul le gap D1 ci-dessus est calculé pour cet actif.
            </div>
          )}
        </div>
      )}

      <div className="mt-8 rounded-2xl bg-[#0d1220] border border-[#1a2332] p-5">
        <div className="flex items-center gap-2 mb-1">
          <Lock className="w-3.5 h-3.5 text-slate-600" />
          <h3 className="text-sm font-bold text-white">Indicateurs, validations & corrélations inter-timeframes</h3>
        </div>
        <p className="text-[11px] text-slate-600 mb-4">
          Périmètre cible complet — à ce stade, seule l'analyse de gap ci-dessus est réellement calculée.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {ROADMAP_INDICATORS.map((ind) => (
            <div key={ind.name} className="p-3.5 rounded-xl bg-[#0a0e17] border border-dashed border-[#1a2332]">
              <p className="text-xs font-bold text-slate-300 mb-1">{ind.name}</p>
              <p className="text-[10px] text-slate-600">{ind.note}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
