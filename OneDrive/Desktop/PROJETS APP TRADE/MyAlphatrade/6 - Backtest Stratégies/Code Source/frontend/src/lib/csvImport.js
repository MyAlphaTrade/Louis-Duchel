// Parser pour les exports historiques MT5 au format CSV (colonnes séparées
// par des tabulations). Format confirmé sur un vrai export XAUUSD M15 :
//
// <DATE>	<TIME>	<OPEN>	<HIGH>	<LOW>	<CLOSE>	<TICKVOL>	<VOL>	<SPREAD>
// 2026.06.01	00:00:00	4539.55	4546.06	4537.50	4540.85	2857	0	15
//
// <TICKVOL> est utilisé comme volume (pas <VOL>, souvent à 0 chez ce broker).

const DATE_RE = /^\d{4}\.\d{2}\.\d{2}$/;
const TIME_RE = /^\d{2}:\d{2}:\d{2}$/;

/**
 * Parse le texte brut d'un CSV MT5 en tableau de bougies
 * { timestamp, open, high, low, close, volume }.
 * Lève une Error avec un message clair (incluant le numéro de ligne) au
 * premier problème rencontré.
 */
export function parseMt5Csv(text) {
  if (!text || !text.trim()) {
    throw new Error("Le fichier est vide.");
  }

  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) {
    throw new Error("Le fichier ne contient aucune ligne de données (en-tête seule ou fichier vide).");
  }

  const header = lines[0];
  if (!header.includes("<DATE>") || !header.includes("<TIME>")) {
    throw new Error(
      "Format de fichier non reconnu : en-tête attendu <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>."
    );
  }

  const candles = [];

  for (let i = 1; i < lines.length; i++) {
    const lineNumber = i + 1; // 1-indexed, header = ligne 1
    const cols = lines[i].split("\t");
    if (cols.length < 6) {
      throw new Error(
        `Ligne ${lineNumber} invalide : ${cols.length} colonne(s) trouvée(s), au moins 6 attendues (DATE, TIME, OPEN, HIGH, LOW, CLOSE).`
      );
    }

    const [date, time, open, high, low, close, tickvol] = cols;

    if (!DATE_RE.test(date)) {
      throw new Error(`Ligne ${lineNumber} : format de date invalide "${date}" (attendu AAAA.MM.JJ).`);
    }
    if (!TIME_RE.test(time)) {
      throw new Error(`Ligne ${lineNumber} : format d'heure invalide "${time}" (attendu HH:MM:SS).`);
    }

    const o = parseFloat(open);
    const h = parseFloat(high);
    const l = parseFloat(low);
    const c = parseFloat(close);
    if ([o, h, l, c].some((v) => Number.isNaN(v))) {
      throw new Error(`Ligne ${lineNumber} : valeurs OHLC invalides (open="${open}" high="${high}" low="${low}" close="${close}").`);
    }

    const [y, m, d] = date.split(".");
    const isoTimestamp = `${y}-${m}-${d}T${time}Z`;

    candles.push({
      timestamp: isoTimestamp,
      open: o,
      high: h,
      low: l,
      close: c,
      volume: parseFloat(tickvol) || 0,
    });
  }

  if (candles.length === 0) {
    throw new Error("Aucune bougie valide trouvée dans le fichier.");
  }

  return candles;
}
