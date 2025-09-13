#!/usr/bin/env python3
"""Collecte des exemples de torrents 'waiting_files_selection' pour analyse.

Écrit les exemples dans data/sample_waiting.json (pas commités normalement).
"""
import sys
import time
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rd_lib.config import load_config
from rd_lib.rd_api import RealDebridAPI


def main(max_samples=10, max_pages=50, page_limit=100, pause=1.0):
    cfg = load_config()
    token = cfg.get('real_debrid', {}).get('token')
    if not token:
        print('Token absent. Set REAL_DEBRID_TOKEN in .env or config.')
        return 2

    api = RealDebridAPI(token)
    collected = []
    page = 1
    while len(collected) < max_samples and page <= max_pages:
        try:
            items = api.get_torrents(page=page, limit=page_limit)
        except Exception as e:
            print(f'Error fetching page {page}: {e}')
            break
        if not items:
            print(f'No items on page {page}')
            break
        for t in items:
            if t.get('status') == 'waiting_files_selection':
                tid = t.get('id')
                try:
                    info = api.get_torrent_info(tid)
                except Exception as e:
                    print(f'Error getting info for {tid}: {e}')
                    continue
                collected.append({'id': tid, 'summary': t, 'info': info})
                print(f'Collected sample for {tid} (total {len(collected)})')
                if len(collected) >= max_samples:
                    break
                time.sleep(pause)
        page += 1

    DATA_DIR = ROOT / 'data'
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / 'sample_waiting.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(collected, f, ensure_ascii=False, indent=2)

    print(f'Wrote {len(collected)} samples to {out}')


if __name__ == '__main__':
    sys.exit(main())
