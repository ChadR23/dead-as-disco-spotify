"use strict";

const $ = (sel) => document.querySelector(sel);
const grid = $("#grid");
const titleEl = $("#contentTitle");
const emptyEl = $("#empty");
const bannerEl = $("#banner");

let importedNames = new Set();

// --- Preview playback (one shared player) ---
const player = new Audio();
let playingId = null;
let playingBtn = null;

function stopPlayback() {
  player.pause();
  if (playingBtn) { playingBtn.classList.remove("playing"); playingBtn.innerHTML = "▶"; }
  playingBtn = null;
  playingId = null;
}
player.addEventListener("ended", stopPlayback);

async function togglePreview(t, btn, bpmEl) {
  if (playingId === t.id) { stopPlayback(); return; }
  stopPlayback();
  btn.innerHTML = '<span class="spin"></span>';
  fetchBpm(t, bpmEl); // analyse in parallel (same cached audio)
  player.src = `/api/preview/${t.id}?uri=${encodeURIComponent(t.uri)}`;
  try {
    await player.play();
    playingId = t.id;
    playingBtn = btn;
    btn.classList.add("playing");
    btn.innerHTML = "⏸";
  } catch (e) {
    btn.innerHTML = "▶";
    banner(`Preview failed (needs Premium): ${e}`, true);
  }
}

async function fetchBpm(t, bpmEl) {
  if (bpmEl.dataset.done) return;
  bpmEl.textContent = "…";
  bpmEl.disabled = true;
  const d = await getJSON(`/api/analyze/${t.id}?uri=${encodeURIComponent(t.uri)}`);
  if (d.ok) {
    bpmEl.textContent = `${d.tempo} BPM`;
    bpmEl.dataset.done = "1";
  } else {
    bpmEl.textContent = "BPM?";
    bpmEl.disabled = false;
    banner(`Couldn’t analyse BPM (needs Premium): ${d.error}`, true);
  }
}

function songName(t) {
  const artists = (t.artists || []).join(", ");
  return artists ? `${t.title} - ${artists}` : t.title;
}

function banner(msg, isErr) {
  if (!msg) { bannerEl.classList.add("hidden"); return; }
  bannerEl.textContent = msg;
  bannerEl.classList.toggle("err", !!isErr);
  bannerEl.classList.remove("hidden");
}

async function getJSON(url) {
  const r = await fetch(url);
  return r.json();
}

async function loadUser() {
  const d = await getJSON("/api/me");
  if (!d.ok) { $("#user").textContent = "Spotify error"; banner(d.error, true); return false; }
  if (!d.authed) {
    $("#user").innerHTML = `<a class="connect" href="${d.login_url}">Connect Spotify →</a>`;
    titleEl.textContent = "Connect your Spotify to start";
    grid.innerHTML = "";
    emptyEl.classList.add("hidden");
    banner("Click “Connect Spotify” (top right) to authorise browsing your playlists.");
    return false;
  }
  const u = d.user;
  let prem;
  if (d.premium) {
    prem = '<span class="badge">Premium</span>';
  } else if (u.product === "free" || u.product === "open") {
    prem = '<span class="badge no">Free — importing audio needs Premium</span>';
  } else {
    prem = '<span class="badge">connected</span>'; // product unknown; don't claim no-Premium
  }
  $("#user").innerHTML = `${u.name} · ${prem}`;
  if (d.game_running) {
    banner("Heads up: the game is running. Restart it (or re-enter song select) for newly imported songs to appear.");
  }
  return true;
}

async function loadImported() {
  const d = await getJSON("/api/imported");
  if (d.ok) importedNames = new Set(d.names);
}

async function loadPlaylists() {
  const d = await getJSON("/api/playlists");
  if (!d.ok) { banner(d.error, true); return; }
  const list = $("#playlistList");
  list.innerHTML = "";
  for (const pl of d.playlists) {
    const b = document.createElement("button");
    b.className = "pl";
    b.dataset.kind = "playlist";
    b.dataset.id = pl.id;
    b.innerHTML = `${pl.name} <span class="cnt">${pl.count}</span>`;
    b.onclick = () => selectSource(b, pl.name, `/api/playlist/${pl.id}/tracks`);
    list.appendChild(b);
  }
}

