from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import urlparse

from .queue import DataPlaneDependencyError

_BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    etag: str = ""


class ObjectStore(Protocol):
    def put_bytes(self, key: str, data: bytes) -> StoredObject: ...

    def put_file(self, key: str, source: Path, *, sha256: str | None = None) -> StoredObject: ...

    def get_bytes(self, key: str) -> bytes: ...

    def download(self, key: str, destination: Path) -> StoredObject: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


class LocalObjectStore:
    """Filesystem fallback with the same key contract as the S3 backend."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes) -> StoredObject:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        key = normalize_object_key(key)
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        _atomic_write(target, data)
        return StoredObject(key=key, size=len(data), sha256=digest)

    def put_file(self, key: str, source: Path, *, sha256: str | None = None) -> StoredObject:
        key = normalize_object_key(key)
        source = source.resolve(strict=True)
        if not source.is_file():
            raise ValueError(f"Object source is not a file: {source}")
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
                while chunk := input_file.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            actual_sha256 = digest.hexdigest()
            if sha256 and actual_sha256 != sha256:
                raise ValueError("Object source SHA-256 does not match the expected digest")
            os.replace(temporary_name, target)
            return StoredObject(key=key, size=size, sha256=actual_sha256)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def download(self, key: str, destination: Path) -> StoredObject:
        key = normalize_object_key(key)
        source = self._path(key)
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(source, temporary_name)
            os.replace(temporary_name, destination)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        return StoredObject(
            key=key,
            size=destination.stat().st_size,
            sha256=_sha256_file(destination),
        )

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        normalized = normalize_object_key(key)
        target = (self.root / Path(*PurePosixPath(normalized).parts)).resolve()
        if os.path.commonpath((self.root, target)) != str(self.root):
            raise ValueError("Object key escapes the configured store root")
        return target


class S3ObjectStore:
    """S3-compatible object store; works with MinIO through a custom endpoint."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region_name: str = "us-east-1",
        allow_insecure: bool = False,
        server_side_encryption: str | None = None,
        client=None,
    ) -> None:
        if (
            not _BUCKET_NAME.fullmatch(bucket)
            or ".." in bucket
            or ".-" in bucket
            or "-." in bucket
        ):
            raise ValueError("bucket must be a valid lowercase S3 bucket name")
        if bool(access_key) != bool(secret_key):
            raise ValueError("access_key and secret_key must be provided together")
        if endpoint_url:
            parsed = urlparse(endpoint_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("endpoint_url must be an HTTP(S) URL")
            if parsed.scheme == "http" and not allow_insecure:
                raise ValueError("HTTP object storage requires allow_insecure=True")
        self.bucket = bucket
        self.server_side_encryption = server_side_encryption
        if client is not None:
            self.client = client
            return
        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:
            raise DataPlaneDependencyError("S3/MinIO support requires `boto3==1.43.51`") from exc
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
            config=Config(s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            code = _s3_error_code(exc)
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes) -> StoredObject:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        key = normalize_object_key(key)
        digest = hashlib.sha256(data).hexdigest()
        response = self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            Metadata={"sha256": digest},
            **self._encryption(),
        )
        return StoredObject(
            key=key,
            size=len(data),
            sha256=digest,
            etag=str(response.get("ETag", "")).strip('"'),
        )

    def put_file(self, key: str, source: Path, *, sha256: str | None = None) -> StoredObject:
        key = normalize_object_key(key)
        source = source.resolve(strict=True)
        if not source.is_file():
            raise ValueError(f"Object source is not a file: {source}")
        actual_sha256 = _sha256_file(source)
        if sha256 and actual_sha256 != sha256:
            raise ValueError("Object source SHA-256 does not match the expected digest")
        extra_args = {"Metadata": {"sha256": actual_sha256}, **self._encryption()}
        self.client.upload_file(str(source), self.bucket, key, ExtraArgs=extra_args)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        return StoredObject(
            key=key,
            size=int(head["ContentLength"]),
            sha256=actual_sha256,
            etag=str(head.get("ETag", "")).strip('"'),
        )

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=normalize_object_key(key))
        return response["Body"].read()

    def download(self, key: str, destination: Path) -> StoredObject:
        key = normalize_object_key(key)
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
        os.close(fd)
        try:
            self.client.download_file(self.bucket, key, temporary_name)
            os.replace(temporary_name, destination)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        digest = _sha256_file(destination)
        metadata_digest = str(head.get("Metadata", {}).get("sha256") or "")
        if metadata_digest and metadata_digest != digest:
            destination.unlink(missing_ok=True)
            raise ValueError("Downloaded object SHA-256 does not match its metadata")
        return StoredObject(
            key=key,
            size=destination.stat().st_size,
            sha256=digest,
            etag=str(head.get("ETag", "")).strip('"'),
        )

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=normalize_object_key(key))
            return True
        except Exception as exc:
            if _s3_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=normalize_object_key(key))

    def _encryption(self) -> dict[str, str]:
        return (
            {"ServerSideEncryption": self.server_side_encryption}
            if self.server_side_encryption
            else {}
        )


def normalize_object_key(key: str) -> str:
    if (
        not isinstance(key, str)
        or not key
        or key != key.strip()
        or len(key) > 1024
        or "\\" in key
        or "\x00" in key
    ):
        raise ValueError("Object key must be a non-empty POSIX path")
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
        raise ValueError("Object key contains an unsafe path segment")
    return path.as_posix()


def _atomic_write(target: Path, data: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _s3_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    return str(response.get("Error", {}).get("Code", ""))
