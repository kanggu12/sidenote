"""Optional OCR text extraction for the change-detection gate.

A pixel signature (gate.py) is background-invariant and layout-sensitive but
cannot read text, so two differently-worded problems on an identical template
look the same to it. This extractor reads the on-screen text so the detector can
tell them apart. It is optional (install server/requirements-ocr.txt); the gate
degrades to the pixel signature when it is unavailable.

Engine: rapidocr-onnxruntime (pip-only, CPU, no system Tesseract).
"""
from __future__ import annotations

import logging

from . import forksafe

log = logging.getLogger("sidenote.ocr")


class OcrTextExtractor:
    available = True

    def __init__(self):
        import os

        import numpy  # noqa: F401

        # ONNX Runtime starts a thread per core unless told otherwise. This engine shares a process
        # with the transcriber's own native threads and with the event loop that answers the panel,
        # so it is held to two: a crop waits about a second for it either way, and the rest of the
        # machine is the user's. Set before the import, which is when the runtime reads them. The
        # two arguments below are not decoration: read back off the built sessions, both the
        # detection and the recognition one come out at intra=2, inter=1.
        for var in ("OMP_NUM_THREADS", "ORT_NUM_THREADS"):
            os.environ.setdefault(var, "2")
        from rapidocr_onnxruntime import RapidOCR

        self._np = numpy
        log.info("loading RapidOCR engine")
        self._engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)

    def run(self, img) -> tuple[str, list[tuple[float, float, float, float]]]:
        """OCR a PIL image -> (joined on-screen text, per-line (x0,y0,x1,y1) boxes).

        Boxes are axis-aligned pixel rectangles in the given image's coordinates,
        used by the problem-region crop; the text feeds the change-detection gate.
        """
        with forksafe.native_work():   # its native thread pool: a fork during this can hang the server (forksafe.py)
            result, _elapse = self._engine(self._np.array(img))
        if not result:
            return "", []
        texts: list[str] = []
        boxes: list[tuple[float, float, float, float]] = []
        for box, text, _score in result:  # rapidocr rows are [box(4 pts), text, score]
            pts = self._np.array(box)
            boxes.append((float(pts[:, 0].min()), float(pts[:, 1].min()),
                          float(pts[:, 0].max()), float(pts[:, 1].max())))
            texts.append(text)
        return " ".join(texts), boxes


def make_ocr(cfg):
    """Return an OcrTextExtractor, or None when OCR is off or unavailable. OCR is opt-in and the
    container image leaves it out (server/requirements-ocr.txt): asking for it there falls back to
    the pixel signature gate with a warning, instead of the server failing to start."""
    if cfg.gate == "signature":
        return None
    if cfg.gate in ("ocr", "hybrid", "auto"):
        try:
            return OcrTextExtractor()
        except Exception as exc:  # pragma: no cover - env dependent
            log.warning("OCR engine unavailable (%s); SIDENOTE_GATE=%s falls back to the pixel signature gate",
                        exc, cfg.gate)
            return None
    return None
