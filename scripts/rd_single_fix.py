#!/usr/bin/env python3
"""rd_single_fix.py

Script autonome (un seul fichier) pour détecter et relancer les torrents
ayant le statut `waiting_files_selection` sur Real‑Debrid.

Fonctionnalités principales:
- utilise l'API RealDebrid (token via --token ou env REAL_DEBRID_TOKEN)
- scanne les pages de torrents, vérifie le détail et sélectionne uniquement
  les fichiers vidéo (extensions configurables)
- gestion basique des limites (Retry-After / 429, et détection 509)
- option `--dry-run` pour simuler
- option `--persist` pour activer une file d'attente SQLite (facultative)
- enregistre les résultats dans un fichier JSONL

Usage minimal:
  ./scripts/rd_single_fix.py --token $REAL_DEBRID_TOKEN

"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from typing import Dict, List, Optional

import urllib.request
import urllib.error
import urllib.parse
import socket
from datetime import datetime
import http.client
import threading
import random

DEFAULT_VIDEO_EXTS = ['.mkv', '.mp4', '.avi', '.mov', '.m4v']


def setup_logger(level=logging.INFO):
    log = logging.getLogger('rd_single_fix')
    # Respect environment override for log level
    env_level = os.environ.get('RD_LOG_LEVEL') or os.environ.get('LOGLEVEL')
    if env_level:
        try:
            level = getattr(logging, env_level.upper())
        except Exception:
            pass

    if not log.handlers:
        h = logging.StreamHandler()
        fmt = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(level)
    return log


class RealDebridClient:
    def __init__(self, token: str, timeout: int = 30):
        self.token = token
        self.base = 'https://api.real-debrid.com/rest/1.0'
        self.timeout = timeout
        # http.client persistent connection pieces
        self._host = 'api.real-debrid.com'
        self._conn_lock = threading.Lock()
        self._conn: Optional[http.client.HTTPSConnection] = None
        # token-bucket for select_files smoothing (default 60/min)
        self._select_bucket: Optional['TokenBucket'] = None

    def _request(self, method: str, path: str, data: Optional[dict] = None, headers: Optional[dict] = None):
        url = f'{self.base}{path}'
        hdrs = {'Authorization': f'Bearer {self.token}', 'User-Agent': 'rd-single-fix/1.0'}
        if headers:
            hdrs.update(headers)

        body = None
        if data is not None:
            # If calling selectFiles endpoint, prefer multipart/form-data with repeated files[] parts
            if '/torrents/selectFiles/' in path and any(k.endswith('[]') for k in data.keys()):
                # Prefer sending as form-urlencoded with a single 'files' parameter as CSV: files=1,3,5
                try:
                    files_list = []
                    for k, v in data.items():
                        if isinstance(v, (list, tuple)):
                            files_list.extend([str(x) for x in v])
                        else:
                            files_list.append(str(v))
                    csv_val = ','.join(files_list)
                    body = f'files={urllib.parse.quote_plus(csv_val)}'.encode('utf-8')
                    hdrs.setdefault('Content-Type', 'application/x-www-form-urlencoded')
                except Exception:
                    # fallback to JSON then multipart
                    try:
                        files_list_int = [int(x) for x in files_list]
                        json_body = json.dumps({'files': files_list_int}, ensure_ascii=False).encode('utf-8')
                        body = json_body
                        hdrs.setdefault('Content-Type', 'application/json')
                    except Exception:
                        boundary = f'----rdsf-{int(time.time())}'
                        lines: List[bytes] = []
                        for k, v in data.items():
                            if isinstance(v, (list, tuple)):
                                for item in v:
                                    lines.append(f'--{boundary}'.encode('utf-8'))
                                    lines.append(f'Content-Disposition: form-data; name="{k}"'.encode('utf-8'))
                                    lines.append(b'')
                                    lines.append(str(item).encode('utf-8'))
                            else:
                                lines.append(f'--{boundary}'.encode('utf-8'))
                                lines.append(f'Content-Disposition: form-data; name="{k}"'.encode('utf-8'))
                                lines.append(b'')
                                lines.append(str(v).encode('utf-8'))
                        lines.append(f'--{boundary}--'.encode('utf-8'))
                        body = b'\r\n'.join(lines) + b'\r\n'
                        hdrs.setdefault('Content-Type', f'multipart/form-data; boundary={boundary}')
            else:
                # Fallback to application/x-www-form-urlencoded preserving literal bracket keys
                parts: List[str] = []
                for k, v in data.items():
                    if isinstance(v, (list, tuple)):
                        for item in v:
                            if k.endswith('[]'):
                                parts.append(f"{k}={urllib.parse.quote_plus(str(item))}")
                            else:
                                parts.append(f"{urllib.parse.quote_plus(str(k))}={urllib.parse.quote_plus(str(item))}")
                    else:
                        if k.endswith('[]'):
                            parts.append(f"{k}={urllib.parse.quote_plus(str(v))}")
                        else:
                            parts.append(f"{urllib.parse.quote_plus(str(k))}={urllib.parse.quote_plus(str(v))}")
                body = '&'.join(parts).encode('utf-8')
                hdrs.setdefault('Content-Type', 'application/x-www-form-urlencoded')

        attempts = 0
        max_attempts = 3
        while True:
            attempts += 1
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            # Debug: log body for selectFiles endpoint to inspect encoding (do not log token)
            log = logging.getLogger('rd_single_fix')
            try:
                if '/torrents/selectFiles/' in path and body:
                    try:
                        body_preview = body.decode('utf-8')
                    except Exception:
                        body_preview = repr(body)
                    safe_headers = {k: v for k, v in hdrs.items() if k.lower() != 'authorization'}
                    log.debug('selectFiles POST body: %s', body_preview)
                    log.debug('selectFiles headers: %s', safe_headers)
            except Exception:
                pass
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status = resp.getcode()
                    info = resp.info()
                    text = resp.read().decode('utf-8')
            except urllib.error.HTTPError as e:
                status = e.code
                info = e.headers
                try:
                    text = e.read().decode('utf-8')
                except Exception:
                    text = ''
            except (urllib.error.URLError, socket.timeout) as e:
                # transient network error -> retry
                if attempts < max_attempts:
                    time.sleep(1 * attempts)
                    continue
                raise

            # handle rate limits
            if status == 429:
                ra = info.get('Retry-After') if info is not None else None
                retry_after = int(ra) if ra and ra.isdigit() else None
                raise RateLimitError('429', retry_after=retry_after)
            if status == 509:
                raise RateLimitError('509')

            if status >= 500 and attempts < max_attempts:
                # server error: retry a few times
                time.sleep(1 * attempts)
                continue

            if status >= 400:
                # raise a simple error with details
                raise Exception(f'HTTP {status} returned: {text}')

            # try to parse JSON
            try:
                return json.loads(text)
            except ValueError:
                return text

    def get_torrents(self, page: int = 1, limit: int = 100):
        return self._request('GET', f'/torrents?page={page}&limit={limit}')

    def get_torrent_info(self, tid: str):
        return self._request('GET', f'/torrents/info/{tid}')

    def select_files(self, tid: str, ids: List[str]):
        # Use token-bucket to smooth selects if configured
        if self._select_bucket:
            # block until allowed
            self._select_bucket.wait_for(1)

        # Prefer CSV form-urlencoded as working encoding
        files_csv = ','.join(str(x) for x in ids)
        path = f'/rest/1.0/torrents/selectFiles/{tid}'
        body = f'files={urllib.parse.quote_plus(files_csv)}'.encode('utf-8')
        headers = {'Authorization': f'Bearer {self.token}', 'User-Agent': 'rd-single-fix/1.0',
                   'Content-Type': 'application/x-www-form-urlencoded', 'Connection': 'keep-alive',
                   'Content-Length': str(len(body))}

        # Attempt to use persistent http.client connection for POST
        try:
            status, resp_headers, text_bytes = self._http_post(path, body, headers)
            text = text_bytes.decode('utf-8') if isinstance(text_bytes, (bytes, bytearray)) else str(text_bytes)
            if status >= 400:
                # mimic previous behavior raising exceptions
                if status == 429:
                    # parse Retry-After if present
                    ra = None
                    for k, v in resp_headers:
                        if k.lower() == 'retry-after' and v.isdigit():
                            ra = int(v)
                    raise RateLimitError('429', retry_after=ra)
                if status == 509:
                    raise RateLimitError('509')
                raise Exception(f'HTTP {status} returned: {text}')
            try:
                return json.loads(text)
            except Exception:
                return text
        except RateLimitError:
            raise
        except Exception:
            # fallback to the generic _request implementation (urllib)
            data = {'files[]': ids}
            return self._request('POST', f'/torrents/selectFiles/{tid}', data=data)

    def configure_select_rate(self, max_per_minute: int):
        if max_per_minute and max_per_minute > 0:
            # bucket capacity = burst of 5 or max_per_minute whichever is smaller
            capacity = max(5, min(max_per_minute, 60))
            refill_per_sec = float(max_per_minute) / 60.0
            self._select_bucket = TokenBucket(capacity=capacity, refill_rate_per_sec=refill_per_sec)


class RateLimitError(Exception):
    def __init__(self, code: str, retry_after: Optional[int] = None):
        super().__init__(f'Rate limit {code}')
        self.code = code
        self.retry_after = retry_after


def find_video_file_ids(info: Dict, video_exts: List[str], include_subs: bool) -> List[str]:
    ids: List[str] = []
    files = info.get('files') or []
    for f in files:
        path = f.get('path', '').lower()
        fid = str(f.get('id') or f.get('index') or '')
        if not fid:
            continue
        if any(path.endswith(ext) for ext in video_exts):
            ids.append(fid)
        elif include_subs and any(path.endswith(ext) for ext in ('.srt', '.ass', '.vtt')):
            ids.append(fid)
    return ids


class TokenBucket:
    """Simple token-bucket rate limiter."""
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_rate = float(refill_rate_per_sec)
        self._last = time.time()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.time()
        with self._lock:
            delta = now - self._last
            if delta > 0:
                self.tokens = min(self.capacity, self.tokens + delta * self.refill_rate)
                self._last = now

    def consume(self, n: float = 1.0) -> bool:
        self._refill()
        with self._lock:
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

    def wait_for(self, n: float = 1.0):
        # busy-wait with sleep small intervals
        while True:
            if self.consume(n):
                return
            time.sleep(0.1 + random.random() * 0.1)


    def _http_post(self, path: str, body: bytes, headers: Dict[str, str]):
        # internal method using http.client.HTTPSConnection on self._host
        # returns (status, headers_list, body_bytes)
        conn = None
        with self._conn_lock:
            if not self._conn:
                self._conn = http.client.HTTPSConnection(self._host, timeout=self.timeout)
            conn = self._conn
        try:
            conn.request('POST', path, body=body, headers=headers)
            resp = conn.getresponse()
            resp_body = resp.read()
            resp_headers = list(resp.getheaders())
            # if server closed, reset connection for next time
            if getattr(resp, 'will_close', False):
                try:
                    conn.close()
                except Exception:
                    pass
                with self._conn_lock:
                    self._conn = None
            return resp.status, resp_headers, resp_body
        except Exception:
            # if anything wrong, ensure connection reset
            try:
                conn.close()
            except Exception:
                pass
            with self._conn_lock:
                self._conn = None
            raise


def ensure_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def append_results(path: str, obj: Dict):
    ensure_dir(path)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def compute_backoff(attempt: int, base: int = 60, factor: int = 2, max_backoff: int = 3600) -> int:
    back = int(base * (factor ** max(0, attempt - 1)))
    return min(back, max_backoff)


# -----------------------
# SQLite retry queue helpers
# -----------------------
def init_db(db_path: str):
    ensure_dir(db_path)
    con = sqlite3.connect(db_path)
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

def list_queue(db_path: str, limit: int = 100) -> None:
    """Print a human-friendly summary of the retries queue.

    Shows id, attempts, next_try (ISO), and a short payload preview.
    """
    if not os.path.exists(db_path):
        print(f"No DB at {db_path}")
        return
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("SELECT id, attempts, next_try, payload FROM retries ORDER BY next_try ASC LIMIT ?", (limit,))
    except sqlite3.OperationalError as e:
        print(f"DB error: {e}")
        conn.close()
        return
    rows = c.fetchall()
    if not rows:
        print("Queue is empty")
        conn.close()
        return
    print(f"Showing up to {limit} items from {db_path}:")
    now = datetime.utcnow()
    for r in rows:
        rid, attempts, next_try, payload = r
        # payload may be JSON or text; make a short preview
        preview = None
        try:
            preview = json.loads(payload)
            preview_str = json.dumps(preview) if isinstance(preview, (dict, list)) else str(preview)
        except Exception:
            preview_str = str(payload)
        if len(preview_str) > 80:
            preview_str = preview_str[:77] + "..."
        # next_try stored as timestamp float or ISO string depending on code; try to normalize
        nt_display = str(next_try)
        try:
            if isinstance(next_try, (int, float)):
                nt_display = datetime.utcfromtimestamp(float(next_try)).isoformat() + "Z"
            else:
                # try parse
                nt_display = str(next_try)
        except Exception:
            nt_display = str(next_try)
        # relative
        try:
            nt_dt = datetime.fromisoformat(nt_display.replace("Z", ""))
            delta = nt_dt - now
            rel = f"in {int(delta.total_seconds())}s" if delta.total_seconds() >= 0 else f"{int(-delta.total_seconds())}s ago"
        except Exception:
            rel = "?"
        print(f"- id={rid} attempts={attempts} next_try={nt_display} ({rel}) payload={preview_str}")
    conn.close()

def add_retry(db_path: str, tid: str, payload: Dict, attempts: int = 0, next_try: int = 0):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute('INSERT OR REPLACE INTO retries (id,payload,attempts,next_try) VALUES (?,?,?,?)',
                (tid, json.dumps(payload, ensure_ascii=False), attempts, int(next_try)))
    con.commit()
    con.close()


def pop_due(db_path: str, max_n: int = 50) -> List[Dict]:
    now = int(time.time())
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute('SELECT id,payload,attempts,next_try FROM retries WHERE next_try<=? ORDER BY next_try ASC LIMIT ?', (now, max_n))
    rows = cur.fetchall()
    con.close()
    return [{'id': r[0], 'payload': json.loads(r[1]), 'attempts': r[2], 'next_try': r[3]} for r in rows]


def remove_retry(db_path: str, tid: str):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute('DELETE FROM retries WHERE id=?', (tid,))
    con.commit()
    con.close()


def update_retry(db_path: str, tid: str, payload: Dict, attempts: int, next_try: int):
    add_retry(db_path, tid, payload, attempts, next_try)



def run_once(client: RealDebridClient, video_exts: List[str], include_subs: bool, pause: float, page_limit: int,
             max_pages: Optional[int], results_path: Optional[str], dry_run: bool, log=None, persist_db: Optional[str]=None,
             max_per_cycle: Optional[int]=None, info_pause: float = 0.5, info_cache_ttl: int = 300):
    log = log or setup_logger()
    processed = 0
    page = 1
    # simple in-memory cache for torrent info to avoid repeated GETs
    info_cache: Dict[str, Dict] = {}
    info_cache_expiry: Dict[str, int] = {}

    # optional sqlite persistence for retries
    conn = None
    if persist_db:
        ensure_dir(persist_db)
        conn = sqlite3.connect(persist_db)
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS retries (id TEXT PRIMARY KEY, attempts INTEGER, next_try INTEGER)''')
        conn.commit()

    # First: collect candidate torrents across pages
    candidates: List[Dict] = []
    while True:
        if max_pages is not None and page > max_pages:
            break
        try:
            items = client.get_torrents(page=page, limit=page_limit)
        except RateLimitError as e:
            ra = e.retry_after or 60
            log.warning('Rate limited when listing torrents: %s, sleeping %ss', e.code, ra)
            time.sleep(ra)
            continue
        except Exception as e:
            log.error('Error fetching torrents page %s: %s', page, e)
            break

        if not items:
            break

        for t in items:
            status = t.get('status')
            if status in ('waiting_files_selection', 'magnet_conversion'):
                candidates.append(t)
            if max_per_cycle is not None and len(candidates) >= max_per_cycle:
                break

        if max_per_cycle is not None and len(candidates) >= max_per_cycle:
            break
        page += 1

    # Then process candidates one by one (fetch info -> select)
    for t in candidates:
        if max_per_cycle is not None and processed >= max_per_cycle:
            log.info('Reached max_per_cycle=%s, stopping cycle', max_per_cycle)
            break
        tid = str(t.get('id'))
        fn = t.get('filename') or t.get('name') or ''
        log.info('Checking %s %s', tid, fn)

        # Try to fetch info from cache first
        now = int(time.time())
        info = None
        if tid in info_cache and info_cache_expiry.get(tid, 0) > now:
            info = info_cache[tid]
        else:
            try:
                info = client.get_torrent_info(tid)
                # cache it
                info_cache[tid] = info
                info_cache_expiry[tid] = now + info_cache_ttl
                # small pause after info fetch to reduce rate
                if info_pause:
                    time.sleep(info_pause)
            except RateLimitError as e:
                ra = e.retry_after or 60
                log.warning('Rate limited when getting info for %s: sleeping %ss', tid, ra)
                time.sleep(ra)
                continue
            except Exception as e:
                log.error('Error getting info for %s: %s', tid, e)
                continue

        ids = find_video_file_ids(info, video_exts, include_subs)
        found = bool(ids)
        changed = False
        reason = None

        if not ids:
            reason = 'no_video_files'
            log.info('No video files found for %s', tid)
        else:
            log.info('Will select %s files for %s', len(ids), tid)
            if dry_run:
                log.info('[dry-run] would call select_files(%s, %s)', tid, ids)
                changed = False
                reason = 'dry_run'
            else:
                try:
                    client.select_files(tid, ids)
                    changed = True
                    reason = 'selected'
                    log.info('Selected %s files for %s', len(ids), tid)
                except RateLimitError as e:
                    reason = f'select_failed_{e.code}'
                    log.warning('Rate limit (%s) when selecting files for %s', e.code, tid)
                    if e.retry_after:
                        time.sleep(e.retry_after)
                    else:
                        # exponential backoff simple
                        time.sleep(compute_backoff(1))
                except Exception as e:
                    reason = 'select_failed'
                    log.error('Error selecting files for %s: %s', tid, e)

        res = {
            'ts': int(time.time()),
            'id': tid,
            'filename': fn,
            'status': t.get('status'),
            'found_files': len(ids),
            'changed': changed,
            'reason': reason,
        }
        if results_path:
            try:
                append_results(results_path, res)
            except Exception:
                log.exception('Failed to append result')

        processed += 1
        time.sleep(pause)

    if conn:
        conn.close()

    log.info('Cycle complete, processed %s items', processed)
    return processed


def run_cycle(client: RealDebridClient, cfg: Dict, pause: float, page_limit: int, max_pages: Optional[int],
              results_path: str, dry_run: bool, persist_db: Optional[str], max_per_cycle: Optional[int], log=None):
    """Process retry queue first, then scan pages for new items and schedule retries with backoff."""
    log = log or setup_logger()
    processed = 0
    video_exts = cfg.get('video_exts', DEFAULT_VIDEO_EXTS)
    include_subs = cfg.get('include_subs', False)
    info_pause = cfg.get('info_pause', 0.5)
    info_cache_ttl = cfg.get('info_cache_ttl', 300)
    info_cache: Dict[str, Dict] = {}
    info_cache_expiry: Dict[str, int] = {}
    processed_ids = set()
    selects_count = 0
    selects_window_start = int(time.time())
    selects_per_minute = cfg.get('max_selects_per_minute', 60)

    # 1) handle due retries
    if persist_db:
        due = pop_due(persist_db, max_n=max_per_cycle or 50)
        for item in due:
            if max_per_cycle is not None and processed >= max_per_cycle:
                break
            tid = item['id']
            if tid in processed_ids:
                log.debug('[retry] %s already processed this cycle, skipping', tid)
                continue
            attempts = item['attempts'] + 1
            log.info('[retry] trying %s (attempt %s)', tid, attempts)
            now = int(time.time())
            info = None
            if tid in info_cache and info_cache_expiry.get(tid, 0) > now:
                info = info_cache[tid]
            else:
                try:
                    info = client.get_torrent_info(tid)
                    info_cache[tid] = info
                    info_cache_expiry[tid] = now + info_cache_ttl
                    if info_pause:
                        time.sleep(info_pause)
                except RateLimitError as e:
                    ra = e.retry_after or 60
                    log.warning('[retry] rate limited when getting info %s, sleeping %s', tid, ra)
                    time.sleep(ra)
                    # reschedule same attempt
                    back = compute_backoff(attempts)
                    update_retry(persist_db, tid, item['payload'], attempts, int(time.time()) + back)
                    continue
                except Exception as e:
                    log.error('[retry] error getting info %s: %s', tid, e)
                    # schedule later
                    back = compute_backoff(attempts)
                    update_retry(persist_db, tid, item['payload'], attempts, int(time.time()) + back)
                    continue

            ids = find_video_file_ids(info, video_exts, include_subs)
            if not ids:
                log.info('[retry] no video files for %s, removing retry', tid)
                remove_retry(persist_db, tid)
                processed += 1
                continue

            if dry_run:
                log.info('[retry dry-run] would select %s for %s', ids, tid)
                remove_retry(persist_db, tid)
                processed += 1
                continue

            try:
                # global selects-per-minute throttle
                now = int(time.time())
                if selects_per_minute and selects_per_minute > 0:
                    if now - selects_window_start >= 60:
                        selects_window_start = now
                        selects_count = 0
                    if selects_count >= selects_per_minute:
                        log.info('[retry] selects per minute limit reached, rescheduling %s', tid)
                        back = compute_backoff(attempts)
                        update_retry(persist_db, tid, item['payload'], attempts, int(time.time()) + back)
                        continue
                client.select_files(tid, ids)
                selects_count += 1
                processed_ids.add(tid)
                log.info('[retry] selected files for %s', tid)
                remove_retry(persist_db, tid)
            except RateLimitError as e:
                attempts = item['attempts'] + 1
                # use a slightly larger backoff for rate limits
                back = compute_backoff(attempts, base=60, factor=3)
                next_try = int(time.time()) + back
                log.warning('[retry] rate limited selecting %s, scheduling next_try in %s', tid, back)
                update_retry(persist_db, tid, item['payload'], attempts, next_try)
            except Exception as e:
                attempts = item['attempts'] + 1
                # on generic errors (503 etc) use larger backoff
                back = compute_backoff(attempts, base=60, factor=3)
                next_try = int(time.time()) + back
                log.error('[retry] error selecting files for %s: %s, scheduling next_try %s', tid, e, back)
                update_retry(persist_db, tid, item['payload'], attempts, next_try)

            processed += 1
            time.sleep(pause)

    # 2) scan pages for new items
    page = 1
    consecutive_509 = 0
    while (max_per_cycle is None or processed < max_per_cycle):
        if max_pages is not None and page > max_pages:
            break
        try:
            items = client.get_torrents(page=page, limit=page_limit)
        except RateLimitError as e:
            ra = e.retry_after or 60
            log.warning('Rate limited when listing torrents: sleeping %s', ra)
            time.sleep(ra)
            continue
        except Exception as e:
            log.error('Error listing torrents page %s: %s', page, e)
            break

        if not items:
            break

        for t in items:
            if max_per_cycle is not None and processed >= max_per_cycle:
                break
            status = t.get('status')
            if status not in ('waiting_files_selection', 'magnet_conversion'):
                continue
            tid = str(t.get('id'))
            if tid in processed_ids:
                log.debug('[scan] %s already processed this cycle, skipping', tid)
                continue
            fn = t.get('filename') or t.get('name') or ''
            log.info('[scan] processing %s %s', tid, fn)
            now = int(time.time())
            info = None
            if tid in info_cache and info_cache_expiry.get(tid, 0) > now:
                info = info_cache[tid]
            else:
                try:
                    info = client.get_torrent_info(tid)
                    info_cache[tid] = info
                    info_cache_expiry[tid] = now + info_cache_ttl
                    if info_pause:
                        time.sleep(info_pause)
                except RateLimitError as e:
                    ra = e.retry_after or 60
                    log.warning('[scan] rate limited when getting info %s: sleeping %s', tid, ra)
                    time.sleep(ra)
                    continue
                except Exception as e:
                    log.error('[scan] error getting info %s: %s', tid, e)
                    continue

            ids = find_video_file_ids(info, video_exts, include_subs)
            if not ids:
                # schedule retry in case metadata updates later
                if persist_db:
                    log.info('[scan] no video files for %s, scheduling retry', tid)
                    add_retry(persist_db, tid, {'summary': t}, attempts=1, next_try=int(time.time()) + compute_backoff(1))
                processed += 1
                continue

            if dry_run:
                log.info('[scan dry-run] would select %s for %s', ids, tid)
                processed += 1
                continue

            try:
                now = int(time.time())
                if selects_per_minute and selects_per_minute > 0:
                    if now - selects_window_start >= 60:
                        selects_window_start = now
                        selects_count = 0
                    if selects_count >= selects_per_minute:
                        log.info('[scan] selects per minute limit reached, scheduling %s', tid)
                        if persist_db:
                            add_retry(persist_db, tid, {'summary': t}, attempts=1, next_try=int(time.time()) + compute_backoff(1))
                        else:
                            log.info('[scan] no persist DB; skipping %s this cycle', tid)
                        continue
                client.select_files(tid, ids)
                selects_count += 1
                processed_ids.add(tid)
                log.info('[scan] selected files for %s', tid)
            except RateLimitError as e:
                log.warning('[scan] rate limit %s selecting %s', e.code, tid)
                # schedule retry
                if persist_db:
                    add_retry(persist_db, tid, {'summary': t}, attempts=1, next_try=int(time.time()) + compute_backoff(1))
                # adaptive sleep on many 509s
                if e.code == '509':
                    consecutive_509 += 1
                    sleep = min(60 * consecutive_509, 600)
                    log.warning('[scan] sleeping %s due to consecutive 509s', sleep)
                    time.sleep(sleep)
            except Exception as e:
                log.error('[scan] error selecting files for %s: %s', tid, e)
                if persist_db:
                    add_retry(persist_db, tid, {'summary': t}, attempts=1, next_try=int(time.time()) + compute_backoff(1))

            processed += 1
            time.sleep(pause)

        page += 1

    log.info('Run cycle complete processed %s items', processed)
    return processed


def build_arg_parser():
    p = argparse.ArgumentParser(description='Detect and relaunch RealDebrid torrents in waiting_files_selection')
    p.add_argument('--token', help='RealDebrid token (or set REAL_DEBRID_TOKEN)')
    p.add_argument('--video-exts', default=','.join(DEFAULT_VIDEO_EXTS),
                   help='Comma-separated list of video extensions (default .mkv,.mp4,...)')
    p.add_argument('--include-subs', action='store_true', help='Also select subtitle files (.srt,.ass)')
    p.add_argument('--pause', type=float, default=1.5, help='Seconds to sleep between selects')
    p.add_argument('--page-limit', type=int, default=5000, help='Torrents per page (max 5000)')
    p.add_argument('--max-pages', type=int, default=0, help='Max pages to scan (use 0 or -1 for unlimited)')
    p.add_argument('--max-per-cycle', type=int, default=200, help='Max items to process per run')
    p.add_argument('--results', default='data/auto_fix_results.jsonl', help='Path to append JSONL results')
    p.add_argument('--dry-run', action='store_true', help='Do not call select_files, only simulate')
    p.add_argument('--persist', help='Enable sqlite persistence file (path). Optional')
    p.add_argument('--info-pause', type=float, default=0.5, help='Seconds to sleep after fetching torrent info')
    p.add_argument('--info-cache-ttl', type=int, default=300, help='Seconds to cache torrent info in memory')
    p.add_argument('--collect-ids', help='Path to write candidate ids (one per line). Only collect, do not select')
    p.add_argument('--process-ids', help='Path to read candidate ids (one per line) and process them slowly')
    p.add_argument('--enqueue', action='store_true', help='When used with --process-ids, enqueue ids into --persist DB instead of immediate select')
    p.add_argument('--process-delay', type=int, default=60, help='Seconds spacing when enqueuing ids (used with --enqueue)')
    p.add_argument('--max-selects-per-minute', type=int, default=60, help='Global cap of select_files calls per minute (0 = no cap)')
    p.add_argument('--worker', action='store_true', help='Run dedicated queue consumer: pop one due item and process it, sleep --process-delay between items')
    p.add_argument('--list-queue', action='store_true', help='List entries in the sqlite retry queue and exit')
    p.add_argument('--once', action='store_true', help='Run a single scan then exit')
    p.add_argument('--daemon', action='store_true', help='Run in daemon mode with persistence and backoff')
    p.add_argument('--cycle-interval', type=int, default=3600, help='Seconds between cycles when daemon')
    return p


def main(argv=None):
    argv = argv or sys.argv[1:]
    args = build_arg_parser().parse_args(argv)
    log = setup_logger()
    # If user only wants to list the queue, allow running without token
    if args.list_queue:
        db_path = args.persist or 'data/auto_fix_state.db'
        init_db(db_path)
        list_queue(db_path)
        return 0

    token = args.token or os.environ.get('REAL_DEBRID_TOKEN')
    if not token:
        log.error('No token provided. Use --token or set REAL_DEBRID_TOKEN')
        return 2
    video_exts = [e if e.startswith('.') else f'.{e}' for e in (v.strip() for v in args.video_exts.split(',')) if e]
    include_subs = args.include_subs
    pause = args.pause
    page_limit = args.page_limit
    max_pages = None if args.max_pages <= 0 else args.max_pages
    max_per_cycle = None if args.max_per_cycle <= 0 else args.max_per_cycle
    max_selects_per_minute = args.max_selects_per_minute
    info_pause = args.info_pause
    info_cache_ttl = args.info_cache_ttl

    client = RealDebridClient(token)
    # configure token-bucket for selects if requested
    try:
        # Dedicated queue worker mode: consumes one retry at a time at steady rate
        if args.worker:
            if not args.persist:
                log.error('--worker requires --persist <db_path>')
                return 2
            init_db(args.persist)
            log.info('Starting dedicated worker: processing one job every %ss', args.process_delay)
            while True:
                due = pop_due(args.persist, max_n=1)
                if not due:
                    time.sleep(1)
                    continue
                item = due[0]
                tid = item['id']
                attempts = item['attempts'] + 1
                log.info('[worker] trying %s (attempt %s)', tid, attempts)
                try:
                    info = client.get_torrent_info(tid)
                except RateLimitError as e:
                    ra = e.retry_after or 60
                    log.warning('[worker] rate limited when getting info %s, sleeping %s', tid, ra)
                    # reschedule
                    back = compute_backoff(attempts)
                    update_retry(args.persist, tid, item['payload'], attempts, int(time.time()) + back)
                    time.sleep(ra)
                    continue
                except Exception as e:
                    log.error('[worker] error getting info %s: %s', tid, e)
                    back = compute_backoff(attempts)
                    update_retry(args.persist, tid, item['payload'], attempts, int(time.time()) + back)
                    time.sleep(args.process_delay)
                    continue

                ids = find_video_file_ids(info, video_exts, include_subs)
                if not ids:
                    log.info('[worker] no video files for %s, removing retry', tid)
                    remove_retry(args.persist, tid)
                    time.sleep(args.process_delay)
                    continue

                try:
                    client.select_files(tid, ids)
                    log.info('[worker] selected files for %s', tid)
                    remove_retry(args.persist, tid)
                except RateLimitError as e:
                    back = compute_backoff(attempts, base=60, factor=3)
                    update_retry(args.persist, tid, item['payload'], attempts, int(time.time()) + back)
                    log.warning('[worker] rate limited selecting %s, scheduling next_try in %s', tid, back)
                except Exception as e:
                    back = compute_backoff(attempts, base=60, factor=3)
                    update_retry(args.persist, tid, item['payload'], attempts, int(time.time()) + back)
                    log.error('[worker] error selecting files for %s: %s, scheduling next_try %s', tid, e, back)

                time.sleep(args.process_delay)
            # worker runs forever
            return 0

        client.configure_select_rate(max_selects_per_minute)
    except Exception:
        pass

    try:
        # If collect-only mode requested: walk pages and dump IDs to file
        if args.collect_ids:
            path = args.collect_ids
            log.info('Collecting candidate ids to %s', path)
            # iterate pages until empty or until max_pages if set
            page = 1
            written = 0
            with open(path, 'w', encoding='utf-8') as fh:
                while True:
                    if max_pages is not None and page > max_pages:
                        break
                    try:
                        items = client.get_torrents(page=page, limit=page_limit)
                    except RateLimitError as e:
                        ra = e.retry_after or 60
                        log.warning('Rate limited when listing torrents: sleeping %ss', ra)
                        time.sleep(ra)
                        continue
                    except Exception as e:
                        log.error('Error listing torrents page %s: %s', page, e)
                        break

                    if not items:
                        break

                    for t in items:
                        status = t.get('status')
                        if status in ('waiting_files_selection', 'magnet_conversion'):
                            tid = str(t.get('id'))
                            fh.write(tid + '\n')
                            written += 1
                    page += 1

            log.info('Collected %s candidate ids to %s', written, path)
            return 0

        # If processing from file requested: read IDs and process each slowly
        if args.process_ids:
            path = args.process_ids
            if not os.path.exists(path):
                log.error('Process ids file not found: %s', path)
                return 2
            with open(path, 'r', encoding='utf-8') as fh:
                ids = [line.strip() for line in fh if line.strip()]
            log.info('Processing %s ids from %s', len(ids), path)
            if args.enqueue:
                if not args.persist:
                    log.error('--enqueue requires --persist <db_path> to be set')
                    return 2
                # ensure DB/table exists
                init_db(args.persist)
                # enqueue ids spaced by process_delay
                now = int(time.time())
                for i, tid in enumerate(ids):
                    next_try = now + i * args.process_delay
                    add_retry(args.persist, tid, {'collected': True}, attempts=0, next_try=next_try)
                log.info('Enqueued %s ids into %s with spacing %ss', len(ids), args.persist, args.process_delay)
                return 0

            for tid in ids:
                try:
                    info = client.get_torrent_info(tid)
                except RateLimitError as e:
                    ra = e.retry_after or 60
                    log.warning('Rate limited when getting info for %s: sleeping %ss', tid, ra)
                    time.sleep(ra)
                    continue
                except Exception as e:
                    log.error('Error getting info for %s: %s', tid, e)
                    continue

                ids_to_select = find_video_file_ids(info, video_exts, include_subs)
                if not ids_to_select:
                    log.info('No video files for %s, skipping', tid)
                    continue
                if args.dry_run:
                    log.info('[dry-run] would select %s for %s', ids_to_select, tid)
                    continue
                try:
                    client.select_files(tid, ids_to_select)
                    log.info('Selected %s files for %s', len(ids_to_select), tid)
                except RateLimitError as e:
                    log.warning('Rate limit %s selecting %s', e.code, tid)
                    if e.retry_after:
                        time.sleep(e.retry_after)
                    else:
                        time.sleep(compute_backoff(1))
                except Exception as e:
                    log.error('Error selecting files for %s: %s', tid, e)

                # small pause between items to be gentle
                time.sleep(pause)
            return 0

        if args.daemon:
            # prepare config dict for run_cycle
            cfg = {'video_exts': video_exts, 'include_subs': include_subs,
                   'max_selects_per_minute': max_selects_per_minute,
                   'info_pause': info_pause, 'info_cache_ttl': info_cache_ttl}
            if args.persist:
                init_db(args.persist)
            while True:
                processed = run_cycle(client, cfg, pause, page_limit, max_pages, args.results, args.dry_run,
                                      args.persist, max_per_cycle, log=log)
                if args.once:
                    break
                if processed == 0:
                    log.info('Daemon: nothing processed; sleeping 60s')
                    time.sleep(60)
                else:
                    # if we processed items, sleep a shorter time to continue slowly (avoid 1h default bursts)
                    short_sleep = min(300, args.cycle_interval)
                    log.info('Daemon: cycle complete; processed %s items; sleeping %s seconds', processed, short_sleep)
                    time.sleep(short_sleep)
        else:
            while True:
                processed = run_once(client, video_exts, include_subs, pause, page_limit, max_pages,
                                     args.results, args.dry_run, log=log, persist_db=args.persist,
                                     max_per_cycle=max_per_cycle)
                if args.once:
                    break
                if processed == 0:
                    log.info('No items processed; sleeping 60s')
                    time.sleep(60)
                else:
                    log.info('Cycle done; sleeping 300s before next cycle')
                    time.sleep(300)
    except KeyboardInterrupt:
        log.info('Interrupted, exiting')
    return 0


if __name__ == '__main__':
    sys.exit(main())
