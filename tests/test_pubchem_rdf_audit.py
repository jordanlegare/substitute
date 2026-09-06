from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from tools import refresh_material_sources as refresh


def test_pubchem_rdf_formula_parser_extracts_cid_and_formula():
    parser = getattr(refresh, "parse_pubchem_rdf_formula_line", None)
    assert callable(parser)
    assert parser('compound:CID10002\tvocab:molecular_formula\t"C3H3Cl2F3" .\n') == ("10002", "C3H3Cl2F3")
    assert parser('@prefix vocab:\t<http://rdf.ncbi.nlm.nih.gov/pubchem/vocabulary#> .\n') is None


def test_pubchem_rdf_audit_matches_reduced_formulas_and_keeps_all_cids():
    audit = getattr(refresh, "audit_pubchem_rdf_lines", None)
    assert callable(audit)
    lines = [
        'compound:CID10\tvocab:molecular_formula\t"Hf2O4" .\n',
        'compound:CID7\tvocab:molecular_formula\t"HfO2" .\n',
        'compound:CID20\tvocab:molecular_formula\t"TiO2" .\n',
        'compound:CID30\tvocab:molecular_formula\t"C2H6O" .\n',
        'compound:CID40\tvocab:molecular_formula\t"Fe0.9O" .\n',
    ]
    result = audit(lines, {"HfO2", "TiO2"})
    assert result["formula_records_scanned"] == 5
    assert result["matched"] == {
        "HfO2": ["7", "10"],
        "O2Ti": ["20"],
    }
    assert result["unsupported_formula_records"] == 1


def test_pubchem_rdf_variant_index_supports_formula_unit_multiples():
    build_index = getattr(refresh, "build_pubchem_formula_variant_index", None)
    assert callable(build_index)
    index = build_index({"HfO2", "TiO2"}, max_scale=3)
    assert index["HfO2"] == "HfO2"
    assert index["Hf2O4"] == "HfO2"
    assert index["Hf3O6"] == "HfO2"
    assert index["O2Ti"] == "O2Ti"
    assert index["O4Ti2"] == "O2Ti"


def test_fast_binary_scan_counts_all_formula_records_and_matches_variants():
    scan = getattr(refresh, "audit_pubchem_rdf_binary_lines", None)
    assert callable(scan)
    variants = refresh.build_pubchem_formula_variant_index({"HfO2", "TiO2"}, max_scale=3)
    lines = [
        b'@prefix vocab:\t<http://rdf.ncbi.nlm.nih.gov/pubchem/vocabulary#> .\n',
        b'compound:CID10\tvocab:molecular_formula\t"Hf2O4" .\n',
        b'compound:CID20\tvocab:molecular_formula\t"O2Ti" .\n',
        b'compound:CID30\tvocab:molecular_formula\t"C2H6O" .\n',
    ]
    result = scan(lines, variants)
    assert result["formula_records_scanned"] == 3
    assert result["matched"] == {"HfO2": ["10"], "O2Ti": ["20"]}


def test_pubchem_primary_formula_filter_keeps_simple_material_like_inorganics():
    normalize = getattr(refresh, "normalize_pubchem_primary_formula", None)
    assert callable(normalize)
    assert normalize("GaSb") == "GaSb"
    assert normalize("NaCl") == "ClNa"
    assert normalize("Na2O") == "Na2O"
    assert normalize("CCl4") is None
    assert normalize("H2O") is None
    assert normalize("KrF2") is None
    assert normalize("Na13Cl") is None


def test_fast_binary_scan_collects_bounded_pubchem_primary_supplements():
    scan = getattr(refresh, "audit_pubchem_rdf_binary_lines", None)
    assert callable(scan)
    variants = refresh.build_pubchem_formula_variant_index({"HfO2"}, max_scale=3)
    lines = [
        b'compound:CID1\tvocab:molecular_formula\t"Hf2O4" .\n',
        b'compound:CID2\tvocab:molecular_formula\t"CCl4" .\n',
        b'compound:CID3\tvocab:molecular_formula\t"H2O" .\n',
        b'compound:CID4\tvocab:molecular_formula\t"GaSb" .\n',
        b'compound:CID5\tvocab:molecular_formula\t"NaCl" .\n',
        b'compound:CID6\tvocab:molecular_formula\t"Na2O" .\n',
    ]
    result = scan(lines, variants, supplemental_limit=2)
    assert result["formula_records_scanned"] == 6
    assert result["matched"] == {"HfO2": ["1"]}
    assert result["supplemental"] == {"ClNa": ["5"], "GaSb": ["4"]}


def test_pubchem_audit_script_runs_directly_from_repository_root():
    script = Path("tools/audit_pubchem_rdf.py")
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "Audit frozen material candidates" in result.stdout
