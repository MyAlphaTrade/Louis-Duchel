import React, { createContext, useContext, useState, useEffect } from "react";
import { getProvider, getDefaultProvider, AI_PARAM_DEFAULTS } from "@/lib/aiProviders";

/**
 * AISettingsContext — Gère l'état de configuration IA de l'utilisateur.
 *
 * Stocke le fournisseur sélectionné, la clé API, le modèle et les paramètres
 * avancés (température, max tokens, top_p).
 *
 * Persistance : localStorage (simulation de stockage sécurisé).
 * Futur : les clés seront chiffrées et stockées côté serveur.
 */

const STORAGE_KEY = "alphatrade:aiSettings";
const AISettingsContext = createContext(null);

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // ignore
  }
}

function defaultSettings() {
  const provider = getDefaultProvider();
  return {
    providerId: provider.id,
    apiKey: "",
    model: provider.defaultModel,
    params: { ...AI_PARAM_DEFAULTS },
  };
}

export function AISettingsProvider({ children }) {
  const [settings, setSettings] = useState(() => {
    const saved = loadSettings();
    return saved || defaultSettings();
  });

  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  // Ensure model is valid when provider changes
  const provider = getProvider(settings.providerId);
  const effectiveSettings = provider
    ? settings
    : { ...settings, providerId: getDefaultProvider().id, model: getDefaultProvider().defaultModel };

  const updateSettings = (patch) => {
    setSettings((prev) => {
      let next = { ...prev, ...patch };
      // If provider changed, reset model to that provider's default — but only
      // clear/override values the caller didn't explicitly set in this same
      // patch (e.g. the Settings page saves providerId+model+apiKey together
      // in one call, which must not be clobbered by these defaults).
      if (patch.providerId && patch.providerId !== prev.providerId) {
        const newProvider = getProvider(patch.providerId);
        if (newProvider && !("model" in patch)) next.model = newProvider.defaultModel;
        if (!("apiKey" in patch)) next.apiKey = ""; // Clear key when switching providers
      }
      return next;
    });
  };

  const resetSettings = () => setSettings(defaultSettings());

  return (
    <AISettingsContext.Provider
      value={{
        settings: effectiveSettings,
        provider,
        updateSettings,
        resetSettings,
        isConfigured: Boolean(effectiveSettings.apiKey && effectiveSettings.apiKey.length >= 5),
      }}
    >
      {children}
    </AISettingsContext.Provider>
  );
}

export function useAISettings() {
  const ctx = useContext(AISettingsContext);
  if (!ctx) throw new Error("useAISettings must be used within AISettingsProvider");
  return ctx;
}