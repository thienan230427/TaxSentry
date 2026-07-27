from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

import pytest

from taxsentry.jurisdictions import (
    PACKAGE_DIR,
    HybridRetriever,
    JurisdictionPack,
    JurisdictionPackError,
    JurisdictionRegistry,
    KnowledgeService,
    MissingJurisdictionPackError,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalRecord,
    UnverifiedJurisdictionPackError,
    _content_checksum,
)


def test_packaged_vietnam_pack_is_verified_and_uses_official_sources():
    registry = JurisdictionRegistry()
    pack = registry.resolve(
        "VN",
        purpose="legal_tax",
        at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )
    assert pack is not None
    assert pack.id == "vietnam-core"
    assert pack.currency == "VND"
    assert pack.minimum_taxsentry_version == "3.0.0"
    assert pack.citation_rules["legal_claims"] == "official_source_required"
    assert pack.refresh_policy["mode"] == "official_allowlist"
    assert pack.sources
    assert {source.url.split("/")[2] for source in pack.sources} == {
        "vanban.chinhphu.vn"
    }


def test_global_core_allows_financial_analysis_but_guards_missing_or_stale_legal_pack():
    registry = JurisdictionRegistry()
    assert registry.resolve("US", purpose="financial") is None
    assert registry.capability("US") == {
        "financial_analysis": True,
        "legal_tax_advice": False,
        "pack": "",
        "reason": "missing_knowledge",
    }
    with pytest.raises(MissingJurisdictionPackError):
        registry.resolve("US", purpose="legal_tax")
    with pytest.raises(UnverifiedJurisdictionPackError, match="freshness"):
        registry.resolve(
            "VN",
            purpose="legal_tax",
            at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        )


def test_jurisdiction_manifest_rejects_non_official_sources_and_tampered_content(tmp_path):
    source = PACKAGE_DIR / "jurisdictions" / "VN" / "vietnam-core"
    destination = tmp_path / "vietnam-core"
    shutil.copytree(source, destination)
    manifest_path = destination / "pack.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["official_domains"] = ["example.com"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(JurisdictionPackError, match="allowlist"):
        JurisdictionPack.load(
            manifest_path, verify_signature=lambda signature, payload: True
        )

    manifest["official_domains"] = ["vanban.chinhphu.vn"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rules = destination / "references" / "tax_rules_vietnam.md"
    rules.write_text(rules.read_text(encoding="utf-8") + "\ntampered", encoding="utf-8")
    with pytest.raises(JurisdictionPackError, match="checksum"):
        JurisdictionPack.load(
            manifest_path, verify_signature=lambda signature, payload: True
        )


def test_pack_checksum_is_stable_across_text_newlines(tmp_path):
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    lf_root.mkdir()
    crlf_root.mkdir()
    (lf_root / "rules.md").write_bytes(b"rule one\nrule two\n")
    (crlf_root / "rules.md").write_bytes(b"rule one\r\nrule two\r\n")
    assert _content_checksum(lf_root, ("rules.md",)) == _content_checksum(
        crlf_root, ("rules.md",)
    )


def test_hybrid_retrieval_prioritizes_exact_reference_and_falls_back_deterministically():
    records = [
        RetrievalRecord(
            "law",
            "Nghị định 320/2025/NĐ-CP",
            "Quy định thuế thu nhập doanh nghiệp",
            "official:law",
            ("320/2025/NĐ-CP",),
            (1.0, 0.0),
        ),
        RetrievalRecord(
            "guide",
            "Hướng dẫn doanh thu",
            "Doanh thu và lợi nhuận doanh nghiệp",
            "internal:guide",
            (),
            (0.9, 0.1),
        ),
    ]
    retriever = HybridRetriever(records)
    exact = retriever.search(
        RetrievalQuery("Áp dụng Nghị định 320/2025/NĐ-CP", vector=(0.0, 1.0))
    )
    assert exact[0].record.id == "law"
    assert "exact" in exact[0].modes

    fallback = retriever.search(RetrievalQuery("doanh thu lợi nhuận"))
    assert fallback[0].record.id == "guide"
    assert fallback[0].modes == ("full_text",)


def test_hybrid_retrieval_accepts_database_scores_without_postgres():
    record = RetrievalRecord("source", "Nguồn", "Nội dung", "db:1")
    hits = HybridRetriever().search(
        RetrievalQuery("không trùng local"),
        candidates=[
            RetrievalCandidate(
                record,
                exact_score=0,
                full_text_score=0.8,
                vector_score=0.7,
            )
        ],
    )
    assert hits[0].record.id == "source"
    assert hits[0].score == pytest.approx(8.7)
    assert hits[0].modes == ("full_text", "vector")


def test_knowledge_service_retrieves_verified_pack_and_guards_missing_pack():
    service = KnowledgeService()
    hits = service.retrieve(
        "Áp dụng Nghị định 320/2025/NĐ-CP",
        "VN",
        purpose="legal_tax",
        at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )
    assert hits[0].record.metadata["kind"] == "official_source"
    assert "exact" in hits[0].modes
    assert service.retrieve("financial ratios", "US", purpose="financial") == []
    with pytest.raises(MissingJurisdictionPackError):
        service.retrieve("tax law", "US", purpose="legal_tax")


def test_knowledge_service_refresh_pack_uses_injected_official_refresher():
    seen = []

    def refresh(pack):
        seen.append(pack.country_code)
        return {
            "stale": False,
            "verified_at": "2026-09-20T00:00:00Z",
            "verified_sources": len(pack.sources),
            "total_sources": len(pack.sources),
        }

    service = KnowledgeService(source_refresher=refresh)
    status = service.refresh_pack("VN")
    assert seen == ["VN"]
    assert status["pack_id"] == "vietnam-core"
    assert status["verified_sources"] == status["total_sources"]
    assert service.retrieve(
        "Nghị định 320/2025/NĐ-CP",
        "VN",
        purpose="legal_tax",
        at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
