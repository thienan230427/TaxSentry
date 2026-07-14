from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(slots=True)
class Extraction:
    content: dict | str
    confidence: float
    source: str


def extract(path: Path, languages: list[str]) -> Extraction:
    suffix = path.suffix.lower()
    if suffix in {".doc", ".xls", ".ppt"}:
        return _legacy_office(path, languages)
    if suffix == ".docx":
        text = _open_xml_text(path, "word/document.xml")
        return Extraction(text, 1.0 if text else 0.0, "docx")
    if suffix == ".xlsx":
        from .core.excel_parser import TaxSentryParser

        parser = TaxSentryParser(str(path))
        parser.load()
        if not parser.has_meaningful_data():
            return Extraction({}, 0.0, "xlsx")
        return Extraction(json.loads(parser.export_json()), 1.0, "xlsx")
    if suffix == ".pptx":
        with zipfile.ZipFile(path) as archive:
            slides = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            text = "\n\n".join(_xml_text(archive.read(name)) for name in slides).strip()
        return Extraction(text, 1.0 if text else 0.0, "pptx")
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


def _xml_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    return " ".join(str(node.text).strip() for node in root.iter() if node.tag.endswith("}t") and node.text and str(node.text).strip())


def _open_xml_text(path: Path, member: str) -> str:
    with zipfile.ZipFile(path) as archive:
        text = _xml_text(archive.read(member)).strip()
    return text


def _legacy_office(path: Path, languages: list[str]) -> Extraction:
    command = shutil.which("soffice") or shutil.which("libreoffice")
    if not command:
        raise ValueError("LibreOffice is required to read legacy .doc/.xls/.ppt files")
    target_suffix = {".doc": "docx", ".xls": "xlsx", ".ppt": "pptx"}[path.suffix.lower()]
    with tempfile.TemporaryDirectory(prefix="taxsentry-office-") as folder:
        output = Path(folder)
        profile = output / "profile"
        try:
            result = subprocess.run(
                [command, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--convert-to", target_suffix, "--outdir", str(output), str(path)],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"LibreOffice conversion failed: {exc}") from exc
        converted = output / f"{path.stem}.{target_suffix}"
        if result.returncode or not converted.is_file() or not converted.stat().st_size:
            detail = (result.stderr or result.stdout or "conversion produced no output").strip()
            raise ValueError(f"LibreOffice conversion failed: {detail[:300]}")
        extracted = extract(converted, languages)
        return Extraction(extracted.content, extracted.confidence, f"{path.suffix.lower()[1:]}->{extracted.source}")


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
