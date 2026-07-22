import React, { useState, useEffect, useMemo } from "react";
import { base44 } from "@/api/base44Client";
import { useAsset } from "@/lib/AssetContext";
import { useToast } from "@/components/ui/use-toast";
import StrategyCard from "@/components/strategy/StrategyCard";
import StrategyForm from "@/components/strategy/StrategyForm";
import { Plus, Search, Loader2, FlaskConical } from "lucide-react";

const STATUS_OPTIONS = [
  { value: "", label: "Tous statuts" },
  { value: "draft", label: "Brouillon" },
  { value: "tested", label: "Testée" },
  { value: "active", label: "Active" },
  { value: "archived", label: "Archivée" },
];

export default function Strategies() {
  const { assets } = useAsset();
  const { toast } = useToast();
  const [strategies, setStrategies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [assetFilter, setAssetFilter] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState(null);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await base44.entities.Strategy.list("-created_date", 500);
        if (mounted) {
          setStrategies(data);
          setLoading(false);
        }
      } catch {
        if (mounted) setLoading(false);
      }
    };
    load();

    const unsubscribe = base44.entities.Strategy.subscribe((event) => {
      if (!mounted) return;
      if (event.type === "create") {
        setStrategies((prev) => [event.data, ...prev]);
      } else if (event.type === "update") {
        setStrategies((prev) => prev.map((s) => (s.id === event.data.id ? event.data : s)));
      } else if (event.type === "delete") {
        setStrategies((prev) => prev.filter((s) => s.id !== event.id));
      }
    });

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  const filtered = useMemo(() => {
    let result = [...strategies];
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (s) =>
          s.name?.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q) ||
          s.author?.toLowerCase().includes(q)
      );
    }
    if (statusFilter) {
      result = result.filter((s) => s.status === statusFilter);
    }
    if (assetFilter) {
      result = result.filter((s) => {
        if (s.asset_scope === "all") return true;
        if (s.asset_scope === "category") {
          const asset = assets.find((a) => a.symbol === assetFilter);
          return asset?.category === s.asset_category;
        }
        return s.asset_symbols?.includes(assetFilter);
      });
    }
    return result;
  }, [strategies, search, statusFilter, assetFilter, assets]);

  const stats = [
    { label: "Total", value: strategies.length, color: "text-white" },
    { label: "Actives", value: strategies.filter((s) => s.status === "active").length, color: "text-emerald-400" },
    { label: "Testées", value: strategies.filter((s) => s.status === "tested").length, color: "text-blue-400" },
    { label: "Brouillons", value: strategies.filter((s) => s.status === "draft").length, color: "text-slate-400" },
  ];

  const handleAdd = () => {
    setEditingStrategy(null);
    setFormOpen(true);
  };

  const handleCardClick = (strategy) => {
    setEditingStrategy(strategy);
    setFormOpen(true);
  };

  const handleSave = async (data) => {
    if (editingStrategy?.id) {
      await base44.entities.Strategy.update(editingStrategy.id, data);
    } else {
      await base44.entities.Strategy.create(data);
    }
    setFormOpen(false);
    setEditingStrategy(null);
  };

  const handleDelete = async (strategy) => {
    if (!window.confirm(`Supprimer la stratégie « ${strategy.name} » ?`)) return;
    try {
      await base44.entities.Strategy.delete(strategy.id);
      toast({ title: "Stratégie supprimée", description: strategy.name });
    } catch (err) {
      toast({ title: "Erreur", description: err.message, variant: "destructive" });
    }
  };

  const bumpVersion = (version) => {
    if (!version) return "1.1";
    const parts = version.split(".");
    const minor = parseInt(parts[1] || "0", 10) + 1;
    return `${parts[0]}.${minor}`;
  };

  const handleNewVersion = (strategy) => {
    const newVersion = bumpVersion(strategy.version);
    setEditingStrategy({
      ...strategy,
      id: undefined,
      version: newVersion,
      parent_version_id: strategy.id,
      name: strategy.name,
      status: "draft",
    });
    setFormOpen(true);
    toast({
      title: "Nouvelle version",
      description: `Création de v${newVersion} à partir de v${strategy.version}`,
    });
  };

  const parentMap = useMemo(() => {
    const map = {};
    strategies.forEach((s) => {
      if (s.parent_version_id) {
        map[s.id] = strategies.find((p) => p.id === s.parent_version_id);
      }
    });
    return map;
  }, [strategies]);

  return (
    <div className="p-6 lg:p-10 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <FlaskConical className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Module 2
          </span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Créateur de stratégies
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-xl">
          Concevez, versionnez et gérez vos stratégies de trading. Chaque stratégie est liée à un
          ou plusieurs actifs avec ses propres conditions et règles de risque.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {stats.map((stat, i) => (
          <div key={i} className="p-4 rounded-xl bg-[#0d1220] border border-[#1a2332]">
            <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
            <p className="text-[10px] text-slate-600 uppercase tracking-wider mt-1">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Rechercher par nom, description, auteur…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-11 pr-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors"
          />
        </div>
        <select
          value={assetFilter}
          onChange={(e) => setAssetFilter(e.target.value)}
          className="px-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors cursor-pointer"
        >
          <option value="">Tous les actifs</option>
          {assets.map((a) => (
            <option key={a.id} value={a.symbol}>
              {a.symbol}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-4 py-2.5 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-colors cursor-pointer"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 transition-all flex-shrink-0"
        >
          <Plus className="w-4 h-4" />
          Ajouter
        </button>
      </div>

      {/* Grid */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Chargement des stratégies…</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
          <FlaskConical className="w-8 h-8 text-slate-700 mx-auto mb-3" />
          <p className="text-sm text-slate-500">
            {search || statusFilter || assetFilter
              ? "Aucune stratégie ne correspond à votre recherche."
              : "Aucune stratégie. Cliquez sur « Ajouter » pour commencer."}
          </p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((strategy) => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              onClick={() => handleCardClick(strategy)}
              onNewVersion={handleNewVersion}
              onDelete={handleDelete}
              parentStrategy={parentMap[strategy.id]}
            />
          ))}
        </div>
      )}

      {formOpen && (
        <StrategyForm
          strategy={editingStrategy}
          onSave={handleSave}
          onClose={() => {
            setFormOpen(false);
            setEditingStrategy(null);
          }}
        />
      )}
    </div>
  );
}