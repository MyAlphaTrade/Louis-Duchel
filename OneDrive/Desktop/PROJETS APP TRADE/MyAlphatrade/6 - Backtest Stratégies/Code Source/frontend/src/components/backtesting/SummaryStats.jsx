import React from "react";
import {
  TrendingUp, TrendingDown, Target, Percent, Activity,
  Gauge, Scale, DollarSign, BarChart3, Clock, Wallet
} from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { Info } from "lucide-react";

function StatCard({ icon: Icon, label, value, sublabel, color, tooltip }) {
  return (
    <div className="p-4 rounded-2xl bg-[#0d1220] border border-[#1a2332] hover:border-[#2a3548] transition-colors">
      <div className="flex items-center justify-between mb-2">
        <div className={`w-8 h-8 rounded-lg ${color.bg} flex items-center justify-center`}>
          <Icon className={`w-4 h-4 ${color.text}`} />
        </div>
        <div className="flex items-center gap-1">
          {tooltip && (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex">
                    <Info className="w-3 h-3 text-slate-600 hover:text-amber-400 cursor-help transition-colors" />
                  </span>
                </TooltipTrigger>
                <TooltipContent
                  side="top"
                  className="max-w-[220px] text-center leading-relaxed bg-[#1a2332] border border-[#2a3548] text-slate-300"
                >
                  {tooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
          {sublabel && <span className="text-[9px] text-slate-600 uppercase">{sublabel}</span>}
        </div>
      </div>
      <p className={`text-xl font-bold ${color.text}`}>{value}</p>
      <p className="text-[10px] text-slate-500 mt-0.5">{label}</p>
    </div>
  );
}

export default function SummaryStats({ metrics }) {
  const m = metrics;
  const isProfit = m.netProfit >= 0;

  const colors = {
    profit: { bg: "bg-emerald-500/10", text: "text-emerald-400" },
    loss: { bg: "bg-rose-500/10", text: "text-rose-400" },
    neutral: { bg: "bg-slate-500/10", text: "text-slate-300" },
    amber: { bg: "bg-amber-500/10", text: "text-amber-400" },
    blue: { bg: "bg-blue-500/10", text: "text-blue-400" },
    violet: { bg: "bg-violet-500/10", text: "text-violet-400" },
  };

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <StatCard
        icon={Wallet}
        label="Capital initial"
        value={`$${m.initialCapital.toLocaleString()}`}
        sublabel="Départ"
        color={colors.neutral}
        tooltip="Montant de départ virtuel pour la simulation."
      />
      <StatCard
        icon={DollarSign}
        label="Capital final"
        value={`$${m.finalEquity.toLocaleString()}`}
        sublabel="Arrivée"
        color={colors.amber}
        tooltip="Capital total après tous les trades de la simulation."
      />
      <StatCard
        icon={TrendingUp}
        label="Profit total"
        value={`${m.netProfit >= 0 ? "+" : ""}$${m.netProfit.toLocaleString()}`}
        sublabel={`${m.returnPct >= 0 ? "+" : ""}${m.returnPct}%`}
        color={isProfit ? colors.profit : colors.loss}
        tooltip="Bénéfice ou perte nette en dollars, incluant spread, commission et slippage."
      />
      <StatCard
        icon={BarChart3}
        label="Trades totaux"
        value={m.totalTrades}
        sublabel={`${m.bars || 0} bars`}
        color={colors.neutral}
        tooltip="Nombre total de trades exécutés pendant la simulation."
      />
      <StatCard
        icon={Target}
        label="Taux de réussite"
        value={`${m.winRate}%`}
        sublabel={`${m.winningTrades}G / ${m.losingTrades}P`}
        color={m.winRate >= 50 ? colors.profit : colors.loss}
        tooltip="Pourcentage de trades gagnants par rapport au total."
      />
      <StatCard
        icon={Scale}
        label="Profit Factor"
        value={m.profitFactor}
        sublabel="Brut G / Brut P"
        color={m.profitFactor >= 1 ? colors.profit : colors.loss}
        tooltip="Ratio entre le profit brut et la perte brute. Au-dessus de 1 = rentable."
      />
      <StatCard
        icon={TrendingUp}
        label="Gain moyen"
        value={`$${m.avgWin}`}
        sublabel="Par trade gagnant"
        color={colors.profit}
        tooltip="Profit moyen par trade gagnant."
      />
      <StatCard
        icon={TrendingDown}
        label="Perte moyenne"
        value={`$${m.avgLoss}`}
        sublabel="Par trade perdant"
        color={colors.loss}
        tooltip="Perte moyenne par trade perdant."
      />
      <StatCard
        icon={Activity}
        label="Drawdown max"
        value={`${m.maxDrawdown}%`}
        sublabel="Pic à creux"
        color={colors.loss}
        tooltip="Plus forte baisse du capital depuis son pic. Mesure le risque maximal encouru."
      />
      <StatCard
        icon={Gauge}
        label="Espérance"
        value={`$${m.expectancy}`}
        sublabel="Par trade"
        color={m.expectancy >= 0 ? colors.profit : colors.loss}
        tooltip="Gain ou perte moyenne attendue par trade. Doit être positif pour être rentable."
      />
      <StatCard
        icon={Percent}
        label="Ratio G/P"
        value={m.winLossRatio}
        sublabel="Gain moy / Perte moy"
        color={colors.blue}
        tooltip="Ratio entre le gain moyen et la perte moyenne. Indique la qualité des trades."
      />
      <StatCard
        icon={Clock}
        label="Trades / jour"
        value={m.tradesPerDay}
        sublabel="Fréquence"
        color={colors.violet}
        tooltip="Nombre moyen de trades exécutés par jour sur la période."
      />
    </div>
  );
}