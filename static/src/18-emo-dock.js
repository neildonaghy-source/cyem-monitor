  // ---- EMO dock: the planning tools on the map, each in a small floating card
  const SCORE_KEYS = [['net_availability_pct', 'Net availability %'], ['emitters_exposed', 'Emitters detected'], ['mean_exposure_db', 'Mean exposure dB'], ['fixed', 'Located'], ['targetable', 'Target-quality fixes'], ['denial_achieved', 'Outstations denied'], ['spoofed', 'Outstations deceived'], ['collateral', 'Collateral (civil)'], ['net_area_denied_pct', 'Net coverage denied %'], ['radar_tracks', 'Radar tracks'], ['radar_screened', 'Screened from radar']];
  function emoScoreTable(r) {
    if (!r?.score) return '<p class="dim">Run the analysis first.</p>';
    const order = EMO.side === 'red' ? ['red', 'blue'] : ['blue', 'red'];
    return `<table class="grid"><tr><th></th>${order.map((sd) => `<th style="color:${SIDE_COL[sd]}">${sd === EMO.side ? 'Own (' + sd + ')' : sd}</th>`).join('')}</tr>${SCORE_KEYS.map(([k, l]) => `<tr><td>${l}</td>${order.map((sd) => { const v = r.score[sd][k], pv = EMO.prevScore?.[sd]?.[k]; const d = (typeof v === 'number' && typeof pv === 'number' && v !== pv) ? ` <span class="dim">(${v > pv ? '+' : ''}${Math.round((v - pv) * 10) / 10})</span>` : ''; return `<td class="mono">${v ?? '–'}${d}</td>`; }).join('')}</tr>`).join('')}</table>`;
  }
  // ---- Corridor: one unit's EM manoeuvre corridor to a picked point (POST /api/emo/plan/corridor)
  const corrLayer = L.layerGroup().addTo(map);
  const CORR_COL = { transmit: '#f3b23e', silent: '#45d38a' };
  function emoCorridorClear() { if (EMO.corr) { EMO.corr.res = null; EMO.corr.to = null; } corrLayer.clearLayers(); document.body.dataset.corrLegs = 0; }
  function emoCorridorDraw() {
    corrLayer.clearLayers(); document.body.dataset.corrLegs = 0; const c = EMO.corr; if (!c) return;
    if (c.to) L.circleMarker(c.to, { radius: 6, color: '#fff', weight: 2, fillColor: '#3c8cff', fillOpacity: 0.9 }).bindTooltip('Corridor destination').addTo(corrLayer);
    const r = c.res; document.body.dataset.corrLegs = r ? r.legs.length : 0; if (!r) return;
    if (r.band) L.imageOverlay(r.band, r.bounds, { opacity: 0.8, interactive: false }).addTo(corrLayer);
    r.legs.forEach((lg, i) => L.polyline(lg.path, { color: CORR_COL[lg.emcon], weight: 5, opacity: 0.95 })
      .bindTooltip(`Leg ${i + 1}: ${lg.km} km, ${lg.minutes} min, ${lg.emcon}<br>detect ${lg.p_detect}% · fix ${lg.p_fix}% · radar ${lg.p_radar}% · C2 ${lg.p_c2}%`).addTo(corrLayer));
  }
  function emoCorridorHtml(r) {
    const s = r.summary, v = (lg) => lg.verified ? `${lg.verified.p_detect}%${lg.verified.p_c2 != null ? ` / ${lg.verified.p_c2}%` : ''}` : '–';
    return `<p><b>${esc(r.unit)}</b> (${esc(r.domain)}) ${s.km} km in about ${s.minutes} min at ${s.speed_kmh} km/h <span class="dim">(direct ${s.direct_km} km)</span>; transmitting on ${s.transmit_pct}% of the route.
      Worst: detect ${s.max_p_detect}%, fix ${s.max_p_fix}%, radar ${s.max_p_radar}%, C2 at least ${s.min_p_c2}% <span class="dim">(${esc(s.c2)})</span>. Cost ${s.cost} against ${s.direct_cost} straight; band ${s.band_km2} km² at ${s.cell_m} m cells.</p>
      <p><span style="color:${CORR_COL.transmit}">■</span> transmit leg <span style="color:${CORR_COL.silent}">■</span> silent leg <span style="color:#45d38a;opacity:.6">■</span> corridor band</p>
      <table class="grid"><tr><th>Leg</th><th>km</th><th>min</th><th>EMCON</th><th>Detect</th><th>Fix</th><th>Radar</th><th>C2</th><th title="exact pairwise model at the leg's worst point: detection / C2">Verified</th><th>Heard by</th></tr>
      ${r.legs.map((lg, i) => `<tr><td>${i + 1}</td><td class="mono">${lg.km}</td><td class="mono">${lg.minutes}</td><td style="color:${CORR_COL[lg.emcon]}">${lg.emcon}</td><td class="mono">${lg.p_detect}%</td><td class="mono">${lg.p_fix}%</td><td class="mono">${lg.p_radar}%</td><td class="mono">${lg.p_c2}%</td><td class="mono">${v(lg)}</td><td>${esc((lg.heard_by || []).join(', ')) || '–'}</td></tr>`).join('')}</table>
      ${s.sensors.length ? '' : '<p class="dim">No opposing ES sensor covers this unit\'s band.</p>'}<p class="dim">${esc(r.notes)}</p>`;
  }
  function emoCorridor() {
    const units = EMO.ents.filter((e) => e.side === 'blue' || e.side === 'red');
    if (!units.length) return emoDockCard('Corridor', '<p class="dim">No blue or red units in this scenario.</p>');
    const foc = EMO.ents.find((e) => e.id === EMO.focus && e.side !== 'grey');
    const c = EMO.corr = EMO.corr || { domain: 'ground', emcon: 'auto', silent: 0.6, alt: 150, speed: '' };
    if (!units.some((e) => e.name === c.mover)) c.mover = (foc || units.find((e) => e.side === EMO.side) || units[0]).name;
    const b = emoDockCard('Corridor', `<div class="specset">Unit <select id="corr-unit">${units.map((e) => `<option${e.name === c.mover ? ' selected' : ''} style="color:${SIDE_COL[e.side]}">${esc(e.name)}</option>`).join('')}</select>
        <select id="corr-dom">${[['ground', 'Ground'], ['sea', 'Sea'], ['air', 'Air (low level)']].map(([k, l]) => `<option value="${k}"${c.domain === k ? ' selected' : ''}>${l}</option>`).join('')}</select>
        <span id="corr-altw"${c.domain === 'air' ? '' : ' hidden'}>at <input id="corr-alt" type="number" min="1" max="1000" value="${c.alt}" style="width:58px"> m AGL</span></div>
      <div class="specset">Speed <input id="corr-speed" type="number" min="1" max="1000" placeholder="auto" value="${c.speed}" style="width:60px"> km/h
        EMCON <select id="corr-emcon">${[['auto', 'Auto'], ['emit', 'Transmit'], ['silent', 'Silent']].map(([k, l]) => `<option value="${k}"${c.emcon === k ? ' selected' : ''}>${l}</option>`).join('')}</select>
        <span title="Cost per cell of moving without two-way C2: higher means the planner transmits more">silent price <input id="corr-sil" type="number" min="0" max="10" step="0.1" value="${c.silent}" style="width:52px"></span></div>
      <div class="specset"><button id="corr-pick">Pick destination</button> <span id="corr-to" class="mono dim">${c.to ? `${c.to[0]}, ${c.to[1]}` : 'none'}</span>
        <button id="corr-go" class="primary"${c.to ? '' : ' disabled'}>Plan</button> <button id="corr-clear">Clear</button> <span id="corr-st" class="dim"></span></div>
      <div id="corr-out">${c.res ? emoCorridorHtml(c.res) : `<p class="dim">At T+${Math.round(EMO.t)} min, with the last run's atmosphere. Notional data; screening grade.</p>`}</div>`);
    const read = () => { c.mover = b.querySelector('#corr-unit').value; c.domain = b.querySelector('#corr-dom').value; c.alt = +b.querySelector('#corr-alt').value || 150;
      c.speed = b.querySelector('#corr-speed').value; c.emcon = b.querySelector('#corr-emcon').value; c.silent = Math.max(0, +b.querySelector('#corr-sil').value || 0); };
    b.querySelector('#corr-dom').addEventListener('change', (e) => { b.querySelector('#corr-altw').hidden = e.target.value !== 'air'; });
    b.querySelector('#corr-pick').addEventListener('click', () => {
      read();
      pickOnMap('the corridor destination', (ev) => { c.to = [+ev.latlng.lat.toFixed(5), +ev.latlng.lng.toFixed(5)]; c.res = null; emoCorridorDraw(); if (document.getElementById('emo-dockcard')) emoCorridor(); }, () => { if (document.getElementById('emo-dockcard')) emoCorridor(); });
    });
    b.querySelector('#corr-clear').addEventListener('click', () => { emoCorridorClear(); emoCorridor(); });
    b.querySelector('#corr-go').addEventListener('click', async () => {
      read(); const st = b.querySelector('#corr-st'), t0 = Date.now();
      const tick = setInterval(() => { st.textContent = `planning… ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
      st.innerHTML = '<span class="spinner"></span> planning…';
      const body = { mover: c.mover, to_lat: c.to[0], to_lon: c.to[1], domain: c.domain, emcon: c.emcon, silent_cost: c.silent };
      if (c.domain === 'air') body.alt_m = c.alt;
      if (+c.speed > 0) body.speed_kmh = +c.speed;
      try {
        c.res = await postJson(`/api/emo/plan/corridor?t_min=${EMO.t}`, body); clearInterval(tick);
        emoCorridorDraw(); if (c.res.bounds) map.fitBounds(c.res.bounds, { padding: [20, 20] });
        if (document.getElementById('emo-dockcard')) emoCorridor();
      } catch (err) { clearInterval(tick); st.innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
    });
    return b;
  }
  function emoDockCard(title, html) {
    let c = document.getElementById('emo-dockcard'); if (!c) { c = document.createElement('div'); c.id = 'emo-dockcard'; document.body.appendChild(c); }
    c.innerHTML = `<div class="emo-card-head"><b>${title}</b><span class="btns"><button id="emo-dockclose">×</button></span></div><div id="emo-dockbody">${html}</div>`;
    c.querySelector('#emo-dockclose').addEventListener('click', () => c.remove());
    return c.querySelector('#emo-dockbody');
  }
  async function emoDockTool(tool) {
    if (tool === 'panel') { document.getElementById('emo-dockcard')?.remove(); return openEMO(); }
    if (tool === 'undo') {
      try {
        const r = await postJson('/api/emo/undo', {});
        EMO.ents = r.entities; EMO.res = null; emoClearFocus(); planLayer.clearLayers(); emoDraw();
        emoStatus(`Undid: ${r.undone}${r.depth ? ` (${r.depth} more)` : ''}`); await emoRun();
      } catch (e) { emoStatus('Nothing to undo'); }
      return;
    }
    if (tool === 'space') {
      const toDevice = wsId() === 'default';
      const b = emoDockCard('Scenario space', `<p>Now: <b>${toDevice ? 'Shared (all devices)' : 'This device only'}</b>.</p><p class="dim">${toDevice ? 'A private space keeps your experiments off the shared scenario.' : 'The shared space is what every device sees.'}</p><p><button data-space-go>${toDevice ? 'Switch to this device only' : 'Switch to shared'}</button></p>`);
      b.querySelector('[data-space-go]').addEventListener('click', () => { localStorage.setItem('cyem-ws-mode', toDevice ? 'device' : 'shared'); location.reload(); });
      return;
    }
    if (tool === 'corridor') { emoCorridor(); return; }
    if (tool === 'time') { const sc = document.getElementById('emo-scrub'); if (sc) sc.classList.toggle(matchMedia('(pointer: coarse)').matches ? 'open' : 'closed'); else emoScrubber(); return; }
    if (tool === 'side') { EMO.side = EMO.side === 'blue' ? 'red' : 'blue'; localStorage.setItem('cyem-side', EMO.side); document.getElementById('emo-dock')?.remove(); emoDock(); document.getElementById('emo-dockcard')?.remove(); return; }
    if (tool === 'layers') {
      const b = emoDockCard('EMO overlays', EMO_LAYERS.map(([k, l, col]) => `<label style="display:block"><input type="checkbox" data-dock-layer="${k}"${EMO.on[k] ? ' checked' : ''}> <span style="color:${col}">■</span> ${l}</label>`).join(''));
      b.querySelectorAll('[data-dock-layer]').forEach((cb) => cb.addEventListener('change', () => { EMO.on[cb.dataset.dockLayer] = cb.checked; emoDraw(); }));
    } else if (tool === 'score') {
      emoDockCard('Scoreboard', emoScoreTable(EMO.res) + (EMO.stale ? '<p class="dim">Stale: run again after moves.</p>' : ''));
    } else if (tool === 'time') {
      const b = emoDockCard('Time', `<p>T+<b id="emo-docktime">${EMO.t}</b> min of ${EMO.horizon || 0}</p><input id="emo-dockslider" type="range" min="0" max="${Math.max(1, Math.round(EMO.horizon || 0))}" step="5" value="${EMO.t}" style="width:100%"><p><button id="emo-dockplay">Play</button> <button id="emo-dockt0">T+0</button></p>`);
      const set = async (v) => { EMO.t = +v; $('#emo-docktime').textContent = EMO.t; EMO.stale = true; emoDraw(); await emoRun(); };
      b.querySelector('#emo-dockslider').addEventListener('change', (e) => set(e.target.value));
      b.querySelector('#emo-dockt0').addEventListener('click', () => { b.querySelector('#emo-dockslider').value = 0; set(0); });
      b.querySelector('#emo-dockplay').addEventListener('click', async () => { const sl = b.querySelector('#emo-dockslider'); for (let v = +sl.value + 10; v <= +sl.max && document.getElementById('emo-dockcard'); v += 10) { sl.value = v; await set(v); } });
    } else if (tool === 'coa') {
      const b = emoDockCard('Courses of action', `<p><input id="emo-dockcoaname" placeholder="COA name" style="width:140px"> <button id="emo-dockcoasave">Save current</button> <a href="/api/emo/coas/export.docx" download><button>Word annex</button></a></p><div id="emo-dockcoalist"></div>`);
      const list = async () => {
        const r = await api('/api/emo/coas'); const box = b.querySelector('#emo-dockcoalist');
        const keys = [['net_availability_pct', 'Avail'], ['targetable', 'TQF'], ['denial_achieved', 'Den'], ['radar_tracks', 'Rdr']];
        const row = (name, sc, ctl) => `<tr><td>${name}</td>${['blue', 'red'].map((sd) => keys.map(([k]) => `<td class="mono" style="color:${SIDE_COL[sd]}">${sc?.[sd]?.[k] ?? '–'}</td>`).join('')).join('')}<td>${ctl}</td></tr>`;
        box.innerHTML = r.coas.length || r.current ? `<table class="grid"><tr><th></th>${['B', 'R'].map((s) => keys.map(([, l]) => `<th>${s} ${l}</th>`).join('')).join('')}<th></th></tr>${r.current ? row('<i>now</i>', r.current, '') : ''}${r.coas.map((c) => row(esc(c.name), c.score, `<button data-dock-load="${c.id}">Load</button> <button data-dock-del="${c.id}">×</button>`)).join('')}</table>` : '<p class="dim">No COAs saved.</p>';
        box.querySelectorAll('[data-dock-load]').forEach((x) => x.addEventListener('click', async () => { try { emoAbortRun(); const r2 = await postJson(`/api/emo/coas/${x.dataset.dockLoad}/load`, {}); EMO.ents = r2.entities; EMO.res = null; if (r2.t_min != null) EMO.t = r2.t_min; if (r2.params) EMO.params = { ...EMO.params, ...r2.params }; emoClearFocus(); emoDraw(); await emoRun(); list(); } catch (e) { toast(`COA load failed: ${e.message}`); } }));
        box.querySelectorAll('[data-dock-del]').forEach((x) => x.addEventListener('click', async () => { if (await apiDel(`/api/emo/coas/${x.dataset.dockDel}`)) list(); }));
      };
      b.querySelector('#emo-dockcoasave').addEventListener('click', async () => { const name = b.querySelector('#emo-dockcoaname').value.trim() || `COA ${new Date().toISOString().slice(11, 16)}Z`; try { await postJson('/api/emo/coas', { name }); b.querySelector('#emo-dockcoaname').value = ''; list(); } catch (e) { toast(`COA save failed: ${e.message}`); } });
      list();
    } else if (tool === 'red') {
      const b = emoDockCard('Adversary COA', `<p><select id="emo-dockside"><option value="red"${EMO.side === 'blue' ? ' selected' : ''}>Red</option><option value="blue"${EMO.side === 'red' ? ' selected' : ''}>Blue</option></select> <button data-dock-coa="mlcoa" title="Most likely: at most two modest moves">MLCOA</button> <button data-dock-coa="mdcoa" title="Most dangerous: every jammer and DF site re-sited">MDCOA</button> <button data-dock-coa="revert">Revert</button></p><div id="emo-dockcoaout" class="dim"></div>`);
      b.querySelectorAll('[data-dock-coa]').forEach((x) => x.addEventListener('click', async () => {
        const side = b.querySelector('#emo-dockside').value, o = b.querySelector('#emo-dockcoaout'), kind = x.dataset.dockCoa;
        o.innerHTML = '<span class="spinner"></span> generating and applying…';
        try {
          const r = kind === 'revert' ? await postJson(`/api/emo/plan/coa/revert?side=${side}&t_min=${EMO.t}`, {}) : await postJson(`/api/emo/plan/coa?t_min=${EMO.t}`, { side, coa: kind });
          planLayer.clearLayers();
          (r.moves || []).forEach((m) => L.polyline([m.from, m.to], { color: SIDE_COL[side], weight: 3, dashArray: '6 6' }).bindTooltip(`${esc(m.entity)} → ${esc(m.where)}<br>${esc(m.detail)}`).addTo(planLayer));
          o.innerHTML = kind === 'revert' ? `reverted ${r.reverted} positions` : (r.moves.length ? `${r.coa.toUpperCase()} against ${esc(r.target)}:<br>${r.moves.map((m) => `<b>${esc(m.entity)}</b> ${esc(m.where)}<br><span class="dim">${esc(m.detail)}</span>`).join('<br>')}` : `${r.coa.toUpperCase()}: no move clearly improves ${side}'s laydown`);
          EMO.prevScore = r.score_before || EMO.prevScore; await emoLoad(); EMO.res = null; await emoRun();
        } catch (err) { o.innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
      }));
    } else if (tool === 'timeline') {
      const nets = EMO.ents.filter((e) => e.kind === 'emitter' && e.fixed_level_dbm == null && EMO.ents.some((u) => u.net === e.id));
      const b = emoDockCard('Timeline', `<p>step <input id="emo-docktlstep" type="number" value="10" min="1" style="width:56px"> min, windows for <select id="emo-docktlnet"><option value="">(none)</option>${nets.map((e) => `<option${e.name === EMO.tlNet ? ' selected' : ''}>${esc(e.name)}</option>`).join('')}</select> <button id="emo-docktl">Run</button> <span id="emo-docktlst" class="dim"></span></p><div id="emo-docktlout"></div>`);
      b.querySelector('#emo-docktl').addEventListener('click', async () => {
        const out = b.querySelector('#emo-docktlout'), st = b.querySelector('#emo-docktlst'); EMO.tlNet = b.querySelector('#emo-docktlnet').value || null;
        const t0 = Date.now(); const tick = setInterval(() => { st.textContent = `stepping… ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
        try {
          const r = await postJson('/api/emo/plan/timeline', { step_min: +b.querySelector('#emo-docktlstep').value || 10, net: EMO.tlNet });
          clearInterval(tick); st.textContent = `${r.steps.length} steps to T+${r.horizon_min} min`;
          out.innerHTML = emoTimelineHtml(r);
        } catch (err) { clearInterval(tick); st.innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
      });
    }
  }
  function emoTimelineHtml(r) {
    const names = Object.keys(r.rows).filter((n) => r.rows[n].tracked || r.rows[n].heard.some(Boolean) || r.rows[n].denied.some(Boolean)).sort((a, b) => (r.rows[a].side + a).localeCompare(r.rows[b].side + b));
    const W = 680, lab = 150, cw = Math.max(6, Math.floor((W - lab - 10) / r.steps.length)), rh = 14, H = 20 + names.length * rh;
    const cell = (row, i) => row.denied[i] ? '#dc3cdc' : row.targetable[i] ? '#ff4646' : row.heard[i] ? '#f3b23e' : '#45d38a';
    const svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0b1016;border-radius:6px;font:10px sans-serif">${r.steps.map((s, i) => i % Math.ceil(r.steps.length / 8) === 0 ? `<text x="${lab + i * cw}" y="12" fill="#8593a6">T+${s}</text>` : '').join('')}${names.map((n, k) => `<text x="4" y="${20 + k * rh + 10}" fill="${SIDE_COL[r.rows[n].side] || '#aaa'}">${esc(n.slice(0, 24))}</text>` + r.steps.map((s, i) => `<rect x="${lab + i * cw}" y="${20 + k * rh + 2}" width="${cw - 1}" height="${rh - 3}" fill="${cell(r.rows[n], i)}"><title>${esc(n)} T+${s}: ${r.rows[n].denied[i] ? 'denied' : r.rows[n].targetable[i] ? 'target-quality fix' : r.rows[n].heard[i] ? 'detected by ' + esc(r.rows[n].heard_by[i].join(', ')) : 'undetected'}</title></rect>`).join('')).join('')}</svg>`;
    const w = r.windows;
    return `<p><span style="color:#45d38a">■</span> undetected <span style="color:#f3b23e">■</span> detected <span style="color:#ff4646">■</span> target-quality fix <span style="color:#dc3cdc">■</span> denied</p>${svg}${w ? `<p><b>${esc(w.net)}</b>: ${esc(w.summary)}${w.advantage.length ? `<br>Undetected and not denied: ${w.advantage.map((x) => `T+${x.from_min}–${x.to_min} min`).join(', ')}` : '<br><span class="bad">No window: siting alone gives none; use EMCON or another bearer.</span>'}</p>` : ''}`;
  }
  function emoDock() {
    if (EMO.hidden || document.getElementById('emo-dock') || !EMO.ents.length) return;
    const d = document.createElement('div'); d.id = 'emo-dock';
    d.innerHTML = [['side', EMO.side === 'red' ? 'Red' : 'Blue'], ['undo', 'Undo'], ['layers', 'Overlays'], ['score', 'Score'], ['time', 'Time'], ['coa', 'COA'], ['red', 'Adv COA'], ['timeline', 'Timeline'], ['corridor', 'Corridor'], ['space', wsId() === 'default' ? 'Shared' : 'Device'], ['panel', 'Panel']].map(([k, l]) => `<button data-dock="${k}" style="${k === 'side' ? `border-color:${SIDE_COL[EMO.side]}` : ''}">${l}</button>`).join('');
    document.body.appendChild(d);
    d.querySelectorAll('[data-dock]').forEach((b) => b.addEventListener('click', () => emoDockTool(b.dataset.dock)));
  }
  function emoScrubber() {
    if (EMO.hidden || !EMO.res) return;
    let sc = document.getElementById('emo-scrub');
    if (!sc) {
      sc = document.createElement('div'); sc.id = 'emo-scrub';
      sc.innerHTML = '<button data-sc="play" title="Play">▶</button><input type="range" min="0" step="5"><span data-sc="lbl"></span>';
      document.body.appendChild(sc);
      const inp = sc.querySelector('input');
      inp.addEventListener('input', () => { sc.querySelector('[data-sc=lbl]').textContent = `T+${inp.value} / ${Math.round(EMO.horizon || 0)} min`; });
      inp.addEventListener('change', async () => { EMO.t = +inp.value; EMO.stale = true; emoDraw(); await emoRun(); });
      sc.querySelector('[data-sc=play]').addEventListener('click', async () => {
        if (EMO.playing) { EMO.playing = false; return; }
        EMO.playing = true; sc.querySelector('[data-sc=play]').textContent = '⏸';
        for (let v = EMO.t + 10; v <= +inp.max && EMO.playing; v += 10) { inp.value = v; EMO.t = v; EMO.stale = true; emoDraw(); await emoRun(); }
        EMO.playing = false; sc.querySelector('[data-sc=play]').textContent = '▶';
      });
    }
    const inp = sc.querySelector('input'); inp.max = Math.max(5, Math.round(EMO.horizon || 0)); inp.value = EMO.t;
    sc.querySelector('[data-sc=lbl]').textContent = `T+${Math.round(EMO.t)} / ${Math.round(EMO.horizon || 0)} min`;
  }
  let staleTimer = null, staleLeft = 0;
  function emoStaleBanner() {
    const show = !EMO.hidden && EMO.stale && !EMO.busy && !!EMO.res;
    let b = document.getElementById('emo-stale');
    if (!show) { if (b) b.remove(); if (staleTimer) { clearInterval(staleTimer); staleTimer = null; } return; }
    if (!b) { b = document.createElement('div'); b.id = 'emo-stale'; document.body.appendChild(b); }
    const paint = () => {
      b.innerHTML = staleTimer ? `Scenario changed: results shown are from before. Re-running in ${staleLeft} s <button data-st="now">Now</button> <button data-st="cancel">Cancel</button>`
                               : 'Scenario changed: results shown are from before. <button data-st="now">Re-run</button>';
      b.querySelector('[data-st=now]').addEventListener('click', () => { if (staleTimer) clearInterval(staleTimer); staleTimer = null; emoRun(); });
      b.querySelector('[data-st=cancel]')?.addEventListener('click', () => { clearInterval(staleTimer); staleTimer = null; EMO.staleCancelled = true; paint(); });
    };
    if (!staleTimer && !EMO.staleCancelled) {
      staleLeft = 5;
      staleTimer = setInterval(() => { staleLeft -= 1; if (staleLeft <= 0) { clearInterval(staleTimer); staleTimer = null; emoRun(); } else paint(); }, 1000);
    }
    paint();
  }
  function emoCoach() {
    const b = emoDockCard('Getting started', '<ol><li><b>Tap a unit</b> on the map for its card: EMCON, EP siting, EP measures, Compare.</li><li><b>Use the dock</b> for overlays, the scoreboard, time, COAs, the adversary\'s response and the timeline.</li><li><b>Ask</b> in the bar above the map; select a unit first for siting questions.</li></ol><p><button data-coach-ok>Got it</button></p>');
    b.querySelector('[data-coach-ok]').addEventListener('click', () => { localStorage.setItem('cyem-coach', '1'); document.getElementById('emo-dockcard')?.remove(); });
  }
  function emoAskBar() {
    if (EMO.hidden || document.getElementById('emo-askbar') || !EMO.ents.length) return;
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
        const r = await fetch('/api/emo/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, selected: sel, viewpoint: EMO.side }) });
        if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
        if (!r.ok) throw new Error(`Ask failed: HTTP ${r.status}`);
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
  async function emoAutoStart() {
    if (EMO.hidden) return;
    try {
      const r = await api('/api/emo'); if (!r.entities?.length) return;
      EMO.ents = r.entities; $('#btn-emo').classList.add('active');
      const core = EMO.ents.filter((e) => e.side !== 'grey'); const b = L.latLngBounds((core.length ? core : EMO.ents).map((e) => [e.lat, e.lon])); if (startViewHold) startViewHold = false; else if (b.isValid()) map.fitBounds(b.pad(0.1), matchMedia('(pointer: coarse)').matches && innerHeight > innerWidth ? { paddingBottomRight: [0, Math.round(innerHeight * 0.4)] } : {});
      const touch = matchMedia('(pointer: coarse)').matches, lblZ = touch ? 13 : 11;
      if (!EMO.wired) { EMO.wired = true; map.on('zoomend', () => document.body.classList.toggle('emo-nolabels', map.getZoom() < lblZ)); }
      document.body.classList.toggle('emo-nolabels', map.getZoom() < lblZ);
      if (!EMO.wired2) { EMO.wired2 = true; new MutationObserver(() => document.body.classList.toggle('emo-hascard', !!document.getElementById('emo-card'))).observe(document.body, { childList: true }); }
      emoDraw(); emoDock(); emoAskBar();
      if (!localStorage.getItem('cyem-coach')) emoCoach();
      await emoRun();
    } catch (e) { /* no scenario yet */ }
  }
  EMO.hidden = localStorage.getItem('cyem-emo-on') === '0';
  // EMO off: clear this device's view (the scenario stays on the box); EMO on: show it again and run
  function emoOff() {
    EMO.hidden = true; EMO.playing = false; EMO.pending = false; try { EMO.abort?.abort(); } catch (e) { /* ignore */ }
    if (staleTimer) { clearInterval(staleTimer); staleTimer = null; } clearInterval(emoTick);
    EMO.focus = null; EMO.focusRes = null; EMO.multi = false; EMO.sel = []; EMO.multiRes = {}; EMO.pairRes = {}; EMO.res = null;
    emoLayer.clearLayers(); planLayer.clearLayers(); emoCorridorClear();
    ['emo-chip', 'emo-dock', 'emo-dockcard', 'emo-card', 'emo-askbar', 'emo-askcard', 'emo-stale', 'emo-scrub'].forEach((id) => document.getElementById(id)?.remove());
    document.body.classList.remove('emo-hascard', 'emo-nolabels');
    if ($('#modal-title').textContent.startsWith('EMO')) $('#modal').classList.remove('show');
    try { localStorage.setItem('cyem-emo-on', '0'); } catch (e) { /* ignore */ }
    $('#btn-emo').classList.remove('active');
  }
  function emoEnable() { EMO.hidden = false; try { localStorage.setItem('cyem-emo-on', '1'); } catch (e) { /* ignore */ } $('#btn-emo').classList.add('active'); }
  async function emoOn() { emoEnable(); await emoAutoStart(); if (!EMO.ents.length) openEMO(); }
  const emoActive = () => !EMO.hidden && (!!document.getElementById('emo-chip') || !!document.getElementById('emo-dock'));
  setTimeout(emoAutoStart, 1500);
  async function emoLoad() { EMO.ents = (await api('/api/emo')).entities; }
  let emoTick = null;
  async function emoRun() {
    if (EMO.busy) { EMO.pending = true; EMO.stale = true; return; }
    EMO.busy = true; EMO.pending = false; EMO.started = Date.now(); EMO.staleCancelled = false; emoStaleBanner(); EMO.abort = new AbortController();
    const est = Math.max(0, (+localStorage.getItem('cyem-est-' + (EMO.ents?.length || 0)) || 0) - 1.5);
    clearInterval(emoTick);
    emoTick = setInterval(() => emoStatus(`EMO computing… ${Math.round((Date.now() - EMO.started) / 1000)} s${est ? ` of about ${Math.round(est)} s` : (EMO.res ? '' : ' (first run of a scenario takes about a minute)')} · tap to cancel`), 1000);
    try {
      await emoLoad();
      EMO.prevScore = EMO.res?.score || EMO.prevScore;
      EMO.res = await postJson(`/api/emo/run?t_min=${EMO.t}`, EMO.params, 'POST', EMO.abort.signal); EMO.horizon = EMO.res.horizon_min;
      EMO.stale = EMO.pending; emoDraw(); emoResults(); emoAskBar(); emoDock(); emoScrubber();
      try { if (EMO.res.compute_s >= 2) localStorage.setItem('cyem-est-' + EMO.ents.length, EMO.res.compute_s); } catch (e) { /* ignore */ }
      if (EMO.about && !EMO.aboutShown) { EMO.aboutShown = true; emoDockCard('About this scenario', `<p>${esc(EMO.about)}</p>`); }
      if (EMO.multi && EMO.sel.length) { EMO.multiRes = {}; EMO.pairRes = {}; emoMultiRefresh(); } else if (EMO.focus) emoFocus(EMO.focus);
      const fx = EMO.res.fixes.filter((f) => f.targetable).length;
      const worst = [...EMO.res.nets].sort((a, b) => b.denied_pct - a.denied_pct)[0];
      emoStatus(`EMO T+${Math.round(EMO.t)} min${EMO.pending ? ' · updating…' : ''} · ${fx} target-quality fix${fx === 1 ? '' : 'es'}${worst ? ` · ${worst.net} ${worst.denied_pct}% denied` : ''} · ${EMO.res.compute_s} s`);
    } catch (err) {
      if (err.name === 'AbortError') { EMO.pending = false; EMO.staleCancelled = true; if (EMO.res) EMO.stale = true; emoStatus(EMO.res ? 'Cancelled: results shown are from before' : 'Cancelled: tap the chip to run'); }
      else emoStatus(/run the analysis first/i.test(err.message) ? 'Run the analysis first: tap the chip' : /sign in/i.test(err.message) ? 'Sign in required: reload the page' : `EMO error: ${err.message}`);
    }
    finally { clearInterval(emoTick); EMO.busy = false; EMO.abort = null; emoStaleBanner(); if (EMO.pending) emoRun(); }
  }
  function emoAbortRun() { try { EMO.abort?.abort(); } catch (e) { /* nothing running */ } EMO.pending = false; }
  function emoStatus(t) {
    if (EMO.hidden) return;
    const el = $('#emo-status'); if (el) el.textContent = t;
    let chip = document.getElementById('emo-chip');
    if (!chip) { chip = document.createElement('div'); chip.id = 'emo-chip'; chip.title = 'Open EMO panel'; chip.addEventListener('click', () => { if (EMO.busy && EMO.abort) { EMO.abort.abort(); return; } if (/^Cancelled/.test(chip.textContent)) { emoRun(); return; } openEMO(); }); document.body.appendChild(chip); }
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
      ${emoMetCard(r.met)}
      ${r.score ? `<h3 class="sec">Scoreboard</h3><table class="grid"><tr><th></th><th style="color:${SIDE_COL.blue}">Blue</th><th style="color:${SIDE_COL.red}">Red</th></tr>
        ${[['net_availability_pct', 'Net availability %'], ['emitters_exposed', 'Emitters detected by the other side'], ['mean_exposure_db', 'Mean exposure dB'], ['fixed', 'Located by the other side'], ['targetable', 'Target-quality fixes'], ['denial_achieved', 'Outstations denied'], ['spoofed', 'Outstations deceived'], ['collateral', 'Collateral (civil)'], ['net_area_denied_pct', 'Own net coverage denied %'], ['radar_tracks', 'Radar tracks held'], ['radar_screened', 'Own platforms screened from radar']]
          .map(([k, l]) => `<tr><td>${l}</td>${['blue', 'red'].map((sd) => { const v = r.score[sd][k], pv = EMO.prevScore?.[sd]?.[k]; const d = (typeof v === 'number' && typeof pv === 'number' && v !== pv) ? ` <span class="dim">(${v > pv ? '+' : ''}${Math.round((v - pv) * 10) / 10})</span>` : ''; return `<td class="mono">${v ?? '–'}${d}</td>`; }).join('')}</tr>`).join('')}</table>` : ''}
      ${r.radar?.length ? `<h3 class="sec">Radar: tracks and screening</h3><table class="grid"><tr><th>Radar</th><th>Target</th><th>km</th><th>Echo margin</th><th>Result</th></tr>${r.radar.filter((x) => x.detected || x.jam).map((x) => `<tr><td style="color:${SIDE_COL[x.radar_side]}">${esc(x.radar)}</td><td style="color:${SIDE_COL[x.target_side]}">${esc(x.target)} <span class="dim">${x.rcs_m2} m²</span></td><td class="mono">${x.range_km}</td><td class="mono">${x.margin_db >= 0 ? '+' : ''}${x.margin_db} dB · ${x.p}%</td><td>${x.tracked ? '<b style="color:#45d38a">tracked</b>' : x.screened ? `<b style="color:#dc3cdc">screened</b> by ${esc(x.jam.jammer)} (${esc(x.jam.mode)}, J/S ${x.jam.js_db} dB, burn-through ${x.jam.burnthrough_km} km)` : 'no track'}</td></tr>`).join('')}</table>` : ''}
      <h3 class="sec">ES: what each side can see and fix</h3>
      ${fx.length ? `<table class="grid"><tr><th>Target</th><th>Seen by</th><th>Fix</th></tr>${fx.map((f) => row([`<span style="color:${SIDE_COL[f.target_side]}">${esc(f.target)}</span>`, esc(f.sensors.join(', ')),
        f.fix ? `${f.targetable ? '<b style="color:#ff4646">TARGETABLE</b> ' : ''}±${f.fix.error_m} m, cut ${f.fix.cut_deg}°` : `${f.lobs} line of bearing only`])).join('')}</table>` : '<p class="dim">No DF bearings on any emitter.</p>'}
      <p class="dim">Detections: ${r.detections.filter((d) => d.detected && d.sensor_side === 'red').length} blue emissions detected by red, ${r.detections.filter((d) => d.detected && d.sensor_side === 'blue').length} red emissions detected by blue. Exposure area (ground sensors): blue ${r.exposure.find((x) => x.side === 'blue')?.km2} km², red ${r.exposure.find((x) => x.side === 'red')?.km2} km².</p>
      <h3 class="sec">EA: nets under attack</h3>
      ${r.nets.length ? `<table class="grid"><tr><th>Net</th><th>Coverage</th><th>Denied</th><th>Fails at</th></tr>${r.nets.map((n) => row([`<span style="color:${SIDE_COL[n.side]}">${esc(n.net)}</span>`, n.space ? 'space signal' : `${n.coverage_km2} km²`, `<b>${n.denied_pct}%</b> (${n.denied_km2} km²)`, `J/S ${n.js_req_db} dB`])).join('')}</table>` : ''}
      ${r.jamming.length ? `<table class="grid"><tr><th>Effector</th><th>Victim</th><th>J/S</th><th>Result</th></tr>${r.jamming.map((j) => row([esc(j.effector), esc(j.victim), `${j.js_db} dB`, `<b style="color:${j.status === 'denied' ? '#dc3cdc' : j.status === 'holds' ? '#45d38a' : '#8593a6'}">${esc(j.status)}</b>`])).join('')}</table>` : '<p class="dim">No EA against any net.</p>'}
      <p class="dim">${esc(r.notes)}</p>`;
  }
  function emoMetCard(m) {
    if (!m) return '';
    const u = m.used || {}, fc = m.source === 'open-meteo';
    const ev = m.evap_duct, sea = m.sea;
    const wi = (used, base) => used != null && base != null && Math.abs(used - base) > 1e-6;   // a what-if replaced the forecast value
    const kNow = u.k ?? m.k ?? 1.333;
    const cells = [
      ['k-factor', `<b>${kNow.toFixed(2)}</b> ${wi(kNow, m.k) ? `what-if <span class="dim">(${fc ? `forecast ${m.k.toFixed(2)}, ${esc(m.refraction || '')}, ${m.dn_per_km} N/km` : 'standard 1.33'})</span>` : fc ? `<span class="dim">${esc(m.refraction || '')}, ${m.dn_per_km} N/km</span>` : '<span class="dim">standard</span>'}`],
      ['Rain', `${u.rain_mm_h ?? 0} mm/h${wi(u.rain_mm_h, m.rain_mm_h ?? 0) ? ` what-if <span class="dim">(${fc ? 'forecast' : 'standard'} ${m.rain_mm_h ?? 0})</span>` : ''}`],
      ['Visibility', m.visibility_m == null ? '–' : `${m.visibility_m >= 1000 ? (m.visibility_m / 1000).toFixed(1) + ' km' : Math.round(m.visibility_m) + ' m'}${u.fog_lwc_gm3 ? ` <span class="dim">fog ${u.fog_lwc_gm3} g/m³</span>` : ''}`],
      ...(fc ? [['Wind', `${m.wind_ms ?? '–'} m/s from ${m.wind_dir ?? '–'}°, gusts ${m.gust_ms ?? '–'}`],
        ['Cloud', `${m.cloud_low_pct ?? '–'}% low, base about ${m.cloud_base_m ?? '–'} m · freezing level ${m.freezing_level_m ?? '–'} m`],
        ['Air', `${m.temp_c ?? '–'} °C, ${m.rh_pct ?? '–'} %`]] : []),
      ...(sea ? [['Sea', `${sea.sst_c} °C, waves ${sea.wave_m ?? '–'} m / ${sea.wave_period_s ?? '–'} s${ev ? ` · evaporation duct <b>${ev.height_m} m</b> (${esc(ev.stability)}${ev.cutoff_ghz ? `, traps above ${ev.cutoff_ghz} GHz` : ''})` : ''}`]] : []),
      ...((m.ducts || []).map((d) => ['Duct', `${esc(d.kind)} ${d.base_m}–${d.top_m} m, traps above ${d.cutoff_ghz < 1 ? Math.round(d.cutoff_ghz * 1000) + ' MHz' : d.cutoff_ghz + ' GHz'}`])),
      ...(m.space_weather?.kp != null ? [['Space weather', `Kp ${m.space_weather.kp}`]] : [])];
    return `<h3 class="sec">Met ${fc ? `<span class="dim">Open-Meteo, valid ${esc(m.valid_time || '')} at ${m.lat}, ${m.lon}</span>` : '<span class="dim">standard atmosphere</span>'}</h3>
      <table class="grid">${cells.map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join('')}</table>
      ${(m.warnings || []).map((w) => `<p class="warn">${esc(w)}</p>`).join('')}${(m.notes || []).map((w) => `<p class="dim">${esc(w)}</p>`).join('')}`;
  }
  function emoTimelineMet(r) {
    const ms = (r.board || []).map((b) => b.met).filter(Boolean);
    if (!ms.length || ms.every((m) => m.k === ms[0].k && m.rain_mm_h === ms[0].rain_mm_h && m.fog_lwc_gm3 === ms[0].fog_lwc_gm3 && !m.ducts)) return '';
    return `<p>Met by step: ${(r.board || []).map((b) => b.met ? `T+${b.t} k ${b.met.k}${b.met.rain_mm_h ? `, rain ${b.met.rain_mm_h}` : ''}${b.met.fog_lwc_gm3 ? ', fog' : ''}${b.met.ducts ? ', duct' : ''}` : '').filter(Boolean).join(' · ')}</p>`;
  }
  function emoMetParams() {
    const v = (id) => { const x = $(id)?.value; return x === '' || x == null ? null : +x; };
    EMO.params.met = $('#emo-met').value;
    EMO.params.met_time = $('#emo-mettime').value || null;
    EMO.params.k_factor = v('#emo-k'); EMO.params.rain_mm_h = v('#emo-rain'); EMO.params.visibility_m = v('#emo-vis');
    try { localStorage.setItem('cyem-emo-met', EMO.params.met); } catch (e) { /* private window */ }
  }
  async function openEMO() {
    emoEnable();
    if (!EMO.params.met) { try { EMO.params.met = localStorage.getItem('cyem-emo-met') === 'forecast' ? 'forecast' : 'standard'; } catch (e) { EMO.params.met = 'standard'; } }
    try { if (!EMO.examples) EMO.examples = (await api('/api/emo/examples')).examples; await emoLoad(); EMO.scen = (await api('/api/emo/scenarios')).scenarios; } catch (err) { return openModal('EMO', `<p class="bad">${esc(err.message)}</p>`); }
    const list = EMO.ents.length ? `<table class="grid"><tr><th>Entity</th><th>Role</th><th>MHz</th><th></th></tr>${EMO.ents.map((e) => `<tr class="${e.id === EMO.editId ? 'sel' : ''}"><td style="color:${SIDE_COL[e.side]}">${esc(e.name)}${e.active || e.kind === 'sensor' || e.kind === 'receiver' ? '' : ' <span class="dim">(off-air)</span>'}</td><td class="dim">${esc(KIND_TXT[e.kind])}${e.category ? ' · ' + esc(e.category) : ''}</td><td class="mono">${e.freq_mhz}${e.f_hi_mhz ? '–' + e.f_hi_mhz : ''}</td><td><button data-emo-edit="${esc(e.id)}">Edit</button></td></tr>`).join('')}</table>` : '<p class="dim">No entities: load an example.</p>';
    const H = Math.max(EMO.horizon, 0);
    openModal('EMO: red / blue in the spectrum', `<p class="dim">Notional scenarios. ES: who can hear and fix whom. EA: whose nets are denied. EP: EMCON, siting, antennas. Drag units on the map at T+0.</p>
      <div class="specset"><select id="emo-ex"><option value="">Load example…</option>${[['Home ground (AR)', /^0[de]\./], ['Operational MDO', /^0[bc]?\./], ['Vignettes', /./]].reduce((acc, [g, re]) => { const rest = EMO.examples.filter((x) => !acc.used.has(x.id) && re.test(x.title)); rest.forEach((x) => acc.used.add(x.id)); if (rest.length) acc.html += `<optgroup label="${g}">${rest.map((x) => `<option value="${esc(x.id)}">${esc(x.title)}</option>`).join('')}</optgroup>`; return acc; }, { used: new Set(), html: '' }).html}</select> <button id="emo-ex-go">Load</button></div>
      ${EMO.about ? `<p class="dim">${esc(EMO.about)}</p>` : ''}
      <div class="specset">Save current as <input id="emo-sc-name" placeholder="scenario name" style="width:180px"> <button id="emo-sc-save">Save</button>
        ${(EMO.scen || []).map((x) => `<span style="white-space:nowrap">${esc(x.name)} <span class="dim">(${x.entities})</span> <button data-sc-load="${esc(x.id)}">Load</button><button data-sc-del="${esc(x.id)}">×</button></span>`).join(' ')}</div>
      <div class="specset">Time T+<b id="emo-tv">${Math.round(EMO.t)}</b> min <input id="emo-t" type="range" min="0" max="${Math.max(1, Math.ceil(H))}" step="1" value="${EMO.t}" style="flex:1;min-width:140px">
        <button id="emo-run" class="primary" title="Recompute the analysis at this T+ (it also re-runs on its own after any change)">Re-run</button> <button id="emo-play" title="Step T+ forward through the scenario horizon, re-running at each step: units follow their tracks, on-air windows open and close">${EMO.playing ? 'Stop' : 'Play time'}</button> <span id="emo-status" class="dim"></span></div>
      <div class="specset">${EMO_LAYERS.map(([k, l, c]) => `<label style="white-space:nowrap"><input type="checkbox" data-emo-layer="${k}"${EMO.on[k] ? ' checked' : ''}> <span style="color:${c}">■</span> ${esc(l)}</label>`).join(' ')}</div>
      <div class="specset">Targetable if fix within <input id="emo-tgt" type="number" min="50" step="50" value="${EMO.params.df_fix_good_m}" style="width:80px"> m
        <span class="dim">(tactical ~1000, operational ~5000)</span> · <span class="dim">Map washes are for ground receivers (2 m); airborne results are in the cards and tables.</span></div>
      <div class="specset">Met <select id="emo-met"><option value="standard"${EMO.params.met !== 'forecast' ? ' selected' : ''}>Standard atmosphere (4/3 earth, dry)</option><option value="forecast"${EMO.params.met === 'forecast' ? ' selected' : ''}>Forecast at the scenario centre (Open-Meteo)</option></select>
        T+0 <input id="emo-mettime" type="datetime-local" step="3600" value="${esc(EMO.params.met_time || '')}" style="width:190px" title="UTC; empty means now. Forecasts run 16 days ahead; older dates use archived forecasts."> UTC
        <span class="dim">what-if:</span> k <input id="emo-k" type="number" step="0.1" min="0.5" max="10" placeholder="auto" value="${EMO.params.k_factor ?? ''}" style="width:58px">
        rain <input id="emo-rain" type="number" step="1" min="0" max="200" placeholder="auto" value="${EMO.params.rain_mm_h ?? ''}" style="width:56px"> mm/h
        visibility <input id="emo-vis" type="number" step="50" min="10" placeholder="auto" value="${EMO.params.visibility_m ?? ''}" style="width:68px"> m</div>
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
      <div class="specset">Corridor: one unit's route to a point, EMCON leg by leg <button id="emo-corr">Plan a corridor</button> <span class="dim">(opens beside the map)</span></div>
      <div class="specset">Adversary COA: <select id="emo-coaside"><option value="red">Red</option><option value="blue">Blue</option></select>
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
        const keys = [['net_availability_pct', 'Avail %'], ['targetable', 'Target-quality fixes'], ['denial_achieved', 'Outstations denied'], ['collateral', 'Collateral'], ['net_area_denied_pct', 'Area denied %']];
        const cell = (sc, sd, k) => sc?.[sd]?.[k] ?? '–';
        const rowOf = (name, sc, ctl) => `<tr><td>${name}</td>${['blue', 'red'].map((sd) => keys.map(([k]) => `<td class="mono" style="color:${SIDE_COL[sd]}">${cell(sc, sd, k)}</td>`).join('')).join('')}<td>${ctl}</td></tr>`;
        box.innerHTML = `<table class="grid"><tr><th>COA</th>${['Blue', 'Red'].map((sd) => keys.map(([, l]) => `<th style="color:${SIDE_COL[sd.toLowerCase()]}">${sd} ${l}</th>`).join('')).join('')}<th></th></tr>
          ${r.current ? rowOf('<i>current</i>', r.current, '') : ''}
          ${r.coas.map((c) => rowOf(esc(c.name), c.score, `<button data-coa-load="${c.id}">Load</button> <button data-coa-del="${c.id}">×</button>`)).join('')}</table>`;
        box.querySelectorAll('[data-coa-load]').forEach((b) => b.addEventListener('click', async () => {
          emoAbortRun(); let r2; try { r2 = await postJson(`/api/emo/coas/${b.dataset.coaLoad}/load`, {}); } catch (e) { return toast(`COA load failed: ${e.message}`); } EMO.ents = r2.entities; EMO.res = null; if (r2.t_min != null) EMO.t = r2.t_min; if (r2.params) EMO.params = { ...EMO.params, ...r2.params }; emoClearFocus(); await openEMO(); emoRun();
        }));
        box.querySelectorAll('[data-coa-del]').forEach((b) => b.addEventListener('click', async () => { if (await apiDel(`/api/emo/coas/${b.dataset.coaDel}`)) coaList(); }));
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
            r.steps.map((s, i) => `<rect x="${lab + i * cw}" y="${20 + k * rh + 2}" width="${cw - 1}" height="${rh - 3}" fill="${cell(r.rows[n], i)}"><title>${esc(n)} T+${s}: ${r.rows[n].denied[i] ? 'denied' : r.rows[n].targetable[i] ? 'target-quality fix' : r.rows[n].heard[i] ? 'detected by ' + esc(r.rows[n].heard_by[i].join(', ')) : 'undetected'}</title></rect>`).join('')).join('')}</svg>`;
        const w = r.windows;
        out.innerHTML = `<p><span style="color:#45d38a">■</span> undetected <span style="color:#f3b23e">■</span> detected <span style="color:#ff4646">■</span> target-quality fix <span style="color:#dc3cdc">■</span> denied</p>${svg}
          ${w ? `<h4>Windows of EM advantage for ${esc(w.net)}</h4><p>${esc(w.summary)}</p>${w.advantage.length ? `<p>Undetected and not denied: ${w.advantage.map((x) => `T+${x.from_min}–${x.to_min} min`).join(', ')}</p>` : '<p class="bad">No step where the control station is unheard and all users are undenied: siting alone gives no window; use EMCON or another bearer.</p>'}` : ''}
          ${emoTimelineMet(r)}<p class="dim">${esc(r.notes)}</p>`;
      } catch (err) { clearInterval(tick); st.innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
    });
    $('#emo-corr').addEventListener('click', () => { $('#modal').classList.remove('show'); emoCorridor(); });
    $('#emo-coa-ml').addEventListener('click', () => coa('mlcoa'));
    $('#emo-coa-md').addEventListener('click', () => coa('mdcoa'));
    $('#emo-coa-rev').addEventListener('click', () => coa('revert'));
    $('#emo-tgt').addEventListener('change', (e) => { EMO.params.df_fix_good_m = Math.max(50, +e.target.value || 1000); emoRun(); });
    ['#emo-met', '#emo-mettime', '#emo-k', '#emo-rain', '#emo-vis'].forEach((id) => $(id).addEventListener('change', () => { emoMetParams(); emoRun(); }));
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
        const sel = EMO.multi && EMO.sel.length ? EMO.sel : EMO.focus ? [EMO.focus] : null;   // as the dock's Ask
        const r = await fetch('/api/emo/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, selected: sel, viewpoint: EMO.side }) });
        if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
        if (!r.ok) throw new Error(`Ask failed: HTTP ${r.status}`);
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
      if (wsId() === 'default' && EMO.ents.length && !EMO.loadArmed) { EMO.loadArmed = true; $('#emo-ex-go').textContent = 'Replace the shared scenario? Tap again'; setTimeout(() => { EMO.loadArmed = false; const b = $('#emo-ex-go'); if (b) b.textContent = 'Load'; }, 6000); return; }
      EMO.loadArmed = false;
      emoStatus('loading…');
      try {
        emoAbortRun();
        const r = await postJson(`/api/emo/examples/${encodeURIComponent(id)}`, {});
        EMO.ents = r.entities; EMO.about = r.about; EMO.params = { rx_h: 2, js_req_db: 0, df_fix_good_m: 1000, met: EMO.params.met, met_time: EMO.params.met_time, ...(r.params || {}) }; EMO.t = 0; EMO.res = null; EMO.editId = null; EMO.draft = null;
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
      EMO.playing = false; const pb = $('#emo-play'); if (pb) pb.textContent = 'Play time';
    });
    body.querySelectorAll('input[data-emo-layer]').forEach((cb) => cb.addEventListener('change', () => { EMO.on[cb.dataset.emoLayer] = cb.checked; emoDraw(); }));
    body.querySelectorAll('button[data-emo-edit]').forEach((b) => b.addEventListener('click', () => { EMO.editId = b.dataset.emoEdit; EMO.draft = { ...EMO.ents.find((e) => e.id === EMO.editId) }; openEMO(); }));
    $('#emo-new').addEventListener('click', () => { EMO.editId = null; EMO.draft = null; openEMO(); });
    $('#emo-tpl').addEventListener('change', (ev) => { const tp = EMO_TPL[+ev.target.value]; if (!tp) return; const cur = emoRead();
      EMO.draft = { ...cur, ...tp[1], name: cur.name || tp[0], side: cur.side || 'blue' }; openEMO(); });
    $('#emo-sc-save').addEventListener('click', async () => { const nm = $('#emo-sc-name').value.trim(); if (!nm) return;
      try { await postJson('/api/emo/scenarios', { name: nm }); openEMO(); } catch (err) { emoStatus(err.message); } });
    body.querySelectorAll('button[data-sc-load]').forEach((b) => b.addEventListener('click', async () => {
      emoAbortRun(); try { await postJson(`/api/emo/scenarios/${b.dataset.scLoad}/load`, {}); } catch (e) { return toast(`Scenario load failed: ${e.message}`); } EMO.res = null; EMO.focus = null; document.getElementById('emo-card')?.remove(); EMO.t = 0; await openEMO(); emoDraw(); emoRun(); }));
    body.querySelectorAll('button[data-sc-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!armConfirm(b)) return; if (await apiDel(`/api/emo/scenarios/${b.dataset.scDel}`)) openEMO(); }));
    $('#emo-del')?.addEventListener('click', async () => {
      if (!armConfirm($('#emo-del'), 'Tap again to delete')) return;
      if (!await apiDel(`/api/emo/${encodeURIComponent(EMO.editId)}`)) return; EMO.editId = null; EMO.draft = null; await openEMO(); emoRun();
    });
    $('#emo-pick').addEventListener('click', () => {
      EMO.draft = emoRead(); $('#modal').classList.remove('show'); showSide(false); if (mobile()) showRail(false);
      pickOnMap('the entity position', (ev) => { EMO.draft.lat = +ev.latlng.lat.toFixed(5); EMO.draft.lon = +ev.latlng.lng.toFixed(5); openEMO(); }, () => openEMO());
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
  $('#btn-emo').title = 'EMO on / off for this device (panel: the chip at the bottom or the dock)';
  $('#btn-emo').addEventListener('click', () => { if (emoActive()) emoOff(); else emoOn(); });

  { const _emoDraw = emoDraw; emoDraw = function () { _emoDraw(); emoStaleBanner(); }; }
