from __future__ import annotations

from taxsentry.knowledge import KnowledgeBase, _safe_https_url


class Response:
    headers = type("Headers", (), {"get_content_charset": lambda self: "utf-8"})()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def geturl(self):
        return "https://vanban.chinhphu.vn/?docid=1"

    def read(self, limit):
        body = "Quy định thuế TNDN và hồ sơ chứng minh. " * 10
        return (
            f"<html><body><h1>Nghị định 320/2025/NĐ-CP</h1><p>{body}</p>"
            "<script>ignore me</script></body></html>"
        ).encode()


def test_knowledge_refresh_records_freshness_and_cache(monkeypatch, tmp_path):
    service = KnowledgeBase(
        {"advisor": {"knowledge": {"refresh_days": 7, "legal_stale_days": 30}}},
        root=tmp_path,
    )
    monkeypatch.setattr(
        service,
        "_registry",
        lambda: [
            {
                "id": "nd-320-2025",
                "title": "Nghị định 320/2025/NĐ-CP",
                "issuer": "Chính phủ",
                "effective_from": "2025-12-15",
                "url": "https://vanban.chinhphu.vn/?docid=1",
                "kind": "knowledge",
            }
        ],
    )
    monkeypatch.setattr("taxsentry.knowledge.urlopen", lambda request, timeout: Response())
    status = service.refresh()
    assert not status["stale"] and status["verified_sources"] == 1
    assert "ignore me" not in (tmp_path / "cache" / "nd-320-2025.txt").read_text(encoding="utf-8")


def test_knowledge_is_stale_until_official_sources_are_verified(tmp_path):
    status = KnowledgeBase(root=tmp_path).status()
    assert status["stale"] and not status["verified_at"]


def test_benchmark_registry_rejects_local_or_insecure_urls():
    assert _safe_https_url("https://benchmark.example/data")
    assert not _safe_https_url("http://benchmark.example/data")
    assert not _safe_https_url("https://localhost/data")
    assert not _safe_https_url("https://127.0.0.1/data")


def test_knowledge_search_returns_only_relevant_sources(monkeypatch, tmp_path):
    service = KnowledgeBase(root=tmp_path)
    monkeypatch.setattr(
        service,
        "_registry",
        lambda: [
            {
                "id": "tax",
                "title": "Nghị định thuế thu nhập doanh nghiệp",
                "url": "https://vanban.chinhphu.vn/tax",
                "kind": "knowledge",
            },
            {
                "id": "invoice",
                "title": "Nghị định xử phạt hóa đơn",
                "url": "https://vanban.chinhphu.vn/invoice",
                "kind": "knowledge",
            },
        ],
    )
    assert service.search("báo cáo CFO doanh thu 2026 có thể chỉnh sửa")[1] == []
    assert [item["id"] for item in service.search("thuế thu nhập doanh nghiệp")[1]] == [
        "knowledge:tax"
    ]
