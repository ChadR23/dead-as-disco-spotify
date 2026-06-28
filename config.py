"""Configuration loading for the Dead as Disco Spotify companion.

Reads config.json (falling back to config.example.json defaults) and exposes a
single CONFIG dict plus a few resolved paths. Keep this module dependency-free so
every other module can import it cheaply.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
EXAMPLE_PATH = HERE / "config.example.json"

# Where librespot caches the Spotify Premium login so the user only authorises once.
CREDENTIALS_PATH = HERE / "credentials.json"
# Local audio cache (used for the md5 + as the "original" file the game records).
# Kept so re-imports are cheap and hashes stay stable.
CACHE_DIR = HERE / "cache"

_DEFAULTS = {
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "spotify_redirect_uri": "http://127.0.0.1:8765/callback",
    "imported_songs_dir": "",
    "port": 8765,
    "ogg_quality": 8,
    "auto_tempo": True,
    "default_tempo": 120,
    "overwrite_existing": False,
}


def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        raise FileNotFoundError(
            f"No config.json found. Copy config.example.json to config.json and fill in "
            f"your Spotify app credentials.\nExpected at: {CONFIG_PATH}"
        )
    return cfg


CONFIG = load_config()
CACHE_DIR.mkdir(exist_ok=True)
