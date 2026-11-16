"""Blockwise binary phi graph for proposal only, not MFI or Markov blankets."""
from __future__ import annotations

from dataclasses import dataclass
import csv
import heapq
import json
import math
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
from scipy import sparse


EDGE_COLUMNS = ['gene_i', 'gene_j', 'dependency_statistic', 'dependency_strength',
                'dependency_method', 'selected_edge', 'selection_reason', 'fold',
                'edge_provenance']
_PAIR_DTYPE = np.dtype([('i', '<i4'), ('j', '<i4'), ('phi', '<f8')])


@dataclass
class DependencyGraph:
    nodes: tuple[str, ...]
    edges: pd.DataFrame
    neighborhoods: dict[str, tuple[str, ...]]
    summary: dict

    def neighbors(self, gene: str) -> tuple[str, ...]:
        """Outbound bounded neighbors only; incoming hub degree is not expanded."""
        return tuple(value for value in self.neighborhoods.get(gene, ()) if value != gene)


class DependencyGraphBuilder:
    def __init__(self, *, top_k=3, min_abs_phi=.08, block_size=128,
                 threshold_source='frozen_config', version='v03a',
                 calibration_method='prespecified_not_validation_tuned'):
        for value, name in ((top_k, 'top_k'), (block_size, 'block_size')):
            if isinstance(value, bool) or not isinstance(value, int) or value < (name == 'block_size'):
                raise ValueError(f'invalid {name}')
        if not 0 <= min_abs_phi <= 1:
            raise ValueError('min_abs_phi must be between 0 and 1')
        self.top_k, self.min_abs_phi, self.block_size = top_k, float(min_abs_phi), block_size
        self.threshold_source, self.version = str(threshold_source), str(version)
        self.calibration_method = str(calibration_method)

    def build(self, binary, genes, *, fold='A', audit_path=None) -> DependencyGraph:
        genes = tuple(map(str, genes))
        if len(set(genes)) != len(genes):
            raise ValueError('gene names must be unique')
        if len(binary.shape) != 2 or binary.shape[1] != len(genes) or binary.shape[0] < 2:
            raise ValueError('binary discovery matrix must match genes and contain >=2 cells')
        if sparse.issparse(binary):
            binary = binary.tocsr(copy=True)
            binary.sum_duplicates()
            data = binary.data
        else:
            binary = np.asarray(binary)
            data = binary
        if not np.isfinite(data).all() or ((data != 0) & (data != 1)).any():
            raise ValueError('dependency graph accepts binary detected/undetected states')
        permutation = np.argsort(np.asarray(genes), kind='stable')
        genes = tuple(genes[i] for i in permutation)
        binary = binary[:, permutation]
        n_cells, n_genes = binary.shape
        means = np.asarray(binary.mean(axis=0)).ravel()
        variance = means*(1-means)
        heaps = [[] for _ in genes]
        pair_spool = tempfile.TemporaryFile() if audit_path is not None else None
        pair_count = 0
        try:
            for begin_i in range(0, n_genes, self.block_size):
                end_i = min(begin_i+self.block_size, n_genes)
                left_raw = binary[:, begin_i:end_i]
                left = left_raw.toarray().astype(np.float64) if sparse.issparse(left_raw) else np.asarray(left_raw, dtype=np.float64)
                for begin_j in range(begin_i, n_genes, self.block_size):
                    end_j = min(begin_j+self.block_size, n_genes)
                    right_raw = binary[:, begin_j:end_j]
                    right = right_raw.toarray().astype(np.float64) if sparse.issparse(right_raw) else np.asarray(right_raw, dtype=np.float64)
                    joint = left.T @ right / n_cells
                    covariance = joint-means[begin_i:end_i, None]*means[None, begin_j:end_j]
                    denominator = np.sqrt(variance[begin_i:end_i, None]*variance[None, begin_j:end_j])
                    phi = np.divide(covariance, denominator, out=np.zeros_like(covariance), where=denominator > 0)
                    np.clip(phi, -1, 1, out=phi)
                    local_i, local_j = np.indices(phi.shape)
                    mask = local_i+begin_i < local_j+begin_j
                    all_i, all_j, all_phi = (local_i[mask]+begin_i, local_j[mask]+begin_j, phi[mask])
                    pair_count += len(all_phi)
                    if pair_spool is not None:
                        block = np.empty(len(all_phi), dtype=_PAIR_DTYPE)
                        block['i'], block['j'], block['phi'] = all_i, all_j, all_phi
                        pair_spool.write(block.tobytes())
                    if self.top_k:
                        eligible = (np.abs(all_phi) >= self.min_abs_phi) & (variance[all_i] > 0) & (variance[all_j] > 0)
                        for i, j, value in zip(all_i[eligible].tolist(), all_j[eligible].tolist(), all_phi[eligible].tolist()):
                            for owner, neighbor in ((i, j), (j, i)):
                                entry = (abs(value), -neighbor, value, neighbor)
                                if len(heaps[owner]) < self.top_k:
                                    heapq.heappush(heaps[owner], entry)
                                elif entry[:2] > heaps[owner][0][:2]:
                                    heapq.heapreplace(heaps[owner], entry)
            edge_values, selected_by = {}, {}
            neighborhoods = {}
            for owner, heap in enumerate(heaps):
                ranked = sorted(heap, key=lambda value: (-value[0], genes[value[3]]))
                neighborhoods[genes[owner]] = (genes[owner],) + tuple(genes[item[3]] for item in ranked)
                for _, _, value, neighbor in ranked:
                    key = (min(owner, neighbor), max(owner, neighbor))
                    edge_values[key] = value
                    selected_by.setdefault(key, []).append(genes[owner])
            provenance = {'threshold_source': self.threshold_source, 'version': self.version,
                          'calibration_method': self.calibration_method,
                          'top_k': self.top_k, 'min_abs_phi': self.min_abs_phi,
                          'fit_population': 'discovery_fold_only',
                          'edge_rule': 'union_of_endpoint_top_k_above_fixed_threshold'}
            def record(i, j, value):
                selected = (i, j) in edge_values
                if selected:
                    reason = 'top_k_endpoint_and_min_abs_phi'
                elif variance[i] == 0 or variance[j] == 0:
                    reason = 'constant_gene'
                elif abs(value) < self.min_abs_phi:
                    reason = 'below_min_abs_phi'
                else:
                    reason = 'not_in_endpoint_top_k'
                return {'gene_i': genes[i], 'gene_j': genes[j], 'dependency_statistic': float(value),
                        'dependency_strength': abs(float(value)), 'dependency_method': 'binary_phi',
                        'selected_edge': selected, 'selection_reason': reason, 'fold': str(fold),
                        'edge_provenance': json.dumps({**provenance, 'selected_by': selected_by.get((i, j), [])}, sort_keys=True)}
            edges = pd.DataFrame([record(i, j, value) for (i, j), value in sorted(edge_values.items())], columns=EDGE_COLUMNS)
            if pair_spool is not None:
                path = Path(audit_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                pair_spool.seek(0)
                with path.open('w', newline='') as handle:
                    writer = csv.DictWriter(handle, fieldnames=EDGE_COLUMNS)
                    writer.writeheader()
                    while payload := pair_spool.read(_PAIR_DTYPE.itemsize*8192):
                        for row in np.frombuffer(payload, dtype=_PAIR_DTYPE):
                            writer.writerow(record(int(row['i']), int(row['j']), float(row['phi'])))
        finally:
            if pair_spool is not None:
                pair_spool.close()
        adjacency = {gene: set() for gene in genes}
        for i, j in edge_values:
            adjacency[genes[i]].add(genes[j])
            adjacency[genes[j]].add(genes[i])
        components, remaining = [], set(genes)
        while remaining:
            pending, component = [min(remaining)], []
            remaining.remove(pending[0])
            while pending:
                gene = pending.pop()
                component.append(gene)
                new = adjacency[gene] & remaining
                remaining.difference_update(new)
                pending.extend(sorted(new, reverse=True))
            components.append(sorted(component))
        possible_edges = math.comb(n_genes, 2)
        summary = {'method': 'binary_phi', 'purpose': 'candidate_proposal_only', 'fold': str(fold),
                   'n_cells': n_cells, 'n_nodes': n_genes, 'n_edges': len(edges),
                   'n_pairs_examined': pair_count, 'graph_density': len(edges)/possible_edges if possible_edges else 0.,
                   'node_degree': {gene: len(adjacency[gene]) for gene in genes},
                   'degree_distribution': sorted(len(adjacency[gene]) for gene in genes),
                   'connected_components': components, 'n_connected_components': len(components),
                   'neighborhood_sizes': {gene: len(value) for gene, value in neighborhoods.items()},
                   'neighborhood_rule': 'center_plus_own_outbound_top_k_not_undirected_hub_neighbors',
                   'max_neighborhood_size': max(map(len, neighborhoods.values()), default=0),
                   'graph_audit_scope': 'all_pairs' if audit_path is not None else 'selected_edges_only',
                   'constant_genes': [genes[i] for i in np.flatnonzero(variance == 0)],
                   **provenance}
        return DependencyGraph(genes, edges, neighborhoods, summary)
