  // ---------------------------------------------------------------- status pills
  function pill(id, lbl, val, cls, title) { return `<div class="pill ${cls || ''}" data-p="${id}" title="${esc(title || '')}"><span class="lbl">${esc(lbl)}</span><b>${esc(val)}</b></div>`; }
  function renderPills(s) {
    const sw = s.spaceweather || {};
    const kp = sw.kp;
    const kpCls = kp == null ? '' : kp >= 6 ? 'bad' : kp >= 4 ? 'warn' : 'ok';
    const sc = sw.scales || {};
    const lvl = (c) => (sc[c] && sc[c].level != null) ? String(sc[c].level) : '?';
    const maxLvl = Math.max(...['R', 'S', 'G'].map((c) => parseInt(lvl(c)) || 0));
    const scCls = maxLvl >= 3 ? 'bad' : maxLvl >= 1 ? 'warn' : 'ok';
    const hf = s.hf || {};
    const gn = s.gnss || {};
    const out = s.outages || {};
    const nCrit = (out.countries_critical || []).length;
    const kev = s.kev || {};
    const rw = s.ransomware || {};
    const br = s.brief || {};
    const briefVal = br.generating ? 'generating…' : (br.latest_at ? ago(br.latest_at) + ' ago' : 'none');
    const html = [
      pill('sw', 'Kp', kp == null ? '–' : kp.toFixed(1), kpCls, 'Planetary K-index (NOAA SWPC). Click for space weather detail'),
      pill('sw', 'R/S/G', `${lvl('R')}/${lvl('S')}/${lvl('G')}`, scCls, 'NOAA scales now: radio blackout / solar radiation / geomagnetic storm'),
      pill('sw', 'Flare', sw.max_flare_24h || '–', (sw.max_flare_24h || '').startsWith('X') ? 'bad' : (sw.max_flare_24h || '').startsWith('M') ? 'warn' : '', 'Largest GOES X-ray flare in 24h'),
      pill('hf', 'HF', hf.solarflux ? `SFI ${hf.solarflux} · geomag ${(hf.geomagfield || '?').toLowerCase()}` : '–', hf.geomagfield && /storm|unsettled|^active/i.test(hf.geomagfield) ? 'warn' : hf.geomagfield ? 'ok' : '', 'SFI = 10.7 cm solar flux (higher = better HF propagation on the high bands). Geomag = geomagnetic field state from hamqsl: inactive / quiet = calm (good), unsettled / active / storm = disturbed HF and GNSS. Click for band conditions'),
      ...(s.aurora ? [pill('sw', 'Aurora', `N ${s.aurora.max_north ?? 0}% · S ${s.aurora.max_south ?? 0}%`, Math.max(s.aurora.max_north || 0, s.aurora.max_south || 0) >= 50 ? 'bad' : Math.max(s.aurora.max_north || 0, s.aurora.max_south || 0) >= 25 ? 'warn' : 'ok', `OVATION aurora probability maxima, forecast ${s.aurora.forecast_time || ''}`)] : []),
      ...(s.drap ? [pill('sw', 'D-RAP', s.drap.max_mhz > 0 ? `${s.drap.max_mhz} MHz` : 'clear', s.drap.max_mhz >= 15 ? 'bad' : s.drap.max_mhz > 0 ? 'warn' : 'ok', `Highest HF frequency affected by D-region absorption (NOAA D-RAP, valid ${s.drap.valid_at || ''})`)] : []),
      pill('gnss', 'GNSS', gn.date ? `${gn.high} high` : '–', gn.high >= 40 ? 'bad' : gn.high >= 15 ? 'warn' : gn.date ? 'ok' : '', `GNSS interference hexes for ${gn.date || '?'} (gpsjam)`),
      pill('out', 'Outages', out.alerts_24h != null ? `${nCrit} critical` : '–', nCrit >= 3 ? 'bad' : nCrit >= 1 ? 'warn' : out.alerts_24h != null ? 'ok' : '', 'Countries with critical IODA outage alerts in 24h'),
      pill('kev', 'KEV 7d', kev.added_7d != null ? kev.added_7d : '–', kev.added_7d >= 8 ? 'warn' : 'info', 'CISA KEV entries added in 7 days'),
      pill('rw', 'Ransom 7d', rw.victims_7d != null ? rw.victims_7d : '–', 'info', 'Victims claimed on leak sites in 7 days (ransomware.live)'),
      ...(s.opencti ? [pill('octi', 'OpenCTI', `${s.opencti.reports_24h ?? 0} rep · ${s.opencti.indicators_24h ?? 0} ind`, (s.opencti.errors || []).length ? 'warn' : 'info', `OpenCTI ${s.opencti.version || ''}: reports and new indicators in 24h. Click for detail`)] : []),
      pill('items', 'Sev4+ 24h', (s.counts || {}).high_24h ?? '–', ((s.counts || {}).high_24h || 0) >= 10 ? 'warn' : 'info', 'Items with severity 4 or 5 in 24h'),
      pill('brief', 'Brief', briefVal, br.generating ? 'warn' : br.last_error ? 'bad' : 'info', br.last_error || `Scheduled at ${(br.hours || []).map((h) => String(h).padStart(2, '0') + ':00').join(', ')} ${s.tz || ''}`),
    ].join('');
    $('#pills').innerHTML = html;
    $$('#pills .pill').forEach((p) => p.addEventListener('click', () => onPill(p.dataset.p)));
  }
  function onPill(id) {
    const s = state.status || {};
    if (id === 'sw') return showSpaceWeather(s);
    if (id === 'hf') return showHF(s.hf);
    if (id === 'gnss') { map.setView([45, 30], 4); const cb = $$('#layers input')[0]; if (!cb.checked) cb.click(); return; }
    if (id === 'out') { state.dom = 'infra'; setTab('infra'); state.q = ''; $('#q').value = ''; loadFeed(); showRail(true); return; }
    if (id === 'kev') { state.dom = 'cyber'; setTab('cyber'); state.q = 'KEV'; $('#q').value = 'KEV'; loadFeed(); showRail(true); return; }
    if (id === 'rw') { state.dom = 'cyber'; setTab('cyber'); state.q = 'ransomware'; $('#q').value = 'ransomware'; loadFeed(); showRail(true); return; }
    if (id === 'items') { $('#hi-only').checked = true; state.hiOnly = true; state.hours = 24; $('#hours').value = '24'; loadFeed(); showRail(true); return; }
    if (id === 'brief') { showSide(true); return; }
    if (id === 'octi') { showOpenCTI(); return; }
  }
  async function showOpenCTI() {
    let data;
    try { ({ data } = await api('/api/layers/opencti')); } catch (e) { return openModal('OpenCTI', `<p class="bad">${esc(e.message)}</p>`); }
    if (!data) return openModal('OpenCTI', '<p class="muted">Not configured. Set OPENCTI_URL and OPENCTI_TOKEN in ~/cyem/.env.</p>');
    const reps = (data.reports || []).map((r) => `<tr><td class="mono">${fmtZ(r.published)}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a></td><td>${esc((r.types || []).join(', '))}</td><td>${esc((r.labels || []).join(', '))}</td></tr>`).join('');
    const inds = (data.top_indicators || []).map((i) => `<tr><td class="mono">${i.score ?? ''}</td><td>${esc(i.type)}</td><td><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.name || i.pattern)}</a></td><td>${esc((i.labels || []).join(', '))}</td><td class="mono">${fmtZ(i.valid_until)}</td></tr>`).join('');
    const sets = (data.intrusion_sets || []).map((x) => `<tr><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a><div class="dim">${esc((x.aliases || []).join(', '))}</div></td><td class="mono">${fmtZ(x.modified)}</td><td>${esc(x.description || '')}</td></tr>`).join('');
    openModal(`OpenCTI ${esc(data.version || '')} — ${esc(data.url || '')}`, `
      ${(data.errors || []).length ? `<div class="notice err">${esc(data.errors.join(' · '))}</div>` : ''}
      <div class="kv"><span class="k">Reports 24h</span><span>${data.reports_24h ?? 0}</span><span class="k">New indicators 24h</span><span>${data.indicators_24h ?? 0} — ${esc((data.indicator_types || []).map((t) => `${t[0]} ${t[1]}`).join(', '))}</span><span class="k">Top labels</span><span>${esc((data.indicator_labels || []).map((t) => `${t[0]} ${t[1]}`).join(', '))}</span><span class="k">Fetched</span><span class="mono">${fmtZ(data.fetched_at)}</span></div>
      <h3 class="sec">Recent reports</h3><table class="grid"><tr><th>Published</th><th>Report</th><th>Type</th><th>Labels</th></tr>${reps || '<tr><td colspan=4 class="muted">none</td></tr>'}</table>
      <h3 class="sec">Highest-scored new indicators (24h)</h3><table class="grid"><tr><th>Score</th><th>Type</th><th>Indicator</th><th>Labels</th><th>Valid until</th></tr>${inds || '<tr><td colspan=5 class="muted">none</td></tr>'}</table>
      <h3 class="sec">Recently modified intrusion sets</h3><table class="grid"><tr><th>Set</th><th>Modified</th><th>Description</th></tr>${sets || '<tr><td colspan=3 class="muted">none</td></tr>'}</table>`);
  }
  function showSpaceWeather(s) {
    const sw = s.spaceweather || {};
    const series = sw.kp_series || [];
    const bars = series.map((k) => `<i class="${k.kp >= 7 ? 'k7' : k.kp >= 6 ? 'k6' : k.kp >= 5 ? 'k5' : ''}" style="height:${Math.max(4, k.kp / 9 * 100)}%" title="${esc(k.t)} Kp ${k.kp}"></i>`).join('');
    const sc = sw.scales || {}, p24 = sw.past24h || {}, pred = sw.predicted || {};
    const scaleRow = (c, name) => `<tr><td>${name}</td><td class="mono">${esc(sc[c]?.level ?? '?')} ${esc(sc[c]?.text || '')}</td><td class="mono">${esc(p24[c]?.level ?? '?')} ${esc(p24[c]?.text || '')}</td></tr>`;
    const predRows = Object.values(pred).map((v) => `<tr><td>${esc(v.date)}</td><td class="mono">G${esc(v.G)}</td><td class="mono">${esc(v.R_minor_prob)}% / ${esc(v.R_major_prob)}%</td><td class="mono">${esc(v.S_prob)}%</td></tr>`).join('');
    const flares = (sw.flares || []).map((f) => `<tr><td class="mono">${esc(f.class)}</td><td>${fmtZ(f.begin)}</td><td>${esc(f.max_time || '')}</td><td>${esc(f.region || '')}</td></tr>`).join('');
    const alerts = (sw.alerts || []).map((a) => `<tr><td class="mono">${fmtZ(a.issued)}</td><td>${esc(a.headline)}</td></tr>`).join('');
    const w = sw.solar_wind || {};
    openModal('Space weather (NOAA SWPC)', `
      <div class="kv"><span class="k">Kp now</span><span class="mono">${sw.kp ?? '–'} (24h max ${sw.kp_max_24h ?? '–'})</span><span class="k">F10.7</span><span class="mono">${sw.f107 ?? '–'} sfu</span><span class="k">Solar wind</span><span class="mono">${w.speed_kms ?? '–'} km/s, Bt ${w.bt ?? '–'} nT, Bz ${w.bz ?? '–'} nT</span><span class="k">Updated</span><span class="mono">${fmtZ(sw.updated)}</span></div>
      <h3 class="sec">Kp, last ${series.length * 3} hours</h3><div class="kpbars">${bars || '<span class="muted">no data</span>'}</div>
      <h3 class="sec">NOAA scales</h3><table class="grid"><tr><th>Scale</th><th>Now</th><th>Max 24h</th></tr>${scaleRow('R', 'R radio blackout')}${scaleRow('S', 'S solar radiation')}${scaleRow('G', 'G geomagnetic')}</table>
      <h3 class="sec">3-day outlook</h3><table class="grid"><tr><th>Day</th><th>G</th><th>R1-2 / R3+ prob</th><th>S1+ prob</th></tr>${predRows || '<tr><td colspan=4 class="muted">no forecast</td></tr>'}</table>
      <h3 class="sec">X-ray flares, 3 days</h3><table class="grid"><tr><th>Class</th><th>Begin</th><th>Peak</th><th>Region</th></tr>${flares || '<tr><td colspan=4 class="muted">none recorded</td></tr>'}</table>
      <h3 class="sec">Alerts, watches, warnings</h3><table class="grid">${alerts || '<tr><td class="muted">none in 3 days</td></tr>'}</table>
      <p class="dim">Operational reading: R scale = HF absorption on the sunlit hemisphere; G scale = GNSS accuracy, HF auroral absorption and geomagnetically induced currents; S scale = SATCOM and polar HF.</p>`);
  }
  function showHF(hf) {
    if (!hf) return openModal('HF conditions', '<p class="muted">No data yet.</p>');
    const bands = Object.entries(hf.bands || {}).map(([b, v]) => `<div class="band"><b>${esc(b)}</b>day <span class="cond-${esc(v.day)}">${esc(v.day)}</span> · night <span class="cond-${esc(v.night)}">${esc(v.night)}</span></div>`).join('');
    const vhf = (hf.vhf || []).map((v) => `<tr><td>${esc(v.name)}</td><td>${esc(v.location || '')}</td><td>${esc(v.value)}</td></tr>`).join('');
    openModal('HF and VHF conditions (hamqsl.com, N0NBH)', `
      <div class="kv"><span class="k">Solar flux</span><span class="mono">${esc(hf.solarflux)}</span><span class="k">Sunspots</span><span class="mono">${esc(hf.sunspots)}</span><span class="k">A / K index</span><span class="mono">${esc(hf.aindex)} / ${esc(hf.kindex)}</span><span class="k">X-ray</span><span class="mono">${esc(hf.xray)}</span><span class="k">Geomagnetic field</span><span>${esc(hf.geomagfield)}</span><span class="k">Signal noise</span><span>${esc(hf.signalnoise)}</span><span class="k">MUF</span><span class="mono">${esc(hf.muf || '–')}</span><span class="k">Aurora</span><span class="mono">${esc(hf.aurora)} (lat ${esc(hf.latdegree)})</span><span class="k">Updated</span><span>${esc(hf.updated)}</span></div>
      <h3 class="sec">Band conditions</h3><div class="bands">${bands}</div>
      <h3 class="sec">VHF</h3><table class="grid"><tr><th>Phenomenon</th><th>Location</th><th>State</th></tr>${vhf}</table>`);
  }

