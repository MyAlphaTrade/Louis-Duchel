/**
 * AI Provider Manager — Architecture modulaire et indépendante du fournisseur.
 *
 * Chaque fournisseur (OpenAI, Anthropic, Google Gemini, …) implémente la même
 * interface `AIProvider`. Pour ajouter un nouveau fournisseur, il suffit de
 * créer un objet respectant cette interface et de l'enregistrer via
 * `registerProvider`.
 *
 * Les appels réels passent par le backend AlphaTrade Strategy Lab
 * (POST /ai/generate) car Anthropic et OpenAI bloquent les appels directs
 * depuis un navigateur (CORS). La clé API de l'utilisateur ("bring your own
 * key") transite dans la requête à chaque appel — elle n'est jamais stockée
 * côté serveur, seulement dans le localStorage du navigateur (AISettingsContext).
 */

import { API_BASE_URL } from "@/lib/app-params";

const TOKEN_KEY = "strategylab_token";

function getAuthToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export const AI_PARAM_DEFAULTS = {
  temperature: 0.7,
  maxTokens: 2048,
  topP: 1,
};

/**
 * @typedef {Object} AIProvider
 * @property {string}  id            — identifiant unique (ex: "openai")
 * @property {string}  name          — nom d'affichage
 * @property {string}  description    — courte description
 * @property {string}  apiKeyLabel    — libellé du champ clé API
 * @property {string}  apiKeyPlaceholder
 * @property {string}  docsUrl        — où obtenir une clé
 * @property {Array<{id:string,label:string,description?:string}>} models
 * @property {string}  defaultModel
 * @property {function(object):Promise<{content:string,raw?:object}>} generate
 * @property {function(object):Promise<{ok:boolean,message:string}>} testConnection
 */

// ── Appel backend commun (proxy /ai/generate) ──────────────────────────