function setActive(btn) {
  document.querySelectorAll(".pl").forEach((p) => p.classList.remove("active"));
  if (btn) btn.classList.add("active");
}

async function selectSource(btn, title, url) {
  setActive(btn);
  titleEl.textContent = title;
  grid.innerHTML = '<div class="empty"><span class="spin"></span> Loading…</div>';
  const d = await getJSON(url);
  if (!d.ok) { grid.innerHTML = ""; banner(d.error, true); return; }
  renderTracks(d.tracks);
}

function renderTracks(tracks) {
  stopPlayback();
  grid.innerHTML = "";
  emptyEl.classList.toggle("hidden", tracks.length > 0);
  for (const t of tracks) grid.appendChild(card(t));
}

function card(t) {
  const el = document.createElement("div");
  el.className = "card";
  const cover = t.image_url || "";
  el.innerHTML = `
    ${cover ? `<img class="cover" src="${cover}" loading="lazy" />` : `<div class="cover"></div>`}
    <div class="title">${escapeHtml(t.title)}</div>
    <div class="artist">${escapeHtml((t.artists || []).join(", "))}</div>
  `;

  // controls row: preview play + BPM
  const controls = document.createElement("div");
  controls.className = "controls";
  const play = document.createElement("button");
  play.className = "play";
  play.title = "Preview (plays the full track)";
  play.innerHTML = "▶";
  const bpm = document.createElement("button");
  bpm.className = "bpm";
  bpm.title = "Estimate BPM";
  bpm.textContent = "BPM?";
  bpm.onclick = () => fetchBpm(t, bpm);
  play.onclick = () => togglePreview(t, play, bpm);
  controls.append(play, bpm);
  el.appendChild(controls);

  const btn = document.createElement("button");
  btn.className = "btn";
  if (importedNames.has(songName(t))) {
    btn.classList.add("imported");
    btn.textContent = "✓ Imported";
    btn.disabled = true;
  } else {
    btn.textContent = "Import to game";
    btn.onclick = () => doImport(t, btn);
  }
  el.appendChild(btn);
  return el;
}

async function doImport(t, btn) {
  btn.disabled = true;
  btn.className = "btn working";
  btn.innerHTML = '<span class="spin"></span> Importing…';
  try {
    const r = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(t),
    });
    const d = await r.json();
    if (d.status === "imported" || d.status === "skipped") {
      btn.className = "btn imported";
      btn.textContent = d.status === "imported" ? `✓ Added to game!${d.tempo ? ` · ${d.tempo} BPM` : ""}` : "✓ Already in game";
      importedNames.add(songName(t));
      if (d.status === "imported") {
        banner(`✓ “${t.title}” added! In Dead as Disco, back out of the song-select screen and re-enter it to see it (or restart the game if it doesn’t show).`);
      }
    } else {
      btn.className = "btn error";
      btn.textContent = "Failed — retry";
      btn.disabled = false;
      btn.onclick = () => doImport(t, btn);
      banner(`Import failed: ${d.message || "unknown error"}`, true);
    }
  } catch (e) {
    btn.className = "btn error";
    btn.textContent = "Failed — retry";
    btn.disabled = false;
    btn.onclick = () => doImport(t, btn);
    banner(`Import failed: ${e}`, true);
  }
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Search (debounced)
let searchTimer = null;
$("#searchInput").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(searchTimer);
  if (!q) return;
  searchTimer = setTimeout(async () => {
    setActive(null);
    titleEl.textContent = `Search: "${q}"`;
    grid.innerHTML = '<div class="empty"><span class="spin"></span> Searching…</div>';
    const d = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
    if (!d.ok) { grid.innerHTML = ""; banner(d.error, true); return; }
    renderTracks(d.tracks);
  }, 350);
});

// Liked Songs button
document.querySelector('.pl[data-kind="liked"]').onclick = (e) =>
  selectSource(e.currentTarget, "Liked Songs", "/api/liked");

async function init() {
  const [authed] = await Promise.all([loadUser(), loadImported()]);
  if (!authed) return; // show Connect button; user authorises, callback returns to '/'
  await loadPlaylists();
  selectSource(document.querySelector('.pl[data-kind="liked"]'), "Liked Songs", "/api/liked");
}
init();
