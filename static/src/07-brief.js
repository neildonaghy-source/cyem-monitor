  // ---------------------------------------------------------------- brief
  // sanitize:begin (tests/ui/sanitize_check.py runs this block on its own)
  // Model output (briefs, Ask) is rendered as markdown and then cleaned against an ALLOWLIST with DOMPurify
  // (static/vendor/purify.min.js). Feed text and web results reach the model, so treat its HTML as hostile.
  // Without DOMPurify the text is shown escaped, never as markup. The page's CSP (script-src 'self',
  // base-uri 'none') is the second line of defence.
  const MD_TAGS = ['p', 'br', 'hr', 'strong', 'b', 'em', 'i', 'del', 's', 'code', 'pre', 'blockquote', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'span', 'sup', 'sub'];
  const MD_ATTR = ['href', 'title', 'class', 'colspan', 'rowspan', 'align', 'start'];
  if (window.DOMPurify && DOMPurify.addHook) {
    DOMPurify.addHook('afterSanitizeAttributes', (n) => {
      if (n.tagName === 'A' && n.getAttribute('href')) { n.setAttribute('target', '_blank'); n.setAttribute('rel', 'noopener noreferrer'); }
    });
  }
  function sanitize(html) {
    if (!window.DOMPurify) return esc(html);
    return DOMPurify.sanitize(html, { ALLOWED_TAGS: MD_TAGS, ALLOWED_ATTR: [...MD_ATTR, 'target', 'rel'],
      ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#|\/(?!\/))/i, ALLOW_DATA_ATTR: false });
  }
  // sanitize:end
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
      $('#brief-meta').innerHTML = `<span>${esc(brief.model)}</span><span>·</span><span>${brief.item_count} items</span><span>·</span><span>${Math.round(brief.duration_s)}s</span><select id="brief-hist" aria-label="Earlier briefs">${opts}</select>`;
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

