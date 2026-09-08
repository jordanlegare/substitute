"""Exhaustive, offline combinations of catalog-established ALD simulation motifs.

The compressed index stores one canonical order per distinct component set.
Every permutation can be exported explicitly; none implies stack evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ald_core as core
from tools.build_compound_catalog import build_compound_catalog, canonical_catalog_bytes

DEFAULT_OUTPUT = ROOT / 'recipes' / 'combinations'
NOTICE = (
    'Components inherit catalog-established chemistry recognition only; references '
    'have not been independently audited for every precursor route. The combined '
    'sequence and interfaces are not established by those references. One exposure '
    'motif per component is concatenated; source repeat counts are not transferred. '
    'All executable parameters are synthetic simulator inputs, not fabrication instructions.'
)


def canonical(value):
    return canonical_catalog_bytes(value)


def identity(precursor):
    # Roles may differ (e.g. source versus dopant) without changing identity.
    return (' '.join(precursor['name'].casefold().split()), precursor['formula'].strip())


@dataclass(frozen=True)
class Seed:
    recipe_id: str
    path: str
    sha256: str
    raw: dict

    @property
    def exposures(self):
        return next(i['arguments']['exposures'] for i in self.raw['instructions']
                    if i['opcode'] == 'DEPOSITION_CYCLE')

    @property
    def identities(self):
        return frozenset(identity(p) for p in self.raw['precursors'].values())


def load_seeds():
    seeds = []
    # Rebuild from actual recipes so stale index metadata cannot promote a seed.
    for entry in build_compound_catalog()['entries']:
        if entry['chemistry_status'] != 'established':
            continue
        path = ROOT / entry['path']
        payload = path.read_bytes()
        raw = json.loads(payload)
        cycles = [i for i in raw['instructions'] if i['opcode'] == 'DEPOSITION_CYCLE']
        if len(cycles) != 1:
            raise ValueError(f'{path}: expected a single component exposure motif')
        seeds.append(Seed(entry['recipe_id'], entry['path'], hashlib.sha256(payload).hexdigest(), raw))
    return sorted(seeds, key=lambda s: s.recipe_id)


def iter_combinations(seeds, max_components=6):
    """Enumerate every eligible subset, pruning only monotone schema limits."""
    if not 2 <= max_components <= 6:
        raise ValueError('max_components must be between 2 and 6')
    keys = sorted({key for seed in seeds for key in seed.identities})
    bit = {key: 1 << i for i, key in enumerate(keys)}
    masks = [sum(bit[key] for key in seed.identities) for seed in seeds]
    lengths = [len(seed.exposures) for seed in seeds]

    def walk(start, chosen, mask, steps):
        for index in range(start, len(seeds)):
            next_mask = mask | masks[index]
            next_steps = steps + lengths[index]
            if next_mask.bit_count() > 6 or next_steps > 12:
                continue
            selected = chosen + (index,)
            if len(selected) >= 2:
                yield selected
            if len(selected) < max_components:
                yield from walk(index + 1, selected, next_mask, next_steps)

    yield from walk(0, (), 0, 0)


def compose_recipe(seeds):
    """Export an explicitly ordered set as one synthetic sequential supercycle."""
    if not 2 <= len(seeds) <= 6 or len({s.recipe_id for s in seeds}) != len(seeds):
        raise ValueError('select two to six distinct component recipes')
    if any(s.raw['metadata']['chemistry_status'] != 'established' for s in seeds):
        raise ValueError('components must be catalog-established')
    if len({key for s in seeds for key in s.identities}) > 6:
        raise ValueError('combination exceeds six precursors')
    if sum(len(s.exposures) for s in seeds) > 12:
        raise ValueError('combination exceeds twelve exposures')

    precursors, assigned, exposures, components = {}, {}, [], []
    for seed in seeds:
        mapping = {}
        for old_id, precursor in seed.raw['precursors'].items():
            key = identity(precursor)
            if key not in assigned:
                new_id = 'ABCDEF'[len(assigned)]
                assigned[key] = new_id
                precursors[new_id] = deepcopy(precursor)
            mapping[old_id] = assigned[key]
        start = len(exposures)
        exposures.extend(dict(e, precursor=mapping[e['precursor']]) for e in seed.exposures)
        components.append({
            'recipe_id': seed.recipe_id, 'path': seed.path, 'sha256': seed.sha256,
            'target_formula': seed.raw['metadata']['target_formula'],
            'exposure_start': start, 'exposure_stop': len(exposures),
            'precursor_mapping': mapping,
            'source_references': seed.raw['metadata']['source_references'],
        })
    digest = hashlib.sha256(canonical([s.recipe_id for s in seeds])).hexdigest()[:24]
    references = {json.dumps(r, sort_keys=True): r for s in seeds
                  for r in s.raw['metadata']['source_references']}
    # Use the existing generic simulation envelope, not a component's kinetic
    # model: reaction-factor arrays in a source may have a different signature.
    template = json.loads((ROOT / 'recipes/compounds/oxides/al2o3_tma_water.json').read_text())
    raw = deepcopy(template)
    raw['recipe_id'] = f'combination-{digest}'
    raw['precursors'] = precursors
    raw['metadata'] = {
        'recipe_schema': 'multi-precursor/1',
        'target_material': ' / '.join(s.raw['metadata']['target_material'] for s in seeds),
        'target_formula': '/'.join(s.raw['metadata']['target_formula'] for s in seeds),
        'chemistry_family': 'composed-sequential-motifs',
        'chemistry_status': 'conceptual-multicomponent-surrogate',
        'product_family': 'unvalidated combined-stack simulation',
        'physical_fabrication_mapping': False,
        'simulation_notice': NOTICE,
        'combination_evidence': 'not-established',
        'component_recipes': components,
        'source_references': [references[key] for key in sorted(references)],
    }
    raw['surface'] = {'model_version': 'site-sequential/1'}
    for instruction in raw['instructions']:
        if instruction['opcode'] == 'DEPOSITION_CYCLE':
            instruction['arguments'] = {'exposures': exposures, 'repeat': 1}
    core.compile_recipe(core.validate_recipe(raw))
    return raw


def build_catalog(output, seeds, max_components=6):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    histogram, digest = Counter(), hashlib.sha256()
    # Header timestamp and filename are fixed for reproducible compressed output.
    with (output / 'combinations.jsonl.gz').open('wb') as destination:
        with gzip.GzipFile(fileobj=destination, mode='wb', filename='', mtime=0) as stream:
            for indices in iter_combinations(seeds, max_components):
                payload = canonical(indices)
                stream.write(payload)
                digest.update(payload)
                histogram[len(indices)] += 1
    summary = {
        'schema': 'ald-recipe-combinations/1',
        'notice': NOTICE,
        'selection': {'chemistry_status': 'established', 'min_components': 2,
                      'max_components': max_components, 'max_precursors': 6,
                      'max_exposures': 12, 'repeated_components': False},
        'row_format': 'Array of zero-based seed indices in ascending order; all permutations are exportable.',
        'combination_count': sum(histogram.values()),
        'ordered_sequence_count': sum(math.factorial(n) * count for n, count in histogram.items()),
        'counts_by_component_count': {str(n): histogram[n] for n in sorted(histogram)},
        'index_uncompressed_sha256': digest.hexdigest(),
        'seeds': [{'index': i, 'recipe_id': seed.recipe_id, 'path': seed.path,
                   'sha256': seed.sha256, 'target_formula': seed.raw['metadata']['target_formula'],
                   'precursors': seed.raw['precursors'],
                   'source_references': seed.raw['metadata']['source_references']}
                  for i, seed in enumerate(seeds)],
    }
    (output / 'manifest.json').write_bytes(canonical(summary))
    return summary


def check_catalog(output, seeds, max_components=6):
    output = Path(output)
    with tempfile.TemporaryDirectory() as directory:
        expected = build_catalog(directory, seeds, max_components)
        if (output / 'manifest.json').read_bytes() != canonical(expected):
            raise ValueError('combination manifest is stale or corrupt; rebuild it')
        digest = hashlib.sha256()
        with gzip.open(output / 'combinations.jsonl.gz', 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected['index_uncompressed_sha256']:
            raise ValueError('combination index is stale or corrupt; rebuild it')
    return expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('build', 'check'):
        command = sub.add_parser(name)
        command.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
        command.add_argument('--max-components', type=int, choices=range(2, 7), default=6)
    export = sub.add_parser('export', help='Export named components in the exact supplied order')
    export.add_argument('components', nargs='+', help='Recipe IDs from manifest.json')
    export.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        seeds = load_seeds()
        if args.command == 'export':
            by_id = {seed.recipe_id: seed for seed in seeds}
            missing = set(args.components) - by_id.keys()
            if missing:
                raise ValueError(f'unknown or non-established components: {sorted(missing)}')
            raw = compose_recipe([by_id[recipe_id] for recipe_id in args.components])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical(raw))
            print(f'Exported {raw["recipe_id"]} to {args.output}')
        else:
            action = build_catalog if args.command == 'build' else check_catalog
            summary = action(args.output, seeds, args.max_components)
            print(json.dumps({key: summary[key] for key in (
                'combination_count', 'ordered_sequence_count', 'counts_by_component_count')}, sort_keys=True))
        return 0
    except (ValueError, OSError, EOFError) as error:
        print(f'recipe combinations: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
