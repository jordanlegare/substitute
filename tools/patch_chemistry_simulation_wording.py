from pathlib import Path

path = Path("ald_master/__init__.py")
text = path.read_text(encoding="utf-8")
old = '''    print(\n        "  boundary: literature-recognition chemistry; simulator execution values "\n        "are synthetic and are not shown here"\n    )\n'''
new = '''    print(\n        "  boundary: literature-recognition chemistry for simulation only; "\n        "simulator execution values are synthetic and are not shown here"\n    )\n'''
if text.count(old) != 1:
    raise SystemExit("expected exactly one chemistry safety-boundary marker")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
