import React, { useState, useMemo } from "react";
import { useAsset } from "@/lib/AssetContext";
import { base44 } from "@/api/base44Client";
import {
  ASSET_CATEGORIES,
  getAssetStyle,
  getAssetIcon,
} from "@/lib/assets";
import AssetStats from "@/components/assets/AssetStats";
import AssetTable from "@/components/assets/AssetTable";
import AssetForm from "@/components/assets/AssetForm";
import {
  Plus,
  Search,
  Loader2,
  Settings,
  TrendingUp,
} from "lucide-react";

export default function AssetManagement() {
  const { assets, loading } = useAsset();
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [sortBy, setSortBy] = useState("order");
  const [formOpen, setFormOpen] = useState(false);
  const [editingAsset, setEditingAsset] = useState(null);

  const filtered = useMemo(() => {
    let result = [...assets];
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (a) =>
          a.symbol?.toLowerCase().includes(q) ||
          a.name?.toLowerCase().includes(q) ||
          a.category?.toLowerCase().includes(q) ||
          a.broker?.toLowerCase().includes(q)
      );
    }
    if (categoryFilter) {
      result = result.filter((a) => a.category === categoryFilter);
    }
    result.sort((a, b) => {
      if (sortBy === "name") return (a.name || "").localeCompare(b.name || "");
      if (sortBy === "symbol") return (a.symbol || "").localeCompare(b.symbol || "");
      if (sortBy === "category") return (a.category || "").localeCompare(b.category || "");
      return (a.order || 0) - (b.order || 0);
    });
    return result;
  }, [assets, search, categoryFilter, sortBy]);

  const handleAdd = () => {
    setEditingAsset(null);
    setFormOpen(true);
  };

  const handleEdit = (asset) => {
    setEditingAsset(asset);
    setFormOpen(true);
  };

  const handleToggleStatus = async (asset) => {
    await base44.entities.TradingAsset.update(asset.id, {
      status: asset.status === "active" ? "inactive" : "active",
    });
  };

  const handleDelete = async (asset) => {
    if (
      window.confirm(
        `Supprimer "${asset.symbol}" ? Cette action est irréversible.`
      )
    ) {
      await base44.entities.TradingAsset.delete(asset.id);
    }
  };

  const handleSave = async (data) => {
    if (editingAsset) {
      await base44.entities.TradingAsset.update(editingAsset.id, data);
    } else {
      await base44.entities.TradingAsset.create(data);
    }
    setFormOpen(false);
    setEditingAsset(null);
  };

  return (
    <div className="p-6 lg:p-10 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Settings className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Administration
          </span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Gestion des actifs
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-xl">
          Source unique de tous les instruments de trading. Tout ajout, modification ou
          suppression se répercute instantanément dans tous les modules.
        </p>
      </div>

      {/* Stats */}
      <AssetStats assets={assets} />

      {/* Toolbar */}
      <div className="mt-8 flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Rechercher par symbole, nom, catégorie…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-11 pr-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors"
          />
        </div>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="px-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors cursor-pointer"
        >
          <option value="">Toutes catégories</option>
          {ASSET_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="px-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors cursor-pointer"
        >
          <option value="order">Tri par défaut</option>
          <option value="name">Nom</option>
          <option value="symbol">Symbole</option>
          <option value="category">Catégorie</option>
        </select>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 transition-all flex-shrink-0"
        >
          <Plus className="w-4 h-4" />
          Ajouter
        </button>
      </div>

      {/* Table */}
      <div className="mt-6">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-500 py-12 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">Chargement…</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
            <TrendingUp className="w-8 h-8 text-slate-700 mx-auto mb-3" />
            <p className="text-sm text-slate-500">
              {search || categoryFilter
                ? "Aucun actif ne correspond à votre recherche."
                : "Aucun actif. Cliquez sur « Ajouter » pour commencer."}
            </p>
          </div>
        ) : (
          <AssetTable
            assets={filtered}
            onEdit={handleEdit}
            onToggleStatus={handleToggleStatus}
            onDelete={handleDelete}
          />
        )}
      </div>

      {/* Form modal */}
      {formOpen && (
        <AssetForm
          asset={editingAsset}
          onSave={handleSave}
          onClose={() => {
            setFormOpen(false);
            setEditingAsset(null);
          }}
        />
      )}
    </div>
  );
}