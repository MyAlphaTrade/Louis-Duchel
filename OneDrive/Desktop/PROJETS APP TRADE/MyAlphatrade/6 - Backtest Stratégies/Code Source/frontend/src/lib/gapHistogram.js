// Regroupe les gaps enrichis renvoyes par GET /research/gap-analysis
// (chaque gap porte deja filled/fill_minutes, calcules cote backend par
// gap_analysis.py) en buckets de temps de comblement, pour l'histogramme du
// Module 7 / Recherche. Fonction pure, aucune valeur de gap inventee ici --
// se contente de compter ce que le backend a deja mesure.

export const FILL_TIME_BUCKETS = [
  { key: "0-30m", label: "0-30m", maxMinutes: 30 },
  { key: "30-60m", label: "30-60m", maxMinutes: 60 },
  { key: "1-2h", label: "1-2h", maxMinutes: 120 },
  { key: "2-4h", label: "2-4h", maxMinutes: 240 },
  { key: "4-8h", label: "4-8h", maxMinutes: 480 },
  { key: ">8h", label: ">8h", maxMinutes: Infinity },
];

export function bucketFillTimes(gaps) {
  const counts = FILL_TIME_BUCKETS.map((b) => ({ ...b, count: 0 }));
  let neverFilled = 0;
  for (const gap of gaps) {
    if (!gap.filled) {
      neverFilled += 1;
      continue;
    }
    const bucket = counts.find((b) => gap.fill_minutes <= b.maxMinutes);
    (bucket || counts[counts.length - 1]).count += 1;
  }
  const total = gaps.length;
  const withNever = [
    ...counts.map((b) => ({ key: b.key, label: b.label, count: b.count })),
    { key: "jamais", label: "jamais", count: neverFilled },
  ];
  return withNever.map((b) => ({
    ...b,
    pct: total ? +((b.count / total) * 100).toFixed(1) : 0,
  }));
}
