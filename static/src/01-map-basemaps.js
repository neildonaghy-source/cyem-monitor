  // ---------------------------------------------------------------- map + basemaps
  const map = L.map('map', { zoomControl: false, worldCopyJump: false, minZoom: 2, maxZoom: 13, attributionControl: true, preferCanvas: true, renderer: L.canvas({ padding: 0.3 }) })
    .setView([54.5, -3.0], 6);
  // Default view: Great Britain and Northern Ireland (zoom 6 on a laptop, 5 at phone width or on a short window).
  // A start-up default view (below) replaces it; EMO's auto-fit may move it when a scenario is shown.
  const UK_BOUNDS = L.latLngBounds([49.8, -8.3], [59.0, 1.9]);
  map.setView([54.5, -3.0], Math.max(4, Math.min(innerWidth < 700 ? 5 : 6, map.getBoundsZoom(UK_BOUNDS))), { animate: false });
  // One map pick at a time, with a bar to cancel it (Esc too). Starting a pick cancels the one before, so a single click
  // never sets two positions, and a cancelled pick does not swallow the next ordinary map click.
  let PICK = null;
  function pickOnMap(label, onPick, onCancel) {
    if (PICK) PICK.cancel(false);
    const el = map.getContainer(); el.style.cursor = 'crosshair';
    const bar = document.createElement('div'); bar.className = 'emo-trackbar';
    bar.innerHTML = `<span>Click the map: ${label}</span> <button>Cancel</button>`;
    document.body.appendChild(bar);
    const end = () => { map.off('click', hit); document.removeEventListener('keydown', key); el.style.cursor = ''; bar.remove(); PICK = null; };
    const hit = (ev) => { end(); onPick(ev); };
    const key = (ev) => { if (ev.key === 'Escape') PICK?.cancel(true); };
    PICK = { cancel: (reopen) => { end(); if (reopen && onCancel) onCancel(); } };
    bar.querySelector('button').addEventListener('click', () => PICK?.cancel(true));
    document.addEventListener('keydown', key);
    map.on('click', hit);                                  // the button that starts a pick is outside the map
  }
  map.setMaxBounds([[-85, -200], [85, 200]]);
  window.__cyemMap = map; // test hook for tests/ui/layer_click.py
  if (START?.view) map.setView([START.view.lat, START.view.lon], Math.max(2, START.view.z - (innerWidth < 700 ? 1 : 0)), { animate: false });
  L.control.zoom({ position: 'topright' }).addTo(map);
  const BASEMAPS = {
    esri_dark: { label: 'Esri dark grey', make: () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { attribution: 'Tiles &copy; Esri, HERE, Garmin, OSM contributors', maxNativeZoom: 16, noWrap: true }) },
    esri_imagery: { label: 'Esri imagery', make: () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics', maxNativeZoom: 17, noWrap: true }) },
    osm: { label: 'OpenStreetMap', make: () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxNativeZoom: 19, noWrap: true }) },
    carto_dark: { label: 'CARTO dark (may need key)', make: () => L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { attribution: '&copy; OpenStreetMap &copy; CARTO', subdomains: 'abcd', maxNativeZoom: 19, noWrap: true }) },
  };
  let baseLayer = null;
  function setBasemap(key) {
    if (!BASEMAPS[key]) key = 'esri_dark';
    if (baseLayer) map.removeLayer(baseLayer);
    baseLayer = BASEMAPS[key].make().addTo(map);
    baseLayer.bringToBack();
    try { localStorage.setItem('cyem.basemap', key); } catch {}
    $$('#layers input[name=basemap]').forEach((r) => { r.checked = r.value === key; });
  }

