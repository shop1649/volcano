"""Protected regions (faces) for source cleaning.

Faces are found with the OpenCV Haar cascades ``haarcascade_frontalface_default.xml`` and
``haarcascade_profileface.xml`` (profile run on the image and its mirror).  Detections are
merged across time into protected rects in SOURCE px / SOURCE time, the same shape as a plan's
``sources[].protected`` entries, and optional plan-provided protected rects are merged in.

Backends (first available wins):

1. ``cv2.CascadeClassifier`` with the XMLs in ``cv2.data.haarcascades`` (OpenCV 4.x wheels);
2. the same XML files evaluated by :class:`HaarCascade` below, a numpy re-implementation of
   OpenCV's stump-based Haar cascade (``detectMultiScale`` pyramid, variance normalisation,
   ``groupRectangles``).  OpenCV 5 wheels no longer ship ``CascadeClassifier``/``cv2.data``
   XMLs, so the XMLs are fetched once by ``shortkit clean fetch-models`` from the pinned
   opencv-python-headless wheel on PyPI (HTTP range reads of just the two zip members) into
   ``warehouse/cache/models/haarcascades/`` and verified by sha256.

If no backend is available the result has ``status: "unmeasured"`` and callers must treat the
frame as "faces unknown" (the strategy then refuses to crop).
"""
from __future__ import annotations

import hashlib
import struct
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .. import paths
from ..util.jsonio import now_iso

MODELS_DIR = "warehouse/cache/models/haarcascades"

# Pinned source of the cascade XMLs (Intel License Agreement For Open Source Computer Vision
# Library -- redistribution with notice allowed; the XML header carries the notice).
CASCADE_WHEEL = {
    "package": "opencv-python-headless==4.10.0.84",
    "url": ("https://files.pythonhosted.org/packages/30/c0/66f88d58500e990a9a0a5c06f98862edf1d0a3a430781218a8c193948438/"
            "opencv_python_headless-4.10.0.84-cp37-abi3-win32.whl"),
    "sha256": "9092404b65458ed87ce932f613ffbb1106ed2c843577501e5768912360fc50ec",
}
CASCADES = {
    "frontal": {"file": "haarcascade_frontalface_default.xml",
                "sha256": "0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0"},
    "profile": {"file": "haarcascade_profileface.xml",
                "sha256": "b39a4a3be45539db146a7fc1d3e761a292c196eb88421185e6a615b3055e612d"},
}


# ----------------------------------------------------------------------------- model files
def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_ok(p: Path, sha: str) -> bool:
    return p.is_file() and _sha256_bytes(p.read_bytes()) == sha


def find_cascade(kind: str) -> Path | None:
    """Path of a verified cascade XML (cv2.data first, then the project model cache)."""
    spec = CASCADES[kind]
    try:
        import cv2

        d = getattr(getattr(cv2, "data", None), "haarcascades", None)
        if d and (Path(d) / spec["file"]).is_file():
            return Path(d) / spec["file"]
    except ImportError:
        pass
    p = paths.absp(MODELS_DIR) / spec["file"]
    return p if _sha_ok(p, spec["sha256"]) else None


def _http_range(url: str, start: int, end: int, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}", "User-Agent": "shortkit"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.status != 206:
            raise OSError(f"server ignored the range request (HTTP {r.status})")
    return data


