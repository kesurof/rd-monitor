import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from typing import Optional, Any, Dict


class RealDebridAPI:
    BASE = "https://api.real-debrid.com/rest/1.0"

    def __init__(self, token: str, timeout: int = 20, max_retries: int = 4, backoff_factor: float = 1.0):
        self.token = (token or "").strip()
        if not self.token:
            raise RuntimeError("REAL_DEBRID_TOKEN manquant")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        # session with retry for idempotent requests; also handle 429 explicitly
        self.session = requests.Session()
        retries = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "PUT", "DELETE", "HEAD"),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "application/json"})

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.BASE}{path}"
        attempt = 0
        while True:
            attempt += 1
            r = self.session.request(method, url, timeout=self.timeout, **kwargs)
            # If successful, return
            if r.status_code < 400:
                return r

            # Respect Retry-After header for 429
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = None
                if retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        # could be a HTTP-date; fallback to backoff
                        wait = None
                if wait is None:
                    wait = int(self.backoff_factor * (2 ** (attempt - 1)))
                if attempt <= self.max_retries:
                    time.sleep(wait)
                    continue
                # retries exhausted
                r.raise_for_status()

            # For other 5xx we may retry up to max_retries
            if 500 <= r.status_code < 600 and attempt <= self.max_retries:
                wait = int(self.backoff_factor * (2 ** (attempt - 1)))
                time.sleep(wait)
                continue

            # Otherwise raise
            r.raise_for_status()

    def get_torrents(self, page: int = 1, limit: int = 100) -> Any:
        params = {"page": page, "limit": limit}
        r = self._request("GET", "/torrents", params=params)
        return r.json()

    def get_torrent_info(self, tid: str) -> Any:
        r = self._request("GET", f"/torrents/info/{tid}")
        return r.json()

    def select_files(self, tid: str, file_ids) -> None:
        data = {"files": ",".join(str(i) for i in file_ids)}
        r = self._request("POST", f"/torrents/selectFiles/{tid}", data=data)
        # accept 200 or 204
        if r.status_code not in (200, 204):
            r.raise_for_status()
