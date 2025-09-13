import logging
from typing import List, Dict, Optional
import docker

log = logging.getLogger("rd.docker")

def list_containers(names: List[str]) -> List[Dict]:
    client = docker.from_env()
    results = []
    for c in client.containers.list(all=True):
        try:
            info = c.attrs
            name = (c.name or "").lower()
            if any(n.lower() in name for n in names):
                ip = None
                nets = info.get("NetworkSettings", {}).get("Networks", {}) or {}
                if nets:
                    ip = next((v.get("IPAddress") for v in nets.values() if v.get("IPAddress")), None)
                results.append({
                    "name": c.name,
                    "status": info.get("State", {}).get("Status"),
                    "ip": ip,
                    "image": info.get("Config", {}).get("Image")
                })
        except Exception as e:
            log.warning(f"Docker parse error: {e}")
    return results
