"""Logging setup."""

import logging
import logging.config
from pathlib import Path

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logger(name: str = "argus", log_file: str = "outputs/logs/argus.log") -> logging.Logger:
    """Configure and return the application logger.

    Args:
        name: Logger name.
        log_file: Path to log file.
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))

    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger
