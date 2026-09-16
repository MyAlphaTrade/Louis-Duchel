import React from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { base44 } from "@/api/base44Client";
import { useAuth } from "@/lib/AuthContext";
import {
  Database,
  FlaskConical,
  BarChart3,
  PlayCircle,
  Send,
  LogOut,
  ChevronRight,
  Settings,
  BrainCircuit,
  Microscope,
  Layers,
} from "lucide-react";
import AssetSelector from "@/components/AssetSelector";

const navItems = [
  { path: "/", label: "Données de marché", icon: Database, module: 1 },
  { path: "/strategies", label: "Créateur de stratégies", icon: FlaskConical, module: 2 },
  { path: "/backtesting", label: "Backtesting", icon: BarChart3, module: 3 },
  { path: "/paper-trading", label: "Paper Trading", icon: PlayCircle, module: 4 },
  { path: "/signals", label: "Export Signaux", icon: Send, module: 5 },
  { path: "/ai-designer", label: "AI Strategy Designer", icon: BrainCircuit, module: 6 },
  { path: "/research", label: "Recherche", icon: Microscope, module: 7 },
  { path: "/strategies-discovered", label: "Stratégies découvertes", icon: Layers, module: 8 },
];

// Barre laterale TOUJOURS statique, sans mode mobile/tiroir -- Strategy Lab
// n'est deployee que via la fenetre pywebview de l'app desktop (jamais un
// vrai navigateur mobile), et son min_size (1024x700) est en pixels
// PHYSIQUES : sous mise a l'echelle Windows (125%/150%, courante sur ecran
// haute densite), la largeur CSS reelle tombe sous le seuil `lg` (1024px)
// meme fenetre "grande ouverte", ce qui faisait apparaitre en meme temps la
// barre du haut reduite ET le tiroir complet superposes (Louis, 24/07/2026 :
// "boutons supprimes hors des cartes" -- en realite deux sidebars empilees).
// Une seule sidebar statique elimine la classe de bug entierement, plutot
// que de deplacer le seuil de rupture.
export default function Layout() {
  const location = useLocation();
  const { user } = useAuth();

  const handleLogout = () => {
    base44.auth.logout("/login");
  };

  return (
    <div className="flex h-screen bg-[#0a0e17] text-white overflow-hidden">
      {/* Sidebar */}
      <aside className="static inset-y-0 left-0 w-72 bg-[#0d1220] border-r border-[#1a2332] flex flex-col flex-shrink-0">
        {/* Logo */}
        <div className="p-6 pt-8 pl-8 border-b border-[#1a2332]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center overflow-hidden">
              <img src="/logo-white.png" alt="AlphaTrade" className="w-full h-full object-cover" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight font-heading text-white">
                AlphaTrade
              </h1>
              <p className="text-[11px] text-amber-400/80 font-medium tracking-widest uppercase">
                Strategy Lab
              </p>
            </div>
          </div>
        </div>

        {/* Asset selector */}
        <div className="px-4 pt-4">
          <p className="text-[10px] font-medium tracking-widest uppercase text-slate-600 mb-2 px-1">
            Actif sélectionné
          </p>
          <AssetSelector />
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`group flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                    : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"
                }`}
              >
                <span
                  className={`text-xs font-bold w-5 h-5 rounded flex items-center justify-center ${
                    isActive
                      ? "bg-amber-500/20 text-amber-400"
                      : "bg-white/5 text-slate-500 group-hover:text-slate-300"
                  }`}
                >
                  {item.module}
                </span>
                <item.icon className="w-4 h-4 flex-shrink-0" />
                <span className="flex-1">{item.label}</span>
                {isActive && (
                  <ChevronRight className="w-3.5 h-3.5 text-amber-400/60" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Administration */}
        <div className="px-4 pt-4 border-t border-[#1a2332]">
          <p className="text-[10px] font-medium tracking-widest uppercase text-slate-600 mb-2 px-1">
            Administration
          </p>
          <Link
            to="/assets"
            className={`group flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
              location.pathname === "/assets"
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"
            }`}
          >
            <Settings className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1">Gestion des actifs</span>
          </Link>
          <Link
            to="/settings"
            className={`group flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
              location.pathname === "/settings"
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"
            }`}
          >
            <BrainCircuit className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1">Paramètres IA</span>
          </Link>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[#1a2332]">
          {user?.email && (
            <p className="px-4 pb-2 text-[10px] text-slate-600 truncate" title={user.email}>
              Connecté : {user.email}
            </p>
          )}
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-4 py-3 w-full rounded-xl text-sm text-slate-500 hover:text-red-400 hover:bg-red-500/5 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            <span>Déconnexion</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}