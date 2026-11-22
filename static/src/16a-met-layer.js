  // ---------------------------------------------------------------- met layer (phase 4 part 2): k, rain, visibility, ducts
  const MET_COL = { 'sub-refraction': '#3cc7ff', normal: '#8593a6', 'super-refraction': '#f3b23e', trapping: '#ff5c5c' };
  let metSeq = 0, metTimer = null;
  function metFmtGhz(g) { return g == null ? '' : g < 1 ? `${Math.round(g * 1000)} MHz` : `${g} GHz`; }
  async function loadMet() {
    const g = groups.met; const seq = ++metSeq;
    const b = map.getBounds();
    const s = Math.max(-85, b.getSouth()), n = Math.min(85, b.getNorth()), w = Math.max(-180, b.getWest()), e = Math.min(180, b.getEast());
    if (map.getZoom() < 5 || n - s > 20 || e - w > 30) { g.clearLayers(); setCount('met', 'zoom in'); done('met'); return; }
    const res = await api(`/api/met/grid?s=${s.toFixed(3)}&w=${w.toFixed(3)}&n=${n.toFixed(3)}&e=${e.toFixed(3)}`);
    if (seq !== metSeq) return;
    g.clearLayers();
    for (const p of res.points || []) {
      const col = MET_COL[p.refraction] || '#8593a6';
      const marks = [`k ${p.k != null ? p.k.toFixed(2) : '?'}`];
      if (p.rain_mm_h >= 0.5) marks.push(`rain ${p.rain_mm_h}`);
      if (p.fog) marks.push('fog');
      if (p.duct_cutoff_ghz != null) marks.push('duct');
      const wind = p.wind_ms != null && p.wind_dir != null
        ? ` <span class="metw"><span class="metarr" style="transform:rotate(${Math.round(p.wind_dir)}deg)">↓</span>${Math.round(p.wind_ms)}</span>` : '';
      const html = `<div class="metpt" style="border-color:${col}"><b style="color:${col}">${esc(marks.join(' · '))}</b>${wind}</div>`;
      const ducts = (p.ducts || []).map((d) => `${esc(d.kind)} ${d.base_m}–${d.top_m} m (traps ${metFmtGhz(d.cutoff_ghz)} and up)`);
      if (p.evap_duct_m) ducts.push(`evaporation about ${p.evap_duct_m} m over the sea`);
      L.marker([p.lat, p.lon], { icon: L.divIcon({ className: 'metdiv', html, iconSize: null }) })
        .bindPopup(() => `<h4>Met ${esc((res.valid_time || "").replace("T", " "))}</h4>${kv([
          ['Refraction', `${esc(p.refraction || '')} (k ${p.k}, ${p.dn_per_km} N/km)`], ['Rain', p.rain_mm_h != null ? `${p.rain_mm_h} mm/h` : ''],
          ['Visibility', p.visibility_m != null ? `${(p.visibility_m / 1000).toFixed(1)} km${p.fog ? ' (fog)' : ''}` : ''],
          ['Ducts', ducts.length ? ducts.join('<br>') : 'none found'],
          ['Wind', p.wind_ms != null ? `${p.wind_ms} m/s from ${Math.round(p.wind_dir)}°, gusts ${p.gust_ms} m/s` : ''],
          ['Cloud base', p.cloud_base_m != null ? `about ${p.cloud_base_m} m (${p.cloud_low_pct}% low cloud)` : ''],
          ['Freezing level', p.freezing_level_m != null ? `${Math.round(p.freezing_level_m)} m` : ''],
          ['Sea', p.wave_m != null ? `waves ${p.wave_m} m, sea state ${p.sea_state}` : '']])}
          ${(p.warnings || []).length ? `<p style="margin:4px 0 0">${p.warnings.map(esc).join('<br>')}</p>` : ''}
          <p class="dim" style="margin:4px 0 0">${esc(res.notes)}</p>`)
        .addTo(g);
    }
    setCount('met', res.missing ? `${res.points.length}/${res.points.length + res.missing}` : res.points.length); done('met');
  }
  map.on('moveend', () => {
    if (!map.hasLayer(groups.met)) return;
    clearTimeout(metTimer);
    metTimer = setTimeout(() => loadMet().catch((e) => console.warn('met', e)), 600);
  });

