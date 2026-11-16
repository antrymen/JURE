> **Public-export notice:** Selected records are filtered derivatives; see [transformation notes](PUBLIC_EXPORT_NOTES.md) and [hash mapping](PUBLIC_EXPORT_TRANSFORMS.json). **MED30 M04_03 has a documented historical source-description error**; do not treat it as verified glioma evidence.

# JURE paper evidence archive

This is a **candidate publication archive** of aggregate results and historical scientific role outputs. It contains no raw single-cell matrix, paper PDF, API credentials, or fabricated model calls.

- `discovery/`: frozen reference catalogue, configuration and Day6 candidate associations.
- `validation/`: association-level validation tables, locked internal candidates and frozen configuration records.
- `modules/`: aggregate effect/co-clustering matrices, module summaries and configuration.
- `cases/`: 18 case records, three batch protocol excerpts and an index. See [CASE_INDEX.md](CASE_INDEX.md).
- `source_manifest.json`: original research-relative path, original SHA256, archive path/SHA256 and transformation per copied artifact.
- `inventory.json`: all archived files' checksums (excluding itself).

Run from the repository root:

```bash
python scripts/verify_paper_results.py
```

This recomputes validation summaries/Holm from archived P values and reconstructs stable cores from archived co-clustering. It does not rerun raw-count statistical tests, 50 bootstrap iterations or historical LLM agents.

## Provenance and transformations

Where JSON values or keys contain the original local project root, it is replaced by `research://`. Numerical/scientific fields are unchanged. Original and exported file hashes are distinct when this transformation occurs; embedded historical hashes refer to the original sources, not automatically the sanitized export. Protocol JSON files are explicitly selected-field excerpts, with the original protocol hash; native session identifiers and user authorization prose are not included there. New3 inputs are extracted per-case from the original inputs list. No missing tool transcript is synthesized.

`research://` is a source identifier, not an executable path or URL. Resolve it through source_manifest.json where an artifact is bundled; unbundled sources still require the research archive. Targeted public-content filtering is documented in PUBLIC_EXPORT_NOTES.md. Rights-holder approval for the software release remains pending; third-party source terms are recorded separately.
