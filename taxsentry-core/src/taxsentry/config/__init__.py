"""TaxSentry Config Module."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_CONFIG_IMPL = Path(__file__).resolve().parent.parent / "config.py"
_SPEC = spec_from_file_location("taxsentry._config_impl", _CONFIG_IMPL)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - fatal import guard
    raise ImportError(f"Unable to load TaxSentry config implementation from {_CONFIG_IMPL}")

_IMPL = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPL)

__all__: list[str] = []
for _name in dir(_IMPL):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_IMPL, _name)
    __all__.append(_name)

del _name, _IMPL, _SPEC, _CONFIG_IMPL
