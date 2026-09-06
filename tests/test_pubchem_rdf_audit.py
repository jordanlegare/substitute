from __future__ import annotations

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
