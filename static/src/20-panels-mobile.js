  // ---------------------------------------------------------------- panels / mobile
  const mobile = () => window.matchMedia('(max-width: 900px)').matches;
  const panels = (() => { try { return { rail: false, side: false, ...JSON.parse(localStorage.getItem('cyem.panels') || '{}') }; } catch { return { rail: false, side: false }; } })();
  function showRail(on, remember = true) { $('#rail').classList.toggle('hidden', !on); $('#btn-rail').classList.toggle('active', on); if (remember && !mobile()) { panels.rail = on; saveLs('cyem.panels', panels); } setTimeout(() => map.invalidateSize(), 50); }
  function showSide(on, remember = true) { $('#side').classList.toggle('hidden', !on); $('#btn-side').classList.toggle('active', on); if (remember && !mobile()) { panels.side = on; saveLs('cyem.panels', panels); } setTimeout(() => map.invalidateSize(), 50); }
  $('#btn-rail').addEventListener('click', () => showRail($('#rail').classList.contains('hidden')));
  $('#btn-side').addEventListener('click', () => showSide($('#side').classList.contains('hidden')));
  $$('#mobnav button[data-view]').forEach((b) => b.addEventListener('click', () => {
    $$('#mobnav button[data-view]').forEach((x) => x.classList.toggle('active', x === b));
    showRail(b.dataset.view === 'rail'); showSide(b.dataset.view === 'side');
    if (b.dataset.view === 'map') setTimeout(() => map.invalidateSize(), 250);
  }));
  // Phone layout hides the top-bar buttons; the Tools sheet exposes the same actions.
  const MOB_TOOLS = [['btn-plan', 'Plan', 'Spectrum, links, coverage, HF'], ['btn-emo', 'EMO', 'Red / blue ES, EA and EP'], ['btn-sdr', 'SDR', 'Live receiver and spectrum sweeps'], ['btn-health', 'Health', 'Collectors and data status']];
  $('#mob-tools').addEventListener('click', () => {
    const emoOn = !!document.getElementById('emo-chip');
    const item = ([id, t, d]) => `<button data-go="${id}"><b>${t}</b><span class="dim">${d}</span></button>`;
    const ar = window.webkit?.messageHandlers?.cyem ? '<button data-native="ar"><b>AR view (camera)</b><span class="dim">Emitters around you over the camera image</span></button>' : '';
    openModal('Tools', `<div class="mobtools">
      ${emoOn ? `<div class="mobgrp"><span class="lbl">EMO</span>${item(['emo-panel', 'EMO panel', 'Scenario, time, layers, COAs and Ask'])}${ar}${item(['emo-off', 'Hide EMO', 'Clear the scenario from this device; it stays on the box'])}</div>` : ''}
      <div class="mobgrp"><span class="lbl">Map</span><button data-layers><b>Map layers</b><span class="dim">Basemap, feeds and overlays</span></button></div>
      <div class="mobgrp compact"><span class="lbl">Tools</span>${MOB_TOOLS.filter(([id]) => $('#' + id) && !(emoOn && id === 'btn-emo')).map(item).join('')}${emoOn ? '' : ar}
      <a href="/api/export/plan.docx" class="btnlink" download><b>Export plan (Word)</b></a></div></div>`);
    $$('#modal-body .mobtools button').forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.native) { $('#modal').classList.remove('show'); window.webkit.messageHandlers.cyem.postMessage(b.dataset.native); }
      else if (b.dataset.go === 'emo-panel') { openEMO(); }
      else if (b.dataset.go === 'emo-off') { $('#modal').classList.remove('show'); emoOff(); }
      else if (b.hasAttribute('data-layers')) { $('#modal').classList.remove('show'); const lc = $('#layers'); lc.classList.remove('collapsed'); const tg = $('#layers-toggle'); if (tg) tg.textContent = 'hide'; try { localStorage.setItem('cyem-layers', 'show'); } catch (e) { /* ignore */ } }
      else $('#' + b.dataset.go).click();
    }));
  });
  if (mobile()) { showRail(false, false); showSide(false, false); } else { showRail(panels.rail, false); showSide(panels.side, false); }

