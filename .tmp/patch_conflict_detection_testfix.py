from pathlib import Path

p = Path("tests/test_conflict_detection_lazy_gate.py")
text = p.read_text(encoding="utf-8")
old = '        user_text="почему так?",\n'
new = '        user_text="кто победит?",\n'
if text.count(old) != 1:
    raise SystemExit(f"test marker mismatch: {text.count(old)}")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
