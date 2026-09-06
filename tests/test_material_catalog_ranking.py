from tools import build_material_catalog as builder


def _record(formula, elements, classes, *, provenance=1, phases=1):
    return {
        "material_id": f"mat-{formula}",
        "reduced_formula": formula,
        "elements": list(elements),
        "material_classes": list(classes),
        "provenance": [
            {"source": "cod", "source_id": str(index), "evidence": "crystallographic_identity"}
            for index in range(provenance)
        ],
        "phases": [
            {"source": "cod", "source_id": str(index), "space_group": "P1"}
            for index in range(phases)
        ],
        "identifiers": {},
    }


def test_oxyanion_materials_are_not_mislabeled_as_binary_anion_classes():
    assert "sulfide" not in builder.classify_material(("Ca", "O", "S"), "CaO4S", {})
    assert "boride" not in builder.classify_material(("B", "O"), "B2O3", {})
    assert "arsenide" not in builder.classify_material(("As", "O"), "As2O3", {})
    assert "telluride" not in builder.classify_material(("O", "Te"), "O2Te", {})

    assert "sulfide" in builder.classify_material(("S", "Zn"), "SZn", {})
    assert "boride" in builder.classify_material(("B", "Ti"), "B2Ti", {})
    assert "arsenide" in builder.classify_material(("As", "Ga"), "AsGa", {})
    assert "telluride" in builder.classify_material(("Bi", "Te"), "Bi2Te3", {})


def test_relevance_score_prefers_simple_binary_materials_over_complex_salts():
    simple = _record("HfO2", ("Hf", "O"), ("oxide",), provenance=1, phases=1)
    complex_salt = _record(
        "Ca3O8P2",
        ("Ca", "O", "P"),
        ("oxide", "phosphate"),
        provenance=8,
        phases=8,
    )

    assert builder.relevance_score(simple) < builder.relevance_score(complex_salt)


def test_intermetallics_remain_eligible_materials():
    classes = builder.classify_material(("Al", "Fe"), "AlFe", {})
    assert "intermetallic" in classes


def test_recipe_backed_materials_are_linked_and_prioritized():
    source_records = [
        {"source": "cod", "source_id": "1", "formula": "HfO2", "name": "hafnium dioxide"},
        {"source": "cod", "source_id": "2", "formula": "ZrO2", "name": "zirconium dioxide"},
    ]
    recipe_entries = [
        {
            "recipe_id": "hafnia-water",
            "path": "recipes/compounds/hafnia-water.json",
            "target_formula": "HfO2",
        }
    ]

    catalog, _manifest, audit = builder.build_material_artifacts(
        source_records,
        [],
        recipe_entries,
        target_count=1,
    )

    assert [entry["reduced_formula"] for entry in catalog["entries"]] == ["HfO2"]
    process = catalog["entries"][0]["process_evidence"]
    assert process == {
        "status": "executable-recipe",
        "recipe_ids": ["hafnia-water"],
        "recipe_paths": ["recipes/compounds/hafnia-water.json"],
    }
    assert audit["recipe_linked_materials"] == 1