def _zip_members_by_range(url: str, names: Sequence[str]) -> dict[str, bytes]:
    """Read selected members of a remote zip with HTTP range requests (no full download)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "shortkit"})
    with urllib.request.urlopen(req, timeout=60) as r:
        size = int(r.headers["Content-Length"])
    tail_start = max(0, size - 65536)
    tail = _http_range(url, tail_start, size - 1)
    i = tail.rfind(b"PK\x05\x06")
    if i < 0:
        raise OSError("zip end-of-central-directory not found")
    _, _, _, _, _n, cd_size, cd_off, _ = struct.unpack("<IHHHHIIH", tail[i:i + 22])
    if cd_off >= tail_start:
        cd = tail[cd_off - tail_start: cd_off - tail_start + cd_size]
    else:
        cd = _http_range(url, cd_off, cd_off + cd_size - 1)
    index: dict[str, tuple[int, int, int, int]] = {}
    p = 0
    while p + 46 <= len(cd):
        (_sig, _vm, _vn, _fl, meth, _mt, _md, _crc, csz, usz, fnl, exl, cml, _dn, _ia, _ea,
         lho) = struct.unpack("<IHHHHHHIIIHHHHHII", cd[p:p + 46])
        name = cd[p + 46:p + 46 + fnl].decode("utf-8", "replace")
        index[name] = (meth, csz, usz, lho)
        p += 46 + fnl + exl + cml
    out: dict[str, bytes] = {}
    for name in names:
        member = next((k for k in index if k.endswith("/" + name) or k == name), None)
        if member is None:
            raise OSError(f"{name} not in {url}")
        meth, csz, usz, lho = index[member]
        hdr = _http_range(url, lho, lho + 29)
        fnl, exl = struct.unpack("<HH", hdr[26:30])
        data = _http_range(url, lho + 30 + fnl + exl, lho + 30 + fnl + exl + csz - 1)
        raw = zlib.decompress(data, -15) if meth == 8 else data
        if len(raw) != usz:
            raise OSError(f"{name}: size mismatch")
        out[name] = raw
    return out


def fetch_cascades(force: bool = False) -> dict:
    """Download the pinned cascade XMLs into the model cache (sha256-verified)."""
    dest = paths.ensure_dir(MODELS_DIR)
    status: dict[str, str] = {}
    need = [k for k, s in CASCADES.items() if force or not _sha_ok(dest / s["file"], s["sha256"])]
    for k in CASCADES:
        if k not in need:
            status[k] = "cached"
    if need:
        try:
            got = _zip_members_by_range(CASCADE_WHEEL["url"], [CASCADES[k]["file"] for k in need])
        except Exception as e:  # network or server problem: say so, never pretend
            for k in need:
                status[k] = f"FAILED: {type(e).__name__}: {e}"
            return {"dir": MODELS_DIR, "status": status, "source": CASCADE_WHEEL}
        for k in need:
            spec = CASCADES[k]
            raw = got[spec["file"]]
            if _sha256_bytes(raw) != spec["sha256"]:
                status[k] = "FAILED: sha256 mismatch"
                continue
            (dest / spec["file"]).write_bytes(raw)
            status[k] = "downloaded"
    return {"dir": MODELS_DIR, "status": status, "source": CASCADE_WHEEL, "fetched_at": now_iso()}


# ----------------------------------------------------------------------------- numpy Haar cascade
@dataclass
class _Stage:
    threshold: float
    feat: np.ndarray       # [K] feature index per stump
    thr: np.ndarray        # [K]
    left: np.ndarray       # [K]
    right: np.ndarray      # [K]


class HaarCascade:
    """Stump-based OpenCV Haar cascade (``opencv-cascade-classifier`` XML) evaluated with numpy.

    Mirrors OpenCV's ``CascadeClassifier::detectMultiScale`` for HAAR/BOOST stump cascades:
    image pyramid (INTER_LINEAR), window step 2 while the pyramid factor <= 2 (else 1), variance
    normalisation over the window shrunk by 1 px, windows with std <= 10 rejected, stage sums
    compared with the stage thresholds, then ``groupRectangles(minNeighbors, eps=0.2)``.
    """

    def __init__(self, xml_path: str | Path) -> None:
        root = ET.parse(str(xml_path)).getroot()
        c = root.find("cascade")
        if c is None or (c.findtext("featureType") or "").strip() != "HAAR":
            raise ValueError(f"{xml_path}: not a new-style HAAR cascade")
        self.win_w = int(c.findtext("width"))
        self.win_h = int(c.findtext("height"))
        feats = []
        for f in c.find("features"):
            t = f.find("tilted")
            if t is not None and t.text.strip() not in ("0", ""):
                raise ValueError(f"{xml_path}: tilted features are not supported")
            rects = []
            for r in f.find("rects"):
                x, y, w, h, wt = r.text.split()
                rects.append((int(x), int(y), int(w), int(h), float(wt)))
            while len(rects) < 3:
                rects.append((0, 0, 0, 0, 0.0))
            feats.append(rects)
        self.rects = np.array([[r[:4] for r in f] for f in feats], dtype=np.int64)     # [F,3,4]
        self.weights = np.array([[r[4] for r in f] for f in feats], dtype=np.float64)  # [F,3]
        self.nrects = (self.weights != 0.0).sum(axis=1)                                # 2 or 3
        self.stages: list[_Stage] = []
        for st in c.find("stages"):
            fi, th, lf, rt = [], [], [], []
            for wc in st.find("weakClassifiers"):
                n = wc.findtext("internalNodes").split()
                lv = wc.findtext("leafValues").split()
                if len(n) != 4:
                    raise ValueError(f"{xml_path}: only stump cascades are supported")
                fi.append(int(n[2]))
                th.append(float(n[3]))
                lf.append(float(lv[0]))
                rt.append(float(lv[1]))
            self.stages.append(_Stage(float(st.findtext("stageThreshold")), np.array(fi), np.array(th),
                                      np.array(lf), np.array(rt)))

    def _eval_level(self, img: np.ndarray, step: int) -> tuple[np.ndarray, np.ndarray]:
        """Positive window origins (x, y) in ``img`` (one pyramid level)."""
        import cv2

        h, w = img.shape
        ww, wh = self.win_w, self.win_h
        if w <= ww or h <= wh:
            return np.empty(0, int), np.empty(0, int)
        s, sq = cv2.integral2(img, sdepth=cv2.CV_64F, sqdepth=cv2.CV_64F)
        W1 = w + 1
        sf = s.ravel()
        sqf = sq.ravel()
        # OpenCV scans x in [0, w - ww] (setWindow rejects x + ww >= w + 1), same for y
        gy = np.arange(0, h - wh + 1, step)
        gx = np.arange(0, w - ww + 1, step)
        ys, xs = np.meshgrid(gy, gx, indexing="ij")
        base = (ys * W1 + xs).ravel()
        # variance normalisation on the window shrunk by 1 px; windows with std <= 10 are skipped
        rx0, ry0, nw, nh = 1, 1, ww - 2, wh - 2
        o = np.array([ry0 * W1 + rx0, ry0 * W1 + rx0 + nw, (ry0 + nh) * W1 + rx0, (ry0 + nh) * W1 + rx0 + nw])
        vs = sf[base + o[0]] - sf[base + o[1]] - sf[base + o[2]] + sf[base + o[3]]
        vq = sqf[base + o[0]] - sqf[base + o[1]] - sqf[base + o[2]] + sqf[base + o[3]]
        area = float(nw * nh)
        nf = area * vq - vs * vs
        ok = nf > 0
        inv = (1.0 / np.sqrt(np.where(ok, nf, 1.0))).astype(np.float32)
        ok &= (area * inv.astype(np.float64)) < 0.1
        r = self.rects
        x0, y0, rw, rh = r[..., 0], r[..., 1], r[..., 2], r[..., 3]
        offs = np.stack([y0 * W1 + x0, y0 * W1 + x0 + rw, (y0 + rh) * W1 + x0, (y0 + rh) * W1 + x0 + rw], axis=-1)
        ny, nx = len(gy), len(gx)
        s2 = s  # 2-D integral image for strided (dense) evaluation
        alive = ok.reshape(ny, nx).copy()
        inv2 = inv.reshape(ny, nx)
        si = 0
        # dense phase: while many windows survive, evaluate stumps on strided views (no gathers)
        while si < len(self.stages) and alive.mean() > 0.2:
            st = self.stages[si]
            passed = self._stage_dense(st, s2, step, ny, nx, inv2)
            if si == 0:
                rej0 = alive & ~passed
                evaluated = self._evaluated_after_skips(rej0)
                alive = alive & passed & evaluated
            else:
                alive &= passed
            si += 1
        idx = np.nonzero(alive.ravel())[0]
        if si == 0 and idx.size:
            # stage 0 must still apply OpenCV's skip rule when it runs sparse
            passed = self._stage(self.stages[0], sf, offs, base[idx], inv[idx])
            rej0 = np.zeros(base.size, bool)
            rej0[idx[~passed]] = True
            evaluated = self._evaluated_after_skips(rej0.reshape(ny, nx)).ravel()
            keep_all = np.zeros(base.size, bool)
            keep_all[idx[passed]] = True
            idx = np.nonzero(keep_all & evaluated)[0]
            si = 1
        for st in self.stages[si:]:
            if idx.size == 0:
                break
            idx = idx[self._stage(st, sf, offs, base[idx], inv[idx])]
        return xs.ravel()[idx], ys.ravel()[idx]

    def _stage_dense(self, st: _Stage, s2: np.ndarray, step: int, ny: int, nx: int, inv2: np.ndarray) -> np.ndarray:
        tot = np.zeros((ny, nx), dtype=np.float64)
        ystop, xstop = (ny - 1) * step + 1, (nx - 1) * step + 1
        for k, fi in enumerate(st.feat.tolist()):
            val = np.zeros((ny, nx), dtype=np.float32)
            for (rx, ry, rw_, rh_), wt in zip(self.rects[fi].tolist(), self.weights[fi].tolist()):
                if wt == 0.0:
                    continue
                a = s2[ry:ry + ystop:step, rx:rx + xstop:step]
                b = s2[ry:ry + ystop:step, rx + rw_:rx + rw_ + xstop:step]
                c = s2[ry + rh_:ry + rh_ + ystop:step, rx:rx + xstop:step]
                d = s2[ry + rh_:ry + rh_ + ystop:step, rx + rw_:rx + rw_ + xstop:step]
                val += (a - b - c + d).astype(np.float32) * np.float32(wt)
            val *= inv2
            tot += np.where(val < np.float32(st.thr[k]), np.float64(np.float32(st.left[k])),
                            np.float64(np.float32(st.right[k])))
        return tot >= np.float32(st.threshold)

    @staticmethod
    def _evaluated_after_skips(rej0: np.ndarray) -> np.ndarray:
        """Which windows OpenCV actually evaluates given its 'skip next x after a stage-0
        rejection' rule: inside a run of stage-0 rejections every other window is skipped and
        the window after an odd-length run is skipped too."""
        ny, nx = rej0.shape
        pos = np.broadcast_to(np.arange(nx), (ny, nx))
        start = np.where(~rej0, pos + 1, 0)
        start = np.maximum.accumulate(start, axis=1)
        pos_in_run = pos - start
        ev = np.ones_like(rej0)
        ev[rej0] = (pos_in_run[rej0] % 2) == 0
        prev_skip_cause = np.zeros_like(rej0)
        prev_skip_cause[:, 1:] = rej0[:, :-1] & ev[:, :-1]
        ev[~rej0] = ~prev_skip_cause[~rej0]
        return ev

    def _stage(self, st: _Stage, sf: np.ndarray, offs: np.ndarray, base: np.ndarray, inv: np.ndarray) -> np.ndarray:
        """Sparse stage evaluation (gathers) for the surviving windows ``base``."""
        thr = st.thr.astype(np.float32)[:, None]
        left = st.left.astype(np.float32).astype(np.float64)[:, None]
        right = st.right.astype(np.float32).astype(np.float64)[:, None]
        K = len(st.feat)
        chunk = max(256, int(3_000_000 // (K * 12)))         # bound temporary memory
        tot = np.empty(base.size, dtype=np.float64)
        groups = []
        for nr in (2, 3):
            sel = np.nonzero(self.nrects[st.feat] == nr)[0]
            if sel.size:
                groups.append((sel, offs[st.feat[sel], :nr], self.weights[st.feat[sel], :nr].astype(np.float32)))
        for c0 in range(0, base.size, chunk):
            b = base[c0:c0 + chunk]
            val = np.empty((K, b.size), dtype=np.float32)
            for sel, fo, fw in groups:
                v = sf[b[None, None, None, :] + fo[..., None]]           # [k,nr,4,n]
                rs = (v[:, :, 0] - v[:, :, 1] - v[:, :, 2] + v[:, :, 3]).astype(np.float32)
                acc = rs[:, 0] * fw[:, 0:1]
                for j in range(1, fo.shape[1]):
                    acc = acc + rs[:, j] * fw[:, j:j + 1]
                val[sel] = acc
            val *= inv[None, c0:c0 + chunk]
            tot[c0:c0 + chunk] = np.where(val < thr, left, right).sum(axis=0)
        return tot >= np.float32(st.threshold)

    def detect(self, gray: np.ndarray, scale_factor: float = 1.1, min_neighbors: int = 3,
               min_size: tuple[int, int] | None = None, max_size: tuple[int, int] | None = None
               ) -> list[tuple[int, int, int, int, int]]:
        """``[(x, y, w, h, neighbors)]`` in the input image's px."""
        import cv2

        H, W = gray.shape[:2]
        min_size = min_size or (self.win_w, self.win_h)
        max_size = max_size or (W, H)
        cands: list[tuple[int, int, int, int]] = []
        factor = 1.0
        interp = getattr(cv2, "INTER_LINEAR_EXACT", cv2.INTER_LINEAR)
        while True:
            f32 = float(np.float32(factor))          # OpenCV keeps pyramid scales as float
            ww = int(round(self.win_w * f32))
            wh = int(round(self.win_h * f32))
            sw, sh = int(round(W / f32)), int(round(H / f32))
            if sw <= self.win_w or sh <= self.win_h or ww > max_size[0] or wh > max_size[1]:
                break
            if ww >= min_size[0] and wh >= min_size[1]:
                img = gray if (sw, sh) == (W, H) else cv2.resize(gray, (sw, sh), interpolation=interp)
                step = 1 if f32 > 2.0 else 2
                xs, ys = self._eval_level(img, step)
                for x, y in zip(xs.tolist(), ys.tolist()):
                    cands.append((int(round(x * f32)), int(round(y * f32)), ww, wh))
            factor *= scale_factor
        return group_rectangles(cands, min_neighbors, 0.2)


