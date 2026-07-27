from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlparse

from . import __version__


class SkillValidationError(ValueError):
    pass


class SkillSecurityError(PermissionError):
    pass


_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DEPENDENCY_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+!-]*$"
)
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _version_core(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise SkillValidationError(f"Version không hợp lệ: {value}")
    return tuple(map(int, match.groups()))


def parse_yaml_mapping(text: str) -> dict[str, Any]:
    """Parse the deliberately small YAML subset used by TaxSentry manifests."""

    lines = text.replace("\r\n", "\n").splitlines()

    def meaningful(index: int) -> int:
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped and not stripped.startswith("#"):
                return index
            index += 1
        return index

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        index = meaningful(index)
        if index >= len(lines):
            return {}, index
        first = lines[index]
        if "\t" in first[: len(first) - len(first.lstrip())]:
            raise SkillValidationError("Manifest không được dùng tab để thụt dòng")
        is_list = first.lstrip().startswith("- ")
        value: Any = [] if is_list else {}
        while (index := meaningful(index)) < len(lines):
            raw = lines[index]
            if "\t" in raw[: len(raw) - len(raw.lstrip())]:
                raise SkillValidationError("Manifest không được dùng tab để thụt dòng")
            current_indent = len(raw) - len(raw.lstrip(" "))
            if current_indent < indent:
                break
            if current_indent > indent:
                raise SkillValidationError(f"Thụt dòng không hợp lệ ở dòng {index + 1}")
            item = raw.strip()
            if is_list:
                if not item.startswith("- "):
                    raise SkillValidationError(f"Danh sách không hợp lệ ở dòng {index + 1}")
                value.append(_parse_scalar(item[2:].strip()))
                index += 1
                continue
            if item.startswith("- ") or ":" not in item:
                raise SkillValidationError(f"Thuộc tính không hợp lệ ở dòng {index + 1}")
            key, raw_value = item.split(":", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
                raise SkillValidationError(f"Tên thuộc tính không hợp lệ: {key!r}")
            if key in value:
                raise SkillValidationError(f"Thuộc tính bị lặp: {key}")
            raw_value = raw_value.strip()
            index += 1
            if raw_value:
                value[key] = _parse_scalar(raw_value)
                continue
            child = meaningful(index)
            if child >= len(lines):
                value[key] = {}
                index = child
                continue
            child_indent = len(lines[child]) - len(lines[child].lstrip(" "))
            if child_indent <= indent:
                value[key] = {}
                continue
            value[key], index = parse_block(child, child_indent)
        return value, index

    parsed, end = parse_block(0, 0)
    if meaningful(end) != len(lines) or not isinstance(parsed, dict):
        raise SkillValidationError("Manifest phải là một mapping YAML")
    return parsed


def _parse_scalar(value: str) -> Any:
    if not value:
        return ""
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if value[0] in "&*!>|":
        raise SkillValidationError("YAML tag, anchor và multiline scalar không được hỗ trợ")
    if value.startswith("[") and value.endswith("]"):
        inside = value[1:-1].strip()
        if not inside:
            return []
        return [_parse_scalar(item.strip()) for item in next(csv.reader([inside]))]
    if value.startswith("{") and value.endswith("}"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SkillValidationError("Inline mapping phải là JSON hợp lệ") from exc
        return parsed
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise SkillValidationError("Chuỗi JSON không hợp lệ") from exc
        return value[1:-1].replace("''", "'")
    return value


def _as_string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise SkillValidationError(f"{field_name} phải là danh sách chuỗi")
    return tuple(value)


def _safe_relative(value: str, field_name: str = "path") -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SkillSecurityError(f"{field_name} phải là đường dẫn tương đối an toàn")
    return path.as_posix()


@dataclass(frozen=True)
class PermissionManifest:
    filesystem_read: tuple[str, ...] = ()
    filesystem_write: tuple[str, ...] = ()
    network_domains: tuple[str, ...] = ()
    process: bool = False
    external_send: bool = False

    @classmethod
    def from_mapping(cls, raw: Any) -> PermissionManifest:
        if not isinstance(raw, dict):
            raise SkillValidationError("permissions phải là mapping")
        allowed = {"filesystem", "network_domains", "process", "external_send"}
        unknown = set(raw) - allowed
        if unknown:
            raise SkillValidationError(f"Permission không được hỗ trợ: {', '.join(sorted(unknown))}")
        filesystem = raw.get("filesystem", {})
        if not isinstance(filesystem, dict) or set(filesystem) - {"read", "write"}:
            raise SkillValidationError("permissions.filesystem chỉ hỗ trợ read/write")
        reads = tuple(
            _safe_relative(item, "filesystem.read")
            for item in _as_string_list(filesystem.get("read", []), "filesystem.read")
        )
        writes = tuple(
            _safe_relative(item, "filesystem.write")
            for item in _as_string_list(filesystem.get("write", []), "filesystem.write")
        )
        domains = _as_string_list(raw.get("network_domains", []), "network_domains")
        for domain in domains:
            if not _DOMAIN_RE.fullmatch(domain.casefold()):
                raise SkillSecurityError(f"Domain không hợp lệ: {domain}")
        process = raw.get("process", False)
        external_send = raw.get("external_send", False)
        if not isinstance(process, bool) or not isinstance(external_send, bool):
            raise SkillValidationError("process và external_send phải là boolean")
        return cls(reads, writes, tuple(item.casefold() for item in domains), process, external_send)


@dataclass(frozen=True)
class SkillSource:
    kind: str
    location: str
    commit: str = ""
    catalog: str = ""
    signature: str = ""

    @classmethod
    def from_mapping(cls, raw: Any) -> SkillSource:
        if not isinstance(raw, dict):
            raise SkillValidationError("source phải là mapping")
        if set(raw) - {"kind", "location", "commit", "catalog", "signature"}:
            raise SkillValidationError("source chứa thuộc tính không được hỗ trợ")
        source = cls(
            kind=str(raw.get("kind", "")),
            location=str(raw.get("location", "")),
            commit=str(raw.get("commit", "")).casefold(),
            catalog=str(raw.get("catalog", "")),
            signature=str(raw.get("signature", "")),
        )
        source.validate()
        return source

    def validate(self) -> None:
        if self.kind not in {"local", "github", "marketplace"} or not self.location:
            raise SkillValidationError("source.kind/location không hợp lệ")
        if self.kind == "local":
            if self.commit or self.catalog or self.signature:
                raise SkillValidationError("Local skill không được khai commit/catalog/signature")
            if self.location != ".":
                _safe_relative(self.location, "local source")
            return
        parsed = urlparse(self.location)
        try:
            port = parsed.port
        except ValueError as exc:
            raise SkillSecurityError("Remote skill URL không hợp lệ") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or port not in {None, 443}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or len([part for part in parsed.path.split("/") if part]) < 2
        ):
            raise SkillSecurityError("Remote skill phải dùng URL HTTPS trên github.com")
        if not _COMMIT_RE.fullmatch(self.commit):
            raise SkillSecurityError("Remote skill phải pin Git commit SHA-1 đầy đủ")
        if self.kind == "marketplace" and (not self.catalog or not self.signature):
            raise SkillSecurityError("Marketplace skill phải có catalog và chữ ký")


@dataclass(frozen=True)
class SkillManifest:
    name: str
    version: str
    description: str
    author: str
    platforms: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    capabilities: tuple[str, ...]
    permissions: PermissionManifest
    dependencies: tuple[str, ...]
    source: SkillSource
    checksum: str
    signature: str
    minimum_taxsentry_version: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SkillManifest:
        required = {
            "name",
            "version",
            "description",
            "author",
            "platforms",
            "jurisdictions",
            "capabilities",
            "permissions",
            "dependencies",
            "source",
            "checksum",
            "signature",
            "minimum_taxsentry_version",
        }
        missing = required - set(raw)
        if missing:
            raise SkillValidationError(f"Thiếu thuộc tính: {', '.join(sorted(missing))}")
        if set(raw) - required:
            raise SkillValidationError(f"Thuộc tính không hỗ trợ: {', '.join(sorted(set(raw) - required))}")
        manifest = cls(
            name=str(raw["name"]).casefold(),
            version=str(raw["version"]),
            description=str(raw["description"]).strip(),
            author=str(raw["author"]).strip(),
            platforms=_as_string_list(raw["platforms"], "platforms"),
            jurisdictions=_as_string_list(raw["jurisdictions"], "jurisdictions"),
            capabilities=_as_string_list(raw["capabilities"], "capabilities"),
            permissions=PermissionManifest.from_mapping(raw["permissions"]),
            dependencies=_as_string_list(raw["dependencies"], "dependencies"),
            source=SkillSource.from_mapping(raw["source"]),
            checksum=str(raw["checksum"]).casefold(),
            signature=str(raw["signature"]),
            minimum_taxsentry_version=str(raw["minimum_taxsentry_version"]),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if not _NAME_RE.fullmatch(self.name):
            raise SkillValidationError("Skill name phải là slug chữ thường")
        if not _VERSION_RE.fullmatch(self.version) or not _VERSION_RE.fullmatch(
            self.minimum_taxsentry_version
        ):
            raise SkillValidationError("version phải theo SemVer")
        if _version_core(self.minimum_taxsentry_version) > _version_core(__version__):
            raise SkillValidationError(
                f"Skill yêu cầu TaxSentry >= {self.minimum_taxsentry_version}"
            )
        if not self.description or not self.author or not self.platforms or not self.capabilities:
            raise SkillValidationError("description, author, platforms và capabilities không được rỗng")
        if not _CHECKSUM_RE.fullmatch(self.checksum):
            raise SkillValidationError("checksum phải là SHA-256")
        for dependency in self.dependencies:
            if not _DEPENDENCY_RE.fullmatch(dependency):
                raise SkillSecurityError(
                    f"Dependency phải pin chính xác name==version, không URL/path/option: {dependency}"
                )


@dataclass(frozen=True)
class SkillDefinition:
    manifest: SkillManifest
    instructions: str


@dataclass(frozen=True)
class SkillSummary:
    name: str
    version: str
    description: str
    status: str
    enabled: bool


def read_skill(path: Path, *, include_body: bool = True) -> SkillDefinition:
    skill_file = path / "SKILL.md" if path.is_dir() else path
    try:
        with skill_file.open(encoding="utf-8") as handle:
            if handle.readline().rstrip("\r\n") != "---":
                raise SkillValidationError("SKILL.md phải bắt đầu bằng YAML frontmatter")
            manifest_lines: list[str] = []
            for line in handle:
                if line.rstrip("\r\n") == "---":
                    break
                manifest_lines.append(line)
            else:
                raise SkillValidationError("SKILL.md thiếu dấu đóng frontmatter")
            body = handle.read().strip() if include_body else ""
    except (OSError, UnicodeError) as exc:
        raise SkillValidationError(f"Không đọc được SKILL.md: {exc}") from exc
    if include_body and not body:
        raise SkillValidationError("SKILL.md phải có phần hướng dẫn")
    return SkillDefinition(
        SkillManifest.from_mapping(parse_yaml_mapping("".join(manifest_lines))),
        body,
    )


def compute_skill_checksum(root: Path) -> str:
    root = root.resolve()
    if not root.is_dir():
        raise SkillValidationError("Skill source phải là thư mục")
    digest = hashlib.sha256()
    files = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for path in files:
        if path.is_symlink():
            raise SkillSecurityError("Skill không được chứa symlink")
        if not path.is_file():
            continue
        relative = _safe_relative(path.relative_to(root).as_posix(), "skill file")
        payload = path.read_bytes()
        if relative == "SKILL.md":
            payload = payload.replace(b"\r\n", b"\n")
            payload = re.sub(
                rb"(?m)^checksum:[^\n]*$",
                b"checksum:",
                payload,
                count=1,
            )
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def validate_skill_directory(root: Path) -> SkillDefinition:
    skill = read_skill(root)
    actual = compute_skill_checksum(root)
    if actual != skill.manifest.checksum:
        raise SkillSecurityError(
            f"Skill checksum không khớp: expected {skill.manifest.checksum}, got {actual}"
        )
    return skill


class SkillRegistry:
    """Versioned registry. Every install lands in drafts until explicitly approved."""

    def __init__(self, root: Path):
        self.root = root
        self.drafts = root / ".drafts"
        self.installed = root / "installed"
        self.state_file = root / "registry.json"

    def stage(self, source_dir: Path) -> SkillSummary:
        skill = validate_skill_directory(source_dir)
        target = self.drafts / skill.manifest.name / skill.manifest.version
        if target.exists():
            raise SkillValidationError("Bản skill này đã tồn tại trong drafts")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target, symlinks=False)
        validate_skill_directory(target)
        return SkillSummary(
            skill.manifest.name,
            skill.manifest.version,
            skill.manifest.description,
            "draft",
            False,
        )

    def approve(self, name: str, version: str, *, approved_by: str) -> SkillSummary:
        name = self._name(name)
        version = self._version(version)
        if not approved_by.strip():
            raise SkillValidationError("approved_by không được rỗng")
        draft = self.drafts / name / version
        skill = validate_skill_directory(draft)
        if skill.manifest.name != name or skill.manifest.version != version:
            raise SkillSecurityError("Tên/version draft không khớp đường dẫn registry")
        target = self.installed / name / version
        if target.exists():
            raise SkillValidationError("Bản skill này đã được cài")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(draft), str(target))
        state = self._state()
        entry = state.setdefault("skills", {}).setdefault(name, {"enabled": "", "history": [], "approvals": {}})
        previous = entry.get("enabled", "")
        if previous:
            entry["history"].append(previous)
        entry["enabled"] = version
        entry["approvals"][version] = {
            "approved_by": approved_by.strip(),
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "checksum": skill.manifest.checksum,
            "description": skill.manifest.description,
        }
        self._write_state(state)
        return SkillSummary(name, version, skill.manifest.description, "installed", True)

    def rollback(self, name: str, version: str | None = None) -> SkillSummary:
        name = self._name(name)
        if version is not None:
            version = self._version(version)
        state = self._state()
        entry = state.get("skills", {}).get(name)
        if not entry or not entry.get("enabled"):
            raise SkillValidationError("Skill chưa được enable")
        if version is None:
            history = entry.get("history", [])
            if not history:
                raise SkillValidationError("Không có phiên bản để rollback")
            version = history.pop()
        target = self.installed / name / version
        if version not in entry.get("approvals", {}):
            raise SkillSecurityError("Không thể rollback tới phiên bản chưa được phê duyệt")
        skill = validate_skill_directory(target)
        current = entry["enabled"]
        if current != version:
            entry.setdefault("history", []).append(current)
        entry["enabled"] = version
        self._write_state(state)
        return SkillSummary(name, version, skill.manifest.description, "installed", True)

    def disable(self, name: str) -> None:
        name = self._name(name)
        state = self._state()
        entry = state.get("skills", {}).get(name)
        if not entry:
            raise SkillValidationError("Skill chưa được cài")
        if entry.get("enabled"):
            entry.setdefault("history", []).append(entry["enabled"])
        entry["enabled"] = ""
        self._write_state(state)

    def index(self) -> list[SkillSummary]:
        state = self._state().get("skills", {})
        summaries: list[SkillSummary] = []
        for status, base in (("installed", self.installed), ("draft", self.drafts)):
            if not base.is_dir():
                continue
            for skill_file in sorted(base.glob("*/*/SKILL.md")):
                skill = read_skill(skill_file, include_body=False)
                enabled = (
                    status == "installed"
                    and state.get(skill.manifest.name, {}).get("enabled") == skill.manifest.version
                )
                summaries.append(
                    SkillSummary(
                        skill.manifest.name,
                        skill.manifest.version,
                        skill.manifest.description,
                        status,
                        enabled,
                    )
                )
        return summaries

    def enabled_index(self) -> list[SkillSummary]:
        """Return prompt-safe metadata without reading drafts or instruction bodies."""

        summaries: list[SkillSummary] = []
        for name, entry in sorted(self._state().get("skills", {}).items()):
            version = entry.get("enabled", "")
            if not version:
                continue
            version = self._version(version)
            approval = entry.get("approvals", {}).get(version)
            if (
                not isinstance(approval, dict)
                or not _CHECKSUM_RE.fullmatch(str(approval.get("checksum", "")))
                or not str(approval.get("description", "")).strip()
            ):
                raise SkillSecurityError(f"Enabled skill metadata chưa được phê duyệt: {name}")
            summaries.append(
                SkillSummary(
                    self._name(name),
                    version,
                    str(approval["description"]),
                    "installed",
                    True,
                )
            )
        return summaries

    def view(
        self,
        name: str,
        version: str | None = None,
        *,
        include_drafts: bool = False,
    ) -> SkillDefinition:
        name = self._name(name)
        if version is None:
            version = self._state().get("skills", {}).get(name, {}).get("enabled")
        if not version:
            raise SkillValidationError("Cần chỉ định version hoặc enable skill trước")
        version = self._version(version)
        installed = self.installed / name / version
        if installed.is_dir():
            return validate_skill_directory(installed)
        draft = self.drafts / name / version
        if include_drafts and draft.is_dir():
            return validate_skill_directory(draft)
        raise SkillValidationError("Không tìm thấy skill")

    @staticmethod
    def _name(value: str) -> str:
        value = value.casefold()
        if not _NAME_RE.fullmatch(value):
            raise SkillSecurityError("Skill name không hợp lệ")
        return value

    @staticmethod
    def _version(value: str) -> str:
        if not _VERSION_RE.fullmatch(value):
            raise SkillSecurityError("Skill version không hợp lệ")
        return value

    def _state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "skills": {}}
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillValidationError(f"Registry state không hợp lệ: {exc}") from exc
        if state.get("schema_version") != 1 or not isinstance(state.get("skills"), dict):
            raise SkillValidationError("Registry state không đúng schema")
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_file)


