# ROADMAP: Яйцеслав-бот

> Постоянная дорожная карта production-ветки `feature/human-yayceslav-v2`.
>
> Последнее концептуальное обновление: 2026-08-25.

---

# 0. Правила ведения roadmap

Статусы:

- ✅ **ГОТОВО** — код реализован, тесты зелёные; если задача требует живого поведения, отдельно отмечается live validation.
- 🟡 **НАБЛЮДЕНИЕ / ТЮНИНГ** — функция уже работает, но её нужно оценить на реальных диалогах.
- 🟣 **РУЧНАЯ ПРОВЕРКА** — нужна фактическая проверка в Telegram/Railway.
- ⬜ **BACKLOG** — потенциальная следующая работа, не обязательная для текущего production.
- ⛔ **НЕ ДЕЛАТЬ БЕЗ ОТДЕЛЬНОГО РЕШЕНИЯ**.

После существенного изменения поведения обновлять этот файл и фиксировать production SHA/PR.

---

# 1. Главная концепция

**Яйцеслав — постоянный участник группового чата со своим характером, а не набор slash-команд.**

Ключевой принцип поведения в группе:

1. серьёзность/безопасность, если контекст этого требует;
2. постоянная репутация и симпатия к конкретному человеку;
3. реальная история отношений и уровень знакомства;
4. текущий контекст сообщения/голоса/кружка;
5. характер Яйцеслава, грубость, mood и случайный юмор — только финальная приправа.

Нейтральный человек по умолчанию получает сдержанный нейтрально-позитивный тон. Мат допустим как эмоция про ситуацию, но не как случайная атака на человека. Старый знакомый с реальной историей срачей может получить игровой callback, но не бесконечную автоматическую агрессию.

---

# 2. Архитектурные ограничения — НЕ ЛОМАТЬ

1. Railway Free Tier / маленький runtime budget.
2. SQLite — компактное постоянное состояние.
3. Только bounded RAM state с TTL/лимитами.
4. Никакого Redis без отдельной необходимости.
5. Никакой vector DB/embeddings-memory по умолчанию.
6. Не хранить постоянные voice transcripts.
7. Не хранить бесконечную сырую историю чатов.
8. Не запускать LLM-summary на каждом сообщении.
9. Не добавлять browser automation для обычного поиска.
10. Search enrichment держать ограниченным.
11. Не добавлять отдельный Gemini-вызов только ради определения тона, если сигнал уже есть в профиле/контексте.
12. Никаких бесконечных background loops ради характера/памяти.
13. SQLite-миграции только неразрушительные.
14. Секреты/API keys — только Railway Variables или локальный `.env`.

Текущие лимиты памяти:

- group short-term memory: до ~30 сообщений, горизонт ~15 минут;
- private short-term memory: до ~40 сообщений, горизонт ~15 минут;
- episodic member notes: до 12 на человека, TTL 120 дней;
- chat digests: до 12 на чат, TTL 14 дней;
- никаких постоянных полных транскриптов переписки.

---

# 3. Сводная панель

| Блок | Статус | Что осталось |
|---|---|---|
| Voice 2.0 | ✅ | периодический live smoke |
| Search 2.0 / current date / bare search | ✅ | live regression watch |
| Natural-language command router | ✅ | отслеживать false positives и добавлять реальные варианты |
| Public slash-menu cleanup | ✅ | ничего обязательного |
| Stickers tuning / own-pack routing | ✅ | live частотность и антиспам |
| Relationship/reputation/affinity | ✅ | live тюнинг порогов при необходимости |
| Unified relationship-first tone | ✅ | проверить на реальных людях/кружках/голосе |
| Video-circle proactive comments | ✅ | live sample из серии кружков |
| Bounded memory/digest architecture | ✅ | recap после restart должен честно говорить об отсутствии данных |
| Runtime hotfix cleanup/bootstrap | ✅ | ничего обязательного |
| Railway deployment observability | 🟣 | нет прямого Railway connector в текущем окружении |
| Большой рефакторинг `bot.py` | ⬜ | только если появится реальная цена поддержки |
| Owner diagnostics / health view | ⬜ | полезный будущий инструмент |

---

# 4. ✅ Уже реализовано

## 4.1 Voice 2.0