def group_rectangles(rects: list[tuple[int, int, int, int]], group_threshold: int, eps: float = 0.2
                     ) -> list[tuple[int, int, int, int, int]]:
    """Port of ``cv::groupRectangles`` (returns rect + neighbour count)."""
    n = len(rects)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def similar(a, b) -> bool:
        delta = eps * (min(a[2], b[2]) + min(a[3], b[3])) * 0.5
        return (abs(a[0] - b[0]) <= delta and abs(a[1] - b[1]) <= delta
                and abs(a[0] + a[2] - b[0] - b[2]) <= delta and abs(a[1] + a[3] - b[1] - b[3]) <= delta)

    arr = np.array(rects, dtype=np.float64)
    for i in range(n):
        # vectorised similarity against later rects
        a = arr[i]
        rest = arr[i + 1:]
        if rest.size == 0:
            continue
        delta = eps * (np.minimum(a[2], rest[:, 2]) + np.minimum(a[3], rest[:, 3])) * 0.5
        m = ((np.abs(a[0] - rest[:, 0]) <= delta) & (np.abs(a[1] - rest[:, 1]) <= delta)
             & (np.abs(a[0] + a[2] - rest[:, 0] - rest[:, 2]) <= delta)
             & (np.abs(a[1] + a[3] - rest[:, 1] - rest[:, 3]) <= delta))
        for j in (np.nonzero(m)[0] + i + 1).tolist():
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri
    labels = [find(i) for i in range(n)]
    groups: dict[int, list[int]] = {}
    for i, l in enumerate(labels):
        groups.setdefault(l, []).append(i)
    avg = []
    for idxs in groups.values():
        s = arr[idxs].sum(axis=0)
        k = len(idxs)
        avg.append((int(round(s[0] / k)), int(round(s[1] / k)), int(round(s[2] / k)), int(round(s[3] / k)), k))
    out = []
    for i, r1 in enumerate(avg):
        n1 = r1[4]
        if n1 <= group_threshold:
            continue
        inside = False
        for j, r2 in enumerate(avg):
            n2 = r2[4]
            if j == i or n2 <= group_threshold:
                continue
            dx = int(round(r2[2] * eps))
            dy = int(round(r2[3] * eps))
            if (r1[0] >= r2[0] - dx and r1[1] >= r2[1] - dy and r1[0] + r1[2] <= r2[0] + r2[2] + dx
                    and r1[1] + r1[3] <= r2[1] + r2[3] + dy and (n2 > max(3, n1) or n1 < 3)):
                inside = True
                break
        if not inside:
            out.append(r1)
    return out


