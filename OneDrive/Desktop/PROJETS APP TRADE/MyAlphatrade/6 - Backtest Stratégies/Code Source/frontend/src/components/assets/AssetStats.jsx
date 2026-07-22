import React from "react";
import { Wallet, CheckCircle2, XCircle, FolderTree } from "lucide-react";

export default function AssetStats({ assets }) {
  const total = assets.length;
  const active = assets.filter((a) => a.status === "active").length;
  const inactive = total - active;
  const categories = new Set(assets.map((a) => a.category).filter(Boolean)).size;

  const stats = [
    { label: "Total actifs", value: total, icon: Wallet, color: "text-amber-400", bg: "bg-amber-500/10" },
    { label: "Actifs", value: active, icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    { label: "Inactifs", value: inactive, icon: XCircle, color: "text-rose-400", bg: "bg-rose-500/10" },
    { label: "Catégories", value: categories, icon: FolderTree, color: "text-violet-400", bg: "bg-violet-500/10" },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((stat, i) => (
        <div
          key={i}
          className="p-4 rounded-2xl bg-[#0d1220] border border-[#1a2332]"
        >
          <div className={`w-9 h-9 rounded-xl ${stat.bg} flex items-center justify-center mb-3`}>
            <stat.icon className={`w-4 h-4 ${stat.color}`} />
          </div>
          <p className="text-2xl font-bold text-white">{stat.value}</p>
          <p className="text-xs text-slate-500 mt-0.5">{stat.label}</p>
        </div>
      ))}
    </div>
  );
}