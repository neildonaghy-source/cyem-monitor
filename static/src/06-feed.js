  // ---------------------------------------------------------------- feed
  function setTab(dom) { $$('#dom-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.dom === dom)); }
  $$('#dom-tabs button').forEach((b) => b.addEventListener('click', () => { state.dom = b.dataset.dom; state.country = null; setTab(state.dom); loadFeed(); }));
  let qTimer;
  $('#q').addEventListener('input', (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); loadFeed(); }, 300); });
  $('#hi-only').addEventListener('change', (e) => { state.hiOnly = e.target.checked; loadFeed(); });
  $('#hours').addEventListener('change', (e) => { state.hours = parseInt(e.target.value); loadFeed(); });
  const HOT = new Set(['zero-day', 'kev', 'ransomware', 'apt', 'ics', 'gnss', 'ew', 'satcom', 'cable', 'outage', 'bgp', 'uk']);
  async function loadFeed() {
    const p = new URLSearchParams({ hours: state.hours, limit: 200 });
    if (state.dom !== 'all') p.set('domain', state.dom);
    if (state.q) p.set('q', state.q);
    if (state.hiOnly) p.set('min_severity', 3);
    if (state.country) p.set('country', state.country);
    let data;
    try { data = await api('/api/items?' + p); } catch (e) { $('#feed').innerHTML = `<div class="empty">Feed unavailable: ${esc(e.message)}</div>`; return; }
    const rows = data.items || [];
    if (!rows.length) { $('#feed').innerHTML = `<div class="empty">Nothing matches.${state.country ? ` <a href="#" id="clear-country">Clear country filter</a>` : ''}</div>`; $('#clear-country')?.addEventListener('click', (e) => { e.preventDefault(); state.country = null; loadFeed(); }); return; }
    const head = state.country ? `<div class="notice">Filtered to ${flag(state.country)} ${esc(rows[0].country_name || state.country)} · <a href="#" id="clear-country">clear</a></div>` : '';
    $('#feed').innerHTML = head + rows.map((it) => `
      <div class="item s${it.severity}" data-id="${esc(it.id)}" data-lat="${it.lat ?? ''}" data-lon="${it.lon ?? ''}">
        <div class="sev" title="severity ${it.severity}"></div>
        <div>
          <div class="meta"><span class="dom ${esc(it.domain)}">${esc(it.domain)}</span><span>${esc(it.source)}</span><span>·</span><span title="${esc(it.published_at)}">${ago(it.published_at)}</span>${it.country ? `<span title="${esc(it.country_name || it.country)}">${flag(it.country)}</span>` : ''}${it.kind !== 'news' ? `<span class="dim">${esc(it.kind)}</span>` : ''}</div>
          <div class="title"><a href="${esc(it.url || '#')}" target="_blank" rel="noopener">${esc(it.title)}</a></div>
          <div class="summary">${esc(it.summary || '')}${it.extra && it.extra.epss != null ? ` <span class="mono">EPSS ${Number(it.extra.epss).toFixed(2)}</span>` : ''}</div>
          <div class="tags">${(it.tags || []).slice(0, 6).map((t) => `<span class="tag ${HOT.has(t) ? 'hot' : ''}">${esc(t)}</span>`).join('')}${it.lat != null ? '<span class="tag locate" style="cursor:pointer">◎ locate</span>' : ''}</div>
        </div>
      </div>`).join('');
    $('#clear-country')?.addEventListener('click', (e) => { e.preventDefault(); state.country = null; loadFeed(); });
    $$('#feed .item').forEach((el) => {
      el.addEventListener('click', (e) => { if (e.target.closest('a') || e.target.classList.contains('locate')) return; el.classList.toggle('open'); });
      el.querySelector('.locate')?.addEventListener('click', () => {
        const lat = parseFloat(el.dataset.lat), lon = parseFloat(el.dataset.lon);
        if (isFinite(lat)) { map.flyTo([lat, lon], Math.max(map.getZoom(), 4), { duration: .6 }); const t = el.querySelector('.title').textContent; L.popup().setLatLng([lat, lon]).setContent(`<h4>${esc(t)}</h4>`).openOn(map); }
      });
    });
  }

