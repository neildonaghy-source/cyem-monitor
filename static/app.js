/* CyEM Monitor UI — vanilla JS, Leaflet, marked. No build step. */
(() => {
  'use strict';
  const BUILD = '2026-09-25y';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const flag = (iso2) => (iso2 && /^[A-Za-z]{2}$/.test(iso2)) ? String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65)) : '';
  const ago = (iso) => {
    if (!iso) return '';
    const d = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(d)) return '';
    if (d < 0) return 'now';
    if (d < 60) return `${Math.floor(d)}s`;
    if (d < 3600) return `${Math.floor(d / 60)}m`;
    if (d < 86400) return `${Math.floor(d / 3600)}h`;
    return `${Math.floor(d / 86400)}d`;
  };
  const fmtZ = (iso) => iso ? iso.replace('T', ' ').replace(/:\d\dZ$/, 'Z') : '';
  // EMO scenario space: 'default' is shared across devices; 'device' keeps a private space on this device
  function wsId() {
    if (localStorage.getItem('cyem-ws-mode') !== 'device') return 'default';
    let v = localStorage.getItem('cyem-ws'); if (!v) { v = 'd' + Math.random().toString(36).slice(2, 9); localStorage.setItem('cyem-ws', v); }
    return v;
  }
  const _fetch = window.fetch.bind(window);
  window.fetch = (u, o = {}) => { if (typeof u === 'string' && u.startsWith('/api/')) o = { ...o, headers: { ...(o.headers || {}), 'X-CyEM-WS': wsId() } }; return _fetch(u, o); };
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  const COLOURS = { cyber: '#3cc7ff', em: '#f3b23e', infra: '#2bb9a8', osint: '#b48cff' };
  const state = { dom: 'all', q: '', hiOnly: false, hours: 48, country: null, status: null, briefId: null, layerCounts: {} };

  // ---------------------------------------------------------------- map + basemaps
  const map = L.map('map', { zoomControl: false, worldCopyJump: false, minZoom: 2, maxZoom: 13, attributionControl: true, preferCanvas: true })
    .setView([38, 18], 3);
  map.setMaxBounds([[-85, -200], [85, 200]]);
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

  // ---------------------------------------------------------------- overlay layers (grouped)
  const layerCtl = $('#layers');
  const GROUPS = [
    { id: 'basemap', label: 'Basemap' },
    { id: 'iono', label: 'HF / ionosphere' },
    { id: 'em', label: 'EM / spectrum' },
    { id: 'cyber', label: 'Cyber' },
    { id: 'infra', label: 'Infrastructure' },
    { id: 'osint', label: 'OSINT / reference' },
  ];
  const G = (glyph, col, size = 13) => `<span class="lg" style="color:${col};font-size:${size}px">${glyph}</span>`;
  const DOT = (col, r = 8, extra = '') => `<span class="lgdot" style="background:${col};width:${r}px;height:${r}px;${extra}"></span>`;
  const LAYERS = [
    { id: 'terminator', group: 'iono', label: 'Day / night + grey line', colour: '#f3b23e', on: true, load: loadTerminator, every: 1,
      legend: `${DOT('rgba(0,0,0,.6)', 10, 'border:1px solid #445')} night ${DOT('#f3b23e', 10, 'opacity:.35')} grey line` },
    { id: 'hfmap', group: 'iono', label: 'MUF contours + ionosondes', colour: '#9ad7ff', on: true, load: loadHfmap, every: 15,
      legend: `<span class="lgline" style="background:#e04040"></span>7 <span class="lgline" style="background:#f0c030"></span>14 <span class="lgline" style="background:#40c060"></span>21 <span class="lgline" style="background:#3c8cff"></span>28 MHz · ${DOT('#9ad7ff', 7)} ionosonde` },
    { id: 'drap', group: 'iono', label: 'HF absorption (D-RAP)', colour: '#ff8c42', on: true, load: loadDrap, every: 15,
      legend: `${DOT('rgba(255,220,60,.6)', 9)} &lt;5 ${DOT('rgba(255,140,66,.7)', 9)} 5–15 ${DOT('rgba(255,60,60,.8)', 9)} 15–25 ${DOT('rgba(255,80,220,.85)', 9)} &gt;25 MHz` },
    { id: 'aurora', group: 'iono', label: 'Aurora oval (OVATION)', colour: '#45d38a', on: true, load: loadAurora, every: 15,
      legend: `${DOT('rgba(69,211,138,.5)', 9)} 10% ${DOT('rgba(240,200,60,.7)', 9)} 40% ${DOT('rgba(255,70,70,.85)', 9)} 70%+` },
    { id: 'gpsjam', group: 'em', label: 'GNSS interference', colour: '#ff5c5c', on: true, load: loadGpsjam, every: 10,
      legend: `${G('⬢', '#ff5c5c')} high (&gt;10% aircraft) ${G('⬢', '#f3b23e')} medium (2–10%)` },
    { id: 'milair', group: 'em', label: 'Military aircraft (live)', colour: '#f3b23e', on: true, load: loadMilair, every: 2,
      legend: `${G('➤', '#f3b23e', 15)} ISR ${G('➤', '#ff5c5c', 15)} EW ${G('➤', '#ffd166', 15)} AEW ${G('➤', '#ff8c42', 15)} C2 ${G('➤', '#2bb9a8', 15)} MPA ${G('➤', '#3cc7ff', 11)} tanker ${G('➤', '#8593a6', 11)} other`,
      opts: [{ id: 'milair_isr', label: 'ISR / EW / AEW / MPA only', on: true }] },
    { id: 'sats', group: 'em', label: 'Satellites (live)', colour: '#9ad7ff', on: false, load: loadSats, every: 2,
      legend: `${DOT('#9ad7ff', 7, 'border-radius:0')} GNSS ${DOT('#ff6fb1', 7, 'border-radius:0')} military ${DOT('#2bb9a8', 7, 'border-radius:0')} SBAS · click one for its ground track`,
      opts: [{ id: 'sats_gnss', label: 'GNSS', on: true }, { id: 'sats_military', label: 'military', on: true }, { id: 'sats_sbas', label: 'SBAS', on: false }] },
    { id: 'emitters', group: 'em', label: 'Strategic emitters (ref)', colour: '#ff6fb1', on: true, load: loadEmitters, every: 0,
      legend: `${G('▲', '#ff5c5c')} EW radar ${G('▲', '#ff8c42')} ABM ${G('△', '#ffd166')} OTH ${G('◬', '#c8d3e0')} space surv ${G('▴', '#f3b23e')} air def ${G('◆', '#ff6fb1')} SIGINT ${G('●', '#3cc7ff')} SATCOM ${G('▼', '#b48cff')} VLF ${G('▽', '#b48cff')} HF ${G('✦', '#9ad7ff')} GNSS gnd ${G('✧', '#45d38a')} ionosph ${G('◉', '#2bb9a8')} deep space ${G('✕', '#ff5c5c')} EW range ${G('○', '#5d6b7d')} historic` },
    { id: 'radars', group: 'em', label: 'Radar sites (OSM)', colour: '#c8d3e0', on: false, load: loadRadars, every: 0,
      legend: `${DOT('#e0e6ee', 7)} military ${DOT('#3cc7ff', 7)} space ${DOT('#f3b23e', 6)} aviation ${DOT('#45d38a', 6)} weather ${DOT('#2bb9a8', 6)} maritime ${DOT('#6f7f93', 6)} other`,
      opts: [{ id: 'radars_mil', label: 'military / space only', on: true }] },
    { id: 'air', group: 'em', label: 'All aircraft (ADS-B, UK)', colour: '#8fb3d9', on: false, load: loadAir, every: 2,
      legend: `${DOT('#8fb3d9', 7)} normal ${DOT('#ff6fb1', 7)} military ${DOT('#f3b23e', 8)} degraded GNSS (NIC 1–6) ${DOT('#ff5c5c', 8)} emergency squawk`,
      opts: [{ id: 'air_flags', label: 'Degraded GNSS / emergency only', on: false }] },
    { id: 'ais', group: 'em', label: 'Ships (AIS, UK waters)', colour: '#3cc7ff', on: false, load: loadAis, every: 5,
      legend: `${DOT('#ff5c5c', 7)} military ${DOT('#ff6fb1', 7)} law enf. ${DOT('#f3b23e', 7)} SAR ${DOT('#3cc7ff', 7)} cargo ${DOT('#c07b3a', 7)} tanker ${DOT('#45d38a', 7)} passenger ${DOT('#2bb9a8', 7)} fishing ${DOT('#8593a6', 7)} other`,
      opts: [{ id: 'ais_gov', label: 'Military / law enforcement / SAR only', on: false }] },
    { id: 'cells', group: 'em', label: 'Mobile cells (OpenCelliD, zoom 11+)', colour: '#45d38a', on: false, load: loadCells, every: 0,
      legend: `${DOT('#8593a6', 7)} 2G ${DOT('#3cc7ff', 7)} 3G ${DOT('#45d38a', 7)} 4G ${DOT('#ff6fb1', 7)} 5G · estimated positions` },
    { id: 'coverage', group: 'em', label: 'Coverage sites', colour: '#2bb9a8', on: true, load: loadCoverage, every: 0,
      legend: `${DOT('rgba(43,185,168,.7)', 9)} strong ${DOT('rgba(69,211,138,.6)', 9)} adequate ${DOT('rgba(243,178,62,.6)', 9)} marginal · open Coverage to plan` },
    { id: 'links', group: 'em', label: 'Planned links (P2P)', colour: '#45d38a', on: true, load: loadLinks, every: 0,
      legend: `<span class="lgline" style="background:#45d38a"></span>go <span class="lgline" style="background:#f3b23e"></span>marginal <span class="lgline" style="background:#ff5c5c"></span>no-go · open Links to plan` },
    { id: 'planned', group: 'em', label: 'Planned emitters + conflicts', colour: '#ff5c5c', on: true, load: loadPlanned, every: 0,
      legend: `${G('◉', '#45d38a')} clear ${G('◉', '#f3b23e')} medium/low ${G('◉', '#ff5c5c')} high · dashed ring = check radius · open Spectrum to plan` },
    { id: 'wtr', group: 'em', label: 'Ofcom licences (zoom 8+)', colour: '#8fb3d9', on: false, load: loadWtr, every: 0,
      legend: `${DOT('#3cc7ff', 7)} business radio ${DOT('#8593a6', 7)} fixed links ${DOT('#2bb9a8', 7)} maritime/AIS ${DOT('#ff6fb1', 7)} satellite ${DOT('#f3b23e', 7)} GNSS repeater ${DOT('#c8d3e0', 7)} other · one dot per site` },
    { id: 'launches', group: 'em', label: 'Upcoming launches', colour: '#ffffff', on: false, load: loadLaunches, every: 60, legend: `${G('▲', '#fff')} launch pad` },
    { id: 'ransomware', group: 'cyber', label: 'Ransomware victims 30d', colour: '#b48cff', on: true, load: loadRansomware, every: 10, legend: `${DOT('rgba(180,140,255,.35)', 12, 'border:1px solid #b48cff')} victims per country (size = count)` },
    { id: 'c2', group: 'cyber', label: 'Botnet C2 (country)', colour: '#3cc7ff', on: true, load: loadC2, every: 10, legend: `${DOT('rgba(60,199,255,.2)', 12, 'border:1px dashed #3cc7ff')} C2 servers per country` },
    { id: 'apt', group: 'cyber', label: 'APT groups (ref)', colour: '#ff8c42', on: false, load: loadApt, every: 0, legend: `${G('◆', '#ff8c42')} state ${G('◆', '#ffd166')} criminal` },
    { id: 'ioda', group: 'infra', label: 'Internet outages', colour: '#ff8c42', on: true, load: loadIoda, every: 10, legend: `${DOT('rgba(255,140,66,.4)', 12, 'border:1.5px solid #ff8c42')} critical alerts ${DOT('rgba(138,90,43,.2)', 10, 'border:1px solid #8a5a2b')} warnings` },
    { id: 'cloudflare', group: 'infra', label: 'Cloudflare outages 7d', colour: '#ffd166', on: true, load: loadCloudflare, every: 10, legend: `${DOT('rgba(255,209,102,.3)', 11, 'border:1.5px solid #ffd166')} outage annotation (needs token)` },
    { id: 'cables', group: 'infra', label: 'Submarine cables', colour: '#2bb9a8', on: false, load: loadCables, every: 0, legend: `<span class="lgline" style="background:#2bb9a8"></span> cable system` },
    { id: 'gdelt', group: 'osint', label: 'GDELT news 24h', colour: '#45d38a', on: true, load: loadGdelt, every: 10, legend: `${DOT('#3cc7ff', 8)} cyber ${DOT('#f3b23e', 8)} GNSS/EW ${DOT('#2bb9a8', 8)} connectivity ${DOT('#ff6fb1', 8)} satellite` },
    { id: 'items', group: 'osint', label: 'Located news 7d', colour: '#8593a6', on: false, load: loadItemsLayer, every: 10, legend: `${DOT('#3cc7ff', 6)} cyber ${DOT('#f3b23e', 6)} EM ${DOT('#2bb9a8', 6)} infra ${DOT('#b48cff', 6)} OSINT` },
  ];  const groups = {};
  const saved = (() => { try { return JSON.parse(localStorage.getItem('cyem.layers') || '{}'); } catch { return {}; } })();
  const optState = (() => { try { return JSON.parse(localStorage.getItem('cyem.layeropts') || '{}'); } catch { return {}; } })();
  const collapsed = (() => { try { return JSON.parse(localStorage.getItem('cyem.groups') || '{}'); } catch { return {}; } })();
  function saveLs(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
  function optOn(id) { const o = LAYERS.flatMap((l) => l.opts || []).find((x) => x.id === id); return optState[id] ?? (o ? o.on : false); }
  function isOn(L_) { return saved[L_.id] ?? L_.on; }

  function setLayerOn(L_, on) {
    if (!L_) return;
    if (on) { groups[L_.id].addTo(map); if (!L_.loaded || L_.id === 'wtr') L_.load().catch(console.warn); }
    else map.removeLayer(groups[L_.id]);
    saved[L_.id] = on; saveLs('cyem.layers', saved);
  }
  function buildLayerPanel() {
    layerCtl.innerHTML = `<h3><span>Layers <span class="dim" style="letter-spacing:0;text-transform:none">build ${BUILD}</span></span><a href="#" id="layers-toggle">hide</a></h3>`;
    for (const g of GROUPS) {
      const sec = document.createElement('div');
      sec.className = 'lgroup' + (collapsed[g.id] ? ' collapsed' : '');
      sec.dataset.group = g.id;
      let body = '';
      if (g.id === 'basemap') {
        const cur = (() => { try { return localStorage.getItem('cyem.basemap') || 'esri_dark'; } catch { return 'esri_dark'; } })();
        body = Object.entries(BASEMAPS).map(([k, b]) => `<label><input type="radio" name="basemap" value="${k}" ${k === cur ? 'checked' : ''}> ${esc(b.label)}</label>`).join('');
      } else {
        body = LAYERS.filter((l) => l.group === g.id).map((L_) => `
          <label data-layer="${L_.id}"><input type="checkbox" ${isOn(L_) ? 'checked' : ''}> <span class="sw" style="background:${L_.colour}"></span> ${esc(L_.label)} <span class="n" id="n-${L_.id}"></span></label>
          ${L_.legend ? `<div class="lgkey">${L_.legend}</div>` : ''}
          ${(L_.opts || []).map((o) => `<label class="sub" data-opt="${o.id}"><input type="checkbox" ${optOn(o.id) ? 'checked' : ''}> ${esc(o.label)}</label>`).join('')}`).join('');
      }
      sec.innerHTML = `<div class="ghead"><span class="gname">${esc(g.label)}</span>${g.id !== 'basemap' ? '<a href="#" data-all="on">all</a><a href="#" data-all="off">none</a>' : ''}<a href="#" class="gtoggle">${collapsed[g.id] ? '+' : '−'}</a></div><div class="gbody">${body}</div>`;
      layerCtl.appendChild(sec);
    }
    $('#layers-toggle').addEventListener('click', (e) => { e.preventDefault(); layerCtl.classList.toggle('collapsed'); e.target.textContent = layerCtl.classList.contains('collapsed') ? 'show' : 'hide'; });
    $$('#layers input[name=basemap]').forEach((r) => r.addEventListener('change', () => setBasemap(r.value)));
    $$('#layers .lgroup').forEach((sec) => {
      const gid = sec.dataset.group;
      sec.querySelector('.gtoggle').addEventListener('click', (e) => { e.preventDefault(); sec.classList.toggle('collapsed'); collapsed[gid] = sec.classList.contains('collapsed'); e.target.textContent = collapsed[gid] ? '+' : '−'; saveLs('cyem.groups', collapsed); });
      sec.querySelectorAll('a[data-all]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        const on = a.dataset.all === 'on';
        sec.querySelectorAll('label[data-layer]').forEach((lab) => {
          const cb = lab.querySelector('input');
          if (cb.checked === on) return;
          cb.checked = on;
          setLayerOn(LAYERS.find((l) => l.id === lab.dataset.layer), on);
        });
        const touched = new Set();
        sec.querySelectorAll('label[data-opt]').forEach((lab) => {
          const cb = lab.querySelector('input');
          if (cb.checked === on) return;
          cb.checked = on; optState[lab.dataset.opt] = on;
          const L_ = LAYERS.find((l) => (l.opts || []).some((o) => o.id === lab.dataset.opt));
          if (L_) touched.add(L_);
        });
        saveLs('cyem.layeropts', optState);
        touched.forEach((L_) => { if (map.hasLayer(groups[L_.id])) L_.load().catch(console.warn); });
      }));
      sec.querySelectorAll('label[data-layer]').forEach((lab) => {
        const L_ = LAYERS.find((l) => l.id === lab.dataset.layer);
        lab.querySelector('input').addEventListener('change', (e) => setLayerOn(L_, e.target.checked));
      });
      sec.querySelectorAll('label[data-opt]').forEach((lab) => {
        lab.querySelector('input').addEventListener('change', (e) => {
          optState[lab.dataset.opt] = e.target.checked; saveLs('cyem.layeropts', optState);
          const L_ = LAYERS.find((l) => (l.opts || []).some((o) => o.id === lab.dataset.opt));
          if (L_ && map.hasLayer(groups[L_.id])) L_.load().catch(console.warn);
        });
      });
    });
  }
  for (const L_ of LAYERS) { groups[L_.id] = L.layerGroup(); if (isOn(L_)) groups[L_.id].addTo(map); }
  buildLayerPanel();
  L.DomEvent.disableScrollPropagation(layerCtl);
  layerCtl.addEventListener('wheel', (e) => {
    if (layerCtl.scrollHeight <= layerCtl.clientHeight) return;
    layerCtl.scrollTop += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    e.preventDefault(); e.stopPropagation();
  }, { passive: false });
  L.DomEvent.disableClickPropagation(layerCtl);
  setBasemap((() => { try { return localStorage.getItem('cyem.basemap') || 'esri_dark'; } catch { return 'esri_dark'; } })());
  $('#legend').innerHTML = `<span><i style="background:#ff5c5c"></i>GNSS high</span><span><i style="background:#f3b23e"></i>GNSS medium / ISR aircraft</span><span><i style="background:#ff6fb1"></i>emitter</span><span><i style="background:#ff8c42"></i>outage</span><span><i style="background:#b48cff"></i>ransomware</span><span><i style="background:#3cc7ff"></i>C2</span><span><i style="background:#45d38a"></i>GDELT</span>`;

  function setCount(id, n) { const el = $(`#n-${id}`); if (el) el.textContent = n == null ? '' : n; }
  function done(id) { const L_ = LAYERS.find((l) => l.id === id); if (L_) L_.loaded = true; }
  const kv = (pairs) => `<div class="kv">${pairs.filter((p) => p[1] !== undefined && p[1] !== null && p[1] !== '').map(([k, v]) => `<span class="k">${esc(k)}</span><span>${v}</span>`).join('')}</div>`;

  // ---- ionosphere / spectrum overlays --------------------------------------------
  const RAD = Math.PI / 180;
  function sunPosition(date) {
    const jd = date.getTime() / 86400000 + 2440587.5, n = jd - 2451545.0;
    const L = (280.460 + 0.9856474 * n) % 360, g = ((357.528 + 0.9856003 * n) % 360) * RAD;
    const lambda = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * RAD, eps = (23.439 - 0.0000004 * n) * RAD;
    const dec = Math.asin(Math.sin(eps) * Math.sin(lambda));
    const ra = Math.atan2(Math.cos(eps) * Math.sin(lambda), Math.cos(lambda));
    const gmst = ((18.697374558 + 24.06570982441908 * n) % 24 + 24) % 24;
    let lon = ra / RAD - gmst * 15; lon = ((lon + 540) % 360) - 180;
    return { dec, lon };
  }
  async function loadTerminator() {
    const g = groups.terminator; g.clearLayers();
    const { dec, lon: sunLon } = sunPosition(new Date());
    const line = [];
    for (let lon = -180; lon <= 180; lon += 1) {
      const H = (lon - sunLon) * RAD;
      const lat = Math.atan(-Math.cos(H) / Math.tan(dec)) / RAD;
      line.push([lat, lon]);
    }
    const pole = dec > 0 ? -90 : 90;
    const night = line.concat([[pole, 180], [pole, -180]]);
    L.polygon(night, { stroke: false, fillColor: '#000', fillOpacity: 0.32, interactive: false }).addTo(g);
    L.polyline(line, { color: '#f3b23e', weight: 14, opacity: 0.14, interactive: false }).addTo(g);
    L.polyline(line, { color: '#f3b23e', weight: 1, opacity: 0.6, interactive: false }).addTo(g);
    L.circleMarker([dec / RAD, sunLon], { radius: 5, color: '#ffd166', fillColor: '#ffd166', fillOpacity: 0.9, weight: 1 })
      .bindTooltip('sub-solar point', { direction: 'top' }).addTo(g);
    setCount('terminator', ''); done('terminator');
  }
  const MERC_LAT = 85;
  function mercY(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * RAD / 2)); }
  function rasterOverlay(sample, opts) {
    // sample(lat, lon) -> [r,g,b,a] or null; draws a Web-Mercator-correct raster between ±85°.
    const W = 720, H = 400;
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const ctx = c.getContext('2d'); const img = ctx.createImageData(W, H); const d = img.data;
    const y0 = mercY(MERC_LAT), y1 = mercY(-MERC_LAT);
    for (let py = 0; py < H; py++) {
      const my = y0 + (y1 - y0) * (py + 0.5) / H;
      const lat = (2 * Math.atan(Math.exp(my)) - Math.PI / 2) / RAD;
      for (let px = 0; px < W; px++) {
        const lon = -180 + 360 * (px + 0.5) / W;
        const v = sample(lat, lon);
        if (!v) continue;
        const i = (py * W + px) * 4; d[i] = v[0]; d[i + 1] = v[1]; d[i + 2] = v[2]; d[i + 3] = v[3];
      }
    }
    ctx.putImageData(img, 0, 0);
    return L.imageOverlay(c.toDataURL('image/png'), [[-MERC_LAT, -180], [MERC_LAT, 180]], Object.assign({ opacity: 1, interactive: false }, opts || {}));
  }
  async function loadDrap() {
    const g = groups.drap; g.clearLayers();
    const { data } = await api('/api/layers/drap');
    if (!data) { setCount('drap', '–'); return; }
    const lats = data.lats, lons = data.lons, grid = data.grid;
    const dlat = lats.length > 1 ? Math.abs(lats[1] - lats[0]) : 2, dlon = lons.length > 1 ? Math.abs(lons[1] - lons[0]) : 4;
    const sample = (lat, lon) => {
      const yi = Math.round((lat - lats[0]) / dlat), xi = Math.round((lon - lons[0]) / dlon);
      if (yi < 0 || yi >= lats.length || xi < 0 || xi >= lons.length) return null;
      const v = grid[yi][xi];
      if (!v || v < 1) return null;  // D-RAP carries a ~0.1 MHz daylight baseline; only show real absorption
      if (v < 5) return [255, 220, 60, 90 + v * 20];
      if (v < 15) return [255, 140, 66, 150];
      if (v < 25) return [255, 60, 60, 180];
      return [255, 80, 220, 200];
    };
    rasterOverlay(sample).bindTooltip('D-RAP HF absorption').addTo(g);
    setCount('drap', data.max_mhz > 0 ? `${data.max_mhz} MHz` : 'clear'); done('drap');
  }
  async function loadAurora() {
    const g = groups.aurora; g.clearLayers();
    const { data } = await api('/api/layers/aurora');
    if (!data) { setCount('aurora', '–'); return; }
    const step = data.step || 2, grid = data.grid;
    const sample = (lat, lon) => {
      const yi = Math.round((lat + 90) / step), xi = Math.round((((lon + 360) % 360)) / step) % grid[0].length;
      if (yi < 0 || yi >= grid.length) return null;
      const v = grid[yi][xi];
      if (!v || v < 5) return null;
      const a = Math.min(215, 40 + v * 3);
      if (v < 25) return [69, 211, 138, a];
      if (v < 55) return [240, 200, 60, a];
      return [255, 70, 70, a];
    };
    rasterOverlay(sample).addTo(g);
    setCount('aurora', `N${data.max_north}% S${data.max_south}%`); done('aurora');
  }
  function mufColour(m) { return m < 10 ? '#e04040' : m < 16 ? '#f0c030' : m < 22 ? '#40c060' : m < 26 ? '#3cc7ff' : '#3c8cff'; }
  async function loadHfmap() {
    const g = groups.hfmap; g.clearLayers();
    const { data } = await api('/api/layers/hfmap');
    if (!data) { setCount('hfmap', '–'); return; }
    for (const c of data.contours || []) {
      const latlngs = c.coords.map(([x, y]) => [y, x]);
      L.polyline(latlngs, { color: mufColour(c.mhz), weight: 1.2, opacity: 0.8, interactive: true })
        .bindTooltip(`MUF(3000) ${c.mhz} MHz`, { sticky: true }).addTo(g);
    }
    for (const st of data.stations || []) {
      if (!st.fresh) continue;
      const col = st.mufd ? mufColour(st.mufd) : '#9ad7ff';
      L.circleMarker([st.lat, st.lon], { radius: 4, color: '#000', weight: 0.8, fillColor: col, fillOpacity: 0.95 })
        .bindPopup(`<h4>${esc(st.name)} <span class="muted">${esc(st.code)}</span></h4>${kv([['foF2', st.fof2 != null ? `${st.fof2} MHz` : ''], ['MUF(3000)', st.mufd != null ? `${st.mufd} MHz` : ''], ['hmF2', st.hmf2 != null ? `${st.hmf2} km` : ''], ['TEC', st.tec != null ? `${st.tec} TECU` : ''], ['foE', st.foe != null ? `${st.foe} MHz` : ''], ['Sounding', fmtZ(st.time)]])}<p class="dim" style="margin:6px 0 0">GIRO ionosonde via prop.kc2g.com</p>`)
        .addTo(g);
    }
    setCount('hfmap', `${data.fresh_stations} sondes`); done('hfmap');
  }
  const trackGroup = L.layerGroup().addTo(map);
  async function showSatTrack(norad) {
    trackGroup.clearLayers();
    try {
      const t = await api(`/api/sat/${norad}/track?minutes=100`);
      const segs = []; let cur = [];
      for (const [lat, lon] of t.points) { if (cur.length && Math.abs(lon - cur[cur.length - 1][1]) > 180) { segs.push(cur); cur = []; } cur.push([lat, lon]); }
      if (cur.length) segs.push(cur);
      for (const seg of segs) L.polyline(seg, { color: '#9ad7ff', weight: 1.2, opacity: 0.8, dashArray: '4 4', interactive: false }).addTo(trackGroup);
      const p0 = t.points.find((p) => p[2] === 0) || t.points[0];
      L.circleMarker([p0[0], p0[1]], { radius: 3, color: '#fff', weight: 1, fillOpacity: 0 }).addTo(trackGroup);
    } catch (e) { console.warn('track', e); }
  }
  map.on('popupclose', () => trackGroup.clearLayers());

  async function loadGpsjam() {
    const g = groups.gpsjam; g.clearLayers();
    const { data } = await api('/api/layers/gpsjam');
    if (!data || !data.hexes) { setCount('gpsjam', 0); return; }
    for (const h of data.hexes) {
      const hi = h.level === 'high';
      L.polygon(h.boundary, { color: hi ? '#ff5c5c' : '#f3b23e', weight: 0.6, opacity: 0.6, fillOpacity: hi ? 0.45 : 0.25, interactive: true })
        .bindPopup(`<h4>GNSS interference: ${esc(h.level)}</h4>${kv([['Region', esc(h.region)], ['Degraded aircraft', `${h.bad} of ${h.aircraft} (${h.pct}%)`], ['Date', esc(data.date)], ['H3', `<span class="mono">${esc(h.h3)}</span>`]])}<p class="dim" style="margin:6px 0 0">${esc(data.attribution || '')}</p>`)
        .addTo(g);
    }
    setCount('gpsjam', `${data.high}/${data.medium}`); done('gpsjam');
  }
  const ROLE_COL = { isr: '#f3b23e', ew: '#ff5c5c', aew: '#ffd166', c2: '#ff8c42', mpa: '#2bb9a8', tanker: '#3cc7ff', transport: '#8593a6', strike: '#ff6fb1', fighter: '#6f7f93', heli: '#5d6b7d', trainer: '#4d5b6b', other: '#6f7f93' };
  const ROLE_NAME = { isr: 'ISR / SIGINT', ew: 'Electronic warfare', aew: 'AEW&C', c2: 'Airborne C2 / relay', mpa: 'Maritime patrol', tanker: 'Tanker', transport: 'Transport', strike: 'Bomber / strike', fighter: 'Fighter', heli: 'Helicopter', trainer: 'Trainer', other: 'Other military' };
  const HI_ROLES = new Set(['isr', 'ew', 'aew', 'c2', 'mpa']);
  async function loadMilair() {
    const g = groups.milair; g.clearLayers();
    const { data, updated } = await api('/api/layers/milair');
    if (!data) { setCount('milair', '–'); return; }
    const only = optOn('milair_isr');
    let n = 0;
    for (const a of data.aircraft || []) {
      if (only && !HI_ROLES.has(a.role)) continue;
      n++;
      const col = ROLE_COL[a.role] || '#8593a6';
      const hi = HI_ROLES.has(a.role);
      const icon = L.divIcon({ className: '', iconSize: [hi ? 16 : 11, hi ? 16 : 11], html: `<div class="ac ${hi ? 'hi' : ''}" style="color:${col};transform:rotate(${(a.track || 0) - 90}deg)">➤</div>` });
      L.marker([a.lat, a.lon], { icon, zIndexOffset: hi ? 500 : 0 })
        .bindPopup(`<h4>${esc(a.flight || a.reg || a.hex)} <span class="muted">${esc(a.type || '')}</span></h4>${kv([['Role', esc(ROLE_NAME[a.role] || a.role)], ['Aircraft', esc(a.desc || '')], ['Registration', esc(a.reg || '')], ['Altitude', a.alt != null ? `${a.alt.toLocaleString()} ft` : (a.alt_txt || '')], ['Ground speed', a.gs != null ? `${Math.round(a.gs)} kt` : ''], ['Track', a.track != null ? `${Math.round(a.track)}°` : ''], ['Squawk', esc(a.squawk || '')], ['Hex', `<span class="mono">${esc(a.hex)}</span>`]])}<p style="margin:6px 0 0"><a href="https://globe.adsb.fi/?icao=${esc(a.hex)}" target="_blank" rel="noopener">Track on adsb.fi ↗</a></p><p class="dim" style="margin:4px 0 0">${esc(data.source || '')} · ${fmtZ(updated)}</p>`)
        .addTo(g);
    }
    setCount('milair', `${n}/${data.count}`); done('milair');
  }
  const SAT_COL = { gnss: '#9ad7ff', military: '#ff6fb1', sbas: '#2bb9a8' };
  async function loadSats() {
    const g = groups.sats; g.clearLayers();
    const { data, updated } = await api('/api/layers/sats');
    if (!data) { setCount('sats', '–'); return; }
    let n = 0;
    for (const s of data.sats || []) {
      if (!optOn('sats_' + s.group)) continue;
      n++;
      const col = SAT_COL[s.group] || '#fff';
      const icon = L.divIcon({ className: '', iconSize: [7, 7], html: `<div class="sat" style="background:${col}"></div>` });
      L.marker([s.lat, s.lon], { icon }).bindPopup(`<h4>${esc(s.name)}</h4>${kv([['Group', esc(s.group)], ['NORAD', s.norad], ['Altitude', `${s.alt_km.toLocaleString()} km`], ['Period', s.period_min ? `${s.period_min} min` : ''], ['Sub-point', `${s.lat.toFixed(1)}, ${s.lon.toFixed(1)}`]])}<p class="dim" style="margin:4px 0 0">Dashed line = ground track −33 / +66 min · SGP4 from Celestrak TLEs · ${fmtZ(data.computed_at)}</p>`).on('popupopen', () => showSatTrack(s.norad)).addTo(g);
    }
    setCount('sats', n); done('sats');
  }
  const EMIT_COL = { 'ew-radar': '#ff5c5c', 'abm-radar': '#ff8c42', 'oth-radar': '#ffd166', 'space-surveillance': '#c8d3e0', 'air-defence-radar': '#f3b23e', sigint: '#ff6fb1', satcom: '#3cc7ff', vlf: '#b48cff', hf: '#b48cff', 'gnss-ground': '#9ad7ff', ionospheric: '#45d38a', 'deep-space': '#2bb9a8', 'ew-range': '#ff5c5c', historic: '#5d6b7d' };
  const EMIT_GLYPH = { 'ew-radar': '▲', 'abm-radar': '▲', 'oth-radar': '△', 'space-surveillance': '◬', 'air-defence-radar': '▴', sigint: '◆', satcom: '●', vlf: '▼', hf: '▽', 'gnss-ground': '✦', ionospheric: '✧', 'deep-space': '◉', 'ew-range': '✕', historic: '○' };
  async function loadEmitters() {
    const g = groups.emitters; g.clearLayers();
    const { emitters } = await api('/api/layers/emitters');
    for (const e of emitters) {
      const col = EMIT_COL[e.type] || '#ff6fb1';
      const icon = L.divIcon({ className: '', iconSize: [14, 14], html: `<div class="emit" style="color:${col}">${EMIT_GLYPH[e.type] || '◆'}</div>` });
      L.marker([e.lat, e.lon], { icon, title: e.name }).bindPopup(`<h4>${flag(e.country)} ${esc(e.name)}</h4>${kv([['Type', esc(e.type)], ['Operator', esc(e.operator || '')], ['Country', esc(e.country_name || e.country)]])}<p style="margin:6px 0 0">${esc(e.note || '')}</p><p class="dim" style="margin:4px 0 0">Reference layer from public reporting; positions approximate.</p>`).addTo(g);
    }
    setCount('emitters', emitters.length); done('emitters');
  }
  const RADAR_COL = { military: '#e0e6ee', space: '#3cc7ff', aviation: '#f3b23e', weather: '#45d38a', maritime: '#2bb9a8', other: '#6f7f93' };
  async function loadRadars() {
    const g = groups.radars; g.clearLayers();
    const { data } = await api('/api/layers/radars');
    if (!data) { setCount('radars', '–'); return; }
    const milOnly = optOn('radars_mil');
    let n = 0;
    for (const s of data.sites || []) {
      if (milOnly && s.cls !== 'military' && s.cls !== 'space') continue;
      n++;
      L.circleMarker([s.lat, s.lon], { radius: s.cls === 'military' || s.cls === 'space' ? 3 : 2.5, color: '#000', weight: 0.8, fillColor: RADAR_COL[s.cls] || '#6f7f93', fillOpacity: 0.85 })
        .bindPopup(`<h4>${esc(s.name || 'Unnamed radar')}</h4>${kv([['Class', esc(s.cls)], ['Kind', esc(s.kind || '')], ['Operator', esc(s.operator || '')], ['Height', esc(s.height || '')], ['Note', esc(s.desc || '')]])}<p style="margin:6px 0 0"><a href="https://www.openstreetmap.org/${s.id[0] === 'n' ? 'node' : s.id[0] === 'w' ? 'way' : 'relation'}/${esc(s.id.slice(1))}" target="_blank" rel="noopener">OpenStreetMap ↗</a></p><p class="dim" style="margin:4px 0 0">${esc(data.attribution || '')}</p>`)
        .addTo(g);
    }
    setCount('radars', `${n}/${data.count}`); done('radars');
  }
  async function loadIoda() {
    const g = groups.ioda; g.clearLayers();
    const { data } = await api('/api/layers/ioda');
    if (!data) { setCount('ioda', 0); return; }
    let n = 0;
    for (const e of data.entities || []) {
      if (e.lat == null || e.type !== 'country') continue;
      const crit = e.critical > 0;
      if (!crit && e.alerts < 3) continue;
      n++;
      const r = Math.min(22, 6 + Math.sqrt(e.alerts) * 2.5);
      L.circleMarker([e.lat, e.lon], { radius: r, color: crit ? '#ff8c42' : '#8a5a2b', weight: 1.5, fillColor: crit ? '#ff8c42' : '#8a5a2b', fillOpacity: crit ? 0.35 : 0.15 })
        .bindPopup(`<h4>${esc(e.name)} — internet outage signal</h4>${kv([['Alerts 24h', `${e.alerts} (${e.critical} critical, ${e.warning} warning)`], ['Sources', esc((e.sources || []).map((s) => `${s[0]} ${s[1]}`).join(', '))], ['Window', `${fmtZ(e.first)} → ${fmtZ(e.last)}`]])}<p style="margin:6px 0 0"><a href="https://ioda.inetintel.cc.gatech.edu/country/${esc(e.code)}" target="_blank" rel="noopener">Open in IODA ↗</a></p>`)
        .addTo(g);
    }
    setCount('ioda', n); done('ioda');
  }
  async function loadRansomware() {
    const g = groups.ransomware; g.clearLayers();
    const { points } = await api('/api/layers/ransomware?hours=720');
    for (const p of points) {
      const r = Math.min(26, 4 + Math.sqrt(p.count) * 3);
      L.circleMarker([p.lat, p.lon], { radius: r, color: '#b48cff', weight: 1, fillColor: '#b48cff', fillOpacity: 0.28 })
        .bindPopup(`<h4>${flag(p.country)} ${esc(p.name)}</h4><div>${p.count} ransomware victims claimed in 30 days (ransomware.live)</div><p style="margin:6px 0 0"><a href="#" data-country="${esc(p.country)}" class="filter-country">Show victims in feed</a></p>`)
        .addTo(g);
    }
    setCount('ransomware', points.reduce((a, p) => a + p.count, 0)); done('ransomware');
  }
  async function loadC2() {
    const g = groups.c2; g.clearLayers();
    const { data } = await api('/api/layers/c2');
    if (!data) { setCount('c2', 0); return; }
    for (const p of data.countries || []) {
      const r = Math.min(24, 3 + Math.sqrt(p.count) * 2.2);
      L.circleMarker([p.lat, p.lon], { radius: r, color: '#3cc7ff', weight: 1, fillColor: '#3cc7ff', fillOpacity: 0.2, dashArray: '2 3' })
        .bindPopup(`<h4>${flag(p.country)} ${esc(p.name)} — botnet C2</h4>${kv([['Tracked servers', `${p.count} (${p.online} online)`], ['Families', esc((p.malware || []).map((m) => `${m[0]} ${m[1]}`).join(', '))]])}<p class="dim" style="margin:6px 0 0">abuse.ch Feodo Tracker</p>`)
        .addTo(g);
    }
    setCount('c2', data.total); done('c2');
  }
  const GD_COL = { cyber: '#3cc7ff', gnss: '#f3b23e', infra: '#2bb9a8', satcom: '#ff6fb1' };
  async function loadGdelt() {
    const g = groups.gdelt; g.clearLayers();
    const { data } = await api('/api/layers/gdelt');
    if (!data) { setCount('gdelt', 0); return; }
    let n = 0;
    for (const t of data.themes || []) {
      for (const p of t.points || []) {
        n++;
        const r = Math.min(10, 3 + Math.sqrt(p.count) * 1.4);
        const links = (p.links || []).map((l) => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a> <span class="dim">${esc(l.domain || '')}</span></li>`).join('');
        L.circleMarker([p.lat + (t.key === 'gnss' ? 0.8 : t.key === 'infra' ? -0.8 : 0), p.lon + (t.key === 'satcom' ? 1.2 : 0)], { radius: r, color: GD_COL[t.key] || '#45d38a', weight: 1, fillColor: GD_COL[t.key] || '#45d38a', fillOpacity: 0.5 })
          .bindPopup(`<h4>${esc(t.label)}: ${flag(p.country)} ${esc(p.name)}</h4><div class="muted">${p.count} articles in 24h (GDELT)${p.inferred ? `, ${p.inferred} placed by publisher country` : ''}</div><ul>${links}</ul>`)
          .addTo(g);
      }
    }
    setCount('gdelt', n); done('gdelt');
  }
  async function loadCloudflare() {
    const g = groups.cloudflare; g.clearLayers();
    const { data } = await api('/api/layers/cloudflare');
    if (!data) { setCount('cloudflare', 'key'); return; }
    let n = 0;
    for (const o of data.outages_7d || []) {
      if (o.lat == null) continue;
      n++;
      L.circleMarker([o.lat + 0.6, o.lon + 0.6], { radius: 7, color: '#ffd166', weight: 1.5, fillColor: '#ffd166', fillOpacity: 0.3 })
        .bindPopup(`<h4>${esc(o.description || 'Outage')}</h4>${kv([['Type', esc(o.type || '?')], ['Cause', esc(o.cause || '?')], ['Start', esc(o.start || '')], ['End', esc(o.end || 'ongoing')]])}${o.url ? `<p style="margin:6px 0 0"><a href="${esc(o.url)}" target="_blank" rel="noopener">Source ↗</a></p>` : ''}`)
        .addTo(g);
    }
    setCount('cloudflare', n); done('cloudflare');
  }
  async function loadItemsLayer() {
    const g = groups.items; g.clearLayers();
    const { points } = await api('/api/layers/items?hours=168');
    const seen = {};
    for (const p of points) {
      const key = `${p.lat},${p.lon}`; seen[key] = (seen[key] || 0) + 1;
      const k = seen[key];
      const jitter = [(k % 5 - 2) * 0.35, (Math.floor(k / 5) % 5 - 2) * 0.45];
      L.circleMarker([p.lat + jitter[0], p.lon + jitter[1]], { radius: 3 + (p.severity - 2) * 0.8, color: COLOURS[p.domain] || '#8593a6', weight: 1, fillColor: COLOURS[p.domain] || '#8593a6', fillOpacity: 0.7 })
        .bindPopup(`<h4>${esc(p.title)}</h4><div class="muted">${esc(p.source)} · ${fmtZ(p.published_at)} · sev ${p.severity}</div>${p.summary ? `<p>${esc(p.summary.slice(0, 260))}</p>` : ''}<p style="margin:6px 0 0"><a href="${esc(p.url)}" target="_blank" rel="noopener">Open ↗</a></p>`)
        .addTo(g);
    }
    setCount('items', points.length); done('items');
  }
  async function loadApt() {
    const g = groups.apt; g.clearLayers();
    const { groups: gs } = await api('/api/layers/apt');
    for (const a of gs) {
      const icon = L.divIcon({ className: '', html: `<div style="width:11px;height:11px;transform:rotate(45deg);background:${a.type === 'criminal' ? '#ffd166' : '#ff8c42'};border:1px solid #000"></div>`, iconSize: [11, 11] });
      L.marker([a.lat, a.lon], { icon })
        .bindPopup(`<h4>${esc(a.name)} <span class="muted">${esc(a.aka || '')}</span></h4>${kv([['Sponsor', `${flag(a.country)} ${esc(a.sponsor)}`], ['Type', esc(a.type)], ['Targets', esc((a.sectors || []).join(', '))], ['MITRE', a.mitre ? `<a href="https://attack.mitre.org/groups/${esc(a.mitre)}/" target="_blank" rel="noopener">${esc(a.mitre)} ↗</a>` : '']])}<p style="margin:6px 0 0">${esc(a.note)}</p><p class="dim" style="margin:6px 0 0">Reference layer; attributions as publicly reported.</p>`)
        .addTo(g);
    }
    setCount('apt', gs.length); done('apt');
  }
  async function loadCables() {
    const g = groups.cables; g.clearLayers();
    const { data } = await api('/api/layers/cables');
    if (!data) { setCount('cables', '–'); return; }
    L.geoJSON(data, { style: (f) => ({ color: f.properties.color || '#2bb9a8', weight: 1, opacity: 0.35 }), onEachFeature: (f, l) => l.bindPopup(`<h4>${esc(f.properties.name)}</h4><div class="dim">TeleGeography Submarine Cable Map</div>`) }).addTo(g);
    setCount('cables', (data.features || []).length); done('cables');
  }
  async function loadLaunches() {
    const g = groups.launches; g.clearLayers();
    const { data } = await api('/api/layers/launches');
    if (!data) { setCount('launches', '–'); return; }
    for (const l of data.launches || []) {
      if (l.lat == null) continue;
      const icon = L.divIcon({ className: '', html: `<div style="color:#fff;font-size:13px;line-height:13px;text-shadow:0 0 3px #000">▲</div>`, iconSize: [13, 13] });
      L.marker([l.lat, l.lon], { icon }).bindPopup(`<h4>${esc(l.name)}</h4>${kv([['NET', fmtZ(l.net)], ['Provider', esc(l.provider || '')], ['Mission', `${esc(l.mission || '?')} (${esc(l.mission_type || '')}${l.orbit ? ', ' + esc(l.orbit) : ''})`], ['Pad', `${esc(l.pad || '')}, ${esc(l.location || '')}`]])}`).addTo(g);
    }
    setCount('launches', (data.launches || []).length); done('launches');
  }
  // ---- spectrum: Ofcom WTR baseline + planned emitters ------------------------------
  const SPEC = (() => { try { return { guard_khz: 0, radius_km: 50, span_khz: 200, ...JSON.parse(localStorage.getItem('cyem.spec') || '{}') }; } catch { return { guard_khz: 0, radius_km: 50, span_khz: 200 }; } })();
  const saveSpec = () => saveLs('cyem.spec', SPEC);
  const mhz = (hz) => (hz / 1e6).toFixed(hz % 1000 ? 6 : hz % 1e6 ? 4 : 3).replace(/0+$/, '').replace(/\.$/, '');
  const khz = (hz) => `${+(hz / 1e3).toFixed(2)}`;
  function wtrColour(p) {
    p = p || '';
    if (/^BR /.test(p)) return '#3cc7ff';
    if (/Fixed Links|Self Co-Ord|Scanning Telemetry/.test(p)) return '#8593a6';
    if (/AIS|Maritime|Marina|CSR|Coastal/.test(p)) return '#2bb9a8';
    if (/Satellite/.test(p)) return '#ff6fb1';
    if (/GNSS|Differential Global/.test(p)) return '#f3b23e';
    return '#c8d3e0';
  }
  function wtrPopupRows(list) {
    const shown = list.slice(0, 25).map((r) => `<tr><td class="mono">${mhz(r.freq_hz)}</td><td class="mono">${khz(r.bw_hz)}${r.bw_src === 'emission' ? '*' : ''}</td><td>${esc(r.station_type || '')}</td><td class="mono">${r.erp != null ? esc(`${+r.erp.toFixed(2)} ${r.erp_unit || ''}`) : ''}</td><td class="mono">${esc(r.emission || '')}</td></tr>`).join('');
    return `<table class="grid"><tr><th>MHz</th><th>BW kHz</th><th>T/R</th><th>ERP</th><th>Emission</th></tr>${shown}</table>${list.length > 25 ? `<p class="dim">+${list.length - 25} more at this site</p>` : ''}`;
  }
  let wtrSeq = 0;
  async function loadWtr() {
    const g = groups.wtr; const seq = ++wtrSeq;
    if (map.getZoom() < 8) { g.clearLayers(); setCount('wtr', 'zoom in'); done('wtr'); return; }
    const b = map.getBounds().pad(0.1);
    const q = `s=${b.getSouth().toFixed(4)}&w=${b.getWest().toFixed(4)}&n=${b.getNorth().toFixed(4)}&e=${b.getEast().toFixed(4)}&limit=6000`;
    let res;
    try { res = await api(`/api/spectrum/wtr?${q}`); } catch (e) { setCount('wtr', 'err'); throw e; }
    if (seq !== wtrSeq) return;
    g.clearLayers();
    const sites = new Map();
    for (const r of res.rows) { const k = `${r.lat.toFixed(4)},${r.lon.toFixed(4)}`; if (!sites.has(k)) sites.set(k, []); sites.get(k).push(r); }
    for (const list of sites.values()) {
      const r0 = list[0];
      const byLic = [...new Set(list.map((r) => `${r.company || 'Licensee withheld'} · ${r.product} · ${r.licence}`))];
      L.circleMarker([r0.lat, r0.lon], { radius: Math.min(3 + Math.log2(list.length + 1), 8), color: wtrColour(r0.product), weight: 1, fillOpacity: 0.55 })
        .bindPopup(() => `<h4>${esc(r0.company || 'Licensee withheld')}</h4><p class="dim" style="margin:0 0 6px">${byLic.slice(0, 4).map(esc).join('<br>')}${byLic.length > 4 ? `<br>+${byLic.length - 4} more licences` : ''}</p>${wtrPopupRows(list)}<p class="dim" style="margin:6px 0 0">Ofcom WTR licensed assignment, not measured activity. * BW from emission code.</p>`, { maxWidth: 420 })
        .addTo(g);
    }
    setCount('wtr', res.total > res.returned ? `${res.returned}/${res.total}` : res.total); done('wtr');
  }
  map.on('moveend', () => { if (map.hasLayer(groups.wtr)) loadWtr().catch((e) => console.warn('wtr', e)); });
  let lastConflicts = null;
  const SEV_COL = { high: '#ff5c5c', medium: '#f3b23e', low: '#f3b23e' };
  const worst = (cs) => cs.some((c) => c.severity === 'high') ? 'high' : cs.some((c) => c.severity === 'medium') ? 'medium' : cs.length ? 'low' : null;
  async function fetchConflicts() {
    lastConflicts = await api(`/api/spectrum/conflicts?guard_khz=${SPEC.guard_khz}&radius_km=${SPEC.radius_km}&harm_order=${SPEC.harm_order ?? 3}&cosite_km=${SPEC.cosite_km ?? 1}`);
    return lastConflicts;
  }
  function conflictRows(cs, max = 12) {
    if (!cs.length) return '<p class="ok">No conflicts at current settings.</p>';
    const mech = (c) => !c.mechanism || c.mechanism === 'fundamental' ? 'fund.' : `<span title="product at ${mhz(c.product_hz)} MHz, BW ${khz(c.product_bw_hz)} kHz">${esc(c.mechanism === 'im3' ? 'IM3' : c.label)}</span>`;
    return `<table class="grid"><tr><th>Sev</th><th>Type</th><th>Against</th><th>MHz</th><th>BW kHz</th><th>Spacing kHz</th><th>km</th></tr>${cs.slice(0, max).map((c) => {
      const m = c.b_meta || {};
      const who = c.b_kind === 'product' ? `<b>hit by:</b> ${esc(c.b_name)}` : c.b_kind !== 'planned' ? `${esc(c.b_name)}<div class="dim">${esc(m.product || '')} · ${esc(m.licence || '')}</div>` : `<b>planned:</b> ${esc(c.b_name)}`;
      return `<tr><td style="color:${SEV_COL[c.severity]}">${c.severity}</td><td class="mono">${mech(c)}</td><td>${who}</td><td class="mono">${mhz(c.b_freq_hz)}</td><td class="mono">${khz(c.b_bw_hz)}</td><td class="mono">${khz(c.spacing_hz)}${c.co_channel ? '' : ' <span class="dim">(guard)</span>'}</td><td class="mono">${c.dist_km ?? '<span title="Area licence; location not published">area</span>'}${c.pred_dbm != null ? `<div class="dim" title="predicted level of our signal at the licensee">${c.pred_dbm} dBm</div>` : ''}</td></tr>`;
    }).join('')}</table>${cs.length > max ? `<p class="dim">+${cs.length - max} more</p>` : ''}`;
  }
  async function loadPlanned() {
    const g = groups.planned;
    const res = await fetchConflicts();
    g.clearLayers();
    for (const p of res.planned) {
      const w = worst(p.conflicts);
      const col = w ? SEV_COL[w] : '#45d38a';
      L.circle([p.lat, p.lon], { radius: res.radius_km * 1000, color: col, weight: 1, dashArray: '4 6', fill: false, interactive: false }).addTo(g);
      L.circleMarker([p.lat, p.lon], { radius: 8, color: '#fff', weight: 1.5, fillColor: col, fillOpacity: 0.9 })
        .bindPopup(() => `<h4>${esc(p.name)}</h4>${kv([['Freq', `${mhz(p.freq_hz)} MHz`], ['BW', `${khz(p.bw_hz)} kHz`], ['Power', p.power_w != null ? `${p.power_w} W` : ''], ['Window', `${p.start ? fmtZ(p.start) : 'open'} → ${p.end ? fmtZ(p.end) : 'open'}`], ['Conflicts', `${p.conflicts.length}`]])}${conflictRows(p.conflicts, 6)}<p style="margin:6px 0 0"><a href="#" class="spec-open" data-id="${esc(p.id)}">Open in Spectrum ›</a></p>`, { maxWidth: 460 })
        .addTo(g);
    }
    setCount('planned', res.planned.length ? `${res.planned.length} · ${res.totals.high || 0}H ${res.totals.medium || 0}M` : ''); done('planned');
  }
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelectorAll('a.spec-open').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); map.closePopup(); openSpectrum(a.dataset.id); }));
  });
  function loadLayers(minutes) {
    for (const L_ of LAYERS) {
      if (!map.hasLayer(groups[L_.id])) continue;
      if (minutes != null && (L_.every === 0 || minutes % L_.every !== 0) && L_.loaded) continue;
      L_.load().catch((e) => console.warn(L_.id, e));
    }
  }
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelectorAll('a.filter-country').forEach((a) => a.addEventListener('click', (ev) => {
      ev.preventDefault(); state.country = a.dataset.country; state.dom = 'cyber'; setTab('cyber'); loadFeed(); map.closePopup(); showRail(true);
    }));
  });

  // ---------------------------------------------------------------- status pills
  function pill(id, lbl, val, cls, title) { return `<div class="pill ${cls || ''}" data-p="${id}" title="${esc(title || '')}"><span class="lbl">${esc(lbl)}</span><b>${esc(val)}</b></div>`; }
  function renderPills(s) {
    const sw = s.spaceweather || {};
    const kp = sw.kp;
    const kpCls = kp == null ? '' : kp >= 6 ? 'bad' : kp >= 4 ? 'warn' : 'ok';
    const sc = sw.scales || {};
    const lvl = (c) => (sc[c] && sc[c].level != null) ? String(sc[c].level) : '?';
    const maxLvl = Math.max(...['R', 'S', 'G'].map((c) => parseInt(lvl(c)) || 0));
    const scCls = maxLvl >= 3 ? 'bad' : maxLvl >= 1 ? 'warn' : 'ok';
    const hf = s.hf || {};
    const gn = s.gnss || {};
    const out = s.outages || {};
    const nCrit = (out.countries_critical || []).length;
    const kev = s.kev || {};
    const rw = s.ransomware || {};
    const br = s.brief || {};
    const briefVal = br.generating ? 'generating…' : (br.latest_at ? ago(br.latest_at) + ' ago' : 'none');
    const html = [
      pill('sw', 'Kp', kp == null ? '–' : kp.toFixed(1), kpCls, 'Planetary K-index (NOAA SWPC). Click for space weather detail'),
      pill('sw', 'R/S/G', `${lvl('R')}/${lvl('S')}/${lvl('G')}`, scCls, 'NOAA scales now: radio blackout / solar radiation / geomagnetic storm'),
      pill('sw', 'Flare', sw.max_flare_24h || '–', (sw.max_flare_24h || '').startsWith('X') ? 'bad' : (sw.max_flare_24h || '').startsWith('M') ? 'warn' : '', 'Largest GOES X-ray flare in 24h'),
      pill('hf', 'HF', hf.solarflux ? `SFI ${hf.solarflux} · geomag ${(hf.geomagfield || '?').toLowerCase()}` : '–', hf.geomagfield && /storm|unsettled|^active/i.test(hf.geomagfield) ? 'warn' : hf.geomagfield ? 'ok' : '', 'SFI = 10.7 cm solar flux (higher = better HF propagation on the high bands). Geomag = geomagnetic field state from hamqsl: inactive / quiet = calm (good), unsettled / active / storm = disturbed HF and GNSS. Click for band conditions'),
      ...(s.aurora ? [pill('sw', 'Aurora', `N ${s.aurora.max_north ?? 0}% · S ${s.aurora.max_south ?? 0}%`, Math.max(s.aurora.max_north || 0, s.aurora.max_south || 0) >= 50 ? 'bad' : Math.max(s.aurora.max_north || 0, s.aurora.max_south || 0) >= 25 ? 'warn' : 'ok', `OVATION aurora probability maxima, forecast ${s.aurora.forecast_time || ''}`)] : []),
      ...(s.drap ? [pill('sw', 'D-RAP', s.drap.max_mhz > 0 ? `${s.drap.max_mhz} MHz` : 'clear', s.drap.max_mhz >= 15 ? 'bad' : s.drap.max_mhz > 0 ? 'warn' : 'ok', `Highest HF frequency affected by D-region absorption (NOAA D-RAP, valid ${s.drap.valid_at || ''})`)] : []),
      pill('gnss', 'GNSS', gn.date ? `${gn.high} high` : '–', gn.high >= 40 ? 'bad' : gn.high >= 15 ? 'warn' : gn.date ? 'ok' : '', `GNSS interference hexes for ${gn.date || '?'} (gpsjam)`),
      pill('out', 'Outages', out.alerts_24h != null ? `${nCrit} critical` : '–', nCrit >= 3 ? 'bad' : nCrit >= 1 ? 'warn' : out.alerts_24h != null ? 'ok' : '', 'Countries with critical IODA outage alerts in 24h'),
      pill('kev', 'KEV 7d', kev.added_7d != null ? kev.added_7d : '–', kev.added_7d >= 8 ? 'warn' : 'info', 'CISA KEV entries added in 7 days'),
      pill('rw', 'Ransom 7d', rw.victims_7d != null ? rw.victims_7d : '–', 'info', 'Victims claimed on leak sites in 7 days (ransomware.live)'),
      ...(s.opencti ? [pill('octi', 'OpenCTI', `${s.opencti.reports_24h ?? 0} rep · ${s.opencti.indicators_24h ?? 0} ind`, (s.opencti.errors || []).length ? 'warn' : 'info', `OpenCTI ${s.opencti.version || ''}: reports and new indicators in 24h. Click for detail`)] : []),
      pill('items', 'Sev4+ 24h', (s.counts || {}).high_24h ?? '–', ((s.counts || {}).high_24h || 0) >= 10 ? 'warn' : 'info', 'Items with severity 4 or 5 in 24h'),
      pill('brief', 'Brief', briefVal, br.generating ? 'warn' : br.last_error ? 'bad' : 'info', br.last_error || `Scheduled at ${(br.hours || []).map((h) => String(h).padStart(2, '0') + ':00').join(', ')} ${s.tz || ''}`),
    ].join('');
    $('#pills').innerHTML = html;
    $$('#pills .pill').forEach((p) => p.addEventListener('click', () => onPill(p.dataset.p)));
  }
  function onPill(id) {
    const s = state.status || {};
    if (id === 'sw') return showSpaceWeather(s);
    if (id === 'hf') return showHF(s.hf);
    if (id === 'gnss') { map.setView([45, 30], 4); const cb = $$('#layers input')[0]; if (!cb.checked) cb.click(); return; }
    if (id === 'out') { state.dom = 'infra'; setTab('infra'); state.q = ''; $('#q').value = ''; loadFeed(); showRail(true); return; }
    if (id === 'kev') { state.dom = 'cyber'; setTab('cyber'); state.q = 'KEV'; $('#q').value = 'KEV'; loadFeed(); showRail(true); return; }
    if (id === 'rw') { state.dom = 'cyber'; setTab('cyber'); state.q = 'ransomware'; $('#q').value = 'ransomware'; loadFeed(); showRail(true); return; }
    if (id === 'items') { $('#hi-only').checked = true; state.hiOnly = true; state.hours = 24; $('#hours').value = '24'; loadFeed(); showRail(true); return; }
    if (id === 'brief') { showSide(true); return; }
    if (id === 'octi') { showOpenCTI(); return; }
  }
  async function showOpenCTI() {
    let data;
    try { ({ data } = await api('/api/layers/opencti')); } catch (e) { return openModal('OpenCTI', `<p class="bad">${esc(e.message)}</p>`); }
    if (!data) return openModal('OpenCTI', '<p class="muted">Not configured. Set OPENCTI_URL and OPENCTI_TOKEN in ~/cyem/.env.</p>');
    const reps = (data.reports || []).map((r) => `<tr><td class="mono">${fmtZ(r.published)}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a></td><td>${esc((r.types || []).join(', '))}</td><td>${esc((r.labels || []).join(', '))}</td></tr>`).join('');
    const inds = (data.top_indicators || []).map((i) => `<tr><td class="mono">${i.score ?? ''}</td><td>${esc(i.type)}</td><td><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.name || i.pattern)}</a></td><td>${esc((i.labels || []).join(', '))}</td><td class="mono">${fmtZ(i.valid_until)}</td></tr>`).join('');
    const sets = (data.intrusion_sets || []).map((x) => `<tr><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a><div class="dim">${esc((x.aliases || []).join(', '))}</div></td><td class="mono">${fmtZ(x.modified)}</td><td>${esc(x.description || '')}</td></tr>`).join('');
    openModal(`OpenCTI ${esc(data.version || '')} — ${esc(data.url || '')}`, `
      ${(data.errors || []).length ? `<div class="notice err">${esc(data.errors.join(' · '))}</div>` : ''}
      <div class="kv"><span class="k">Reports 24h</span><span>${data.reports_24h ?? 0}</span><span class="k">New indicators 24h</span><span>${data.indicators_24h ?? 0} — ${esc((data.indicator_types || []).map((t) => `${t[0]} ${t[1]}`).join(', '))}</span><span class="k">Top labels</span><span>${esc((data.indicator_labels || []).map((t) => `${t[0]} ${t[1]}`).join(', '))}</span><span class="k">Fetched</span><span class="mono">${fmtZ(data.fetched_at)}</span></div>
      <h3 class="sec">Recent reports</h3><table class="grid"><tr><th>Published</th><th>Report</th><th>Type</th><th>Labels</th></tr>${reps || '<tr><td colspan=4 class="muted">none</td></tr>'}</table>
      <h3 class="sec">Highest-scored new indicators (24h)</h3><table class="grid"><tr><th>Score</th><th>Type</th><th>Indicator</th><th>Labels</th><th>Valid until</th></tr>${inds || '<tr><td colspan=5 class="muted">none</td></tr>'}</table>
      <h3 class="sec">Recently modified intrusion sets</h3><table class="grid"><tr><th>Set</th><th>Modified</th><th>Description</th></tr>${sets || '<tr><td colspan=3 class="muted">none</td></tr>'}</table>`);
  }
  function showSpaceWeather(s) {
    const sw = s.spaceweather || {};
    const series = sw.kp_series || [];
    const bars = series.map((k) => `<i class="${k.kp >= 7 ? 'k7' : k.kp >= 6 ? 'k6' : k.kp >= 5 ? 'k5' : ''}" style="height:${Math.max(4, k.kp / 9 * 100)}%" title="${esc(k.t)} Kp ${k.kp}"></i>`).join('');
    const sc = sw.scales || {}, p24 = sw.past24h || {}, pred = sw.predicted || {};
    const scaleRow = (c, name) => `<tr><td>${name}</td><td class="mono">${esc(sc[c]?.level ?? '?')} ${esc(sc[c]?.text || '')}</td><td class="mono">${esc(p24[c]?.level ?? '?')} ${esc(p24[c]?.text || '')}</td></tr>`;
    const predRows = Object.values(pred).map((v) => `<tr><td>${esc(v.date)}</td><td class="mono">G${esc(v.G)}</td><td class="mono">${esc(v.R_minor_prob)}% / ${esc(v.R_major_prob)}%</td><td class="mono">${esc(v.S_prob)}%</td></tr>`).join('');
    const flares = (sw.flares || []).map((f) => `<tr><td class="mono">${esc(f.class)}</td><td>${fmtZ(f.begin)}</td><td>${esc(f.max_time || '')}</td><td>${esc(f.region || '')}</td></tr>`).join('');
    const alerts = (sw.alerts || []).map((a) => `<tr><td class="mono">${fmtZ(a.issued)}</td><td>${esc(a.headline)}</td></tr>`).join('');
    const w = sw.solar_wind || {};
    openModal('Space weather (NOAA SWPC)', `
      <div class="kv"><span class="k">Kp now</span><span class="mono">${sw.kp ?? '–'} (24h max ${sw.kp_max_24h ?? '–'})</span><span class="k">F10.7</span><span class="mono">${sw.f107 ?? '–'} sfu</span><span class="k">Solar wind</span><span class="mono">${w.speed_kms ?? '–'} km/s, Bt ${w.bt ?? '–'} nT, Bz ${w.bz ?? '–'} nT</span><span class="k">Updated</span><span class="mono">${fmtZ(sw.updated)}</span></div>
      <h3 class="sec">Kp, last ${series.length * 3} hours</h3><div class="kpbars">${bars || '<span class="muted">no data</span>'}</div>
      <h3 class="sec">NOAA scales</h3><table class="grid"><tr><th>Scale</th><th>Now</th><th>Max 24h</th></tr>${scaleRow('R', 'R radio blackout')}${scaleRow('S', 'S solar radiation')}${scaleRow('G', 'G geomagnetic')}</table>
      <h3 class="sec">3-day outlook</h3><table class="grid"><tr><th>Day</th><th>G</th><th>R1-2 / R3+ prob</th><th>S1+ prob</th></tr>${predRows || '<tr><td colspan=4 class="muted">no forecast</td></tr>'}</table>
      <h3 class="sec">X-ray flares, 3 days</h3><table class="grid"><tr><th>Class</th><th>Begin</th><th>Peak</th><th>Region</th></tr>${flares || '<tr><td colspan=4 class="muted">none recorded</td></tr>'}</table>
      <h3 class="sec">Alerts, watches, warnings</h3><table class="grid">${alerts || '<tr><td class="muted">none in 3 days</td></tr>'}</table>
      <p class="dim">Operational reading: R scale = HF absorption on the sunlit hemisphere; G scale = GNSS accuracy, HF auroral absorption and geomagnetically induced currents; S scale = SATCOM and polar HF.</p>`);
  }
  function showHF(hf) {
    if (!hf) return openModal('HF conditions', '<p class="muted">No data yet.</p>');
    const bands = Object.entries(hf.bands || {}).map(([b, v]) => `<div class="band"><b>${esc(b)}</b>day <span class="cond-${esc(v.day)}">${esc(v.day)}</span> · night <span class="cond-${esc(v.night)}">${esc(v.night)}</span></div>`).join('');
    const vhf = (hf.vhf || []).map((v) => `<tr><td>${esc(v.name)}</td><td>${esc(v.location || '')}</td><td>${esc(v.value)}</td></tr>`).join('');
    openModal('HF and VHF conditions (hamqsl.com, N0NBH)', `
      <div class="kv"><span class="k">Solar flux</span><span class="mono">${esc(hf.solarflux)}</span><span class="k">Sunspots</span><span class="mono">${esc(hf.sunspots)}</span><span class="k">A / K index</span><span class="mono">${esc(hf.aindex)} / ${esc(hf.kindex)}</span><span class="k">X-ray</span><span class="mono">${esc(hf.xray)}</span><span class="k">Geomagnetic field</span><span>${esc(hf.geomagfield)}</span><span class="k">Signal noise</span><span>${esc(hf.signalnoise)}</span><span class="k">MUF</span><span class="mono">${esc(hf.muf || '–')}</span><span class="k">Aurora</span><span class="mono">${esc(hf.aurora)} (lat ${esc(hf.latdegree)})</span><span class="k">Updated</span><span>${esc(hf.updated)}</span></div>
      <h3 class="sec">Band conditions</h3><div class="bands">${bands}</div>
      <h3 class="sec">VHF</h3><table class="grid"><tr><th>Phenomenon</th><th>Location</th><th>State</th></tr>${vhf}</table>`);
  }

  // ---------------------------------------------------------------- feed
  function setTab(dom) { $$('#dom-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.dom === dom)); }
  $$('#dom-tabs button').forEach((b) => b.addEventListener('click', () => { state.dom = b.dataset.dom; state.country = null; setTab(state.dom); loadFeed(); }));
  let qTimer;
  $('#q').addEventListener('input', (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); loadFeed(); }, 300); });
  $('#hi-only').addEventListener('change', (e) => { state.hiOnly = e.target.checked; loadFeed(); });
  $('#hours').addEventListener('change', (e) => { state.hours = parseInt(e.target.value); loadFeed(); });
  const HOT = new Set(['zero-day', 'kev', 'ransomware', 'apt', 'ics', 'gnss', 'ew', 'satcom', 'cable', 'outage', 'bgp', 'uk']);
  async function loadFeed() {
    const p = new URLSearchParams({ hours: state.hours, limit: 200 });
    if (state.dom !== 'all') p.set('domain', state.dom);
    if (state.q) p.set('q', state.q);
    if (state.hiOnly) p.set('min_severity', 3);
    if (state.country) p.set('country', state.country);
    let data;
    try { data = await api('/api/items?' + p); } catch (e) { $('#feed').innerHTML = `<div class="empty">Feed unavailable: ${esc(e.message)}</div>`; return; }
    const rows = data.items || [];
    if (!rows.length) { $('#feed').innerHTML = `<div class="empty">Nothing matches.${state.country ? ` <a href="#" id="clear-country">Clear country filter</a>` : ''}</div>`; $('#clear-country')?.addEventListener('click', (e) => { e.preventDefault(); state.country = null; loadFeed(); }); return; }
    const head = state.country ? `<div class="notice">Filtered to ${flag(state.country)} ${esc(rows[0].country_name || state.country)} · <a href="#" id="clear-country">clear</a></div>` : '';
    $('#feed').innerHTML = head + rows.map((it) => `
      <div class="item s${it.severity}" data-id="${esc(it.id)}" data-lat="${it.lat ?? ''}" data-lon="${it.lon ?? ''}">
        <div class="sev" title="severity ${it.severity}"></div>
        <div>
          <div class="meta"><span class="dom ${esc(it.domain)}">${esc(it.domain)}</span><span>${esc(it.source)}</span><span>·</span><span title="${esc(it.published_at)}">${ago(it.published_at)}</span>${it.country ? `<span title="${esc(it.country_name || it.country)}">${flag(it.country)}</span>` : ''}${it.kind !== 'news' ? `<span class="dim">${esc(it.kind)}</span>` : ''}</div>
          <div class="title"><a href="${esc(it.url || '#')}" target="_blank" rel="noopener">${esc(it.title)}</a></div>
          <div class="summary">${esc(it.summary || '')}${it.extra && it.extra.epss != null ? ` <span class="mono">EPSS ${Number(it.extra.epss).toFixed(2)}</span>` : ''}</div>
          <div class="tags">${(it.tags || []).slice(0, 6).map((t) => `<span class="tag ${HOT.has(t) ? 'hot' : ''}">${esc(t)}</span>`).join('')}${it.lat != null ? '<span class="tag locate" style="cursor:pointer">◎ locate</span>' : ''}</div>
        </div>
      </div>`).join('');
    $('#clear-country')?.addEventListener('click', (e) => { e.preventDefault(); state.country = null; loadFeed(); });
    $$('#feed .item').forEach((el) => {
      el.addEventListener('click', (e) => { if (e.target.closest('a') || e.target.classList.contains('locate')) return; el.classList.toggle('open'); });
      el.querySelector('.locate')?.addEventListener('click', () => {
        const lat = parseFloat(el.dataset.lat), lon = parseFloat(el.dataset.lon);
        if (isFinite(lat)) { map.flyTo([lat, lon], Math.max(map.getZoom(), 4), { duration: .6 }); const t = el.querySelector('.title').textContent; L.popup().setLatLng([lat, lon]).setContent(`<h4>${esc(t)}</h4>`).openOn(map); }
      });
    });
  }

  // ---------------------------------------------------------------- brief
  function sanitize(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach((n) => n.remove());
    doc.querySelectorAll('*').forEach((n) => { for (const a of Array.from(n.attributes)) if (/^on/i.test(a.name) || (a.name === 'href' && /^javascript:/i.test(a.value))) n.removeAttribute(a.name); });
    return doc.body.innerHTML;
  }
  function renderMd(md) {
    let html = marked.parse(md || '', { gfm: true, breaks: false });
    html = sanitize(html).replace(/\[(\d{1,3})\]/g, '<span class="cite" title="source item in the brief context">[$1]</span>');
    return html;
  }
  async function loadBrief(id) {
    try {
      const { brief } = await api(id ? `/api/briefs/${id}` : '/api/briefs/latest');
      if (!brief) { $('#brief').innerHTML = '<div class="empty">No brief yet. Press Regenerate once collectors have run.</div>'; return; }
      state.briefId = brief.id;
      $('#brief').innerHTML = renderMd(brief.content);
      const { briefs } = await api('/api/briefs?limit=30');
      const opts = briefs.map((b) => `<option value="${b.id}" ${b.id === brief.id ? 'selected' : ''}>${fmtZ(b.created_at)} · ${esc(b.kind)}</option>`).join('');
      $('#brief-meta').innerHTML = `<span>${esc(brief.model)}</span><span>·</span><span>${brief.item_count} items</span><span>·</span><span>${Math.round(brief.duration_s)}s</span><select id="brief-hist">${opts}</select>`;
      $('#brief-hist').addEventListener('change', (e) => loadBrief(parseInt(e.target.value)));
    } catch (e) { $('#brief-notice').innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  }
  let pollTimer;
  async function pollBrief() {
    try {
      const st = await api('/api/briefs/state');
      if (st.generating) {
        $('#brief-notice').innerHTML = `<div class="notice"><span class="spinner"></span> Generating brief with ${esc((state.status?.brief || {}).model || 'Ollama')} on CPU — typically 2–5 minutes. Started ${ago(st.started_at)} ago.</div>`;
        $('#btn-gen').disabled = true;
        clearTimeout(pollTimer); pollTimer = setTimeout(pollBrief, 5000);
      } else {
        $('#btn-gen').disabled = false;
        $('#brief-notice').innerHTML = st.last_error ? `<div class="notice err">Last generation failed: ${esc(st.last_error)}</div>` : '';
        if (state.wasGenerating) { await loadBrief(); refreshStatus(); }
        state.wasGenerating = false;
      }
      state.wasGenerating = st.generating;
    } catch (e) { /* ignore */ }
  }
  $('#btn-gen').addEventListener('click', async () => {
    try { await api('/api/briefs/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hours: 24 }) }); state.wasGenerating = true; pollBrief(); }
    catch (e) { $('#brief-notice').innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  });

  // ---------------------------------------------------------------- ask
  $('#ask-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = $('#ask-q').value.trim();
    if (!q) return;
    const out = $('#answer');
    out.textContent = '';
    $('#ask-btn').disabled = true;
    out.innerHTML = '<span class="spinner"></span> thinking…';
    let text = '';
    try {
      const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let first = true;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          const line = p.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          const d = JSON.parse(line.slice(6));
          if (d.t) { if (first) { out.textContent = ''; first = false; } text += d.t; out.textContent = text; out.scrollTop = out.scrollHeight; }
          if (d.error) { out.textContent = `Error: ${d.error}`; }
        }
      }
      if (text) out.innerHTML = renderMd(`**Q: ${q.replace(/\*/g, '')}**\n\n` + text);
    } catch (err) { out.textContent = `Error: ${err.message}`; }
    finally { $('#ask-btn').disabled = false; }
  });

  // ---------------------------------------------------------------- health modal
  function openModal(title, html) { $('#modal-title').textContent = title; $('#modal-body').innerHTML = html; $('#modal').classList.add('show'); }
  $('#modal-close').addEventListener('click', () => $('#modal').classList.remove('show'));
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') $('#modal').classList.remove('show'); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#modal').classList.remove('show'); });
  $('#btn-health').addEventListener('click', async () => {
    try {
      const [{ collectors, feeds }, ol, cfg] = await Promise.all([api('/api/collectors'), api('/api/ollama'), api('/api/config')]);
      const rows = collectors.map((c) => `<tr><td><b>${esc(c.name)}</b><div class="dim">${esc(c.description)}</div></td><td>${esc(c.domain)}</td><td class="mono">${Math.round(c.interval_s / 60)}m</td><td class="${c.running ? 'warn' : c.ok === 1 ? 'ok' : c.ok === 0 ? 'bad' : ''}">${c.running ? 'running' : c.ok === 1 ? 'ok' : c.ok === 0 ? 'FAIL' : c.enabled ? 'pending' : 'off'}</td><td class="mono" title="${esc(c.last_finished)}">${c.last_finished ? ago(c.last_finished) + ' ago' : '–'}</td><td class="mono">${c.count ?? ''}</td><td>${esc(c.message || '')}</td></tr>`).join('');
      const bad = feeds.filter((f) => f.fail_count > 0).map((f) => `<tr><td class="mono" style="word-break:break-all">${esc(f.url)}</td><td class="bad">${f.fail_count}</td><td>${esc(f.last_error || '')}</td></tr>`).join('');
      const olTxt = ol.reachable ? `<span class="ok">reachable</span> at ${esc(ol.url)} · model ${esc(ol.model)} ${ol.model_present ? '<span class="ok">present</span>' : '<span class="bad">NOT FOUND</span>'} · loaded: ${esc((ol.loaded || []).map((m) => m.name).join(', ') || 'none')}` : `<span class="bad">unreachable</span> ${esc(ol.error || '')}`;
      const keysTxt = Object.entries(cfg.keys || {}).map(([k, v]) => `<span class="${v ? 'ok' : 'dim'}">${esc(k)} ${v ? '✓' : '—'}</span>`).join(' · ');
      openModal('Collector health', `<p><b>Ollama:</b> ${olTxt}</p><p><b>Optional keys:</b> ${keysTxt} <span class="dim">(set in ~/cyem/.env, then docker compose up -d)</span></p><table class="grid"><tr><th>Collector</th><th>Domain</th><th>Every</th><th>State</th><th>Last</th><th>Count</th><th>Message</th></tr>${rows}</table>
        <h3 class="sec">Failing feeds (${feeds.filter((f) => f.fail_count > 0).length} of ${feeds.length})</h3><table class="grid"><tr><th>Feed</th><th>Fails</th><th>Error</th></tr>${bad || '<tr><td colspan=3 class="ok">all feeds healthy</td></tr>'}</table>
        <p style="margin-top:10px"><button id="run-all">Run all collectors now</button></p>`);
      $('#run-all').addEventListener('click', async () => { await api('/api/collect/all', { method: 'POST' }); $('#run-all').textContent = 'started'; setTimeout(() => { refreshStatus(); loadLayers(); loadFeed(); }, 20000); });
    } catch (e) { openModal('Collector health', `<p class="bad">${esc(e.message)}</p>`); }
  });

  // ---------------------------------------------------------------- spectrum planning panel
  let bandplan = null;
  let specSel = null;
  let draft = null;   // form contents survive a pick-on-map round trip
  const toLocalInput = (iso) => iso ? iso.slice(0, 16) : '';
  function specForm(d) {
    d = d || {};
    const v = (k, x) => esc(d[k] ?? x ?? '');
    return `<div class="specform">
      <input type="hidden" id="sp-id" value="${v('id')}">
      <label>Name<input id="sp-name" maxlength="80" value="${v('name')}" placeholder="e.g. Net 1 (exercise)"></label>
      <label>Freq MHz<input id="sp-f" type="number" step="any" value="${d.freq_hz != null ? mhz(d.freq_hz) : ''}"></label>
      <label>BW kHz<input id="sp-bw" type="number" step="any" value="${d.bw_hz != null ? khz(d.bw_hz) : '25'}"></label>
      <label>Power W<input id="sp-pw" type="number" step="any" value="${v('power_w')}"></label>
      <label>Lat<input id="sp-lat" type="number" step="any" value="${v('lat')}"></label>
      <label>Lon<input id="sp-lon" type="number" step="any" value="${v('lon')}"></label>
      <label>Start (Z)<input id="sp-start" type="datetime-local" value="${toLocalInput(d.start_at)}"></label>
      <label>End (Z)<input id="sp-end" type="datetime-local" value="${toLocalInput(d.end_at)}"></label>
      <label class="wide">Notes<input id="sp-notes" maxlength="500" value="${v('notes')}"></label>
      <div class="wide btns"><button id="sp-pick">Pick on map</button> <button id="sp-save" class="primary">${d.id ? 'Update' : 'Add'} emitter</button> <button id="sp-clear">Clear</button> <span id="sp-err" class="bad"></span></div>
    </div>`;
  }
  function readForm() {
    const n = (id) => { const x = $(id).value.trim(); return x === '' ? null : Number(x); };
    const t = (id) => { const x = $(id).value; return x ? `${x}:00Z` : null; };
    return { id: $('#sp-id').value || null, name: $('#sp-name').value.trim(), freq_mhz: n('#sp-f'), bw_khz: n('#sp-bw') ?? 0, power_w: n('#sp-pw'),
             lat: n('#sp-lat'), lon: n('#sp-lon'), start_at: t('#sp-start'), end_at: t('#sp-end'), notes: $('#sp-notes').value.trim() || null };
  }
  function formToDraft(f) {
    return { id: f.id, name: f.name, freq_hz: f.freq_mhz != null ? f.freq_mhz * 1e6 : null, bw_hz: f.bw_khz * 1e3, power_w: f.power_w,
             lat: f.lat, lon: f.lon, start_at: f.start_at, end_at: f.end_at, notes: f.notes };
  }
  function spectralSvg(v, guardHz) {
    const W = 900, padL = 8, padR = 8, top = 22, laneH = 11, maxLanes = 16;
    const f0 = v.planned.freq_hz, span = v.span_hz, lo = f0 - span, hi = f0 + span;
    const x = (f) => padL + ((f - lo) / (hi - lo)) * (W - padL - padR);
    const cl = (f) => Math.max(lo, Math.min(hi, f));
    const items = v.assignments.map((a) => ({ ...a, l: a.freq_hz - a.bw_hz / 2, r: a.freq_hz + a.bw_hz / 2 }))
      .filter((a) => a.r >= lo && a.l <= hi).sort((a, b) => a.l - b.l || a.dist_km - b.dist_km);
    const laneEnd = []; let hidden = 0;
    for (const a of items) {
      let k = laneEnd.findIndex((e) => e < a.l);
      if (k === -1) { if (laneEnd.length < maxLanes) { k = laneEnd.length; laneEnd.push(0); } else { hidden += 1; a.lane = -1; continue; } }
      laneEnd[k] = a.r + (hi - lo) * 0.002; a.lane = k;
    }
    const lanes = Math.max(laneEnd.length, 3), H = top + lanes * laneH + 34;
    const pl = v.planned, gl = pl.freq_hz - pl.bw_hz / 2 - guardHz, gr = pl.freq_hz + pl.bw_hz / 2 + guardHz;
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="background:#0a0e13;border:1px solid var(--border);border-radius:6px;font:10px var(--font)">`;
    for (const b of (bandplan?.bands || [])) {
      const bl = b.lo_mhz * 1e6, br = b.hi_mhz * 1e6;
      if (br < lo || bl > hi) continue;
      s += `<rect x="${x(cl(bl))}" y="2" width="${Math.max(1, x(cl(br)) - x(cl(bl)))}" height="14" fill="#1b2a3a" stroke="#2c4157"><title>${esc(b.label)} ${b.lo_mhz}–${b.hi_mhz} MHz</title></rect>`;
      s += `<text x="${x(cl(bl)) + 4}" y="12" fill="#8593a6">${esc(b.label)}</text>`;
    }
    s += `<rect x="${x(cl(gl))}" y="${top - 2}" width="${Math.max(2, x(cl(gr)) - x(cl(gl)))}" height="${lanes * laneH + 4}" fill="rgba(255,92,92,.10)" stroke="#ff5c5c" stroke-dasharray="${guardHz ? '4 3' : '0'}"/>`;
    for (const a of items) {
      if (a.lane < 0) continue;
      const hit = a.r > gl && a.l < gr;
      const op = Math.max(0.3, 1 - (a.dist_km / v.radius_km) * 0.7).toFixed(2);
      s += `<rect x="${x(cl(a.l))}" y="${top + a.lane * laneH}" width="${Math.max(1.5, x(cl(a.r)) - x(cl(a.l)))}" height="${laneH - 2}" fill="${wtrColour(a.meta?.product)}" fill-opacity="${op}" stroke="${hit ? '#ff5c5c' : 'none'}"><title>${esc(a.name)} · ${esc(a.meta?.product || '')} · ${mhz(a.freq_hz)} MHz · ${khz(a.bw_hz)} kHz · ${a.dist_km} km</title></rect>`;
    }
    for (const o of v.planned_others) {
      s += `<rect x="${x(cl(o.freq_hz - o.bw_hz / 2))}" y="${top - 2}" width="${Math.max(2, x(cl(o.freq_hz + o.bw_hz / 2)) - x(cl(o.freq_hz - o.bw_hz / 2)))}" height="${lanes * laneH + 4}" fill="rgba(243,178,62,.15)" stroke="#f3b23e"><title>planned: ${esc(o.name)} ${mhz(o.freq_hz)} MHz, ${o.dist_km} km</title></rect>`;
    }
    const y0 = top + lanes * laneH + 6;
    s += `<line x1="${padL}" x2="${W - padR}" y1="${y0}" y2="${y0}" stroke="#445"/>`;
    for (let i = 0; i <= 4; i++) { const f = lo + (i / 4) * (hi - lo); s += `<line x1="${x(f)}" x2="${x(f)}" y1="${y0}" y2="${y0 + 4}" stroke="#667"/><text x="${x(f)}" y="${y0 + 16}" fill="#8593a6" text-anchor="${i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}">${mhz(f)}</text>`; }
    s += `<text x="${W - padR}" y="${y0 + 28}" fill="#5d6b7d" text-anchor="end">MHz · ±${khz(span)} kHz · licences within ${v.radius_km} km, fainter = further${hidden ? ` · ${hidden} not drawn` : ''}</text></svg>`;
    return s;
  }
  async function openSpectrum(selId) {
    if (selId) specSel = selId;
    let st, res;
    try {
      [st, res] = await Promise.all([api('/api/spectrum/status'), fetchConflicts()]);
      if (!bandplan) bandplan = await api('/api/spectrum/bandplan');
    } catch (e) { return openModal('Spectrum', `<p class="bad">${esc(e.message)}</p>`); }
    if (specSel && !res.planned.some((p) => p.id === specSel)) specSel = null;
    if (!specSel && res.planned.length) specSel = res.planned[0].id;
    const src = st.source || {};
    const head = st.loaded
      ? `<p class="dim">Baseline: <b>${st.loaded.toLocaleString('en-GB')}</b> Ofcom WTR assignments, source dated ${esc(src.last_modified || '?')}, loaded ${st.updated ? ago(st.updated) + ' ago' : '?'}. Licensed assignments only, not measured on-air use. Band plan is simplified; UKFAT is authoritative.</p>`
      : `<p class="warn">Ofcom baseline not loaded yet. It downloads on first run (about 52 MB); check Health for the <b>wtr</b> collector.</p>`;
    const settingsRow = `<div class="specset">Guard <input id="sp-guard" type="number" step="any" min="0" value="${SPEC.guard_khz}"> kHz · Radius <input id="sp-rad" type="number" step="any" min="1" value="${SPEC.radius_km}"> km · Display ±<input id="sp-span" type="number" step="any" min="1" value="${SPEC.span_khz}"> kHz · Harmonics to <input id="sp-harm" type="number" min="0" max="5" step="1" value="${SPEC.harm_order ?? 3}"> · Co-site IM3 <input id="sp-cosite" type="number" step="any" min="0" value="${SPEC.cosite_km ?? 1}"> km <button id="sp-recheck">Recheck</button></div>`;
    const tot = res.totals;
    const list = res.planned.length ? `<table class="grid"><tr><th>Emitter</th><th>MHz</th><th>BW kHz</th><th>Window (Z)</th><th>Conflicts</th><th></th></tr>${res.planned.map((p) => {
      const c = { high: 0, medium: 0, low: 0 }; p.conflicts.forEach((x) => { c[x.severity] += 1; });
      return `<tr class="${p.id === specSel ? 'sel' : ''}"><td><a href="#" data-sel="${esc(p.id)}">${esc(p.name)}</a></td><td class="mono">${mhz(p.freq_hz)}</td><td class="mono">${khz(p.bw_hz)}</td><td class="mono dim">${p.start ? fmtZ(p.start) : 'open'} → ${p.end ? fmtZ(p.end) : 'open'}</td><td><span style="color:#ff5c5c">${c.high}H</span> <span style="color:#f3b23e">${c.medium}M ${c.low}L</span></td><td style="white-space:nowrap"><button data-edit="${esc(p.id)}">Edit</button> <button data-del="${esc(p.id)}">Delete</button></td></tr>`;
    }).join('')}</table><p class="dim">Totals: ${tot.vs_licensed} against licences, ${tot.planned_pairs} planned/planned pairs, ${tot.harmonic} harmonic and ${tot.im3} IM3 product hits; ${tot.high} high, ${tot.medium} medium, ${tot.low} low. Harmonic and IM3 results are screening only: power and filtering are not modelled.</p>` : '<p class="dim">No planned emitters yet. Add one below.</p>';
    const sel = res.planned.find((p) => p.id === specSel);
    openModal('Spectrum deconfliction', `${head}<p><a href="/api/export/plan.docx" class="btnlink" download>Export plan (Word)</a> <span class="dim">planned emitters, conflicts, links and coverage in one document</span></p>${settingsRow}<h3 class="sec">Planned emitters</h3>${list}
      <h3 class="sec">${draft?.id ? 'Edit' : 'Add'} planned emitter</h3>${specForm(draft)}
      ${sel ? `<h3 class="sec">Spectral view: ${esc(sel.name)}</h3><div id="sp-svg" class="dim">Loading…</div><h3 class="sec">Conflicts: ${esc(sel.name)}</h3>${conflictRows(sel.conflicts, 30)}` : ''}
      ${res.planned.length ? `<h3 class="sec">Deconfliction note (Ollama)</h3><p><button id="sp-brief" class="primary">Generate note</button> <span class="dim">Narrates the computed results above; takes 1–3 min on CPU.</span></p><div id="sp-brief-out" class="md"></div>` : ''}`);
    wireSpectrum();
    if (sel) {
      try { const v = await api(`/api/spectrum/view/${encodeURIComponent(sel.id)}?span_khz=${SPEC.span_khz}&radius_km=${SPEC.radius_km}`); $('#sp-svg').outerHTML = spectralSvg(v, SPEC.guard_khz * 1e3); }
      catch (e) { $('#sp-svg').textContent = e.message; }
    }
  }
  function wireSpectrum() {
    const body = $('#modal-body');
    body.querySelectorAll('a[data-sel]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); openSpectrum(a.dataset.sel); }));
    body.querySelectorAll('button[data-edit]').forEach((b) => b.addEventListener('click', async () => {
      const { planned } = await api('/api/spectrum/planned');
      draft = planned.find((p) => p.id === b.dataset.edit) || null; openSpectrum(b.dataset.edit);
    }));
    body.querySelectorAll('button[data-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this planned emitter?')) return;
      await api(`/api/spectrum/planned/${encodeURIComponent(b.dataset.del)}`, { method: 'DELETE' });
      if (draft?.id === b.dataset.del) draft = null;
      if (specSel === b.dataset.del) specSel = null;
      await openSpectrum(); loadPlanned().catch(() => {});
    }));
    $('#sp-recheck')?.addEventListener('click', () => {
      SPEC.guard_khz = Math.max(0, Number($('#sp-guard').value) || 0);
      SPEC.radius_km = Math.max(1, Number($('#sp-rad').value) || 50);
      SPEC.span_khz = Math.max(1, Number($('#sp-span').value) || 200);
      SPEC.harm_order = Math.min(5, Math.max(0, Math.round(Number($('#sp-harm').value) || 0)));
      SPEC.cosite_km = Math.max(0, Number($('#sp-cosite').value) || 0);
      saveSpec(); draft = formToDraft(readForm()); openSpectrum(); loadPlanned().catch(() => {});
    });
    $('#sp-clear')?.addEventListener('click', () => { draft = null; openSpectrum(); });
    $('#sp-pick')?.addEventListener('click', () => {
      draft = formToDraft(readForm());
      $('#modal').classList.remove('show');
      showSide(false); if (mobile()) showRail(false);
      map.getContainer().style.cursor = 'crosshair';
      map.once('click', (e) => {
        map.getContainer().style.cursor = '';
        draft = { ...draft, lat: +e.latlng.lat.toFixed(5), lon: +e.latlng.lng.toFixed(5) };
        openSpectrum();
      });
    });
    $('#sp-save')?.addEventListener('click', async () => {
      const f = readForm();
      const err = !f.name ? 'Name required' : f.freq_mhz == null ? 'Frequency required' : f.lat == null || f.lon == null ? 'Position required (or Pick on map)' : '';
      if (err) { $('#sp-err').textContent = err; return; }
      const { id, ...bodyData } = f;
      try {
        const r = await api(id ? `/api/spectrum/planned/${encodeURIComponent(id)}` : '/api/spectrum/planned',
          { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bodyData) });
        draft = null; specSel = r.id;
        await openSpectrum(); loadPlanned().catch(() => {});
      } catch (e) { $('#sp-err').textContent = e.message; }
    });
    $('#sp-brief')?.addEventListener('click', async () => {
      const btn = $('#sp-brief'); btn.disabled = true; btn.textContent = 'Generating…';
      try {
        const r = await api('/api/spectrum/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ guard_khz: SPEC.guard_khz, radius_km: SPEC.radius_km, harm_order: SPEC.harm_order ?? 3, cosite_km: SPEC.cosite_km ?? 1 }) });
        $('#sp-brief-out').innerHTML = renderMd(r.content) + `<p class="dim">${esc(r.model || '')} · ${r.duration_s ?? ''} s · narrates computed results only; check against the table above.</p>`;
      } catch (e) { $('#sp-brief-out').innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
      finally { btn.disabled = false; btn.textContent = 'Regenerate note'; }
    });
  }
  $('#btn-spec').addEventListener('click', () => openSpectrum());
  // ---------------------------------------------------------------- link planner (P2P)
  let linkDraft = null, linkPresets = null, linkRes = null, linkEditId = null;
  const VERDICT_COL = { go: '#45d38a', marginal: '#f3b23e', 'no-go': '#ff5c5c' };
  const LINK_FIELDS = [
    ['name', 'Link name', 'text'], ['a_name', 'Site A', 'text'], ['a_lat', 'A lat', 'number'], ['a_lon', 'A lon', 'number'], ['a_h', 'A mast m AGL', 'number'],
    ['b_name', 'Site B', 'text'], ['b_lat', 'B lat', 'number'], ['b_lon', 'B lon', 'number'], ['b_h', 'B mast m AGL', 'number'],
    ['freq_mhz', 'Freq MHz', 'number'], ['rtn_freq_mhz', 'Return MHz (FDD)', 'number'], ['bw_khz', 'BW kHz', 'number'],
    ['ptx_dbm', 'Tx dBm', 'number'], ['gtx_dbi', 'Ant gain A dBi', 'number'], ['grx_dbi', 'Ant gain B dBi', 'number'],
    ['ltx_db', 'Feeder loss A dB', 'number'], ['lrx_db', 'Feeder loss B dB', 'number'], ['sens_dbm', 'Rx sens dBm', 'number'],
    ['req_margin_db', 'Req margin dB', 'number'], ['rain_mm_h', 'Rain R0.01 mm/h', 'number'], ['avail_target', 'Avail target %', 'number'],
    ['pol', 'Pol H/V', 'text'], ['k', 'k-factor', 'number'], ['start_at', 'Start (Z)', 'datetime-local'], ['end_at', 'End (Z)', 'datetime-local'],
  ];
  function linkForm(d) {
    d = d || {};
    const val = (k, t) => t === 'datetime-local' ? toLocalInput(d[k]) : esc(d[k] ?? '');
    return `<div class="specform">${LINK_FIELDS.map(([k, lbl, t]) => `<label${k === 'name' ? ' class="wide"' : ''}>${esc(lbl)}<input id="lk-${k}" type="${t}" step="any" value="${val(k, t)}"></label>`).join('')}
      <div class="wide btns"><select id="lk-preset"><option value="">Band preset…</option>${(linkPresets?.presets || []).map((p) => `<option value="${p.id}">${esc(p.label)}</option>`).join('')}</select>
      <button id="lk-pick-a">Pick A on map</button> <button id="lk-pick-b">Pick B on map</button>
      <button id="lk-analyse" class="primary">Analyse</button> <button id="lk-save">${linkEditId ? 'Update' : 'Save'} link</button> <button id="lk-clear">Clear</button> <span id="lk-err" class="bad"></span></div>
      <p class="dim wide">Presets are typical values only: replace with your equipment data. Rain R0.01 of about 25 mm/h is typical for southern England (ITU-R P.837 gives local values).</p></div>`;
  }
  function readLink() {
    const o = {};
    for (const [k, , t] of LINK_FIELDS) {
      const v = $(`#lk-${k}`).value.trim();
      if (t === 'number') o[k] = v === '' ? null : Number(v);
      else if (t === 'datetime-local') o[k] = v ? `${v}:00Z` : null;
      else o[k] = v || null;
    }
    return o;
  }
  function linkBody(o) {
    const b = {}; for (const [k, v] of Object.entries(o)) if (v !== null && v !== undefined) b[k] = v;
    return b;
  }
  async function postJson(path, body, method = 'POST') {
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join('; ') : `HTTP ${r.status}`);
    return j;
  }
  function profileSvg(r) {
    const P = r.profile, W = 900, H = 260, pl = 46, pr = 10, pt = 10, pb = 26;
    const D = r.distance_m;
    const lowF1 = P.los.map((l, i) => l - P.f1[i]), low60 = P.los.map((l, i) => l - 0.6 * P.f1[i]);
    const ymin = Math.min(...P.terrain, ...lowF1) - 10, ymax = Math.max(...P.bulged, ...P.los, r.ha_asl, r.hb_asl) + 15;
    const x = (d) => pl + (d / D) * (W - pl - pr), y = (h) => pt + (1 - (h - ymin) / (ymax - ymin)) * (H - pt - pb);
    const path = (arr) => arr.map((h, i) => `${i ? 'L' : 'M'}${x(P.dist[i]).toFixed(1)},${y(h).toFixed(1)}`).join('');
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="background:#0a0e13;border:1px solid var(--border);border-radius:6px;font:10px var(--font)">`;
    s += `<path d="${path(P.bulged)}L${x(D)},${y(ymin)}L${x(0)},${y(ymin)}Z" fill="#3a3222" stroke="#8a6d3b" stroke-width="1"><title>terrain incl. earth bulge (k=${r.k.toFixed(2)})</title></path>`;
    s += `<path d="${path(P.terrain)}" fill="none" stroke="#5d6b7d" stroke-width=".7" stroke-dasharray="2 2"><title>terrain, flat earth</title></path>`;
    s += `<path d="${path(lowF1)}" fill="none" stroke="#3cc7ff" stroke-opacity=".35"><title>first Fresnel zone lower edge</title></path>`;
    s += `<path d="${path(low60)}" fill="none" stroke="#3cc7ff" stroke-dasharray="4 3"><title>60% first Fresnel zone</title></path>`;
    s += `<path d="${path(P.los)}" fill="none" stroke="${VERDICT_COL[r.verdict]}" stroke-width="1.6"><title>line of sight</title></path>`;
    for (const e of r.edges || []) s += `<circle cx="${x(e.dist_m)}" cy="${y(P.bulged[e.i])}" r="4" fill="none" stroke="#ff5c5c"><title>diffraction edge ${(e.dist_m / 1000).toFixed(2)} km, v=${e.v}, ${e.loss_db} dB</title></circle>`;
    for (let i = 0; i <= 4; i++) { const h = ymin + (i / 4) * (ymax - ymin); s += `<text x="${pl - 4}" y="${y(h) + 3}" fill="#8593a6" text-anchor="end">${Math.round(h)}</text>`; }
    for (let i = 0; i <= 5; i++) { const d = (i / 5) * D; s += `<text x="${x(d)}" y="${H - 8}" fill="#8593a6" text-anchor="${i === 0 ? 'start' : i === 5 ? 'end' : 'middle'}">${(d / 1000).toFixed(1)} km</text>`; }
    s += `<text x="${pl + 4}" y="${pt + 10}" fill="#5d6b7d">m ASL · solid = line of sight · dashed blue = 60% F1 · red circles = diffraction edges</text></svg>`;
    return s;
  }
  function budgetTable(r) {
    const rows = [['Distance', `${(r.distance_m / 1000).toFixed(2)} km`], ['Bearings', `A→B ${r.bearing_ab_deg}° · B→A ${r.bearing_ba_deg}°`],
      ['EIRP', `${r.eirp_dbm} dBm`], ['Free-space loss', `${r.fspl_db} dB`], ['Diffraction', `${r.diffraction_db} dB`], ['Gases', `${r.gas_db} dB`],
      ['Received level', `${r.prx_dbm} dBm`], ['Fade margin', `<b>${r.margin_db} dB</b> (sensitivity ${r.sens_dbm} dBm)`],
      ['Min F1 clearance', r.min_f1_clearance == null ? '' : `${Math.round(r.min_f1_clearance * 100)}% at ${(r.worst_point_m / 1000).toFixed(2)} km`],
      ['Rain A0.01', r.rain_a001_db ? `${r.rain_a001_db} dB at ${r.rain_mm_h} mm/h, pol ${r.pol}` : 'negligible'],
      ['Rain availability', r.availability_pct == null ? 'n/a' : `${r.availability_pct}% (target ${r.avail_target_pct}%)`]];
    return `<p><b style="color:${VERDICT_COL[r.verdict]};text-transform:uppercase">${esc(r.verdict)}</b>${r.issues.length ? ' · ' + r.issues.map(esc).join('; ') : ''}</p>${kv(rows)}<p class="dim">${esc(r.assumptions || '')}</p>`;
  }
  async function openLinks(editId) {
    if (editId !== undefined) linkEditId = editId;
    try { if (!linkPresets) linkPresets = await api('/api/links/presets'); } catch (e) { return openModal('Link planner', `<p class="bad">${esc(e.message)}</p>`); }
    const { links } = await api('/api/links');
    if (linkEditId && !linkDraft) {
      const row = links.find((l) => l.id === linkEditId);
      if (row) linkDraft = { ...row, freq_mhz: row.freq_hz / 1e6, rtn_freq_mhz: row.rtn_freq_hz ? row.rtn_freq_hz / 1e6 : null, bw_khz: row.bw_hz / 1e3 };
    }
    const d = linkDraft || { a_h: 15, b_h: 15, pol: 'V', k: +(4 / 3).toFixed(3), rain_mm_h: 25, ltx_db: 0, lrx_db: 0 };
    const list = links.length ? `<table class="grid"><tr><th>Link</th><th>MHz</th><th>km</th><th>Margin</th><th>Verdict</th><th></th></tr>${links.map((l) => `<tr class="${l.id === linkEditId ? 'sel' : ''}"><td>${esc(l.name)}</td><td class="mono">${mhz(l.freq_hz)}${l.rtn_freq_hz ? ' / ' + mhz(l.rtn_freq_hz) : ''}</td><td class="mono">${l.last_distance_m ? (l.last_distance_m / 1000).toFixed(1) : ''}</td><td class="mono">${l.last_margin_db ?? ''} dB</td><td style="color:${VERDICT_COL[l.last_verdict] || '#8593a6'}">${esc(l.last_verdict || '')}</td><td style="white-space:nowrap"><button data-lk-edit="${esc(l.id)}">Open</button> <button data-lk-del="${esc(l.id)}">Delete</button></td></tr>`).join('')}</table>` : '<p class="dim">No saved links yet.</p>';
    const dm = linkPresets.dem || {};
    openModal('Link planner (point-to-point)', `<p class="dim">Terrain: Copernicus 30 m, ${dm.tiles_cached ?? 0} tiles cached (${dm.cache_mb ?? 0} MB); new areas download on first use. Saved links create planned emitters at both ends for spectrum deconfliction.</p>
      <h3 class="sec">Saved links</h3>${list}<h3 class="sec">${linkEditId ? 'Edit link' : 'New link'}</h3>${linkForm(d)}<div id="lk-out">${linkRes ? profileSvg(linkRes) + budgetTable(linkRes) : ''}</div>`);
    wireLinks();
  }
  function wireLinks() {
    const body = $('#modal-body');
    body.querySelectorAll('button[data-lk-edit]').forEach((b) => b.addEventListener('click', async () => {
      linkDraft = null; linkEditId = b.dataset.lkEdit; linkRes = null;
      try { linkRes = (await api(`/api/links/${encodeURIComponent(linkEditId)}/analysis`)).analysis; } catch (e) { console.warn(e); }
      openLinks(); drawLinkResult();
    }));
    body.querySelectorAll('button[data-lk-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this link and its planned emitters?')) return;
      await fetch(`/api/links/${encodeURIComponent(b.dataset.lkDel)}`, { method: 'DELETE' });
      if (linkEditId === b.dataset.lkDel) { linkEditId = null; linkDraft = null; linkRes = null; }
      openLinks(); loadLinks().catch(() => {}); loadPlanned().catch(() => {});
    }));
    $('#lk-preset').addEventListener('change', (e) => {
      const p = (linkPresets.presets || []).find((x) => x.id === e.target.value); if (!p) return;
      linkDraft = { ...readLink(), ...Object.fromEntries(Object.entries(p).filter(([k]) => !['id', 'label'].includes(k))) };
      openLinks();
    });
    const pick = (end) => () => {
      linkDraft = readLink();
      $('#modal').classList.remove('show'); showSide(false); if (mobile()) showRail(false);
      map.getContainer().style.cursor = 'crosshair';
      map.once('click', (e) => {
        map.getContainer().style.cursor = '';
        linkDraft = { ...linkDraft, [`${end}_lat`]: +e.latlng.lat.toFixed(5), [`${end}_lon`]: +e.latlng.lng.toFixed(5) };
        openLinks();
      });
    };
    $('#lk-pick-a').addEventListener('click', pick('a'));
    $('#lk-pick-b').addEventListener('click', pick('b'));
    $('#lk-clear').addEventListener('click', () => { linkDraft = null; linkEditId = null; linkRes = null; openLinks(); });
    $('#lk-analyse').addEventListener('click', async () => {
      const btn = $('#lk-analyse'); btn.disabled = true; btn.textContent = 'Analysing…'; $('#lk-err').textContent = '';
      linkDraft = readLink();
      try { linkRes = await postJson('/api/links/analyse', linkBody(linkDraft)); $('#lk-out').innerHTML = profileSvg(linkRes) + budgetTable(linkRes); drawLinkResult(); }
      catch (e) { $('#lk-err').textContent = e.message; }
      finally { btn.disabled = false; btn.textContent = 'Analyse'; }
    });
    $('#lk-save').addEventListener('click', async () => {
      $('#lk-err').textContent = '';
      linkDraft = readLink();
      try {
        const r = await postJson(linkEditId ? `/api/links/${encodeURIComponent(linkEditId)}` : '/api/links', linkBody(linkDraft), linkEditId ? 'PUT' : 'POST');
        linkEditId = r.link.id; linkRes = r.analysis; linkDraft = null;
        await openLinks(); drawLinkResult(); loadLinks().catch(() => {}); loadPlanned().catch(() => {});
      } catch (e) { $('#lk-err').textContent = e.message; }
    });
  }
  const linkPreview = L.layerGroup().addTo(map);
  function drawLinkResult() {
    linkPreview.clearLayers();
    if (!linkRes?.points) return;
    L.polyline(linkRes.points, { color: VERDICT_COL[linkRes.verdict], weight: 3, dashArray: '6 6', interactive: false }).addTo(linkPreview);
  }
  async function loadLinks() {
    const g = groups.links;
    const { links } = await api('/api/links');
    g.clearLayers();
    for (const l of links) {
      const col = VERDICT_COL[l.last_verdict] || '#8593a6';
      L.polyline([[l.a_lat, l.a_lon], [l.b_lat, l.b_lon]], { color: col, weight: 3, opacity: 0.9 })
        .bindPopup(`<h4>${esc(l.name)}</h4>${kv([['Freq', `${mhz(l.freq_hz)} MHz${l.rtn_freq_hz ? ' / ' + mhz(l.rtn_freq_hz) : ''}`], ['Distance', l.last_distance_m ? `${(l.last_distance_m / 1000).toFixed(2)} km` : ''], ['Margin', `${l.last_margin_db} dB`], ['Verdict', `<span style="color:${col}">${esc(l.last_verdict || '')}</span>`]])}<p style="margin:6px 0 0"><a href="#" class="lk-open" data-id="${esc(l.id)}">Open in Link planner ›</a></p>`).addTo(g);
      for (const [la, lo, nm] of [[l.a_lat, l.a_lon, l.a_name || 'A'], [l.b_lat, l.b_lon, l.b_name || 'B']])
        L.circleMarker([la, lo], { radius: 5, color: '#fff', weight: 1, fillColor: col, fillOpacity: 1 }).bindTooltip(`${esc(l.name)}: ${esc(nm)}`).addTo(g);
    }
    setCount('links', links.length || ''); done('links');
  }
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelectorAll('a.lk-open').forEach((a) => a.addEventListener('click', async (ev) => {
      ev.preventDefault(); map.closePopup(); linkDraft = null; linkEditId = a.dataset.id;
      try { linkRes = (await api(`/api/links/${encodeURIComponent(linkEditId)}/analysis`)).analysis; } catch { linkRes = null; }
      openLinks(); drawLinkResult();
    }));
  });
  $('#btn-links').addEventListener('click', () => openLinks());
  // ---------------------------------------------------------------- coverage (omni / sector / P2MP hub)
  let covDraft = null, covRes = null, covEditId = null;
  const covPreview = L.layerGroup().addTo(map);
  const COV_PRESETS = [
    { id: 'vhf', label: 'VHF 150 MHz omni base, 25 W, 25 kHz', freq_mhz: 150, bw_khz: 25, ptx_dbm: 44, gtx_dbi: 3, ltx_db: 2, pattern: 'omni', sens_dbm: -110, margin_db: 10, rx_h_agl: 1.5, grx_dbi: 0, radius_km: 30 },
    { id: 'uhf', label: 'UHF 450 MHz omni base, 25 W, 12.5 kHz', freq_mhz: 450, bw_khz: 12.5, ptx_dbm: 44, gtx_dbi: 5, ltx_db: 2, pattern: 'omni', sens_dbm: -112, margin_db: 10, rx_h_agl: 1.5, grx_dbi: 0, radius_km: 25 },
    { id: 'uhfsec', label: 'UHF 450 MHz 65° sector, 25 W', freq_mhz: 450, bw_khz: 12.5, ptx_dbm: 44, gtx_dbi: 13, ltx_db: 2, pattern: 'sector', azimuth: 0, beamwidth: 65, sens_dbm: -112, margin_db: 10, rx_h_agl: 1.5, grx_dbi: 0, radius_km: 30 },
    { id: 'p2mp', label: 'SHF 5.8 GHz P2MP 90° sector hub, 20 MHz', freq_mhz: 5800, bw_khz: 20000, ptx_dbm: 27, gtx_dbi: 17, ltx_db: 0.5, pattern: 'sector', azimuth: 0, beamwidth: 90, sens_dbm: -80, margin_db: 10, rx_h_agl: 6, grx_dbi: 23, radius_km: 15 },
  ];
  const COV_FIELDS = [['name', 'Site name', 'text'], ['lat', 'Lat', 'number'], ['lon', 'Lon', 'number'], ['h_agl', 'Mast m AGL', 'number'],
    ['freq_mhz', 'Freq MHz', 'number'], ['bw_khz', 'BW kHz', 'number'], ['ptx_dbm', 'Tx dBm', 'number'], ['gtx_dbi', 'Ant gain dBi', 'number'],
    ['ltx_db', 'Feeder loss dB', 'number'], ['pattern', 'Pattern omni/sector', 'text'], ['azimuth', 'Sector azimuth °', 'number'], ['beamwidth', 'Beamwidth °', 'number'],
    ['radius_km', 'Radius km (≤100)', 'number'], ['rx_h_agl', 'Rx height m', 'number'], ['grx_dbi', 'Rx gain dBi', 'number'], ['sens_dbm', 'Rx sens dBm', 'number'],
    ['margin_db', 'Req margin dB', 'number'], ['itf_dbm', 'Interference thr dBm', 'number'], ['fine', 'Fine sampling (1 = on, ~3x slower)', 'number'], ['start_at', 'Start (Z)', 'datetime-local'], ['end_at', 'End (Z)', 'datetime-local']];
  function covForm(d) {
    const val = (k, t) => t === 'datetime-local' ? toLocalInput(d[k]) : esc(d[k] ?? '');
    return `<div class="specform">${COV_FIELDS.map(([k, lbl, t]) => `<label${k === 'name' ? ' class="wide"' : ''}>${esc(lbl)}<input id="cv-${k}" type="${t}" step="any" value="${val(k, t)}"></label>`).join('')}
      <div class="wide btns"><select id="cv-preset"><option value="">Preset…</option>${COV_PRESETS.map((p) => `<option value="${p.id}">${esc(p.label)}</option>`).join('')}</select>
      <button id="cv-pick">Pick site on map</button> <button id="cv-analyse" class="primary">Compute coverage</button> <button id="cv-save">${covEditId ? 'Update' : 'Save'} site</button> <button id="cv-clear">Clear</button> <span id="cv-err" class="bad"></span></div>
      <p class="dim wide">Presets are typical values only. Interference threshold is the level of your signal at a licensee that counts as a clash in deconfliction (default −120 dBm).</p></div>`;
  }
  function readCov() {
    const o = {};
    for (const [k, , t] of COV_FIELDS) {
      const v = $(`#cv-${k}`).value.trim();
      o[k] = t === 'number' ? (v === '' ? null : Number(v)) : t === 'datetime-local' ? (v ? `${v}:00Z` : null) : (v || null);
    }
    if (o.pattern) o.pattern = o.pattern.toLowerCase();
    o.fine = !!o.fine;
    return o;
  }
  function covStats(r) {
    const s = r.stats, b = r.bands;
    return `${kv([['Adequate coverage', `${s.area_km2} km² (≥ ${b.adequate_dbm} dBm), furthest ${s.max_range_km} km`], ['Marginal only', `${s.marginal_area_km2} km² (${b.marginal_dbm} to ${b.adequate_dbm} dBm)`],
      ['Interference footprint', `${s.interference_area_km2} km² above ${b.interference_dbm} dBm`], ['Site ground', `${s.site_ground_m} m ASL`], ['Resolution', `${s.step_m} m steps, 1° radials, ${s.compute_s} s`]])}<p class="dim">${esc(r.assumptions || '')}</p>`;
  }
  function showCovPreview(r) {
    covPreview.clearLayers();
    if (r?.overlay) { L.imageOverlay(r.overlay, r.bounds, { opacity: 1, interactive: false }).addTo(covPreview); map.fitBounds(r.bounds, { padding: [20, 20] }); }
  }
  async function openCoverage(editId) {
    if (editId !== undefined) covEditId = editId;
    const { sites } = await api('/api/coverage');
    if (covEditId && !covDraft) {
      const row = sites.find((s) => s.id === covEditId);
      if (row) covDraft = { ...row, freq_mhz: row.freq_hz / 1e6, bw_khz: row.bw_hz / 1e3 };
    }
    const d = covDraft || { h_agl: 15, pattern: 'omni', radius_km: 20, rx_h_agl: 1.5, grx_dbi: 0, ltx_db: 1, margin_db: 10, itf_dbm: -120, sens_dbm: -110 };
    const list = sites.length ? `<table class="grid"><tr><th>Site</th><th>MHz</th><th>Pattern</th><th>Adequate km²</th><th>Range km</th><th></th></tr>${sites.map((s) => `<tr class="${s.id === covEditId ? 'sel' : ''}"><td>${esc(s.name)}</td><td class="mono">${mhz(s.freq_hz)}</td><td>${esc(s.pattern)}${s.pattern === 'sector' ? ` ${s.azimuth ?? 0}°/${s.beamwidth ?? 65}°` : ''}</td><td class="mono">${s.stats?.area_km2 ?? ''}</td><td class="mono">${s.stats?.max_range_km ?? ''}</td><td style="white-space:nowrap"><button data-cv-edit="${esc(s.id)}">Open</button> <button data-cv-del="${esc(s.id)}">Delete</button></td></tr>`).join('')}</table>` : '<p class="dim">No saved sites yet.</p>';
    openModal('Coverage (omni, sector, P2MP hub)', `<p class="dim">Coverage on Copernicus 30 m terrain. Saved sites create a planned emitter, and deconfliction then uses this predicted coverage instead of the fixed radius.</p>
      <h3 class="sec">Saved sites</h3>${list}<h3 class="sec">${covEditId ? 'Edit site' : 'New site'}</h3>${covForm(d)}<div id="cv-out">${covRes ? covStats(covRes) : ''}</div>`);
    wireCoverage();
  }
  function wireCoverage() {
    const body = $('#modal-body');
    body.querySelectorAll('button[data-cv-edit]').forEach((b) => b.addEventListener('click', async () => {
      covDraft = null; covEditId = b.dataset.cvEdit; covRes = null;
      try { const o = await api(`/api/coverage/${encodeURIComponent(covEditId)}/overlay`); covRes = { ...o, stats: o.site.stats, bands: { adequate_dbm: o.site.sens_dbm + o.site.margin_db, marginal_dbm: o.site.sens_dbm, interference_dbm: o.site.itf_dbm } }; } catch (e) { console.warn(e); }
      openCoverage();
    }));
    body.querySelectorAll('button[data-cv-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this site and its planned emitter?')) return;
      await fetch(`/api/coverage/${encodeURIComponent(b.dataset.cvDel)}`, { method: 'DELETE' });
      if (covEditId === b.dataset.cvDel) { covEditId = null; covDraft = null; covRes = null; covPreview.clearLayers(); }
      openCoverage(); loadCoverage().catch(() => {}); loadPlanned().catch(() => {});
    }));
    $('#cv-preset').addEventListener('change', (e) => {
      const p = COV_PRESETS.find((x) => x.id === e.target.value); if (!p) return;
      const { id, label, ...vals } = p; covDraft = { ...readCov(), ...vals }; openCoverage();
    });
    $('#cv-pick').addEventListener('click', () => {
      covDraft = readCov();
      $('#modal').classList.remove('show'); showSide(false); if (mobile()) showRail(false);
      map.getContainer().style.cursor = 'crosshair';
      map.once('click', (e) => { map.getContainer().style.cursor = ''; covDraft = { ...covDraft, lat: +e.latlng.lat.toFixed(5), lon: +e.latlng.lng.toFixed(5) }; openCoverage(); });
    });
    $('#cv-clear').addEventListener('click', () => { covDraft = null; covEditId = null; covRes = null; covPreview.clearLayers(); openCoverage(); });
    $('#cv-analyse').addEventListener('click', async () => {
      const btn = $('#cv-analyse'); btn.disabled = true; btn.textContent = 'Computing…'; $('#cv-err').textContent = '';
      covDraft = readCov();
      try { covRes = await postJson('/api/coverage/analyse', linkBody(covDraft)); $('#cv-out').innerHTML = covStats(covRes); showCovPreview(covRes); }
      catch (e) { $('#cv-err').textContent = e.message; }
      finally { btn.disabled = false; btn.textContent = 'Compute coverage'; }
    });
    $('#cv-save').addEventListener('click', async () => {
      const btn = $('#cv-save'); btn.disabled = true; $('#cv-err').textContent = '';
      covDraft = readCov();
      try {
        const r = await postJson(covEditId ? `/api/coverage/${encodeURIComponent(covEditId)}` : '/api/coverage', linkBody(covDraft), covEditId ? 'PUT' : 'POST');
        covEditId = r.site.id; covRes = r; covDraft = null; covPreview.clearLayers();
        await openCoverage(); loadCoverage().catch(() => {}); loadPlanned().catch(() => {});
      } catch (e) { $('#cv-err').textContent = e.message; btn.disabled = false; }
    });
  }
  async function loadCoverage() {
    const g = groups.coverage;
    const { sites } = await api('/api/coverage');
    g.clearLayers();
    for (const s of sites) {
      try {
        const o = await api(`/api/coverage/${encodeURIComponent(s.id)}/overlay`);
        L.imageOverlay(o.overlay, o.bounds, { opacity: 1, interactive: false }).addTo(g);
      } catch (e) { console.warn('coverage', s.id, e); }
      L.circleMarker([s.lat, s.lon], { radius: 6, color: '#fff', weight: 1.5, fillColor: '#2bb9a8', fillOpacity: 1 })
        .bindPopup(`<h4>${esc(s.name)}</h4>${kv([['Freq', `${mhz(s.freq_hz)} MHz`], ['Pattern', `${esc(s.pattern)}${s.pattern === 'sector' ? ` ${s.azimuth ?? 0}° / ${s.beamwidth ?? 65}°` : ''}`], ['Adequate', `${s.stats?.area_km2 ?? '?'} km², to ${s.stats?.max_range_km ?? '?'} km`]])}<p style="margin:6px 0 0"><a href="#" class="cv-open" data-id="${esc(s.id)}">Open in Coverage ›</a></p>`).addTo(g);
    }
    setCount('coverage', sites.length || ''); done('coverage');
  }
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelectorAll('a.cv-open').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); map.closePopup(); covDraft = null; covRes = null; openCoverage(a.dataset.id); }));
  });
  $('#btn-cov').addEventListener('click', () => openCoverage());
  // ---------------------------------------------------------------- omnibox: search + Ask AI (home screen)
  const omniOut = $('#omni-out'), omniBody = $('#omni-body'), omniIn = $('#omni-q');
  const omniMark = L.layerGroup().addTo(map);
  function omniShow(html) { omniBody.innerHTML = html; omniOut.classList.add('show'); }
  function omniHide() { omniOut.classList.remove('show'); }
  $('#omni-close').addEventListener('click', omniHide);
  function flyMark(lat, lon, label) {
    if (lat == null || lon == null) return;
    omniMark.clearLayers();
    L.circleMarker([lat, lon], { radius: 11, color: '#fff', weight: 2, fill: false }).addTo(omniMark);
    L.circleMarker([lat, lon], { radius: 5, color: '#3cc7ff', weight: 1, fillOpacity: 1 }).bindTooltip(esc(label || ''), { permanent: false }).addTo(omniMark);
    map.flyTo([lat, lon], Math.max(map.getZoom(), 10), { duration: 0.8 });
  }
  function omniRow(label, sub, attrs) { return `<div class="omni-row" ${attrs}><div>${label}</div>${sub ? `<div class="dim">${sub}</div>` : ''}</div>`; }
  async function omniSearch(q) {
    omniShow('<span class="spinner"></span> searching…');
    let r;
    try { r = await api(`/api/search?q=${encodeURIComponent(q)}&limit=12`); } catch (e) { return omniShow(`<p class="bad">${esc(e.message)}</p>`); }
    const R = r.results, parts = [];
    const sec = (title, rows) => rows.length ? `<h3 class="sec">${title} <span class="dim">${rows.length}</span></h3>${rows.join('')}` : '';
    parts.push(sec('UK allocation (UKFAT)', (R.ukfat || []).map((u) => `<div class="omni-row"><div><b>${esc(u.band)}</b> <span class="dim">UKFAT p.${u.page}</span></div>`
      + u.rows.map((r) => `<div class="dim">${esc(r.service)}${r.service_name ? ' · ' + esc(r.service_name) : ''} · ${esc(r.status)} · ${esc(r.footnotes)}</div>`).join('')
      + Object.entries(u.footnotes).map(([k, v]) => `<div style="margin-top:3px"><b>${esc(k)}</b> ${esc(v)}</div>`).join('') + '</div>')));
    parts.push(sec('Satellite downlinks (SatNOGS, ±50 kHz)', (R.sats || []).map((t) => omniRow(`${esc(String(t.sat))} <span class="dim">NORAD ${t.norad ?? '?'}</span>`,
      `${mhz(t.lo)} MHz ${esc(t.mode)} · ${esc(t.desc)}${t.offset_khz ? ` · ${t.offset_khz} kHz off` : ''}`, t.norad ? `data-act="sat" data-norad="${t.norad}" data-label="${esc(String(t.sat))}"` : ''))));
    parts.push(sec('Planned emitters', R.planned.map((p) => omniRow(esc(p.name), `${p.freq_mhz} MHz`, `data-act="spec" data-id="${esc(p.id)}"`))));
    parts.push(sec('Links', R.links.map((l) => omniRow(esc(l.name), `${l.freq_mhz} MHz · ${esc(l.last_verdict || '')}`, `data-act="link" data-id="${esc(l.id)}"`))));
    parts.push(sec('Coverage sites', R.sites.map((s) => omniRow(esc(s.name), `${s.freq_mhz} MHz`, `data-act="site" data-id="${esc(s.id)}"`))));
    parts.push(sec(r.freqs_mhz.length ? `Ofcom licences on ${r.freqs_mhz.join(', ')} MHz${R.place ? ` within ${R.place.radius_km} km of ${esc(R.place.name)}` : ' (UK-wide)'}` : 'Ofcom licences', R.licences.map((x) =>
      omniRow(`${esc(x.company || 'Licensee withheld')} <span class="dim">${esc(x.licence)}</span>`, `${x.freq_mhz} MHz · ${khz(x.bw_hz)} kHz · ${esc(x.product)}${x.dist_km != null ? ` · ${x.dist_km} km` : ''}`,
        `data-act="fly" data-lat="${x.lat ?? ''}" data-lon="${x.lon ?? ''}" data-label="${esc(x.company || x.licence)}"`))));
    parts.push(sec('Feed items (30 days)', R.items.map((it) => omniRow(`${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>` : esc(it.title)}`,
      `${esc(it.source || '')} · ${esc(it.domain || '')} · ${it.when ? ago(it.when) + ' ago' : ''}`,
      it.lat != null ? `data-act="fly" data-lat="${it.lat}" data-lon="${it.lon}" data-label="${esc(it.title.slice(0, 60))}"` : ''))));
    const html = parts.join('');
    omniShow((html || '<p class="dim">No matches.</p>') + `<p class="dim" style="margin-top:8px">Tip: press Ask AI to put this question to the model with all of the above as context.</p>`);
    omniBody.querySelectorAll('.omni-row[data-act]').forEach((el) => el.addEventListener('click', (e) => {
      if (e.target.closest('a')) return;
      const a = el.dataset.act, id = el.dataset.id;
      if (a === 'fly') { if (el.dataset.lat) flyMark(+el.dataset.lat, +el.dataset.lon, el.dataset.label); else omniShow(omniBody.innerHTML + '<p class="dim">Area licence: no published location.</p>'); }
      if (a === 'spec') { omniHide(); openSpectrum(id); }
      if (a === 'sat') {
        const c = map.getCenter();
        const box = document.createElement('div'); box.className = 'dim'; box.textContent = 'computing passes…'; el.appendChild(box);
        api(`/api/sat/passes?norad=${el.dataset.norad}&lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}&hours=24`).then((r) => {
          box.innerHTML = r.passes.length ? `Next passes over map centre (${c.lat.toFixed(2)}, ${c.lng.toFixed(2)}), ≥10° elevation:` + r.passes.slice(0, 6).map((q) => `<div class="mono">${fmtZ(q.start)} · ${q.duration_min} min · max ${q.max_el}° · az ${q.az_start}°→${q.az_end}°</div>`).join('') : 'No passes above 10° in the next 24 h.';
        }).catch((e) => { box.textContent = e.message; });
      }
      if (a === 'link') { omniHide(); linkDraft = null; linkRes = null; openLinks(id); }
      if (a === 'site') { omniHide(); covDraft = null; covRes = null; openCoverage(id); }
    }));
  }
  let omniAbort = null;
  async function omniAsk(q) {
    if (omniAbort) omniAbort.abort();
    omniAbort = new AbortController();
    omniShow(`<p><b>Q:</b> ${esc(q)}</p><div id="omni-ans" class="md"><span class="spinner"></span> thinking… (1–2 min on the box's CPU)</div><div id="omni-src"></div>`);
    const out = $('#omni-ans');
    let text = '', first = true, meta = null;
    try {
      const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, web: !!$('#omni-web')?.checked }), signal: omniAbort.signal });
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          const line = p.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          const d = JSON.parse(line.slice(6));
          if (d.meta) meta = d.meta;
          if (d.t) { if (first) { out.textContent = ''; first = false; } text += d.t; out.textContent = text; }
          if (d.error) out.innerHTML = `<p class="bad">Error: ${esc(d.error)}</p>`;
        }
      }
      if (text) out.innerHTML = renderMd(text);
      const srcs = (meta?.sources || []).filter((s) => new RegExp(`\\[${s.n}\\]`).test(text));
      const webs = (meta?.web || []).filter((w) => new RegExp(`\\[W${w.n}\\]`).test(text));
      $('#omni-src').innerHTML = (webs.length ? `<h3 class="sec">Web sources (unverified)</h3>${webs.map((w) => `<div>[W${w.n}] <a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.title)}</a></div>`).join('')}` : '') + (srcs.length ? `<h3 class="sec">Cited items</h3>${srcs.map((s) => `<div>[${s.n}] ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title)} <span class="dim">${esc(s.source || '')}</span></div>`).join('')}` : '')
        + `<p class="dim">Answer draws on CyEM status, the latest brief, ${meta?.items ?? 0} matching items${meta?.freqs_mhz?.length ? `, Ofcom licences on ${meta.freqs_mhz.join(', ')} MHz${meta.place ? ` within 30 km of ${esc(meta.place)}` : ' (UK-wide)'}` : ''} and your plan. Anything under "General knowledge" is the model's background, not CyEM data.</p>`;
    } catch (e) { if (e.name !== 'AbortError') out.innerHTML = `<p class="bad">Error: ${esc(e.message)}</p>`; }
  }
  $('#omni-form').addEventListener('submit', (e) => { e.preventDefault(); const q = omniIn.value.trim(); if (q.length >= 2) (q.startsWith('?') ? omniAsk(q.slice(1).trim()) : omniSearch(q)); });
  $('#omni-ask').addEventListener('click', () => { const q = omniIn.value.trim().replace(/^\?/, ''); if (q.length >= 2) omniAsk(q); });
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) { e.preventDefault(); omniIn.focus(); omniIn.select(); }
    if (e.key === 'Escape') omniHide();
  });
  // ---------------------------------------------------------------- AIS vessels + OpenCelliD cells
  const AIS_COL = { military: '#ff5c5c', law: '#ff6fb1', sar: '#f3b23e', tanker: '#c07b3a', cargo: '#3cc7ff', passenger: '#45d38a',
                    fishing: '#2bb9a8', service: '#b48cff', leisure: '#8fb3d9', other: '#8593a6', unknown: '#5d6b7d' };
  const AIS_NAME = { military: 'Military', law: 'Law enforcement', sar: 'Search and rescue', tanker: 'Tanker', cargo: 'Cargo', passenger: 'Passenger',
                     fishing: 'Fishing', service: 'Tug / pilot / service', leisure: 'Sailing / pleasure', other: 'Other', unknown: 'Type not yet received' };
  const aisCanvas = L.canvas({ padding: 0.3 });
  async function loadAis() {
    const g = groups.ais; g.clearLayers();
    const { data, updated } = await api('/api/layers/ais');
    if (!data) { setCount('ais', '–'); done('ais'); return; }
    const only = optOn('ais_gov');
    let n = 0;
    for (const v of data.vessels || []) {
      if (only && !['military', 'law', 'sar'].includes(v.cat)) continue;
      n++;
      const col = AIS_COL[v.cat] || '#8593a6', hi = ['military', 'law', 'sar'].includes(v.cat);
      L.circleMarker([v.lat, v.lon], { renderer: aisCanvas, radius: hi ? 5 : 3, color: hi ? '#fff' : col, weight: hi ? 1 : 0, fillColor: col, fillOpacity: 0.85 })
        .bindPopup(() => `<h4>${esc(v.name || 'MMSI ' + v.mmsi)}</h4>${kv([['Type', esc(AIS_NAME[v.cat] || v.cat) + (v.type != null ? ` (${v.type})` : '')], ['MMSI', `<span class="mono">${v.mmsi}</span>`], ['Call sign', esc(v.callsign || '')], ['Speed', v.sog != null ? `${v.sog} kn` : ''], ['Course', v.cog != null ? `${Math.round(v.cog)}°` : ''], ['Destination', esc(v.dest || '')], ['Class', v.cls], ['Last seen', fmtZ(v.seen)]])}<p class="dim" style="margin:4px 0 0">AIS via aisstream.io, sampled every 5 min · ${fmtZ(updated)}</p>`)
        .addTo(g);
    }
    setCount('ais', `${n}/${data.count}`); done('ais');
  }
  const CELL_COL = { GSM: '#8593a6', UMTS: '#3cc7ff', LTE: '#45d38a', NR: '#ff6fb1', CDMA: '#f3b23e' };
  let cellSeq = 0;
  async function loadCells() {
    const g = groups.cells; const seq = ++cellSeq;
    if (map.getZoom() < 11) { g.clearLayers(); setCount('cells', 'zoom in'); done('cells'); return; }
    const b = map.getBounds().pad(0.05);
    const res = await api(`/api/cells?s=${b.getSouth().toFixed(4)}&w=${b.getWest().toFixed(4)}&n=${b.getNorth().toFixed(4)}&e=${b.getEast().toFixed(4)}`);
    if (seq !== cellSeq) return;
    g.clearLayers();
    if (!res.loaded) { setCount('cells', 'not loaded'); done('cells'); return; }
    for (const c of res.rows) {
      L.circleMarker([c.lat, c.lon], { renderer: aisCanvas, radius: 3, weight: 0, fillColor: CELL_COL[c.radio] || '#c8d3e0', fillOpacity: 0.8 })
        .bindPopup(() => `<h4>${esc(c.operator)} ${esc(c.radio)}</h4>${kv([['Cell', `<span class="mono">${c.mcc}-${c.net}-${c.area}-${c.cell}</span>`], ['Est. range', c.range_m ? `${c.range_m} m` : ''], ['Samples', c.samples], ['Updated', c.updated ? new Date(c.updated * 1000).toISOString().slice(0, 10) : '']])}<p class="dim" style="margin:4px 0 0">OpenCelliD (CC BY-SA 4.0): crowd-sourced estimate of where the cell was heard, not a surveyed mast.</p>`)
        .addTo(g);
    }
    setCount('cells', res.total > res.returned ? `${res.returned}/${res.total}` : res.total); done('cells');
  }
  map.on('moveend', () => { if (map.hasLayer(groups.cells)) loadCells().catch((e) => console.warn('cells', e)); });
  // ---------------------------------------------------------------- all aircraft (ADS-B)
  async function loadAir() {
    const g = groups.air; g.clearLayers();
    const { data, updated } = await api('/api/layers/air');
    if (!data) { setCount('air', '–'); done('air'); return; }
    const only = optOn('air_flags');
    let n = 0;
    for (const a of data.aircraft || []) {
      if (only && !a.gnss_bad && !a.emerg) continue;
      n++;
      const col = a.emerg ? '#ff5c5c' : a.gnss_bad ? '#f3b23e' : a.mil ? '#ff6fb1' : '#8fb3d9';
      const big = a.emerg || a.gnss_bad;
      L.circleMarker([a.lat, a.lon], { renderer: aisCanvas, radius: big ? 4.5 : 2.5, color: big ? '#fff' : col, weight: big ? 1 : 0, fillColor: col, fillOpacity: 0.85 })
        .bindPopup(() => `<h4>${esc(a.flight || a.reg || a.hex)} <span class="muted">${esc(a.type || '')}</span></h4>${kv([['Status', a.emerg ? `<b style="color:#ff5c5c">Squawk ${a.squawk}: ${esc(a.emerg)}</b>` : a.gnss_bad ? '<b style="color:#f3b23e">Degraded position integrity</b>' : 'normal'], ['NIC / NACp', `${a.nic ?? '–'} / ${a.nacp ?? '–'}`], ['Altitude', a.ground ? 'on ground' : a.alt != null ? `${a.alt.toLocaleString()} ft` : ''], ['Ground speed', a.gs != null ? `${Math.round(a.gs)} kt` : ''], ['Track', a.track != null ? `${Math.round(a.track)}°` : ''], ['Squawk', esc(a.squawk || '')], ['Registration', esc(a.reg || '')], ['Hex', `<span class="mono">${esc(a.hex)}</span>`]])}<p style="margin:6px 0 0"><a href="https://globe.adsb.fi/?icao=${esc(a.hex)}" target="_blank" rel="noopener">Track on adsb.fi ↗</a></p><p class="dim" style="margin:4px 0 0">NIC 1 to 6 suggests degraded GNSS (jamming, spoofing or equipment). ${esc(data.source || '')} · ${fmtZ(updated)}</p>`)
        .addTo(g);
    }
    setCount('air', `${n}/${data.count} · ${data.degraded} GNSS`); done('air');
  }
  // ---------------------------------------------------------------- HF skywave now-cast
  let hfDraft = { freqs: '3.5, 5.3, 7.0, 10.1, 14.0, 18.1, 21.0, 24.9, 28.0' }, hfRes = null;
  const hfLayer = L.layerGroup().addTo(map);
  const HF_COL = { good: '#45d38a', marginal: '#f3b23e', 'above MUF': '#ff5c5c', absorbed: '#b48cff', 'no data': '#8593a6' };
  function hfForm() {
    const v = (k) => esc(hfDraft[k] ?? '');
    return `<div class="specform">
      <label>A lat<input id="hf-alat" type="number" step="any" value="${v('a_lat')}"></label><label>A lon<input id="hf-alon" type="number" step="any" value="${v('a_lon')}"></label>
      <label>B lat<input id="hf-blat" type="number" step="any" value="${v('b_lat')}"></label><label>B lon<input id="hf-blon" type="number" step="any" value="${v('b_lon')}"></label>
      <label class="wide">Frequencies MHz (comma separated)<input id="hf-f" value="${v('freqs')}"></label>
      <div class="wide btns"><button id="hf-pa">Pick A on map</button> <button id="hf-pb">Pick B on map</button> <button id="hf-go" class="primary">Plan path</button> <span id="hf-err" class="bad"></span></div></div>`;
  }
  function hfRead() {
    const n = (id) => { const x = $(id).value.trim(); return x === '' ? null : Number(x); };
    hfDraft = { a_lat: n('#hf-alat'), a_lon: n('#hf-alon'), b_lat: n('#hf-blat'), b_lon: n('#hf-blon'), freqs: $('#hf-f').value };
    return hfDraft;
  }
  function hfResult(r) {
    const f = r.frequencies.map((x) => `<span class="mono" style="display:inline-block;margin:2px 6px 2px 0;padding:2px 6px;border-radius:4px;border:1px solid ${HF_COL[x.status]};color:${HF_COL[x.status]}">${x.mhz} · ${esc(x.status)}</span>`).join('');
    const cps = `<table class="grid"><tr><th>Control point</th><th>foF2</th><th>MUF(3000)</th><th>hmF2</th><th>Hop MUF</th><th>D-RAP</th><th>Ionosondes (km, age h)</th></tr>${r.control_points.map((c) => `<tr><td class="mono">${c.lat}, ${c.lon}</td><td class="mono">${c.fof2 ?? '–'}</td><td class="mono">${c.mufd ?? '–'}</td><td class="mono">${c.hmf2}</td><td class="mono"><b>${c.muf ?? 'no data'}</b></td><td class="mono">${c.luf_sw ?? '–'}</td><td>${c.sources.map((s) => `${esc(s.name)} (${s.km}, ${s.age_h ?? '?'})`).join('; ') || '<span class="bad">none within 2,000 km</span>'}</td></tr>`).join('')}</table>`;
    return `${kv([['Path', `${r.distance_km.toLocaleString()} km · ${r.mode} · ${r.hops} hop${r.hops > 1 ? 's' : ''} of ${r.hop_km} km · take-off ${r.elev_deg}°`], ['MUF', r.muf != null ? `<b>${r.muf} MHz</b>` : '<span class="bad">not assessable (no ionosonde near a control point)</span>'], ['FOT (0.85 × MUF)', r.fot != null ? `${r.fot} MHz` : ''], ['Space-weather lower limit', r.luf_space_weather != null ? `${r.luf_space_weather} MHz (D-RAP)` : 'none (no D-RAP absorption)'], ['Data', `${r.stations_used} ionosondes ≤ ${r.max_age_h} h old · D-RAP valid ${r.drap_valid ? fmtZ(r.drap_valid) : '?'}`]])}<div style="margin:6px 0">${f}</div>${cps}<p class="dim">${esc(r.notes)}</p>`;
  }
  function hfDraw(r) {
    hfLayer.clearLayers();
    if (!r) return;
    const col = r.muf == null ? '#8593a6' : r.frequencies.some((x) => x.status === 'good') ? '#45d38a' : '#f3b23e';
    L.polyline([[hfDraft.a_lat, hfDraft.a_lon], ...r.control_points.map((c) => [c.lat, c.lon]), [hfDraft.b_lat, hfDraft.b_lon]], { color: col, weight: 2, dashArray: '8 6' }).addTo(hfLayer);
    for (const c of r.control_points) L.circleMarker([c.lat, c.lon], { radius: 5, color: '#fff', weight: 1, fillColor: col, fillOpacity: 1 }).bindTooltip(`Control point: hop MUF ${c.muf ?? 'no data'} MHz`).addTo(hfLayer);
  }
  function openHF() {
    openModal('HF skywave now-cast', `<p class="dim">Path MUF and optimum working frequency now, from live ionosondes and NOAA D-RAP. Screening, not a forecast.</p>${hfForm()}<div id="hf-out">${hfRes ? hfResult(hfRes) : ''}</div>`);
    const pick = (end) => () => {
      hfRead(); $('#modal').classList.remove('show'); map.getContainer().style.cursor = 'crosshair';
      map.once('click', (e) => { map.getContainer().style.cursor = ''; hfDraft[`${end}_lat`] = +e.latlng.lat.toFixed(4); hfDraft[`${end}_lon`] = +e.latlng.lng.toFixed(4); openHF(); });
    };
    $('#hf-pa').addEventListener('click', pick('a')); $('#hf-pb').addEventListener('click', pick('b'));
    $('#hf-go').addEventListener('click', async () => {
      const d = hfRead();
      if ([d.a_lat, d.a_lon, d.b_lat, d.b_lon].some((x) => x == null)) { $('#hf-err').textContent = 'Set both ends'; return; }
      const freqs = d.freqs.split(/[,\s]+/).map(Number).filter((x) => x > 1 && x < 60);
      try { hfRes = await postJson('/api/hf/plan', { a_lat: d.a_lat, a_lon: d.a_lon, b_lat: d.b_lat, b_lon: d.b_lon, freqs_mhz: freqs }); $('#hf-out').innerHTML = hfResult(hfRes); hfDraw(hfRes); }
      catch (e) { $('#hf-err').textContent = e.message; }
    });
  }
  $('#btn-hf').addEventListener('click', () => openHF());
  // ---------------------------------------------------------------- EMO red / blue (notional scenarios)
  const EMO = { ents: [], res: null, t: 0, horizon: 0, params: { rx_h: 2, js_req_db: 0, df_fix_good_m: 1000 }, draft: null, editId: null,
    playing: false, busy: false, pending: false, stale: false, started: 0, examples: null, about: '',
    on: { blue_seen: false, red_seen: false, blue_denied: false, red_denied: false, blue_cov: false, red_cov: false, lines: true, civil_lines: false },
    focus: null, focusRes: null, multi: false, sel: [], multiRes: {}, pairRes: {} };
  const emoLayer = L.layerGroup().addTo(map);
  const planLayer = L.layerGroup().addTo(map);
  const SIDE_COL = { blue: '#3c8cff', red: '#ff4646', grey: '#a6b0bd' };
  const EMO_LAYERS = [['blue_seen', 'Blue emissions red can hear', '#ff4646'], ['red_seen', 'Red emissions blue can hear', '#3cc8ff'],
    ['blue_denied', 'Blue nets denied', '#dc3cdc'], ['red_denied', 'Red nets denied', '#ffa028'], ['blue_cov', 'Blue net coverage', '#3c8cff'],
    ['red_cov', 'Red net coverage', '#ff5a5a'], ['grey_seen', 'Civil emissions heard', '#c8ccd4'], ['grey_denied', 'Civil users denied (collateral)', '#ffffff'], ['civil_lines', 'Lines to civil emitters', '#a6b0bd'], ['lines', 'Detections, bearings, J/S lines', '#c8d3e0']];
  const KIND_TXT = { emitter: 'Emitter', receiver: 'Net user', sensor: 'ES sensor', effector: 'EA effector' };
  function emoIcon(e, off = [0, 0]) {
    const sidc = e.sidc || (e.side === 'blue' ? 'SFGPU----------' : e.side === 'grey' ? 'SNGPU----------' : 'SHGPU----------');
    const air = EMO.res?.on_air?.[e.id] ?? e.active;
    const dim = e.kind !== 'sensor' && (e.kind !== 'receiver' || e.eirp_dbm != null) && !air;
    let html = null, sz = [16, 16], anc = [8, 8];
    if (window.ms) {
      try {
        const sym = new ms.Symbol(sidc, { size: 24, ...(e.side === 'grey' ? { fillColor: '#a6b0bd', colorMode: 'Light' } : {}), uniqueDesignation: e.name.slice(0, 20), additionalInformation: `${KIND_TXT[e.kind]}${e.category ? ' · ' + e.category.toUpperCase() : ''}${dim ? ' · OFF-AIR' : ''}` });
        html = sym.asSVG(); const s = sym.getSize(), a = sym.getAnchor(); sz = [s.width, s.height]; anc = [a.x, a.y];
      } catch (err) { console.warn('milsymbol', err); }
    }
    html = html || `<div style="width:14px;height:14px;border:2px solid #fff;background:${SIDE_COL[e.side]};${e.side === 'red' ? 'transform:rotate(45deg)' : 'border-radius:3px'}"></div>`;
    return L.divIcon({ className: 'emo-sym', html: `<div style="opacity:${dim ? 0.35 : 1}">${html}</div>`, iconSize: sz, iconAnchor: [anc[0] - off[0], anc[1] - off[1]] });
  }
  const emoPos = (e) => (EMO.t === 0 || !EMO.res?.positions?.[e.id]) ? [e.lat, e.lon] : EMO.res.positions[e.id];
  const emoPosId = (id, fallback) => { const e = EMO.ents.find((x) => x.id === id); return e ? emoPos(e) : fallback; };
  function emoDraw() {
    emoLayer.clearLayers();
    const r = EMO.res;
    const F = EMO.focus ? EMO.focusRes : null;
    const M = EMO.multi && EMO.sel.length > 1;
    if (M) {
      const inPair = new Set();
      for (const [k, P] of Object.entries(EMO.pairRes)) { if (P?.overlay) { k.split('|').forEach((x) => inPair.add(x)); L.imageOverlay(P.overlay.png, P.overlay.bounds, { interactive: false, opacity: EMO.stale ? 0.3 : 0.9 }).addTo(emoLayer); } }
      for (const id of EMO.sel) { if (inPair.has(id)) continue; const R = EMO.multiRes[id]; if (R?.overlay) L.imageOverlay(R.overlay.png, R.overlay.bounds, { interactive: false, opacity: EMO.stale ? 0.3 : 0.7 }).addTo(emoLayer); }
    }
    else if (F?.overlay) L.imageOverlay(F.overlay.png, F.overlay.bounds, { interactive: false, opacity: EMO.stale ? 0.35 : 1 }).addTo(emoLayer);
    if (!EMO.focus && !M) for (const [k] of EMO_LAYERS) if (!['lines', 'civil_lines'].includes(k) && EMO.on[k] && r?.layers?.[k]) L.imageOverlay(r.layers[k], r.bounds, { interactive: false, opacity: EMO.stale ? 0.35 : 1 }).addTo(emoLayer);
    const selSet = new Set(EMO.sel);
    const selNames = new Set(EMO.ents.filter((e) => selSet.has(e.id)).map((e) => e.name));
    const inv = (a, b) => M ? (selSet.has(a) && selSet.has(b)) : (!EMO.focus || a === EMO.focus || b === EMO.focus);
    const involved = M ? selSet : new Set(EMO.focus ? [EMO.focus, ...((F?.heard_by || []).map((d) => d.sensor_id)), ...((F?.hears || []).map((d) => d.target_id)),
      ...((F?.jams || []).map((x) => x.victim_id)), ...((F?.jammed || []).flatMap((x) => [x.effector_id, x.victim_id]))] : []);
    for (const e of EMO.ents) if (e.track?.length) L.polyline([[e.lat, e.lon], ...e.track], { color: SIDE_COL[e.side], weight: 2, dashArray: '6 6', opacity: 0.7, interactive: false }).addTo(emoLayer);
    if (EMO.on.lines && r) {
      const greyIds = new Set(EMO.ents.filter((e) => e.side === 'grey').map((e) => e.id));
      for (const d of r.detections.filter((x) => x.detected && inv(x.sensor_id, x.target_id) && (EMO.on.civil_lines || M || EMO.focus || !greyIds.has(x.target_id)))) {
        L.polyline([emoPosId(d.sensor_id, d.a), emoPosId(d.target_id, d.b)], { color: d.sensor_side === 'red' ? '#ff4646' : '#3cc8ff', weight: 1.5, opacity: EMO.stale ? 0.35 : 0.7, dashArray: d.df ? null : '2 5' })
          .bindTooltip(`${esc(d.sensor)} hears ${esc(d.target)}: ${d.level_dbm} dBm, margin ${d.margin_db} dB${d.df ? ' (DF bearing)' : ''}`).addTo(emoLayer);
      }
      for (const f of r.fixes.filter((x) => x.fix && (M ? selNames.has(x.target) : (!EMO.focus || x.target === F?.name)))) {
        const col = f.target_side === 'blue' ? '#ff4646' : '#3cc8ff';
        L.circle(f.fix.fix, { radius: f.fix.error_m, color: col, weight: f.targetable ? 3 : 1.5, fillOpacity: f.targetable ? 0.25 : 0.08 })
          .bindTooltip(`${f.targetable ? 'FIXED, TARGETABLE' : 'Fix'}: ${esc(f.target)} ±${f.fix.error_m} m (cut ${f.fix.cut_deg}°, ${esc(f.fix.sensors.join(' + '))})`, { direction: 'top' }).addTo(emoLayer);
        if (f.targetable) L.marker(f.fix.fix, { interactive: false, icon: L.divIcon({ className: 'emo-fixlbl', html: `FIX ±${f.fix.error_m} m`, iconSize: [84, 16], iconAnchor: [42, -10] }) }).addTo(emoLayer);
        else if (f.located && (EMO.on.civil_lines || M || EMO.focus)) L.marker(f.fix.fix, { interactive: false, icon: L.divIcon({ className: 'emo-fixlbl emo-loc', html: `located ±${f.fix.error_m} m`, iconSize: [96, 16], iconAnchor: [48, -10] }) }).addTo(emoLayer);
      }
      for (const j of r.jamming.filter((x) => inv(x.effector_id, x.victim_id) || (EMO.focus && F?.kind === 'emitter' && x.net === F?.name))) {
        const col = j.status === 'denied' ? '#dc3cdc' : j.status === 'holds' ? '#45d38a' : '#8593a6';
        L.polyline([emoPosId(j.effector_id, j.a), emoPosId(j.victim_id, j.b)], { color: col, weight: 2.5, opacity: EMO.stale ? 0.35 : 0.9 })
          .bindTooltip(`${esc(j.effector)} → ${esc(j.victim)}: J/S ${j.js_db} dB vs ${j.js_req_db} dB needed → ${esc(j.status)}${j.p != null ? ` (${j.p}% likely)` : ''}${j.bw_penalty_db ? ` (bandwidth loss ${j.bw_penalty_db} dB)` : ''}`).addTo(emoLayer);
      }
    }
    // fan out co-located symbols (e.g. a ship's radar, radio and EA) so each can be tapped
    const stack = {}, fan = {};
    for (const e of EMO.ents) { const p = emoPos(e); const k = `${p[0].toFixed(3)},${p[1].toFixed(3)}`; (stack[k] = stack[k] || []).push(e.id); }
    for (const ids of Object.values(stack)) if (ids.length > 1) ids.forEach((id, i) => { const a = (2 * Math.PI * i) / ids.length - Math.PI / 2, r = 16 + 5 * ids.length; fan[id] = [Math.round(r * Math.cos(a)), Math.round(r * Math.sin(a))]; });
    for (const e of EMO.ents) {
      const mk = L.marker(emoPos(e), { icon: emoIcon(e, fan[e.id]), draggable: EMO.t === 0, zIndexOffset: e.id === EMO.focus ? 2000 : 1000, autoPan: true,
        opacity: (EMO.focus || M) && !involved.has(e.id) ? 0.3 : 1 });
      mk.on('click', (ev) => (EMO.multi || ev.originalEvent?.shiftKey) ? emoToggleSel(e.id) : emoFocus(e.id));
      mk.on('dragend', async () => {
        const ll = mk.getLatLng();
        e.lat = +ll.lat.toFixed(5); e.lon = +ll.lng.toFixed(5); EMO.stale = true; emoDraw();
        try { await postJson(`/api/emo/${encodeURIComponent(e.id)}/move`, { lat: e.lat, lon: e.lon }); emoRun(); } catch (err) { emoToast(err.message); }
      });
      const radiates = e.kind === 'emitter' || e.kind === 'effector' || (e.kind === 'receiver' && e.eirp_dbm != null);
      const _info = (() => `<h4 style="color:${SIDE_COL[e.side]}">${esc(e.name)}</h4>${kv([['Role', `${e.side} ${KIND_TXT[e.kind].toLowerCase()}${e.category ? ' (' + e.category + ')' : ''}`],
        ['Frequency', e.kind === 'sensor' ? `${e.freq_mhz}–${e.f_hi_mhz} MHz${e.df_rms_deg ? `, DF ±${e.df_rms_deg}°` : ''}` : `${e.freq_mhz} MHz, ${e.bw_khz} kHz`],
        ['EIRP', e.fixed_level_dbm != null ? `space signal ${e.fixed_level_dbm} dBm` : e.eirp_dbm != null ? `${e.eirp_dbm} dBm` : 'receive only'],
        ['Height', `${e.h_agl} m`], ['Track', e.track?.length ? `${e.track.length} waypoint(s), ${e.speed_kmh} km/h` : 'static']])}
        <p style="margin:6px 0 0">${radiates && e.fixed_level_dbm == null ? `<a href="#" class="emo-emcon" data-id="${esc(e.id)}" data-on="${e.active ? 0 : 1}">${e.active ? 'EMCON: take off-air' : 'Back on air'}</a> · ` : ''}<a href="#" class="emo-edit" data-id="${esc(e.id)}">Edit</a>${EMO.t === 0 ? ' · drag to move' : ' · set time 0 to drag'}</p>`); mk.addTo(emoLayer);
    }
  }
  map.on('popupopen', (ev) => {
    const el = ev.popup.getElement(); if (!el) return;
    el.querySelectorAll('a.emo-edit').forEach((a) => a.addEventListener('click', (x) => { x.preventDefault(); map.closePopup(); EMO.editId = a.dataset.id; EMO.draft = { ...EMO.ents.find((e) => e.id === a.dataset.id) }; openEMO(); }));
    el.querySelectorAll('a.emo-emcon').forEach((a) => a.addEventListener('click', async (x) => {
      x.preventDefault(); map.closePopup();
      try { await fetch(`/api/emo/${encodeURIComponent(a.dataset.id)}/active?on=${a.dataset.on === '1'}`, { method: 'POST' }); await emoLoad(); emoRun(); } catch (err) { emoToast(err.message); }
    }));
  });
  async function emoFocus(id) {
    EMO.focus = id; EMO.focusRes = null; emoCard('<span class="dim">Loading…</span>');
    try {
      if (!EMO.res) { emoCard('<span class="dim">Waiting for the analysis to finish…</span>'); return; }
      EMO.focusRes = await api(`/api/emo/focus/${encodeURIComponent(id)}?t_min=${EMO.t}`);
      emoDraw(); emoCard(emoCardHtml(EMO.focusRes));
    } catch (err) { emoCard(`<span class="bad">${esc(err.message)}</span>`); }
  }
  async function emoPlan(kind) {
    const out = $('#emo-planout'); if (!out) return;
    const e = EMO.ents.find((x) => x.id === EMO.focus); if (!e) return;
    const t0 = Date.now(); const tick = setInterval(() => { out.innerHTML = `<p><span class="spinner"></span> searching positions… ${Math.round((Date.now() - t0) / 1000)} s (1-3 min)</p>`; }, 1000);
    try {
      const r = await postJson(`/api/emo/plan/map?t_min=${EMO.t}`, kind === 'net' ? { kind: 'net', name: e.name } : { kind: 'ea', name: e.name, target_net: $('[data-emo-eatgt]').value });
      clearInterval(tick);
      planLayer.clearLayers();
      EMO.planRes = r;
      const showLayer = (k) => { planLayer.eachLayer((l) => { if (l instanceof L.ImageOverlay) planLayer.removeLayer(l); }); L.imageOverlay(r.layers[k], r.bounds, { interactive: false, opacity: 0.75 }).addTo(planLayer); };
      showLayer('score');
      const cur = emoPos(e);
      const fmt = (x) => kind === 'net'
        ? `${x.users_closed}/${x.of_users} users closed · margin ${x.link_margin_db >= 0 ? '+' : ''}${x.link_margin_db} dB · ${x.heard_by.length ? `heard by ${x.heard_by.length}` : 'not heard'} · J/S ${x.worst_js_db} dB`
        : `denies ${x.denied}/${x.of_users} · worst J/S ${x.min_js_db} dB · exposure ${x.exposure_db >= 0 ? '+' : ''}${x.exposure_db} dB${x.fratricide ? ` · <b class="bad">fratricide ${x.fratricide}</b>` : ''}`;
      r.best.slice(0, 3).forEach((x, i) => {
        L.polyline([cur, [x.lat, x.lon]], { color: '#45d38a', weight: 2, dashArray: '5 6', opacity: 0.8, interactive: false }).addTo(planLayer);
        L.marker([x.lat, x.lon], { icon: L.divIcon({ className: 'emo-planpin', html: `${i + 1}`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
          .bindTooltip(`Option ${i + 1}: ${x.where}<br>${fmt(x)}`).addTo(planLayer);
      });
      if (r.relay) L.marker([r.relay.lat, r.relay.lon], { icon: L.divIcon({ className: 'emo-planpin emo-relay', html: 'R', iconSize: [22, 22], iconAnchor: [11, 11] }) })
        .bindTooltip(`Relay: ${r.relay.where}<br>reaches ${r.relay.reaches}/${r.relay.of_failing} (${esc(r.relay.serves.join(', '))})`).addTo(planLayer);
      out.innerHTML = `<h4>${kind === 'net' ? 'Where to site this net' : `Where to site it to deny ${esc(r.target_net)}`}</h4>
        <p>${Object.keys(r.layers).map((k) => `<label style="margin-right:8px"><input type="radio" name="emo-planlayer" value="${k}"${k === 'score' ? ' checked' : ''}> ${k}</label>`).join('')} <span class="dim">${esc(r.legend)}</span></p>
        ${r.unavoidable?.length ? `<p class="bad">No site within reach hides this net from ${esc(r.unavoidable.join(', '))}, even at minimum power: use EMCON windows, a directional antenna or another bearer.</p>` : ''}
        <table class="grid">${r.best.slice(0, 3).map((x, i) => `<tr><td><b>${i + 1}</b></td><td>${esc(x.where)}<div class="dim">${fmt(x)}</div></td><td><button data-emo-moveto="${x.lat},${x.lon}">Move here</button></td></tr>`).join('')}</table>
        ${r.relay ? `<p><b>Relay R</b>: ${esc(r.relay.where)}: reaches ${r.relay.reaches}/${r.relay.of_failing} (${esc(r.relay.serves.join(', '))}), exposure ${r.relay.exposure_db} dB.</p>` : ''}
        <p class="dim">${esc(r.notes)}</p>`;
      out.querySelectorAll('input[name=emo-planlayer]').forEach((rb) => rb.addEventListener('change', () => showLayer(rb.value)));
      out.querySelectorAll('[data-emo-moveto]').forEach((b) => b.addEventListener('click', async () => {
        const [la, lo] = b.dataset.emoMoveto.split(',').map(Number);
        e.lat = la; e.lon = lo; EMO.stale = true; planLayer.clearLayers(); emoDraw();
        await postJson(`/api/emo/${encodeURIComponent(e.id)}/move`, { lat: la, lon: lo }); emoRun();
      }));
    } catch (err) { clearInterval(tick); out.innerHTML = `<p class="bad">${esc(err.message)}</p>`; }
  }
  async function emoTune() {
    const out = $('#emo-planout'), e = EMO.ents.find((x) => x.id === EMO.focus); if (!out || !e) return;
    out.innerHTML = '<p><span class="spinner"></span> computing power, antenna and channel options…</p>';
    try {
      const r = await postJson(`/api/emo/plan/tune?t_min=${EMO.t}`, { net: e.name });
      const P = r.power, A = r.antenna.best_sector, O = r.antenna.omni_now, C = r.channel;
      const apply = async (body) => { await postJson(`/api/emo/plan/tune/apply?t_min=${EMO.t}`, { net: e.name, ...body }); await emoLoad(); emoRun(); };
      out.innerHTML = `<h4>EP options at the current position</h4>
        <p><b>Power:</b> cut by ${P.cut_db} dB (${P.current_eirp_dbm} → ${P.recommended_eirp_dbm} dBm EIRP) keeps 6 dB margin at every user; still heard by ${P.heard_by_after.length ? esc(P.heard_by_after.join(', ')) : 'no opposing sensor'} (now: ${P.heard_by_now.length}). ${P.cut_db > 0 ? `<button data-tune-power>Apply</button>` : ''}</p>
        <p><b>Antenna:</b> ${A ? `sector ${A.beamwidth}° at ${A.azimuth}°: ${A.users_closed}/${A.of_users} users kept, heard by ${A.heard_by.length} (omni: ${O.users_closed} kept, heard by ${O.heard_by.length}), worst exposure ${A.worst_exposure_db} dB (omni ${O.worst_exposure_db}). ${A.heard_by.length < O.heard_by.length || A.worst_exposure_db < O.worst_exposure_db - 3 ? '<button data-tune-ant>Apply</button>' : '<span class="dim">no gain over omni</span>'}` : 'n/a'}</p>
        <p><b>Channel:</b> now ${C.current_mhz} MHz${C.current_jammed_by.length ? `, inside ${esc(C.current_jammed_by.join(', '))}` : ', clear of jammers'}. ${C.clear_of_jammers.length ? `Clear of jammers: ${C.clear_of_jammers.slice(0, 6).map((f) => `<button data-tune-freq="${f}">${f}</button>`).join(' ')} MHz` : 'No clear channel in band.'} <span class="dim">${esc(C.note)}</span></p>
        <p class="dim">${esc(r.notes)}</p>`;
      out.querySelector('[data-tune-power]')?.addEventListener('click', () => apply({ eirp_dbm: P.recommended_eirp_dbm }));
      out.querySelector('[data-tune-ant]')?.addEventListener('click', () => apply({ azimuth: A.azimuth, beamwidth: A.beamwidth }));
      out.querySelectorAll('[data-tune-freq]').forEach((b) => b.addEventListener('click', () => apply({ freq_mhz: +b.dataset.tuneFreq })));
    } catch (err) { out.innerHTML = `<p class="bad">${esc(err.message)}</p>`; }
  }
  async function emoJoint() {
    const out = $('#emo-planout'), e = EMO.ents.find((x) => x.id === EMO.focus); if (!out || !e) return;
    const t0 = Date.now(); const tick = setInterval(() => { out.innerHTML = `<p><span class="spinner"></span> re-siting users then control station… ${Math.round((Date.now() - t0) / 1000)} s</p>`; }, 1000);
    try {
      const r = await postJson(`/api/emo/plan/joint?t_min=${EMO.t}`, { net: e.name });
      clearInterval(tick); planLayer.clearLayers();
      r.moves.forEach((m) => L.polyline([m.from, m.to], { color: '#45d38a', weight: 3, dashArray: '6 6' }).bindTooltip(`${esc(m.entity)} → ${esc(m.where)}<br>${esc(m.detail)}`).addTo(planLayer));
      out.innerHTML = `<h4>Joint re-site</h4>${r.moves.length ? `<ul>${r.moves.map((m) => `<li><b>${esc(m.entity)}</b> → ${esc(m.where)}: ${esc(m.detail)}</li>`).join('')}</ul>` : '<p>No move is clearly better; the net is already well sited.</p>'}${(r.rejected || []).map((x) => `<p class="bad">${esc(x)}</p>`).join('')}<p class="dim">${esc(r.notes)}</p>`;
      EMO.prevScore = r.score_before || EMO.prevScore; await emoLoad(); EMO.res = null; await emoRun();
    } catch (err) { clearInterval(tick); out.innerHTML = `<p class="bad">${esc(err.message)}</p>`; }
  }
  function emoClearFocus() { planLayer.clearLayers(); EMO.focus = null; EMO.focusRes = null; EMO.multi = false; EMO.sel = []; EMO.multiRes = {}; EMO.pairRes = {}; document.getElementById('emo-card')?.remove(); emoDraw(); }
  function emoCard(html) {
    let c = document.getElementById('emo-card');
    if (!c) { c = document.createElement('div'); c.id = 'emo-card'; document.body.appendChild(c); }
    c.innerHTML = html;
    c.querySelector('[data-emo-clear]')?.addEventListener('click', emoClearFocus);
    c.querySelector('[data-emo-multi]')?.addEventListener('click', () => { EMO.multi = true; EMO.sel = [EMO.focus]; emoMultiRefresh(); });
    c.querySelector('[data-emo-done]')?.addEventListener('click', () => { const last = EMO.sel[EMO.sel.length - 1]; EMO.multi = false; EMO.sel = []; EMO.multiRes = {}; if (last) emoFocus(last); else emoClearFocus(); });
    c.querySelectorAll('[data-emo-unsel]').forEach((b) => b.addEventListener('click', () => emoToggleSel(b.dataset.emoUnsel)));
    c.querySelector('[data-emo-add]')?.addEventListener('change', (e) => { if (e.target.value) emoToggleSel(e.target.value); });
    c.querySelector('[data-emo-emcon]')?.addEventListener('click', async (x) => {
      const b = x.currentTarget; await fetch(`/api/emo/${encodeURIComponent(EMO.focus)}/active?on=${b.dataset.on === '1'}`, { method: 'POST' }); EMO.stale = true; emoRun();
    });
    c.querySelector('[data-emo-plannet]')?.addEventListener('click', () => emoPlan('net'));
    c.querySelector('[data-emo-planea]')?.addEventListener('click', () => emoPlan('ea'));
    c.querySelector('[data-emo-tune]')?.addEventListener('click', () => emoTune());
    c.querySelector('[data-emo-joint]')?.addEventListener('click', () => emoJoint());
    c.querySelector('[data-emo-editf]')?.addEventListener('click', () => { EMO.editId = EMO.focus; EMO.draft = { ...EMO.ents.find((e) => e.id === EMO.focus) }; openEMO(); });
  }
  function emoCardHtml(f) {
    const e = EMO.ents.find((x) => x.id === f.id) || {};
    const col = SIDE_COL[f.side];
    const row = (a, b, c) => `<tr><td>${a}</td><td class="mono">${b}</td><td>${c || ''}</td></tr>`;
    const tbl = (title, rows) => rows.length ? `<h4>${title}</h4><table class="grid">${rows.join('')}</table>` : '';
    const heard = f.heard_by.filter((d) => d.detected), missed = f.heard_by.filter((d) => !d.detected);
    const hears = f.hears.filter((d) => d.detected), misses = f.hears.filter((d) => !d.detected);
    const radiates = ['emitter', 'effector'].includes(f.kind) || (f.kind === 'receiver' && e.eirp_dbm != null);
    return `<div class="emo-card-head"><b style="color:${col}">${esc(f.name)}</b> <span class="dim">${esc(f.side)} ${esc(KIND_TXT[f.kind] || f.kind)}${f.category ? ' · ' + esc(f.category) : ''}${f.active ? '' : ' · OFF-AIR'}</span>
        <span class="btns">${radiates && e.fixed_level_dbm == null ? `<button data-emo-emcon data-on="${f.active ? 0 : 1}">${f.active ? 'EMCON off-air' : 'On air'}</button>` : ''}<button data-emo-editf>Edit</button><button data-emo-multi>Compare with others</button>${f.kind === 'emitter' && e.fixed_level_dbm == null && EMO.ents.some((u) => u.net === f.id) ? '<button data-emo-plannet>Find a better site (EP)</button> <button data-emo-tune>Tune: power, antenna, channel</button> <button data-emo-joint>Joint re-site net</button>' : ''}<button data-emo-clear>Clear focus</button></span></div>
      ${f.kind === 'effector' ? `<div class="specset"><select data-emo-eatgt>${EMO.ents.filter((n) => n.kind === 'emitter' && n.side !== f.side && n.side !== 'grey' && EMO.ents.some((u) => u.net === n.id)).map((n) => `<option>${esc(n.name)}</option>`).join('')}</select><button data-emo-planea>Best site to deny it (EA)</button></div>` : ''}
      <div id="emo-planout"></div>
      ${f.legend ? `<p class="dim">Footprint: where its signal is above ${f.legend.threshold_dbm} dBm (${esc(f.legend.basis)}); darker = just audible, brighter = +10 and +20 dB above; the outline is the limit.${f.kind === 'effector' ? ' Hatched magenta: denial it causes on victim nets.' : ''}</p>` : ''}
      ${f.fix?.fix ? `<p><b style="color:${f.fix.targetable ? '#ff4646' : '#f3b23e'}">${f.fix.targetable ? 'FIXED, TARGETABLE' : 'Fixed'}: ±${f.fix.fix.error_m} m</b> <span class="dim">(cut ${f.fix.fix.cut_deg}°, ${esc(f.fix.fix.sensors.join(' + '))})</span></p>` : (heard.some((d) => d.df) ? '<p class="dim">Single line of bearing only: not fixed.</p>' : '')}
      ${tbl(`Picked up by (${heard.length})`, heard.map((d) => row(esc(d.sensor), `+${d.margin_db} dB`, d.df ? 'DF bearing' : 'intercept')))}
      ${tbl(`Not heard by (${missed.length})`, missed.map((d) => row(esc(d.sensor), `${d.margin_db} dB`, 'below sensitivity')))}
      ${tbl(`Hears (${hears.length})`, hears.map((d) => row(esc(d.target), `+${d.margin_db} dB`, esc(d.category || ''))))}
      ${tbl(`Misses (${misses.length})`, misses.map((d) => row(esc(d.target), `${d.margin_db} dB`, '')))}
      ${tbl(`Jams (${f.jams.length})`, f.jams.map((x) => row(esc(x.victim), `J/S ${x.js_db} dB${x.p != null ? ` · ${x.p}%` : ''}`, `<b style="color:${x.status === 'denied' ? '#dc3cdc' : x.status === 'spoofed' ? '#c58cff' : '#45d38a'}">${esc(x.status)}</b>`)))}
      ${tbl(`Under attack (${f.jammed.length})`, f.jammed.map((x) => row(`${esc(x.effector)} → ${esc(x.victim)}`, `J/S ${x.js_db} dB${x.p != null ? ` · ${x.p}%` : ''}`, `<b style="color:${x.status === 'denied' ? '#dc3cdc' : x.status === 'spoofed' ? '#c58cff' : '#45d38a'}">${esc(x.status)}</b>`)))}
      ${!heard.length && !missed.length && !hears.length && !misses.length && !f.jams.length && !f.jammed.length ? '<p class="dim">No interactions on its frequencies.</p>' : ''}`;
  }
  function emoToggleSel(id) {
    if (!EMO.multi) { EMO.multi = true; EMO.sel = EMO.focus ? [EMO.focus] : []; }
    EMO.sel = EMO.sel.includes(id) ? EMO.sel.filter((x) => x !== id) : [...EMO.sel, id];
    if (!EMO.sel.length) return emoClearFocus();
    emoMultiRefresh();
  }
  async function emoMultiRefresh() {
    EMO.focus = EMO.sel[EMO.sel.length - 1] || null;
    emoCard('<span class="dim">Loading selection…</span>');
    if (!EMO.res) { emoCard('<span class="dim">Waiting for the analysis to finish…</span>'); return; }
    try {
      await Promise.all(EMO.sel.filter((id) => !EMO.multiRes[id]).map(async (id) => { EMO.multiRes[id] = await api(`/api/emo/focus/${encodeURIComponent(id)}?t_min=${EMO.t}`); }));
      const pairs = []; for (let i = 0; i < EMO.sel.length; i++) for (let k = i + 1; k < EMO.sel.length; k++) pairs.push([EMO.sel[i], EMO.sel[k]]);
      for (const key of Object.keys(EMO.pairRes)) { const [a, b] = key.split('|'); if (!EMO.sel.includes(a) || !EMO.sel.includes(b)) delete EMO.pairRes[key]; }
      await Promise.all(pairs.filter(([a, b]) => !(`${a}|${b}` in EMO.pairRes)).map(async ([a, b]) => {
        try { const P = await api(`/api/emo/pair?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&t_min=${EMO.t}`); EMO.pairRes[`${a}|${b}`] = P.kind === 'none' ? null : P; } catch (e) { EMO.pairRes[`${a}|${b}`] = null; }
      }));
      EMO.focusRes = EMO.multiRes[EMO.focus] || null;
      emoDraw(); emoCard(emoMultiHtml());
    } catch (err) { emoCard(`<span class="bad">${esc(err.message)}</span>`); }
  }
  function emoMultiHtml() {
    const r = EMO.res, sel = new Set(EMO.sel), byId = Object.fromEntries(EMO.ents.map((e) => [e.id, e]));
    const nm = (id) => `<span style="color:${SIDE_COL[byId[id]?.side] || '#fff'}">${esc(byId[id]?.name || id)}</span>`;
    const chips = EMO.sel.map((id) => `<span class="emo-chipsel">${nm(id)} <button data-emo-unsel="${esc(id)}" title="Remove">×</button></span>`).join(' ');
    const det = r.detections.filter((d) => sel.has(d.sensor_id) && sel.has(d.target_id)).sort((a, b) => b.margin_db - a.margin_db);
    const jam = r.jamming.filter((j) => sel.has(j.effector_id) && sel.has(j.victim_id));
    const names = new Set(EMO.sel.map((id) => byId[id]?.name));
    const fx = r.fixes.filter((f) => names.has(f.target) && f.fix);
    const row = (a, b, c) => `<tr><td>${a}</td><td class="mono">${b}</td><td>${c || ''}</td></tr>`;
    const tbl = (h, rows) => rows.length ? `<h4>${h}</h4><table class="grid">${rows.join('')}</table>` : '';
    return `<div class="emo-card-head"><b>Comparing ${EMO.sel.length}</b><span class="btns"><button data-emo-done>Done</button><button data-emo-clear>Clear</button></span></div>
      <p>${chips}</p>
      <p><select data-emo-add style="max-width:100%"><option value="">+ Add an entity…</option>
        ${['blue', 'red'].map((sd) => `<optgroup label="${sd === 'blue' ? 'Blue' : 'Red'}">${EMO.ents.filter((e) => e.side === sd && !sel.has(e.id)).sort((a, b) => a.name.localeCompare(b.name)).map((e) => `<option value="${esc(e.id)}">${esc(e.name)} · ${esc(KIND_TXT[e.kind] || e.kind)}${e.category ? ' · ' + esc(e.category) : ''}</option>`).join('')}</optgroup>`).join('')}
      </select></p>
      <p class="dim">Add from the list, or tap symbols on the map${matchMedia('(pointer:fine)').matches ? ' (shift-click on desktop)' : ''}; × removes. All selected footprints are shown; lines only between them.</p>
      ${EMO.sel.length < 2 ? '<p class="dim">Select at least one more entity.</p>' : ''}
      ${Object.values(EMO.pairRes).filter(Boolean).map((P) => P.kind === 'jam'
        ? `<div class="emo-pair"><b>${esc(P.effector)} vs ${esc(P.net)}</b>: ${P.space ? `denies ${P.denied_km2} km²` : `denies <b>${P.denied_pct}%</b> of the net's coverage (${P.denied_km2} of ${P.coverage_km2} km²)`}; fails at J/S ${P.js_req_db} dB.${P.users.length ? '<br>' + P.users.map((u) => `${esc(u.victim)}: J/S ${u.js_db} dB, <b style="color:${u.status === 'denied' ? '#dc3cdc' : '#45d38a'}">${esc(u.status)}</b>`).join(' · ') : ''}<div class="dim">${esc(P.legend)}</div></div>`
        : `<div class="emo-pair"><b>${esc(P.sensor)} ${P.detected ? 'hears' : 'does not hear'} ${esc(P.emitter)}</b>${P.margin_db != null ? ` (${P.margin_db >= 0 ? '+' : ''}${P.margin_db} dB)` : ''}<div class="dim">${esc(P.legend)}</div></div>`).join('')}
      ${tbl(`Who hears whom (${det.filter((d) => d.detected).length})`, det.map((d) => row(`${nm(d.sensor_id)} → ${nm(d.target_id)}`, `${d.margin_db >= 0 ? '+' : ''}${d.margin_db} dB`, d.detected ? (d.df ? 'heard, DF bearing' : 'heard') : '<span class="dim">not heard</span>')))}
      ${tbl('Fixes on selected', fx.map((f) => row(esc(f.target), `±${f.fix.error_m} m`, `${f.targetable ? '<b style="color:#ff4646">TARGETABLE</b> ' : ''}by ${esc(f.fix.sensors.join(' + '))}`)))}
      ${tbl(`Who jams whom (${jam.length})`, jam.map((j) => row(`${nm(j.effector_id)} → ${nm(j.victim_id)}`, `J/S ${j.js_db} dB`, `<b style="color:${j.status === 'denied' ? '#dc3cdc' : '#45d38a'}">${esc(j.status)}</b>`)))}
      ${EMO.sel.length > 1 && !det.length && !jam.length ? '<p class="dim">No interactions between these on their frequencies (different bands, or no sensor/effector among them).</p>' : ''}`;
  }
  function emoAskBar() {
    if (document.getElementById('emo-askbar') || !EMO.ents.length) return;
    const bar = document.createElement('div'); bar.id = 'emo-askbar';
    bar.innerHTML = '<input id="emo-askmap" placeholder="Ask about this scenario or your selection…"><button id="emo-askgo">Ask</button><button id="emo-askx" title="Hide">×</button>';
    document.body.appendChild(bar);
    const go = async () => {
      const q = $('#emo-askmap').value.trim(); if (q.length < 2) return;
      const sel = EMO.multi && EMO.sel.length ? EMO.sel : EMO.focus ? [EMO.focus] : null;
      let card = document.getElementById('emo-askcard'); if (!card) { card = document.createElement('div'); card.id = 'emo-askcard'; document.body.appendChild(card); }
      card.innerHTML = `<div class="emo-card-head"><b>EMO analyst</b><span class="dim">${sel ? `about ${sel.length} selected` : 'whole scenario'}</span><span class="btns"><button id="emo-askclose">Close</button></span></div><div id="emo-askbody"><span class="spinner"></span> thinking… (about a minute)</div>`;
      $('#emo-askclose').addEventListener('click', () => card.remove());
      let text = '';
      try {
        const r = await fetch('/api/emo/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, selected: sel }) });
        const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
        while (true) {
          const { value, done } = await rd.read(); if (done) break;
          buf += dec.decode(value, { stream: true }); const parts = buf.split('\n\n'); buf = parts.pop();
          for (const p of parts) { const l = p.split('\n').find((x) => x.startsWith('data: ')); if (!l) continue; const d = JSON.parse(l.slice(6)); if (d.t) { text += d.t; $('#emo-askbody').textContent = text; } }
        }
        $('#emo-askbody').innerHTML = renderMd(text || '(no answer)');
      } catch (err) { $('#emo-askbody').innerHTML = `<p class="bad">${esc(err.message)}</p>`; }
    };
    $('#emo-askgo').addEventListener('click', go);
    $('#emo-askmap').addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    $('#emo-askx').addEventListener('click', () => bar.remove());
  }
  async function emoLoad() { EMO.ents = (await api('/api/emo')).entities; }
  let emoTick = null;
  async function emoRun() {
    if (EMO.busy) { EMO.pending = true; EMO.stale = true; return; }
    EMO.busy = true; EMO.pending = false; EMO.started = Date.now();
    clearInterval(emoTick);
    emoTick = setInterval(() => emoStatus(`EMO computing… ${Math.round((Date.now() - EMO.started) / 1000)} s${EMO.res ? '' : ' (first run of a scenario takes about a minute)'}`), 1000);
    try {
      await emoLoad();
      EMO.prevScore = EMO.res?.score || EMO.prevScore;
      EMO.res = await postJson(`/api/emo/run?t_min=${EMO.t}`, EMO.params); EMO.horizon = EMO.res.horizon_min;
      EMO.stale = EMO.pending; emoDraw(); emoResults(); emoAskBar();
      if (EMO.multi && EMO.sel.length) { EMO.multiRes = {}; EMO.pairRes = {}; emoMultiRefresh(); } else if (EMO.focus) emoFocus(EMO.focus);
      const fx = EMO.res.fixes.filter((f) => f.targetable).length;
      const worst = [...EMO.res.nets].sort((a, b) => b.denied_pct - a.denied_pct)[0];
      emoStatus(`EMO T+${Math.round(EMO.t)} min${EMO.pending ? ' · updating…' : ''} · ${fx} targetable fix${fx === 1 ? '' : 'es'}${worst ? ` · ${worst.net} ${worst.denied_pct}% denied` : ''} · ${EMO.res.compute_s} s`);
    } catch (err) { emoStatus(`EMO error: ${err.message}`); }
    finally { clearInterval(emoTick); EMO.busy = false; if (EMO.pending) emoRun(); }
  }
  function emoStatus(t) {
    const el = $('#emo-status'); if (el) el.textContent = t;
    let chip = document.getElementById('emo-chip');
    if (!chip) { chip = document.createElement('div'); chip.id = 'emo-chip'; chip.title = 'Open EMO panel'; chip.addEventListener('click', () => openEMO()); document.body.appendChild(chip); }
    chip.textContent = t; chip.classList.toggle('busy', /computing|updating/.test(t));
  }
  function emoToast(t) { console.warn(t); emoStatus(t); }
  const EMO_FIELDS = [['name', 'Name', 'text'], ['side', 'Side (blue/red/grey)', 'text'], ['kind', 'Kind (emitter/receiver/sensor/effector)', 'text'],
    ['category', 'Category (comms/radar/datalink/nav/cuas/other/es/df/rwr)', 'text'], ['lat', 'Lat', 'number'], ['lon', 'Lon', 'number'],
    ['h_agl', 'Height m AGL', 'number'], ['freq_mhz', 'Freq MHz (sensor: band start)', 'number'], ['f_hi_mhz', 'Sensor band end MHz', 'number'],
    ['bw_khz', 'Bandwidth kHz', 'number'], ['eirp_dbm', 'EIRP dBm (blank = receive only)', 'number'], ['sens_dbm', 'Sensitivity dBm', 'number'],
    ['js_req_db', 'Net fails at J/S dB', 'number'], ['df_rms_deg', 'DF accuracy ° RMS (sensor)', 'number'], ['fixed_level_dbm', 'Space signal dBm (GNSS)', 'number'],
    ['pattern', 'Antenna omni/sector', 'text'], ['azimuth', 'Sector azimuth °', 'number'], ['beamwidth', 'Beamwidth °', 'number'],
    ['ea_mode', 'EA mode noise/spoof (effector)', 'text'], ['rcs_m2', 'RCS m² (as a radar target)', 'number'], ['radar_gain_dbi', 'Radar antenna gain dBi', 'number'], ['radar_mds_dbm', 'Radar min detectable echo dBm', 'number'],
    ['radius_km', 'Footprint radius km (≤100, blank = auto)', 'number'], ['hop_bw_khz', 'Hopset width kHz (frequency hopping)', 'number'],
    ['pg_db', 'Processing gain dB (anti-jam)', 'number'], ['speed_kmh', 'Track speed km/h', 'number'], ['sidc', 'APP-6 SIDC', 'text'], ['notes', 'Notes', 'text']];
  const EMO_TPL = [
    ['CNR manpack VHF, 5 W, hopping', { kind: 'receiver', category: 'comms', freq_mhz: 45, bw_khz: 25, eirp_dbm: 37, hop_bw_khz: 58000, h_agl: 2 }],
    ['CNR vehicle VHF, 50 W, hopping (net control)', { kind: 'emitter', category: 'comms', freq_mhz: 45, bw_khz: 25, eirp_dbm: 47, hop_bw_khz: 58000, sens_dbm: -110, js_req_db: 0, h_agl: 4 }],
    ['VHF single-channel net control, 50 W', { kind: 'emitter', category: 'comms', freq_mhz: 45, bw_khz: 25, eirp_dbm: 47, hop_bw_khz: null, sens_dbm: -110, js_req_db: 0, h_agl: 4 }],
    ['UHF tactical, 25 kHz, 10 W', { kind: 'emitter', category: 'comms', freq_mhz: 300, bw_khz: 25, eirp_dbm: 40, sens_dbm: -110, js_req_db: 0, h_agl: 4 }],
    ['Link 16 class terminal (3 MHz hops, 960-1215 MHz)', { kind: 'emitter', category: 'datalink', freq_mhz: 1087.5, bw_khz: 3000, hop_bw_khz: 255000, eirp_dbm: 50, sens_dbm: -100, js_req_db: 10 }],
    ['Tactical SATCOM terminal (X-band, dish)', { kind: 'emitter', category: 'comms', freq_mhz: 7950, bw_khz: 5000, eirp_dbm: 70, pattern: 'sector', azimuth: 170, beamwidth: 3, h_agl: 3 }],
    ['UAS datalink (S-band)', { kind: 'emitter', category: 'datalink', freq_mhz: 2350, bw_khz: 5000, eirp_dbm: 40, sens_dbm: -95, js_req_db: 6, h_agl: 5 }],
    ['Ground surveillance radar (X-band)', { kind: 'emitter', category: 'radar', freq_mhz: 9500, bw_khz: 10000, eirp_dbm: 85, pattern: 'sector', beamwidth: 90, h_agl: 6 }],
    ['Air-defence radar (S-band)', { kind: 'emitter', category: 'radar', freq_mhz: 3000, bw_khz: 10000, eirp_dbm: 95, pattern: 'omni', h_agl: 8 }],
    ['Counter-battery radar (S/C-band)', { kind: 'emitter', category: 'radar', freq_mhz: 3300, bw_khz: 5000, eirp_dbm: 88, pattern: 'sector', beamwidth: 90, h_agl: 6 }],
    ['ES/DF site, 20-3000 MHz, mast', { kind: 'sensor', category: 'df', freq_mhz: 20, f_hi_mhz: 3000, sens_dbm: -118, df_rms_deg: 2, h_agl: 15 }],
    ['Airborne ES, 20-18000 MHz', { kind: 'sensor', category: 'df', freq_mhz: 20, f_hi_mhz: 18000, sens_dbm: -115, df_rms_deg: 3, h_agl: 9000 }],
    ['VHF barrage jammer, 20 MHz, 2 kW', { kind: 'effector', category: 'comms', freq_mhz: 45, bw_khz: 20000, eirp_dbm: 63, h_agl: 10 }],
    ['VHF spot jammer, 500 W', { kind: 'effector', category: 'comms', freq_mhz: 45, bw_khz: 25, eirp_dbm: 57, h_agl: 8 }],
    ['GNSS L1 jammer, 10 W', { kind: 'effector', category: 'nav', freq_mhz: 1575.42, bw_khz: 2046, eirp_dbm: 40, h_agl: 3 }],
    ['C-UAS jammer, 2.4 GHz', { kind: 'effector', category: 'cuas', freq_mhz: 2400, bw_khz: 100000, eirp_dbm: 50, h_agl: 5 }],
    ['GPS L1 space signal (net for GNSS users)', { kind: 'emitter', category: 'nav', freq_mhz: 1575.42, bw_khz: 2046, eirp_dbm: null, fixed_level_dbm: -128, js_req_db: 35, sens_dbm: -140 }],
  ];
  const schedTxt = (s) => (s || []).map(([a, b]) => `${a}-${b}`).join(', ');
  const schedParse = (v) => { const out = []; for (const m of (v || '').matchAll(/(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)/g)) out.push([+m[1], +m[2]]); return out.length ? out : null; };
  function emoForm(d) {
    d = d || { side: 'blue', kind: 'emitter', category: 'comms', h_agl: 3, bw_khz: 25, pattern: 'omni', radius_km: 20 };
    const nets = EMO.ents.filter((e) => e.kind === 'emitter');
    return `<div class="specform">${EMO_FIELDS.map(([k, l, t]) => `<label${k === 'name' || k === 'notes' ? ' class="wide"' : ''}>${esc(l)}<input id="emo-${k}" type="${t}" step="any" value="${esc(d[k] ?? '')}"></label>`).join('')}
      <label class="wide">Net (for net users)<select id="emo-net"><option value="">none</option>${nets.map((n) => `<option value="${esc(n.id)}"${d.net === n.id ? ' selected' : ''}>${esc(n.name)} (${n.side})</option>`).join('')}</select></label>
      <label class="wide"><span><input id="emo-active" type="checkbox"${d.active === false ? '' : ' checked'}> On air (untick for EMCON)</span></label>
      <label class="wide">On-air windows, minutes (blank = always), e.g. 0-20, 45-90<input id="emo-sched" value="${esc(schedTxt(d.schedule))}"></label>
      <label class="wide">Template<select id="emo-tpl"><option value="">Apply a template…</option>${EMO_TPL.map(([n], i) => `<option value="${i}">${esc(n)}</option>`).join('')}</select></label>
      <div class="wide dim">Track: ${d.track?.length ? `${d.track.length} waypoint(s)` : 'none'} <button id="emo-trk">Draw track on map</button> <button id="emo-trk-clear">Clear track</button></div>
      <div class="wide btns"><button id="emo-pick">Pick position on map</button> <button id="emo-save" class="primary">${EMO.editId ? 'Update' : 'Add'}</button> <button id="emo-new">New</button>${EMO.editId ? ' <button id="emo-del">Delete</button>' : ''} <span id="emo-err" class="bad"></span></div></div>`;
  }
  function emoRead() {
    const o = { ...(EMO.draft || {}) };
    for (const [k, , t] of EMO_FIELDS) { const v = $(`#emo-${k}`).value.trim(); o[k] = t === 'number' ? (v === '' ? null : Number(v)) : (v || null); }
    o.net = $('#emo-net').value || null; o.active = $('#emo-active').checked; o.schedule = schedParse($('#emo-sched').value);
    return o;
  }
  function emoBody(o) {
    const keep = [...EMO_FIELDS.map(([k]) => k), 'net', 'active', 'track', 'schedule'];
    const b = {}; for (const k of keep) if (o[k] !== null && o[k] !== undefined && o[k] !== '') b[k] = o[k];
    return b;
  }
  function emoResults() {
    const r = EMO.res, out = $('#emo-results'); if (!out || !r) return;
    const fx = r.fixes.filter((f) => f.fix || f.lobs);
    const row = (cells) => `<tr>${cells.map((c) => `<td>${c}</td>`).join('')}</tr>`;
    out.innerHTML = `
      ${r.score ? `<h3 class="sec">Scoreboard</h3><table class="grid"><tr><th></th><th style="color:${SIDE_COL.blue}">Blue</th><th style="color:${SIDE_COL.red}">Red</th></tr>
        ${[['net_availability_pct', 'Net availability %'], ['emitters_exposed', 'Emitters heard by the other side'], ['mean_exposure_db', 'Mean exposure dB'], ['fixed', 'Fixed by the other side'], ['targetable', 'Targetable'], ['denial_achieved', 'Denial achieved (users)'], ['spoofed', 'Spoofed (users)'], ['collateral', 'Civil collateral'], ['net_area_denied_pct', 'Own net area denied %'], ['radar_tracks', 'Radar tracks held'], ['radar_screened', 'Own platforms screened from radar']]
          .map(([k, l]) => `<tr><td>${l}</td>${['blue', 'red'].map((sd) => { const v = r.score[sd][k], pv = EMO.prevScore?.[sd]?.[k]; const d = (typeof v === 'number' && typeof pv === 'number' && v !== pv) ? ` <span class="dim">(${v > pv ? '+' : ''}${Math.round((v - pv) * 10) / 10})</span>` : ''; return `<td class="mono">${v ?? '–'}${d}</td>`; }).join('')}</tr>`).join('')}</table>` : ''}
      ${r.radar?.length ? `<h3 class="sec">Radar: tracks and screening</h3><table class="grid"><tr><th>Radar</th><th>Target</th><th>km</th><th>Echo margin</th><th>Result</th></tr>${r.radar.filter((x) => x.detected || x.jam).map((x) => `<tr><td style="color:${SIDE_COL[x.radar_side]}">${esc(x.radar)}</td><td style="color:${SIDE_COL[x.target_side]}">${esc(x.target)} <span class="dim">${x.rcs_m2} m²</span></td><td class="mono">${x.range_km}</td><td class="mono">${x.margin_db >= 0 ? '+' : ''}${x.margin_db} dB · ${x.p}%</td><td>${x.tracked ? '<b style="color:#45d38a">tracked</b>' : x.screened ? `<b style="color:#dc3cdc">screened</b> by ${esc(x.jam.jammer)} (${esc(x.jam.mode)}, J/S ${x.jam.js_db} dB, burn-through ${x.jam.burnthrough_km} km)` : 'no track'}</td></tr>`).join('')}</table>` : ''}
      <h3 class="sec">ES: what each side can see and fix</h3>
      ${fx.length ? `<table class="grid"><tr><th>Target</th><th>Seen by</th><th>Fix</th></tr>${fx.map((f) => row([`<span style="color:${SIDE_COL[f.target_side]}">${esc(f.target)}</span>`, esc(f.sensors.join(', ')),
        f.fix ? `${f.targetable ? '<b style="color:#ff4646">TARGETABLE</b> ' : ''}±${f.fix.error_m} m, cut ${f.fix.cut_deg}°` : `${f.lobs} line of bearing only`])).join('')}</table>` : '<p class="dim">No DF bearings on any emitter.</p>'}
      <p class="dim">Detections: ${r.detections.filter((d) => d.detected && d.sensor_side === 'red').length} blue emissions heard by red, ${r.detections.filter((d) => d.detected && d.sensor_side === 'blue').length} red emissions heard by blue. Exposure area (ground sensors): blue ${r.exposure.find((x) => x.side === 'blue')?.km2} km², red ${r.exposure.find((x) => x.side === 'red')?.km2} km².</p>
      <h3 class="sec">EA: nets under attack</h3>
      ${r.nets.length ? `<table class="grid"><tr><th>Net</th><th>Coverage</th><th>Denied</th><th>Fails at</th></tr>${r.nets.map((n) => row([`<span style="color:${SIDE_COL[n.side]}">${esc(n.net)}</span>`, n.space ? 'space signal' : `${n.coverage_km2} km²`, `<b>${n.denied_pct}%</b> (${n.denied_km2} km²)`, `J/S ${n.js_req_db} dB`])).join('')}</table>` : ''}
      ${r.jamming.length ? `<table class="grid"><tr><th>Effector</th><th>Victim</th><th>J/S</th><th>Result</th></tr>${r.jamming.map((j) => row([esc(j.effector), esc(j.victim), `${j.js_db} dB`, `<b style="color:${j.status === 'denied' ? '#dc3cdc' : j.status === 'holds' ? '#45d38a' : '#8593a6'}">${esc(j.status)}</b>`])).join('')}</table>` : '<p class="dim">No EA against any net.</p>'}
      <p class="dim">${esc(r.notes)}</p>`;
  }
  async function openEMO() {
    try { if (!EMO.examples) EMO.examples = (await api('/api/emo/examples')).examples; await emoLoad(); EMO.scen = (await api('/api/emo/scenarios')).scenarios; } catch (err) { return openModal('EMO', `<p class="bad">${esc(err.message)}</p>`); }
    const list = EMO.ents.length ? `<table class="grid"><tr><th>Entity</th><th>Role</th><th>MHz</th><th></th></tr>${EMO.ents.map((e) => `<tr class="${e.id === EMO.editId ? 'sel' : ''}"><td style="color:${SIDE_COL[e.side]}">${esc(e.name)}${e.active || e.kind === 'sensor' || e.kind === 'receiver' ? '' : ' <span class="dim">(off-air)</span>'}</td><td class="dim">${esc(KIND_TXT[e.kind])}${e.category ? ' · ' + esc(e.category) : ''}</td><td class="mono">${e.freq_mhz}${e.f_hi_mhz ? '–' + e.f_hi_mhz : ''}</td><td><button data-emo-edit="${esc(e.id)}">Edit</button></td></tr>`).join('')}</table>` : '<p class="dim">No entities: load an example.</p>';
    const H = Math.max(EMO.horizon, 0);
    openModal('EMO: red / blue in the spectrum', `<p class="dim">Notional scenarios. ES: who can hear and fix whom. EA: whose nets are denied. EP: EMCON, siting, antennas. Drag units on the map at T+0.</p>
      <div class="specset"><select id="emo-ex"><option value="">Load example…</option>${EMO.examples.map((x) => `<option value="${esc(x.id)}">${esc(x.title)}</option>`).join('')}</select> <button id="emo-ex-go">Load</button></div>
      ${EMO.about ? `<p class="dim">${esc(EMO.about)}</p>` : ''}
      <div class="specset">Save current as <input id="emo-sc-name" placeholder="scenario name" style="width:180px"> <button id="emo-sc-save">Save</button>
        ${(EMO.scen || []).map((x) => `<span style="white-space:nowrap">${esc(x.name)} <span class="dim">(${x.entities})</span> <button data-sc-load="${esc(x.id)}">Load</button><button data-sc-del="${esc(x.id)}">×</button></span>`).join(' ')}</div>
      <div class="specset">Time T+<b id="emo-tv">${Math.round(EMO.t)}</b> min <input id="emo-t" type="range" min="0" max="${Math.max(1, Math.ceil(H))}" step="1" value="${EMO.t}" style="flex:1;min-width:140px">
        <button id="emo-run" class="primary">Run</button> <button id="emo-play">${EMO.playing ? 'Stop' : 'Play'}</button> <span id="emo-status" class="dim"></span></div>
      <div class="specset">${EMO_LAYERS.map(([k, l, c]) => `<label style="white-space:nowrap"><input type="checkbox" data-emo-layer="${k}"${EMO.on[k] ? ' checked' : ''}> <span style="color:${c}">■</span> ${esc(l)}</label>`).join(' ')}</div>
      <div class="specset">Targetable if fix within <input id="emo-tgt" type="number" min="50" step="50" value="${EMO.params.df_fix_good_m}" style="width:80px"> m
        <span class="dim">(tactical ~1000, operational ~5000)</span> · <span class="dim">Map washes are for ground receivers (2 m); airborne results are in the cards and tables.</span></div>
      <div class="specset"><input id="emo-askq" placeholder="Ask about this scenario, e.g. which blue emitter is most at risk?" style="flex:1;min-width:200px"> <button id="emo-ask">Ask AI</button></div>
      <div id="emo-askout" class="md"></div>
      <div class="specset">Briefing phases (minutes) <input id="emo-phases" value="0, ${Math.round((EMO.horizon || 0) / 2)}, ${Math.round(EMO.horizon || 0)}" style="width:120px">
        <a id="emo-export" class="btnlink" href="#">Export briefing (Word)</a> <span class="dim">one section per phase; takes a minute per new phase</span></div>
      <div class="specset">Scenario space: <select id="emo-ws"><option value="default"${wsId() === 'default' ? ' selected' : ''}>Shared (all devices)</option><option value="device"${wsId() !== 'default' ? ' selected' : ''}>This device only</option></select>
        <span class="dim">Courses of action:</span> <input id="emo-coaname" placeholder="COA name" style="width:120px"> <button id="emo-coasave">Save current as COA</button></div>
      <div id="emo-coalist"></div>
      <div class="specset">Timeline: step <input id="emo-tlstep" type="number" value="10" min="1" style="width:56px"> min, windows for <select id="emo-tlnet"><option value="">(none)</option>${EMO.ents.filter((e) => e.kind === 'emitter' && e.fixed_level_dbm == null && EMO.ents.some((u) => u.net === e.id)).map((e) => `<option${e.name === EMO.tlNet ? ' selected' : ''}>${esc(e.name)}</option>`).join('')}</select>
        <button id="emo-tl">Run timeline</button> <span id="emo-tlstatus" class="dim"></span></div>
      <div id="emo-tlout"></div>
      <div class="specset">Other side's response: <select id="emo-coaside"><option value="red">Red</option><option value="blue">Blue</option></select>
        <button id="emo-coa-ml" title="Most likely: at most two modest moves">MLCOA</button> <button id="emo-coa-md" title="Most dangerous: every jammer and DF site re-sited for effect">MDCOA</button>
        <button id="emo-coa-rev">Revert</button> <span id="emo-coaout" class="dim"></span></div>
      <div id="emo-results"></div>
      <h3 class="sec">Entities</h3>${list}
      <h3 class="sec">${EMO.editId ? 'Edit entity' : 'Add entity'}</h3>${emoForm(EMO.draft)}`);
    emoResults();
    const body = $('#modal-body');
    const coa = async (kind) => {
      const side = $('#emo-coaside').value, o = $('#emo-coaout');
      o.innerHTML = '<span class="spinner"></span> generating and applying…';
      try {
        const r = kind === 'revert' ? await postJson(`/api/emo/plan/coa/revert?side=${side}&t_min=${EMO.t}`, {}) : await postJson(`/api/emo/plan/coa?t_min=${EMO.t}`, { side, coa: kind });
        planLayer.clearLayers();
        (r.moves || []).forEach((m) => { L.polyline([m.from, m.to], { color: SIDE_COL[side], weight: 3, dashArray: '6 6' }).bindTooltip(`${esc(m.entity)} → ${esc(m.where)}<br>${esc(m.detail)}`).addTo(planLayer); });
        o.innerHTML = kind === 'revert' ? `reverted ${r.reverted} positions` : (r.moves.length ? `${r.coa.toUpperCase()} against ${esc(r.target)}: ${r.moves.map((m) => `<b>${esc(m.entity)}</b> ${esc(m.where)} (${esc(m.detail)})`).join('; ')}` : `${r.coa.toUpperCase()}: no move clearly improves ${side}'s laydown`);
        await emoLoad(); EMO.prevScore = r.score_before || EMO.prevScore; EMO.res = null; await emoRun();
      } catch (err) { o.innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
    };
    $('#emo-ws').addEventListener('change', async (e) => { localStorage.setItem('cyem-ws-mode', e.target.value === 'device' ? 'device' : 'shared'); EMO.res = null; EMO.ents = []; emoClearFocus(); await openEMO(); });
    const coaList = async () => {
      const box = $('#emo-coalist'); if (!box) return;
      try {
        const r = await api('/api/emo/coas');
        if (!r.coas.length) { box.innerHTML = ''; return; }
        const keys = [['net_availability_pct', 'Avail %'], ['targetable', 'Targetable'], ['denial_achieved', 'Denied (users)'], ['collateral', 'Collateral'], ['net_area_denied_pct', 'Area denied %']];
        const cell = (sc, sd, k) => sc?.[sd]?.[k] ?? '–';
        const rowOf = (name, sc, ctl) => `<tr><td>${name}</td>${['blue', 'red'].map((sd) => keys.map(([k]) => `<td class="mono" style="color:${SIDE_COL[sd]}">${cell(sc, sd, k)}</td>`).join('')).join('')}<td>${ctl}</td></tr>`;
        box.innerHTML = `<table class="grid"><tr><th>COA</th>${['Blue', 'Red'].map((sd) => keys.map(([, l]) => `<th style="color:${SIDE_COL[sd.toLowerCase()]}">${sd} ${l}</th>`).join('')).join('')}<th></th></tr>
          ${r.current ? rowOf('<i>current</i>', r.current, '') : ''}
          ${r.coas.map((c) => rowOf(esc(c.name), c.score, `<button data-coa-load="${c.id}">Load</button> <button data-coa-del="${c.id}">×</button>`)).join('')}</table>`;
        box.querySelectorAll('[data-coa-load]').forEach((b) => b.addEventListener('click', async () => {
          const r2 = await postJson(`/api/emo/coas/${b.dataset.coaLoad}/load`, {}); EMO.ents = r2.entities; EMO.res = null; if (r2.t_min != null) EMO.t = r2.t_min; if (r2.params) EMO.params = { ...EMO.params, ...r2.params }; emoClearFocus(); await openEMO(); emoRun();
        }));
        box.querySelectorAll('[data-coa-del]').forEach((b) => b.addEventListener('click', async () => { await fetch(`/api/emo/coas/${b.dataset.coaDel}`, { method: 'DELETE' }); coaList(); }));
      } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    };
    coaList();
    $('#emo-coasave').addEventListener('click', async () => {
      const name = $('#emo-coaname').value.trim() || `COA ${new Date().toISOString().slice(11, 16)}Z`;
      try { await postJson('/api/emo/coas', { name }); $('#emo-coaname').value = ''; coaList(); } catch (e) { emoStatus(e.message); }
    });
    $('#emo-tl').addEventListener('click', async () => {
      const out = $('#emo-tlout'), st = $('#emo-tlstatus'); EMO.tlNet = $('#emo-tlnet').value || null;
      const t0 = Date.now(); const tick = setInterval(() => { st.textContent = `stepping… ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
      try {
        const r = await postJson('/api/emo/plan/timeline', { step_min: +$('#emo-tlstep').value || 10, net: EMO.tlNet });
        clearInterval(tick); st.textContent = `${r.steps.length} steps to T+${r.horizon_min} min`;
        const names = Object.keys(r.rows).filter((n) => r.rows[n].tracked || r.rows[n].heard.some(Boolean) || r.rows[n].denied.some(Boolean))
          .sort((a, b) => (r.rows[a].side + a).localeCompare(r.rows[b].side + b));
        const W = 680, lab = 150, cw = Math.max(6, Math.floor((W - lab - 10) / r.steps.length)), rh = 14, H = 20 + names.length * rh;
        const cell = (row, i) => row.denied[i] ? '#dc3cdc' : row.targetable[i] ? '#ff4646' : row.heard[i] ? '#f3b23e' : '#45d38a';
        const svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0b1016;border-radius:6px;font:10px sans-serif">
          ${r.steps.map((s, i) => i % Math.ceil(r.steps.length / 8) === 0 ? `<text x="${lab + i * cw}" y="12" fill="#8593a6">T+${s}</text>` : '').join('')}
          ${names.map((n, k) => `<text x="4" y="${20 + k * rh + 10}" fill="${SIDE_COL[r.rows[n].side] || '#aaa'}">${esc(n.slice(0, 24))}</text>` +
            r.steps.map((s, i) => `<rect x="${lab + i * cw}" y="${20 + k * rh + 2}" width="${cw - 1}" height="${rh - 3}" fill="${cell(r.rows[n], i)}"><title>${esc(n)} T+${s}: ${r.rows[n].denied[i] ? 'denied' : r.rows[n].targetable[i] ? 'targetable' : r.rows[n].heard[i] ? 'heard by ' + esc(r.rows[n].heard_by[i].join(', ')) : 'clear'}</title></rect>`).join('')).join('')}</svg>`;
        const w = r.windows;
        out.innerHTML = `<p><span style="color:#45d38a">■</span> clear <span style="color:#f3b23e">■</span> heard <span style="color:#ff4646">■</span> targetable <span style="color:#dc3cdc">■</span> denied</p>${svg}
          ${w ? `<h4>Advantage windows for ${esc(w.net)}</h4><p>${esc(w.summary)}</p>${w.advantage.length ? `<p>Unheard and undenied: ${w.advantage.map((x) => `T+${x.from_min}–${x.to_min} min`).join(', ')}</p>` : '<p class="bad">No step where the control station is unheard and all users are undenied: siting alone gives no window; use EMCON or another bearer.</p>'}` : ''}
          <p class="dim">${esc(r.notes)}</p>`;
      } catch (err) { clearInterval(tick); st.innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
    });
    $('#emo-coa-ml').addEventListener('click', () => coa('mlcoa'));
    $('#emo-coa-md').addEventListener('click', () => coa('mdcoa'));
    $('#emo-coa-rev').addEventListener('click', () => coa('revert'));
    $('#emo-tgt').addEventListener('change', (e) => { EMO.params.df_fix_good_m = Math.max(50, +e.target.value || 1000); emoRun(); });
    $('#emo-export').addEventListener('click', (e) => {
      e.preventDefault();
      const ph = $('#emo-phases').value.split(/[,\s]+/).filter((x) => x !== '' && !isNaN(+x)).join(',') || '0';
      emoStatus('Building briefing… (download starts when ready)');
      window.location.href = `/api/emo/export.docx?phases=${encodeURIComponent(ph)}&df_fix_good_m=${EMO.params.df_fix_good_m}`;
    });
    $('#emo-ask').addEventListener('click', async () => {
      const q = $('#emo-askq').value.trim(); if (q.length < 2) return;
      const out = $('#emo-askout'); out.innerHTML = '<span class="spinner"></span> thinking… (about a minute)';
      let text = '';
      try {
        const r = await fetch('/api/emo/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) });
        const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
        while (true) {
          const { value, done } = await rd.read(); if (done) break;
          buf += dec.decode(value, { stream: true }); const parts = buf.split('\n\n'); buf = parts.pop();
          for (const p of parts) { const l = p.split('\n').find((x) => x.startsWith('data: ')); if (!l) continue; const d = JSON.parse(l.slice(6));
            if (d.t) { text += d.t; out.textContent = text; } if (d.error) out.innerHTML = `<p class="bad">${esc(d.error)}</p>`; }
        }
        if (text) out.innerHTML = renderMd(text);
      } catch (err) { out.innerHTML = `<p class="bad">${esc(err.message)}</p>`; }
    });
    $('#emo-ex-go').addEventListener('click', async () => {
      const id = $('#emo-ex').value; if (!id) return;
      emoStatus('loading…');
      try {
        const r = await postJson(`/api/emo/examples/${encodeURIComponent(id)}`, {});
        EMO.ents = r.entities; EMO.about = r.about; EMO.params = { rx_h: 2, js_req_db: 0, df_fix_good_m: 1000, ...(r.params || {}) }; EMO.t = 0; EMO.res = null; EMO.editId = null; EMO.draft = null;
        map.setView(r.centre, r.zoom); emoDraw(); await openEMO(); emoRun();
      } catch (err) { emoStatus(err.message); }
    });
    $('#emo-t').addEventListener('input', (e) => { EMO.t = +e.target.value; $('#emo-tv').textContent = EMO.t; });
    $('#emo-t').addEventListener('change', () => emoRun());
    $('#emo-run').addEventListener('click', () => emoRun());
    $('#emo-play').addEventListener('click', async () => {
      EMO.playing = !EMO.playing; $('#emo-play').textContent = EMO.playing ? 'Stop' : 'Play';
      const step = Math.max(1, Math.round(Math.max(EMO.horizon, 10) / 12));
      while (EMO.playing && EMO.t < Math.max(EMO.horizon, 1)) {
        EMO.t = Math.min(EMO.t + step, Math.ceil(EMO.horizon)); const tv = $('#emo-tv'), ts = $('#emo-t'); if (tv) tv.textContent = EMO.t; if (ts) ts.value = EMO.t;
        await emoRun();
      }
      EMO.playing = false; const pb = $('#emo-play'); if (pb) pb.textContent = 'Play';
    });
    body.querySelectorAll('input[data-emo-layer]').forEach((cb) => cb.addEventListener('change', () => { EMO.on[cb.dataset.emoLayer] = cb.checked; emoDraw(); }));
    body.querySelectorAll('button[data-emo-edit]').forEach((b) => b.addEventListener('click', () => { EMO.editId = b.dataset.emoEdit; EMO.draft = { ...EMO.ents.find((e) => e.id === EMO.editId) }; openEMO(); }));
    $('#emo-new').addEventListener('click', () => { EMO.editId = null; EMO.draft = null; openEMO(); });
    $('#emo-tpl').addEventListener('change', (ev) => { const tp = EMO_TPL[+ev.target.value]; if (!tp) return; const cur = emoRead();
      EMO.draft = { ...cur, ...tp[1], name: cur.name || tp[0], side: cur.side || 'blue' }; openEMO(); });
    $('#emo-sc-save').addEventListener('click', async () => { const nm = $('#emo-sc-name').value.trim(); if (!nm) return;
      try { await postJson('/api/emo/scenarios', { name: nm }); openEMO(); } catch (err) { emoStatus(err.message); } });
    body.querySelectorAll('button[data-sc-load]').forEach((b) => b.addEventListener('click', async () => {
      await postJson(`/api/emo/scenarios/${b.dataset.scLoad}/load`, {}); EMO.res = null; EMO.focus = null; document.getElementById('emo-card')?.remove(); EMO.t = 0; await openEMO(); emoDraw(); emoRun(); }));
    body.querySelectorAll('button[data-sc-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this saved scenario?')) return; await fetch(`/api/emo/scenarios/${b.dataset.scDel}`, { method: 'DELETE' }); openEMO(); }));
    $('#emo-del')?.addEventListener('click', async () => {
      if (!confirm('Delete this entity?')) return;
      await fetch(`/api/emo/${encodeURIComponent(EMO.editId)}`, { method: 'DELETE' }); EMO.editId = null; EMO.draft = null; await openEMO(); emoRun();
    });
    $('#emo-pick').addEventListener('click', () => {
      EMO.draft = emoRead(); $('#modal').classList.remove('show'); showSide(false); if (mobile()) showRail(false);
      map.getContainer().style.cursor = 'crosshair';
      map.once('click', (ev) => { map.getContainer().style.cursor = ''; EMO.draft.lat = +ev.latlng.lat.toFixed(5); EMO.draft.lon = +ev.latlng.lng.toFixed(5); openEMO(); });
    });
    $('#emo-trk-clear').addEventListener('click', () => { EMO.draft = { ...emoRead(), track: null }; openEMO(); });
    $('#emo-trk').addEventListener('click', () => {
      EMO.draft = emoRead(); if (EMO.draft.lat == null) { $('#emo-err').textContent = 'Set a position first'; return; }
      const pts = []; const tmp = L.polyline([[EMO.draft.lat, EMO.draft.lon]], { color: SIDE_COL[EMO.draft.side] || '#fff', dashArray: '6 6' }).addTo(map);
      $('#modal').classList.remove('show'); map.getContainer().style.cursor = 'crosshair';
      const bar = document.createElement('div'); bar.className = 'emo-trackbar';
      bar.innerHTML = '<span>Tap the map to add waypoints</span> <button class="primary">Finish track</button> <button>Cancel</button>';
      document.body.appendChild(bar);
      const add = (ev) => { pts.push([+ev.latlng.lat.toFixed(5), +ev.latlng.lng.toFixed(5)]); tmp.addLatLng(ev.latlng); bar.firstChild.textContent = `${pts.length} waypoint(s)`; };
      map.on('click', add);
      const done = (keep) => { map.off('click', add); map.removeLayer(tmp); bar.remove(); map.getContainer().style.cursor = '';
        if (keep && pts.length) { EMO.draft.track = pts; if (!EMO.draft.speed_kmh) EMO.draft.speed_kmh = 20; } openEMO(); };
      bar.querySelectorAll('button')[0].addEventListener('click', () => done(true));
      bar.querySelectorAll('button')[1].addEventListener('click', () => done(false));
    });
    $('#emo-save').addEventListener('click', async () => {
      const o = emoRead();
      try {
        const r = await postJson(EMO.editId ? `/api/emo/${encodeURIComponent(EMO.editId)}` : '/api/emo', emoBody(o), EMO.editId ? 'PUT' : 'POST');
        EMO.editId = r.id; EMO.draft = { ...r }; await openEMO(); emoRun();
      } catch (err) { $('#emo-err').textContent = err.message; }
    });
    if (EMO.res) emoDraw();
  }
  $('#btn-emo').addEventListener('click', () => openEMO());
  // ---------------------------------------------------------------- SDR nodes (live receiver + sweeps)
  const SDR = { node: null, timer: null };
  const TIER_COL = { accounted: '#45d38a', unsure: '#f3b23e', unaccounted: '#ff4646' };
  const TIER_TXT = { accounted: 'Accounted for', unsure: 'Unsure', unaccounted: 'Not accounted for' };
  function sdrChart(l) {
    const W = 680, H = 190, P = 28, n = l.db.length;
    const lo = Math.min(...l.db), hi = Math.max(...l.db), span = Math.max(10, hi - lo);
    const x = (i) => P + (i / (n - 1)) * (W - P - 6), y = (v) => H - 18 - ((v - lo) / span) * (H - 30);
    const f = (i) => (l.f0_hz + i * l.bin_hz) / 1e6;
    let d = ''; l.db.forEach((v, i) => { d += `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
    const ticks = [50, 100, 200, 400, 800, 1200, 1600].filter((t) => t > f(0) && t < f(n - 1))
      .map((t) => { const i = (t * 1e6 - l.f0_hz) / l.bin_hz; return `<line x1="${x(i)}" x2="${x(i)}" y1="10" y2="${H - 18}" stroke="#243040"/><text x="${x(i)}" y="${H - 4}" fill="#8593a6" font-size="10" text-anchor="middle">${t}</text>`; }).join('');
    const pk = (l.peaks || []).slice(0, 25).map((p) => { const i = (p.f_hz - l.f0_hz) / l.bin_hz; return `<circle cx="${x(i)}" cy="${y(p.level_db)}" r="4" fill="${TIER_COL[p.tier] || '#f3b23e'}" stroke="#0b1016"><title>${(p.f_hz / 1e6).toFixed(3)} MHz · ${p.level_db} dB · SNR ${p.snr_db} dB</title></circle>`; }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0b1016;border-radius:6px">${ticks}<path d="${d}" fill="none" stroke="#3cc8ff" stroke-width="1.2"/>${pk}
      <text x="${P}" y="12" fill="#8593a6" font-size="10">${hi.toFixed(0)} dB</text><text x="${P}" y="${H - 20}" fill="#8593a6" font-size="10">${lo.toFixed(0)} dB</text><text x="${W - 6}" y="${H - 4}" fill="#8593a6" font-size="10" text-anchor="end">MHz</text></svg>`;
  }
  async function openSDR() {
    let nodes = [];
    try { nodes = (await api('/api/sdr/nodes')).nodes; } catch (e) { return openModal('SDR', `<p class="bad">${esc(e.message)}</p>`); }
    if (!nodes.length) return openModal('SDR receivers', '<p>No SDR node has reported yet. Set up the Raspberry Pi with <span class="mono">pi/setup.sh</span> (see <span class="mono">pi/README.md</span>); it appears here after its first sweep.</p>');
    SDR.node = SDR.node && nodes.some((n) => n.node === SDR.node) ? SDR.node : nodes[0].node;
    const n = nodes.find((x) => x.node === SDR.node);
    const age = n.last_seen ? Math.round((Date.now() - Date.parse(n.last_seen)) / 60000) : null;
    let body = `<div class="specset"><select id="sdr-node">${nodes.map((x) => `<option${x.node === SDR.node ? ' selected' : ''}>${esc(x.node)}</option>`).join('')}</select>
      <span class="${age != null && age < 10 ? 'good' : 'bad'}">${age == null ? 'never seen' : age < 10 ? `online, last sweep ${age} min ago` : `last seen ${age} min ago`}</span>
      ${n.url ? `<a class="btnlink" href="${esc(n.url)}">Open live receiver</a>` : ''} <button id="sdr-pos">Set receiver position to this device</button> <button id="sdr-ins">Insight (AI)</button></div><div id="sdr-insout" class="md"></div>
      <p class="dim">Position: ${n.lat != null ? `${n.lat.toFixed(4)}, ${n.lon.toFixed(4)} (${fmtZ(n.pos_at)})` : 'not set'} · ${n.sweeps} sweeps stored. Spectrum occupancy only; nothing is demodulated or recorded.</p>
      <div id="sdr-out"><span class="spinner"></span></div>`;
    openModal('SDR receivers', body);
    $('#sdr-node').addEventListener('change', (e) => { SDR.node = e.target.value; openSDR(); });
    $('#sdr-ins').addEventListener('click', async () => {
      const o = $('#sdr-insout'); o.innerHTML = '<span class="spinner"></span> reading the spectrum… (about a minute)';
      try { const r = await api(`/api/insight/sdr?node=${encodeURIComponent(SDR.node)}`); o.innerHTML = renderMd(r.text); }
      catch (e) { o.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    });
    $('#sdr-pos').addEventListener('click', () => {
      if (!navigator.geolocation) return toastSDR('No location on this device');
      navigator.geolocation.getCurrentPosition(async (p) => {
        try { await postJson(`/api/sdr/nodes/${encodeURIComponent(SDR.node)}/position`, { lat: +p.coords.latitude.toFixed(5), lon: +p.coords.longitude.toFixed(5) }); openSDR(); }
        catch (e) { toastSDR(e.message); }
      }, (e) => toastSDR(`Location: ${e.message}`), { enableHighAccuracy: true, timeout: 15000 });
    });
    try {
      const l = await api(`/api/sdr/latest?node=${encodeURIComponent(SDR.node)}`);
      let c = null; try { c = await api(`/api/sdr/correlate?node=${encodeURIComponent(SDR.node)}`); } catch (e) { /* no position yet */ }
      if (c) { const byF = Object.fromEntries(c.peaks.map((p) => [p.f_hz, p])); l.peaks = l.peaks.map((p) => byF[p.f_hz] || p); }
      const T = c?.tiers || {};
      const who = (p) => p.licences?.length ? `${esc(p.licences[0].who)}, ${esc(p.licences[0].what || '')}` + (p.licence_count > 1 ? ` <span class="dim">+${p.licence_count - 1} more</span>` : '') : esc(p.band || p.label || '');
      const where = (p) => p.licences?.length ? `${p.licences[0].dist_km} km at ${p.licences[0].bearing}°` : (p.context ? esc(p.context) : '');
      $('#sdr-out').innerHTML = `<p class="dim">Sweep ${fmtZ(l.ts)} · ${(l.f0_hz / 1e6).toFixed(0)}–${((l.f0_hz + l.bin_hz * l.db.length) / 1e6).toFixed(0)} MHz · max-hold per ${(l.bin_hz / 1e3).toFixed(0)} kHz</p>${sdrChart(l)}
        ${c ? `<p>${['accounted', 'unsure', 'unaccounted'].map((k) => `<span style="color:${TIER_COL[k]}">●</span> ${TIER_TXT[k]} <b>${T[k] || 0}</b>`).join(' &nbsp; ')}</p>` : '<p class="bad">Set the receiver position to correlate peaks with licences.</p>'}
        <h3 class="sec">Signals (${l.peaks.length})</h3><table class="grid"><tr><th></th><th>MHz</th><th>SNR</th><th>Who / what</th><th>Where</th></tr>
        ${l.peaks.slice(0, 40).map((p) => `<tr title="${esc(p.tier_why || p.status_text || '')}"><td><span style="color:${TIER_COL[p.tier] || '#8593a6'};font-size:16px">●</span></td><td class="mono">${(p.f_hz / 1e6).toFixed(3)}</td><td class="mono">${p.snr_db}</td><td>${who(p)}<div class="dim">${esc(p.tier_why || '')}</div></td><td>${where(p)}</td></tr>`).join('')}</table>
        <p class="dim">${esc(c?.notes || 'Levels are relative dB (not calibrated). Peaks are carriers at least 10 dB above the local floor.')}</p>`;
    } catch (e) { $('#sdr-out').innerHTML = `<p class="dim">${esc(e.message)}</p>`; }
  }
  function toastSDR(t) { const o = $('#sdr-out'); if (o) o.insertAdjacentHTML('afterbegin', `<p class="bad">${esc(t)}</p>`); }
  $('#btn-sdr').addEventListener('click', () => openSDR());
  // ---------------------------------------------------------------- panels / mobile
  const mobile = () => window.matchMedia('(max-width: 900px)').matches;
  const panels = (() => { try { return { rail: false, side: false, ...JSON.parse(localStorage.getItem('cyem.panels') || '{}') }; } catch { return { rail: false, side: false }; } })();
  function showRail(on, remember = true) { $('#rail').classList.toggle('hidden', !on); $('#btn-rail').classList.toggle('active', on); if (remember && !mobile()) { panels.rail = on; saveLs('cyem.panels', panels); } setTimeout(() => map.invalidateSize(), 50); }
  function showSide(on, remember = true) { $('#side').classList.toggle('hidden', !on); $('#btn-side').classList.toggle('active', on); if (remember && !mobile()) { panels.side = on; saveLs('cyem.panels', panels); } setTimeout(() => map.invalidateSize(), 50); }
  $('#btn-rail').addEventListener('click', () => showRail($('#rail').classList.contains('hidden')));
  $('#btn-side').addEventListener('click', () => showSide($('#side').classList.contains('hidden')));
  $$('#mobnav button[data-view]').forEach((b) => b.addEventListener('click', () => {
    $$('#mobnav button[data-view]').forEach((x) => x.classList.toggle('active', x === b));
    showRail(b.dataset.view === 'rail'); showSide(b.dataset.view === 'side');
    if (b.dataset.view === 'map') setTimeout(() => map.invalidateSize(), 250);
  }));
  // Phone layout hides the top-bar buttons; the Tools sheet exposes the same actions.
  const MOB_TOOLS = [['btn-spec', 'Spectrum', 'Planned emitters, conflicts, export'], ['btn-links', 'Links', 'Point-to-point link planner'],
    ['btn-cov', 'Coverage', 'Omni / sector / P2MP coverage'], ['btn-hf', 'HF', 'Skywave now-cast'], ['btn-emo', 'EMO', 'Red / blue ES, EA and EP'], ['btn-sdr', 'SDR', 'Live receiver and spectrum sweeps'], ['btn-health', 'Health', 'Collectors and data status']];
  $('#mob-tools').addEventListener('click', () => {
    openModal('Tools', `<div class="mobtools">${MOB_TOOLS.filter(([id]) => $('#' + id)).map(([id, t, d]) => `<button data-go="${id}"><b>${t}</b><span class="dim">${d}</span></button>`).join('')}
      ${window.webkit?.messageHandlers?.cyem ? '<button data-native="ar"><b>AR view (camera)</b><span class="dim">Emitters around you over the camera image</span></button>' : ''}
      <a href="/api/export/plan.docx" class="btnlink" download><b>Export plan (Word)</b></a></div>`);
    $$('#modal-body .mobtools button').forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.native) { $('#modal').classList.remove('show'); window.webkit.messageHandlers.cyem.postMessage(b.dataset.native); }
      else $('#' + b.dataset.go).click();
    }));
  });
  if (mobile()) { showRail(false, false); showSide(false, false); } else { showRail(panels.rail, false); showSide(panels.side, false); }

  // ---------------------------------------------------------------- refresh loops
  async function refreshStatus() {
    try { state.status = await api('/api/status'); renderPills(state.status); } catch (e) { console.warn(e); }
  }
  function tickClock() { const d = new Date(); $('#clock').textContent = d.toISOString().slice(11, 16) + 'Z · ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + ' local'; }
  tickClock(); setInterval(tickClock, 15000);
  refreshStatus(); loadFeed(); loadBrief(); pollBrief(); loadLayers();
  let minute = 0;
  setInterval(refreshStatus, 60000);
  setInterval(loadFeed, 150000);
  setInterval(() => { minute += 1; loadLayers(minute); }, 60000);
})();
