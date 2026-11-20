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
    let nodes = [], st = {};
    try { st = await api('/api/sdr/nodes'); nodes = st.nodes; } catch (e) { return openModal('SDR', `<p class="bad">${esc(e.message)}</p>`); }
    if (!nodes.length) {
      const rj = st.last_reject;
      openModal('SDR receivers', `<p><b>No receiver is sending sweeps to this server.</b></p>
        <ul>
          <li>Ingest on this server: ${st.ingest_enabled ? '<span class="good">on</span> (a token is set)' : '<span class="bad">off</span>: SDR_INGEST_TOKEN is not set on the server'}.</li>
          <li>Last rejected sweep: ${rj ? `<span class="bad">${esc(rj.node || '?')} at ${esc(fmtZ(rj.at))}: ${esc(rj.reason)}</span>` : 'none since the server started'}.</li>
          <li>The dongle on trade is shared with the Ecowitt weather receiver: once the shared sweep is installed there (<span class="mono">pi/trade/</span>) it sweeps four times a day and appears here as trade-sdr.</li>
        </ul>
        <p>To add one: a Raspberry Pi 5 with an RTL-SDR Blog V4, or a second V4 on trade or the EVO, running the sweep agent from the repo's <span class="mono">pi/</span> folder with this server's address and ingest token. It appears here within a few minutes of its first sweep.</p>
        <p><button id="sdr-again">Check again</button></p>`);
      $('#sdr-again').addEventListener('click', () => openSDR());
      return;
    }
    SDR.node = SDR.node && nodes.some((n) => n.node === SDR.node) ? SDR.node : nodes[0].node;
    const n = nodes.find((x) => x.node === SDR.node);
    const age = n.last_seen ? Math.round((Date.now() - Date.parse(n.last_seen)) / 60000) : null;
    let body = `<div class="specset"><select id="sdr-node">${nodes.map((x) => `<option${x.node === SDR.node ? ' selected' : ''}>${esc(x.node)}</option>`).join('')}</select>
      ${(() => { const shared = /shared/.test(n.info?.state || '') || !!n.info?.live_capable; const ok = age != null && (age < 10 || (shared && age < 480));
        const when = age == null ? 'never seen' : age < 90 ? `${age} min ago` : `${Math.round(age / 60)} h ago`;
        return `<span class="${ok ? 'good' : 'bad'}">${age == null ? 'never seen' : shared ? `shared receiver: sweeps four times a day, last ${when}` : age < 10 ? `online${n.info?.state && n.info.state !== 'sweeping' ? ' (' + esc(n.info.state) + ')' : ''}, last sweep ${when}` : `last seen ${when}`}</span>`; })()}
      ${n.url && !n.info?.live_capable ? `<button id="sdr-live" data-url="${esc(n.url)}">Open live receiver</button>` : ''} <button id="sdr-ins">Insight (AI)</button></div>
      ${n.info?.live_capable ? sdrLiveBox() : ''}<div class="specset sdr-posset"><input id="sdr-q" placeholder="Postcode, place or lat, lon" autocomplete="off" style="flex:1 1 220px"> <button id="sdr-set">Set position</button> <button id="sdr-pick">Pick on map</button> <button id="sdr-pos">Use this device</button></div><div id="sdr-insout" class="md"></div>
      <p class="dim">Position: ${n.lat != null ? `${n.lat.toFixed(4)}, ${n.lon.toFixed(4)} (${fmtZ(n.pos_at)})` : 'not set'} · ${n.sweeps} sweeps stored. Spectrum occupancy only; nothing is demodulated or recorded.</p>
      ${SDR.posMsg ? `<p class="good">${esc(SDR.posMsg)}</p>` : ''}<div id="sdr-out"><span class="spinner"></span></div>`; SDR.posMsg = '';
    openModal('SDR receivers', body);
    $('#sdr-node').addEventListener('change', (e) => { SDR.node = e.target.value; openSDR(); });
    // Live receiver in an in-app window: a plain link replaced the whole app page, and the Mac/iPhone apps have no Back
    $('#sdr-live')?.addEventListener('click', (ev) => openLiveRx(ev.currentTarget.dataset.url, n.node));
    if (n.info?.live_capable) sdrLiveWire(n);
    $('#sdr-ins').addEventListener('click', async () => {
      const o = $('#sdr-insout'); o.innerHTML = '<span class="spinner"></span> reading the spectrum… (about a minute)';
      try { const r = await api(`/api/insight/sdr?node=${encodeURIComponent(SDR.node)}`); o.innerHTML = renderMd(r.text); }
      catch (e) { o.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    });
    const setQ = async () => {
      const q = $('#sdr-q').value.trim(); if (!q) return toastSDR('Enter a postcode, place or lat, lon');
      $('#sdr-set').disabled = true;
      try { const r = await postJson(`/api/sdr/nodes/${encodeURIComponent(SDR.node)}/locate`, { q }); SDR.posMsg = `Position set: ${r.label}`; openSDR(); }
      catch (e) { $('#sdr-set').disabled = false; toastSDR(e.message); }
    };
    $('#sdr-set').addEventListener('click', setQ);
    $('#sdr-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); setQ(); } });
    $('#sdr-pick').addEventListener('click', () => {
      $('#modal').classList.remove('show');
      pickOnMap('the receiver position', async (e) => {
        const lat = +e.latlng.lat.toFixed(5), lon = +e.latlng.lng.toFixed(5);
        try { await postJson(`/api/sdr/nodes/${encodeURIComponent(SDR.node)}/position`, { lat, lon }); SDR.posMsg = `Position set from the map: ${lat}, ${lon}`; }
        catch (err) { SDR.posMsg = err.message; }
        openSDR();
      }, () => openSDR());
    });
    $('#sdr-pos').addEventListener('click', () => {
      if (!navigator.geolocation) return toastSDR('No location on this device');
      navigator.geolocation.getCurrentPosition(async (p) => {
        try { await postJson(`/api/sdr/nodes/${encodeURIComponent(SDR.node)}/position`, { lat: +p.coords.latitude.toFixed(5), lon: +p.coords.longitude.toFixed(5) }); openSDR(); }
        catch (e) { toastSDR(e.message); }
      }, (e) => toastSDR(`This device's location is unavailable (${e.message}): enter a postcode, place or lat, lon, or use Pick on map.`), { enableHighAccuracy: true, timeout: 15000 });
    });
    try {
      const l = await api(`/api/sdr/latest?node=${encodeURIComponent(SDR.node)}`);
      if (l.empty) { $('#sdr-out').innerHTML = `<p class="dim">No sweeps from ${esc(SDR.node)} yet${n.info?.state ? ` (node reports: ${esc(n.info.state)})` : ''}. ${n.info?.state === 'no dongle' ? 'Plug the RTL-SDR in; sweeps start on their own.' : ''}</p>`; return; }
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
  // ---- Listen live (Nov 2026): the node's agent pauses the weather receiver and starts OpenWebRX+, reached via /sdr/live/
  function sdrLiveBox() {
    return `<div id="sdr-livebox" class="sdr-livebox"><div class="specset"><b>Listen live</b>
        <select id="sdr-live-min" aria-label="How long"><option value="15">15 min</option><option value="30" selected>30 min</option><option value="60">60 min</option></select>
        <button id="sdr-listen">Listen live</button> <button id="sdr-stop" hidden>Stop</button> <button id="sdr-full" hidden>Full screen</button></div>
      <p id="sdr-live-status" class="dim"></p>
      <p class="dim">Listening pauses the weather receiver on this dongle until you press Stop or the time runs out (at most two hours), and the shared sweeps skip while it is live. Audio is streamed to you only: nothing is recorded or stored.</p>
      <div id="sdr-live-frame"></div></div>`;
  }
  function sdrHHMM(iso) { try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso; } }
  function sdrLiveWire(n0) {
    clearInterval(SDR.liveTimer);
    const node = n0.node;
    const render = (n) => {
      const st = $('#sdr-live-status'); if (!st) return false;
      const m = n.mode || {}, state = n.info?.state || '', err = n.info?.live_error;
      const want = m.mode === 'live', live = state === 'live';
      let txt, cls = 'dim';
      if (want && live) { txt = `Live until ${esc(sdrHHMM(m.until))}. Tap the play button in the receiver to start audio.`; cls = 'good'; SDR.liveBack = true; }
      else if (want) txt = `Switching… pausing the weather receiver and starting the live receiver (usually under 30 s${state === 'sweeping' ? '; a shared sweep is running and finishes first, about 3 minutes' : ''}).`;
      else if (live) txt = 'Switching back to the weather receiver…';
      else if (SDR.liveBack && state === 'weather') { txt = 'Weather receiver back.'; cls = 'good'; }
      else txt = state === 'sweeping' ? 'A shared sweep is running; live listening can start when it ends.' : state === 'weather' ? 'Weather receiver running.' : `Receiver reports: ${esc(state || 'nothing yet')}.`;
      if (err && !(want && live)) txt += ` <span class="bad">${esc(err)}</span>`;
      st.className = cls; st.innerHTML = txt;
      $('#sdr-listen').hidden = want; $('#sdr-live-min').hidden = want; $('#sdr-stop').hidden = !want; $('#sdr-full').hidden = !(want && live);
      const fr = $('#sdr-live-frame');
      if (want && live && !fr.querySelector('iframe')) {
        fr.innerHTML = '<div class="lvbar"><b>Live receiver</b><span class="dim">nothing is recorded</span><button id="sdr-full-close">Close full screen</button></div><iframe src="/sdr/live/" allow="autoplay; fullscreen" title="Live receiver"></iframe>';
        $('#sdr-full-close').addEventListener('click', () => fr.classList.remove('full'));
      } else if (!(want && live) && fr.querySelector('iframe')) {
        fr.querySelector('iframe').src = 'about:blank'; fr.innerHTML = ''; fr.classList.remove('full');
      }
      return true;
    };
    const poll = async () => {
      if (!$('#sdr-live-status')) { clearInterval(SDR.liveTimer); return; }       // panel closed or redrawn
      try { const st = await api('/api/sdr/nodes'); const n = st.nodes.find((x) => x.node === node); if (n) render(n); } catch (e) { /* next tick */ }
    };
    render(n0);
    SDR.liveTimer = setInterval(poll, 4000);
    $('#sdr-listen').addEventListener('click', async () => {
      $('#sdr-listen').disabled = true;
      try { const m = await postJson('/api/sdr/mode', { node, mode: 'live', minutes: +$('#sdr-live-min').value }); SDR.liveBack = false; render({ ...n0, mode: m }); poll(); }
      catch (e) { $('#sdr-live-status').innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
      $('#sdr-listen').disabled = false;
    });
    $('#sdr-stop').addEventListener('click', async () => {
      const fr = $('#sdr-live-frame'); const f = fr.querySelector('iframe'); if (f) f.src = 'about:blank';
      fr.innerHTML = ''; fr.classList.remove('full');
      try { await postJson('/api/sdr/mode', { node, mode: 'auto' }); SDR.liveBack = true; poll(); }
      catch (e) { $('#sdr-live-status').innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
    });
    $('#sdr-full').addEventListener('click', () => $('#sdr-live-frame').classList.add('full'));
  }
  function openLiveRx(url, node) {
    closeLiveRx();
    const ov = document.createElement('div'); ov.id = 'sdr-live-ov';
    ov.innerHTML = `<div class="lvbar"><b>Live receiver</b><span class="dim">${esc(node || '')} · OpenWebRX · tap the play button to start audio</span><button id="sdr-live-close">Close ×</button></div><iframe src="${esc(url)}" allow="autoplay; fullscreen" referrerpolicy="no-referrer"></iframe>`;
    document.body.appendChild(ov);
    ov.querySelector('#sdr-live-close').addEventListener('click', closeLiveRx);
    document.addEventListener('keydown', liveEsc);
  }
  function liveEsc(e) { if (e.key === 'Escape') closeLiveRx(); }
  function closeLiveRx() {
    const ov = document.getElementById('sdr-live-ov'); if (!ov) return;
    const f = ov.querySelector('iframe'); if (f) f.src = 'about:blank';   // stop the audio stream
    ov.remove(); document.removeEventListener('keydown', liveEsc);
  }
  function toastSDR(t) { const o = $('#sdr-out'); if (o) o.insertAdjacentHTML('afterbegin', `<p class="bad">${esc(t)}</p>`); }
  $('#btn-sdr').addEventListener('click', () => openSDR());
