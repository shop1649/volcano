"""shortkit.util.ocr: OMP_THREAD_LIMIT=1 for every tesseract subprocess + timeouts."""
from __future__ import annotations

import os

import pytest


def test_env_forced_during_call_and_restored(monkeypatch):
    pyt = pytest.importorskip("pytesseract")
    from shortkit.util import ocr

    seen = {}

    def fake(img, lang, config, timeout, **kw):
        seen.update(env=os.environ.get("OMP_THREAD_LIMIT"), timeout=timeout, lang=lang, config=config, kw=kw)
        return "가나"

    monkeypatch.setattr(pyt, "image_to_string", fake)
    monkeypatch.setenv("OMP_THREAD_LIMIT", "4")
    import numpy as np

    assert ocr.image_to_string(np.zeros((10, 10), np.uint8), lang="kor", config="--psm 7", timeout=3) == "가나"
    assert seen["env"] == "1" and seen["timeout"] == 3 and seen["lang"] == "kor" and seen["config"] == "--psm 7"
    assert os.environ["OMP_THREAD_LIMIT"] == "4"            # restored
    monkeypatch.delenv("OMP_THREAD_LIMIT")
    with ocr.tesseract_env():
        with ocr.tesseract_env():                            # nesting shares one reference count
            assert os.environ["OMP_THREAD_LIMIT"] == "1"
        assert os.environ["OMP_THREAD_LIMIT"] == "1"
    assert "OMP_THREAD_LIMIT" not in os.environ


def test_timeout_and_missing_binary_are_explicit(monkeypatch):
    pyt = pytest.importorskip("pytesseract")
    from shortkit.util import ocr

    def slow(*a, **k):
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr(pyt, "image_to_data", slow)
    with pytest.raises(ocr.OcrTimeout):
        ocr.image_to_data([[0]], timeout=0.01)

    def missing(*a, **k):
        raise pyt.TesseractNotFoundError()

    monkeypatch.setattr(pyt, "image_to_data", missing)
    with pytest.raises(ocr.OcrUnavailable):
        ocr.image_to_data([[0]])


def test_real_tesseract_reads_text():
    from shortkit.util import ocr

    if not ocr.available("eng"):
        pytest.skip("tesseract/eng not installed")
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("L", (360, 80), 255)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(im).text((10, 15), "HELLO 42", fill=0, font=font)
    txt = ocr.image_to_string(im, lang="eng", config="--psm 7", timeout=20)
    assert "HELLO" in txt and "42" in txt
    d = ocr.image_to_data(im, lang="eng", config="--psm 7", timeout=20)
    assert "HELLO" in [w.strip() for w in d["text"]]
