  // ---------------------------------------------------------------- ask
  $('#ask-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = $('#ask-q').value.trim();
    if (!q) return;
    const out = $('#answer');
    out.textContent = '';
    $('#ask-btn').disabled = true;
    out.innerHTML = '<span class="spinner"></span> thinking…';
    let text = '';
    try {
      const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let first = true;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          const line = p.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          const d = JSON.parse(line.slice(6));
          if (d.t) { if (first) { out.textContent = ''; first = false; } text += d.t; out.textContent = text; out.scrollTop = out.scrollHeight; }
          if (d.error) { out.textContent = `Error: ${d.error}`; }
        }
      }
      if (text) out.innerHTML = renderMd(`**Q: ${q.replace(/\*/g, '')}**\n\n` + text);
    } catch (err) { out.textContent = `Error: ${err.message}`; }
    finally { $('#ask-btn').disabled = false; }
  });

