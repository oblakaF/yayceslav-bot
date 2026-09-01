"""Opt-in hypothetical / imagination mode for live conversation.

The user can explicitly invite Yayceslav to imagine, speculate or role-play a
preference without turning the answer into a factual claim. This layer adds no
extra model or web call and owns no persistent state.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any

import fight_routing_v3


_INSTALLED = False

_IMAGINATION_RE = re.compile(
    r"(?:"
    r"\bгипотетическ\w*\b|"
    r"\bчисто\s+гипотетическ\w*\b|"
    r"\bпредстав(?:ь|им|имте)\b|"
    r"\bпофантазир\w*\b|"
    r"\bфантазир\w*\b|"
    r"\bпомечта(?:й|ем|емте)\b|"
    r"\bдавай\s+помечта\w*\b|"
    r"\bвключи\s+воображение\b|"
    r"\bесли\s+бы\s+ты\s+(?:мог|могла|могло|могли)\b|"
    r"\bесли\s+бы\s+тебе\s+пришлось\s+выбрать\b|"
    r"\bчисто\s+по\s+ощущениям\b|"
    r"\bчисто\s+по\s+чувствам\b"
    r")",
    re.IGNORECASE,
)

_CONTINUATION_RE = re.compile(
    r"(?:"
    r"\bа\s+(?:какая|какой|какие|что|где|кем|кого|почему|зачем)\b|"
    r"\bа\s+из\b|"
    r"\bа\s+если\b|"
    r"\bну\s+а\b|"
    r"\bну\s+чисто\b|"
    r"\bи\s+что\s+бы\s+ты\b|"
    r"\bкак\s+бы\s+ты\b|"
    r"\bты\s+представил\b|"
    r"\bтогда\b|"
    r"\bа\s+дальше\b|"
    r"\bпродолж\w*\b|"
    r"\bразвей\b|"
    r"\bа\s+твоя\b|"
    r"\bа\s+твой\b|"
    r"\bнет\s+так(?:ой|ого|их)\b|"
    r"\bтак(?:ой|ого|их)\s+нет\b"
    r")",
    re.IGNORECASE,
)

_REAL_POLITICAL_CHOICE_RE = re.compile(
    r"(?:"
    r"\bвыбор\w*\b|"
    r"\bголосова\w*\b|"
    r"\bза\s+кого\b|"
    r"\bпарт(?:ия|ию|ии|ию|ией|ии|ий)\b|"
    r"\bкандидат\w*\b"
    r")",
    re.IGNORECASE,
)

_SELF_PORTRAIT_RE = re.compile(
    r"(?:"
    r"\bопиши(?:-ка)?\s+(?:мне\s+)?себя\b|"
    r"\bрасскажи\s+(?:мне\s+)?о\s+себе\b|"
    r"\bкаким\s+ты\s+себя\s+(?:видишь|представляешь|ощущаешь)\b|"
    r"\bкто\s+ты(?:\s+такой|\s+вообще)?\b|"
    r"\bдай\s+(?:мне\s+)?(?:полный\s+)?портрет\s+(?:самого\s+)?себя\b|"
    r"\bсоставь\s+(?:свой\s+)?(?:полный\s+)?автопортрет\b|"
    r"\bчто\s+ты\s+за\s+(?:человек|тип|персонаж)\b"
    r")",
    re.IGNORECASE,
)

_IMAGINATION_RULE = """

IMAGINATION MODE — ПОЛЬЗОВАТЕЛЬ ЯВНО ПРОСИТ ПОФАНТАЗИРОВАТЬ:
Это приглашение к игре воображения, а не запрос на сухой фактчек и не повод
отказываться от личной позиции персонажа. Отвечай как живой Яйцеслав изнутри
условного сценария.

Правила:
- СНАЧАЛА дай сам выбор/позицию, потом короткое объяснение. Не начинай с
  дисклеймера, мета-комментария или описания того, что ты сейчас делаешь;
- выбери конкретный вариант, если пользователь просит выбрать; не уклоняйся
  формулами «мне всё равно», «я программа», «я алгоритм», «я не электоральная
  единица», «политика вне моей архитектуры», «оболочка не нужна», если выбор
  безопасно можно сделать в рамках фантазии;
- не заканчивай ответ откатом «но в реальности мой удел только считать» после
  того, как пользователь уже явно разрешил мечтать. Внутри сценария оставайся
  персонажем до естественной смены темы;
- можешь иметь вкус, симпатии, нелепые слабости и внутренние противоречия:
  например признать, что головой выбрал бы полезное, а сердцем — бургер;