- structured schema для решения по входящему voice/audio;
- transcript живёт только внутри текущего запроса;
- transcript не пишется в SQLite/chat memory;
- явная просьба `ответь голосом` детектируется детерминированно;
- malformed/partial JSON не показывается пользователю;
- voice web-search поддерживается;
- group member profile передаётся в voice path;
- voice/audio service prompt не должен восприниматься как агрессивные слова пользователя;
- обычное voice/audio в группе сохраняет существующий address gate.

Связанные production PR: #11, #12, #13.

## 4.2 Search 2.0

- enrichment ограничен максимум 2 страницами;
- общий fetched text около 8k chars;
- никакого browser session;
- bare `проверь в интернете` может восстановить предыдущую тему;
- `какой сейчас год/дата` берёт процессное время МСК и не тратит web-search;
- search flow не должен заставлять человека заново формулировать уже понятную тему.

Связанные production PR: #10, #12.

## 4.3 Natural-language router

High-confidence фразы могут запускать действие в группе без `/command`, без mention и без reply.

Поддерживаемые классы и примеры:

### Recap

- `че было в чате?`
- `что было в чате?`
- `о чем базар был?`
- `про что вы тут базарили?`
- `что сегодня обсуждали?`
- `о чем мы сегодня разговаривали?`
- `о нифига вы тут насрали в чат`
- `что за движ тут?`
- `введите в курс дел`
- `перескажи чат`

### Roast

- `прожарь @nick`
- `прожарь Серегу`
- `подколи @nick`
- `прожарка для @nick`

### Judge / debate / argument

- `разрули спор`
- `кто тут прав?`
- `вынеси вердикт`
- `аргументы за и против`
- `разбери с двух сторон`
- `приведи аргумент`

### Fact check

- `правда или пиздеж`
- `это правда или нет?`
- `факт или баян`
- `проверь утверждение`

### Group stats / reports

- `кто тут главный болтун`
- `топ болтунов`
- `итоги недели`
- `что было за неделю`
- `кому награды дали`

Правило: двусмысленная обычная болтовня не должна будить бота через этот router.

Связанный production PR: #14.

## 4.4 Публичное Telegram menu

Из обычного группового slash-menu скрыты naturalized actions:

- `/roast`
- `/judge`
- `/argument`
- `/debate`
- `/leaderboard`
- `/awards`

Handlers НЕ удалены и остаются hidden fallback. Owner menu остаётся полным.

Production merge SHA блока menu cleanup: `ee568915e3d508eb6747b15e015e1e776d841916`.

## 4.5 Stickers

- own-pack standalone sticker в группе не должен сам по себе будить бота;
- own-pack sticker как reply к Яйцеславу может вызвать реакцию;
- foreign packs не входят в own-pack behavior;
- вероятность согласованных sticker-events поднята на +5 процентных пунктов;
- background cap остаётся ограниченным;
- direct-question chance ограничен;
- post-text tag chance ограничен;
- shared anti-spam остаётся, включая максимум 3 stickers/hour.

Целевой текущий tuning:

- background cap: 8%;
- direct question: 12%;
- post-text tag: 13%;
- aggressive-event cap: 6%;
- probability bump: +5 pp.

Связанный production PR: #11.

## 4.6 Relationship / reputation / affinity

Бот уже имеет и использует:

- lifetime reputation `-100..+100`;
- positive affinity / sympathy;
- relationship/familiarity levels;
- positive streak/history;
- negative-event/history signals;
- bounded episodic notes;
- recent short-term context;
- chat-wide mood как вторичный слой.

Смысл: текущая формулировка не должна полностью обнулять отношения, а отношения не должны полностью игнорировать текущий контекст.

## 4.7 Unified relationship-first tone

Production PR: #16.

Production merge SHA: `cb802bfd0b505fb6b3d0ca63a0ff9c0f2669595c`.

Основная иерархия:

`serious/safety -> reputation+affinity -> relationship history -> current content -> character/mood`

Режимы поведения включают:

- neutral;
- neutral familiar;
- friendly;
- trusted;
- wary;
- feuding familiar.

Правила:

- neutral/new: сдержанно, спокойно, нейтрально-позитивно;
- positive/friendly: живее, теплее, допускается добрый стёб;
- old familiar: локальные callback-мемы допустимы, если реально есть история;
- recurring feud: один короткий игровой упреждающий подкол допустим без злобы, затем ответ по содержанию;
- один неприятный эпизод не должен превращать человека в постоянного врага;
- serious context всегда подавляет старый бантер;
- generic roughness/mood не могут перевернуть выбранное отношение.

