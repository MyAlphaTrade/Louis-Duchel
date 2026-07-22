import React from "react";
import ModulePage from "@/components/ModulePage";
import { Send, Zap, FileCheck } from "lucide-react";

const features = [
  {
    icon: Send,
    title: "Signaux BUY / SELL / WAIT",
    description: "Exportez les signaux générés par votre stratégie vers AlphaTrade automatiquement.",
  },
  {
    icon: Zap,
    title: "Envoi instantané",
    description: "Les signaux sont transmis en temps réel avec prix d'entrée, SL et TP inclus.",
  },
  {
    icon: FileCheck,
    title: "Historique des signaux",
    description: "Consultez l'historique complet de tous les signaux exportés avec leur statut.",
  },
];

export default function Signals() {
  return (
    <ModulePage
      module={5}
      title="Export vers AlphaTrade"
      description="Envoyez vos signaux de trading directement vers AlphaTrade pour exécution automatique."
      features={features}
    />
  );
}