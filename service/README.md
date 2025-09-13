Installation systemd (exemples)

1) Créez un utilisateur dédié ou utilisez votre utilisateur existant.

2) Assurez-vous que le venv est créé dans le dépôt (par ex. `.venv`) et que les dépendances sont installées :

```bash
cd ~/Projets_Github/rd-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3) Copier l'unité systemd (en tant que root) :

```bash
sudo cp service/rd-monitor-daemon.service /etc/systemd/system/rd-monitor-daemon@<user>.service
sudo systemctl daemon-reload
sudo systemctl enable --now rd-monitor-daemon@<user>.service
```

Remplacez `<user>` par votre nom d'utilisateur (par ex. `kesurof`). Le unit file utilise des chemins relatifs à `/home/<user>/Projets_Github/rd-monitor`.

4) Vérifiez le statut et les logs :

```bash
systemctl status rd-monitor-daemon@<user>.service
journalctl -u rd-monitor-daemon@<user>.service -f
```

Logrotate suggestion (facultatif) : ajoutez une rotation pour `~/Projets_Github/rd-monitor/logs/rd-monitor.log` et `~/Projets_Github/rd-monitor/data/auto_fix_results.jsonl` via logrotate pour éviter que les fichiers n'occupent trop d'espace.
