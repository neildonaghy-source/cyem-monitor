  // ---------------------------------------------------------------- refresh loops
  async function refreshStatus() {
    try { state.status = await api('/api/status'); renderPills(state.status); } catch (e) { console.warn(e); }
  }
  function tickClock() { const d = new Date(); $('#clock').textContent = d.toISOString().slice(11, 16) + 'Z · ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + ' local'; }
  tickClock(); setInterval(tickClock, 15000);
  refreshStatus(); loadFeed(); loadBrief(); pollBrief(); loadLayers();
  let minute = 0;
  setInterval(refreshStatus, 60000);
  setInterval(loadFeed, 150000);
  setInterval(() => { minute += 1; loadLayers(minute); }, 60000);
})();
