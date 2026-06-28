"""Local web app: browse your Spotify, click a track, it lands in Dead as Disco.

Run:  python app.py
Then your browser opens to http://127.0.0.1:<port>/ .

The Spotify Web API half (browse/search) is official. The audio import half
(librespot) requires Spotify Premium and is for personal use only.
"""
from __future__ import annotations

import sys
import threading
import webbrowser

# Force UTF-8 console output so logging song names with non-Latin characters
# (Japanese, accents, etc.) can't crash an import on Windows (cp1252 default).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory

from config import CONFIG
import spotify_client
import audio_grabber
import game_paths
import importer

app = Flask(__name__, static_folder="static", template_folder="templates")


@app.get("/")
def index():
    return send_from_directory("templates", "index.html")


@app.get("/login")
def login():
    """Send the user to Spotify to authorise the Web API (browse/search)."""
    return redirect(spotify_client.authorize_url())


@app.get("/callback")
def callback():
    """Spotify redirects here with ?code=...; exchange it for a token, then go home."""
    err = request.args.get("error")
    if err:
        return f"Spotify authorisation failed: {err}. You can close this tab and retry.", 400
    code = request.args.get("code")
    if not code:
        return "Missing authorisation code.", 400
    try:
        spotify_client.complete_auth(code)
    except Exception as e:
        return f"Failed to complete Spotify login: {e}", 500
    return redirect("/")


@app.get("/api/me")
def api_me():
    if not spotify_client.is_authed():
        return jsonify({"ok": True, "authed": False, "login_url": "/login"})
    try:
        user = spotify_client.current_user()
        return jsonify({
            "ok": True,
            "authed": True,
            "user": user,
            "premium": user.get("product") == "premium",
            "audio_logged_in": audio_grabber.has_cached_login(),
            "game_running": game_paths.is_game_running(),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _require_auth():
    """Return a (json, status) tuple if not authed, else None."""
    if not spotify_client.is_authed():
        return jsonify({"ok": False, "error": "Not connected to Spotify.", "login_url": "/login"}), 401
    return None


@app.get("/api/playlists")
def api_playlists():
    guard = _require_auth()
    if guard:
        return guard
    try:
        return jsonify({"ok": True, "playlists": spotify_client.list_playlists()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/playlist/<playlist_id>/tracks")
def api_playlist_tracks(playlist_id: str):
    guard = _require_auth()
    if guard:
        return guard
    try:
        return jsonify({"ok": True, "tracks": spotify_client.list_playlist_tracks(playlist_id)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/liked")
def api_liked():
    guard = _require_auth()
    if guard:
        return guard
    try:
        return jsonify({"ok": True, "tracks": spotify_client.list_liked()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/search")
def api_search():
    guard = _require_auth()
    if guard:
        return guard
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": True, "tracks": []})
    try:
        return jsonify({"ok": True, "tracks": spotify_client.search(q)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/imported")
def api_imported():
    try:
        return jsonify({"ok": True, "names": sorted(game_paths.existing_song_names())})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/analyze/<track_id>")
def api_analyze(track_id: str):
    guard = _require_auth()
    if guard:
        return guard
    uri = request.args.get("uri")
    if not uri:
        return jsonify({"ok": False, "error": "Missing track uri."}), 400
    try:
        return jsonify({"ok": True, "tempo": importer.analyze_tempo(track_id, uri)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/preview/<track_id>")
def api_preview(track_id: str):
    """Stream the (cached) full track for in-browser preview. Needs Premium."""
    guard = _require_auth()
    if guard:
        return guard
    uri = request.args.get("uri")
    if not uri:
        return "Missing track uri.", 400
    try:
        src = importer.ensure_source(track_id, uri)
    except Exception as e:
        return f"Preview failed: {e}", 500
    return send_file(str(src), mimetype="audio/ogg", conditional=True)


@app.post("/api/import")
def api_import():
    meta = request.get_json(force=True, silent=True) or {}
    if not meta.get("uri") or not meta.get("id"):
        return jsonify({"status": "error", "message": "Missing track uri/id."}), 400
    result = importer.import_track(meta)
    code = 200 if result["status"] in ("imported", "skipped") else 500
    return jsonify(result), code


def _open_browser(port: int):
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()


def main():
    port = int(CONFIG.get("port", 8765))
    print(f"Dead as Disco x Spotify -> http://127.0.0.1:{port}/")
    print(f"Imported songs go to: {game_paths.imported_songs_dir()}")
    _open_browser(port)
    # threaded so a slow import doesn't freeze browsing; debug off to avoid double-open.
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
