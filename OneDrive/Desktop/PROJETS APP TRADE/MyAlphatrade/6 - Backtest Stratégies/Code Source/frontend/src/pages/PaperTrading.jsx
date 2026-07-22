import React from "react";
import ModulePage from "@/components/ModulePage";
import { Wallet, Activity, Clock } from "lucide-react";

const features = [
  {
    icon: Wallet,
    title: "Portefeuille virtuel",
    description: "Tradez avec un capital fictif pour tester vos stratégies sans aucun risque réel.",
  },
  {
    icon: Activity,
    title: "Exécution en temps réel",
    description: "Les signaux de votre stratégie s'exécutent automatiquement sur le marché live.",
  },
  {
    icon: Clock,
    title: "Historique des trades",
    description: "Suivez chaque trade papier avec entrée, sortie, P&L et statistiques globales.",
  },
];

export default function PaperTrading() {
  return (
    <ModulePage
      module={4}
      title="Paper Trading"
      description="Testez vos stratégies en conditions réelles de marché, sans risquer de capital."
      features={features}
    />
  );
}