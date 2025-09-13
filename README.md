# RD Monitor — mode minimal

Ce dépôt contient un unique outil autonome pour corriger les torrents Real‑Debrid bloqués en
`waiting_files_selection` en sélectionnant automatiquement les fichiers vidéo.

Composants présents
- `scripts/rd_single_fix.py` : script autonome (mode interactif, one‑shot ou daemon) qui :
	- scanne vos torrents Real‑Debrid,
	- récupère les détails d'un torrent,
	- sélectionne les fichiers vidéo (option pour inclure les sous‑titres),
	- gère les erreurs de rate‑limit (429/Retry‑After et 509) et propose une file d'attente
		persistante SQLite pour retenter automatiquement,
	- journalise les actions dans un fichier JSONL.
- `service/rd-monitor-daemon.service` : unité systemd d'exemple configurée pour lancer le script en mode
	daemon (optionnelle).
- `requirements.txt` : dépendances runtime minimales (requests).
- `dev-requirements.txt` : dépendances de développement (pytest).
# RD Monitor — exécution sans venv

Ce dépôt contient un outil autonome pour corriger les torrents Real‑Debrid en statut
`waiting_files_selection`. Le script utilise uniquement la bibliothèque standard de Python
pour les requêtes HTTP : il n'y a plus besoin d'installer `requests` ni d'utiliser un venv.

Fichiers importants
- `scripts/rd_single_fix.py` : script autonome. Arguments principaux : `--token` ou `REAL_DEBRID_TOKEN`,
  `--once`, `--daemon`, `--dry-run`, `--persist`, `--results`.
- `scripts/run_service.sh` : wrapper qui exécute le script en recherchant un Python dans cet ordre :
  `RD_VENV_PATH`, `$HOME/.venvs/rd-monitor`, `./.venv`, puis `python3` système. Utile si vous voulez
  un venv isolé mais il n'est pas requis.
- `service/rd-monitor-daemon.service` : unité systemd d'exemple qui utilise le wrapper pour démarrer le daemon.
- `requirements.txt` : vide de dépendances externes (utilise la stdlib).

Sécurité
- Ne commitez jamais votre token Real‑Debrid. Fournissez le via l'option `--token` ou la variable
  d'environnement `REAL_DEBRID_TOKEN`.

Exemples d'utilisation

Mode simulation (dry-run, aucun changement) :

```bash
./scripts/run_service.sh --once --dry-run --token "<VOTRE_TOKEN>"
```

Mode one-shot réel (effectue les sélections) :

```bash
export REAL_DEBRID_TOKEN="<VOTRE_TOKEN>"
./scripts/run_service.sh --once
```

Mode daemon (persistant, avec SQLite pour retries) :

```bash
./scripts/run_service.sh --daemon --persist data/auto_fix_state.db --results data/auto_fix_results.jsonl
```

Installation systemd (exemple pour un utilisateur `<user>`) :

```bash
sudo cp service/rd-monitor-daemon.service /etc/systemd/system/rd-monitor-daemon@<user>.service
sudo systemctl daemon-reload
sudo systemctl enable --now rd-monitor-daemon@<user>.service
```

Vérifier le service :

```bash
systemctl status rd-monitor-daemon@<user>.service
journalctl -u rd-monitor-daemon@<user>.service -f
```

Notes
- Le script fonctionne sans venv, mais si vous préférez isoler les dépendances pour d'autres outils,
  créez un venv dans `$HOME/.venvs/rd-monitor` et exportez `RD_VENV_PATH` ou laissez le wrapper le trouver.
- Si vous voulez que je retire complètement les fichiers relatifs au venv local (`.venv`) ou que j'ajoute
  un petit utilitaire d'inspection pour la base SQLite, dites‑le.


Vérifier le service et les logs :

```bash
systemctl status rd-monitor-daemon@<user>.service
journalctl -u rd-monitor-daemon@<user>.service -f
```

Fichiers de sortie
- `data/auto_fix_results.jsonl` : journal JSONL des actions (succès/échecs) — localement produit par le script.
- `data/auto_fix_state.db` : base SQLite utilisée en mode `--persist` pour mémoriser la file d'attente des retries.

Support & personnalisation
- Le script est conçu pour être simple et modulaire : vous pouvez modifier `--pause`, `--max-per-cycle` et
	les règles d'extensions pour l'adapter à votre usage.
- Si vous souhaitez que je prépare une installation systemd automatisée sur cette machine ou que je pousse
	ces changements sur le dépôt distant, dites‑le et je m'en occupe.

---
Pour toute question ou adaptation (par exemple exporter des métriques, ajouter un résumé quotidien,
ou intégrer un webhook), dites ce que vous voulez et je l'implémenterai.
