#!/usr/bin/env python3
"""Script d'exécution manuelle: cherche un torrent 'waiting_files_selection' et tente fix_one.

NE COMMITTEZ PAS VOTRE TOKEN. Le script lit la config (.env) via rd_lib.config.
"""
import sys
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rd_lib.config import load_config
from rd_lib.rd_api import RealDebridAPI
from rd_lib.rd_logic import fix_one


def main():
    cfg = load_config()
    token = cfg.get('real_debrid', {}).get('token')
    if not token:
        print('Token absent. Ensure REAL_DEBRID_TOKEN is set in .env or config.')
        return 2

    print('Token loaded (not displayed). Testing up to 5 pages for waiting_files_selection...')
    api = RealDebridAPI(token)
    exts = [e.lower() for e in cfg['real_debrid']['video_extensions']]
    include_subs = bool(cfg['real_debrid']['include_subtitles'])

    found = False
    for page in range(1, 6):
        try:
            items = api.get_torrents(page=page, limit=100)
        except Exception as e:
            print(f'Error fetching page {page}: {e}')
            break
        if not items:
            print(f'Page {page} empty or no items.')
            continue
        for t in items:
            if t.get('status') == 'waiting_files_selection':
                tid = t.get('id')
                print(f"Found waiting torrent on page {page}: id={tid}, filename={t.get('filename')}")
                try:
                    res = fix_one(api, tid, exts, include_subs)
                    print('fix_one result:', json.dumps(res, ensure_ascii=False))
                except Exception as e:
                    print('Exception when fixing:', e)
                found = True
                break
        if found:
            break

    if not found:
        print('No torrent with status waiting_files_selection found in first 5 pages.')


if __name__ == '__main__':
    sys.exit(main() or 0)
