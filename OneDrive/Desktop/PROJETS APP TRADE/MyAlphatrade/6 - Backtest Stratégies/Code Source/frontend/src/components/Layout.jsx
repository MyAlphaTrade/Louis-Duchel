import React, { useState } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { base44 } from "@/api/base44Client";
import {
  Database,
  FlaskConical,
  BarChart3,
  PlayCircle,
  Send,
  Menu,
  X,
  LogOut,
  ChevronRight,
  Settings,
  BrainCircuit,
} from "lucide-react";
import AssetSelector from "@/components/AssetSelector";

const navItems = [
  { path: "/", label: "Données de marché", icon: Database, module: 1 },
  { path: "/strategies", label: "Créateur de stratégies", icon: FlaskConical, module: 2 },
  { path: "/backtesting", label: "Backtesting", icon: BarChart3, module: 3 },
  { path: "/paper-trading", label: "Paper Trading", icon: PlayCircle, module: 4 },
  { path: "/signals", label: "Export Signaux", icon: Send, module: 5 },
  { path: "/ai-designer", label: "AI Strategy Designer", icon: BrainCircuit, module: 6 },
];

export default function Layout() {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleLogout = () => {
    base44.auth.logout("/login");
  };

  return (
    <div className="flex h-screen bg-[#0a0e17] text-white overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-40 w-72 bg-[#0d1220] border-r border-[#1a2332] flex flex-col transform transition-transform duration-300 ease-out ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        {/* Logo */}
        <div className="p-6 border-b border-[#1a2332]">
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
                onClick={() => setSidebarOpen(false)}
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
            onClick={() => setSidebarOpen(false)}
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
            onClick={() => setSidebarOpen(false)}
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
        {/* Top bar mobile */}
        <header className="lg:hidden flex items-center justify-between px-4 py-3 bg-[#0d1220] border-b border-[#1a2332]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 rounded-lg hover:bg-white/5 text-slate-400"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center overflow-hidden">
              <img src="/logo-white.png" alt="AlphaTrade" className="w-full h-full object-cover" />
            </div>
            <span className="font-bold text-sm">AlphaTrade</span>
          </div>
          <div className="w-9" />
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}