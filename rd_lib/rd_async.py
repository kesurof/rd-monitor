"""Async helpers pour Real-Debrid: requests asynchrones, retries, backoff, et batch upsert.

Contient:
- api_request: wrapper aiohttp avec retries/backoff et respect Retry-After
- fetch_all_torrents: pagination (limit=5000) + upsert par page + option details parallèles
- fetch_torrent_detail: récupération détaillée avec upsert
"""
import asyncio
import aiohttp
import random
import logging
from typing import Optional, Callable, List, Dict, Any

log = logging.getLogger("rd.async")

DEFAULT_PAGE_LIMIT = 5000
DEFAULT_PAGE_WAIT = 1.0


async def api_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    max_retries: int = 4,
    backoff_base: float = 0.8,
):
    """Effectue une requête HTTP avec retries/backoff/jitter et respect de Retry-After."""
    headers = headers or {}
    attempt = 0
    while True:
        attempt += 1
        try:
            async with session.request(method, url, headers=headers, params=params, data=data, timeout=timeout) as resp:
                text = await resp.text()
                if 200 <= resp.status < 300:
                    try:
                        return await resp.json()
                    except Exception:
                        return text
                if resp.status == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait = None
                    if retry_after:
                        try:
                            wait = int(retry_after)
                        except Exception:
                            wait = None
                    if wait is None:
                        wait = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    log.warning("429 received for %s (attempt %d/%d). Waiting %.1fs", url, attempt, max_retries, wait)
                    if attempt >= max_retries:
                        raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=text)
                    await asyncio.sleep(wait)
                    continue
                if 500 <= resp.status < 600:
                    wait = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    log.warning("Server error %d for %s; retrying in %.1fs (attempt %d/%d)", resp.status, url, wait, attempt, max_retries)
                    if attempt >= max_retries:
                        raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=text)
                    await asyncio.sleep(wait)
                    continue
                # other 4xx -> raise
                raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=text)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Request exception for %s (attempt %d/%d): %s", url, attempt, max_retries, exc)
            if attempt >= max_retries:
                raise
            wait = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            await asyncio.sleep(wait)
            continue


async def fetch_torrent_detail(
    session: aiohttp.ClientSession,
    token: str,
    torrent_id: str,
    upsert_fn: Callable[[Dict], Any],
    max_retries: int = 3,
):
    url = f"https://api.real-debrid.com/rest/1.0/torrents/info/{torrent_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        detail = await api_request(session, "GET", url, headers=headers, max_retries=max_retries)
        if detail:
            maybe = upsert_fn(detail)
            if asyncio.iscoroutine(maybe):
                await maybe
        return detail
    except aiohttp.ClientResponseError as cre:
        log.debug("Detail not found for %s: %s", torrent_id, cre)
        return None
    except Exception as e:
        log.exception("Error fetching detail for %s: %s", torrent_id, e)
        return None


async def fetch_all_torrents(
    token: str,
    upsert_fn: Callable[[Dict], Any],
    session: Optional[aiohttp.ClientSession] = None,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    page_wait: float = DEFAULT_PAGE_WAIT,
    max_pages: Optional[int] = None,
    detail_parallel: bool = False,
    detail_concurrency: int = 10,
    stop_event: Optional[asyncio.Event] = None,
):
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    headers = {"Authorization": f"Bearer {token}"}
    page = 1
    total = 0
    sem = asyncio.Semaphore(detail_concurrency) if detail_parallel else None
    pending = []

    try:
        while True:
            if stop_event and stop_event.is_set():
                log.info("Stop requested, breaking fetch_all_torrents")
                break

            if max_pages and page > max_pages:
                break

            params = {"page": page, "limit": page_limit}
            url = "https://api.real-debrid.com/rest/1.0/torrents"
            try:
                torrents = await api_request(session, "GET", url, headers=headers, params=params)
            except aiohttp.ClientResponseError as cre:
                log.warning("HTTP error fetching page %d: %s", page, cre)
                break
            except Exception as e:
                log.exception("Error fetching page %d: %s", page, e)
                await asyncio.sleep(page_wait * 2)
                break

            if not torrents:
                break

            # upsert page items immediately
            for t in torrents:
                maybe = upsert_fn(t)
                if asyncio.iscoroutine(maybe):
                    pending.append(maybe)

            total += len(torrents)
            log.info("Page %d: %d torrents (total %d)", page, len(torrents), total)

            # optionally fetch details in parallel
            if detail_parallel:
                for t in torrents:
                    tid = t.get("id")
                    if not tid:
                        continue
                    async def _run(tid=tid):
                        async with sem:
                            return await fetch_torrent_detail(session, token, tid, upsert_fn)
                    pending.append(asyncio.create_task(_run()))

            if len(torrents) < page_limit:
                break
            page += 1
            await asyncio.sleep(page_wait)

        if pending:
            log.info("Waiting for %d pending upserts/details...", len(pending))
            results = await asyncio.gather(*pending, return_exceptions=True)
            errs = sum(1 for r in results if isinstance(r, Exception))
            if errs:
                log.warning("%d detail tasks failed", errs)

        return total
    finally:
        if close_session:
            await session.close()
