"""Run a reviewed v0.4 configuration against a hash-verified prepared dataset."""
import argparse
import json
from pathlib import Path

import yaml

from ..v03.data import load_prepared
from .config import ScalableConfig
from .pipeline import fit_twofold


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('choose a new output directory; never overwrite an existing run')
    config = ScalableConfig(**yaml.safe_load(Path(args.config).read_text()))
    folds, selections, metadata = load_prepared(args.prepared, config)
    result = fit_twofold(folds['A'], folds['B'], config, output,
        dataset_manifest=metadata, selections=selections, dry_run=args.dry_run)
    print(json.dumps(dict(status=result.manifest['status'], output_dir=str(output.resolve()),
                         runtime_seconds=result.manifest['runtime_seconds']), ensure_ascii=False))


if __name__ == '__main__':
    main()
