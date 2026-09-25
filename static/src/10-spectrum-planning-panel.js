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
