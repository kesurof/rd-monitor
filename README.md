# rd-monitor — outil minimal pour corriger les torrents Real‑Debrid

Ce dépôt contient un petit outil autonome (un seul script) pour détecter et corriger
les torrents Real‑Debrid en statut `waiting_files_selection` en sélectionnant
automatiquement les fichiers vidéo.

Principes et objectifs
- Script simple, sans dépendances externes (utilise la bibliothèque standard de Python).
- Mode "collect then process": possibilité de collecter d'abord tous les IDs candidats,
  puis de les corriger lentement pour éviter les bursts et les rate‑limits.
- File persistante SQLite optionnelle pour gérer les retries et répartir les sélections
  dans le temps (utile pour des milliers de torrents).

Fichiers importants
- `scripts/rd_single_fix.py` : script autonome. C'est l'outil principal.
- `scripts/run_service.sh` : petit wrapper pour lancer le script avec le Python approprié.
- `service/rd-monitor-daemon.service` : exemple d'unité systemd.
- `data/auto_fix_results.jsonl` : (éventuel) journal JSONL des actions du script.
- `data/auto_fix_state.db` : (éventuel) base SQLite contenant la table `retries`.

Sécurité
- Ne commitez jamais votre token Real‑Debrid.
- Fournissez le token via l'option `--token` ou via la variable d'environnement
  `REAL_DEBRID_TOKEN`.

Usage général

Le script principal est `scripts/rd_single_fix.py`.
Il fournit plusieurs modes d'utilisation : collecte (collect-ids), traitement (process-ids / enqueue),
mode one-shot (`--once`) et mode daemon (`--daemon`).

Options principales

Toutes les options suivantes sont disponibles dans `scripts/rd_single_fix.py` :

- --token <token>
  - Token Real‑Debrid (optionnel si `REAL_DEBRID_TOKEN` est défini en variable d'environnement).

- --video-exts <ext,ext,...>
  - Liste séparée par des virgules d'extensions considérées comme vidéos.
  - Par défaut : .mkv,.mp4,.avi,.mov,.m4v

- --include-subs
  - Sélectionne aussi les fichiers de sous‑titres (.srt, .ass, .vtt) si présents.

- --pause <float>
  - Pause (en secondes) entre deux opérations de selection pour être plus "gentil" avec l'API.
  - Défaut : 1.5

- --page-limit <int>
  - Nombre de torrents par page demandé à l'API (max 5000).
  - Défaut : 5000

- --max-pages <int>
  - Limite du nombre de pages à parcourir (0 ou <0 = illimité).
  - Défaut : 0 (illimité)

- --max-per-cycle <int>
  - Nombre maximum d'items à traiter par cycle (0 ou <0 = illimité).
  - Défaut : 200

- --results <path>
  - Chemin vers le fichier JSONL où les résultats d'actions sont appendus.
  - Défaut : data/auto_fix_results.jsonl

- --dry-run
  - Mode simulation : n'appelle pas réellement `select_files`.

- --persist <db_path>
  - Active la persistence SQLite et utilise la base fournie pour la file de retries.
  - Exemple : --persist data/auto_fix_state.db

- --info-pause <float>
  - Pause (en secondes) après chaque appel `get_torrent_info` pour réduire la charge.
  - Défaut : 0.5

- --info-cache-ttl <seconds>
  - Durée (en secondes) de cache en mémoire pour les infos de torrent (évite des relectures répétées).
  - Défaut : 300

- --collect-ids <path>
  - Parcourt l'ensemble des torrents et écrit les IDs candidats (un par ligne) dans le fichier fourni.
  - Mode collect-only : n'effectue aucune sélection.

- --process-ids <path>
  - Lit un fichier d'IDs (un par ligne) et les traite séquentiellement.
  - Utile pour relancer une liste collectée localement.

- --enqueue
  - À utiliser avec --process-ids : au lieu d'essayer de sélectionner immédiatement, ajoute les IDs
    dans la file SQLite (--persist doit être fourni) espacés de `--process-delay` secondes.

- --process-delay <seconds>
  - Espacement (en secondes) utilisé lorsque vous enqueuez des IDs (default: 60).

- --max-selects-per-minute <int>
  - Cap global de nombre d'appels `select_files` par minute (0 = pas de cap).
  - Défaut : 60

- --list-queue
  - Affiche le contenu (sommaire) de la table `retries` de la DB SQLite et sort.
  - Utile pour vérifier le nombre d'éléments en attente et leur `next_try`.

- --once
  - Faire une seule passe/scan puis sortir.

- --daemon
  - Mode persistant : effectue des cycles réguliers et utilise la DB `--persist` pour gérer les retries.

- --cycle-interval <seconds>
  - Intervalle en secondes entre deux cycles en mode daemon.
  - Défaut : 3600

Exemples de commandes

1) Simulation rapide (aucune modification) :

