// Base URL du backend AlphaTrade Strategy Lab (FastAPI).
// Remplace l'ancienne logique Base44 (app_id, token dans l'URL, storage base44_*, etc.)
// qui n'a plus lieu d'être : on ne garde que l'URL du backend, configurable via
// VITE_API_BASE_URL, avec un fallback vers le serveur de dev local.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';
