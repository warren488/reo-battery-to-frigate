"""Persist web-UI tuned parameters so they survive container restarts.

Storage is a single JSON file: {"encoder": {...}, "streaming": {...}}.
All failures are soft — a missing, corrupt, or unwritable file must never
take the stream down.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def load_params(path: Path) -> dict:
    """Return the saved params dict, or {} if the file is missing or invalid."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("params file is not a JSON object")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable params file %s: %s", path, e)
        return {}


def save_params(path: Path, params: dict) -> None:
    """Atomically write the params file. Failure is logged, never raised."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Could not persist params to %s: %s", path, e)
