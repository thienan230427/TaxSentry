from __future__ import annotations

import keyring

SERVICE = "taxsentry-v2"


def set_secret(name: str, value: str) -> None:
    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        delete_secret(name)


def get_secret(name: str) -> str:
    return keyring.get_password(SERVICE, name) or ""


def delete_secret(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
