from pathlib import Path

p = Path("humanizer_engine.py")
text = p.read_text(encoding="utf-8")
old = '''    if not sentences:\n        sentences = [clean]\n\n    kept: list[str] = []\n'''
new = '''    if not sentences:\n        sentences = [clean]\n\n    # A short explicit send-off is already a complete human reply.\n    # Do not append Gemini's explanatory second sentence after it.\n    first_lower = sentences[0].lower()\n    direct_sendoff_markers = (\n        "иди нах",\n        "пошел нах",\n        "пошёл нах",\n        "нахуй",\n        "на хуй",\n        "отъеб",\n        "съеб",\n        "завали ебало",\n    )\n    if (\n        len(sentences[0]) <= 45\n        and any(marker in first_lower for marker in direct_sendoff_markers)\n    ):\n        return (sentences[0],)\n\n    kept: list[str] = []\n'''
if text.count(old) != 1:
    raise SystemExit("compact conflict post-patch marker mismatch")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
