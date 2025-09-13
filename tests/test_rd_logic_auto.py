import os
import sys
import pathlib

# Ensure project root is on sys.path so tests can import `rd_lib` when pytest
# is executed from the repository root or elsewhere.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from rd_lib.rd_logic import auto_fix_waiting, fix_one


class FakeAPI:
    def __init__(self, pages):
        # pages: list of lists of torrent dicts
        self.pages = pages
        self.info_store = {}

    def get_torrents(self, page=1, limit=100):
        idx = page - 1
        if idx < 0 or idx >= len(self.pages):
            return []
        return self.pages[idx]

    def get_torrent_info(self, tid):
        return self.info_store.get(tid, {})

    def select_files(self, tid, ids):
        # simulate selection: if ids provided, update info_store
        info = self.info_store.get(tid, {})
        info["status"] = "downloading"
        info["progress"] = 0
        self.info_store[tid] = info


def test_no_waiting():
    api = FakeAPI(pages=[[{"id": "1", "status": "seeding"}]])
    res = auto_fix_waiting(api, [".mkv"], include_subs=False, max_pages=2)
    assert res["found"] == 0
    assert res["fixed"] == 0


def test_waiting_no_videos():
    # torrent waiting but no video files in info
    api = FakeAPI(pages=[[{"id": "2", "status": "waiting_files_selection"}]])
    api.info_store["2"] = {"files": [{"path": "readme.txt", "id": "10"}], "status": "waiting_files_selection"}
    res = auto_fix_waiting(api, [".mkv"], include_subs=False, max_pages=2)
    assert res["found"] == 1
    assert res["fixed"] == 0


def test_waiting_with_videos_is_fixed():
    api = FakeAPI(pages=[[{"id": "3", "status": "waiting_files_selection"}]])
    api.info_store["3"] = {"files": [{"path": "movie.mkv", "id": "11"}], "status": "waiting_files_selection"}
    res = auto_fix_waiting(api, [".mkv"], include_subs=False, max_pages=2)
    assert res["found"] == 1
    assert res["fixed"] == 1
