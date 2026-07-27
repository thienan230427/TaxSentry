from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .documents import CoverageReport, DocumentUnit, parse_document


@dataclass(slots=True)
class Extraction:
    content: dict | str
    confidence: float
    source: str
    units: tuple[dict[str, Any], ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)


def extract(path: Path, languages: list[str]) -> Extraction:
    """Compatibility API backed by the structural Document Intelligence parser."""
    if path.suffix.casefold() in {".doc", ".xls", ".ppt"} and not (
        shutil.which("soffice") or shutil.which("libreoffice")
    ):
        raise ValueError("LibreOffice is required to read legacy .doc/.xls/.ppt files")
    parsed = parse_document(path, "compat", languages)
    units = tuple(parsed.units)
    failed = tuple(unit.locator for unit in units if unit.status != "processed")
    warnings = tuple(
        dict.fromkeys(warning for unit in units for warning in unit.warnings)
    )
    coverage = CoverageReport(
        total=len(units),
        processed=sum(unit.status == "processed" for unit in units),
        failed=len(failed),
        failed_units=failed,
        warnings=warnings,
    )
    return Extraction(
        parsed.compatibility_content,
        parsed.confidence,
        parsed.source,
        tuple(_unit_payload(unit) for unit in units),
        {**asdict(coverage), "complete": coverage.complete},
    )


def _unit_payload(unit: DocumentUnit) -> dict[str, Any]:
    payload = asdict(unit)
    payload["source_id"] = payload.pop("id")
    payload.pop("document_id", None)
    return payload
