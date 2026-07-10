from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Extraction:
    content: dict | str
    confidence: float
    source: str


def extract(path: Path, languages: list[str]) -> Extraction:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        from .core.excel_parser import TaxSentryParser

        parser = TaxSentryParser(str(path))
        parser.load()
        if not parser.has_meaningful_data():
            return Extraction({}, 0.0, "xlsx")
        return Extraction(json.loads(parser.export_json()), 1.0, "xlsx")
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as document:
            text = "\n".join(page.extract_text() or "" for page in document.pages).strip()
        if len(text) >= 80:
            return Extraction(text, 1.0, "pdf-text")
        return _ocr_pdf(path, languages)
    if suffix in {".png", ".jpg", ".jpeg"}:
        return _ocr_image(path, languages)
    raise ValueError(f"Unsupported attachment: {suffix}")


def _ocr_pdf(path: Path, languages: list[str]) -> Extraction:
    import fitz
    from PIL import Image

    pages, scores = [], []
    with fitz.open(path) as document:
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            result = _ocr(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples), languages)
            pages.append(result.content)
            scores.append(result.confidence)
    return Extraction("\n\n".join(map(str, pages)), sum(scores) / len(scores) if scores else 0.0, "pdf-ocr")


def _ocr_image(path: Path, languages: list[str]) -> Extraction:
    from PIL import Image

    return _ocr(Image.open(path), languages)


def _ocr(image, languages: list[str]) -> Extraction:
    import pytesseract

    lang = "+".join(languages)
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    words, confidence = [], []
    for text, score in zip(data["text"], data["conf"]):
        text = str(text).strip()
        try:
            value = float(score)
        except (TypeError, ValueError):
            value = -1
        if text:
            words.append(text)
        if value >= 0:
            confidence.append(value)
    return Extraction(" ".join(words), (sum(confidence) / len(confidence) / 100) if confidence else 0.0, "ocr")