# ----------------------------------------------------------------------------- detectors
class _Detector:
    def __init__(self, kind: str, path: Path) -> None:
        import cv2

        self.kind = kind
        self.path = path
        self.native = None
        if hasattr(cv2, "CascadeClassifier"):
            cc = cv2.CascadeClassifier(str(path))
            if not cc.empty():
                self.native = cc
        self.numpy = None if self.native is not None else HaarCascade(path)

    @property
    def backend(self) -> str:
        return "cv2.CascadeClassifier" if self.native is not None else "shortkit.HaarCascade(numpy)"

    def __call__(self, gray: np.ndarray, min_size: int, min_neighbors: int) -> list[tuple[int, int, int, int, int]]:
        if self.native is not None:
            rects, nums = self.native.detectMultiScale2(gray, scaleFactor=1.1, minNeighbors=min_neighbors,
                                                        minSize=(min_size, min_size))
            return [(int(x), int(y), int(w), int(h), int(n)) for (x, y, w, h), n in zip(rects, nums)]
        return self.numpy.detect(gray, 1.1, min_neighbors, (min_size, min_size))


_DET_CACHE: dict[str, _Detector] = {}


def load_detectors() -> tuple[list[_Detector], list[str]]:
    dets, missing = [], []
    for kind in ("frontal", "profile"):
        p = find_cascade(kind)
        if p is None:
            missing.append(kind)
            continue
        key = f"{kind}:{p}"
        if key not in _DET_CACHE:
            _DET_CACHE[key] = _Detector(kind, p)
        dets.append(_DET_CACHE[key])
    return dets, missing