async function callGenerateEndpoint({ providerId, apiKey, model, systemPrompt, prompt, params }) {
  const token = getAuthToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${API_BASE_URL}/ai/generate`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        provider: providerId,
        api_key: apiKey,
        model,
        system_prompt: systemPrompt || "",
        prompt,
        params: {
          temperature: params?.temperature,
          maxTokens: params?.maxTokens,
          topP: params?.topP,
        },
      }),
    });
  } catch {
    const err = new Error("Impossible de contacter le serveur AlphaTrade. Vérifiez votre connexion.");
    err.status = 0;
    throw err;
  }

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `Erreur ${res.status} lors de l'appel à l'IA.`;
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }

  return data;
}

async function realGenerate(providerId, { prompt, systemPrompt, params, apiKey, model }) {
  const data = await callGenerateEndpoint({ providerId, apiKey, model, systemPrompt, prompt, params });
  return { content: data?.content ?? "", raw: data };
}

async function realTest(providerId, apiKey, model) {
  if (!apiKey || apiKey.length < 5) {
    return { ok: false, message: "Clé API trop courte." };
  }
  try {
    const data = await callGenerateEndpoint({
      providerId,
      apiKey,
      model,
      systemPrompt: "Tu réponds uniquement par le mot demandé, sans rien ajouter.",
      prompt: "Réponds juste OK.",
      params: { temperature: 0, maxTokens: 16, topP: 1 },
    });
    if (data?.content) {
      return { ok: true, message: "Connexion réussie." };
    }
    return { ok: true, message: "Connexion réussie (réponse vide)." };
  } catch (err) {
    return { ok: false, message: err.message || "Échec de la connexion." };
  }
}

// ── Fournisseurs enregistrés ──────────────────────────────────────────

const openaiProvider = {
  id: "openai",
  name: "OpenAI",
  description: "GPT-4o, GPT-4 Turbo et autres modèles OpenAI.",
  apiKeyLabel: "Clé API OpenAI",
  apiKeyPlaceholder: "sk-…",
  docsUrl: "https://platform.openai.com/api-keys",
  // NOTE: ces IDs de modèles OpenAI n'ont pas été revérifiés contre le
  // catalogue actuel — à confirmer avant un usage en production.
  models: [
    { id: "gpt-4o", label: "GPT-4o", description: "Modèle le plus avancé, multimodal" },
    { id: "gpt-4o-mini", label: "GPT-4o mini", description: "Rapide et économique" },
    { id: "gpt-4-turbo", label: "GPT-4 Turbo", description: "Haute performance" },
  ],
  defaultModel: "gpt-4o",

  async generate({ prompt, systemPrompt, params, apiKey, model }) {
    return realGenerate("openai", { prompt, systemPrompt, params, apiKey, model: model || this.defaultModel });
  },

  async testConnection({ apiKey, model }) {
    return realTest("openai", apiKey, model || this.defaultModel);
  },
};

const anthropicProvider = {
  id: "anthropic",
  name: "Anthropic",
  description: "Claude Sonnet, Opus et Haiku.",
  apiKeyLabel: "Clé API Anthropic",
  apiKeyPlaceholder: "sk-ant-…",
  docsUrl: "https://console.anthropic.com/settings/keys",
  models: [
    { id: "claude-sonnet-5", label: "Claude Sonnet 5", description: "Équilibré, excellent en raisonnement" },
    { id: "claude-opus-4-8", label: "Claude Opus 4.8", description: "Le plus puissant" },
    { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5", description: "Rapide et économique" },
  ],
  defaultModel: "claude-sonnet-5",

  async generate({ prompt, systemPrompt, params, apiKey, model }) {
    return realGenerate("anthropic", { prompt, systemPrompt, params, apiKey, model: model || this.defaultModel });
  },

  async testConnection({ apiKey, model }) {
    return realTest("anthropic", apiKey, model || this.defaultModel);
  },
};

const geminiProvider = {
  id: "gemini",
  name: "Google Gemini",
  description: "Gemini 1.5 Pro et Flash par Google.",
  apiKeyLabel: "Clé API Google AI",
  apiKeyPlaceholder: "AIza…",
  docsUrl: "https://aistudio.google.com/app/apikey",
  models: [
    { id: "gemini-1.5-pro", label: "Gemini 1.5 Pro", description: "Contexte très long, multimodal" },
    { id: "gemini-1.5-flash", label: "Gemini 1.5 Flash", description: "Rapide et économique" },
  ],
  defaultModel: "gemini-1.5-pro",

  // Gemini n'est pas encore branché côté backend (/ai/generate ne supporte
  // que "anthropic" et "openai" pour l'instant) — reste simulé.
  async generate({ prompt, systemPrompt, params }) {
    return simulateGenerate("gemini", { prompt, systemPrompt, params });
  },

  async testConnection({ apiKey }) {
    return simulateTest("gemini", apiKey);
  },
};

// ── Registre interne ──────────────────────────────────────────────────

const registry = new Map();
[openaiProvider, anthropicProvider, geminiProvider].forEach((p) => registry.set(p.id, p));

export function registerProvider(provider) {
  if (!provider?.id) throw new Error("Provider must have an id");
  registry.set(provider.id, provider);
}

export function getProvider(id) {
  return registry.get(id);
}

export function getAllProviders() {
  return Array.from(registry.values());
}

export function getDefaultProvider() {
  return openaiProvider;
}

// ── Simulateur (encore utilisé par Gemini, non branché) ────────────────

function simulateGenerate(providerId, { prompt, systemPrompt, params }) {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        content: `Réponse simulée (${providerId}) — Analyse de votre idée en cours…`,
        raw: { provider: providerId, simulated: true, params },
      });
    }, 800);
  });
}

function simulateTest(providerId, apiKey) {
  return new Promise((resolve) => {
    setTimeout(() => {
      if (!apiKey || apiKey.length < 5) {
        resolve({ ok: false, message: "Clé API trop courte (simulation)." });
      }
      resolve({ ok: true, message: `Connexion simulée réussie (${providerId}).` });
    }, 600);
  });
}
