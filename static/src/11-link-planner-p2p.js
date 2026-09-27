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
  async function postJson(path, body, method = 'POST', signal = undefined) {
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
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
      if (!armConfirm(b)) return;
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