def detect_faces_in_frame(rgb: np.ndarray, detectors: list[_Detector], min_face_px: int = 24,
                          min_neighbors: int = 4) -> list[dict]:
    """Faces in one RGB frame (coordinates in that frame's px)."""
    import cv2

    gray = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    W = gray.shape[1]
    out = []
    for det in detectors:
        for x, y, w, h, n in det(gray, min_face_px, min_neighbors):
            out.append({"x": x, "y": y, "w": w, "h": h, "kind": det.kind, "neighbors": n})
        if det.kind == "profile":   # the profile cascade is one-sided: run on the mirror too
            for x, y, w, h, n in det(np.ascontiguousarray(gray[:, ::-1]), min_face_px, min_neighbors):
                out.append({"x": W - x - w, "y": y, "w": w, "h": h, "kind": "profile_mirror", "neighbors": n})
    return _nms(out, 0.3)


def _iou(a: dict, b: dict) -> float:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    u = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / u if u > 0 else 0.0


def _nms(dets: list[dict], thr: float) -> list[dict]:
    dets = sorted(dets, key=lambda d: (-d["neighbors"], -(d["w"] * d["h"])))
    keep: list[dict] = []
    for d in dets:
        if all(_iou(d, k) < thr for k in keep):
            keep.append(d)
    return keep


