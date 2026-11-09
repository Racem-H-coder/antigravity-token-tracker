# Project History : Antigravity Token Tracker

## Date : 2026-11-09

### 🚀 Initialisation du Plugin, Déplacement sur le Bureau & Installation Complète

#### Objectif
Permettre le suivi automatique et détaillé de la consommation de tokens dans Antigravity (par jour, par heure et par projet), avec affichage dynamique au lancement d'une nouvelle fenêtre et accès rapide par bouton pendant le travail.

#### Emplacements & Intégration
- **Dossier du projet & Dépôt Git** : `C:\Users\medra\Desktop\antigravity-token-tracker`
- **Installation Plugin Antigravity** : `~/.gemini/config/plugins/antigravity-token-tracker` (Junction vers le Bureau)
- **Installation Skill Globale** : `~/.gemini/config/skills/token-tracker` (Junction vers le dossier skills)
- **Règles Globales Injectées** : `~/.gemini/config/AGENTS.md` et `~/.gemini/config/GEMINI.md`
- **Lanceur 1-clic Bureau** : `C:\Users\medra\Desktop\📊 Antigravity Tokens.bat`

#### Composants Actifs
1. **Moteur d'Analyse (`scripts/tracker.py`)** :
   - Mode lecture non-bloquante (`mode=ro`) sur SQLite et logs `transcript.jsonl`.
   - Agrégation par jour, heure et projet avec calcul des économies de cache et des coûts.
   - Dashboard HTML avec graphiques SVG interactifs et serveur live.
2. **Hook de démarrage (`hooks.json` & `scripts/session_start_hook.py`)** :
   - Déclenché à l'événement `SessionStart` à l'ouverture de chaque nouvelle fenêtre/conversation.
3. **Skill Antigravity (`skills/token-tracker/SKILL.md`)** :
   - Prise en charge des requêtes chat et de la commande `/tokens`.
4. **Dépôt Git** :
   - Initialisé sur la branche `main` dans le dossier du Bureau, prêt à être poussé sur GitHub (`Racem-H`).
