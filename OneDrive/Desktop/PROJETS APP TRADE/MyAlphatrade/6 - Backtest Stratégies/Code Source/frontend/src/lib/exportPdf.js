import { jsPDF } from "jspdf";
import html2canvas from "html2canvas";

function formatDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("fr-FR", { day: "2-digit", month: "long", year: "numeric" });
}

function formatDateTime(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export async function exportBacktestPDF(results, strategy, asset, config) {
  const m = results.metrics;
  const trades = results.trades;
  const pdf = new jsPDF("p", "mm", "a4");
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const margin = 14;
  let y = margin;

  // ── Header ──
  pdf.setFillColor(10, 14, 23);
  pdf.rect(0, 0, pageW, 28, "F");
  pdf.setTextColor(245, 158, 11);
  pdf.setFontSize(18);
  pdf.setFont("helvetica", "bold");
  pdf.text("AlphaTrade Strategy Lab", margin, 12);
  pdf.setFontSize(10);
  pdf.setTextColor(100, 116, 139);
  pdf.setFont("helvetica", "normal");
  pdf.text("Rapport de Backtesting", margin, 18);
  pdf.setFontSize(8);
  pdf.text(`Généré le ${formatDate(new Date())}`, pageW - margin - 50, 18);
  y = 36;

  // ── Strategy info ──
  pdf.setFontSize(14);
  pdf.setFont("helvetica", "bold");
  pdf.setTextColor(30, 41, 59);
  pdf.text(strategy.name, margin, y);
  y += 6;
  pdf.setFontSize(9);
  pdf.setFont("helvetica", "normal");
  pdf.setTextColor(100, 116, 139);
  pdf.text(`${asset.symbol} · ${config.timeframe} · ${results.bars} bars · ${formatDate(config.startDate)} → ${formatDate(config.endDate)}`, margin, y);
  y += 8;

  // Config badges
  pdf.setFillColor(245, 247, 250);
  const badges = [
    `Spread ${config.spread}p`,
    `Commission $${config.commission}/lot`,
    `Slippage ${config.slippage}p`,
    `Levier 1:${config.leverage}`,
    `Risque ${config.riskPerTrade}%`,
    `Capital $${config.initialCapital}`,
  ];
  let badgeX = margin;
  badges.forEach((b) => {
    const w = pdf.getTextWidth(b) + 8;
    pdf.roundedRect(badgeX, y - 4, w, 6, 1, 1, "F");
    pdf.setTextColor(71, 85, 105);
    pdf.setFontSize(8);
    pdf.text(b, badgeX + 4, y);
    badgeX += w + 3;
  });
  y += 12;

  // ── Summary metrics (2 columns) ──
  pdf.setDrawColor(226, 232, 240);
  pdf.setFillColor(248, 250, 252);
  pdf.roundedRect(margin, y, pageW - margin * 2, 48, 2, 2, "F");
  pdf.setFontSize(11);
  pdf.setFont("helvetica", "bold");
  pdf.setTextColor(30, 41, 59);
  pdf.text("Performances", margin + 4, y + 6);
  y += 12;

  const metrics = [
    ["Capital initial", `$${m.initialCapital.toLocaleString()}`],
    ["Capital final", `$${m.finalEquity.toLocaleString()}`],
    ["Profit net", `${m.netProfit >= 0 ? "+" : ""}$${m.netProfit.toLocaleString()}`],
    ["Rendement", `${m.returnPct >= 0 ? "+" : ""}${m.returnPct}%`],
    ["Trades totaux", `${m.totalTrades}`],
    ["Taux de réussite", `${m.winRate}%`],
    ["Profit Factor", `${m.profitFactor}`],
    ["Drawdown max", `${m.maxDrawdown}%`],
    ["Espérance", `$${m.expectancy}`],
    ["Ratio G/P", `${m.winLossRatio}`],
    ["Gain moyen", `$${m.avgWin}`],
    ["Perte moyenne", `$${m.avgLoss}`],
  ];

  const colW = (pageW - margin * 2 - 8) / 2;
  metrics.forEach((metric, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = margin + 4 + col * colW;
    const rowY = y + row * 7;
    pdf.setFontSize(8);
    pdf.setFont("helvetica", "normal");
    pdf.setTextColor(100, 116, 139);
    pdf.text(metric[0], x, rowY);
    pdf.setFont("helvetica", "bold");
    pdf.setTextColor(30, 41, 59);
    pdf.text(metric[1], x + colW - 30, rowY);
  });
  y += 48;

  // ── Trade table ──
  y += 6;
  pdf.setFontSize(11);
  pdf.setFont("helvetica", "bold");
  pdf.setTextColor(30, 41, 59);
  pdf.text("Journal des opérations", margin, y);
  y += 6;

  const tableHeaders = ["#", "Dir", "Entrée", "Px Entrée", "Px Sortie", "Lots", "Motif", "P&L"];
  const colWidths = [10, 14, 30, 26, 26, 16, 18, 26];
  const tableX = margin;

  // Header row
  pdf.setFillColor(13, 18, 32);
  pdf.rect(tableX, y - 4, colWidths.reduce((a, b) => a + b, 0), 6, "F");
  pdf.setFontSize(7);
  pdf.setFont("helvetica", "bold");
  pdf.setTextColor(148, 163, 184);
  let cx = tableX + 2;
  tableHeaders.forEach((h, i) => {
    pdf.text(h, cx, y);
    cx += colWidths[i];
  });
  y += 6;

  // Trade rows
  pdf.setFont("helvetica", "normal");
  pdf.setFontSize(7);
  const maxRows = Math.min(trades.length, 25);
  for (let i = 0; i < maxRows; i++) {
    const t = trades[i];
    if (y > pageH - 20) {
      pdf.addPage();
      y = margin;
    }
    const isWin = t.profit > 0;
    const row = [
      `${i + 1}`,
      t.direction,
      formatDateTime(t.entry_time),
      t.entry_price?.toFixed(4) || "—",
      t.exit_price?.toFixed(4) || "—",
      t.volume?.toFixed(2) || "—",
      t.close_reason || "—",
      `${isWin ? "+" : ""}$${(t.profit || 0).toFixed(2)}`,
    ];
    cx = tableX + 2;
    pdf.setTextColor(isWin ? 16 : 225, isWin ? 122 : 69, isWin ? 87 : 69);
    row.forEach((cell, j) => {
      pdf.text(cell, cx, y);
      cx += colWidths[j];
    });
    pdf.setDrawColor(226, 232, 240);
    pdf.line(tableX, y + 1, tableX + colWidths.reduce((a, b) => a + b, 0), y + 1);
    y += 5;
  }

  if (trades.length > maxRows) {
    y += 4;
    pdf.setFontSize(8);
    pdf.setTextColor(100, 116, 139);
    pdf.text(`... et ${trades.length - maxRows} trades supplémentaires (voir l'export CSV).`, margin, y);
  }

  // ── Footer ──
  const pageCount = pdf.internal.getNumberOfPages();
  for (let p = 1; p <= pageCount; p++) {
    pdf.setPage(p);
    pdf.setFontSize(7);
    pdf.setTextColor(148, 163, 184);
    pdf.text("AlphaTrade Strategy Lab — Rapport confidentiel", margin, pageH - 6);
    pdf.text(`${p} / ${pageCount}`, pageW - margin - 10, pageH - 6);
  }

  pdf.save(`backtest_${strategy.name}_${asset.symbol}_${Date.now()}.pdf`);
}