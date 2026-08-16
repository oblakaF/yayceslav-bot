from pathlib import Path

p = Path('style_engine.py')
text = p.read_text(encoding='utf-8')
repls = {
    '        VOICE_PACK_YOUTH: 0.22,\n        VOICE_PACK_SKOOF: 0.18,\n        VOICE_PACK_OLD_RUSSIAN: 0.045,\n        VOICE_PACK_BLAT: 0.10,\n': '        VOICE_PACK_YOUTH: 0.19,\n        VOICE_PACK_SKOOF: 0.15,\n        VOICE_PACK_OLD_RUSSIAN: 0.045,\n        VOICE_PACK_BLAT: 0.13,\n',
    '        VOICE_PACK_BATTLE_2017: 0.06,\n        VOICE_PACK_POST_IRONY: 0.06,\n': '        VOICE_PACK_BATTLE_2017: 0.06,\n        VOICE_PACK_POST_IRONY: 0.09,\n',
    '        VOICE_PACK_YOUTH: 0.23,\n        VOICE_PACK_SKOOF: 0.20,\n        VOICE_PACK_OLD_RUSSIAN: 0.055,\n        VOICE_PACK_BLAT: 0.15,\n': '        VOICE_PACK_YOUTH: 0.21,\n        VOICE_PACK_SKOOF: 0.18,\n        VOICE_PACK_OLD_RUSSIAN: 0.055,\n        VOICE_PACK_BLAT: 0.17,\n',
    '        VOICE_PACK_BATTLE_2017: 0.05,\n        VOICE_PACK_POST_IRONY: 0.05,\n': '        VOICE_PACK_BATTLE_2017: 0.05,\n        VOICE_PACK_POST_IRONY: 0.07,\n',
    '        VOICE_PACK_YOUTH: 0.22,\n        VOICE_PACK_SKOOF: 0.16,\n        VOICE_PACK_OLD_RUSSIAN: 0.040,\n        VOICE_PACK_BLAT: 0.22,\n': '        VOICE_PACK_YOUTH: 0.18,\n        VOICE_PACK_SKOOF: 0.13,\n        VOICE_PACK_OLD_RUSSIAN: 0.040,\n        VOICE_PACK_BLAT: 0.26,\n',
    '        VOICE_PACK_BATTLE_2017: 0.11,\n        VOICE_PACK_POST_IRONY: 0.10,\n': '        VOICE_PACK_BATTLE_2017: 0.11,\n        VOICE_PACK_POST_IRONY: 0.13,\n',
    '        VOICE_PACK_YOUTH: 0.18,\n        VOICE_PACK_SKOOF: 0.15,\n        VOICE_PACK_OLD_RUSSIAN: 0.030,\n        VOICE_PACK_BLAT: 0.27,\n': '        VOICE_PACK_YOUTH: 0.15,\n        VOICE_PACK_SKOOF: 0.12,\n        VOICE_PACK_OLD_RUSSIAN: 0.030,\n        VOICE_PACK_BLAT: 0.31,\n',
    '        VOICE_PACK_BATTLE_2017: 0.14,\n        VOICE_PACK_POST_IRONY: 0.10,\n': '        VOICE_PACK_BATTLE_2017: 0.14,\n        VOICE_PACK_POST_IRONY: 0.12,\n',
}
for old, new in repls.items():
    if text.count(old) != 1:
        raise SystemExit(f'marker mismatch: {old!r} count={text.count(old)}')
    text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')

t = Path('tests/test_compact_conflict_humanizer.py')
s = t.read_text(encoding='utf-8')
append = '''\n\ndef test_voice_mix_rebalances_away_from_youth_and_skoof():\n    normal = style_engine._VOICE_PACK_WEIGHTS_BY_MODE["normal"]\n    assert normal[style_engine.VOICE_PACK_YOUTH] == 0.19\n    assert normal[style_engine.VOICE_PACK_SKOOF] == 0.15\n    assert normal[style_engine.VOICE_PACK_BLAT] == 0.13\n    assert normal[style_engine.VOICE_PACK_POST_IRONY] == 0.09\n\n    hostile = style_engine._VOICE_PACK_WEIGHTS_BY_MODE["hostile"]\n    assert hostile[style_engine.VOICE_PACK_YOUTH] == 0.15\n    assert hostile[style_engine.VOICE_PACK_SKOOF] == 0.12\n    assert hostile[style_engine.VOICE_PACK_BLAT] == 0.31\n    assert hostile[style_engine.VOICE_PACK_POST_IRONY] == 0.12\n'''
if 'test_voice_mix_rebalances_away_from_youth_and_skoof' not in s:
    t.write_text(s + append, encoding='utf-8')
