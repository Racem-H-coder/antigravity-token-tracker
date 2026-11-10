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

---

## Date : 2026-11-10

### ⚡ Amélioration de la Précision Temporelle & Détection Automatique du Workspace

#### Objectif & Problèmes résolus
1. **Conversion UTC vers Heure Locale** :
   - Les horodatages dans `transcript.jsonl` sont stockés au format ISO UTC (ex: `09:27:56Z`).
   - L'extraction précédente tronquait la chaîne sans conversion de fuseau horaire, créant un décalage d'1 heure avec l'heure locale et affichant 0 token pour l'heure courante.
   - Intégration de `datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone()` pour refléter exactement l'activité de l'heure locale.
2. **Détection Automatique du Projet Actif** :
   - Ajout d'un fallback automatique vers `os.getcwd()` lorsque `target_workspace` n'est pas fourni.
   - Les commandes `/tokens` ou `--markdown` affichent désormais directement les statistiques du workspace courant (`antigravity-token-tracker`).
3. **Mise à jour du Dashboard HTML** :
   - Régénération complète de `dashboard.html` avec les données temps réel actualisées.
4. **Extension Barre d'État Antigravity IDE (Bouton 1-Clic "View Usage / Tokens")** :
   - Création de l'extension IDE locale `ide-extension/` installée dans `~/.antigravity-ide/extensions`.
   - Ajout d'un bouton permanent dans la barre d'état (en bas à droite) affichant les tokens en direct et le coût.
   - Au clic : régénère et ouvre automatiquement `dashboard.html` dans le navigateur par défaut.
   - Raccourci clavier dédié configuré : `Ctrl+Alt+T`.


---

## Date : 2026-11-10 (Mise à jour Quotas 5h, Limites Hebdomadaires & Préparation Open-Source)

### 🎯 Quotas Roulants 5h, Limites Hebdomadaires (Weekly Cap) & Vue par Semaine

#### Objectifs & Nouveautés
1. **Suivi de la limite instantanée 5h (Rolling Window)** :
   - Prise en compte de la fenêtre glissante des 5 dernières heures (`now - 5h`) pour surveiller les sprints de requêtes intensives et éviter d'atteindre le seuil de limitation temporaire.
   - Calcul des tokens restants sur 5h et barre visuelle de progression.
2. **Quota Hebdomadaire (Weekly Cap) & Consommation par Semaine** :
   - Agrégation des sessions par semaine civile (du lundi au dimanche).
   - Calcul du pourcentage de la limite hebdomadaire utilisé pour chaque semaine (`% de la limite weekly`) et des tokens restants.
   - Décomposition détaillée jour par jour au sein de chaque semaine, affichant la contribution exacte de chaque jour par rapport au quota hebdomadaire global.
3. **Gestionnaire de Forfaits & Quotas (`config.json`)** :
   - Définition de profils prêts à l'emploi : `Google AI Starter`, `Google AI Pro`, `Google AI Ultra`, et `Custom`.
   - Commandes CLI dédiées : `--set-plan`, `--set-5h-quota`, `--set-weekly-quota`, `--set-daily-quota`.
   - Modale de configuration intégrée directement dans `dashboard.html` avec serveur API local (`GET /api/config` et `POST /api/config`).
4. **Extension Antigravity IDE & Bannière de Chat** :
   - Mise à jour de la barre d'état : `⚡ 5h: XXM · Hebdo: YYM restants`.
   - Tooltip complet et menu QuickPick avec changement d'abonnement en 1 clic.
   - Bannière Markdown à 4 colonnes intégrant les jauges 5h, hebdomadaire et journalière.
5. **Préparation au Dépôt Public Open-Source** :
   - Création des scripts d'installation automatique universels `install.bat` et `install.ps1`.
   - Ajout du mode démo anonymisé `--demo` pour générer un `dashboard.html` prêt pour Git, sans aucune fuite de chemins personnels ou noms de projets privés.
