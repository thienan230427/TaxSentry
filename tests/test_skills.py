from __future__ import annotations

import json
from pathlib import Path

import pytest

from taxsentry.skills import (
    MarketplaceCatalog,
    PermissionManifest,
    SandboxExecutionPolicy,
    SkillRegistry,
    SkillSecurityError,
    SkillService,
    SkillSource,
    SkillValidationError,
    compute_skill_checksum,
    read_skill,
    validate_skill_directory,
)


def _skill(
    root: Path,
    version: str = "1.0.0",
    dependency: str = "",
    network_domain: str = "",
    source: SkillSource | None = None,
) -> Path:
    root.mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "run.sh").write_text("#!/bin/sh\nprintf ok\n", encoding="utf-8")
    dependencies = f"\n  - {dependency}" if dependency else " []"
    network_domains = f"\n    - {network_domain}" if network_domain else " []"
    source = source or SkillSource("local", ".")
    source_lines = [
        f"  kind: {source.kind}",
        f"  location: {source.location}",
    ]
    if source.commit:
        source_lines.append(f"  commit: {source.commit}")
    if source.catalog:
        source_lines.append(f"  catalog: {source.catalog}")
    if source.signature:
        source_lines.append(f"  signature: {source.signature}")
    source_block = "\n".join(source_lines)
    (root / "SKILL.md").write_text(
        f"""---
name: document-audit
version: {version}
description: Audit a document with cited findings
author: TaxSentry
platforms:
  - linux
  - windows
jurisdictions:
  - VN
capabilities:
  - document-audit
permissions:
  filesystem:
    read:
      - inputs
    write:
      - outputs
  network_domains:{network_domains}
  process: true
  external_send: false
dependencies:{dependencies}
source:
{source_block}
checksum: {"0" * 64}
signature: '{source.signature}'
minimum_taxsentry_version: 3.0.0
---
# Document audit

Load details only when this skill is selected.
""",
        encoding="utf-8",
    )
    checksum = compute_skill_checksum(root)
    skill_file = root / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("0" * 64, checksum, 1),
        encoding="utf-8",
    )
    return root


def test_skill_manifest_validates_checksum_permissions_and_progressive_view(tmp_path):
    source = _skill(tmp_path / "source")
    skill = validate_skill_directory(source)
    assert skill.manifest.permissions.filesystem_read == ("inputs",)
    assert skill.manifest.permissions.process

    registry = SkillRegistry(tmp_path / "registry")
    registry.stage(source)
    summary = registry.index()
    assert [(item.status, item.enabled) for item in summary] == [("draft", False)]
    assert registry.enabled_index() == []
    with pytest.raises(SkillValidationError):
        registry.view("document-audit", "1.0.0")
    assert registry.view(
        "document-audit", "1.0.0", include_drafts=True
    ).instructions.startswith("# Document audit")


def test_skill_rejects_a_newer_taxsentry_runtime_requirement(tmp_path):
    source = _skill(tmp_path / "future")
    skill_file = source / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            "minimum_taxsentry_version: 3.0.0",
            "minimum_taxsentry_version: 99.0.0",
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillValidationError, match="TaxSentry >="):
        validate_skill_directory(source)


def test_draft_needs_approval_and_registry_can_rollback(tmp_path):
    registry = SkillRegistry(tmp_path / "registry")
    registry.stage(_skill(tmp_path / "v1", "1.0.0"))
    registry.approve("document-audit", "1.0.0", approved_by="boss")
    registry.stage(_skill(tmp_path / "v2", "1.1.0"))
    assert [item.version for item in registry.enabled_index()] == ["1.0.0"]
    registry.approve("document-audit", "1.1.0", approved_by="boss")

    assert registry.view("document-audit").manifest.version == "1.1.0"
    assert registry.rollback("document-audit").version == "1.0.0"
    assert registry.view("document-audit").manifest.version == "1.0.0"


