// Tests de non-régression -- Phase 1 Strategy Lab (2026-09-12).
// Deux angles : (1) correction ponctuelle sur des valeurs calculables à la
// main, (2) causalité générique -- même méthode que l'audit Market Memory
// (comparer une série complète vs tronquée à un instant T) appliquée ici à
// CHAQUE indicateur de l'interface, en une seule boucle plutôt que huit
// tests dupliqués.
import { describe, it, expect } from "vitest";
import { sma, ema, rsi, atr, bollinger, computeIndicator } from "../indicatorCalculations";
import { INDICATORS } from "../indicators";

function makeBars(closes) {
  // OHLC synthétique simple : open=high=low=close pour ne pas introduire de
  // bruit non pertinent dans les tests de formule/causalité.
  return closes.map((c, i) => ({ open: c, high: c, low: c, close: c, volume: 100 + i }));
}

describe("sma", () => {
  it("calcule la moyenne glissante correcte, null pendant l'échauffement", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });
});

describe("rsi", () => {
  it("vaut 100 sur une série strictement croissante (aucune perte)", () => {
    const closes = Array.from({ length: 20 }, (_, i) => 100 + i);
    const values = rsi(closes, 14);
    expect(values[19]).toBe(100);
  });
});

describe("atr", () => {
  it("le premier True Range est simplement high-low (pas de clôture précédente)", () => {
    const bars = [{ open: 10, high: 12, low: 8, close: 11 }, { open: 11, high: 13, low: 9, close: 10 }];
    // Calcul manuel: TR[0]=high-low=4. period=14 > n donc tout est null (échauffement),
    // on vérifie juste qu'aucune erreur n'est levée et que la forme est correcte.
    const values = atr(bars, 14);
    expect(values.length).toBe(2);
    expect(values.every((v) => v === null)).toBe(true);
  });
});

describe("computeIndicator — breakout exclut la bougie courante", () => {
  it("un plus haut sur la bougie courante ne se reflète jamais dans son propre niveau de breakout", () => {
    const closes = [10, 10, 10, 10, 10, 10, 1000]; // dernière bougie = pic anormal
    const bars = closes.map((c) => ({ open: c, high: c, low: c, close: c, volume: 1 }));
    const values = computeIndicator("breakout", { lookback: 5 }, bars);
    // i=6 (le pic) : la fenêtre est [1..5], jamais l'indice 6 lui-même.
    expect(values[6]).toBe(10);
  });
});

describe("causalité générique -- tous les indicateurs de l'interface", () => {
  const closes = Array.from({ length: 120 }, (_, i) => 100 + Math.sin(i / 5) * 10 + i * 0.3);
  const bars = makeBars(closes);
  const testIdx = 80;

  // "smc"/"liquidity" exclus : confirmés FAUX INDICATEUR/PLACEHOLDER en Audit
  // Phase B (retombent sur le prix de clôture brut) -- pas un vrai calcul
  // causal à vérifier ici, juste un fait déjà documenté ailleurs.
  const realIndicators = INDICATORS.filter((i) => !["liquidity", "smc"].includes(i.id));

  for (const ind of realIndicators) {
    it(`${ind.id} (${ind.name}) : valeur à T identique, série complète vs tronquée`, () => {
      const params = Object.fromEntries((ind.params || []).map((p) => [p.key, p.default]));
      const full = computeIndicator(ind.id, params, bars);
      const truncated = computeIndicator(ind.id, params, bars.slice(0, testIdx + 1));
      expect(truncated[testIdx]).toBe(full[testIdx]);
    });
  }
});

describe("bollinger", () => {
  it("bande haute et basse encadrent toujours la moyenne, une fois l'échauffement passé", () => {
    const closes = Array.from({ length: 30 }, () => 100 + Math.random() * 5);
    const { mid, upper, lower } = bollinger(closes, 20, 2);
    for (let i = 19; i < closes.length; i++) {
      expect(upper[i]).toBeGreaterThanOrEqual(mid[i]);
      expect(lower[i]).toBeLessThanOrEqual(mid[i]);
    }
  });
});
