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

Installation rapide
1. Clonez le dépôt et placez‑vous dedans :

```bash
git clone https://github.com/kesurof/rd-monitor.git
cd rd-monitor
```

2. Créez un environnement Python et installez les dépendances :

```bash
python3 -m venv .venv
source .venv/bin/activate
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

L'unité fournie `service/rd-monitor-daemon.service` pointe par défaut vers l'environnement virtuel
et le script. Pour l'installer pour votre utilisateur (<user>) :

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
