"""Retrieve a track's audio from Spotify via librespot and write it as an Ogg file.

librespot signs in with a Spotify **Premium** account and reads the Ogg Vorbis
stream. Kept isolated here so the rest of the app stays on the plain Web API.

For personal use only. Requires Spotify Premium.
"""
from __future__ import annotations

import concurrent.futures
import threading
import webbrowser
from pathlib import Path

from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import Session
from librespot.metadata import TrackId

# Hard cap so an unavailable/region-locked track fails cleanly instead of hanging.
FETCH_TIMEOUT_S = 90

from config import CREDENTIALS_PATH, CONFIG

_session: Session | None = None
_lock = threading.Lock()

# Shown in the librespot login tab after the user authorises, instead of librespot's
# bare "received callback" text. Auto-bounces back to the app.
_APP_URL = f"http://127.0.0.1:{int(CONFIG.get('port', 8765))}/"
SUCCESS_PAGE = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Connected</title>
<meta http-equiv="refresh" content="2;url={_APP_URL}">
<style>
  body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:'Segoe UI',system-ui,sans-serif;text-align:center;
       background:radial-gradient(900px 500px at 70% -10%,#2a0f3a,#0b0712 60%);color:#f3eaff}}
  h1{{font-size:26px;margin:0 0 8px}} .tick{{color:#38e08a}}
  p{{color:#9a8cc2}} a{{color:#36e0ff}}
</style></head><body><div>
  <h1><span class="tick">✓</span> Spotify Premium connected</h1>
  <p>All set — taking you back to the app…</p>
  <p><a href="{_APP_URL}">Click here if it doesn't redirect.</a></p>
</div></body></html>"""

# Surfaced to the UI so the front-end can show "open this URL to authorise Spotify".
PENDING_AUTH_URL: str | None = None


def _oauth_callback(url: str) -> str:
    """librespot calls this with the authorise URL during first-time login."""
    global PENDING_AUTH_URL
    PENDING_AUTH_URL = url
    print("\n=== Spotify Premium login required (one time) ===")
    print(url)
    print("=================================================\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return url


def has_cached_login() -> bool:
    return CREDENTIALS_PATH.is_file()


def get_session() -> Session:
    """Return a cached librespot session, creating (and logging in) on first use.

    The first call without a cached credentials.json blocks until the user
    completes the OAuth flow in their browser (librespot runs its own callback
    server on 127.0.0.1:5588).
    """
    global _session, PENDING_AUTH_URL
    with _lock:
        if _session is None:
            builder = Session.Builder()
            # builder.oauth() auto-reuses conf.stored_credentials_file when present.
            builder.conf.stored_credentials_file = str(CREDENTIALS_PATH)
            if CREDENTIALS_PATH.is_file():
                builder.stored_file(str(CREDENTIALS_PATH))
            else:
                builder.oauth(_oauth_callback, SUCCESS_PAGE)
            _session = builder.create()
            PENDING_AUTH_URL = None
        return _session


def fetch_track(track_uri: str, dest: Path) -> Path:
    """Retrieve `track_uri` (spotify:track:...) as an Ogg Vorbis file at `dest`.

    librespot hands back the Ogg Vorbis container, so we stream it straight to disk
    without transcoding.
    """
    # Run the (blocking) librespot read in a worker thread so we can enforce a
    # timeout. An unavailable track can otherwise hang forever inside load().
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_do_fetch, track_uri, dest)
    try:
        result = fut.result(timeout=FETCH_TIMEOUT_S)
        ex.shutdown(wait=False)
        return result
    except concurrent.futures.TimeoutError:
        ex.shutdown(wait=False)  # don't block on the stuck worker
        raise RuntimeError(
            f"Timed out after {FETCH_TIMEOUT_S}s — this track is likely unavailable "
            f"to stream (region-locked, or not playable on Spotify Connect)."
        )


def _do_fetch(track_uri: str, dest: Path) -> Path:
    print(f"[grab] loading {track_uri} ...", flush=True)
    session = get_session()
    track_id = TrackId.from_uri(track_uri)
    stream = session.content_feeder().load(
        track_id, VorbisOnlyAudioQuality(AudioQuality.VERY_HIGH), False, None
    )
    inp = stream.input_stream.stream()
    total = getattr(stream.input_stream, "size", None)
    print(f"[grab] reading {total or '?'} bytes -> {dest.name}", flush=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write to a .part file and rename on success, so an interrupted/timed-out
    # transfer never leaves a corrupt 'complete' file behind.
    part = dest.with_suffix(".part")
    written = 0
    with open(part, "wb") as f:
        while True:
            to_read = 64 * 1024
            if total is not None:
                remaining = total - written
                if remaining <= 0:
                    break
                to_read = min(to_read, remaining)
            chunk = inp.read(to_read)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)

    if written == 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Got 0 bytes for {track_uri} (track unavailable?).")
    part.replace(dest)
    print(f"[grab] done: {dest.name} ({written} bytes)", flush=True)
    return dest
