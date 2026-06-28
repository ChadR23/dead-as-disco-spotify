"""Locate the Dead as Disco (Unreal project "Pagoda") imported-songs folder.

Custom songs live at:
    %LOCALAPPDATA%\\Pagoda\\Saved\\ImportedSongs\\<Title - Artist>\\
        Audio.ogg   (Ogg Vorbis, 44.1kHz, stereo)
        Meta.json   (tempo, seed, ids, ...)

The game scans this directory on startup / when entering song select, so newly
written folders appear after a game restart (or re-entering the menu).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from config import CONFIG

GAME_PROCESS = "PagodaSteam-Win64-Shipping.exe"


def imported_songs_dir() -> Path:
    """Return the ImportedSongs directory, creating it if needed."""
    override = (CONFIG.get("imported_songs_dir") or "").strip()
    if override:
        base = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("LOCALAPPDATA is not set; cannot locate the game folder.")
        base = Path(local) / "Pagoda" / "Saved" / "ImportedSongs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def existing_song_names() -> set[str]:
    """Folder names already present in ImportedSongs (used for the 'imported' badge)."""
    d = imported_songs_dir()
    return {p.name for p in d.iterdir() if p.is_dir()} if d.exists() else set()


def is_game_running() -> bool:
    """Best-effort check so we can warn the user to restart for songs to show up."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}"],
            capture_output=True, text=True, timeout=5,
        )
        return GAME_PROCESS.lower() in out.stdout.lower()
    except Exception:
        return False
