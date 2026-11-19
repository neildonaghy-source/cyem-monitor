  // ---------------------------------------------------------------- omnibox: search + Ask AI (home screen)
  const omniOut = $('#omni-out'), omniBody = $('#omni-body'), omniIn = $('#omni-q');
  const omniMark = L.layerGroup().addTo(map);
  function omniShow(html) { omniBody.innerHTML = html; omniOut.classList.add('show'); }
  function omniHide() { omniOut.classList.remove('show'); }
  $('#omni-close').addEventListener('click', omniHide);
  function flyMark(lat, lon, label) {
    if (lat == null || lon == null) return;
    omniMark.clearLayers();
    L.circleMarker([lat, lon], { radius: 11, color: '#fff', weight: 2, fill: false }).addTo(omniMark);
    L.circleMarker([lat, lon], { radius: 5, color: '#3cc7ff', weight: 1, fillOpacity: 1 }).bindTooltip(esc(label || ''), { permanent: false }).addTo(omniMark);
    map.flyTo([lat, lon], Math.max(map.getZoom(), 10), { duration: 0.8 });
  }
  function omniRow(label, sub, attrs) { return `<div class="omni-row" ${attrs}><div>${label}</div>${sub ? `<div class="dim">${sub}</div>` : ''}</div>`; }
  async function omniSearch(q) {
    omniShow('<span class="spinner"></span> searching…');
    let r;
    try { r = await api(`/api/search?q=${encodeURIComponent(q)}&limit=12`); } catch (e) { return omniShow(`<p class="bad">${esc(e.message)}</p>`); }
    const R = r.results, parts = [];
    const sec = (title, rows) => rows.length ? `<h3 class="sec">${title} <span class="dim">${rows.length}</span></h3>${rows.join('')}` : '';
    parts.push(sec('UK allocation (UKFAT)', (R.ukfat || []).map((u) => `<div class="omni-row"><div><b>${esc(u.band)}</b> <span class="dim">UKFAT p.${u.page}</span></div>`
      + u.rows.map((r) => `<div class="dim">${esc(r.service)}${r.service_name ? ' · ' + esc(r.service_name) : ''} · ${esc(r.status)} · ${esc(r.footnotes)}</div>`).join('')
      + Object.entries(u.footnotes).map(([k, v]) => `<div style="margin-top:3px"><b>${esc(k)}</b> ${esc(v)}</div>`).join('') + '</div>')));
    parts.push(sec('Satellite downlinks (SatNOGS, ±50 kHz)', (R.sats || []).map((t) => omniRow(`${esc(String(t.sat))} <span class="dim">NORAD ${t.norad ?? '?'}</span>`,
      `${mhz(t.lo)} MHz ${esc(t.mode)} · ${esc(t.desc)}${t.offset_khz ? ` · ${t.offset_khz} kHz off` : ''}`, t.norad ? `data-act="sat" data-norad="${t.norad}" data-label="${esc(String(t.sat))}"` : ''))));
    parts.push(sec('Planned emitters', R.planned.map((p) => omniRow(esc(p.name), `${p.freq_mhz} MHz`, `data-act="spec" data-id="${esc(p.id)}"`))));
    parts.push(sec('Links', R.links.map((l) => omniRow(esc(l.name), `${l.freq_mhz} MHz · ${esc(l.last_verdict || '')}`, `data-act="link" data-id="${esc(l.id)}"`))));
    parts.push(sec('Coverage sites', R.sites.map((s) => omniRow(esc(s.name), `${s.freq_mhz} MHz`, `data-act="site" data-id="${esc(s.id)}"`))));
    parts.push(sec(r.freqs_mhz.length ? `Ofcom licences on ${r.freqs_mhz.join(', ')} MHz${R.place ? ` within ${R.place.radius_km} km of ${esc(R.place.name)}` : ' (UK-wide)'}` : 'Ofcom licences', R.licences.map((x) =>
      omniRow(`${esc(x.company || 'Licensee withheld')} <span class="dim">${esc(x.licence)}</span>`, `${x.freq_mhz} MHz · ${khz(x.bw_hz)} kHz · ${esc(x.product)}${x.dist_km != null ? ` · ${x.dist_km} km` : ''}`,
        `data-act="fly" data-lat="${x.lat ?? ''}" data-lon="${x.lon ?? ''}" data-label="${esc(x.company || x.licence)}"`))));
    parts.push(sec('Feed items (30 days)', R.items.map((it) => omniRow(`${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>` : esc(it.title)}`,
      `${esc(it.source || '')} · ${esc(it.domain || '')} · ${it.when ? ago(it.when) + ' ago' : ''}`,
      it.lat != null ? `data-act="fly" data-lat="${it.lat}" data-lon="${it.lon}" data-label="${esc(it.title.slice(0, 60))}"` : ''))));
    const html = parts.join('');
    omniShow((html || '<p class="dim">No matches.</p>') + `<p class="dim" style="margin-top:8px">Tip: press Ask AI to put this question to the model with all of the above as context.</p>`);
    omniBody.querySelectorAll('.omni-row[data-act]').forEach((el) => el.addEventListener('click', (e) => {
      if (e.target.closest('a')) return;
      const a = el.dataset.act, id = el.dataset.id;
      if (a === 'fly') { if (el.dataset.lat) flyMark(+el.dataset.lat, +el.dataset.lon, el.dataset.label); else omniShow(omniBody.innerHTML + '<p class="dim">Area licence: no published location.</p>'); }
      if (a === 'spec') { omniHide(); openSpectrum(id); }
      if (a === 'sat') {
        const c = map.getCenter();
        const box = document.createElement('div'); box.className = 'dim'; box.textContent = 'computing passes…'; el.appendChild(box);
        api(`/api/sat/passes?norad=${el.dataset.norad}&lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}&hours=24`).then((r) => {
          box.innerHTML = r.passes.length ? `Next passes over map centre (${c.lat.toFixed(2)}, ${c.lng.toFixed(2)}), ≥10° elevation:` + r.passes.slice(0, 6).map((q) => `<div class="mono">${fmtZ(q.start)} · ${q.duration_min} min · max ${q.max_el}° · az ${q.az_start}°→${q.az_end}°</div>`).join('') : 'No passes above 10° in the next 24 h.';
        }).catch((e) => { box.textContent = e.message; });
      }
      if (a === 'link') { omniHide(); linkDraft = null; linkRes = null; openLinks(id); }
      if (a === 'site') { omniHide(); covDraft = null; covRes = null; openCoverage(id); }
    }));
  }
  let omniAbort = null;
  async function omniAsk(q) {
    if (omniAbort) omniAbort.abort();
    omniAbort = new AbortController();
    omniShow(`<p><b>Q:</b> ${esc(q)}</p><div id="omni-ans" class="md"><span class="spinner"></span> thinking… (1–2 min on the box's CPU)</div><div id="omni-src"></div>`);
    const out = $('#omni-ans');
    let text = '', first = true, meta = null;
    try {
      const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, web: !!$('#omni-web')?.checked }), signal: omniAbort.signal });
      if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
      if (!r.ok) throw new Error(`Ask failed: HTTP ${r.status}`);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          const line = p.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          const d = JSON.parse(line.slice(6));
          if (d.meta) meta = d.meta;
          if (d.t) { if (first) { out.textContent = ''; first = false; } text += d.t; out.textContent = text; }
          if (d.error) out.innerHTML = `<p class="bad">Error: ${esc(d.error)}</p>`;
        }
      }
      if (text) out.innerHTML = renderMd(text);
      const srcs = (meta?.sources || []).filter((s) => new RegExp(`\\[${s.n}\\]`).test(text));
      const webs = (meta?.web || []).filter((w) => new RegExp(`\\[W${w.n}\\]`).test(text));
      $('#omni-src').innerHTML = (webs.length ? `<h3 class="sec">Web sources (unverified)</h3>${webs.map((w) => `<div>[W${w.n}] <a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.title)}</a></div>`).join('')}` : '') + (srcs.length ? `<h3 class="sec">Cited items</h3>${srcs.map((s) => `<div>[${s.n}] ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title)} <span class="dim">${esc(s.source || '')}</span></div>`).join('')}` : '')
        + `<p class="dim">Answer draws on CyEM status, the latest brief, ${meta?.items ?? 0} matching items${meta?.freqs_mhz?.length ? `, Ofcom licences on ${meta.freqs_mhz.join(', ')} MHz${meta.place ? ` within 30 km of ${esc(meta.place)}` : ' (UK-wide)'}` : ''} and your plan. Anything under "General knowledge" is the model's background, not CyEM data.</p>`;
    } catch (e) { if (e.name !== 'AbortError') out.innerHTML = `<p class="bad">Error: ${esc(e.message)}</p>`; }
  }
  $('#omni-form').addEventListener('submit', (e) => { e.preventDefault(); const q = omniIn.value.trim(); if (q.length >= 2) (q.startsWith('?') ? omniAsk(q.slice(1).trim()) : omniSearch(q)); });
  $('#omni-ask').addEventListener('click', () => { const q = omniIn.value.trim().replace(/^\?/, ''); if (q.length >= 2) omniAsk(q); });
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) { e.preventDefault(); omniIn.focus(); omniIn.select(); }
    if (e.key === 'Escape') omniHide();
  });
