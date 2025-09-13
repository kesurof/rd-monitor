import requests

class RealDebridAPI:
    BASE = "https://api.real-debrid.com/rest/1.0"

    def __init__(self, token: str, timeout: int = 20):
        self.token = token.strip()
        if not self.token:
            raise RuntimeError("REAL_DEBRID_TOKEN manquant")
        self.timeout = timeout

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get_torrents(self, page=1, limit=100):
        params = {"page": page, "limit": limit}
        r = requests.get(f"{self.BASE}/torrents", headers=self._headers(), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_torrent_info(self, tid: str):
        r = requests.get(f"{self.BASE}/torrents/info/{tid}", headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def select_files(self, tid: str, file_ids):
        data = {"files": ",".join(str(i) for i in file_ids)}
        r = requests.post(f"{self.BASE}/torrents/selectFiles/{tid}", headers=self._headers(), data=data, timeout=self.timeout)
        if r.status_code not in (200, 204):
            r.raise_for_status()
