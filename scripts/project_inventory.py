"""Build a static source inventory without importing or executing project code."""
import ast
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (
    'clue_discovery', 'jure', 'triage', 'broad_screening', 'broad_annotation',
    'landscape_analysis', 'perturbation_scan', 'real_nt_v04_holm',
    'nt_reference_experiment', 'stage2_validation', 'dataset_audit',
    'real_data_test', 'real_data_v02', 'scripts', 'tests',
)

def main():
    rows = []
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            source = path.read_text(encoding='utf-8')
            try:
                tree = ast.parse(source)
                symbols = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                imports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(n.name for n in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imports.add('.' * node.level + (node.module or ''))
                status = 'parsed'
            except SyntaxError as error:
                symbols, imports, status = [], set(), f'syntax_error:{error.lineno}'
            rows.append([str(path.relative_to(ROOT)), len(source.splitlines()), status,
                         '__main__' in source, '; '.join(symbols), '; '.join(sorted(imports))])
    target = ROOT / 'docs/architecture/source_inventory.csv'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['path', 'lines', 'parse_status', 'contains_main_marker', 'top_level_symbols', 'static_imports'])
        writer.writerows(rows)
    experiment_paths = sorted(str(p.relative_to(ROOT)) for directory in ('output', 'outputs')
                              for p in (ROOT / directory).rglob('*.py') if '__pycache__' not in p.parts)
    (target.parent / 'experiment_scripts.txt').write_text('\n'.join(experiment_paths) + '\n', encoding='utf-8')
    print(f'{len(rows)} source files; {len(experiment_paths)} experiment scripts; '
          f'{sum(row[2] != "parsed" for row in rows)} parse errors')

if __name__ == '__main__':
    main()
