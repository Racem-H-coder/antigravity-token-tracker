---
name: token-tracker
description: >-
  Suivi et analyse en temps réel de la consommation de tokens et des quotas Antigravity (limite 5h glissante, plafond weekly, jour et projets).
  Permet d'afficher un rapport détaillé, de générer un dashboard HTML interactif ou d'inspecter les coûts.
---

# Antigravity Token Tracker Skill

Cette skill permet à Antigravity d'analyser, suivre et afficher en temps réel la consommation exacte de tokens (Input, Output, Cache, Coûts) ainsi que les quotas d'abonnement :
- **Limite instantanée 5h glissante** (Sprint capacity Google AI Pro / Ultra)
- **Plafond hebdomadaire (Weekly Cap)** et pourcentage utilisé par semaine et par jour
- **Consommation par projet et par heure**

---

## 🎯 Quand utiliser cette skill ?

- L'utilisateur tape `/tokens` ou demande « combien de tokens me reste-t-il ? ».
- L'utilisateur s'informe sur sa limite 5h ou son quota hebdomadaire / journalier.
- L'utilisateur veut connaître sa consommation aujourd'hui, cette semaine ou par heure.
- L'utilisateur souhaite comparer la consommation de tokens entre différents projets / dossiers de travail.
- L'utilisateur demande d'ouvrir ou rafraîchir le dashboard interactif.

---

## 🚀 Étape 1 : Obtenir les statistiques en direct

Pour générer le rapport le plus récent à partir de la base SQLite et des fichiers `transcript.jsonl` :

```powershell
python "C:\Users\medra\Desktop\antigravity-token-tracker\scripts\tracker.py" --markdown
```

Ou pour un format JSON complet :
```powershell
python "C:\Users\medra\Desktop\antigravity-token-tracker\scripts\tracker.py" --json
```

---

## 📊 Étape 2 : Présenter les résultats à l'utilisateur

1. **Format Markdown synthétique** :
   Présentez toujours les 4 indicateurs clés :
   - **Aujourd'hui** : Total tokens, nombre d'appels, coût estimé en USD.
   - **Dernière heure** : Pic d'activité récent.
   - **Projet Actuel** : Tokens consommés sur le workspace actif.
   - **Optimisation Cache** : Taux d'utilisation du Context Caching (en %).

2. **Lien vers le Dashboard** :
   Incluez toujours le lien direct cliquable vers le dashboard graphique local :
   `[📊 Ouvrir le Dashboard Graphique Complet](file:///C:/Users/medra/Desktop/antigravity-token-tracker/dashboard.html)`

---

## 🌐 Étape 3 : Lancer le Serveur Live (Optionnel)

Si l'utilisateur souhaite un dashboard web avec rechargement automatique dans son navigateur :
```powershell
python "C:\Users\medra\Desktop\antigravity-token-tracker\scripts\tracker.py" --serve
```
Cela démarre un serveur local sur `http://localhost:8765` et ouvre automatiquement le navigateur web.
