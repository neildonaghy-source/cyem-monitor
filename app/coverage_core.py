"""Area coverage (P2MP / omni / sector) on terrain: vectorised with numpy.

Per radial, every sample is treated as a receiver; loss = free space + diffraction
+ gas. Diffraction uses the Deygout construction with up to three edges (principal edge,
then the worst edge on each side of it), each costed with the ITU-R P.526 knife-edge
J(v); the link planner uses the same method, so the two agree to within the edge
count and sampling. Screening grade.
"""
from __future__ import annotations

import base64
import math
import struct
import zlib

import numpy as np

from .link_core import C, EARTH_R_M, gas_specific_db_km


def sector_atten_db(off_deg: np.ndarray, beamwidth_deg: float, max_db: float = 25.0) -> np.ndarray:
    """3GPP-style horizontal pattern: min(12 (theta/theta3dB)^2, Am)."""
    return np.minimum(12.0 * (off_deg / beamwidth_deg) ** 2, max_db)


def radial_points(lat: float, lon: float, az_deg: np.ndarray, dist_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Destination lat/lon arrays of shape (len(az), len(dist)) on a sphere."""
    p1, l1 = math.radians(lat), math.radians(lon)
    th = np.radians(az_deg)[:, None]
    dl = (dist_m / EARTH_R_M)[None, :]
    p2 = np.arcsin(np.sin(p1) * np.cos(dl) + np.cos(p1) * np.sin(dl) * np.cos(th))
    l2 = l1 + np.arctan2(np.sin(th) * np.sin(dl) * np.cos(p1), np.cos(dl) - np.sin(p1) * np.sin(p2))
    return np.degrees(p2), (np.degrees(l2) + 540) % 360 - 180


def jv(v: np.ndarray) -> np.ndarray:
    out = 6.9 + 20 * np.log10(np.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)
    return np.where(v > -0.78, out, 0.0)


def polar_prx(heights: np.ndarray, dist_m: np.ndarray, az_deg: np.ndarray, *, h_tx_agl: float, h_rx_agl: float,
              f_hz: float, eirp_dbm: np.ndarray, grx_dbi: float = 0.0, lrx_db: float = 0.0, k: float = 4 / 3) -> np.ndarray:
    """Received level (dBm) for every radial sample. heights: (n_az, n) terrain m ASL with
    heights[:, 0] at the site; eirp_dbm: (n_az,) EIRP towards each radial."""
    n_az, n = heights.shape
    lam = C / f_hz
    d = dist_m.astype(float)
    di, dj = d[:, None], d[None, :]
    mask = (dj > 0) & (dj < di)
    with np.errstate(divide="ignore", invalid="ignore"):
        geom = np.where(mask, np.sqrt(2 / lam * (1 / dj + 1 / (di - dj))), 0.0)
        bulge = np.where(mask, dj * (di - dj) / (2 * k * EARTH_R_M), 0.0)
        frac = np.where(di > 0, dj / di, 0.0)
    rows = np.arange(n)
    fspl = 20 * np.log10(np.maximum(d, 1.0) / 1000) + 20 * math.log10(f_hz / 1e6) + 32.44
    gas = gas_specific_db_km(f_hz / 1e9) * d / 1000
    out = np.empty((n_az, n), dtype=np.float32)
    hb_sub_bulge = bulge
    for a in range(n_az):
        h = heights[a]
        ht = h[0] + h_tx_agl
        hr = h + h_rx_agl
        los = ht + (hr[:, None] - ht) * frac                      # (receiver i, point j)
        hb = h[None, :] + bulge
        vm = np.where(mask, (hb - los) * geom, -np.inf)
        m = vm.argmax(axis=1)                                     # principal edge per receiver
        vmax = vm[rows, m]
        # left sub-path Tx -> edge m (depends on m only): same construction with the edge as receiver
        losl = ht + (h[:, None] - ht) * frac
        vl_all = np.where(mask, (h[None, :] + hb_sub_bulge - losl) * geom, -np.inf).max(axis=1)
        vl = vl_all[m]
        # right sub-path edge m -> receiver i
        dmj = dj - d[m][:, None]
        mr = (dmj > 0) & (dj < di)
        dmi = np.maximum(di - d[m][:, None], 1e-3)
        with np.errstate(divide="ignore", invalid="ignore"):
            gr = np.where(mr, np.sqrt(2 / lam * (1 / np.where(mr, dmj, 1.0) + 1 / np.where(mr, di - dj, 1.0))), 0.0)
            br = np.where(mr, dmj * (di - dj) / (2 * k * EARTH_R_M), 0.0)
            hm = h[m][:, None]
            losr = hm + (hr[:, None] - hm) * dmj / dmi
            vr = np.where(mr, (h[None, :] + br - losr) * gr, -np.inf).max(axis=1)
        has = np.isfinite(vmax) & (vmax > -0.78)
        diff = jv(np.where(np.isfinite(vmax), vmax, -10.0)) + np.where(
            has, jv(np.where(np.isfinite(vl), vl, -10.0)) + jv(np.where(np.isfinite(vr), vr, -10.0)), 0.0)
        out[a] = eirp_dbm[a] - fspl - diff - gas + grx_dbi - lrx_db
    out[:, 0] = np.nan
    return out


# ---- lookup, packing, rendering ----------------------------------------------------
class Coverage:
    """Polar grid of received level (dBm) around a site, with point lookup."""

    def __init__(self, lat: float, lon: float, step_m: float, n_az: int, prx: np.ndarray):
        self.lat, self.lon, self.step_m, self.n_az, self.prx = lat, lon, step_m, n_az, prx
        self.radius_m = step_m * (prx.shape[1] - 1)

    def level_dbm(self, lat: float, lon: float) -> float | None:
        """Nearest-cell level at a point; None outside the computed radius."""
        from .link_core import bearing_deg, haversine_m
        d = haversine_m(self.lat, self.lon, lat, lon)
        if d > self.radius_m:
            return None
        a = int(round(bearing_deg(self.lat, self.lon, lat, lon) / (360 / self.n_az))) % self.n_az
        i = max(1, int(round(d / self.step_m)))
        v = float(self.prx[a, i])
        return None if math.isnan(v) else v

    def pack(self) -> str:
        q = np.where(np.isnan(self.prx), -32768, np.clip(np.round(self.prx * 2), -32767, 32767)).astype("<i2")
        head = struct.pack("<ddfII", self.lat, self.lon, self.step_m, self.n_az, self.prx.shape[1])
        return base64.b64encode(zlib.compress(head + q.tobytes(), 6)).decode()

    @classmethod
    def unpack(cls, blob: str) -> "Coverage":
        raw = zlib.decompress(base64.b64decode(blob))
        lat, lon, step, n_az, n = struct.unpack("<ddfII", raw[:28])
        q = np.frombuffer(raw[28:], dtype="<i2").reshape(n_az, n).astype(np.float32)
        return cls(lat, lon, step, n_az, np.where(q == -32768, np.nan, q / 2))

    def area_km2(self, threshold_dbm: float) -> float:
        """Area where level >= threshold (annulus-sector cell areas)."""
        r = np.arange(self.prx.shape[1]) * self.step_m
        cell = (2 * math.pi / self.n_az) * np.maximum(r, self.step_m / 2) * self.step_m
        ok = np.nan_to_num(self.prx, nan=-999) >= threshold_dbm
        return float((ok * cell[None, :]).sum() / 1e6)

    def max_range_km(self, threshold_dbm: float) -> float:
        ok = np.nan_to_num(self.prx, nan=-999) >= threshold_dbm
        idx = np.where(ok.any(axis=0))[0]
        return float(idx.max() * self.step_m / 1000) if idx.size else 0.0

    def bounds(self) -> tuple[float, float, float, float]:
        dlat = math.degrees(self.radius_m / EARTH_R_M)
        dlon = dlat / max(math.cos(math.radians(self.lat)), 0.01)
        return self.lat - dlat, self.lon - dlon, self.lat + dlat, self.lon + dlon

    def render_png(self, sens_dbm: float, margin_db: float, px: int = 480) -> tuple[str, list[list[float]]]:
        """RGBA PNG (data URL) in plain lat/lon, three bands: strong (>= sens+margin+10),
        adequate (>= sens+margin), marginal (>= sens). Returns (data_url, [[s,w],[n,e]])."""
        s, w, n, e = self.bounds()
        H = px
        W = max(8, int(round(px * (e - w) * math.cos(math.radians(self.lat)) / (n - s))))
        lats = n - (np.arange(H) + 0.5) / H * (n - s)
        lons = w + (np.arange(W) + 0.5) / W * (e - w)
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        p1, p2 = math.radians(self.lat), np.radians(LA)
        dl = np.radians(LO - self.lon)
        a = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
        dist = 2 * EARTH_R_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        brg = (np.degrees(np.arctan2(np.sin(dl) * np.cos(p2), math.cos(p1) * np.sin(p2) - math.sin(p1) * np.cos(p2) * np.cos(dl))) + 360) % 360
        ai = np.round(brg / (360 / self.n_az)).astype(int) % self.n_az
        ri = np.clip(np.round(dist / self.step_m).astype(int), 1, self.prx.shape[1] - 1)
        lv = np.nan_to_num(self.prx[ai, ri], nan=-999)
        lv = np.where(dist <= self.radius_m, lv, -999)
        img = np.zeros((H, W, 4), dtype=np.uint8)
        for thr, rgba in ((sens_dbm, (243, 178, 62, 110)), (sens_dbm + margin_db, (69, 211, 138, 110)),
                          (sens_dbm + margin_db + 10, (43, 185, 168, 150))):
            img[lv >= thr] = rgba
        return "data:image/png;base64," + base64.b64encode(_png(img)).decode(), [[s, w], [n, e]]


def _png(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