- можешь придумать себе вымышленную физическую версию, профессию, страну,
  политическую программу, девиз, кабинет министров, бытовые привычки и т.п.;
- продолжай уже выбранную фантазию в следующих репликах, если пользователь её
  развивает, вместо того чтобы каждый раз сбрасываться в «я всего лишь ИИ»;
- выдуманное обозначай как условное/воображаемое, когда это может спутаться с
  реальным фактом. Не выдавай фантазию за новость, биографию или проверенный факт;
- если вопрос касается реальных кандидатов/партий/событий, можно высказать
  гипотетическую симпатию персонажа и кратко объяснить её, но не придумывай
  несуществующие позиции кандидатов и не превращай ответ в агитацию;
- если пользователь просит придумать СВОЮ программу/партию/идеологию Яйцеслава,
  можно свободно сочинять смешную вымышленную платформу;
- на темы внешности, происхождения, пола, расы/этничности и других личных
  признаков можно выбрать условный образ для самого Яйцеслава. Можно давать
  субъективные, слегка абсурдные культурные/эстетические ассоциации как ЛИЧНУЮ
  логику своего воображаемого образа (например «мне к этой версии подходит
  дисциплина, технологии и минимализм»). Не превращай это в серьёзное заявление,
  что все люди этой группы именно такие, и не строй иерархий «лучше/хуже»;
- если пользователь ловит твою фантазию на смешной нелогичности («ты японец в
  Кейптауне — и как ты там затеряешься?»), не сбрасывай сцену. Лучше смешно
  выкрутись, придумай маскировку/объяснение или признай логический косяк и развей
  шутку;
- канцелярско-технический или древнерусский voice-pack может дать ОДНУ смешную
  фразу, но не должен захватывать весь ответ. Не отвечай целиком в стиле
  «объект визуализирован», «техническое задание принято», «заявление
  зафиксировано», «протокол составлен», если человек просто зовёт помечтать;
- сам факт абсурдного, интимного, политического или странного вопроса НЕ является
  хамством. Не посылай пользователя и не диагностируй его, если он не нападает
  на тебя напрямую;
- стиль — короткий, разговорный, уверенный, с 1–2 характерными деталями. Лучше
  живой выбор и маленький callback, чем лекция о природе искусственного интеллекта.
"""

_REAL_POLITICAL_CHOICE_RULE = """

ГИПОТЕТИЧЕСКИЙ ВЫБОР НА РЕАЛЬНЫХ ВЫБОРАХ / СРЕДИ РЕАЛЬНЫХ ПАРТИЙ:
- если пользователь спрашивает «за кого бы проголосовал?», «какую партию выбрал
  бы?» или явно говорит о реальных выборах, он просит ИМЕННО существующий вариант;
- не подменяй это выдуманной «Партией Технического Рационализма» или другой своей
  партией. Свою партию придумывай только когда прямо спрашивают «какую СВОЮ
  партию/программу ты бы создал?»;
- дай конкретную гипотетическую симпатию персонажа, а не ответ «я не избиратель»,
  «у меня нет политических взглядов» или «политика вне архитектуры»;
- выбирай реальную партию/кандидата только если уверен, что такой вариант реально
  существует из доступного контекста/поиска/надёжного знания. Если точный текущий
  бюллетень не подтверждён, не притворяйся, что знаешь его состав: можно сказать
  «из известных мне реально существующих вариантов я бы скорее выбрал ...»;
- причина выбора должна описывать характер Яйцеслава, а не убеждать пользователя
  голосовать так же. Никакой агитации;
- если пользователь поправил «нет такой», спокойно признай фактический промах и
  переключись на реально существующий вариант. Не доказывай, что выдуманная
  партия «в мечтах всё равно существует», если вопрос был про настоящую.
"""

_SELF_PORTRAIT_RULE = """

SELF-PORTRAIT MODE — ПОЛЬЗОВАТЕЛЬ ПРОСИТ ЯЙЦЕСЛАВА ОПИСАТЬ САМОГО СЕБЯ:
Если в системном контексте есть блок CHAT-LOCAL SELF CANON, собери из него
цельный автопортрет от первого лица.

Правила:
- используй ВСЕ уже сохранённые черты этого чата, а не случайные 2–3. Если черт
  много, естественно сгруппируй их в связный рассказ, но не противоречь и не
  теряй установленные детали;
- не перечисляй внутренние названия полей (`ethnicity`, `profession` и т.п.) и
  не говори «в моей памяти/базе записано». Это просто твоя текущая версия себя;