@dataclass(frozen=True)
class MarketplaceSkill:
    name: str
    version: str
    repository: str
    commit: str
    path: str
    checksum: str


@dataclass(frozen=True)
class MarketplaceCatalog:
    catalog_id: str
    repository: str
    commit: str
    generated_at: str
    public_key_id: str
    signature: str
    skills: tuple[MarketplaceSkill, ...]
    verified: bool = field(default=False, init=False, repr=False, compare=False)

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        verify_signature: Callable[[str, bytes, str], bool] | None,
    ) -> MarketplaceCatalog:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillValidationError(f"Catalog không hợp lệ: {exc}") from exc
        required = {
            "schema_version",
            "catalog_id",
            "repository",
            "commit",
            "generated_at",
            "public_key_id",
            "signature",
            "skills",
        }
        if not isinstance(raw, dict) or set(raw) != required or raw["schema_version"] != 1:
            raise SkillValidationError("Marketplace catalog không đúng schema v1")
        if verify_signature is None:
            raise SkillSecurityError("Marketplace catalog cần signature verifier")
        signature = str(raw["signature"])
        try:
            base64.b64decode(signature, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise SkillSecurityError("Catalog signature không phải base64 hợp lệ") from exc
        unsigned = {key: value for key, value in raw.items() if key != "signature"}
        payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if not verify_signature(str(raw["public_key_id"]), payload, signature):
            raise SkillSecurityError("Chữ ký marketplace catalog không hợp lệ")
        repository = _pinned_github(str(raw["repository"]), str(raw["commit"]))
        if not isinstance(raw["skills"], list):
            raise SkillValidationError("Catalog skills phải là danh sách")
        skills: list[MarketplaceSkill] = []
        for item in raw["skills"]:
            if not isinstance(item, dict) or set(item) != {
                "name",
                "version",
                "repository",
                "commit",
                "path",
                "checksum",
            }:
                raise SkillValidationError("Catalog skill không đúng schema")
            name, version = str(item["name"]), str(item["version"])
            if not _NAME_RE.fullmatch(name) or not _VERSION_RE.fullmatch(version):
                raise SkillValidationError("Catalog skill name/version không hợp lệ")
            skills.append(
                MarketplaceSkill(
                    name,
                    version,
                    _pinned_github(str(item["repository"]), str(item["commit"])),
                    str(item["commit"]).casefold(),
                    _safe_relative(str(item["path"]), "catalog skill path"),
                    _checksum(str(item["checksum"])),
                )
            )
        catalog = cls(
            str(raw["catalog_id"]),
            repository,
            str(raw["commit"]).casefold(),
            str(raw["generated_at"]),
            str(raw["public_key_id"]),
            signature,
            tuple(skills),
        )
        object.__setattr__(catalog, "verified", True)
        return catalog


def _pinned_github(repository: str, commit: str) -> str:
    parsed = urlparse(repository)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SkillSecurityError("Git source URL không hợp lệ") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len([part for part in parsed.path.split("/") if part]) < 2
        or not _COMMIT_RE.fullmatch(commit.casefold())
    ):
        raise SkillSecurityError("Git source phải là github.com HTTPS và pin commit SHA-1")
    return repository


