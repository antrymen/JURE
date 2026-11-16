"""Small auditable artifacts; distributions are written immediately, not retained."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys

import numpy as np
import pandas as pd
import yaml


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def canonical(value):
    return json.dumps(clean(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def enforce_memory_budget(config):
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    mib = value/(1024**2 if sys.platform == 'darwin' else 1024)
    if mib > config.max_process_rss_mib:
        raise MemoryError(f'process RSS high-water mark {mib:.1f} MiB exceeds frozen {config.max_process_rss_mib} MiB budget')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value) + '\n')


def write_csv(path, records, columns=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    if columns is not None:
        for c in columns:
            if c not in frame:
                frame[c] = pd.Series(dtype=object)
        frame = frame[list(columns) + [c for c in frame if c not in columns]]
    for c in frame:
        if frame[c].map(lambda x: isinstance(x, (tuple, list, dict, np.ndarray))).any():
            frame[c] = frame[c].map(lambda x: canonical(x) if isinstance(x, (tuple, list, dict, np.ndarray)) else x)
    frame.to_csv(path, index=False)


def software_versions():
    result = {'python': platform.python_version()}
    for name in ('numpy', 'scipy', 'pandas', 'anndata', 'h5py', 'PyYAML'):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def code_hashes():
    root = Path(__file__).resolve().parents[2]
    result = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('clue_discovery', 'nt_reference_experiment')
            for p in sorted((root/folder).rglob('*')) if p.is_file() and p.suffix in ('.py', '.sh', '.md')}
    if (root/'pyproject.toml').exists():
        result['pyproject.toml'] = hashlib.sha256((root/'pyproject.toml').read_bytes()).hexdigest()
    return result


class ArtifactStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ('state_tables', 'bootstrap', 'gain', 'search_logs'):
            (self.root/name).mkdir(exist_ok=True)

    def save_counts(self, role, candidate_id, counts, assessment):
        relative = f'state_tables/{role}/{candidate_id}.json'
        write_json(self.root/relative, {'counts': counts, **assessment})
        return relative

    def counts(self, path):
        return np.asarray(json.loads((self.root/path).read_text())['counts'], dtype=np.int64)

    def save_arrays(self, category, role, candidate_id, arrays):
        relative = f'{category}/{role}/{candidate_id}.npz'
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **{k: v for k, v in arrays.items() if isinstance(v, np.ndarray)})
        return relative

    def freeze_config(self, config):
        path = self.root/'config_frozen.yaml'
        if path.exists():
            raise FileExistsError('frozen run exists; choose a new run directory/version')
        path.write_text(yaml.safe_dump(config.to_dict(), sort_keys=True, allow_unicode=True))
        return config.sha256