```bash
./scripts/run_service.sh --once --dry-run --token "<VOTRE_TOKEN>"
```

2) One-shot réel (exécuter immédiatement) :

```bash
export REAL_DEBRID_TOKEN="<VOTRE_TOKEN>"
./scripts/run_service.sh --once
```

3) Collecter tous les IDs candidats dans un fichier (sans les modifier) :

```bash
./scripts/run_service.sh --collect-ids candidates.txt --token "<VOTRE_TOKEN>"
# candidates.txt contiendra un ID par ligne
```

4) Traiter un fichier d'IDs lentement (sélection immédiate, utile pour tests) :

```bash
./scripts/run_service.sh --process-ids candidates.txt --token "<VOTRE_TOKEN>"
```

5) Enqueuer un gros lot pour traitement différé (préférable pour 10k+ torrents) :

```bash
# Enqueue écrit les IDs dans la DB SQLite espacés par --process-delay
./scripts/run_service.sh --process-ids candidates.txt --enqueue --persist data/auto_fix_state.db --process-delay 30
```

6) Lancer le daemon qui consomme progressivement la file SQLite :

```bash
./scripts/run_service.sh --daemon --persist data/auto_fix_state.db --results data/auto_fix_results.jsonl --token "<VOTRE_TOKEN>"
```

7) Inspecter la file SQLite (sans token nécessaire) :

```bash
./scripts/rd_single_fix.py --list-queue
# ou si votre DB est ailleurs :
./scripts/rd_single_fix.py --persist data/auto_fix_state.db --list-queue
```

Conseils de bonne pratique

- Workflow recommandé pour grandes quantités (10k+ torrents) :
  1) `--collect-ids` pour exporter la liste complète des candidats.
  2) Revérifier / filtrer localement si besoin.
  3) `--process-ids --enqueue --persist data/auto_fix_state.db --process-delay 30` pour répartir les sélections dans le temps.
  4) Lancer `--daemon` sur une machine avec le token pour consommer la file à un rythme contrôlé.

- Ajustez `--process-delay`, `--pause`, `--info-pause` et `--max-selects-per-minute` pour réduire
  le risque d'atteindre des limites 429/509.

- `--dry-run` est utile pour confirmer que la logique de détection identifie bien les fichiers souhaités.

Notes techniques rapides

- Le script communique avec l'API Real‑Debrid et essaie d'envoyer la sélection sous la forme
  `application/x-www-form-urlencoded` avec `files=1,3,5` (CSV) qui a montré moins de rejets
  par l'API que d'autres encodages.
- Gestion de rate-limits : le script respecte `Retry-After` sur 429 quand fourni, applique un backoff
  et détecte des 509 pour déclencher des pauses/retours en file.
- La table SQLite `retries` contient au moins : id (tid), payload JSON, attempts, next_try (timestamp).

Besoin d'aide ?

Si vous voulez que j'ajoute :
- une sortie JSON pour `--list-queue`,
- un utilitaire `--purge-queue` ou `--retry-now <id>`,
- ou des métriques / export Prometheus,
 dites lequel et je l'implémenterai.