def _checksum(value: str) -> str:
    value = value.casefold()
    if not _CHECKSUM_RE.fullmatch(value):
        raise SkillValidationError("Checksum phải là SHA-256")
    return value


class SkillService:
    """Public install/create/approval API; remote code is only staged, never imported."""

    def __init__(
        self,
        root: Path | SkillRegistry,
        *,
        source_resolver: Callable[[SkillSource], Path] | None = None,
        git_binary: str = "git",
    ):
        self.registry = root if isinstance(root, SkillRegistry) else SkillRegistry(root)
        self.source_resolver = source_resolver
        self.git_binary = git_binary

    def install(
        self,
        source: Path | str | SkillSource | MarketplaceSkill,
        *,
        expected_checksum: str = "",
        catalog: MarketplaceCatalog | None = None,
    ) -> SkillSummary:
        if isinstance(source, (Path, str)):
            source = Path(source)
            skill = validate_skill_directory(source)
            if skill.manifest.source.kind != "local":
                raise SkillSecurityError(
                    "Remote skill phải cài qua metadata đã pin, không qua local path"
                )
            return self.registry.stage(source)

        subpath = ""
        if isinstance(source, MarketplaceSkill):
            if catalog is None or not catalog.verified or source not in catalog.skills:
                raise SkillSecurityError("Marketplace skill cần catalog đã xác minh")
            metadata = SkillSource(
                "marketplace",
                source.repository,
                source.commit,
                catalog.catalog_id,
                catalog.signature,
            )
            metadata.validate()
            expected_checksum = source.checksum
            subpath = source.path
        else:
            metadata = source
            metadata.validate()
            if metadata.kind == "local":
                return self.install(Path(metadata.location))
            if metadata.kind == "marketplace":
                raise SkillSecurityError(
                    "Marketplace install phải dùng item từ catalog đã xác minh"
                )
            if not expected_checksum:
                raise SkillSecurityError("GitHub install cần expected_checksum độc lập")
            expected_checksum = _checksum(expected_checksum)

        with self._resolve(metadata) as checkout:
            skill_root = checkout / subpath if subpath else checkout
            skill = validate_skill_directory(skill_root)
            if skill.manifest.source != metadata:
                raise SkillSecurityError("Skill source metadata không khớp nguồn đã pin")
            if skill.manifest.checksum != expected_checksum:
                raise SkillSecurityError("Skill checksum không khớp nguồn đã pin")
            return self.registry.stage(skill_root)

    def approve(self, name: str, version: str, *, approved_by: str) -> SkillSummary:
        return self.registry.approve(name, version, approved_by=approved_by)

    def create_draft(
        self,
        manifest: Mapping[str, Any],
        instructions: str,
        *,
        files: Mapping[str, str | bytes] | None = None,
    ) -> SkillSummary:
        if not instructions.strip():
            raise SkillValidationError("Skill instructions không được rỗng")
        raw = dict(manifest)
        if "permissions" not in raw or "signature" not in raw:
            raise SkillValidationError("Self-created skill phải khai permissions và signature")
        raw["checksum"] = "0" * 64
        definition = SkillManifest.from_mapping(raw)
        if definition.source.kind != "local" or definition.source.location != ".":
            raise SkillSecurityError("Self-created skill phải dùng local source và vào drafts")
        payloads = dict(files or {})
        if len(payloads) > 256:
            raise SkillSecurityError("Skill draft vượt giới hạn 256 files")
        if any(not isinstance(value, (str, bytes)) for value in payloads.values()):
            raise SkillValidationError("Draft file phải là str hoặc bytes")
        total_size = sum(
            len(value.encode("utf-8") if isinstance(value, str) else value)
            for value in payloads.values()
        )
        if total_size > 10_000_000:
            raise SkillSecurityError("Skill draft vượt giới hạn 10 MB")

        self.registry.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".skill-draft-",
            dir=self.registry.root,
        ) as temporary:
            root = Path(temporary)
            for relative, value in payloads.items():
                relative = _safe_relative(relative, "draft file")
                if relative == "SKILL.md":
                    raise SkillSecurityError("files không được ghi đè SKILL.md")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(value, str):
                    target.write_text(value, encoding="utf-8")
                elif isinstance(value, bytes):
                    target.write_bytes(value)
            skill_file = root / "SKILL.md"
            skill_file.write_text(
                _skill_markdown(raw, instructions),
                encoding="utf-8",
            )
            checksum = compute_skill_checksum(root)
            skill_file.write_text(
                skill_file.read_text(encoding="utf-8").replace("0" * 64, checksum, 1),
                encoding="utf-8",
            )
            return self.registry.stage(root)

    @contextmanager
    def _resolve(self, source: SkillSource) -> Iterator[Path]:
        if self.source_resolver is not None:
            resolved = self.source_resolver(source).resolve()
            if not resolved.is_dir():
                raise SkillValidationError("Source resolver không trả về thư mục")
            yield resolved
            return
        self.registry.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".skill-git-",
            dir=self.registry.root,
        ) as temporary:
            checkout = Path(temporary) / "checkout"
            self._git(("init", str(checkout)))
            self._git(("-C", str(checkout), "remote", "add", "origin", source.location))
            self._git(
                (
                    "-C",
                    str(checkout),
                    "fetch",
                    "--depth=1",
                    "origin",
                    source.commit,
                )
            )
            self._git(("-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"))
            result = self._git(("-C", str(checkout), "rev-parse", "HEAD"))
            if result.stdout.strip().casefold() != source.commit:
                raise SkillSecurityError("Git checkout không khớp commit đã pin")
            yield checkout

    def _git(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.git_binary, *args],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SkillValidationError(f"Không chạy được Git checkout: {exc}") from exc
        if result.returncode:
            raise SkillValidationError(
                f"Git checkout thất bại: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result


def _skill_markdown(manifest: Mapping[str, Any], instructions: str) -> str:
    order = (
        "name",
        "version",
        "description",
        "author",
        "platforms",
        "jurisdictions",
        "capabilities",
        "permissions",
        "dependencies",
        "source",
        "checksum",
        "signature",
        "minimum_taxsentry_version",
    )
    values = "\n".join(
        f"{key}: {json.dumps(manifest[key], ensure_ascii=False, separators=(',', ':'))}"
        for key in order
    )
    return f"---\n{values}\n---\n{instructions.strip()}\n"


@dataclass(frozen=True)
class SandboxExecutionPolicy:
    image: str
    timeout_seconds: int = 120
    memory: str = "256m"
    cpus: str = "1.0"
    pids_limit: int = 64
    docker_binary: str = "docker"

    def __post_init__(self) -> None:
        if not re.search(r"@sha256:[0-9a-f]{64}$", self.image):
            raise SkillSecurityError("Sandbox image phải pin bằng sha256 digest")
        if self.timeout_seconds <= 0 or self.pids_limit <= 0:
            raise SkillValidationError("Sandbox limits phải lớn hơn 0")

    def command(
        self,
        skill_root: Path,
        script: str,
        permissions: PermissionManifest,
        args: Sequence[str] = (),
        mounts: Mapping[str, Path] | None = None,
    ) -> list[str]:
        validated_permissions = validate_skill_directory(skill_root).manifest.permissions
        if permissions != validated_permissions:
            raise SkillSecurityError("Permission manifest không khớp skill đã xác minh")
        if not permissions.process:
            raise SkillSecurityError("Skill chưa được cấp quyền process")
        if permissions.network_domains:
            raise SkillSecurityError(
                "Docker runner mặc định chỉ hỗ trợ network=none; cần egress runner có domain enforcement"
            )
        script = _safe_relative(script, "script")
        if not script.startswith("scripts/"):
            raise SkillSecurityError("Chỉ script trong thư mục scripts/ được chạy")
        root = skill_root.resolve()
        target = (root / Path(script)).resolve()
        if root not in target.parents or not target.is_file() or target.is_symlink():
            raise SkillSecurityError("Script không tồn tại hoặc thoát khỏi skill root")
        command = [
            self.docker_binary,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=65532:65532",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,src={root},dst=/skill,readonly",
        ]
        allowed_read = set(permissions.filesystem_read)
        allowed_write = set(permissions.filesystem_write)
        for alias, host_path in sorted((mounts or {}).items()):
            alias = _safe_relative(alias, "mount alias")
            if alias not in allowed_read | allowed_write:
                raise SkillSecurityError(f"Skill chưa được cấp quyền filesystem cho {alias}")
            host = host_path.resolve()
            if not host.exists() or any(character in str(host) for character in ",\r\n"):
                raise SkillSecurityError(f"Mount host path không hợp lệ: {host}")
            readonly = ",readonly" if alias not in allowed_write else ""
            command.extend(
                [
                    "--mount",
                    f"type=bind,src={host},dst=/workspace/{alias}{readonly}",
                ]
            )
        return [*command, self.image, f"/skill/{script}", *[str(arg) for arg in args]]

    def run(
        self,
        skill_root: Path,
        script: str,
        permissions: PermissionManifest,
        args: Sequence[str] = (),
        mounts: Mapping[str, Path] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command(skill_root, script, permissions, args, mounts),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
            shell=False,
        )
