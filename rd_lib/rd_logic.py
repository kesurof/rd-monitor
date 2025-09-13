import logging
import time
from typing import List, Dict

log = logging.getLogger("rd.logic")

def is_video(path: str, exts: List[str]) -> bool:
    p = (path or "").lower()
    return any(p.endswith(e) for e in exts)

def is_sub(path: str) -> bool:
    p = (path or "").lower()
    return p.endswith(".srt") or p.endswith(".ass")

def extract_ids(info: Dict, video_exts: List[str], include_subs: bool) -> List[int]:
    ids = []
    for f in info.get("files", []):
        path = f.get("path") or f.get("filename") or ""
        if is_video(path, video_exts) or (include_subs and is_sub(path)):
            try:
                ids.append(int(f.get("id")))
            except Exception:
                pass
    return ids

def fix_one(api, tid: str, video_exts: List[str], include_subs: bool, skip_precheck: bool = False, sleep_after_select: float = 0.0) -> Dict:
    # If skip_precheck is False we try a lightweight pre-check over recent pages to
    # avoid unnecessary 404s; when we already have the torrent list item (from
    # get_torrents) callers should set skip_precheck=True to go straight to info.
    try:
        if not skip_precheck:
            found = False
            for p in range(1, 4):
                try:
                    items = api.get_torrents(page=p, limit=100)
                except Exception:
                    items = []
                for t in items:
                    if t.get("id") == tid:
                        found = True
                        break
                if found:
                    break
            if not found:
                log.info(f"Torrent {tid} non listé dans les pages récentes, skip")
                return {"id": tid, "changed": False, "status": None, "reason": "not_listed"}

        info = api.get_torrent_info(tid)
    except Exception as e:
        log.warning(f"Impossible d'obtenir les infos du torrent {tid}: {e}")
        return {"id": tid, "changed": False, "status": None, "reason": "not_found_or_error", "error": str(e)}

    status = info.get("status")
    if status != "waiting_files_selection":
        return {"id": tid, "changed": False, "status": status, "reason": "not_waiting"}

    ids = extract_ids(info, video_exts, include_subs)
    if not ids:
        return {"id": tid, "changed": False, "status": status, "reason": "no_video_files"}
    try:
        api.select_files(tid, ids)
    except Exception as e:
        log.exception(f"Erreur lors de la sélection des fichiers pour {tid}: {e}")
        return {"id": tid, "changed": False, "status": status, "reason": "select_failed", "error": str(e)}

    # Optionally sleep after selection to let the backend process and avoid bursts
    if sleep_after_select and sleep_after_select > 0:
        time.sleep(float(sleep_after_select))
    try:
        info2 = api.get_torrent_info(tid)
    except Exception as e:
        log.warning(f"Impossible d'obtenir les infos (après sélection) du torrent {tid}: {e}")
        return {"id": tid, "changed": True, "status": None, "selected_count": len(ids), "reason": "post_select_info_missing", "error": str(e)}

    return {"id": tid, "changed": True, "status": info2.get("status"), "selected_count": len(ids), "progress": info2.get("progress")}


def auto_fix_waiting(api, video_exts: List[str], include_subs: bool, page_start: int = 1, page_limit: int = 100, max_pages: int = 5):
    """Parcourt les pages de torrents et appelle fix_one sur chaque torrent dont le status == 'waiting_files_selection'.

    Retourne un résumé simple : {
        'scanned_pages': n,
        'found': total_found,
        'fixed': total_fixed,
        'skipped': total_skipped,
        'errors': total_errors
    }

    Conception volontairement simple : page_start (1-based), page_limit (items/page), max_pages limite le scan pour éviter trop de travail.
    """
    log = logging.getLogger("rd.logic.auto")
    scanned = 0
    found = 0
    fixed = 0
    skipped = 0
    errors = 0

    page = page_start
    while True:
        if max_pages is not None and scanned >= max_pages:
            break
        try:
            items = api.get_torrents(page=page, limit=page_limit)
        except Exception as e:
            log.exception(f"Erreur get_torrents page {page}: {e}")
            errors += 1
            break

        if not items:
            break

        for t in items:
            tid = t.get("id")
            status = t.get("status")
            if status == "waiting_files_selection" or status == "magnet_conversion":
                # list may show 'magnet_conversion' while detailed info shows
                # 'waiting_files_selection' — skip_precheck=True avoids redundant page search
                found += 1
                try:
                    res = fix_one(api, tid, video_exts, include_subs, skip_precheck=True)
                    if res.get("changed"):
                        fixed += 1
                        log.info(f"Auto-fixed {tid}: {res}")
                    else:
                        skipped += 1
                        log.info(f"Skipped {tid}: {res}")
                except Exception as e:
                    errors += 1
                    log.exception(f"Erreur lors de fix_one pour {tid}: {e}")

        scanned += 1
        if len(items) < page_limit:
            break
        page += 1

    return {
        "scanned_pages": scanned,
        "found": found,
        "fixed": fixed,
        "skipped": skipped,
        "errors": errors,
    }
