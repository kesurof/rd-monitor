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

suppose repo dans /home/$USER/scripts/rd-monitor

sudo cp scripts/service/rd-monitor.service /etc/systemd/system/rd-monitor.service
sudo sed -i "s/%i/$USER/g" /etc/systemd/system/rd-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable rd-monitor.service
sudo systemctl start rd-monitor.service
sudo systemctl status rd-monitor.service


## Détection Docker (optionnelle)

Affiche état/IP des conteneurs dont le nom contient `rdt-client` ou `debrid-media-manager`.


[6][4][17][20]

Notes d’implémentation
- Les endpoints Real‑Debrid utilisés et la nécessité d’appeler selectFiles pour démarrer le torrent sont documentés dans la doc officielle et un SDK tiers, ce que le script applique strictement [6][4].  
- La détection des conteneurs et de leur IP s’appuie sur Docker SDK pour Python, pratique pour reproduire l’approche Arr‑Monitor qui inspecte des services liés [17][20].  
- L’outil fonctionne sans dépendances « TUI » pour rester simple et portable dans SSH, mais peut être étendu avec curses/curses-menu si souhaité [7][10].
