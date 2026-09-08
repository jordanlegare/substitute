import copy
import gzip
import itertools
import json
import math

import pytest

import ald_core as core
from tools import build_recipe_combinations as combos


def test_enumeration_matches_brute_force_with_no_truncation():
    seeds = combos.load_seeds()
    # Include different families and the four-exposure doped-oxide motif.
    sample = seeds[:3] + seeds[24:28] + seeds[-1:]
    expected = []
    for size in range(2, 7):
        for indices in itertools.combinations(range(len(sample)), size):
            selected = [sample[i] for i in indices]
            identities = {key for seed in selected for key in seed.identities}
            if len(identities) <= 6 and sum(len(s.exposures) for s in selected) <= 12:
                expected.append(indices)
    actual = list(combos.iter_combinations(sample))
    assert set(actual) == set(expected)
    assert len(actual) == len(set(actual))
    assert actual == list(combos.iter_combinations(sample))


def test_only_catalog_established_seeds_with_references_are_used():
    seeds = combos.load_seeds()
    assert len(seeds) == 59
    assert all(s.raw['metadata']['chemistry_status'] == 'established' for s in seeds)
    assert all(s.raw['metadata']['source_references'] for s in seeds)


def test_export_preserves_motifs_merges_shared_water_and_runs():
    seeds = combos.load_seeds()
    selected = [next(s for s in seeds if s.recipe_id.endswith(suffix)) for suffix in (
        'al2o3_tma_water-001', 'tio2_ticl4_water-001', 'zno_dez_water-001')]
    before = copy.deepcopy([s.raw for s in selected])
    raw = combos.compose_recipe(selected)
    assert len(raw['precursors']) == 4
    cycle = next(i for i in raw['instructions'] if i['opcode'] == 'DEPOSITION_CYCLE')
    names = [raw['precursors'][e['precursor']]['name'] for e in cycle['arguments']['exposures']]
    assert names == ['trimethylaluminum', 'water', 'titanium tetrachloride', 'water', 'diethylzinc', 'water']
    assert raw['metadata']['chemistry_status'] == 'conceptual-multicomponent-surrogate'
    assert raw['metadata']['combination_evidence'] == 'not-established'
    assert len(raw['metadata']['component_recipes']) == 3
    result = core.SimulatedALDController().execute(core.compile_recipe(core.validate_recipe(raw)), 42)
    assert result.fault is None
    assert result.final_state is core.ControllerState.IDLE
    assert before == [s.raw for s in selected]
    reverse = combos.compose_recipe(list(reversed(selected)))
    assert reverse['recipe_id'] != raw['recipe_id']


def test_export_rejects_duplicate_components_and_excess_precursors():
    seeds = combos.load_seeds()
    with pytest.raises(ValueError, match='distinct'):
        combos.compose_recipe([seeds[0], seeds[0]])
    selected = []
    identities = set()
    for seed in seeds:
        if not identities.intersection(seed.identities):
            selected.append(seed)
            identities.update(seed.identities)
        if len(selected) == 4:
            break
    with pytest.raises(ValueError, match='six precursors'):
        combos.compose_recipe(selected)


def test_catalog_rebuild_check_and_corruption_detection(tmp_path):
    seeds = combos.load_seeds()[:5]
    first, second = tmp_path / 'first', tmp_path / 'second'
    summary = combos.build_catalog(first, seeds)
    combos.build_catalog(second, seeds)
    assert (first / 'combinations.jsonl.gz').read_bytes() == (second / 'combinations.jsonl.gz').read_bytes()
    rows = [json.loads(line) for line in gzip.open(first / 'combinations.jsonl.gz', 'rt')]
    assert len(rows) == summary['combination_count']
    assert summary['ordered_sequence_count'] == sum(math.factorial(len(row)) for row in rows)
    combos.check_catalog(first, seeds)
    with gzip.open(first / 'combinations.jsonl.gz', 'wb') as stream:
        stream.write(b'[0,0]\n')
    with pytest.raises(ValueError, match='stale|corrupt'):
        combos.check_catalog(first, seeds)


