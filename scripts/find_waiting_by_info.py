#!/usr/bin/env python3
"""Scan limited number of torrents and call get_torrent_info to find detailed status 'waiting_files_selection'.
Saves samples to data/sample_waiting_info.json for analysis.
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


def main(max_samples=20, max_items=500, page_limit=100, pause=0.5):
    cfg = load_config()
    token = cfg.get('real_debrid', {}).get('token')
    if not token:
        print('Token absent. Set REAL_DEBRID_TOKEN in .env or config.')
        return 2
    api = RealDebridAPI(token)

    collected = []
    scanned = 0
    page = 1
    while scanned < max_items and len(collected) < max_samples:
        try:
            items = api.get_torrents(page=page, limit=page_limit)
        except Exception as e:
            print(f'Error fetching page {page}: {e}')
            break
        if not items:
            break
        for t in items:
            if scanned >= max_items or len(collected) >= max_samples:
                break
            scanned += 1
            tid = t.get('id')
            try:
                info = api.get_torrent_info(tid)
            except Exception as e:
                print(f'Error getting info for {tid}: {e}')
                time.sleep(pause)
                continue
            if info.get('status') == 'waiting_files_selection':
                print(f'Found waiting in info for {tid} (scanned {scanned})')
                collected.append({'id': tid, 'list_summary': t, 'info': info})
            time.sleep(pause)
        page += 1

    DATA_DIR = ROOT / 'data'
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / 'sample_waiting_info.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(collected, f, ensure_ascii=False, indent=2)
    print(f'Wrote {len(collected)} samples to {out}; scanned {scanned} items')


if __name__ == '__main__':
    sys.exit(main())
