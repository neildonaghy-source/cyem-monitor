  // ---------------------------------------------------------------- brief
  function sanitize(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach((n) => n.remove());
    doc.querySelectorAll('*').forEach((n) => { for (const a of Array.from(n.attributes)) if (/^on/i.test(a.name) || (a.name === 'href' && /^javascript:/i.test(a.value))) n.removeAttribute(a.name); });
    return doc.body.innerHTML;
  }
  function renderMd(md) {
    let html = marked.parse(md || '', { gfm: true, breaks: false });
    html = sanitize(html).replace(/\[(\d{1,3})\]/g, '<span class="cite" title="source item in the brief context">[$1]</span>');
    return html;
  }
  async function loadBrief(id) {
    try {
      const { brief } = await api(id ? `/api/briefs/${id}` : '/api/briefs/latest');
      if (!brief) { $('#brief').innerHTML = '<div class="empty">No brief yet. Press Regenerate once collectors have run.</div>'; return; }
      state.briefId = brief.id;
      $('#brief').innerHTML = renderMd(brief.content);
      const { briefs } = await api('/api/briefs?limit=30');
      const opts = briefs.map((b) => `<option value="${b.id}" ${b.id === brief.id ? 'selected' : ''}>${fmtZ(b.created_at)} · ${esc(b.kind)}</option>`).join('');
      $('#brief-meta').innerHTML = `<span>${esc(brief.model)}</span><span>·</span><span>${brief.item_count} items</span><span>·</span><span>${Math.round(brief.duration_s)}s</span><select id="brief-hist">${opts}</select>`;
      $('#brief-hist').addEventListener('change', (e) => loadBrief(parseInt(e.target.value)));
    } catch (e) { $('#brief-notice').innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  }
  let pollTimer;
  async function pollBrief() {
    try {
      const st = await api('/api/briefs/state');
      if (st.generating) {
        $('#brief-notice').innerHTML = `<div class="notice"><span class="spinner"></span> Generating brief with ${esc((state.status?.brief || {}).model || 'Ollama')} on CPU — typically 2–5 minutes. Started ${ago(st.started_at)} ago.</div>`;
        $('#btn-gen').disabled = true;
        clearTimeout(pollTimer); pollTimer = setTimeout(pollBrief, 5000);
      } else {
        $('#btn-gen').disabled = false;
        $('#brief-notice').innerHTML = st.last_error ? `<div class="notice err">Last generation failed: ${esc(st.last_error)}</div>` : '';
        if (state.wasGenerating) { await loadBrief(); refreshStatus(); }
        state.wasGenerating = false;
      }
      state.wasGenerating = st.generating;
    } catch (e) { /* ignore */ }
  }
  $('#btn-gen').addEventListener('click', async () => {
    try { await api('/api/briefs/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hours: 24 }) }); state.wasGenerating = true; pollBrief(); }
    catch (e) { $('#brief-notice').innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  });

