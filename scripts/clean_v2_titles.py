from pathlib import Path

path = Path("vocabulary.py")
text = path.read_text(encoding="utf-8")

start_marker = "# ============================================================\n# ШУТОЧНЫЕ ТИТУЛЫ (/title)"
end_marker = "# ============================================================\n# ТОСТЫ (/toast)"

start = text.index(start_marker)
end = text.index(end_marker, start)

replacement = '''# ============================================================
# ШУТОЧНЫЕ ТИТУЛЫ (/title) — V2
#
# Единственный источник титулов: title_pools.py.
# Ровно 10 титулов на каждую V2-личность + отдельные street_memes.
# Старые tone-категории V1 удалены из vocabulary.py полностью.
# ============================================================

from title_pools import (
    ALL_TITLES as JOKE_TITLES,
    TITLE_POOLS as JOKE_TITLE_CATEGORIES,
)


'''

path.write_text(
    text[:start] + replacement + text[end:],
    encoding="utf-8",
)
