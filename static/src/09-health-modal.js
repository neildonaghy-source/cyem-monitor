  // ---------------------------------------------------------------- health modal
  // Planning area: Spectrum, Links, Coverage and HF share one modal with a tab strip. Each tool still renders itself
  // through openModal, so the strip is added here (by title) and survives the tools' own re-renders.
  const PLAN_TABS = [['spec', 'Spectrum', /^Spectrum/, () => openSpectrum()], ['links', 'Links', /^Link planner/, () => openLinks()],
    ['cov', 'Coverage', /^Coverage/, () => openCoverage()], ['hf', 'HF', /^HF skywave/, () => openHF()]];
  const planTabFor = (title) => PLAN_TABS.find(([, , re]) => re.test(title));
  function openPlanning(tab) {
    const t = PLAN_TABS.find(([k]) => k === tab) || PLAN_TABS.find(([k]) => k === localStorage.getItem('cyem-plan-tab')) || PLAN_TABS[0];
    t[3]();
  }
  function openModal(title, html) {
    const tab = planTabFor(title);
    if (tab) {
      try { localStorage.setItem('cyem-plan-tab', tab[0]); } catch (e) { /* ignore */ }
      html = `<div class="plantabs">${PLAN_TABS.map(([k, l]) => `<button data-plan="${k}" class="${k === tab[0] ? 'active' : ''}">${l}</button>`).join('')}<span class="dim">${esc(title)}</span></div>` + html;
      title = 'Plan';
    }
    $('#modal-title').textContent = title; $('#modal-body').innerHTML = html; $('#modal').classList.add('show');
    if (tab) $$('#modal-body .plantabs button').forEach((b) => b.addEventListener('click', () => { if (b.dataset.plan !== tab[0]) openPlanning(b.dataset.plan); }));
  }
  $('#btn-plan').addEventListener('click', () => openPlanning());
  $('#modal-close').addEventListener('click', () => $('#modal').classList.remove('show'));
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') $('#modal').classList.remove('show'); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#modal').classList.remove('show'); });
  // Health opens in a side sheet (00-head.js openSheet), so the map stays usable while it is up.
  $('#btn-health').addEventListener('click', async () => {
    openSheet('health-sheet', 'Collector health', '<p class="dim"><span class="spinner"></span> Loading…</p>');
    try {
      const [{ collectors, feeds }, ol, cfg] = await Promise.all([api('/api/collectors'), api('/api/ollama'), api('/api/config')]);
      const rows = collectors.map((c) => `<tr><td><b>${esc(c.name)}</b><div class="dim">${esc(c.description)}</div></td><td>${esc(c.domain)}</td><td class="mono">${Math.round(c.interval_s / 60)}m</td><td class="${c.running ? 'warn' : c.ok === 1 ? 'ok' : c.ok === 0 ? 'bad' : ''}">${c.running ? 'running' : c.ok === 1 ? 'ok' : c.ok === 0 ? 'FAIL' : c.enabled ? 'pending' : 'off'}</td><td class="mono" title="${esc(c.last_finished)}">${c.last_finished ? ago(c.last_finished) + ' ago' : '–'}</td><td class="mono">${c.count ?? ''}</td><td>${esc(c.message || '')}</td></tr>`).join('');
      const bad = feeds.filter((f) => f.fail_count > 0).map((f) => `<tr><td class="mono" style="word-break:break-all">${esc(f.url)}</td><td class="bad">${f.fail_count}</td><td>${esc(f.last_error || '')}</td></tr>`).join('');
      const olTxt = ol.reachable ? `<span class="ok">reachable</span> at ${esc(ol.url)} · model ${esc(ol.model)} ${ol.model_present ? '<span class="ok">present</span>' : '<span class="bad">NOT FOUND</span>'} · loaded: ${esc((ol.loaded || []).map((m) => m.name).join(', ') || 'none')}` : `<span class="bad">unreachable</span> ${esc(ol.error || '')}`;
      const keysTxt = Object.entries(cfg.keys || {}).map(([k, v]) => `<span class="${v ? 'ok' : 'dim'}">${esc(k)} ${v ? '✓' : '—'}</span>`).join(' · ');
      openSheet('health-sheet', 'Collector health', `<p><b>Ollama:</b> ${olTxt}</p><p><b>Optional keys:</b> ${keysTxt} <span class="dim">(set in ~/cyem/.env, then docker compose up -d)</span></p><table class="grid"><tr><th>Collector</th><th>Domain</th><th>Every</th><th>State</th><th>Last</th><th>Count</th><th>Message</th></tr>${rows}</table>
        <h3 class="sec">Failing feeds (${feeds.filter((f) => f.fail_count > 0).length} of ${feeds.length})</h3><table class="grid"><tr><th>Feed</th><th>Fails</th><th>Error</th></tr>${bad || '<tr><td colspan=3 class="ok">all feeds healthy</td></tr>'}</table>
        <p style="margin-top:10px"><button id="run-all">Run all collectors now</button></p>`);
      $('#run-all').addEventListener('click', async () => { await api('/api/collect/all', { method: 'POST' }); $('#run-all').textContent = 'started'; setTimeout(() => { refreshStatus(); loadLayers(); loadFeed(); }, 20000); });
    } catch (e) { openSheet('health-sheet', 'Collector health', `<p class="bad">${esc(e.message)}</p>`); }
  });

