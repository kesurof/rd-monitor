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

def fix_one(api, tid: str, video_exts: List[str], include_subs: bool) -> Dict:
    info = api.get_torrent_info(tid)
    status = info.get("status")
    if status != "waiting_files_selection":
        return {"id": tid, "changed": False, "status": status, "reason": "not_waiting"}
    ids = extract_ids(info, video_exts, include_subs)
    if not ids:
        return {"id": tid, "changed": False, "status": status, "reason": "no_video_files"}
    api.select_files(tid, ids)
    time.sleep(1.0)
    info2 = api.get_torrent_info(tid)
    return {"id": tid, "changed": True, "status": info2.get("status"), "selected_count": len(ids), "progress": info2.get("progress")}
