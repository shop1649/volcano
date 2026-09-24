"""Verify an exported MLT project against the master MP4 by actually rendering it with melt.

    verify(resolved, master_mp4, project_file) -> dict   (also writes <project>/verify.json)

Status (stored English, reported Korean):
    pass        melt rendered the project and every per-second row met the thresholds
    fail        melt rendered it and at least one row / global check missed a threshold
    unmeasured  (못 잼) melt / X display / master missing or melt failed -> nothing was compared.
                A pass is NEVER reported without a finished melt render.

Comparison (same absolute time, 1-second grid):
  video  melt renders at the profile resolution (its affine placement is only exact there); both
         files are then decoded to gray, area-downscaled to <= 540 px wide; per frame SSIM (Gaussian 11x11,
         sigma 1.5, K1=0.01, K2=0.03, same as Wang et al. 2004) and mean |diff|; per second:
         mean/min SSIM and mean abs diff.
  audio  mono 16 kHz; RMS envelope (50 ms windows) Pearson correlation over the whole file;
         per second RMS level difference in dB (only where the master is above -45 dBFS).
Thresholds (defaults below, recorded in verify.json):
  ssim_sec_mean >= 0.90  per second    (identical geometry through two different scalers +
                                        x264 of both files measured ~0.95-0.99 on test clips;
                                        a 1-frame cut misplacement or wrong zoom drops < 0.8)
  ssim_overall  >= 0.95  whole file
  mad_sec       <= 10.0  per second    (0-255 gray levels)
  audio_env_corr >= 0.90 whole file
  level_diff_db <= 2.0   per second    (|dB|, seconds where master >= -45 dBFS)
  duration_diff <= 2 frames
"""
from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .. import paths
from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import FFMPEG, MediaError, lufs, probe, read_audio
from .ir import ResolvedEdit

DEFAULT_THRESHOLDS = {
    "ssim_sec_mean_min": 0.90,
    "ssim_overall_min": 0.95,
    "mad_sec_max": 10.0,
    "audio_env_corr_min": 0.90,
    "level_diff_db_max": 2.0,
    "level_floor_dbfs": -45.0,
    "duration_diff_frames_max": 2,
}
QT_SERVICES = ("qtcrop", "qtblend", "qimage", "qtext")
STATUS_KO = {"pass": "통과", "fail": "불일치", "unmeasured": "못 잼"}


class MeltUnavailable(RuntimeError):
    pass


# ============================================================================ melt runner
def find_melt() -> str | None:
    for name in (os.environ.get("MELT") or "", "melt", "melt-7"):
        if name and shutil.which(name):
            return shutil.which(name)
    return None


def melt_command(project_file: Path) -> tuple[list[str], dict]:
    """[xvfb-run -a] melt ... ; the wrapper is used only when the project needs Qt services and
    there is no display."""
    melt = find_melt()
    if not melt:
        raise MeltUnavailable("melt 실행 파일을 찾지 못함 (PATH 또는 $MELT)")
    text = Path(project_file).read_text(encoding="utf-8", errors="replace")
    needs_qt = any(f">{s}<" in text for s in QT_SERVICES)
    env = {"mode": "direct", "needs_qt": needs_qt}
    if needs_qt and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        xv = shutil.which("xvfb-run")
        if not xv:
            raise MeltUnavailable("프로젝트가 Qt 서비스(qtcrop/qtblend/qimage)를 쓰는데 DISPLAY 가 없고 xvfb-run 도 없음")
        env["mode"] = "xvfb-run"
        return [xv, "-a", melt], env
    return [melt], env