def test_skill_service_creates_draft_and_requires_explicit_approval(tmp_path):
    service = SkillService(tmp_path / "registry")
    manifest = {
        "name": "generated-audit",
        "version": "1.0.0",
        "description": "Generated audit procedure",
        "author": "TaxSentry",
        "platforms": ["linux"],
        "jurisdictions": ["VN"],
        "capabilities": ["document-audit"],
        "permissions": {
            "filesystem": {"read": ["inputs"], "write": ["outputs"]},
            "network_domains": [],
            "process": True,
            "external_send": False,
        },
        "dependencies": [],
        "source": {"kind": "local", "location": "."},
        "signature": "",
        "minimum_taxsentry_version": "3.0.0",
    }
    draft = service.create_draft(
        manifest,
        "# Generated audit\n\nRun only after approval.",
        files={"scripts/run.sh": "#!/bin/sh\nprintf ok\n"},
    )
    assert draft.status == "draft" and not draft.enabled
    assert service.registry.enabled_index() == []

    approved = service.approve("generated-audit", "1.0.0", approved_by="boss")
    assert approved.enabled
    assert service.registry.view("generated-audit").instructions.startswith(
        "# Generated audit"
    )

    with pytest.raises(SkillSecurityError, match="đường dẫn"):
        service.create_draft(
            {**manifest, "version": "1.1.0"},
            "# Unsafe",
            files={"../outside": "blocked"},
        )


def test_skill_service_installs_pinned_github_checkout_without_network(tmp_path):
    commit = "e" * 40
    metadata = SkillSource(
        "github",
        "https://github.com/taxsentry/document-audit",
        commit,
    )
    checkout = _skill(tmp_path / "checkout", source=metadata)
    checksum = read_skill(checkout).manifest.checksum
    service = SkillService(
        tmp_path / "registry",
        source_resolver=lambda source: checkout,
    )
    installed = service.install(metadata, expected_checksum=checksum)
    assert installed.status == "draft" and not installed.enabled
    assert service.registry.enabled_index() == []

    other = SkillService(
        tmp_path / "other-registry",
        source_resolver=lambda source: checkout,
    )
    with pytest.raises(SkillSecurityError, match="checksum"):
        other.install(metadata, expected_checksum="f" * 64)


def test_skill_rejects_traversal_unpinned_dependency_and_checksum_tampering(tmp_path):
    source = _skill(tmp_path / "source")
    skill_file = source / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8").replace("      - inputs", "      - ../secret")
    skill_file.write_text(text, encoding="utf-8")
    with pytest.raises(SkillSecurityError):
        read_skill(source)

    dependency_source = _skill(tmp_path / "dependency", dependency="unsafe>=1.0")
    with pytest.raises(SkillSecurityError):
        read_skill(dependency_source)

    clean = _skill(tmp_path / "clean")
    (clean / "scripts" / "run.sh").write_text("tampered", encoding="utf-8")
    with pytest.raises(SkillSecurityError, match="checksum"):
        validate_skill_directory(clean)
    with pytest.raises(SkillSecurityError, match="version"):
        SkillRegistry(tmp_path / "registry").approve(
            "document-audit", "../outside", approved_by="boss"
        )


def test_marketplace_catalog_requires_signature_and_pinned_git_commits(tmp_path):
    commit = "a" * 40
    catalog_path = tmp_path / "catalog.json"
    catalog = {
        "schema_version": 1,
        "catalog_id": "taxsentry-official",
        "repository": "https://github.com/taxsentry/skills",
        "commit": commit,
        "generated_at": "2026-07-26T00:00:00Z",
        "public_key_id": "taxsentry-2026",
        "signature": "c2ln",
        "skills": [
            {
                "name": "document-audit",
                "version": "1.0.0",
                "repository": "https://github.com/taxsentry/skills",
                "commit": commit,
                "path": "skills/document-audit",
                "checksum": "b" * 64,
            }
        ],
    }
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(SkillSecurityError, match="verifier"):
        MarketplaceCatalog.load(catalog_path, verify_signature=None)
    loaded = MarketplaceCatalog.load(
        catalog_path,
        verify_signature=lambda key_id, payload, signature: (
            key_id == "taxsentry-2026"
            and b'"catalog_id":"taxsentry-official"' in payload
            and signature == "c2ln"
        ),
    )
    assert loaded.skills[0].commit == commit

    catalog["skills"][0]["commit"] = "main"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(SkillSecurityError, match="pin commit"):
        MarketplaceCatalog.load(catalog_path, verify_signature=lambda *_: True)