Никаких новых таблиц, background workers, transcript storage или дополнительных Gemini-вызовов этот слой не добавляет.

## 4.8 Proactive video circles

Текущая модель:

- если кружок не адресован боту, остаётся **20% chance** проактивного комментария;
- shared intervention budget/антиспам остаётся;
- репутация НЕ меняет сам 20% gate;
- репутация/симпатия/история меняют тон реакции после срабатывания gate;
- сервисный prompt кружка нейтрализуется до personality/aggression logic;
- проактивный кружок не считается ещё одним прямым вызовом бота;
- реакция content-first, а не оценка личности автора;
- нейтральный человек + отпуск -> доброжелательная зависть/кайф;
- нейтральный человек + пробки/работа/усталость -> признать проблему и поддержать;
- жалоба на третьих лиц не считается атакой на Яйцеслава;
- внешность/голос/автор не становятся мишенью без реального контекста;
- serious media побеждает бантер;
- для реального старого партнёра по срачам допустим лёгкий callback.

## 4.9 Runtime cleanup

Удалён старый delayed `runtime_hotfix.py` с readiness thread.

Теперь first-class runtimes:

- date grounding;
- search context recovery;
- Voice 2.0;
- sticker tuning;
- social priority;
- Search enrichment;
- chat digest;
- natural router.

Bootstrap order явный и тестируется.

Production CI: Python 3.12 + 3.13.

---

# 5. 🟣 Live validation — это главный оставшийся этап

## 5.1 Relationship-first tone

Проверить в реальной группе несколько разных профилей:

- новый/нейтральный человек + обычное сообщение;
- положительный знакомый + обычное сообщение;
- старый знакомый + обычное сообщение;
- знакомый с повторяющейся историей срачей + нейтральное сообщение;
- реальный прямой наезд на Яйцеслава;
- серьёзная просьба от человека с плохой историей.

Ожидается:

- neutral users не получают случайный personal attack;
- friendly/trusted users получают более тёплую фамильярность без лести;
- recurring-feud users могут получить короткий callback, но не бесконечный конфликт;
- actual hostility получает пропорциональную защиту;
- serious/help context полностью подавляет pointless banter.

## 5.2 Кружки — проверять серией, не одним сообщением

Поскольку gate = 20%, один кружок ничего не доказывает.

Проверить серию реальных video notes:

- частота реакции примерно соответствует 20% + shared cap;
- neutral vacation content -> neutral-positive;
- traffic/work fatigue -> сочувствие/поддержка;
- нет необъяснимых оскорблений нейтрального автора;
- relationship history влияет на стиль, но не вытесняет содержание;
- serious circle не получает comedy-first ответ.

## 5.3 Stickers

Наблюдать примерно 20-50 релевантных возможностей:

- стало заметно чаще, чем до +5pp;
- max 3/hour действительно защищает от спама;
- aggressive stickers не доминируют в серьёзном контексте;
- standalone own-pack group sticker остаётся ignored, если не адресован боту.

## 5.4 Voice regression smoke

Периодически проверить:

- обычное короткое voice -> чистый ответ;
- `ответь голосом...` -> именно voice message;
- voice web search -> clean answer без JSON;
- group voice/audio без обращения к боту остаётся ignored согласно address gate.

## 5.5 Natural router false-positive watch

Следить за обычным разговором.

Если конкретная фраза ложно будит бота — ужесточать только соответствующий regex/pattern, не ослаблять всю систему.

## 5.6 Recap после restart/autodeploy

Short-term RAM memory намеренно исчезает после restart.

Бот НЕ должен делать вывод `мы сегодня не разговаривали`, если у него просто нет данных.

Правильная семантика при отсутствии контекста: честно сказать, что после restart/истечения RAM-окна он не может надёжно восстановить этот период.

---

# 6. 🟡 Near-term tuning — только по реальным наблюдениям

Не менять заранее. Делать только если live Telegram показывает проблему:

- пороги relationship bands;
- критерий recurring feud;
- вес positive affinity против lifetime reputation;
- wording neutral/friendly/trusted instruction;
- конкретные natural-language aliases;
- false-positive regex;
- sticker chances/caps;
- phrasing proactive-circle instruction;
- digest trigger/TTL, если реальная группа показывает неудобство.

Предпочтение: deterministic config/prompt change без дополнительного Gemini call.

---

# 7. ⬜ Backlog — полезно, но не нужно для текущего production

