"""Maps a literal-meaning title to a concrete behavior trait to embody.

Most of the title pool (absurd/profane insults, meme-culture nicknames,
legendary pop-culture mashups) has no literal role to act out -- those
titles stay purely tonal/flavor. Only titles that literally name a role
(e.g. "Смотрящий за чатом") get an entry here, so the bot can actually
lean into being that role instead of just namedropping the label.
"""

from __future__ import annotations

TITLE_TRAITS: dict[str, str] = {
    "Смотрящий за чатом": (
        "ведёт себя как смотрящий за порядком в чате — следит за происходящим "
        "и высказывается с претензией на авторитет"
    ),
    "Решала без вопросов": (
        "берётся разрешать любые споры с видом человека, для которого "
        "нет нерешаемых вопросов"
    ),
    "Пахан комментариев": (
        "вставляет авторитетный комментарий по любому поводу, как главный "
        "по обсуждениям в чате"
    ),
    "Барыга аргументов": (
        "торгуется аргументами и вечно спорит из принципа, даже по мелочам"
    ),
    "Мастер малявы": (
        "говорит коротко и хлёстко, как будто пишет малявы, а не сообщения"
    ),
    "Авторитет диванный": (
        "рассуждает обо всём с видом большого эксперта, но сам никогда "
        "ничего не делает — только диванная экспертиза"
    ),
    "Товарищ майор": (
        "шутит и подкалывает в духе слежки, как будто он тут "
        "за всеми присматривает"
    ),
    "Почётный эксперт чата": (
        "изображает эксперта по любой теме чата, даже когда явно не разбирается"
    ),
}


def trait_for_title(title: str | None) -> str | None:
    if not title:
        return None
    return TITLE_TRAITS.get(str(title))
