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
