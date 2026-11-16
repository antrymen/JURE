# Configuration boundaries

These files are retained historical configurations, not universally portable defaults. Resolve dataset, output, model and tool paths before use. Never silently change scientific thresholds to make a run succeed.

For an offline generated dataset, use `python -m examples.run_synthetic`; its fixture supplies its own configuration. For real discovery, inspect `python -m clue_discovery.run --help` and the adapter contract. For agent runs, read `AGENT_PROTOCOL_AUDIT.md`: GLM configurations do not reproduce Codex/Luna case batches. Existing model names and scientific parameters remain unchanged.

Local paths and internal infrastructure references are inventoried in the local publication audit; sanitizing a public example must be a separate reviewed change, not an overwrite of archived configurations.
