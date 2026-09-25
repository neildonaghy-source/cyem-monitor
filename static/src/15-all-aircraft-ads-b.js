  // ---------------------------------------------------------------- all aircraft (ADS-B)
  async function loadAir() {
    const g = groups.air; g.clearLayers();
    const { data, updated } = await api('/api/layers/air');
    if (!data) { setCount('air', '–'); done('air'); return; }
    const only = optOn('air_flags');
    let n = 0;
    for (const a of data.aircraft || []) {
      if (only && !a.gnss_bad && !a.emerg) continue;
      n++;
      const col = a.emerg ? '#ff5c5c' : a.gnss_bad ? '#f3b23e' : a.mil ? '#ff6fb1' : '#8fb3d9';
      const big = a.emerg || a.gnss_bad;
      L.circleMarker([a.lat, a.lon], { renderer: aisCanvas, radius: big ? 4.5 : 2.5, color: big ? '#fff' : col, weight: big ? 1 : 0, fillColor: col, fillOpacity: 0.85 })
        .bindPopup(() => `<h4>${esc(a.flight || a.reg || a.hex)} <span class="muted">${esc(a.type || '')}</span></h4>${kv([['Status', a.emerg ? `<b style="color:#ff5c5c">Squawk ${a.squawk}: ${esc(a.emerg)}</b>` : a.gnss_bad ? '<b style="color:#f3b23e">Degraded position integrity</b>' : 'normal'], ['NIC / NACp', `${a.nic ?? '–'} / ${a.nacp ?? '–'}`], ['Altitude', a.ground ? 'on ground' : a.alt != null ? `${a.alt.toLocaleString()} ft` : ''], ['Ground speed', a.gs != null ? `${Math.round(a.gs)} kt` : ''], ['Track', a.track != null ? `${Math.round(a.track)}°` : ''], ['Squawk', esc(a.squawk || '')], ['Registration', esc(a.reg || '')], ['Hex', `<span class="mono">${esc(a.hex)}</span>`]])}<p style="margin:6px 0 0"><a href="https://globe.adsb.fi/?icao=${esc(a.hex)}" target="_blank" rel="noopener">Track on adsb.fi ↗</a></p><p class="dim" style="margin:4px 0 0">NIC 1 to 6 suggests degraded GNSS (jamming, spoofing or equipment). ${esc(data.source || '')} · ${fmtZ(updated)}</p>`)
        .addTo(g);
    }
    setCount('air', `${n}/${data.count} · ${data.degraded} GNSS`); done('air');
  }
