import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


DEFAULT_LOG_FILE = Path(__file__).parents[1] / "logs" / "rd-monitor.log"


def setup_logger(log_file: Optional[str] = None, level: str = "INFO") -> None:
    """Configure le logger racine avec un RotatingFileHandler et un StreamHandler.

    Args:
        log_file: chemin du fichier de log (par défaut logs/rd-monitor.log)
        level: niveau de logging (INFO, DEBUG, ...)
    """
    if log_file is None:
        log_file = str(DEFAULT_LOG_FILE)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    # remove existing handlers and add ours
    logger.handlers.clear()
    logger.addHandler(fh)
    logger.addHandler(sh)


def get_logger(name: Optional[str] = None, log_file: Optional[str] = None, level: str = "INFO") -> logging.Logger:
    """Retourne un logger initialisé. Initialise la configuration si nécessaire.

    Args:
        name: nom du logger (None -> racine)
        log_file: chemin pour initialiser le handler si non encore fait
        level: niveau par défaut si initialisation
    """
    root = logging.getLogger()
    if not root.handlers:
        setup_logger(log_file=log_file, level=level)
    return logging.getLogger(name)