def test_skill_service_installs_only_from_verified_marketplace_catalog(tmp_path):
    commit = "a" * 40
    repository = "https://github.com/taxsentry/skills"
    source = SkillSource(
        "marketplace",
        repository,
        commit,
        "taxsentry-official",
        "c2ln",
    )
    checkout = tmp_path / "checkout"
    skill_root = _skill(checkout / "skills" / "document-audit", source=source)
    checksum = read_skill(skill_root).manifest.checksum
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalog_id": "taxsentry-official",
                "repository": repository,
                "commit": commit,
                "generated_at": "2026-07-26T00:00:00Z",
                "public_key_id": "taxsentry-2026",
                "signature": "c2ln",
                "skills": [
                    {
                        "name": "document-audit",
                        "version": "1.0.0",
                        "repository": repository,
                        "commit": commit,
                        "path": "skills/document-audit",
                        "checksum": checksum,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog = MarketplaceCatalog.load(
        catalog_file,
        verify_signature=lambda *_: True,
    )
    service = SkillService(
        tmp_path / "registry",
        source_resolver=lambda metadata: checkout,
    )
    draft = service.install(catalog.skills[0], catalog=catalog)
    assert draft.status == "draft" and not draft.enabled

    unverified = MarketplaceCatalog(
        catalog.catalog_id,
        catalog.repository,
        catalog.commit,
        catalog.generated_at,
        catalog.public_key_id,
        catalog.signature,
        catalog.skills,
    )
    with pytest.raises(SkillSecurityError, match="catalog đã xác minh"):
        SkillService(
            tmp_path / "unverified-registry",
            source_resolver=lambda metadata: checkout,
        ).install(unverified.skills[0], catalog=unverified)


def test_remote_skill_source_metadata_requires_pin_and_marketplace_signature():
    commit = "d" * 40
    github = SkillSource.from_mapping(
        {
            "kind": "github",
            "location": "https://github.com/taxsentry/skills",
            "commit": commit,
        }
    )
    assert github.commit == commit
    with pytest.raises(SkillSecurityError, match="pin Git commit"):
        SkillSource.from_mapping(
            {
                "kind": "github",
                "location": "https://github.com/taxsentry/skills",
                "commit": "main",
            }
        )
    with pytest.raises(SkillSecurityError, match="chữ ký"):
        SkillSource.from_mapping(
            {
                "kind": "marketplace",
                "location": "https://github.com/taxsentry/skills",
                "commit": commit,
                "catalog": "official",
            }
        )
    with pytest.raises(SkillSecurityError, match="local source"):
        SkillSource.from_mapping(
            {"kind": "local", "location": "../../outside"}
        )


def test_sandbox_policy_builds_hardened_external_command(tmp_path):
    source = _skill(tmp_path / "source")
    permissions = validate_skill_directory(source).manifest.permissions
    policy = SandboxExecutionPolicy("taxsentry/skill-runner@sha256:" + "c" * 64)
    input_path = tmp_path / "input.xlsx"
    input_path.write_bytes(b"xlsx")
    command = policy.command(
        source,
        "scripts/run.sh",
        permissions,
        ("--check",),
        {"inputs": input_path},
    )
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert any("dst=/workspace/inputs,readonly" in item for item in command)
    assert command[-1] == "--check"

    with pytest.raises(SkillSecurityError, match="filesystem"):
        policy.command(
            source,
            "scripts/run.sh",
            permissions,
            mounts={"secrets": input_path},
        )
    forged = PermissionManifest(process=True)
    with pytest.raises(SkillSecurityError, match="Permission manifest"):
        policy.command(source, "scripts/run.sh", forged)

    network_source = _skill(
        tmp_path / "network-source",
        network_domain="api.example.com",
    )
    network_permissions = validate_skill_directory(network_source).manifest.permissions
    with pytest.raises(SkillSecurityError, match="egress runner"):
        policy.command(
            network_source,
            "scripts/run.sh",
            network_permissions,
        )