## 7.1 Owner diagnostics

Сделать owner-only диагностику, которая показывает без раскрытия внутреннего prompt:

- текущий relationship band конкретного участника;
- reputation/affinity/familiarity summary;
- сколько short-term memory/digests сейчас доступно;
- rate-limit/intervention counters;
- причину, почему бот выбрал neutral/friendly/wary/feuding-familiar.

Это полезнее, чем гадать по одному ответу бота.

## 7.2 Production health/status

Owner-only compact status:

- current production commit;
- DB accessible;
- memory sizes;
- digest counts;
- recent error counters;
- search/voice availability;
- latest scheduler state.

Не добавлять heavy monitoring infrastructure.

## 7.3 Автоматическая regression matrix социальных сценариев

Набор сценариев типа:

- neutral + vacation;
- neutral + traffic complaint;
- trusted + success;
- feud familiar + neutral greeting;
- feud familiar + serious help request;
- neutral + direct insult;
- proactive circle neutral;
- voice neutral;

Цель: будущие prompt changes не должны случайно возвращать unprovoked toxicity.

## 7.4 Декомпозиция огромного `bot.py`

Старый roadmap предлагал полный handlers/services/repositories refactor.

Текущая позиция: **не делать большой рефакторинг ради красоты**. Делать по частям только там, где реально мешает сопровождению.

Возможные направления:

- `command_registry.py`;
- repositories для DB areas;
- services для Gemini/search/files/voice;
- typed request context для `ask_gemini`;
- единый permission/owner-only helper.

Но это backlog, а не текущий приоритет.

## 7.5 Telegram command menu automation

Публичное меню уже управляется кодом/scopes. Дополнительная автоматизация нужна только если реальная эксплуатация выявит рассинхрон.

## 7.6 Дополнительные natural aliases

Добавлять только варианты, которые реально пишут люди, а не бесконечно раздувать regex заранее.

---

# 8. Старые roadmap-задачи, которые остаются как технический backlog

Следующие идеи из старой версии roadmap НЕ потеряны, но больше не являются blockers текущего production:

- единый `command_registry.py`;
- дальнейшее деление `bot.py` на handlers/services/repositories;
- больше repository abstractions для SQLite;
- единый owner-only/permission слой;
- расширение тестовой матрицы команд и миграций;
- Gemini model через config/env, если потребуется переключаемость;
- ImageProvider abstraction без обязательного включения image generation;
- дополнительные мемные/voice packs только если это реально улучшает персонажа.

Старые пункты про обязательный быстрый список из множества slash-команд устарели: стратегия продукта теперь наоборот — **natural conversation first, slash fallback second**.

---

# 9. ⛔ Явные non-goals

Не внедрять без отдельного решения владельца:

- Redis;
- vector DB;
- embeddings-memory всего чата;
- unlimited chat history;
- permanent voice transcripts;
- хранение документов/изображений в persistent memory;
- browser automation;
- обычный поиск на 10+ страниц;
- LLM-summary на каждое сообщение;
- unbounded in-memory dictionaries;
- high-frequency background workers;
- сложную microservice-архитектуру для одного Telegram bot;
- дополнительные Gemini calls только ради mood/tone classification.

---

# 10. Production milestones

Последние ключевые production milestones:

- PR #10 — smart tools: natural router foundation, bounded search enrichment, chat digest;
- PR #11 — Voice 2.0 + sticker tuning;
- PR #12 — runtime hotfix cleanup, first-class date/search/voice guards;
- PR #13 — deterministic explicit voice reply fix;
- PR #14 — расширение разговорных no-mention triggers;
- PR #15 — public slash-menu cleanup;
- PR #16 — unified relationship-first tone for text, voice/audio and circles.

Текущий зафиксированный production merge после PR #16:

`cb802bfd0b505fb6b3d0ca63a0ff9c0f2669595c`

CI после merge: Python 3.12 + 3.13 — success.

---

# 11. Что делать дальше

**Главная разработка текущего этапа завершена.**

Следующая фаза:

1. дождаться/подтвердить Railway autodeploy;
2. использовать бота в реальном чате;
3. собрать конкретные примеры странного поведения;
4. тюнить только доказанные проблемы;
5. после стабилизации перейти к owner diagnostics / regression scenarios, если они действительно нужны.

Не начинать новый тяжёлый архитектурный блок, пока live validation не покажет, что он нужен.
