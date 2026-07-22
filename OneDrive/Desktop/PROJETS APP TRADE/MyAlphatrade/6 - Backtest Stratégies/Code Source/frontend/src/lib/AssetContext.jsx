import React, { createContext, useContext, useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";

const AssetContext = createContext(null);
const STORAGE_KEY = "alphatrade:selectedAsset";

export function AssetProvider({ children }) {
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSymbol, setSelectedSymbol] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
      return null;
    }
  });

  // Load from DB + subscribe to realtime changes
  useEffect(() => {
    let mounted = true;
    const loadAssets = async () => {
      try {
        const data = await base44.entities.TradingAsset.list("order", 500);
        if (mounted) {
          setAssets(data);
          setLoading(false);
        }
      } catch {
        if (mounted) setLoading(false);
      }
    };
    loadAssets();

    const unsubscribe = base44.entities.TradingAsset.subscribe((event) => {
      if (!mounted) return;
      if (event.type === "create") {
        setAssets((prev) => [...prev, event.data]);
      } else if (event.type === "update") {
        setAssets((prev) =>
          prev.map((a) => (a.id === event.data.id ? event.data : a))
        );
      } else if (event.type === "delete") {
        setAssets((prev) => prev.filter((a) => a.id !== event.id));
      }
    });

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  const activeAssets = assets.filter((a) => a.status === "active");
  const selectedAsset =
    activeAssets.find((a) => a.symbol === selectedSymbol) ||
    activeAssets[0] ||
    null;

  // Persist selection
  useEffect(() => {
    if (selectedAsset?.symbol) {
      try {
        localStorage.setItem(STORAGE_KEY, selectedAsset.symbol);
      } catch {}
    }
  }, [selectedAsset?.symbol]);

  // Auto-select first active if none valid
  useEffect(() => {
    if (!loading && !selectedAsset && activeAssets.length > 0) {
      setSelectedSymbol(activeAssets[0].symbol);
    }
  }, [loading, selectedAsset, activeAssets.length]);

  return (
    <AssetContext.Provider
      value={{
        assets,
        activeAssets,
        selectedSymbol,
        setSelectedSymbol,
        selectedAsset,
        loading,
      }}
    >
      {children}
    </AssetContext.Provider>
  );
}

export function useAsset() {
  const ctx = useContext(AssetContext);
  if (!ctx) throw new Error("useAsset must be used within AssetProvider");
  return ctx;
}