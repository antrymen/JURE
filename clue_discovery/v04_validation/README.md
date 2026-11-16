# Validation-family experiment for frozen v0.4

This separate module leaves the v0.4 searcher, numerical statistics, thresholds
and raw decisions unchanged. It freezes direction-specific families before
validation, then applies raw, BH and Holm gates to the same held-out p-values.
It does not enable real-data execution or Agent investigation.

```bash
python -m clue_discovery.v04_validation.benchmark \
  --output-dir outputs/clue_hunting_v04_validation_family_v1 --workers 2
```

The protocol, source hashes, all 232 new dataset specifications, and acceptance
criteria are saved before data generation. Every dataset is generated and hashed
before the first discovery/validation run. Old seeds 11/29/47 are not reused.
Existing output directories are rejected. Failed or negative results are kept.

Each direction's family is all unique locked triplet gene sets. Multiple states
share a p-value; unevaluable/missing members keep a denominator slot with p=1
for accounting and cannot reject. BH(0.05) is the requested comparator, BH(0.025)
splits the direction budget, and Holm(0.025 per direction) is the predeclared
conservative arm. BH dependence and post-filtering assumptions are not silently
treated as established. State-level FDR and biological/causal validity are not
claimed.

Benchmark storage keeps counts, all decision summaries and array hashes instead
of reproducible Monte Carlo arrays. Simulations themselves are unchanged. Large
CSV artifacts are losslessly compressed; consult compressed_csv_manifest.json.
Numerical equivalence to the original v0.4 pipeline is regression tested.

Full protocol: [design](../../docs/clue_hunting/v04_validation_family_protocol.md).
