#!/usr/bin/env python3
"""Run mass fix: iterate torrents and call fix_one for those in waiting state.

Use with caution: this will call RealDebrid select_files. Default pause between
selections is 0.5s. Results are appended to data/auto_fix_results.jsonl
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
from rd_lib.rd_logic import fix_one


def main(max_pages=None, page_limit=100, pause_between=0.5, max_samples=None):
    cfg = load_config()
    token = cfg.get('real_debrid', {}).get('token')
    if not token:
        print('Token absent. Set REAL_DEBRID_TOKEN in .env or config.')
        return 2

    api = RealDebridAPI(token)
    exts = [e.lower() for e in cfg['real_debrid']['video_extensions']]
    include_subs = bool(cfg['real_debrid']['include_subtitles'])

    DATA_DIR = ROOT / 'data'
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / 'auto_fix_results.jsonl'

    page = 1
    processed = 0
    while True:
        if max_pages is not None and page > max_pages:
            break
        items = api.get_torrents(page=page, limit=page_limit)
        if not items:
            break
        for t in items:
            status = t.get('status')
            if status in ('waiting_files_selection', 'magnet_conversion'):
                tid = t.get('id')
                print(f'Processing {tid} ({t.get("filename")})')
                res = fix_one(api, tid, exts, include_subs, skip_precheck=True, sleep_after_select=pause_between)
                with open(out, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(res, ensure_ascii=False) + '\n')
                processed += 1
                time.sleep(pause_between)
                if max_samples and processed >= max_samples:
                    print('Reached max_samples, stopping')
                    return 0
        page += 1

    print(f'Done. Processed {processed} torrents. Results appended to {out}')


if __name__ == '__main__':
    sys.exit(main())
