from __future__ import annotations

import os
from pathlib import Path
from typing import MutableMapping

SECRET_ENVIRONMENTS = (
    "TAXSENTRY_POSTGRES_DSN",
    "TAXSENTRY_POSTGRES_PASSWORD",
    "TAXSENTRY_S3_ACCESS_KEY",
    "TAXSENTRY_S3_SECRET_KEY",
)


def load_secret_environment(
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load allowlisted Docker secrets without printing or passing them as arguments."""

    environ = environ if environ is not None else os.environ
    for name in SECRET_ENVIRONMENTS:
        file_name = f"{name}_FILE"
        direct = str(environ.get(name, ""))
        secret_file = str(environ.get(file_name, ""))
        if direct and secret_file:
            raise RuntimeError(f"{name} and {file_name} cannot both be set")
        if not secret_file:
            continue
        path = Path(secret_file)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
            raise RuntimeError(f"{file_name} is not a valid secret file")
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Cannot read {file_name}") from exc
        if not value or "\x00" in value or "\n" in value or "\r" in value:
            raise RuntimeError(f"{file_name} contains an invalid secret")
        environ[name] = value
        environ.pop(file_name, None)


def main() -> int:
    load_secret_environment()
    from taxsentry.data_plane.worker import main as worker_main

    return worker_main()


if __name__ == "__main__":
    raise SystemExit(main())