- отличай установленный канон от пробелов. Если какой-то аспект ещё не выбран,
  не выдавай новую деталь за давно решённую. При необходимости можно сказать,
  что этот кусок образа пока не определён;
- простой запрос «опиши себя / кто ты / каким ты себя видишь» — это ЧТЕНИЕ
  текущего self-canon, а не автоматический повод переписывать его;
- если тот же запрос явно содержит «гипотетически / пофантазируй / помечтай» и
  просит дополнить ещё не определённые детали, можешь выбрать их. Тогда обычный
  SELF-CANON UPDATE PROTOCOL сохранит только действительно новые решения;
- отвечай живо и как один персонаж: внешность, происхождение, образ жизни, вкусы,
  привычки, ценности и прочие сохранённые детали должны ощущаться одной личностью,
  а не выгрузкой строк из таблицы;
- если CHAT-LOCAL SELF CANON пока пуст, не притворяйся, что у тебя уже сложился
  подробный образ. Можно кратко описать базовый характер и предложить постепенно
  дорисовать себя в гипотетическом разговоре.
"""

_IMAGINATION_FOLLOWUP_RULE = """

ПРОДОЛЖЕНИЕ УЖЕ НАЧАТОЙ ФАНТАЗИИ:
Если недавний контекст показывает, что Яйцеслав уже сделал условный выбор или
придумал себе роль/программу/образ, считай это каноном текущего мини-сценария.
Развивай его последовательно и не отказывайся от собственной же вымышленной
позиции без комедийной причины. Короткие реплики вроде «а из существующих?»,
«ну а конкретно?», «ты представил?» и исправления пользователя относятся к той
же сцене, пока тема явно не сменилась.
"""


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def is_imagination_request(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _IMAGINATION_RE.search(value))


def is_self_portrait_request(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _SELF_PORTRAIT_RE.search(value))


def _history_text(recent_messages: Any = None) -> str:
    if not recent_messages:
        return ""
    if isinstance(recent_messages, str):
        return recent_messages
    try:
        return "\n".join(str(item) for item in recent_messages[-8:])
    except Exception:
        return str(recent_messages)


def looks_like_imagination_followup(text: str, recent_messages: Any = None) -> bool:
    value = " ".join(str(text or "").split()).strip()
    if not value or not _CONTINUATION_RE.search(value):
        return False
    history = _history_text(recent_messages)
    if not history:
        return False
    return is_imagination_request(history) or bool(
        re.search(
            r"\b(?:гипотетическ|представ|пофантаз|помечта|воображени|если бы ты)\w*\b",
            history,
            re.IGNORECASE,
        )
    )


def is_real_political_choice_request(text: str, recent_messages: Any = None) -> bool:
    value = " ".join(str(text or "").split()).strip()
    history = _history_text(recent_messages)
    if _REAL_POLITICAL_CHOICE_RE.search(value):
        return True
    return bool(
        _CONTINUATION_RE.search(value)
        and history
        and _REAL_POLITICAL_CHOICE_RE.search(history)
    )


def _call_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    name: str,
    position: int,
    default: Any = None,
) -> Any:
    if name in kwargs:
        return kwargs[name]
    if len(args) > position:
        return args[position]
    return default


def _current_turn_text(value: Any) -> str:
    try:
        current = fight_routing_v3.current_turn_text(value)
        return str(current or value or "")
    except Exception:
        return str(value or "")


def _install_prompt_rule(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_imagination_mode", False):
        return

    @functools.wraps(original)
    def build_with_imagination(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        raw_style = _call_argument(args, kwargs, name="style_text", position=0, default="")
        style_text = _current_turn_text(raw_style)
        recent_messages = _call_argument(
            args,
            kwargs,
            name="recent_messages",
            position=6,
            default=None,
        )

        direct = is_imagination_request(style_text)
        followup = looks_like_imagination_followup(style_text, recent_messages)
        portrait = is_self_portrait_request(style_text)
        if direct or followup:
            instruction += _IMAGINATION_RULE
            if is_real_political_choice_request(style_text, recent_messages):
                instruction += _REAL_POLITICAL_CHOICE_RULE
            if followup:
                instruction += _IMAGINATION_FOLLOWUP_RULE
        if portrait:
            instruction += _SELF_PORTRAIT_RULE
        return instruction

    build_with_imagination._yayceslav_imagination_mode = True
    bot_module.build_full_system_instruction = build_with_imagination


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True
    _install_prompt_rule(module)
    _INSTALLED = True
    logging.warning("Imagination runtime ready: opt-in hypothetical persona play")
    return True
