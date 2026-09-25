  // ---- spectrum: Ofcom WTR baseline + planned emitters ------------------------------
  const SPEC = (() => { try { return { guard_khz: 0, radius_km: 50, span_khz: 200, ...JSON.parse(localStorage.getItem('cyem.spec') || '{}') }; } catch { return { guard_khz: 0, radius_km: 50, span_khz: 200 }; } })();
  const saveSpec = () => saveLs('cyem.spec', SPEC);
  const mhz = (hz) => (hz / 1e6).toFixed(hz % 1000 ? 6 : hz % 1e6 ? 4 : 3).replace(/0+$/, '').replace(/\.$/, '');
  const khz = (hz) => `${+(hz / 1e3).toFixed(2)}`;
  function wtrColour(p) {
    p = p || '';
    if (/^BR /.test(p)) return '#3cc7ff';
    if (/Fixed Links|Self Co-Ord|Scanning Telemetry/.test(p)) return '#8593a6';
    if (/AIS|Maritime|Marina|CSR|Coastal/.test(p)) return '#2bb9a8';
    if (/Satellite/.test(p)) return '#ff6fb1';
    if (/GNSS|Differential Global/.test(p)) return '#f3b23e';
    return '#c8d3e0';
  }
  function wtrPopupRows(list) {
    const shown = list.slice(0, 25).map((r) => `<tr><td class="mono">${mhz(r.freq_hz)}</td><td class="mono">${khz(r.bw_hz)}${r.bw_src === 'emission' ? '*' : ''}</td><td>${esc(r.station_type || '')}</td><td class="mono">${r.erp != null ? esc(`${+r.erp.toFixed(2)} ${r.erp_unit || ''}`) : ''}</td><td class="mono">${esc(r.emission || '')}</td></tr>`).join('');
    return `<table class="grid"><tr><th>MHz</th><th>BW kHz</th><th>T/R</th><th>ERP</th><th>Emission</th></tr>${shown}</table>${list.length > 25 ? `<p class="dim">+${list.length - 25} more at this site</p>` : ''}`;
  }
  let wtrSeq = 0;
  async function loadWtr() {
    const g = groups.wtr; const seq = ++wtrSeq;
    if (map.getZoom() < 8) { g.clearLayers(); setCount('wtr', 'zoom in'); done('wtr'); return; }
    const b = map.getBounds().pad(0.1);
    const q = `s=${b.getSouth().toFixed(4)}&w=${b.getWest().toFixed(4)}&n=${b.getNorth().toFixed(4)}&e=${b.getEast().toFixed(4)}&limit=6000`;
    let res;
    try { res = await api(`/api/spectrum/wtr?${q}`); } catch (e) { setCount('wtr', 'err'); throw e; }
    if (seq !== wtrSeq) return;
    g.clearLayers();
    const sites = new Map();
    for (const r of res.rows) { const k = `${r.lat.toFixed(4)},${r.lon.toFixed(4)}`; if (!sites.has(k)) sites.set(k, []); sites.get(k).push(r); }
    for (const list of sites.values()) {
      const r0 = list[0];
      const byLic = [...new Set(list.map((r) => `${r.company || 'Licensee withheld'} · ${r.product} · ${r.licence}`))];
      L.circleMarker([r0.lat, r0.lon], { radius: Math.min(3 + Math.log2(list.length + 1), 8), color: wtrColour(r0.product), weight: 1, fillOpacity: 0.55 })
        .bindPopup(() => `<h4>${esc(r0.company || 'Licensee withheld')}</h4><p class="dim" style="margin:0 0 6px">${byLic.slice(0, 4).map(esc).join('<br>')}${byLic.length > 4 ? `<br>+${byLic.length - 4} more licences` : ''}</p>${wtrPopupRows(list)}<p class="dim" style="margin:6px 0 0">Ofcom WTR licensed assignment, not measured activity. * BW from emission code.</p>`, { maxWidth: 420 })
        .addTo(g);
    }
    setCount('wtr', res.total > res.returned ? `${res.returned}/${res.total}` : res.total); done('wtr');
  }
  map.on('moveend', () => { if (map.hasLayer(groups.wtr)) loadWtr().catch((e) => console.warn('wtr', e)); });
  let lastConflicts = null;
  const SEV_COL = { high: '#ff5c5c', medium: '#f3b23e', low: '#f3b23e' };
  const worst = (cs) => cs.some((c) => c.severity === 'high') ? 'high' : cs.some((c) => c.severity === 'medium') ? 'medium' : cs.length ? 'low' : null;
  async function fetchConflicts() {
    lastConflicts = await api(`/api/spectrum/conflicts?guard_khz=${SPEC.guard_khz}&radius_km=${SPEC.radius_km}&harm_order=${SPEC.harm_order ?? 3}&cosite_km=${SPEC.cosite_km ?? 1}`);
    return lastConflicts;
  }
  function conflictRows(cs, max = 12) {
    if (!cs.length) return '<p class="ok">No conflicts at current settings.</p>';
    const mech = (c) => !c.mechanism || c.mechanism === 'fundamental' ? 'fund.' : `<span title="product at ${mhz(c.product_hz)} MHz, BW ${khz(c.product_bw_hz)} kHz">${esc(c.mechanism === 'im3' ? 'IM3' : c.label)}</span>`;
    return `<table class="grid"><tr><th>Sev</th><th>Type</th><th>Against</th><th>MHz</th><th>BW kHz</th><th>Spacing kHz</th><th>km</th></tr>${cs.slice(0, max).map((c) => {
      const m = c.b_meta || {};
      const who = c.b_kind === 'product' ? `<b>hit by:</b> ${esc(c.b_name)}` : c.b_kind !== 'planned' ? `${esc(c.b_name)}<div class="dim">${esc(m.product || '')} · ${esc(m.licence || '')}</div>` : `<b>planned:</b> ${esc(c.b_name)}`;
      return `<tr><td style="color:${SEV_COL[c.severity]}">${c.severity}</td><td class="mono">${mech(c)}</td><td>${who}</td><td class="mono">${mhz(c.b_freq_hz)}</td><td class="mono">${khz(c.b_bw_hz)}</td><td class="mono">${khz(c.spacing_hz)}${c.co_channel ? '' : ' <span class="dim">(guard)</span>'}</td><td class="mono">${c.dist_km ?? '<span title="Area licence; location not published">area</span>'}${c.pred_dbm != null ? `<div class="dim" title="predicted level of our signal at the licensee">${c.pred_dbm} dBm</div>` : ''}</td></tr>`;
    }).join('')}</table>${cs.length > max ? `<p class="dim">+${cs.length - max} more</p>` : ''}`;
  }
  async function loadPlanned() {
    const g = groups.planned;
    const res = await fetchConflicts();
    g.clearLayers();
    for (const p of res.planned) {
      const w = worst(p.conflicts);
      const col = w ? SEV_COL[w] : '#45d38a';
      L.circle([p.lat, p.lon], { radius: res.radius_km * 1000, color: col, weight: 1, dashArray: '4 6', fill: false, interactive: false }).addTo(g);
      L.circleMarker([p.lat, p.lon], { radius: 8, color: '#fff', weight: 1.5, fillColor: col, fillOpacity: 0.9 })
        .bindPopup(() => `<h4>${esc(p.name)}</h4>${kv([['Freq', `${mhz(p.freq_hz)} MHz`], ['BW', `${khz(p.bw_hz)} kHz`], ['Power', p.power_w != null ? `${p.power_w} W` : ''], ['Window', `${p.start ? fmtZ(p.start) : 'open'} → ${p.end ? fmtZ(p.end) : 'open'}`], ['Conflicts', `${p.conflicts.length}`]])}${conflictRows(p.conflicts, 6)}<p style="margin:6px 0 0"><a href="#" class="spec-open" data-id="${esc(p.id)}">Open in Spectrum ›</a></p>`, { maxWidth: 460 })
        .addTo(g);
    }
    setCount('planned', res.planned.length ? `${res.planned.length} · ${res.totals.high || 0}H ${res.totals.medium || 0}M` : ''); done('planned');
  }
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelectorAll('a.spec-open').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); map.closePopup(); openSpectrum(a.dataset.id); }));
  });
  function loadLayers(minutes) {
    for (const L_ of LAYERS) {
      if (!map.hasLayer(groups[L_.id])) continue;
      if (minutes != null && (L_.every === 0 || minutes % L_.every !== 0) && L_.loaded) continue;
      L_.load().catch((e) => console.warn(L_.id, e));
    }
  }
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelectorAll('a.filter-country').forEach((a) => a.addEventListener('click', (ev) => {
      ev.preventDefault(); state.country = a.dataset.country; state.dom = 'cyber'; setTab('cyber'); loadFeed(); map.closePopup(); showRail(true);
    }));
  });

