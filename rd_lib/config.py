import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DEFAULT_CFG_FILE = CONFIG_DIR / "config.yaml"
LOCAL_CFG_FILE = CONFIG_DIR / "config.yaml.local"

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CFG_FILE.exists():
        DEFAULT_CFG_FILE.write_text("monitoring:\n  check_interval: 90\nreal_debrid:\n  token: \"\"\n  video_extensions: [\".mkv\", \".mp4\", \".avi\", \".mov\", \".m4v\"]\n  include_subtitles: false\ndocker:\n  enabled: true\n  watch_names: [\"rdt-client\", \"debrid-media-manager\"]\nlogging:\n  level: \"INFO\"\n  file: \"logs/rd-monitor.log\"\n")
    load_dotenv(ROOT / ".env", override=False)
    cfg = {}
    with open(DEFAULT_CFG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if LOCAL_CFG_FILE.exists():
        with open(LOCAL_CFG_FILE, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
            cfg = deep_merge(cfg, local)

    # Env overrides
    token = os.getenv("REAL_DEBRID_TOKEN")
    if token:
        cfg.setdefault("real_debrid", {})["token"] = token
    ve = os.getenv("VIDEO_EXTENSIONS")
    if ve:
        cfg.setdefault("real_debrid", {})["video_extensions"] = [x.strip().lower() for x in ve.split(",") if x.strip()]
    incs = os.getenv("INCLUDE_SUBTITLES")
    if incs:
        cfg.setdefault("real_debrid", {})["include_subtitles"] = incs.lower() == "true"
    ci = os.getenv("CHECK_INTERVAL_SECONDS")
    if ci:
        cfg.setdefault("monitoring", {})["check_interval"] = int(ci)
    ll = os.getenv("LOG_LEVEL")
    if ll:
        cfg.setdefault("logging", {})["level"] = ll

    return cfg

def deep_merge(a, b):
    if not isinstance(b, dict):
        return b
    result = dict(a)
    for k, v in b.items():
        if k in result and isinstance(result[k], dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def save_local(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_CFG_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
