// Shim de compatibilité : les pages portées importent `useToast` depuis
// "@/components/ui/use-toast" (ancienne convention shadcn/ui), alors que la CLI
// shadcn actuelle génère ce hook dans "@/hooks/use-toast". On ré-exporte
// simplement pour éviter de modifier les fichiers portés.
export { useToast, toast } from "@/hooks/use-toast";
