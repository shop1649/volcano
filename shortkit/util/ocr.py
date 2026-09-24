"""Shared tesseract helper: every OCR subprocess runs with ``OMP_THREAD_LIMIT=1`` and a timeout.

tesseract 5 is built with OpenMP; with its default thread count on a small shared machine (4 cores
here, other jobs running) each call becomes dramatically slower because the threads fight for the
cores.  pytesseract has no ``env`` argument, so the variable is set in this process' environment
for the duration of the call (reference counted, restored afterwards) and inherited by the
tesseract subprocess.

    from shortkit.util import ocr
    d = ocr.image_to_data(img, lang="kor+eng", config="--psm 6")      # dict of lists (pytesseract DICT)
    s = ocr.image_to_string(img, lang="kor", timeout=10)

``img`` may be a PIL image or a numpy array (H x W [x 3], uint8).  Errors are explicit:
``OcrUnavailable`` (pytesseract / tesseract binary / language missing) and ``OcrTimeout``.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator

DEFAULT_TIMEOUT_S = 20.0
THREAD_LIMIT = "1"

_lock = threading.Lock()
_depth = 0
_saved: str | None = None


class OcrUnavailable(RuntimeError):
    """pytesseract / the tesseract binary / a requested language is not installed."""


class OcrTimeout(RuntimeError):
    """tesseract did not finish within the timeout (the process was killed by pytesseract)."""


@contextmanager
def tesseract_env() -> Iterator[None]:
    """Force ``OMP_THREAD_LIMIT=1`` for tesseract subprocesses started inside the block (nesting and
    threads share one reference count; the previous value is restored when the last block exits)."""
    global _depth, _saved
    with _lock:
        if _depth == 0:
            _saved = os.environ.get("OMP_THREAD_LIMIT")
        _depth += 1
        os.environ["OMP_THREAD_LIMIT"] = THREAD_LIMIT
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0:
                if _saved is None:
                    os.environ.pop("OMP_THREAD_LIMIT", None)
                else:
                    os.environ["OMP_THREAD_LIMIT"] = _saved


def _pyt():
    try:
        import pytesseract  # type: ignore
    except ImportError as e:
        raise OcrUnavailable(f"pytesseract 가 설치되지 않음: {e}") from None
    return pytesseract


def _image(img: Any):
    from PIL import Image

    if isinstance(img, Image.Image):
        return img
    import numpy as np

    a = np.asarray(img)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(a)


def _call(fn_name: str, img: Any, lang: str, config: str, timeout: float, **kw):
    pyt = _pyt()
    fn = getattr(pyt, fn_name)
    try:
        with tesseract_env():
            return fn(_image(img), lang=lang, config=config, timeout=timeout, **kw)
    except pyt.TesseractNotFoundError as e:
        raise OcrUnavailable(f"tesseract 실행 파일 없음: {e}") from None
    except pyt.TesseractError as e:
        msg = str(e)
        if "Failed loading language" in msg or "Error opening data file" in msg:
            raise OcrUnavailable(f"tesseract 언어 데이터 없음({lang}): {msg[:200]}") from None
        raise
    except RuntimeError as e:          # pytesseract signals a timeout with a plain RuntimeError
        if "timeout" in str(e).lower():
            raise OcrTimeout(f"tesseract 가 {timeout}s 안에 끝나지 않음") from None
        raise


def image_to_data(img: Any, lang: str = "kor+eng", config: str = "", timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """pytesseract.image_to_data as a dict of lists (level, left, top, width, height, conf, text ...)."""
    pyt = _pyt()
    return _call("image_to_data", img, lang, config, timeout, output_type=pyt.Output.DICT)


def image_to_string(img: Any, lang: str = "kor+eng", config: str = "", timeout: float = DEFAULT_TIMEOUT_S) -> str:
    return _call("image_to_string", img, lang, config, timeout)


def available(lang: str | None = None) -> bool:
    """True when pytesseract + tesseract (and ``lang``, e.g. 'kor', if given) are usable."""
    try:
        pyt = _pyt()
        with tesseract_env():
            pyt.get_tesseract_version()
            if lang:
                have = set(pyt.get_languages(config=""))
                return all(x in have for x in lang.split("+"))
        return True
    except Exception:
        return False
