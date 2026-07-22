import React from "react";
import { getAssetStyle, getAssetIcon } from "@/lib/assets";
import { Pencil, Trash2, Power } from "lucide-react";

export default function AssetTable({ assets, onEdit, onToggleStatus, onDelete }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-[#0d1220] border border-[#1a2332]">
      <table className="w-full">
        <thead>
          <tr className="border-b border-[#1a2332]">
            <th className="text-left text-[10px] font-semibold tracking-wider uppercase text-slate-600 px-4 py-3">
              Actif
            </th>
            <th className="text-left text-[10px] font-semibold tracking-wider uppercase text-slate-600 px-4 py-3">
              Catégorie
            </th>
            <th className="text-left text-[10px] font-semibold tracking-wider uppercase text-slate-600 px-4 py-3 hidden md:table-cell">
              Broker
            </th>
            <th className="text-left text-[10px] font-semibold tracking-wider uppercase text-slate-600 px-4 py-3 hidden lg:table-cell">
              TF par défaut
            </th>
            <th className="text-left text-[10px] font-semibold tracking-wider uppercase text-slate-600 px-4 py-3">
              Statut
            </th>
            <th className="text-right text-[10px] font-semibold tracking-wider uppercase text-slate-600 px-4 py-3">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => {
            const style = getAssetStyle(asset.color);
            const Icon = getAssetIcon(asset.icon);
            const isActive = asset.status === "active";

            return (
              <tr
                key={asset.id}
                className="border-b border-[#1a2332] last:border-0 hover:bg-white/[0.02] transition-colors"
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg ${style.bg} flex items-center justify-center flex-shrink-0`}>
                      <Icon className={`w-4 h-4 ${style.text}`} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-white leading-tight">
                        {asset.symbol}
                      </p>
                      <p className="text-[11px] text-slate-500 leading-tight truncate">
                        {asset.name}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-[10px] font-medium px-2 py-1 rounded-full ${style.bg} ${style.text}`}>
                    {asset.category}
                  </span>
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <span className="text-sm text-slate-400">{asset.broker || "—"}</span>
                </td>
                <td className="px-4 py-3 hidden lg:table-cell">
                  <span className="text-sm text-slate-400 font-mono">{asset.default_timeframe}</span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-full ${
                      isActive ? "bg-emerald-500/10 text-emerald-400" : "bg-slate-500/10 text-slate-500"
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${isActive ? "bg-emerald-400" : "bg-slate-600"}`} />
                    {isActive ? "Actif" : "Inactif"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => onToggleStatus(asset)}
                      title={isActive ? "Désactiver" : "Réactiver"}
                      className="p-2 rounded-lg text-slate-500 hover:text-white hover:bg-white/5 transition-colors"
                    >
                      <Power className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => onEdit(asset)}
                      title="Modifier"
                      className="p-2 rounded-lg text-slate-500 hover:text-amber-400 hover:bg-amber-500/5 transition-colors"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => onDelete(asset)}
                      title="Supprimer"
                      className="p-2 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/5 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}