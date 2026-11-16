"""Small artifact helpers for the integration layer."""
from pathlib import Path
import hashlib
import json
import math
from enum import Enum
import numpy as np
from pydantic import BaseModel

def clean(value):
    if isinstance(value, BaseModel): return clean(value.model_dump(mode='json'))
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple,np.ndarray)): return [clean(v) for v in value]
    if isinstance(value, np.generic): return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, Path): return str(value.resolve())
    if isinstance(value, Enum): return value.value
    return value

def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def write_jsonl(path, values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w') as out:
        for v in values: out.write(json.dumps(clean(v),ensure_ascii=False,allow_nan=False)+'\n')

def read_jsonl(path):
    with Path(path).open() as src: return [json.loads(s) for s in src if s.strip()]

def sha256(path):
    with Path(path).open('rb') as src: return hashlib.file_digest(src,'sha256').hexdigest()

def identity(value):
    return hashlib.sha256(json.dumps(clean(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

def artifact(path):
    return {'path':str(Path(path).resolve()),'sha256':sha256(path)}
