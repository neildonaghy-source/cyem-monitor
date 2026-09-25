  // ---------------------------------------------------------------- health modal
  function openModal(title, html) { $('#modal-title').textContent = title; $('#modal-body').innerHTML = html; $('#modal').classList.add('show'); }
  $('#modal-close').addEventListener('click', () => $('#modal').classList.remove('show'));
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') $('#modal').classList.remove('show'); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#modal').classList.remove('show'); });
  $('#btn-health').addEventListener('click', async () => {
    try {
      const [{ collectors, feeds }, ol, cfg] = await Promise.all([api('/api/collectors'), api('/api/ollama'), api('/api/config')]);
      const rows = collectors.map((c) => `<tr><td><b>${esc(c.name)}</b><div class="dim">${esc(c.description)}</div></td><td>${esc(c.domain)}</td><td class="mono">${Math.round(c.interval_s / 60)}m</td><td class="${c.running ? 'warn' : c.ok === 1 ? 'ok' : c.ok === 0 ? 'bad' : ''}">${c.running ? 'running' : c.ok === 1 ? 'ok' : c.ok === 0 ? 'FAIL' : c.enabled ? 'pending' : 'off'}</td><td class="mono" title="${esc(c.last_finished)}">${c.last_finished ? ago(c.last_finished) + ' ago' : '–'}</td><td class="mono">${c.count ?? ''}</td><td>${esc(c.message || '')}</td></tr>`).join('');
      const bad = feeds.filter((f) => f.fail_count > 0).map((f) => `<tr><td class="mono" style="word-break:break-all">${esc(f.url)}</td><td class="bad">${f.fail_count}</td><td>${esc(f.last_error || '')}</td></tr>`).join('');
      const olTxt = ol.reachable ? `<span class="ok">reachable</span> at ${esc(ol.url)} · model ${esc(ol.model)} ${ol.model_present ? '<span class="ok">present</span>' : '<span class="bad">NOT FOUND</span>'} · loaded: ${esc((ol.loaded || []).map((m) => m.name).join(', ') || 'none')}` : `<span class="bad">unreachable</span> ${esc(ol.error || '')}`;
      const keysTxt = Object.entries(cfg.keys || {}).map(([k, v]) => `<span class="${v ? 'ok' : 'dim'}">${esc(k)} ${v ? '✓' : '—'}</span>`).join(' · ');
      openModal('Collector health', `<p><b>Ollama:</b> ${olTxt}</p><p><b>Optional keys:</b> ${keysTxt} <span class="dim">(set in ~/cyem/.env, then docker compose up -d)</span></p><table class="grid"><tr><th>Collector</th><th>Domain</th><th>Every</th><th>State</th><th>Last</th><th>Count</th><th>Message</th></tr>${rows}</table>
        <h3 class="sec">Failing feeds (${feeds.filter((f) => f.fail_count > 0).length} of ${feeds.length})</h3><table class="grid"><tr><th>Feed</th><th>Fails</th><th>Error</th></tr>${bad || '<tr><td colspan=3 class="ok">all feeds healthy</td></tr>'}</table>
        <p style="margin-top:10px"><button id="run-all">Run all collectors now</button></p>`);
      $('#run-all').addEventListener('click', async () => { await api('/api/collect/all', { method: 'POST' }); $('#run-all').textContent = 'started'; setTimeout(() => { refreshStatus(); loadLayers(); loadFeed(); }, 20000); });
    } catch (e) { openModal('Collector health', `<p class="bad">${esc(e.message)}</p>`); }
  });

