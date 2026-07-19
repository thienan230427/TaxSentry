from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import APP_HOME

PACKAGE_DIR = Path(__file__).with_name("knowledge_base")
REGISTRY_FILE = PACKAGE_DIR / "knowledge_sources.json"
BENCHMARK_REGISTRY_FILE = PACKAGE_DIR / "benchmark_sources.json"
LOCAL_KNOWLEDGE = PACKAGE_DIR / "tax_rules_vietnam.md"
TRUSTED_DOMAIN = "vanban.chinhphu.vn"


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored and (text := " ".join(data.split())):
            self.parts.append(text)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"\w+", text.casefold(), re.UNICODE) if len(token) > 2}


class KnowledgeBase:
    """Small, local-first legal knowledge registry with freshness evidence."""

    def __init__(self, settings: dict | None = None, root: Path | None = None):
        self.settings = settings or {}
        self.root = root or APP_HOME / "knowledge"
        self.cache_dir = self.root / "cache"
        self.status_file = self.root / "status.json"

    def _registry(self) -> list[dict]:
        try:
            values = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            values = []
        legal = [
            {**value, "kind": "knowledge"}
            for value in values
            if isinstance(value, dict)
            and urlparse(str(value.get("url", ""))).hostname == TRUSTED_DOMAIN
        ]
        try:
            benchmarks = json.loads(
                BENCHMARK_REGISTRY_FILE.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            benchmarks = []
        return [
            *legal,
            *[
                {**value, "kind": "benchmark"}
                for value in benchmarks
                if isinstance(value, dict)
                and value.get("accepted") is True
                and all(
                    str(value.get(field, "")).strip()
                    for field in (
                        "id",
                        "title",
                        "issuer",
                        "industry",
                        "scope",
                        "data_period_end",
                    )
                )
                and _safe_https_url(str(value.get("url", "")))
            ],
        ]

    def _status_data(self) -> dict:
        try:
            value = json.loads(self.status_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def status(self) -> dict:
        data = self._status_data()
        verified_at = _parse_time(str(data.get("verified_at", "")))
        stale_days = int(
            self.settings.get("advisor", {}).get("knowledge", {}).get("legal_stale_days", 30)
        )
        stale = not verified_at or _utcnow() - verified_at > timedelta(days=stale_days)
        sources = data.get("sources", {})
        return {
            "verified_at": data.get("verified_at", ""),
            "stale": stale,
            "verified_sources": sum(
                1 for item in sources.values() if item.get("verified_current")
            ),
            "total_sources": len(self._registry()),
            "errors": [
                item.get("error", "")
                for item in sources.values()
                if item.get("error")
            ],
        }

    def refresh_if_due(self) -> dict:
        refresh_days = int(
            self.settings.get("advisor", {}).get("knowledge", {}).get("refresh_days", 7)
        )
        verified_at = _parse_time(str(self._status_data().get("verified_at", "")))
        if verified_at and _utcnow() - verified_at <= timedelta(days=refresh_days):
            return self.status()
        return self.refresh()

    def refresh(self) -> dict:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        registry = self._registry()
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(registry)))) as pool:
            results = list(pool.map(self._fetch, registry))
        now = _utcnow().isoformat()
        payload = {
            "verified_at": now if results and all(item["verified_current"] for item in results) else "",
            "checked_at": now,
            "sources": {item["id"]: item for item in results},
        }
        self.status_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.status()

    def _fetch(self, source: dict) -> dict:
        result = {
            **source,
            "fetched_at": _utcnow().isoformat(),
            "verified_current": False,
            "checksum": "",
            "error": "",
        }
        try:
            request = Request(
                source["url"],
                headers={"User-Agent": "TaxSentry/2 knowledge freshness check"},
            )
            with urlopen(request, timeout=15) as response:  # noqa: S310 - allowlisted HTTPS host
                final_host = urlparse(response.geturl()).hostname
                expected_host = urlparse(source["url"]).hostname
                if final_host != expected_host:
                    raise ValueError("Nguồn chuyển hướng ra ngoài domain chính thức")
                raw = response.read(2_000_000).decode(
                    response.headers.get_content_charset() or "utf-8", errors="replace"
                )
            parser = _TextParser()
            parser.feed(raw)
            text = "\n".join(parser.parts)
            if (
                source.get("kind") == "knowledge"
                and source["id"].split("-", 1)[-1].replace("-", "/") not in text
                and source["title"].split()[0] not in text
            ):
                raise ValueError("Trang nguồn không chứa định danh văn bản")
            if len(text) < 200:
                raise ValueError("Nguồn không có đủ nội dung để xác minh")
            cache = self.cache_dir / f"{source['id']}.txt"
            cache.write_text(text[:500_000], encoding="utf-8")
            result["checksum"] = hashlib.sha256(text.encode()).hexdigest()
            result["verified_current"] = True
        except Exception as exc:
            result["error"] = str(exc) or type(exc).__name__
        return result

    def search(self, query: str, limit: int = 4) -> tuple[str, list[dict]]:
        status = self.status()
        sections = self._sections()
        wanted = _tokens(query)
        ranked = sorted(
            sections,
            key=lambda item: len(wanted & _tokens(item["title"] + " " + item["text"])),
            reverse=True,
        )
        selected = [
            item
            for item in ranked[:limit]
            if not wanted or wanted & _tokens(item["title"] + " " + item["text"])
        ]
        source_wanted = {
            token
            for token in wanted
            if not token.isdigit()
        } - {
            "báo",
            "cáo",
            "cfo",
            "chỉnh",
            "doanh",
            "nghiệp",
            "được",
            "dữ",
            "đổi",
            "kiểm",
            "liệu",
            "lập",
            "nội",
            "quản",
            "sửa",
            "tháng",
            "thể",
            "tra",
            "trị",
            "thu",
        }
        registry = self._registry()
        source_status = self._status_data().get("sources", {})
        sources = []
        ranked_sources = []
        for item in registry:
            searchable = " ".join(
                str(item.get(field, ""))
                for field in ("title", "industry", "scope")
            )
            score = len(source_wanted & _tokens(searchable))
            if score:
                ranked_sources.append((score, item))
        for _, item in sorted(ranked_sources, key=lambda value: value[0], reverse=True)[
            :limit
        ]:
            checked = source_status.get(item["id"], {})
            sources.append(
                {
                    "id": f"{item.get('kind', 'knowledge')}:{item['id']}",
                    "kind": item.get("kind", "knowledge"),
                    "title": item["title"],
                    "locator": item["url"],
                    "fetched_at": checked.get("fetched_at", ""),
                    "effective_from": item.get("effective_from", ""),
                    "verified_current": bool(
                        checked.get("verified_current") and not status["stale"]
                    ),
                    **(
                        {
                            "industry": item["industry"],
                            "scope": item["scope"],
                            "data_period_end": item["data_period_end"],
                        }
                        if item.get("kind") == "benchmark"
                        else {}
                    ),
                }
            )
        context = "\n\n".join(
            f"### {item['title']}\n{item['text'][:3500]}" for item in selected
        )
        return context, sources

    def _sections(self) -> list[dict[str, str]]:
        texts: list[tuple[str, str]] = []
        try:
            texts.append(("Kho tri thức nội bộ", LOCAL_KNOWLEDGE.read_text(encoding="utf-8")))
        except OSError:
            pass
        for source in self._registry():
            cache = self.cache_dir / f"{source['id']}.txt"
            if cache.is_file():
                texts.append((source["title"], cache.read_text(encoding="utf-8")))
        sections: list[dict[str, str]] = []
        for fallback, content in texts:
            heading, lines = fallback, []
            for line in content.splitlines():
                if line.startswith("#"):
                    if lines:
                        sections.append({"title": heading, "text": "\n".join(lines)})
                    heading, lines = line.lstrip("# ").strip() or fallback, []
                else:
                    lines.append(line)
            if lines:
                sections.append({"title": heading, "text": "\n".join(lines)})
        return sections


def _safe_https_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return parsed.hostname.casefold() != "localhost"
    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_reserved,
        )
    )