def test_largest_sequences_compile_and_simulate_within_packet_limit():
    seeds = combos.load_seeds()
    largest = next(indices for indices in combos.iter_combinations(seeds) if len(indices) == 6)
    doped = len(seeds) - 1
    with_dopant = next(indices for indices in combos.iter_combinations(seeds)
                       if doped in indices and sum(len(seeds[i].exposures) for i in indices) == 12)
    for indices in (largest, with_dopant):
        raw = combos.compose_recipe([seeds[i] for i in indices])
        compiled = core.compile_recipe(core.validate_recipe(raw))
        assert max(len(p.canonical_bytes) for p in compiled.packets) <= 800
        result = core.SimulatedALDController().execute(compiled, 42)
        assert result.fault is None
        assert len(result.surface.exposure_signature) == 12


def test_export_cli_reports_invalid_components_without_writing(tmp_path, capsys):
    output = tmp_path / 'recipe.json'
    assert combos.main(['export', 'invented', 'also-invented', '--output', str(output)]) == 1
    assert not output.exists()
    assert 'unknown or non-established' in capsys.readouterr().err


def test_export_cli_produces_a_valid_recipe(tmp_path):
    seeds = combos.load_seeds()
    output = tmp_path / 'recipe.json'
    assert combos.main(['export', seeds[0].recipe_id, seeds[1].recipe_id,
                        '--output', str(output)]) == 0
    core.compile_recipe(core.validate_recipe(json.loads(output.read_text())))


def test_checked_in_exhaustive_catalog_is_current():
    result = combos.check_catalog(combos.DEFAULT_OUTPUT, combos.load_seeds())
    assert result['combination_count'] == 397811
    assert result['ordered_sequence_count'] == 48534764


def test_bulk_export_writes_all_valid_recipes_and_resumes(tmp_path):
    seeds = combos.load_seeds()[:3]
    result = combos.export_all(tmp_path, seeds)
    assert result == {'total': 4, 'written': 4, 'skipped': 0}
    files = sorted(tmp_path.glob('*-components/*/combination-*.json'))
    assert len(files) == 4
    for path in files:
        raw = json.loads(path.read_text())
        count = len(raw['metadata']['component_recipes'])
        assert path.parent.parent.name == f'{count}-components'
        assert path.stem == raw['recipe_id']
        core.compile_recipe(core.validate_recipe(raw))
    assert combos.export_all(tmp_path, seeds) == {'total': 4, 'written': 0, 'skipped': 4}


def test_bulk_export_all_orders_and_dry_run(tmp_path):
    seeds = combos.load_seeds()[:3]
    destination = tmp_path / 'recipes'
    result = combos.export_all(destination, seeds, all_orders=True, dry_run=True)
    assert result == {'total': 12, 'written': 0, 'skipped': 0}
    assert not destination.exists()
    assert combos.export_all(destination, seeds, all_orders=True)['written'] == 12
    assert len(list(destination.rglob('combination-*.json'))) == 12
    assert combos.export_all(tmp_path / 'pairs', seeds, max_components=2)['total'] == 3


def test_bulk_export_does_not_silently_replace_changed_files(tmp_path):
    seeds = combos.load_seeds()[:2]
    combos.export_all(tmp_path, seeds)
    path = next(tmp_path.rglob('combination-*.json'))
    path.write_text('user modified this file')
    with pytest.raises(ValueError, match='overwrite'):
        combos.export_all(tmp_path, seeds)
    assert path.read_text() == 'user modified this file'
    assert combos.export_all(tmp_path, seeds, overwrite=True)['written'] == 1
    core.validate_recipe(json.loads(path.read_text()))


def test_bulk_export_cli_dry_run_uses_repository_recipe_folder(capsys):
    assert combos.DEFAULT_EXPORT == combos.ROOT / 'recipes/combinations/generated'
    assert combos.main(['export-all', '--max-components', '2', '--dry-run']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['total'] == 1711
    assert output['written'] == 0
