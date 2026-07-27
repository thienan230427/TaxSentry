# Large-document acceptance run — 2026-07-27

This result was produced by the synthetic `acceptance` profile in
`scripts/benchmark_documents.py` inside the TaxSentry development Docker
environment. The recorded result timestamp is
`2026-07-26T17:14:58.813945+00:00` (00:14:58 on 2026-07-27 in
Asia/Bangkok).

## Result

| Fixture | Structural size | File size | Ingest time | Coverage |
| --- | ---: | ---: | ---: | ---: |
| XLSX | 100 sheets, 1,000,000 data rows | 521,141,936 bytes | 25.879382 s | 4,101 / 4,101 |
| PDF | 1,000 pages, including 100 simulated scan pages | 611,505 bytes | 57.259799 s | 1,000 / 1,000 |
| PPTX | 500 slides | 433,948 bytes | 1.922927 s | 502 / 502 |
| DOCX | 2,001 paragraphs, 201 table rows, header, footer, comment | 46,343 bytes | 0.029241 s | 2,006 / 2,006 |
| Case | Four documents | 522,233,732 bytes (about 498 MiB) | 69.480318 s | 7,609 / 7,609 |

The run passed with zero failed units, zero skipped units, complete case
coverage, and no detected silent unit loss. The workbook correctly emitted a
warning for formulas without cached values.

Recorded result SHA-256:

```text
F2F2D90799EDE0C564252C6872F53839BC3D840120E8159DAC4A412153855BD5
```

## Reproduction

Run the same profile from an environment containing the locked development
dependencies:

```powershell
.venv\Scripts\python.exe scripts\benchmark_documents.py `
  --profile acceptance `
  --output acceptance.json
Get-FileHash -Algorithm SHA256 acceptance.json
```

The acceptance XLSX contains the stated worksheets and rows. A stored,
unreferenced OOXML payload pads the case close to 500 MB so the run also
exercises large-file hashing, ZIP inventory, and transport without pretending
that padding is additional worksheet data.

## Scope

This run validates local structural inventory, extraction, case reduction,
coverage accounting, and the under-two-hour performance target for this
fixture. It does not certify three-host throughput, cloud-model throttling,
production TLS, encrypted volumes/backups, restore, external delivery, or the
2.0.13-versus-3.0 shadow-report comparison; those remain separate release
gates.
