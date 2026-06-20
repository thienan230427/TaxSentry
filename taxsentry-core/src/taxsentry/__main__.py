"""
Main entry point for TaxSentry AI Agent.
Allows running with: python -m taxsentry
"""

import sys
from pathlib import Path

# Ensure the package is importable even if not installed
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxsentry.utils.runtime import bootstrap_into_venv

bootstrap_into_venv(["-m", "taxsentry", *sys.argv[1:]])

from taxsentry.ui.tui import main

if __name__ == "__main__":
    main()
