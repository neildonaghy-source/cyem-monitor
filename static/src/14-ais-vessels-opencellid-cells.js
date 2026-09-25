  // ---------------------------------------------------------------- AIS vessels + OpenCelliD cells
  const AIS_COL = { military: '#ff5c5c', law: '#ff6fb1', sar: '#f3b23e', tanker: '#c07b3a', cargo: '#3cc7ff', passenger: '#45d38a',
                    fishing: '#2bb9a8', service: '#b48cff', leisure: '#8fb3d9', other: '#8593a6', unknown: '#5d6b7d' };
  const AIS_NAME = { military: 'Military', law: 'Law enforcement', sar: 'Search and rescue', tanker: 'Tanker', cargo: 'Cargo', passenger: 'Passenger',
                     fishing: 'Fishing', service: 'Tug / pilot / service', leisure: 'Sailing / pleasure', other: 'Other', unknown: 'Type not yet received' };
  const aisCanvas = L.canvas({ padding: 0.3 });
  async function loadAis() {
    const g = groups.ais; g.clearLayers();
    const { data, updated } = await api('/api/layers/ais');
    if (!data) { setCount('ais', '–'); done('ais'); return; }
    const only = optOn('ais_gov');
    let n = 0;
    for (const v of data.vessels || []) {
      if (only && !['military', 'law', 'sar'].includes(v.cat)) continue;
      n++;
      const col = AIS_COL[v.cat] || '#8593a6', hi = ['military', 'law', 'sar'].includes(v.cat);
      L.circleMarker([v.lat, v.lon], { renderer: aisCanvas, radius: hi ? 5 : 3, color: hi ? '#fff' : col, weight: hi ? 1 : 0, fillColor: col, fillOpacity: 0.85 })
        .bindPopup(() => `<h4>${esc(v.name || 'MMSI ' + v.mmsi)}</h4>${kv([['Type', esc(AIS_NAME[v.cat] || v.cat) + (v.type != null ? ` (${v.type})` : '')], ['MMSI', `<span class="mono">${v.mmsi}</span>`], ['Call sign', esc(v.callsign || '')], ['Speed', v.sog != null ? `${v.sog} kn` : ''], ['Course', v.cog != null ? `${Math.round(v.cog)}°` : ''], ['Destination', esc(v.dest || '')], ['Class', v.cls], ['Last seen', fmtZ(v.seen)]])}<p class="dim" style="margin:4px 0 0">AIS via aisstream.io, sampled every 5 min · ${fmtZ(updated)}</p>`)
        .addTo(g);
    }
    setCount('ais', `${n}/${data.count}`); done('ais');
  }
  const CELL_COL = { GSM: '#8593a6', UMTS: '#3cc7ff', LTE: '#45d38a', NR: '#ff6fb1', CDMA: '#f3b23e' };
  let cellSeq = 0;
  async function loadCells() {
    const g = groups.cells; const seq = ++cellSeq;
    if (map.getZoom() < 11) { g.clearLayers(); setCount('cells', 'zoom in'); done('cells'); return; }
    const b = map.getBounds().pad(0.05);
    const res = await api(`/api/cells?s=${b.getSouth().toFixed(4)}&w=${b.getWest().toFixed(4)}&n=${b.getNorth().toFixed(4)}&e=${b.getEast().toFixed(4)}`);
    if (seq !== cellSeq) return;
    g.clearLayers();
    if (!res.loaded) { setCount('cells', 'not loaded'); done('cells'); return; }
    for (const c of res.rows) {
      L.circleMarker([c.lat, c.lon], { renderer: aisCanvas, radius: 3, weight: 0, fillColor: CELL_COL[c.radio] || '#c8d3e0', fillOpacity: 0.8 })
        .bindPopup(() => `<h4>${esc(c.operator)} ${esc(c.radio)}</h4>${kv([['Cell', `<span class="mono">${c.mcc}-${c.net}-${c.area}-${c.cell}</span>`], ['Est. range', c.range_m ? `${c.range_m} m` : ''], ['Samples', c.samples], ['Updated', c.updated ? new Date(c.updated * 1000).toISOString().slice(0, 10) : '']])}<p class="dim" style="margin:4px 0 0">OpenCelliD (CC BY-SA 4.0): crowd-sourced estimate of where the cell was heard, not a surveyed mast.</p>`)
        .addTo(g);
    }
    setCount('cells', res.total > res.returned ? `${res.returned}/${res.total}` : res.total); done('cells');
  }
  map.on('moveend', () => { if (map.hasLayer(groups.cells)) loadCells().catch((e) => console.warn('cells', e)); });