def merge_tracks(samples: list[tuple[float, list[dict]]], interval: float, duration: float,
                 min_hits: int = 1, pad_frac: float = 0.15) -> list[dict]:
    """Merge per-sample detections into protected regions over time.

    Detections overlapping (IoU >= 0.2 or centre inside) a track seen within the last two
    samples join it.  Each track becomes ``{label: 'face', x, y, w, h, start, end, hits}``:
    the union of its boxes padded by ``pad_frac`` (hair/chin), active from half a sample
    interval before the first hit to half after the last one.
    """
    tracks: list[dict] = []
    for t, dets in samples:
        for d in dets:
            best, best_s = None, 0.0
            cx, cy = d["x"] + d["w"] / 2, d["y"] + d["h"] / 2
            for tr in tracks:
                if t - tr["t_last"] > 2.01 * interval:
                    continue
                last = tr["last"]
                s = _iou(d, last)
                if last["x"] <= cx <= last["x"] + last["w"] and last["y"] <= cy <= last["y"] + last["h"]:
                    s = max(s, 0.5)
                if s >= 0.2 and s > best_s:
                    best, best_s = tr, s
            if best is None:
                best = {"boxes": [], "t_first": t, "t_last": t, "kinds": set()}
                tracks.append(best)
            best["boxes"].append(d)
            best["last"] = d
            best["t_last"] = t
            best["kinds"].add(d.get("kind", "face"))
    out = []
    for tr in tracks:
        if len(tr["boxes"]) < min_hits:
            continue
        x0 = min(b["x"] for b in tr["boxes"])
        y0 = min(b["y"] for b in tr["boxes"])
        x1 = max(b["x"] + b["w"] for b in tr["boxes"])
        y1 = max(b["y"] + b["h"] for b in tr["boxes"])
        px, py = (x1 - x0) * pad_frac, (y1 - y0) * pad_frac
        out.append({"label": "face", "x": x0 - px, "y": y0 - py, "w": (x1 - x0) + 2 * px, "h": (y1 - y0) + 2 * py,
                    "start": max(0.0, tr["t_first"] - interval / 2), "end": min(duration, tr["t_last"] + interval / 2),
                    "hits": len(tr["boxes"]), "kinds": sorted(tr["kinds"])})
    return out


