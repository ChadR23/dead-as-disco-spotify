"""Spotify Web API access (clean / official) for browsing playlists, liked songs,
and search. Uses spotipy with the Authorization Code flow.

This is the plain Web API half (browse/search/metadata). The audio retrieval lives
in audio_grabber.py.
"""
from __future__ import annotations

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config import CONFIG, HERE

# user-read-private is required for the 'product' (premium/free) field on current_user.
SCOPES = "playlist-read-private playlist-read-collaborative user-library-read user-read-private"

_auth: SpotifyOAuth | None = None
_client: spotipy.Spotify | None = None


def _auth_manager() -> SpotifyOAuth:
    """The shared OAuth manager. open_browser=False so spotipy never tries to start
    its own callback server (our Flask app owns the redirect port and handles the
    callback itself)."""
    global _auth
    if _auth is None:
        if not CONFIG["spotify_client_id"] or not CONFIG["spotify_client_secret"]:
            raise RuntimeError(
                "spotify_client_id / spotify_client_secret are not set in config.json. "
                "Register an app at https://developer.spotify.com/dashboard and paste them in."
            )
        _auth = SpotifyOAuth(
            client_id=CONFIG["spotify_client_id"],
            client_secret=CONFIG["spotify_client_secret"],
            redirect_uri=CONFIG["spotify_redirect_uri"],
            scope=SCOPES,
            cache_path=str(HERE / ".spotipy_cache"),
            open_browser=False,
        )
    return _auth


def authorize_url() -> str:
    """URL to send the user to for granting access."""
    return _auth_manager().get_authorize_url()


def complete_auth(code: str) -> None:
    """Exchange the ?code from the redirect for an access token and cache it."""
    _auth_manager().get_access_token(code, as_dict=False, check_cache=False)


def is_authed() -> bool:
    """True if we hold a cached token (spotipy auto-refreshes expired ones on use)."""
    try:
        token = _auth_manager().cache_handler.get_cached_token()
        return token is not None
    except Exception:
        return False


def get_client() -> spotipy.Spotify:
    """Return a Spotify Web API client backed by the cached token (non-interactive)."""
    global _client
    if _client is None:
        _client = spotipy.Spotify(auth_manager=_auth_manager(), requests_timeout=30, retries=3)
    return _client


def _image(images: list[dict] | None) -> str:
    if not images:
        return ""
    # images come largest-first; pick a mid-size one if available
    return (images[1] if len(images) > 1 else images[0]).get("url", "")


def track_meta(track: dict) -> dict | None:
    """Normalise a Spotify track object into the fields the UI + importer need."""
    if not track or not track.get("id") or track.get("is_local"):
        return None
    return {
        "id": track["id"],
        "uri": track["uri"],
        "title": track["name"],
        "artists": [a["name"] for a in track.get("artists", [])],
        "artist_str": ", ".join(a["name"] for a in track.get("artists", [])),
        "album": (track.get("album") or {}).get("name", ""),
        "duration_ms": track.get("duration_ms", 0),
        "image_url": _image((track.get("album") or {}).get("images")),
    }


def current_user() -> dict:
    u = get_client().current_user()
    return {
        "id": u["id"],
        "name": u.get("display_name") or u["id"],
        "product": u.get("product", "unknown"),  # 'premium' required to import audio
    }


def list_playlists() -> list[dict]:
    sp = get_client()
    out: list[dict] = []
    results = sp.current_user_playlists(limit=50)
    while results:
        for pl in results["items"]:
            if not pl:
                continue
            out.append({
                "id": pl["id"],
                "name": pl["name"],
                "image_url": _image(pl.get("images")),
                "count": (pl.get("tracks") or {}).get("total", 0),
            })
        results = sp.next(results) if results.get("next") else None
    return out


def list_playlist_tracks(playlist_id: str) -> list[dict]:
    sp = get_client()
    out: list[dict] = []
    results = sp.playlist_items(playlist_id, additional_types=("track",), limit=100)
    while results:
        for item in results["items"]:
            m = track_meta((item or {}).get("track"))
            if m:
                out.append(m)
        results = sp.next(results) if results.get("next") else None
    return out


def list_liked() -> list[dict]:
    sp = get_client()
    out: list[dict] = []
    results = sp.current_user_saved_tracks(limit=50)
    while results:
        for item in results["items"]:
            m = track_meta((item or {}).get("track"))
            if m:
                out.append(m)
        results = sp.next(results) if results.get("next") else None
    return out


def search(query: str, limit: int = 30) -> list[dict]:
    sp = get_client()
    res = sp.search(q=query, type="track", limit=limit)
    return [m for m in (track_meta(t) for t in res["tracks"]["items"]) if m]
