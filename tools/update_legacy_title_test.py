from pathlib import Path

path = Path("tests/test_last_message_commands.py")
text = path.read_text(encoding="utf-8")
old = '''def test_pick_new_title_falls_back_when_only_one_option(monkeypatch):\n    monkeypatch.setattr(bot, "JOKE_TITLES", ["Единственный титул"])\n    assert bot.pick_new_title("Единственный титул") == "Единственный титул"\n'''
new = '''def test_pick_new_title_delegates_to_v2_title_pools(monkeypatch):\n    monkeypatch.setattr(\n        bot.title_pools,\n        "pick_title",\n        lambda previous_title=None: "Единственный титул",\n    )\n    assert bot.pick_new_title("Старый титул") == "Единственный титул"\n'''
if old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
elif new not in text:
    raise SystemExit("legacy title test anchor not found")
