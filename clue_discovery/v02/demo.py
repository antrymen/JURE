"""CPU-only synthetic reference/validation/test demonstration; no real data read."""
import argparse
from itertools import product
import json
from pathlib import Path
import numpy as np
from . import Population, ReferenceConfig, reference_guided


def make_population(prefix, per_state_counts):
    states = np.array(list(product((0, 1), repeat=3)), dtype=np.uint8)
    values = np.repeat(states, per_state_counts, axis=0)
    return Population(values, ('A', 'B', 'C'), tuple(f'{prefix}:{i}' for i in range(len(values))))


def main(output):
    # All one- and two-gene marginals are identical; the reference has pure parity dependence.
    nt = make_population('NT', [1600, 400, 400, 1600, 400, 1600, 1600, 400])
    perturbations = {'uniform_shift': make_population('P', [250]*8),
                     'same_reference': make_population('Q', [400, 100, 100, 400, 100, 400, 400, 100])}
    result = reference_guided(nt, perturbations, candidate_genes=['A', 'B', 'C'], config=ReferenceConfig())
    result.write(output)
    summary = dict(nt_total=len(nt.cell_ids), nt_discovery=result.reference.metadata['n_discovery'],
                   nt_validation=result.reference.metadata['n_validation'],
                   nt_test=result.reference.metadata['n_reference_test'],
                   catalogue_patterns=len(result.reference.catalogue.patterns),
                   highest_evaluated_order=result.reference.metadata['highest_evaluated_order'],
                   stop_reason=result.reference.metadata['stop_reason'],
                   shifts_by_perturbation=result.testing.shifts.query("status == 'candidate_shift'").groupby('perturbation').size().to_dict(),
                   validation_scope='random NT cell holdout; not biological replication')
    Path(output, 'demo_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/clue_discovery_v02_demo')
    main(parser.parse_args().output)
