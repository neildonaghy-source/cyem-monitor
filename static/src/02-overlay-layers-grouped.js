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
    layerCtl.innerHTML = `<h3><span>Map layers <span class="dim" style="letter-spacing:0;text-transform:none">build ${BUILD}</span></span><a href="#" id="layers-toggle">hide</a></h3>`;
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
    $('#layers-toggle').addEventListener('click', (e) => { e.preventDefault(); layerCtl.classList.toggle('collapsed'); e.target.textContent = layerCtl.classList.contains('collapsed') ? 'show' : 'hide'; localStorage.setItem('cyem-layers', layerCtl.classList.contains('collapsed') ? 'hide' : 'show'); });
    if (localStorage.getItem('cyem-layers') === 'hide' || (matchMedia('(max-width: 900px)').matches && !localStorage.getItem('cyem-layers'))) { layerCtl.classList.add('collapsed'); $('#layers-toggle').textContent = 'show'; }
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

