"""Centralized path management for TaxSentry AI Agent."""
import os
from pathlib import Path

# Dynamic path resolution:
# Find the base directory by going up from this file (config/paths.py) to taxsentry/ root,
# then to src, then to the project root (taxsentry-core).

CURRENT_FILE = Path(__file__).resolve()
# CURRENT_FILE -> .../taxsentry-core/src/taxsentry/config/paths.py
# .parent.parent.parent.parent -> .../taxsentry-core/
BASE_DIR = CURRENT_FILE.parent.parent.parent.parent
BASE_DIR = BASE_DIR.resolve()

# Fallback for legacy execution (if run directly from old path)
if not (BASE_DIR / "pyproject.toml").exists() and not (BASE_DIR / "requirements.txt").exists():
    # Try assuming BASE_DIR is the absolute project path
    BASE_DIR = Path("D:/TaxSentry")

# Ensure base directory exists
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Define subdirectories
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

KNOWLEDGE_DIR = BASE_DIR / "src" / "taxsentry" / "knowledge_base"
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

SCRATCH_DIR = BASE_DIR / "scratch"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

# Define specific file paths
DB_PATH = BASE_DIR / "taxsentry.db"
EXCEL_PATH = BASE_DIR / "mock_report.xlsx"
JSON_PATH = BASE_DIR / "parsed_report.json"
ENV_PATH = BASE_DIR / ".env"
KNOWLEDGE_PATH = KNOWLEDGE_DIR / "tax_rules_vietnam.md"
AUDIT_REPORT_PATH = BASE_DIR / "audit_report.md"
