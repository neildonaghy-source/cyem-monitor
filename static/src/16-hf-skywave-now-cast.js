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
      hfRead(); $('#modal').classList.remove('show');
      pickOnMap(`end ${end.toUpperCase()} of the HF path`, (e) => { hfDraft[`${end}_lat`] = +e.latlng.lat.toFixed(4); hfDraft[`${end}_lon`] = +e.latlng.lng.toFixed(4); openHF(); }, () => openHF());
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
