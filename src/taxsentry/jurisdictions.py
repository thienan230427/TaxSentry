from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from . import __version__
from .skills import SkillSecurityError, _safe_relative

PACKAGE_DIR = Path(__file__).with_name("knowledge_base")


class JurisdictionPackError(ValueError):
    pass


class MissingJurisdictionPackError(JurisdictionPackError):
    pass


class UnverifiedJurisdictionPackError(JurisdictionPackError):
    pass


_PACK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _semver_core(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise JurisdictionPackError(f"Version không hợp lệ: {value}")
    return tuple(map(int, match.groups()))


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JurisdictionPackError(f"Timestamp không hợp lệ: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _strings(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or (not value and not allow_empty)
    ):
        raise JurisdictionPackError(f"{field_name} phải là danh sách chuỗi")
    return tuple(item.strip() for item in value)


def _content_checksum(root: Path, paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(paths):
        safe = _safe_relative(relative, "pack content path")
        path = (root / safe).resolve()
        if root.resolve() not in path.parents or not path.is_file() or path.is_symlink():
            raise SkillSecurityError(f"Pack content không an toàn hoặc không tồn tại: {safe}")
        payload = path.read_bytes()
        if path.suffix.casefold() in {".csv", ".json", ".md", ".txt", ".yaml", ".yml"}:
            payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(safe.encode("utf-8") + b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _safe_official_url(url: str, domains: Sequence[str]) -> bool:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        return False
    host = parsed.hostname.casefold().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host in domains
    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_reserved,
        )
    ) and host in domains


@dataclass(frozen=True)
class JurisdictionSource:
    id: str
    title: str
    issuer: str
    effective_from: str
    url: str


@dataclass(frozen=True)
class JurisdictionPack:
    id: str
    country_code: str
    name: str
    version: str
    languages: tuple[str, ...]
    currency: str
    domains: tuple[str, ...]
    effective_from: str
    verified: bool
    verified_at: datetime | None
    verification_method: str
    freshness_days: int
    official_domains: tuple[str, ...]
    rules_file: Path
    sources_file: Path
    sources: tuple[JurisdictionSource, ...]
    content_checksum: str
    manifest_path: Path
    citation_rules: Mapping[str, str] = field(default_factory=dict)
    refresh_policy: Mapping[str, Any] = field(default_factory=dict)
    signature: str = ""
    minimum_taxsentry_version: str = ""

    @classmethod
    def load(
        cls,
        manifest_path: Path,
        *,
        verify_signature: Callable[[str, bytes], bool] | None = None,
    ) -> JurisdictionPack:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JurisdictionPackError(f"Không đọc được jurisdiction manifest: {exc}") from exc
        required = {
            "schema_version",
            "id",
            "country_code",
            "name",
            "version",
            "languages",
            "currency",
            "domains",
            "effective_from",
            "verification",
            "freshness_days",
            "official_domains",
            "content",
            "content_checksum",
        }
        extended = {
            "citation_rules",
            "refresh_policy",
            "signature",
            "minimum_taxsentry_version",
        }
        structured = manifest_path.name.casefold() == "pack.yaml"
        if (
            not isinstance(raw, dict)
            or required - set(raw)
            or set(raw) - required - extended
            or raw["schema_version"] != 1
            or (structured and extended - set(raw))
        ):
            raise JurisdictionPackError("Jurisdiction manifest không đúng schema v1")
        verification = raw["verification"]
        content = raw["content"]
        if not isinstance(verification, dict) or set(verification) != {
            "verified",
            "verified_at",
            "method",
        }:
            raise JurisdictionPackError("verification không đúng schema")
        if not isinstance(content, dict) or set(content) != {"rules", "sources"}:
            raise JurisdictionPackError("content không đúng schema")
        pack_id = str(raw["id"]).casefold()
        country_code = str(raw["country_code"]).upper()
        version = str(raw["version"])
        if not _PACK_ID_RE.fullmatch(pack_id) or not _COUNTRY_RE.fullmatch(country_code):
            raise JurisdictionPackError("id/country_code không hợp lệ")
        if not _VERSION_RE.fullmatch(version):
            raise JurisdictionPackError("version phải theo SemVer")
        name = str(raw["name"]).strip()
        currency = str(raw["currency"]).upper()
        if not name or not re.fullmatch(r"[A-Z]{3}", currency):
            raise JurisdictionPackError("name/currency không hợp lệ")
        languages = _strings(raw["languages"], "languages")
        domains = _strings(raw["domains"], "domains")
        official_domains = tuple(
            item.casefold().rstrip(".")
            for item in _strings(raw["official_domains"], "official_domains")
        )
        if any(not _DOMAIN_RE.fullmatch(item) for item in official_domains):
            raise JurisdictionPackError("official_domains chứa domain không hợp lệ")
        rules_relative = _safe_relative(str(content["rules"]), "rules path")
        sources_relative = _safe_relative(str(content["sources"]), "sources path")
        expected_checksum = str(raw["content_checksum"]).casefold()
        if not _CHECKSUM_RE.fullmatch(expected_checksum):
            raise JurisdictionPackError("content_checksum phải là SHA-256")
        actual_checksum = _content_checksum(
            manifest_path.parent,
            (rules_relative, sources_relative),
        )
        if actual_checksum != expected_checksum:
            raise JurisdictionPackError(
                f"Pack checksum không khớp: expected {expected_checksum}, got {actual_checksum}"
            )
        sources_path = manifest_path.parent / sources_relative
        try:
            source_data = json.loads(sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JurisdictionPackError(f"Source registry không hợp lệ: {exc}") from exc
        if not isinstance(source_data, list) or not source_data:
            raise JurisdictionPackError("Source registry phải là danh sách không rỗng")
        sources: list[JurisdictionSource] = []
        seen_ids: set[str] = set()
        for item in source_data:
            required_source = {"id", "title", "issuer", "effective_from", "url"}
            if not isinstance(item, dict) or set(item) != required_source:
                raise JurisdictionPackError("Official source không đúng schema")
            source_id = str(item["id"])
            if source_id in seen_ids:
                raise JurisdictionPackError(f"Official source id bị lặp: {source_id}")
            seen_ids.add(source_id)
            if not _safe_official_url(str(item["url"]), official_domains):
                raise JurisdictionPackError(f"Source URL không thuộc allowlist: {item['url']}")
            sources.append(
                JurisdictionSource(
                    source_id,
                    str(item["title"]),
                    str(item["issuer"]),
                    str(item["effective_from"]),
                    str(item["url"]),
                )
            )
        freshness_days = raw["freshness_days"]
        if not isinstance(freshness_days, int) or freshness_days <= 0:
            raise JurisdictionPackError("freshness_days phải là số nguyên dương")
        citation_rules = raw.get("citation_rules", {})
        refresh_policy = raw.get("refresh_policy", {})
        signature = str(raw.get("signature", ""))
        minimum_version = str(raw.get("minimum_taxsentry_version", ""))
        if structured:
            if (
                not isinstance(citation_rules, dict)
                or set(citation_rules) != {"legal_claims", "locator"}
                or not all(
                    isinstance(value, str) and value.strip()
                    for value in citation_rules.values()
                )
                or not isinstance(refresh_policy, dict)
                or set(refresh_policy) != {"mode", "days"}
                or refresh_policy.get("mode") != "official_allowlist"
                or not isinstance(refresh_policy.get("days"), int)
                or refresh_policy["days"] <= 0
                or not signature
                or not _VERSION_RE.fullmatch(minimum_version)
            ):
                raise JurisdictionPackError(
                    "citation_rules/refresh_policy/signature/minimum version không hợp lệ"
                )
            if _semver_core(minimum_version) > _semver_core(__version__):
                raise JurisdictionPackError(
                    f"Pack yêu cầu TaxSentry >= {minimum_version}"
                )
            bundled = PACKAGE_DIR.resolve() in manifest_path.resolve().parents
            if bundled:
                if signature != "bundled-wheel-trust":
                    raise JurisdictionPackError("Bundled pack signature marker không hợp lệ")
            else:
                unsigned = {
                    key: value for key, value in raw.items() if key != "signature"
                }
                payload = json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                if verify_signature is None or not verify_signature(signature, payload):
                    raise JurisdictionPackError(
                        "External jurisdiction pack signature chưa được xác minh"
                    )
        verified = verification["verified"]
        method = str(verification["method"]).strip()
        if not isinstance(verified, bool) or not method:
            raise JurisdictionPackError("verification.verified/method không hợp lệ")
        verified_at_raw = str(verification["verified_at"])
        if verified and not verified_at_raw:
            raise JurisdictionPackError("Pack verified phải có verified_at")
        return cls(
            pack_id,
            country_code,
            name,
            version,
            languages,
            currency,
            domains,
            str(raw["effective_from"]),
            verified,
            _utc(verified_at_raw) if verified_at_raw else None,
            method,
            freshness_days,
            official_domains,
            manifest_path.parent / rules_relative,
            sources_path,
            tuple(sources),
            expected_checksum,
            manifest_path,
            citation_rules,
            refresh_policy,
            signature,
            minimum_version,
        )

    def is_fresh(self, at: datetime | None = None) -> bool:
        at = at or datetime.now(timezone.utc)
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return bool(self.verified_at) and self.verified_at <= at and at - self.verified_at <= timedelta(
            days=self.freshness_days
        )

    def assert_legal_ready(self, at: datetime | None = None) -> None:
        if not self.verified:
            raise UnverifiedJurisdictionPackError(
                f"Jurisdiction pack {self.country_code} chưa được xác minh"
            )
        if not self.is_fresh(at):
            raise UnverifiedJurisdictionPackError(
                f"Jurisdiction pack {self.country_code} đã quá hạn freshness"
            )


class JurisdictionRegistry:
    """Global financial core; legal/tax work is guarded by verified country packs."""

    def __init__(
        self,
        manifests: Iterable[Path] | None = None,
        *,
        signature_verifier: Callable[[str, bytes], bool] | None = None,
    ):
        packaged = sorted(
            PACKAGE_DIR.glob("jurisdictions/*/*/pack.yaml")
        )
        paths = (
            list(manifests)
            if manifests is not None
            else packaged or sorted(PACKAGE_DIR.glob("jurisdiction_*.json"))
        )
        self.packs: dict[str, JurisdictionPack] = {}
        for path in paths:
            pack = JurisdictionPack.load(
                path, verify_signature=signature_verifier
            )
            if pack.country_code in self.packs:
                raise JurisdictionPackError(
                    f"Trùng jurisdiction pack cho {pack.country_code}"
                )
            self.packs[pack.country_code] = pack

    def resolve(
        self,
        country_code: str,
        *,
        purpose: str = "financial",
        at: datetime | None = None,
    ) -> JurisdictionPack | None:
        country_code = country_code.upper()
        if not _COUNTRY_RE.fullmatch(country_code):
            raise JurisdictionPackError("country_code phải là ISO alpha-2")
        if purpose not in {"financial", "legal_tax"}:
            raise JurisdictionPackError("purpose chỉ nhận financial hoặc legal_tax")
        pack = self.packs.get(country_code)
        if purpose == "financial":
            return pack
        if pack is None:
            raise MissingJurisdictionPackError(
                f"Chưa có jurisdiction pack cho {country_code}; chỉ được phân tích tài chính"
            )
        pack.assert_legal_ready(at)
        return pack

    def capability(self, country_code: str, at: datetime | None = None) -> dict[str, Any]:
        country_code = country_code.upper()
        if not _COUNTRY_RE.fullmatch(country_code):
            raise JurisdictionPackError("country_code phải là ISO alpha-2")
        pack = self.packs.get(country_code)
        legal_ready = bool(pack and pack.verified and pack.is_fresh(at))
        return {
            "financial_analysis": True,
            "legal_tax_advice": legal_ready,
            "pack": pack.id if pack else "",
            "reason": (
                ""
                if legal_ready
                else "missing_knowledge"
                if pack is None
                else "unverified_or_stale"
            ),
        }


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", value.casefold(), re.UNICODE)
        if len(token) > 1
    }


def _normalize_ref(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold())


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


@dataclass(frozen=True)
class RetrievalRecord:
    id: str
    title: str
    text: str
    locator: str
    exact_refs: tuple[str, ...] = ()
    vector: tuple[float, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    exact_refs: tuple[str, ...] = ()
    vector: tuple[float, ...] = ()


@dataclass(frozen=True)
class RetrievalCandidate:
    record: RetrievalRecord
    exact_score: float | None = None
    full_text_score: float | None = None
    vector_score: float | None = None


@dataclass(frozen=True)
class RetrievalHit:
    record: RetrievalRecord
    score: float
    modes: tuple[str, ...]


class HybridRetriever:
    """Ranks exact/full-text/vector signals and falls back to deterministic local scoring."""

    def __init__(self, records: Iterable[RetrievalRecord] = ()):
        self.records = tuple(records)

    def search(
        self,
        query: RetrievalQuery,
        *,
        candidates: Iterable[RetrievalCandidate] | None = None,
        limit: int = 5,
    ) -> list[RetrievalHit]:
        if limit <= 0:
            return []
        values = (
            tuple(candidates)
            if candidates is not None
            else tuple(RetrievalCandidate(record) for record in self.records)
        )
        query_tokens = _tokens(query.text)
        query_refs = {_normalize_ref(item) for item in query.exact_refs}
        normalized_text = _normalize_ref(query.text)
        hits: list[RetrievalHit] = []
        for candidate in values:
            record = candidate.record
            record_refs = {_normalize_ref(item) for item in record.exact_refs}
            exact = candidate.exact_score
            if exact is None:
                exact = float(
                    bool(query_refs & record_refs)
                    or any(reference and reference in normalized_text for reference in record_refs)
                )
            full_text = candidate.full_text_score
            if full_text is None:
                full_text = (
                    len(query_tokens & _tokens(record.title + " " + record.text))
                    / len(query_tokens)
                    if query_tokens
                    else 0.0
                )
            vector = candidate.vector_score
            if vector is None:
                vector = _cosine(query.vector, record.vector)
            exact = min(1.0, max(0.0, float(exact)))
            full_text = min(1.0, max(0.0, float(full_text)))
            vector = min(1.0, max(0.0, float(vector)))
            score = exact * 100.0 + full_text * 10.0 + vector
            if score <= 0:
                continue
            modes = tuple(
                name
                for name, value in (
                    ("exact", exact),
                    ("full_text", full_text),
                    ("vector", vector),
                )
                if value > 0
            )
            hits.append(RetrievalHit(record, score, modes))
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]


class KnowledgeService:
    """Public guarded retrieval/refresh API over jurisdiction packs."""

    def __init__(
        self,
        registry: JurisdictionRegistry | None = None,
        *,
        retriever: HybridRetriever | None = None,
        source_refresher: Callable[[JurisdictionPack], Mapping[str, Any]] | None = None,
    ):
        self.registry = registry or JurisdictionRegistry()
        self.retriever = retriever
        self.source_refresher = source_refresher
        self._pack_retrievers: dict[tuple[str, str], HybridRetriever] = {}
        self._runtime_verified_at: dict[str, datetime] = {}

    def retrieve(
        self,
        query: str | RetrievalQuery,
        country_code: str = "VN",
        *,
        purpose: str = "financial",
        exact_refs: Sequence[str] = (),
        vector: Sequence[float] = (),
        candidates: Iterable[RetrievalCandidate] | None = None,
        limit: int = 5,
        at: datetime | None = None,
    ) -> list[RetrievalHit]:
        if purpose == "legal_tax":
            pack = self.registry.resolve(country_code, purpose="financial")
            if pack is None:
                raise MissingJurisdictionPackError(
                    f"Chưa có jurisdiction pack cho {country_code.upper()}; "
                    "chỉ được phân tích tài chính"
            )
            verified_at = self._runtime_verified_at.get(pack.country_code)
            check_at = at or datetime.now(timezone.utc)
            if check_at.tzinfo is None:
                check_at = check_at.replace(tzinfo=timezone.utc)
            runtime_fresh = bool(
                verified_at
                and verified_at <= check_at
                and check_at - verified_at <= timedelta(days=pack.freshness_days)
            )
            if not runtime_fresh:
                pack.assert_legal_ready(at)
        else:
            pack = self.registry.resolve(country_code, purpose=purpose, at=at)
        request = (
            query
            if isinstance(query, RetrievalQuery)
            else RetrievalQuery(str(query), tuple(exact_refs), tuple(vector))
        )
        retriever = self.retriever
        if retriever is None:
            if pack is None:
                return []
            key = (pack.id, pack.content_checksum)
            retriever = self._pack_retrievers.get(key)
            if retriever is None:
                retriever = HybridRetriever(_pack_records(pack))
                self._pack_retrievers[key] = retriever
        return retriever.search(request, candidates=candidates, limit=limit)

    def refresh_pack(
        self,
        country_code: str = "VN",
        *,
        refresher: Callable[[JurisdictionPack], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        pack = self.registry.resolve(country_code, purpose="financial")
        if pack is None:
            raise MissingJurisdictionPackError(
                f"Chưa có jurisdiction pack cho {country_code.upper()}"
            )
        callback = refresher or self.source_refresher
        if callback is None:
            if pack.country_code != "VN":
                raise JurisdictionPackError(
                    "Pack ngoài Việt Nam cần source_refresher riêng"
                )
            from .knowledge import KnowledgeBase

            status: Mapping[str, Any] = KnowledgeBase().refresh()
        else:
            status = callback(pack)
        if not isinstance(status, Mapping):
            raise JurisdictionPackError("Pack refresher phải trả về mapping status")
        verified_at = str(status.get("verified_at", ""))
        verified_sources = status.get("verified_sources", 0)
        total_sources = status.get("total_sources", 0)
        if (
            verified_at
            and status.get("stale") is False
            and isinstance(verified_sources, int)
            and isinstance(total_sources, int)
            and verified_sources == total_sources
            and total_sources >= len(pack.sources)
        ):
            self._runtime_verified_at[pack.country_code] = _utc(verified_at)
        else:
            self._runtime_verified_at.pop(pack.country_code, None)
        return {
            "pack_id": pack.id,
            "country_code": pack.country_code,
            **dict(status),
        }


def retrieval_context(
    hits: Iterable[RetrievalHit],
) -> tuple[str, list[dict[str, Any]], bool]:
    values = tuple(hits)
    context = "\n\n".join(
        f"### {hit.record.title}\n{hit.record.text}" for hit in values
    )
    sources = [
        {
            "id": hit.record.id,
            "kind": str(hit.record.metadata.get("kind") or "knowledge"),
            "title": hit.record.title,
            "locator": hit.record.locator,
            "fetched_at": "",
            "effective_from": "",
            "verified_current": True,
            "retrieval_modes": list(hit.modes),
            "retrieval_score": hit.score,
        }
        for hit in values
    ]
    semantic_downgrade = bool(values) and not any(
        "vector" in hit.modes for hit in values
    )
    return context, sources, semantic_downgrade


def _pack_records(pack: JurisdictionPack) -> tuple[RetrievalRecord, ...]:
    records: list[RetrievalRecord] = []
    for source in pack.sources:
        identifiers = re.findall(
            r"\d+/\d{4}/[A-ZĐ]+(?:-[A-ZĐ]+)*",
            source.title,
        )
        records.append(
            RetrievalRecord(
                f"{pack.id}:source:{source.id}",
                source.title,
                f"{source.issuer}; hiệu lực từ {source.effective_from}",
                source.url,
                tuple(dict.fromkeys((source.id, *identifiers))),
                metadata={
                    "country_code": pack.country_code,
                    "pack_id": pack.id,
                    "kind": "official_source",
                },
            )
        )
    try:
        markdown = pack.rules_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise JurisdictionPackError(f"Không đọc được pack rules: {exc}") from exc
    heading = pack.name
    lines: list[str] = []
    section = 0
    for line in markdown.splitlines():
        if line.startswith("#"):
            if lines:
                section += 1
                records.append(
                    _rule_record(pack, section, heading, "\n".join(lines))
                )
            heading = line.lstrip("# ").strip() or pack.name
            lines = []
        else:
            lines.append(line)
    if lines:
        section += 1
        records.append(_rule_record(pack, section, heading, "\n".join(lines)))
    return tuple(records)


def _rule_record(
    pack: JurisdictionPack,
    section: int,
    title: str,
    text: str,
) -> RetrievalRecord:
    return RetrievalRecord(
        f"{pack.id}:rules:{section}",
        title,
        text,
        f"pack:{pack.id}:rules:{section}",
        metadata={
            "country_code": pack.country_code,
            "pack_id": pack.id,
            "kind": "rules",
        },
    )


def guard_legal_report(
    report: dict[str, Any], capability: Mapping[str, Any]
) -> dict[str, Any]:
    """Remove unsupported legal conclusions while retaining financial analysis."""
    if capability.get("legal_tax_advice"):
        return report
    guarded = {**report, "tax_risks": []}
    missing = [dict(item) for item in report.get("missing_data", [])]
    if not any(item.get("field") == "missing_knowledge" for item in missing):
        missing.append(
            {
                "field": "missing_knowledge",
                "impact": (
                    "Chưa có jurisdiction pack đã xác minh; "
                    "báo cáo chỉ gồm phân tích tài chính."
                ),
                "material": True,
            }
        )
    guarded["missing_data"] = missing
    return guarded


def mark_retrieval_downgrade(
    report: dict[str, Any], downgraded: bool
) -> dict[str, Any]:
    if not downgraded:
        return report
    missing = [dict(item) for item in report.get("missing_data", [])]
    if not any(item.get("field") == "semantic_retrieval" for item in missing):
        missing.append(
            {
                "field": "semantic_retrieval",
                "impact": (
                    "Embedding provider unavailable; exact-reference and "
                    "full-text retrieval were used."
                ),
                "material": False,
            }
        )
    return {**report, "missing_data": missing}
