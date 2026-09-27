  // ---------------------------------------------------------------- map + basemaps
  const map = L.map('map', { zoomControl: false, worldCopyJump: false, minZoom: 2, maxZoom: 13, attributionControl: true, preferCanvas: true, renderer: L.canvas({ padding: 0.3 }) })
    .setView([38, 18], 3);
  map.setMaxBounds([[-85, -200], [85, 200]]);
  window.__cyemMap = map; // test hook for tests/ui/layer_click.py
  if (START?.view) map.setView([START.view.lat, START.view.lon], Math.max(2, START.view.z - (innerWidth < 700 ? 1 : 0)), { animate: false });
  L.control.zoom({ position: 'topright' }).addTo(map);
  const BASEMAPS = {
    esri_dark: { label: 'Esri dark grey', make: () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { attribution: 'Tiles &copy; Esri, HERE, Garmin, OSM contributors', maxNativeZoom: 16, noWrap: true }) },
    esri_imagery: { label: 'Esri imagery', make: () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics', maxNativeZoom: 17, noWrap: true }) },
    osm: { label: 'OpenStreetMap', make: () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxNativeZoom: 19, noWrap: true }) },
    carto_dark: { label: 'CARTO dark (may need key)', make: () => L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { attribution: '&copy; OpenStreetMap &copy; CARTO', subdomains: 'abcd', maxNativeZoom: 19, noWrap: true }) },
  };
  let baseLayer = null;
  function setBasemap(key) {
    if (!BASEMAPS[key]) key = 'esri_dark';
    if (baseLayer) map.removeLayer(baseLayer);
    baseLayer = BASEMAPS[key].make().addTo(map);
    baseLayer.bringToBack();
    try { localStorage.setItem('cyem.basemap', key); } catch {}
    $$('#layers input[name=basemap]').forEach((r) => { r.checked = r.value === key; });
  }

