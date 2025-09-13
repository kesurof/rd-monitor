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

Principes de sécurité
- Ne stockez jamais votre token Real‑Debrid dans le dépôt. Utilisez soit la variable d'environnement
	`REAL_DEBRID_TOKEN`, soit le fichier `.env` (ignoré par Git).

Isolation de l'environnement Python (recommandé)

Pour éviter d'interférer avec un venv existant dans le dépôt, le projet fournit un petit wrapper
`scripts/run_service.sh` qui recherche un environnement isolé dans l'ordre suivant :

1. la variable d'environnement `RD_VENV_PATH` (chemin vers l'exécutable Python dans un venv),
2. `$HOME/.venvs/rd-monitor/bin/python` (emplacement recommandé pour un venv utilisateur),
3. `./.venv/bin/python` (venv local au projet si présent),
4. `python3` système.

Créez un venv isolé recommandé :

```bash
python3 -m venv ~/.venvs/rd-monitor
source ~/.venvs/rd-monitor/bin/activate
pip install -r requirements.txt
```

Ensuite, soit exportez `RD_VENV_PATH` :

```bash
export RD_VENV_PATH="$HOME/.venvs/rd-monitor/bin/python"
```

soit laissez le wrapper le découvrir automatiquement.

Installation rapide
1. Clonez le dépôt et placez‑vous dedans :

```bash
git clone https://github.com/kesurof/rd-monitor.git
cd rd-monitor
```


2. Créez un environnement Python (ex. local ou recommandé ~/.venvs/rd-monitor) et installez les dépendances :

```bash
# exemple : venv local
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ou venv utilisateur recommandé
python3 -m venv ~/.venvs/rd-monitor
source ~/.venvs/rd-monitor/bin/activate
pip install -r requirements.txt
```

3. Exportez votre token (ou placez‑le dans `.env`) :

```bash
export REAL_DEBRID_TOKEN="<votre_token>"
```

Utilisation du script

Mode one‑shot (analyse et tentative de correction une seule fois) :

```bash
.venv/bin/python scripts/rd_single_fix.py --once
```

Mode simulation (dry run) : n'exécute pas `selectFiles`, utile pour vérifier quels torrents seraient visés :

```bash
.venv/bin/python scripts/rd_single_fix.py --once --dry-run
```

Mode daemon (persistant, utilise SQLite pour retries) :

Utilisez de préférence le wrapper `scripts/run_service.sh` pour démarrer le script avec l'environnement isolé découvert :

```bash
scripts/run_service.sh --daemon --persist data/auto_fix_state.db --results data/auto_fix_results.jsonl
```

ou si vous utilisez un venv local :

```bash
.venv/bin/python scripts/rd_single_fix.py --daemon --persist data/auto_fix_state.db --results data/auto_fix_results.jsonl
```

Options importantes
- `--video-exts` : liste séparée par des virgules d'extensions vidéo à sélectionner (par défaut `.mkv,.mp4,.avi,.mov,.m4v`).
- `--include-subs` : inclure également les fichiers de sous‑titres (.srt, .ass).
- `--pause` : pause en secondes entre sélections pour limiter le rythme des appels API.
- `--max-per-cycle` : nombre maximal d'éléments traités par cycle.
- `--cycle-interval` : intervalle (en s) entre deux cycles en mode daemon.

Systemd (exemple)

L'unité fournie `service/rd-monitor-daemon.service` utilise désormais le wrapper `scripts/run_service.sh`.
Pour l'installer pour votre utilisateur (<user>) :

```bash
sudo cp service/rd-monitor-daemon.service /etc/systemd/system/rd-monitor-daemon@<user>.service
sudo systemctl daemon-reload
sudo systemctl enable --now rd-monitor-daemon@<user>.service
```

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
