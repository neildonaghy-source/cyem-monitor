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
      if (!armConfirm(b)) return;
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
