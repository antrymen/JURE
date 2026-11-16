# Clue Hunting v0.4

This version adds a discovery-only binary parity fingerprint channel and
evidence-based allocation of calibration/bootstrap budgets. v0.3 and all of its
frozen outputs remain unchanged. Statistical kernels and locked validation are
imported from v0.3; orchestration and catalogue policy are versioned here.

Run the predeclared synthetic regression suite into a new directory:

```bash
python -m clue_discovery.v04.benchmark --output-dir outputs/clue_hunting_v04_benchmark
```

The suite includes 100/500/1000-gene candidate coverage at two signal strengths
and three seeds, the original 100-gene dataset through the full search pipeline,
one full 1000-gene synthetic case, and nine full negative-control runs. It does
not read real NT or require GPU/SSH. Read the resulting report, including misses.
Do not change seeds or thresholds until recovery looks positive.

For a reviewed configuration and an existing hash-verified prepared dataset:

```bash
python -m clue_discovery.v04.run --prepared /absolute/path/to/prepared \
  --config /absolute/path/to/v04_config.yaml \
  --output-dir /absolute/path/to/new_run
```

Add `--dry-run` for proposal-only accounting. The prepared-data path is the same
format as v0.3. The CLI does not download data, connect to AutoDL, or launch a GPU.
Do not describe repeatedly inspected NT as an untouched validation benchmark.

Scientific design, budget accounting and limitations:
[v0.4 design](../../docs/clue_hunting/clue_hunting_v0.4.md).
