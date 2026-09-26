  // ---------------------------------------------------------------- EMO red / blue (notional scenarios)
  const EMO = { ents: [], res: null, t: 0, horizon: 0, params: { rx_h: 2, js_req_db: 0, df_fix_good_m: 1000 }, draft: null, editId: null,
    playing: false, busy: false, pending: false, stale: false, started: 0, examples: null, about: '',
    on: { blue_seen: false, red_seen: false, blue_denied: false, red_denied: false, blue_cov: false, red_cov: false, lines: true, civil_lines: false },
    focus: null, focusRes: null, multi: false, sel: [], multiRes: {}, pairRes: {}, side: localStorage.getItem('cyem-side') || 'blue' };
  const emoLayer = L.layerGroup().addTo(map);
  const planLayer = L.layerGroup().addTo(map);
  const SIDE_COL = { blue: '#3c8cff', red: '#ff4646', grey: '#a6b0bd' };
  const EMO_LAYERS = [['blue_seen', 'Blue emissions red can hear', '#ff4646'], ['red_seen', 'Red emissions blue can hear', '#3cc8ff'],
    ['blue_denied', 'Blue nets denied', '#dc3cdc'], ['red_denied', 'Red nets denied', '#ffa028'], ['blue_cov', 'Blue net coverage', '#3c8cff'],
    ['red_cov', 'Red net coverage', '#ff5a5a'], ['grey_seen', 'Civil emissions heard', '#c8ccd4'], ['grey_denied', 'Civil users denied (collateral)', '#ffffff'], ['civil_lines', 'Lines to civil emitters', '#a6b0bd'], ['lines', 'Detections, bearings, J/S lines', '#c8d3e0']];
  const KIND_TXT = { emitter: 'Emitter', receiver: 'Outstation', sensor: 'ES sensor', effector: 'EA effector' };
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
          .bindTooltip(`${f.targetable ? 'TARGET-QUALITY FIX' : 'Fix'}: ${esc(f.target)} ±${f.fix.error_m} m (cut ${f.fix.cut_deg}°, ${esc(f.fix.sensors.join(' + '))})`, { direction: 'top' }).addTo(emoLayer);
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
        ? `${x.users_closed}/${x.of_users} outstations linked · margin ${x.link_margin_db >= 0 ? '+' : ''}${x.link_margin_db} dB · ${x.heard_by.length ? `detected by ${x.heard_by.length}` : 'not detected'} · J/S ${x.worst_js_db} dB`
        : `denies ${x.denied}/${x.of_users} · worst J/S ${x.min_js_db} dB · exposure ${x.exposure_db >= 0 ? '+' : ''}${x.exposure_db} dB${x.fratricide ? ` · <b class="bad">fratricide ${x.fratricide}</b>` : ''}`;
      r.best.slice(0, 3).forEach((x, i) => {
        L.polyline([cur, [x.lat, x.lon]], { color: '#45d38a', weight: 2, dashArray: '5 6', opacity: 0.8, interactive: false }).addTo(planLayer);
        L.marker([x.lat, x.lon], { icon: L.divIcon({ className: 'emo-planpin', html: `${i + 1}`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
          .bindTooltip(`Option ${i + 1}: ${x.where}<br>${fmt(x)}`).addTo(planLayer);
      });
      if (r.relay) L.marker([r.relay.lat, r.relay.lon], { icon: L.divIcon({ className: 'emo-planpin emo-relay', html: 'R', iconSize: [22, 22], iconAnchor: [11, 11] }) })
        .bindTooltip(`Relay: ${r.relay.where}<br>reaches ${r.relay.reaches}/${r.relay.of_failing} (${esc(r.relay.serves.join(', '))})`).addTo(planLayer);
      out.innerHTML = `<h4>${kind === 'net' ? 'EP siting for this net' : `EA siting to deny ${esc(r.target_net)}`}</h4>
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
      out.innerHTML = `<h4>EP measures at the current position</h4>
        <p><b>Power:</b> cut by ${P.cut_db} dB (${P.current_eirp_dbm} → ${P.recommended_eirp_dbm} dBm EIRP) keeps 6 dB margin at every user; still detected by ${P.heard_by_after.length ? esc(P.heard_by_after.join(', ')) : 'no opposing sensor'} (now: ${P.heard_by_now.length}). ${P.cut_db > 0 ? `<button data-tune-power>Apply</button>` : ''}</p>
        <p><b>Antenna:</b> ${A ? `sector ${A.beamwidth}° at ${A.azimuth}°: ${A.users_closed}/${A.of_users} outstations kept, detected by ${A.heard_by.length} (omni: ${O.users_closed} kept, detected by ${O.heard_by.length}), worst exposure ${A.worst_exposure_db} dB (omni ${O.worst_exposure_db}). ${A.heard_by.length < O.heard_by.length || A.worst_exposure_db < O.worst_exposure_db - 3 ? '<button data-tune-ant>Apply</button>' : '<span class="dim">no gain over omni</span>'}` : 'n/a'}</p>
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
        <span class="btns">${radiates && e.fixed_level_dbm == null ? `<button data-emo-emcon data-on="${f.active ? 0 : 1}">${f.active ? 'EMCON off-air' : 'On air'}</button>` : ''}<button data-emo-editf>Edit</button><button data-emo-multi>Compare with others</button>${f.kind === 'emitter' && e.fixed_level_dbm == null && EMO.ents.some((u) => u.net === f.id) ? '<button data-emo-plannet>EP siting</button> <button data-emo-tune>EP measures: power, antenna, channel</button> <button data-emo-joint>Re-site net (joint)</button>' : ''}<button data-emo-clear>Clear focus</button></span></div>
      ${f.kind === 'effector' ? `<div class="specset"><select data-emo-eatgt>${EMO.ents.filter((n) => n.kind === 'emitter' && n.side !== f.side && n.side !== 'grey' && EMO.ents.some((u) => u.net === n.id)).map((n) => `<option>${esc(n.name)}</option>`).join('')}</select><button data-emo-planea>EA siting</button></div>` : ''}
      <div id="emo-planout"></div>
      ${f.legend ? `<p class="dim">Footprint: where its signal is above ${f.legend.threshold_dbm} dBm (${esc(f.legend.basis)}); darker = just audible, brighter = +10 and +20 dB above; the outline is the limit.${f.kind === 'effector' ? ' Hatched magenta: denial it causes on victim nets.' : ''}</p>` : ''}
      ${f.fix?.fix ? `<p><b style="color:${f.fix.targetable ? '#ff4646' : '#f3b23e'}">${f.fix.targetable ? 'TARGET-QUALITY FIX' : 'Fixed'}: ±${f.fix.fix.error_m} m</b> <span class="dim">(cut ${f.fix.fix.cut_deg}°, ${esc(f.fix.fix.sensors.join(' + '))})</span></p>` : (heard.some((d) => d.df) ? '<p class="dim">Single line of bearing only: not fixed.</p>' : '')}
      ${tbl(`Detected by (${heard.length})`, heard.map((d) => row(esc(d.sensor), `+${d.margin_db} dB`, d.df ? 'DF bearing' : 'intercept')))}
      ${tbl(`Not detected by (${missed.length})`, missed.map((d) => row(esc(d.sensor), `${d.margin_db} dB`, 'below sensitivity')))}
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
        ? `<div class="emo-pair"><b>${esc(P.effector)} vs ${esc(P.net)}</b>: ${P.space ? `denies ${P.denied_km2} km²` : `denies <b>${P.denied_pct}%</b> of the net's coverage (${P.denied_km2} of ${P.coverage_km2} km²)`}; fails at J/S ${P.js_req_db} dB.${P.users.length ? '<br>' + P.users.map((u) => `${esc(u.victim)}: J/S ${u.js_db} dB, <b style="color:${u.status === 'denied' ? '#dc3cdc' : u.status === 'degraded' ? '#f3b23e' : '#45d38a'}">${esc(u.status)}</b>`).join(' · ') : ''}<div class="dim">${esc(P.legend)}</div></div>`
        : `<div class="emo-pair"><b>${esc(P.sensor)} ${P.detected ? 'hears' : 'does not hear'} ${esc(P.emitter)}</b>${P.margin_db != null ? ` (${P.margin_db >= 0 ? '+' : ''}${P.margin_db} dB)` : ''}<div class="dim">${esc(P.legend)}</div></div>`).join('')}
      ${tbl(`Who hears whom (${det.filter((d) => d.detected).length})`, det.map((d) => row(`${nm(d.sensor_id)} → ${nm(d.target_id)}`, `${d.margin_db >= 0 ? '+' : ''}${d.margin_db} dB`, d.detected ? (d.df ? 'heard, DF bearing' : 'heard') : '<span class="dim">not detected</span>')))}
      ${tbl('Fixes on selected', fx.map((f) => row(esc(f.target), `±${f.fix.error_m} m`, `${f.targetable ? '<b style="color:#ff4646">TARGETABLE</b> ' : ''}by ${esc(f.fix.sensors.join(' + '))}`)))}
      ${tbl(`Who jams whom (${jam.length})`, jam.map((j) => row(`${nm(j.effector_id)} → ${nm(j.victim_id)}`, `J/S ${j.js_db} dB`, `<b style="color:${j.status === 'denied' ? '#dc3cdc' : '#45d38a'}">${esc(j.status)}</b>`)))}
      ${EMO.sel.length > 1 && !det.length && !jam.length ? '<p class="dim">No interactions between these on their frequencies (different bands, or no sensor/effector among them).</p>' : ''}`;
  }
