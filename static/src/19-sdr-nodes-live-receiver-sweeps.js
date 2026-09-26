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
      <span class="${age != null && age < 10 ? 'good' : 'bad'}">${age == null ? 'never seen' : age < 10 ? `online${n.info?.state && n.info.state !== 'sweeping' ? ' (' + esc(n.info.state) + ')' : ''}, last sweep ${age} min ago` : `last seen ${age} min ago`}</span>
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
  function toastSDR(t) { const o = $('#sdr-out'); if (o) o.insertAdjacentHTML('afterbegin', `<p class="bad">${esc(t)}</p>`); }
  $('#btn-sdr').addEventListener('click', () => openSDR());
