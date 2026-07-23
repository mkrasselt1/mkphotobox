"""Shared standalone photo-gallery viewer (offline + live).

One small, dependency-free HTML/CSS/JS gallery used in two ways:

* **Offline** (USB export): ``VIEWER_HTML`` loads ``photos.js`` (which sets
  ``window.PHOTOS``) from the same folder. Works by double-clicking index.html
  under ``file://`` — fetch() is blocked there, hence a JS file not JSON.
* **Live** (web): ``live_viewer_html(feed_url)`` injects ``window.PHOTO_FEED``;
  the page polls that JSON endpoint and lazy-appends new photos as they arrive.
"""

from __future__ import annotations

import json

# ── <head> (shared) ──────────────────────────────────────────────────────────
_HEAD = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Fotos</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         background:#0e1117; color:#e8eaf0; }
  header { position:sticky; top:0; z-index:5; display:flex; align-items:center;
           gap:.75rem; padding:.85rem 1.1rem; background:rgba(14,17,23,.92);
           backdrop-filter:blur(8px); border-bottom:1px solid #232a3a; }
  header h1 { font-size:1.1rem; margin:0; font-weight:700; letter-spacing:.2px; }
  header #count { color:#8a93a6; font-size:.85rem; }
  header .live { margin-left:auto; display:none; align-items:center; gap:.4rem;
                 font-size:.8rem; color:#46d39a; }
  header .live.on { display:flex; }
  .dot { width:9px; height:9px; border-radius:50%; background:#46d39a;
         box-shadow:0 0 0 0 rgba(70,211,154,.6); animation:pulse 1.6s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(70,211,154,.5);} 70%{box-shadow:0 0 0 8px rgba(70,211,154,0);} 100%{box-shadow:0 0 0 0 rgba(70,211,154,0);} }
  #grid { display:grid; gap:6px; padding:6px;
          grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); }
  .tile { position:relative; aspect-ratio:1/1; overflow:hidden; border-radius:10px;
          background:#1a2030; cursor:pointer; }
  .tile img { width:100%; height:100%; object-fit:cover; display:block;
              transition:transform .25s; }
  .tile:hover img { transform:scale(1.05); }
  .tile.new::after { content:"neu"; position:absolute; top:6px; left:6px;
          background:#46d39a; color:#06281b; font-size:.65rem; font-weight:700;
          padding:1px 7px; border-radius:7px; }
  .tile .gif-badge { position:absolute; top:6px; right:6px; z-index:2;
          background:rgba(43,108,255,.92); color:#fff; font-size:.7rem; font-weight:700;
          padding:3px 8px; border-radius:7px; border:none; cursor:pointer;
          letter-spacing:.4px; box-shadow:0 2px 8px rgba(0,0,0,.35); }
  .tile .gif-badge.playing { background:rgba(231,76,60,.95); }
  #empty { padding:3rem 1rem; text-align:center; color:#8a93a6; }
  /* Lightbox */
  #lb { position:fixed; inset:0; z-index:50; display:none; background:rgba(0,0,0,.93);
        align-items:center; justify-content:center; }
  #lb.on { display:flex; }
  /* Fixed box + object-fit:contain upscales small images (e.g. GIFs) so they
     fill the viewport just like full-res photos, keeping aspect ratio. */
  #lb img { width:96vw; height:88vh; object-fit:contain; border-radius:6px; }
  #lb .bar { position:absolute; top:0; left:0; right:0; display:flex; align-items:center;
             gap:1rem; padding:.8rem 1rem; }
  #lb .bar .name { font-size:.9rem; color:#cfd6e6; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #lb a.dl { margin-left:auto; color:#fff; text-decoration:none; background:#2b6cff;
             padding:.5rem 1rem; border-radius:10px; font-size:.9rem; font-weight:600; }
  #lb button { background:rgba(255,255,255,.12); color:#fff; border:none; cursor:pointer;
               width:54px; height:54px; border-radius:50%; font-size:1.6rem; }
  #lb .nav { position:absolute; top:50%; transform:translateY(-50%); }
  #lb .prev { left:14px; } #lb .next { right:14px; }
  #lb .close { position:absolute; top:.7rem; right:1rem; width:44px; height:44px; font-size:1.3rem; }
  @media (max-width:600px){ #grid{grid-template-columns:repeat(auto-fill,minmax(108px,1fr));} #lb .nav{width:44px;height:44px;} }
</style>
</head>"""

# ── <body> + gallery logic (shared) ─────────────────────────────────────────
_INNER = """
<header>
  <h1 id="title">Fotos</h1>
  <span id="count"></span>
  <span class="live" id="liveBadge"><span class="dot"></span> Live</span>
</header>
<div id="empty">Noch keine Fotos.</div>
<div id="grid"></div>
<div id="lb">
  <div class="bar"><span class="name" id="lbName"></span>
    <button class="dl" id="lbGif" style="display:none;border:none;cursor:pointer;background:#16a085;">GIF ▶</button>
    <a class="dl" id="lbDl" download>Herunterladen</a></div>
  <button class="close" id="lbClose">&times;</button>
  <button class="nav prev" id="lbPrev">&#8249;</button>
  <img id="lbImg" alt="">
  <button class="nav next" id="lbNext">&#8250;</button>
</div>
<script>
(function(){
  var title = window.VIEWER_TITLE || 'Fotos';
  document.getElementById('title').textContent = title;
  document.title = title;
  var feed = window.PHOTO_FEED || null;
  var seen = {}, items = [];
  var grid = document.getElementById('grid');
  var emptyEl = document.getElementById('empty');
  var countEl = document.getElementById('count');
  var lb = document.getElementById('lb'), lbImg = document.getElementById('lbImg');
  var lbName = document.getElementById('lbName'), lbDl = document.getElementById('lbDl');
  var lbGif = document.getElementById('lbGif');
  var cur = 0, gifOn = false;

  function norm(p){
    if (typeof p === 'string') return { src:p, full:p, name:p, gif:null };
    var full = p.url || p.src || p.thumb;
    return { src:(p.thumb || full), full:full, name:(p.name || full), gif:(p.gif || null) };
  }
  function add(list, prepend){
    var added = 0;
    (list||[]).forEach(function(raw){
      var it = norm(raw);
      if (!it.src || seen[it.src]) return;
      seen[it.src] = 1;
      prepend ? items.unshift(it) : items.push(it);
      added++;
    });
    return added;
  }
  function tileEl(it, isNew){
    var d = document.createElement('div');
    d.className = 'tile' + (isNew ? ' new' : '');
    var img = document.createElement('img');
    img.loading = 'lazy'; img.src = it.src; img.alt = it.name;
    d.appendChild(img);
    d.addEventListener('click', function(){ open(items.indexOf(it)); });
    if (it.gif) {
      var b = document.createElement('button');
      b.className = 'gif-badge'; b.type = 'button'; b.textContent = 'GIF ▶';
      b.addEventListener('click', function(e){
        e.stopPropagation();            // don't open the lightbox
        var playing = b.classList.toggle('playing');
        b.textContent = playing ? 'Foto' : 'GIF ▶';
        img.src = playing ? it.gif : it.src;
      });
      d.appendChild(b);
    }
    if (isNew) setTimeout(function(){ d.classList.remove('new'); }, 8000);
    return d;
  }
  function renderAll(){
    grid.innerHTML = '';
    items.forEach(function(it){ grid.appendChild(tileEl(it, false)); });
    refresh();
  }
  function prependNew(n){
    for (var i = n - 1; i >= 0; i--) grid.insertBefore(tileEl(items[i], true), grid.firstChild);
    refresh();
  }
  function refresh(){
    countEl.textContent = items.length + (items.length === 1 ? ' Foto' : ' Fotos');
    emptyEl.style.display = items.length ? 'none' : '';
  }
  // Lightbox
  function open(i){ cur = i; gifOn = false; show(); lb.classList.add('on'); }
  function show(){
    var it = items[cur]; if (!it) return;
    var showGif = gifOn && it.gif;
    lbImg.src = showGif ? it.gif : (it.full || it.src);
    lbName.textContent = it.name;
    lbDl.href = (showGif ? it.gif : (it.full || it.src)); lbDl.setAttribute('download', it.name);
    lbGif.style.display = it.gif ? '' : 'none';
    lbGif.textContent = showGif ? 'Foto' : 'GIF ▶';
  }
  function close(){ lb.classList.remove('on'); }
  function step(d){ if(!items.length) return; cur = (cur + d + items.length) % items.length; gifOn = false; show(); }
  lbGif.onclick = function(){ gifOn = !gifOn; show(); };
  document.getElementById('lbClose').onclick = close;
  document.getElementById('lbPrev').onclick = function(){ step(-1); };
  document.getElementById('lbNext').onclick = function(){ step(1); };
  lb.addEventListener('click', function(e){ if (e.target === lb) close(); });
  document.addEventListener('keydown', function(e){
    if (!lb.classList.contains('on')) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'ArrowRight') step(1);
  });

  // Initial (offline: window.PHOTOS)
  if (window.PHOTOS) add(window.PHOTOS, false);
  renderAll();

  // Live polling
  if (feed) {
    document.getElementById('liveBadge').classList.add('on');
    var poll = function(){
      fetch(feed, { cache:'no-store' })
        .then(function(r){ return r.json(); })
        .then(function(d){
          var n = add(d.photos || d || [], true);
          if (n) prependNew(n);
        })
        .catch(function(){});
    };
    poll();
    setInterval(poll, 4000);
  }
})();
</script>
</body>
</html>"""

VIEWER_HTML = _HEAD + '\n<body>\n<script src="photos.js"></script>' + _INNER


def viewer_photos_js(image_names: list[str]) -> str:
    """Return the ``photos.js`` content that the offline viewer loads."""
    return "window.PHOTOS = " + json.dumps(list(image_names), ensure_ascii=False) + ";\n"


def live_viewer_html(feed_url: str, title: str = "Fotos") -> str:
    """Full HTML for a live gallery that polls *feed_url* for new photos."""
    cfg = (
        "<script>window.PHOTO_FEED=" + json.dumps(feed_url)
        + ";window.VIEWER_TITLE=" + json.dumps(title) + ";</script>"
    )
    return _HEAD + "\n<body>\n" + cfg + _INNER
