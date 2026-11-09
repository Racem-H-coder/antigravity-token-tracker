# Règle : Token Tracking & Awareness

1. **Prise en compte des Tokens :**
   - Lorsque l'utilisateur demande des informations sur sa consommation de tokens, ses coûts, ou utilise le déclencheur `/tokens`, activez la skill `token-tracker`.
   - Utilisez le script `scripts/tracker.py` pour obtenir des chiffres précis (par jour, heure et projet).
   - Fournissez toujours le lien vers le dashboard local interactif : `[📊 Dashboard des Tokens](file:///C:/Users/medra/Desktop/antigravity-token-tracker/dashboard.html)`.

2. **Démarrage de session :**
   - Le hook `SessionStart` injecte automatiquement le statut de consommation en haut de chaque nouvelle conversation.
