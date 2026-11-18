/* CyEM Monitor UI — vanilla JS, Leaflet, marked. No build step. */
(() => {
  'use strict';
  const BUILD = '2026-11-18c';
  // Shared start-up setup (Map layers > Save this setup as the start-up default). Applied once per app launch;
  // changes during a session stand until the app is closed, unless saved as the new default.
  const START = (() => {
    const s = window.CYEM_STARTUP; if (!s || !s.saved_at) return null;
    try {
      if (sessionStorage.getItem('cyem-startup') === s.saved_at) return null;
      const phone = matchMedia('(max-width: 900px)').matches;
      for (const [k, v] of Object.entries(s.ls || {})) {
        if (phone && (k === 'cyem-layers' || k === 'cyem.panels')) continue;  // panel layout stays per device on phones
        if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v);
      }
      sessionStorage.setItem('cyem-startup', s.saved_at);
    } catch (e) { return null; }
    return s;
  })();
  let startViewHold = !!START?.view;  // keep the saved view instead of EMO's first auto-fit
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const flag = (iso2) => (iso2 && /^[A-Za-z]{2}$/.test(iso2)) ? String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65)) : '';
  const ago = (iso) => {
    if (!iso) return '';
    const d = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(d)) return '';
    if (d < 0) return 'now';
    if (d < 60) return `${Math.floor(d)}s`;
    if (d < 3600) return `${Math.floor(d / 60)}m`;
    if (d < 86400) return `${Math.floor(d / 3600)}h`;
    return `${Math.floor(d / 86400)}d`;
  };
  const fmtZ = (iso) => iso ? iso.replace('T', ' ').replace(/:\d\dZ$/, 'Z') : '';
  // EMO scenario space: 'default' is shared across devices; 'device' keeps a private space on this device
  function wsId() {
    if (localStorage.getItem('cyem-ws-mode') !== 'device') return 'default';
    let v = localStorage.getItem('cyem-ws'); if (!v) { v = 'd' + Math.random().toString(36).slice(2, 9); localStorage.setItem('cyem-ws', v); }
    return v;
  }
  // Two-tap confirm. The Mac and iPhone app web views do not show window.confirm() (it returns false), so deletes
  // never ran there. First tap arms the button (red, "Confirm" for 4 s); the second tap goes ahead.
  function armConfirm(btn, label = 'Confirm') {
    if (!btn) return true;
    if (btn.dataset.armed === '1') { delete btn.dataset.armed; btn.classList.remove('armed'); return true; }
    const txt = btn.textContent; btn.dataset.armed = '1'; btn.textContent = label; btn.classList.add('armed');
    setTimeout(() => { if (btn.dataset.armed === '1') { delete btn.dataset.armed; btn.textContent = txt; btn.classList.remove('armed'); } }, 4000);
    return false;
  }
  const _fetch = window.fetch.bind(window);
  window.fetch = (u, o = {}) => { if (typeof u === 'string' && u.startsWith('/api/')) o = { ...o, headers: { ...(o.headers || {}), 'X-CyEM-WS': wsId() } }; return _fetch(u, o); };
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (r.status === 401) {                  // internet session expired or signed out elsewhere: back to the log-in page
      location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
      throw new Error(`${path}: sign in required`);
    }
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  const COLOURS = { cyber: '#3cc7ff', em: '#f3b23e', infra: '#2bb9a8', osint: '#b48cff' };
  const state = { dom: 'all', q: '', hiOnly: false, hours: 48, country: null, status: null, briefId: null, layerCounts: {} };