def clamp_rect(r: dict, W: int, H: int) -> dict:
    x0 = max(0.0, float(r["x"]))
    y0 = max(0.0, float(r["y"]))
    x1 = min(float(W), float(r["x"]) + float(r["w"]))
    y1 = min(float(H), float(r["y"]) + float(r["h"]))
    out = dict(r)
    out.update({"x": round(x0, 1), "y": round(y0, 1), "w": round(max(0.0, x1 - x0), 1), "h": round(max(0.0, y1 - y0), 1)})
    return out


def detect_faces(video: str | Path, sample_fps: float = 1.0, analysis_width: int = 960, max_samples: int = 60,
                 min_face_frac: float = 0.03, min_neighbors: int = 4,
                 plan_protected: Iterable[dict] | None = None) -> dict:
    """Detect faces over the clip and merge them into protected regions (SOURCE px/time).

    ``plan_protected`` entries (``{label,x,y,w,h,start,end}`` in SOURCE px) are appended as-is.
    """
    from ..util.media import iter_frames, probe

    info = probe(video)
    W, H = info.width, info.height
    if not W or not H:
        raise ValueError(f"no video stream in {video}")
    plan_prot = [dict(p, origin="plan") for p in (plan_protected or [])]
    dets, missing = load_detectors()
    base = {"schema": "shortkit.faces/1", "resolution": [W, H], "duration": info.duration,
            "detected_at": now_iso(), "cascades": {d.kind: d.path.name for d in dets}, "missing_cascades": missing}
    if not dets or "frontal" in missing:
        return {**base, "status": "unmeasured", "method": None,
                "blocker": "Haar 캐스케이드 파일이 없음: `shortkit clean fetch-models` 실행 필요",
                "samples": [], "faces": [], "protected": plan_prot}
    aw = min(analysis_width, W)
    scale = W / aw
    fps = min(sample_fps, max_samples / max(info.duration, 1e-3))
    interval = 1.0 / fps
    min_px = max(20, int(round(min_face_frac * min(W, H) / scale)))
    samples: list[tuple[float, list[dict]]] = []
    for t, rgb in iter_frames(video, fps=fps, width=aw):
        found = detect_faces_in_frame(rgb, dets, min_face_px=min_px, min_neighbors=min_neighbors)
        src = [{**d, "x": d["x"] * scale, "y": d["y"] * scale, "w": d["w"] * scale, "h": d["h"] * scale} for d in found]
        samples.append((round(t, 3), src))
    tracks = merge_tracks(samples, interval, info.duration)
    faces = [clamp_rect(tr, W, H) for tr in tracks]
    return {**base, "status": "measured", "method": f"haar frontal+profile ({dets[0].backend})",
            "sample_fps": round(fps, 4), "analysis_width": aw, "min_face_px_source": int(min_px * scale),
            "min_neighbors": min_neighbors,
            "samples": [{"t": t, "faces": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in d.items()}
                                           for d in ds]} for t, ds in samples],
            "faces": faces,
            "protected": [{k: f[k] for k in ("label", "x", "y", "w", "h", "start", "end")} for f in faces] + plan_prot}
