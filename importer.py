"""Turn a Spotify track into a ready-to-play Dead as Disco custom song.

Pipeline (fully automatic):
    1. retrieve the track's Ogg from Spotify (audio_grabber)
    2. normalise to Audio.ogg @ 44.1kHz stereo (ffmpeg) -- avoids the 48kHz crash
    3. estimate tempo (librosa)
    4. write ImportedSongs/<Title - Artist>/{Audio.ogg, Meta.json}

Mirrors the layout the game's own importer produces, so the game treats these as
normal imported songs. Idempotent: an existing folder is skipped unless
overwrite_existing is set.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import subprocess
import threading
from pathlib import Path

from config import CONFIG, CACHE_DIR
from game_paths import imported_songs_dir
import audio_grabber
import tempo as tempo_mod

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_INT32_MAX = 2_147_483_647

# Serialize librespot reads (one session, not fully thread-safe) and cache tempo
# so preview + analyze + import all share a single retrieval per track.
_fetch_lock = threading.Lock()
_tempo_cache: dict[str, int] = {}


def ensure_source(track_id: str, uri: str) -> Path:
    """Retrieve the track's Ogg to cache/<id>.ogg once; return the cached path."""
    dest = CACHE_DIR / f"{track_id}.ogg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    # Bound the wait so a stuck retrieval elsewhere can't freeze this request forever.
    if not _fetch_lock.acquire(timeout=120):
        raise RuntimeError("Another track is being prepared — try again in a moment.")
    try:
        if not (dest.exists() and dest.stat().st_size > 0):
            audio_grabber.fetch_track(uri, dest)
    finally:
        _fetch_lock.release()
    return dest


def analyze_tempo(track_id: str, uri: str) -> int:
    """Estimated BPM for a track (cached). Retrieves the audio if needed."""
    if track_id in _tempo_cache:
        return _tempo_cache[track_id]
    src = ensure_source(track_id, uri)
    bpm = tempo_mod.estimate_tempo(str(src)) or int(CONFIG.get("default_tempo", 120))
    _tempo_cache[track_id] = bpm
    return bpm


def song_name(title: str, artists: list[str]) -> str:
    """Match the game's '<Title> - <Artist1, Artist2>' folder/song naming."""
    artist_str = ", ".join(artists)
    return f"{title} - {artist_str}" if artist_str else title


def sanitize(name: str) -> str:
    cleaned = _ILLEGAL.sub("", name).strip().rstrip(".")
    return cleaned or "Untitled"


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,sample_rate,channels",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(out.stdout)["streams"][0]
    except Exception:
        return {}


def _to_game_ogg(src: Path, dest: Path) -> None:
    """Copy if already Vorbis/44.1k/stereo, else transcode with ffmpeg."""
    info = _ffprobe(src)
    if (info.get("codec_name") == "vorbis"
            and info.get("sample_rate") == "44100"
            and str(info.get("channels")) == "2"):
        shutil.copyfile(src, dest)
        return
    q = str(CONFIG.get("ogg_quality", 8))
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(src), "-ar", "44100", "-ac", "2",
         "-c:a", "libvorbis", "-qscale:a", q, str(dest)],
        check=True,
    )


def import_track(meta: dict) -> dict:
    """Import one normalised track dict (from spotify_client.track_meta).

    Returns a status dict: {status: imported|skipped|error, name, tempo?, message?}.
    """
    name = song_name(meta["title"], meta.get("artists", []))
    folder_name = sanitize(name)
    dest_dir = imported_songs_dir() / folder_name

    if dest_dir.exists() and not CONFIG.get("overwrite_existing", False):
        return {"status": "skipped", "name": name, "message": "Already imported."}

    try:
        print(f"[import] {name}: preparing...", flush=True)
        # 1. retrieve raw Ogg from Spotify (cached; shared with preview/analyze)
        source = ensure_source(meta["id"], meta["uri"])

        # 2. normalise into the game's Audio.ogg
        print(f"[import] {name}: converting to 44.1kHz...", flush=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        audio_ogg = dest_dir / "Audio.ogg"
        _to_game_ogg(source, audio_ogg)

        # 3. tempo (reuses the cached estimate if preview/analyze already ran)
        print(f"[import] {name}: analysing tempo...", flush=True)
        if CONFIG.get("auto_tempo", True):
            tempo = analyze_tempo(meta["id"], meta["uri"])
        else:
            tempo = int(CONFIG.get("default_tempo", 120))
        print(f"[import] {name}: done ({tempo} BPM)", flush=True)

        # 4. Meta.json (mirrors the game's own schema, version 1)
        meta_json = {
            "version": 1,
            "uniqueId": random.randint(1, _INT32_MAX),
            "songName": name,
            "performedBy": [],
            "writtenBy": [],
            "seed": random.randint(1, _INT32_MAX),
            "tempo": tempo,
            "customTempoSections": [],
            "beatOffset": 0,
            "startSongOffset": 0,
            "endSongOffset": 0,
            "uEAssetName": name,
            "originalAudioFileHash": _md5(source),
            "originalAudioFilePath": str(source).replace("\\", "/"),
        }
        with open(dest_dir / "Meta.json", "w", encoding="utf-8") as f:
            json.dump(meta_json, f, indent=4)

        return {"status": "imported", "name": name, "tempo": tempo}

    except Exception as e:
        # Clean up a half-written folder so a retry starts fresh.
        if dest_dir.exists() and not any(dest_dir.iterdir()):
            try:
                dest_dir.rmdir()
            except OSError:
                pass
        return {"status": "error", "name": name, "message": str(e)}
