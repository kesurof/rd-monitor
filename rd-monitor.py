#!/usr/bin/env python3
import os
import sys
import time
import threading
import argparse
import logging
from pathlib import Path

from rd_lib.config import load_config, save_local
from rd_lib.logger import setup_logger
from rd_lib.rd_api import RealDebridAPI
from rd_lib.rd_logic import fix_one
from rd_lib.docker_utils import list_containers

BANNER = "RD Monitor - Sélection auto vidéos (Real-Debrid)"

def print_menu():
    print("\n" + BANNER)
    print("1) Lancer le monitoring continu")
    print("2) Fixer un torrent par ID")
    print("3) Lister torrents (page 1)")
    print("4) Configurer le token/API et extensions")
    print("5) Infos Docker (optionnel)")
    print("6) Voir le log en temps réel")
    print("7) Quitter")

def tail_log(log_file):
    print(f"--- Tailing {log_file} (Ctrl+C pour quitter) ---")
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            print(line, end="")

def monitor_loop(cfg):
    api = RealDebridAPI(cfg["real_debrid"]["token"])
    interval = int(cfg["monitoring"]["check_interval"])
    exts = [e.lower() for e in cfg["real_debrid"]["video_extensions"]]
    include_subs = bool(cfg["real_debrid"]["include_subtitles"])
    log = logging.getLogger("rd.monitor")

    while True:
        try:
            page = 1
            processed = 0
            while True:
                items = api.get_torrents(page=page, limit=100)
                if not items:
                    break
                for t in items:
                    tid = t.get("id")
                    status = t.get("status")
                    if status == "waiting_files_selection":
                        res = fix_one(api, tid, exts, include_subs)
                        log.info(f"Fix {tid}: {res}")
                        processed += 1
                if len(items) < 100:
                    break
                page += 1
            log.info(f"Cycle terminé. Torrents traités: {processed}. Prochain cycle dans {interval}s.")
        except KeyboardInterrupt:
            print("\nInterrompu.")
            return
        except Exception as e:
            log.exception(f"Erreur monitoring: {e}")
        time.sleep(interval)

def cmd_configure(cfg):
    print("Configuration actuelle:")
    print(f"- Token: {'***' if cfg['real_debrid']['token'] else '(vide)'}")
    print(f"- Extensions vidéo: {', '.join(cfg['real_debrid']['video_extensions'])}")
    print(f"- Sous-titres inclus: {cfg['real_debrid']['include_subtitles']}")
    print(f"- Intervalle (s): {cfg['monitoring']['check_interval']}")
    token = input("Nouveau token (laisser vide pour conserver): ").strip()
    if token:
        cfg["real_debrid"]["token"] = token
    exts = input("Extensions vidéo (comma, ex: .mkv,.mp4) [laisser vide]: ").strip()
    if exts:
        cfg["real_debrid"]["video_extensions"] = [x.strip().lower() for x in exts.split(",") if x.strip()]
    incs = input("Inclure sous-titres .srt/.ass ? (y/N): ").strip().lower()
    if incs in ("y", "yes", "o", "oui"):
        cfg["real_debrid"]["include_subtitles"] = True
    interval = input("Intervalle en secondes [laisser vide]: ").strip()
    if interval.isdigit():
        cfg["monitoring"]["check_interval"] = int(interval)
    save_local(cfg)
    print("Configuration enregistrée.")

def main():
    cfg = load_config()
    log_file = cfg["logging"]["file"]
    setup_logger(log_file, cfg["logging"]["level"])

    parser = argparse.ArgumentParser(description=BANNER)
    parser.add_argument("--monitor", action="store_true", help="Lancer le monitoring sans menu")
    parser.add_argument("--fix", metavar="TORRENT_ID", help="Fixer un torrent par ID")
    parser.add_argument("--list", action="store_true", help="Lister torrents (page 1)")
    args = parser.parse_args()

    if args.monitor:
        return monitor_loop(cfg)

    api = None
    try:
        api = RealDebridAPI(cfg["real_debrid"]["token"])
    except Exception as e:
        logging.getLogger("rd.start").warning(f"Token RD manquant ou invalide. Passez par la configuration. Détail: {e}")

    if args.fix and api:
        res = fix_one(api, args.fix, cfg["real_debrid"]["video_extensions"], cfg["real_debrid"]["include_subtitles"])
        print(res)
        return
    if args.list and api:
        items = api.get_torrents(page=1, limit=50)
        for t in items:
            print(f"{t.get('id')}  {t.get('filename')}  {t.get('status')}  progress={t.get('progress')}")
        return

    while True:
        print_menu()
        choice = input("Choix: ").strip()
        if choice == "1":
            monitor_loop(cfg)
        elif choice == "2":
            if not api:
                api = RealDebridAPI(cfg["real_debrid"]["token"])
            tid = input("ID du torrent: ").strip()
            res = fix_one(api, tid, cfg["real_debrid"]["video_extensions"], cfg["real_debrid"]["include_subtitles"])
            print(res)
        elif choice == "3":
            if not api:
                api = RealDebridAPI(cfg["real_debrid"]["token"])
            items = api.get_torrents(page=1, limit=50)
            for t in items:
                print(f"{t.get('id')}  {t.get('filename')}  {t.get('status')}  progress={t.get('progress')}")
        elif choice == "4":
            cmd_configure(cfg)
            api = None  # re-validation
        elif choice == "5":
            names = cfg.get("docker", {}).get("watch_names", [])
            infos = list_containers(names)
            for d in infos:
                print(f"{d['name']}  {d['status']}  {d.get('ip') or '-'}  {d.get('image') or '-'}")
            if not infos:
                print("Aucun conteneur correspondant trouvé.")
        elif choice == "6":
            try:
                tail_log(log_file)
            except KeyboardInterrupt:
                pass
        elif choice == "7":
            print("Au revoir.")
            break
        else:
            print("Choix invalide.")

if __name__ == "__main__":
    main()