def run_melt(project_file: Path, consumer_args: list[str], timeout: float = 1800.0) -> dict:
    """Run melt in the project folder (relative av.fontsdir resolves there); kill the whole
    process group on timeout (melt ignores SIGTERM when stuck)."""
    project_file = Path(project_file)
    pre, env = melt_command(project_file)
    cmd = pre + [project_file.name, *consumer_args]
    proc = subprocess.Popen(cmd, cwd=str(project_file.parent), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise MediaError(f"melt 시간 초과({timeout:.0f}s)")
    txt = scrub((err or b"").decode("utf-8", "replace"))
    tail = "\n".join(line for line in txt.replace("\r", "\n").splitlines()
                     if line.strip() and not line.startswith("Current Frame"))[-3000:]
    failed = [ln for ln in tail.splitlines() if "failed to load" in ln]
    if proc.returncode != 0 or failed:
        raise MediaError(f"melt 실패(rc={proc.returncode}): {tail[-1500:]}")
    shown = ["xvfb-run", "-a", "melt"] if env["mode"] == "xvfb-run" else ["melt"]
    return {"cmd": shown + [scrub(a) for a in cmd[len(pre):]], "mode": env["mode"], "needs_qt": env["needs_qt"],
            "stderr_tail": tail[-800:]}


def scrub(text: str) -> str:
    """Remove machine-specific absolute paths (project root, tool install dirs) from stored text."""
    try:
        root = str(paths.project_root())
        text = text.replace(root + "/", "").replace(root, ".")
    except RuntimeError:
        pass
    for d in ("/usr/local/bin/", "/usr/bin/", "/bin/"):
        text = text.replace(d, "")
    return text


def melt_audio_lufs(project_file: Path, reference: Path | None = None) -> dict:
    """Render only the audio of an MLT project with melt; integrated loudness, and when a reference
    file (the master) is given, the whole-file RMS ratio reference/project in dB (a stable gain
    estimate between two renders of the same mix; short dynamic clips make gated LUFS jumpy)."""
    with tempfile.TemporaryDirectory(prefix="melt_audio_") as td:
        wav = Path(td) / "mix.wav"
        run_melt(Path(project_file), ["-consumer", f"avformat:{wav}", "video_off=1", "vn=1", "ar=48000", "ac=2",
                                      "acodec=pcm_f32le", "real_time=-1"], timeout=900)
        out = lufs(wav)
        if reference is not None and Path(reference).is_file():
            a = read_audio(wav, sr=48000, mono=False)
            b = read_audio(reference, sr=48000, mono=False)
            n = min(len(a), len(b))
            pa = float((a[:n].astype(np.float64) ** 2).mean()) if n else 0.0
            pb = float((b[:n].astype(np.float64) ** 2).mean()) if n else 0.0
            out["rms_ratio_db"] = round(10 * math.log10(pb / pa), 3) if pa > 1e-12 and pb > 1e-12 else None
        return out


# ============================================================================ comparison
def _gray_frames(path: Path, w: int, h: int, fps: float, max_frames: int) -> np.ndarray:
    vf = f"scale={w}:{h}:flags=area,fps={fps:g},format=gray"
    raw = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-vf", vf,
                          "-frames:v", str(max_frames), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w)


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Mean SSIM of two gray uint8 images (Gaussian window 11, sigma 1.5)."""
    import cv2

    a = a.astype(np.float64)
    b = b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    k = (11, 11)
    mu_a = cv2.GaussianBlur(a, k, 1.5)
    mu_b = cv2.GaussianBlur(b, k, 1.5)
    saa = cv2.GaussianBlur(a * a, k, 1.5) - mu_a ** 2
    sbb = cv2.GaussianBlur(b * b, k, 1.5) - mu_b ** 2
    sab = cv2.GaussianBlur(a * b, k, 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (saa + sbb + c2))
    return float(m.mean())


def _rms_env(x: np.ndarray, sr: int, win_s: float = 0.05) -> np.ndarray:
    w = max(1, int(sr * win_s))
    n = len(x) // w
    if n == 0:
        return np.zeros(0)
    return np.sqrt((x[: n * w].reshape(n, w) ** 2).mean(axis=1) + 1e-12)


def _level_db(x: np.ndarray) -> float:
    if len(x) == 0:
        return -120.0
    r = float(np.sqrt((x.astype(np.float64) ** 2).mean()))
    return 20 * math.log10(r) if r > 1e-6 else -120.0


COMPARE_MAX_WIDTH = 540   # both files are area-downscaled to this width for the SSIM grid (speed)


def compare(master: Path, render: Path, width: int, height: int, fps: float, duration: float,
            thresholds: dict) -> dict:
    th = thresholds
    nexp = int(round(duration * fps))
    if width > COMPARE_MAX_WIDTH:
        height = int(round(height * COMPARE_MAX_WIDTH / width / 2)) * 2
        width = COMPARE_MAX_WIDTH
    fm = _gray_frames(master, width, height, fps, nexp + 5)
    fr = _gray_frames(render, width, height, fps, nexp + 5)
    n = min(len(fm), len(fr), nexp)
    per_frame = np.zeros((n, 2))
    for i in range(n):
        per_frame[i, 0] = ssim(fm[i], fr[i])
        per_frame[i, 1] = float(np.abs(fm[i].astype(np.int16) - fr[i].astype(np.int16)).mean())
    sr = 16000
    am = read_audio(master, sr=sr, mono=True)
    ar = read_audio(render, sr=sr, mono=True)
    na = min(len(am), len(ar))
    am, ar = am[:na], ar[:na]
    em, er = _rms_env(am, sr), _rms_env(ar, sr)
    ne = min(len(em), len(er))
    corr = None
    if ne > 2 and em[:ne].std() > 1e-9 and er[:ne].std() > 1e-9:
        corr = float(np.corrcoef(em[:ne], er[:ne])[0, 1])
    rows = []
    n_sec = int(math.ceil(duration - 1e-6))
    for k in range(n_sec):
        f0, f1 = int(round(k * fps)), min(n, int(round((k + 1) * fps)))
        row: dict = {"sec": k, "t0": float(k), "t1": float(min(k + 1, duration)), "frames": max(0, f1 - f0)}
        if f1 > f0:
            s = per_frame[f0:f1, 0]
            row.update({"ssim_mean": round(float(s.mean()), 4), "ssim_min": round(float(s.min()), 4),
                        "mad": round(float(per_frame[f0:f1, 1].mean()), 3)})
            row["video"] = ("pass" if row["ssim_mean"] >= th["ssim_sec_mean_min"] and row["mad"] <= th["mad_sec_max"]
                            else "fail")
        else:
            row["video"] = "unmeasured"
        a0, a1 = int(k * sr), min(na, int((k + 1) * sr))
        lm, lr = _level_db(am[a0:a1]), _level_db(ar[a0:a1])
        row.update({"level_master_dbfs": round(lm, 2), "level_project_dbfs": round(lr, 2)})
        if a1 <= a0:
            row["audio"] = "unmeasured"
        elif lm < th["level_floor_dbfs"]:
            row["level_diff_db"] = round(lr - lm, 2)
            row["audio"] = "quiet"
        else:
            row["level_diff_db"] = round(lr - lm, 2)
            row["audio"] = "pass" if abs(lr - lm) <= th["level_diff_db_max"] else "fail"
        rows.append(row)
    ssim_all = float(per_frame[:, 0].mean()) if n else None
    info_m, info_r = probe(master), probe(render)
    dur_diff_frames = abs(info_m.duration - info_r.duration) * fps
    glob = {
        "frames_compared": n, "frames_expected": nexp, "frames_master": len(fm), "frames_project": len(fr),
        "ssim_overall": round(ssim_all, 4) if ssim_all is not None else None,
        "ssim_worst_second": min((r["ssim_mean"] for r in rows if "ssim_mean" in r), default=None),
        "mad_overall": round(float(per_frame[:, 1].mean()), 3) if n else None,
        "audio_env_corr": round(corr, 4) if corr is not None else None,
        "duration_master_s": round(info_m.duration, 4), "duration_project_s": round(info_r.duration, 4),
        "duration_diff_frames": round(dur_diff_frames, 2), "compare_size": [width, height],
    }
    from ..util.stats import pstats

    glob["per_second"] = {   # distribution over the 1-second rows (single episode: no per-format split)
        "ssim_mean": pstats(r.get("ssim_mean") for r in rows),
        "mad": pstats(r.get("mad") for r in rows),
        "level_diff_db": pstats(r.get("level_diff_db") for r in rows if r.get("audio") in ("pass", "fail")),
    }
    checks = {
        "ssim_overall": ssim_all is not None and ssim_all >= th["ssim_overall_min"],
        "audio_env_corr": corr is not None and corr >= th["audio_env_corr_min"],
        "duration": dur_diff_frames <= th["duration_diff_frames_max"],
        "frames": n >= nexp - th["duration_diff_frames_max"],
        "rows_video": all(r["video"] == "pass" for r in rows),
        "rows_audio": all(r["audio"] in ("pass", "quiet") for r in rows),
    }
    return {"global": glob, "checks": checks, "rows": rows}


# ============================================================================ entry point
def _render_path(project_file: Path) -> Path:
    pf = Path(project_file)
    if pf.parent.name == "project":
        return pf.parent.parent / "build" / "verify" / f"{pf.stem}.melt.mkv"
    return pf.parent / ".verify" / f"{pf.stem}.melt.mkv"


def _rel(p: Path) -> str:
    try:
        return paths.relp(p)
    except (ValueError, RuntimeError):
        return Path(p).name


def verify(resolved: ResolvedEdit, master_mp4: Path, project_file: Path, *, thresholds: dict | None = None,
           timeout: float = 3600.0, keep_render: bool = True) -> dict:
    """Render the MLT project with melt and compare it with the master MP4 (contract API)."""
    r = resolved
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    project_file = Path(project_file)
    master_mp4 = Path(master_mp4)
    if project_file.suffix.lower() != ".mlt":
        return _record_unrenderable(r, project_file)
    W, H, fps = int(r.canvas["width"]), int(r.canvas["height"]), float(r.canvas["fps"])
    res: dict = {"schema": "shortkit.project_verify/1", "episode_id": r.episode_id, "checked_at": now_iso(),
                 "project_file": _rel(project_file), "master": _rel(master_mp4), "thresholds": th,
                 "method": {"video": "gray SSIM(11x11 gaussian, σ=1.5) + 평균 절대차, 1초 격자; 두 파일 모두 "
                                     f"폭 {COMPARE_MAX_WIDTH}px 이하로 area 축소 후 비교",
                            "audio": "mono 16 kHz RMS envelope(50 ms) 상관 + 초별 RMS 레벨 차(dB)",
                            "render": "melt avformat consumer, 프로필 해상도(축소 렌더 아님)"},
                 "not_verified": ["Shotcut/Kdenlive GUI 에서 실제로 열어 보기(이 기계에 GUI 없음)",
                                  "사람이 직접 보고 들은 확인(청취·시청 확인 안 함)"]}
    status, why = None, None
    if not master_mp4.is_file():
        status, why = "unmeasured", f"마스터 MP4 없음: {_rel(master_mp4)}"
    elif not project_file.is_file():
        status, why = "unmeasured", f"프로젝트 파일 없음: {_rel(project_file)}"
    if status is None:
        out = _render_path(project_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        # unique temp name: two exports of the same episode may verify at the same time
        tmp = out.with_name(f"{out.stem}.{os.getpid()}.tmp.render.mkv")
        # size / rate / colorspace come from the project profile: overriding width/height on the
        # consumer makes melt pick the BT.601 matrix for small frames (and misplaces affine rects)
        args = ["-consumer", f"avformat:{os.path.relpath(tmp, project_file.parent)}", "progressive=1",
                "vcodec=libx264", "preset=veryfast", "crf=12", "acodec=pcm_s16le", "ar=48000", "ac=2",
                "real_time=-1"]
        try:
            res["melt"] = run_melt(project_file, args, timeout=timeout)
            if tmp.is_file():
                os.replace(tmp, out)
            res["melt"]["output"] = _rel(out)
        except MeltUnavailable as e:
            status, why = "unmeasured", str(e)
        except MediaError as e:
            status, why = "unmeasured", f"melt 렌더 실패: {scrub(str(e))[:1200]}"
        finally:
            if tmp.is_file():
                tmp.unlink()
        if status is None:
            if not out.is_file() or out.stat().st_size == 0:
                status, why = "unmeasured", "melt 가 출력 파일을 만들지 않음"
            else:
                try:
                    cmp_ = compare(master_mp4, out, W, H, fps, r.duration, th)
                    res.update(cmp_)
                    status = "pass" if all(cmp_["checks"].values()) else "fail"
                    if status == "fail":
                        why = "기준 미달: " + ", ".join(k for k, v in cmp_["checks"].items() if not v)
                except (MediaError, subprocess.CalledProcessError, ValueError) as e:
                    status, why = "unmeasured", f"비교 실패: {type(e).__name__}: {scrub(str(e))[:400]}"
            if not keep_render and out.is_file():
                out.unlink()
    res["status"] = status
    res["status_ko"] = STATUS_KO[status]
    if why:
        res["why"] = why
    if status == "unmeasured":
        res["impact"] = ("편집 프로젝트(.mlt)로 다시 렌더한 결과가 마스터 MP4 와 같은지 모름 → Shotcut 에서 수정 후 내보낸 "
                         "영상은 QA 를 처음부터 다시 받아야 함")
    prev = read_json(project_file.parent / "verify.json", {}) or {}
    if prev.get("other_formats"):
        res["other_formats"] = prev["other_formats"]
    write_json(project_file.parent / "verify.json", res)
    return res


NLE_IMPACT = {
    ".fcpxml": "Resolve/FCP 로 가져온 타임라인이 마스터와 다를 수 있음(위치·자르기 단위, easing 곡선, 영역 마스크 없음) "
               "→ 그 프로그램에서 내보낸 영상은 QA 를 다시 받아야 함",
    ".otio": "가져오는 편집기마다 해석이 달라 결과가 마스터와 다를 수 있음 → 내보낸 영상은 QA 를 다시 받아야 함",
}
NLE_NOTES = {
    ".fcpxml": "FCPXML 은 DaVinci Resolve / Final Cut Pro 에서 열어야 렌더할 수 있는데 이 기계에는 둘 다 없음",
    ".otio": "OTIO 는 교환용 타임라인이라 자체 렌더러가 없음(가져오는 NLE 에서만 재생 가능)",
}


def _record_unrenderable(r: ResolvedEdit, project_file: Path) -> dict:
    """FCPXML / OTIO: no renderer here -> status unmeasured (never pass); structure checks only are
    done by the tests.  The MLT result already in verify.json is kept untouched."""
    ext = project_file.suffix.lower()
    res = {"project_file": _rel(project_file), "checked_at": now_iso(), "status": "unmeasured",
           "status_ko": STATUS_KO["unmeasured"],
           "why": NLE_NOTES.get(ext, "렌더 검증 방법 없음") + " → 렌더 동등성은 못 잼(구조·시간 일관성만 테스트에서 확인)",
           "impact": NLE_IMPACT.get(ext, "결과가 마스터와 다를 수 있음")}
    f = project_file.parent / "verify.json"
    d = read_json(f, {}) or {}
    d.setdefault("schema", "shortkit.project_verify/1")
    d.setdefault("episode_id", r.episode_id)
    if not d.get("status"):          # no MLT result yet: the file must not look verified
        d.update({"status": "unmeasured", "status_ko": STATUS_KO["unmeasured"], "why": "MLT 검증 결과 없음"})
    d.setdefault("other_formats", {})[ext.lstrip(".")] = res
    write_json(f, d)
    return res


def _fr(fps: float) -> tuple[int, int]:
    from fractions import Fraction

    f = Fraction(fps).limit_denominator(1001)
    return f.numerator, f.denominator
