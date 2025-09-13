# RD Monitor

Outil terminal pour Real-Debrid qui corrige automatiquement les torrents bloqués en `waiting_files_selection` en ne sélectionnant que les fichiers vidéo, avec monitoring continu, venv, logs, et intégration Docker optionnelle.

## Installation

git clone https://github.com/kesurof/rd-monitor.git
cd rd-monitor
chmod +x scripts/install-rd.sh
./scripts/install-rd.sh
source ~/.bashrc
rd-monitor


## Utilisation rapide

- Menu: `rd-monitor`
- Monitoring direct: `rd-monitor --monitor`
- Lister: `rd-monitor --list`
- Fix ID: `rd-monitor --fix <TORRENT_ID>`

Renseigner le token via le menu « Configurer le token » ou via `.env` (`REAL_DEBRID_TOKEN=`).

## Configuration

- `.env`: REAL_DEBRID_TOKEN, VIDEO_EXTENSIONS, INCLUDE_SUBTITLES, CHECK_INTERVAL_SECONDS, LOG_LEVEL
- `config/config.yaml.local`: surcouche persistante

## Fonctionnement

- RD API: `GET /torrents`, `GET /torrents/info/{id}`, `POST /torrents/selectFiles/{id}` pour lever l’état et démarrer [Doc RD].
- Filtrage: `.mkv,.mp4,.avi,.mov,.m4v` par défaut; option d’inclure `.srt/.ass`.

## Service systemd (optionnel)

Le projet fournit désormais un démon principal `scripts/run_daemon_fix.py` et une unité systemd
prête à l'emploi `service/rd-monitor-daemon.service` (plus simple et plus robuste que les vieux
fichiers dans `scripts/service/`).

Exemple d'installation (remplacez <user> par votre nom d'utilisateur) :

1. Créez et activez un environnement virtuel et installez les dépendances :

```bash
cd ~/Projets_Github/rd-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copier l'unité systemd et activer le service pour votre utilisateur :

```bash
sudo cp service/rd-monitor-daemon.service /etc/systemd/system/rd-monitor-daemon@<user>.service
sudo systemctl daemon-reload
sudo systemctl enable --now rd-monitor-daemon@<user>.service
```

3. Vérifier le statut et suivre les logs :

```bash
systemctl status rd-monitor-daemon@<user>.service
journalctl -u rd-monitor-daemon@<user>.service -f
```


## Détection Docker (optionnelle)

Affiche état/IP des conteneurs dont le nom contient `rdt-client` ou `debrid-media-manager`.


[6][4][17][20]

Notes d’implémentation
- Les endpoints Real‑Debrid utilisés et la nécessité d’appeler selectFiles pour démarrer le torrent sont documentés dans la doc officielle et un SDK tiers, ce que le script applique strictement [6][4].  
- La détection des conteneurs et de leur IP s’appuie sur Docker SDK pour Python, pratique pour reproduire l’approche Arr‑Monitor qui inspecte des services liés [17][20].  
- L’outil fonctionne sans dépendances « TUI » pour rester simple et portable dans SSH, mais peut être étendu avec curses/curses-menu si souhaité [7][10].

## Changements récents

- Suppressions : `scripts/run_mass_fix.py` et `scripts/find_waiting_by_info.py` ont été retirés — leurs
	fonctionnalités sont maintenant couvertes par le démon `scripts/run_daemon_fix.py` et par
	`scripts/inspect_waiting.py` pour les inspections manuelles.
- Le fichier `scripts/service/rd-monitor.service` (dupliqué) a été supprimé. Conservez
	`service/rd-monitor-daemon.service` qui est l'unité recommandée.

Pourquoi : consolidation pour réduire la surface de maintenance et éviter les doublons. Le démon
utilise une file d'attente SQLite (data/auto_fix_state.db) et journalise les résultats dans
`data/auto_fix_results.jsonl`.

Si vous souhaitez rétablir un script supprimé ou extraire une partie de son comportement,
dites-le et je peux restaurer ou extraire le fragment concerné.
