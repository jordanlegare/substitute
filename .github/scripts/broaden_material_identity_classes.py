from pathlib import Path

path = Path("tools/build_material_catalog.py")
text = path.read_text(encoding="utf-8")

old = '''    if "As" in present and not has_oxygen:
        classes.add("arsenide")
    if len(present) >= 2 and present.issubset(_METALLIC_ELEMENTS):
        classes.add("intermetallic")
'''
new = '''    if "As" in present and not has_oxygen:
        classes.add("arsenide")
    if "Sb" in present and not has_oxygen:
        classes.add("antimonide")
    if "Ge" in present and not has_oxygen:
        classes.add("germanide")
    if "H" in present and "C" not in present and not has_oxygen and present.intersection(_METALLIC_ELEMENTS):
        classes.add("hydride")
    if len(present) >= 2 and present.issubset(_METALLIC_ELEMENTS):
        classes.add("intermetallic")
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    classes = set(classify_material(elements, reduced_formula, {}))
    classes.update(explicit_classes)
    result = {
'''
new = '''    classes = set(classify_material(elements, reduced_formula, {}))
    classes.update(explicit_classes)
    if not classes:
        classes.add("other-inorganic")
    result = {
'''
assert old in text
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
