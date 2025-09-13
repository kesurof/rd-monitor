#!/usr/bin/env python3
"""Daemon runner for automated fixes.

Features:
- Scans RealDebrid torrents and attempts fixes (select_files) in controlled batches
- Persists retry queue in SQLite (data/auto_fix_state.db)
- Exponential backoff for retrying failed items; special handling for 509 (rate limit)
- Writes action results to data/auto_fix_results.jsonl

Configure via CLI args or environment; safe defaults aim to spread work over time.
"""
import argparse
import json
import sqlite3
import time
import pathlib
import sys
import logging

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rd_lib.config import load_config
from rd_lib.rd_api import RealDebridAPI
from rd_lib.rd_logic import fix_one
from rd_lib.logger import get_logger

log = get_logger('rd.daemon')


DB_PATH = ROOT / 'data' / 'auto_fix_state.db'
RESULTS_PATH = ROOT / 'data' / 'auto_fix_results.jsonl'


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS retries (
            id TEXT PRIMARY KEY,
            payload TEXT,
            attempts INTEGER DEFAULT 0,
            next_try INTEGER DEFAULT 0
        )
    ''')
    con.commit()
    con.close()


def add_retry(tid, payload, attempts=0, next_try=0):
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute('INSERT OR REPLACE INTO retries (id,payload,attempts,next_try) VALUES (?,?,?,?)',
                (tid, json.dumps(payload, ensure_ascii=False), attempts, int(next_try)))
    con.commit()
    con.close()


def pop_due(max_n=50):
    now = int(time.time())
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute('SELECT id,payload,attempts,next_try FROM retries WHERE next_try<=? ORDER BY next_try ASC LIMIT ?', (now, max_n))
    rows = cur.fetchall()
    con.close()
    return [{'id': r[0], 'payload': json.loads(r[1]), 'attempts': r[2], 'next_try': r[3]} for r in rows]


def remove_retry(tid):
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute('DELETE FROM retries WHERE id=?', (tid,))
    con.commit()
    con.close()


def update_retry(tid, payload, attempts, next_try):
    add_retry(tid, payload, attempts, next_try)


def append_result(res):
    with open(RESULTS_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(res, ensure_ascii=False) + '\n')
    log.info('result', extra={'result': res})


def now_ts():
    return int(time.time())


def compute_backoff(attempts, base=60, factor=2, max_backoff=3600):
    # exponential backoff in seconds
    back = int(base * (factor ** max(0, attempts - 1)))
    return min(back, max_backoff)


def run_cycle(api, cfg, pause_between, max_per_cycle, max_pages, max_retries_per_item):
    exts = [e.lower() for e in cfg['real_debrid']['video_extensions']]
    include_subs = bool(cfg['real_debrid']['include_subtitles'])

    processed = 0
    # handle retry queue first
    due = pop_due(max_n=max_per_cycle)
    for item in due:
        if processed >= max_per_cycle:
            break
        tid = item['id']
        attempts = item['attempts'] + 1
        log.info(f'[retry] Trying {tid} (attempt {attempts})')
        res = fix_one(api, tid, exts, include_subs, skip_precheck=True, sleep_after_select=pause_between)
        append_result(res)
        if res.get('changed'):
            remove_retry(tid)
        else:
            if attempts >= max_retries_per_item:
                log.warning(f'[retry] Max attempts for {tid}, giving up')
                remove_retry(tid)
            else:
                back = compute_backoff(attempts)
                next_try = now_ts() + back
                log.info(f'[retry] Scheduling {tid} next_try in {back}s')
                update_retry(tid, item['payload'], attempts, next_try)
        processed += 1

    # scan pages for new items
    page = 1
    consecutive_509 = 0
    while (max_per_cycle is None or processed < max_per_cycle):
        if max_pages is not None and page > max_pages:
            break
        try:
            items = api.get_torrents(page=page, limit=100)
        except Exception as e:
            log.error('Error fetching page %s: %s', page, e)
            break
        if not items:
            break
        for t in items:
            if max_per_cycle is not None and processed >= max_per_cycle:
                break
            status = t.get('status')
            if status not in ('waiting_files_selection', 'magnet_conversion'):
                continue
            tid = t.get('id')
            log.info('[scan] Processing %s (%s)', tid, t.get('filename'))
            res = fix_one(api, tid, exts, include_subs, skip_precheck=True, sleep_after_select=pause_between)
            append_result(res)
            if not res.get('changed') and res.get('reason') == 'select_failed' and '509' in (res.get('error') or ''):
                consecutive_509 += 1
                attempts = 1
                back = compute_backoff(attempts, base=60)
                next_try = now_ts() + back
                log.warning('[rate] 509 for %s, scheduling retry in %ss', tid, back)
                add_retry(tid, {'list_summary': t}, attempts=attempts, next_try=next_try)
                sleep = min(60 * consecutive_509, 600)
                log.warning('[rate] sleeping %ss due to rate limits', sleep)
                time.sleep(sleep)
            else:
                consecutive_509 = 0
            if not res.get('changed') and res.get('reason') not in ('select_failed',):
                attempts = 1
                next_try = now_ts() + compute_backoff(attempts, base=300)
                add_retry(tid, {'list_summary': t}, attempts=attempts, next_try=next_try)
            processed += 1
        page += 1

    log.info('Cycle complete. Processed %s items.', processed)
    return processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pause', type=float, default=1.5, help='pause between selects (s)')
    parser.add_argument('--max-per-cycle', type=int, default=200, help='max items to process per cycle')
    parser.add_argument('--cycle-interval', type=int, default=3600, help='seconds between cycles')
    parser.add_argument('--max-pages', type=int, default=50, help='max pages to scan per cycle')
    parser.add_argument('--max-retries', type=int, default=5, help='max retry attempts per item')
    args = parser.parse_args()

    cfg = load_config()
    token = cfg.get('real_debrid', {}).get('token')
    if not token:
        print('Token absent. Set REAL_DEBRID_TOKEN in .env or config.')
        return 2

    init_db()
    api = RealDebridAPI(token)

    print('Daemon started: pause=', args.pause, 'max_per_cycle=', args.max_per_cycle, 'cycle_interval=', args.cycle_interval)
    try:
        while True:
            processed = run_cycle(api, cfg, args.pause, args.max_per_cycle, args.max_pages, args.max_retries)
            print('Sleeping for', args.cycle_interval, 'seconds before next cycle')
            time.sleep(args.cycle_interval)
    except KeyboardInterrupt:
        print('Interrupted, exiting')


if __name__ == '__main__':
    sys.exit(main())
