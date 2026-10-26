from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)(\S+)"),
]


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.getMessage())
        record.args = ()
        return True


def _redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}***", text)
        else:
            text = pattern.sub("sk-***", text)
    return text


def setup_logging(log_dir: Path, *, debug: bool = False) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "paperflow.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redactor = RedactSecretsFilter()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)
    root.addHandler(file_handler)

    if debug:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(redactor)
        root.addHandler(stream)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("keyring").setLevel(logging.WARNING)
    return log_file