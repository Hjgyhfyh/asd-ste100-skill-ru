#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Детерминированный линтер структурных правил УТР (SKILL.md).

Проверяет только правила, которые можно проверить без словаря ASD.
Намеренно НИКОГДА не отмечает осторожность и модальность («может», «возможно»,
«иногда», «вероятно»): уверенность автора — это содержание, а линтер, который
выдавливает оговорки, заставит переписывать утверждения.

Использование:
    ste-lint.py ФАЙЛ [ФАЙЛ ...]
    echo "текст" | ste-lint.py [--json]
    ste-lint.py --baseline 5 ФАЙЛ        # успех, пока жёстких нарушений не больше 5
    ste-lint.py --disable точка-с-запятой,длинное-предложение ФАЙЛ
    ste-lint.py --selftest

Код возврата 1, когда жёстких нарушений больше --baseline (по умолчанию 0).
Рекомендательные находки (страдательный залог, причастный оборот) прогон не роняют.

Это перенос scripts/ste-lint.py из англоязычного навыка danyuchn/asd-ste100-skill.
Список правил заменён на русский: точки с запятой, канцелярит, отглагольные
существительные, рекламные прилагательные, многосоюзность, синонимная ротация,
длина предложения, висячий союз, плюс страдательный залог и причастия как
рекомендательные.
"""
import json
import os
import bisect
import re
import sys

# За регулярными выражениями стоит эвристика, а не разбор грамматики.
# Правила цепочки существительных нет: ему нужна разметка частей речи.
MAX_WORDS = 20  # потолок для описаний; для инструкций ориентир 15

# Слова, которые почти всегда означают одно и то же действие.
# Основы, а не словоформы: в русском окончания меняются, основа остаётся.
# Смысловые различия («ошибка» / «сбой» / «отказ») сюда НЕ входят: их
# смешение меняет утверждение, поэтому повторять слово лучше, чем чередовать.
SYNONYM_GROUPS = [
    ("удал", "стер|сотр|стёр", "снес"),
    # «показыва|покаж», а не «показ»: основа «показ» захватывала «показатель» —
    # метрику, которая ничего общего не имеет с глаголом «показывать».
    ("показыва|покаж", "отображ"),
    ("нач", "приступ"),
    ("исправ", "почин"),
    ("измен", "поменя", "передел"),
    ("останов", "прекрат"),
    ("законч", "заверш", "оконч"),
    ("отправ", "отсыл"),
    # У глагола «найти» три чередующиеся основы: «найд» в будущем и прошедшем
    # несовершенном (найдёт, найти), «наш» в прошедшем совершенном (нашёл,
    # нашла) и «нах» в настоящем (находит, нахожу). Голая «наш» не годится:
    # это ещё и притяжательное местоимение, оно есть почти в каждом тексте.
    ("най[дт]|наш[еёо]|нашл|нах", "обнаруж", "выяв"),
    ("использу", "примен"),
]

# Слова, которые по форме совпадают с причастием, но прилагательными и
# существительными не являются. Регулярка работает по кускам основы, поэтому
# без этого списка она ловит «данные», «временные», «следующий».
_NOT_A_PARTICIPLE = (
    r"данны\w*|временн\w*|следующ\w*|входящ\w*|исходящ\w*|встроенн\w*"
    r"|текущ\w*|показател\w*|готовы|готов\w*|новы|новый|первы|первый"
    r"|лучш\w*|различн\w*|основны\w*|общи\w*|полны\w*|собственны\w*"
    r"|длинн\w*|постепенн\w*|единственн\w*|кратн\w*|положит\w*"
)

# Слова, которые по форме совпадают с причастием прошедшего времени, но
# прилагательными и существительными не являются. Без этого списка правило
# страдательного залога ловило оговорки: «Вероятно», «причина», «обычно»
# оканчиваются так же, как «удалён», и в сочетании с творительным падежом
# давали вывод «возможный страдательный залог» там, где его нет.
_NOT_A_PASSIVE = (
    # Оговорки и безличные конструкции. Оканчиваются так же, как причастие
    # прошедшего времени, но причастиями не являются.
    r"причи[нануемой]*|возможн\w*|вероятн\w*|скорее|обычн\w*|вручн\w*|точно"
    r"|нужн\w*|важн\w*|обязат\w*|желат\w*|примерн\w*|наконец|конечн\w*"
    r"|случайн\w*|регулярн\w*|постоянн\w*|полностью|частично|отдельно"
    r"|готов\w*|должен\w*|способ\w*"
    # Связка с прилагательным: «был свободен» — это не страдательный залог.
    # Подлежащее остаётся на месте, исполнителя нет, и называть его некого.
    # Основы пишемся БЕЗ «н»: мужской род краткой формы — это «свобод»+«ен»,
    # а не «свободн», поэтому «свободн\w*» не ловил «свободен» вовсе.
    r"|свобод\w*|актив\w*|очевид\w*|замет\w*|стабил\w*|уверен\w*"
    r"|доступ\w*|недоступ\w*|извест\w*|неизвест\w*|видим\w*|виден"
    r"|цел|жив|прав|важен|важн|равен|равн|болен|сильн|слаб|молод|чист|пуст"
    r"|прост|полн|слож\w*|ясен|ясн|точен|верен|долг|нужно|нельзя|можно"
    # Безличные на -но: «трудно сказать», «видно, что», «непонятно, что».
    r"|нетрудно|обидно|немного|странно|правильно|достаточно|реально|абсолютно"
    r"|окончательно|исключительно|минимально|максимально|оптимально"
    r"|формально|основном|жаль|пора|следует|труд\w*|невозмож\w*"
    r"|маловероят\w*|непонят\w*|видно|нов|стар|готов\w*|способ\w*"
)

# Причастные основы. Окончания подобраны так, чтобы обычные прилагательные
# не попадали в правило. Опасные окончания отброшены: одиночная «т» ловила бы
# порядковые числительные («третий», «четвёртый»), а «ш» — «лучший», «хороший».
PARTICIPLE = (r"(?<![а-яё])(?!(?:" + _NOT_A_PARTICIPLE + r")\b)"
              r"[а-яё]+(?:нн|енн|атн|уч|ач|ящ|ащ|ющ|ающ|ивш|ующ)"
              r"(?:ый|ий|ая|яя|ое|ее|ые|ие)\b")

# Короткие причастия прошедшего времени: «удалён», «выполнена», «запущен».
# За ними обязательно идёт падежное окончание, поэтому «новый» и «первый»
# сюда не попадают.
PASSIVE_SHORT = (r"(?<![а-яё])(?!(?:" + _NOT_A_PASSIVE + r")\b)[а-яё]{3,}"
                 r"(?:нн|енн|н|ен|ан|ят|атн|уч|ащ|ящ|ющ|ающ)"
                 r"(?:а|у|ы|и|о|е|ом|ем|ого|ему|ах|ам)?\b")
PASSIVE_ANY = (r"(?:" + PARTICIPLE + r"|" + PASSIVE_SHORT + r")")

# Окончания глагола для правила отглагольных существительных. Список явный,
# а не `\w*`: иначе под правило попадали причастия («выполненных операций»)
# и страдательные формы («проверка была выполнена»).
#
# Прошедших времён здесь НЕТ намеренно. «Выполнил проверку» и «Провёл
# проверку» — уже глагольные обороты, действие не спрятано в существительном.
# Правило должно требовать инфинитив, повелительное или настоящее время.
VERB_ENDING = (r"(?:ться|сь|ся|ется|ится|яется|ается|уется|ть|сти"
               r"|ет|ит|ёт|и|ем|им|ут|ют|ите|ете|ыте)")

# Основы глаголов номинализации. Без чередований (провед|провел, осуществл|осуществ)
# правило молчало на формах вроде «Провёл проверку» и «Осуществите проверку».
VERB_STEM = (r"(?:осуществ|выполн|провед|провод|провес|произвед"
             r"|производ|сдела|настро|обработа|использу|окаж|оказ|реализу)")

# Окончание обязательно: иначе основа съедает всё слово целиком, и прошедшее
# время («Провёл проверку») начинает совпадать. Но «выполненных операций» и
# «была выполнена» под правило не попадают: там хвост не совпадает с окончанием,
# а дальше обязателен пробел с именем.
VERB_TAIL = r"\w*" + VERB_ENDING

RULES = [
    ("точка-с-запятой", "advisory-free",
     re.compile(r";"),
     "STE запрещает точку с запятой (правило 8.1). Разбей на два предложения."),
    ("рекламное-прилагательное", "advisory-free",
     re.compile(r"\b(?:уникальн\w*|безупречн\w*|инновационн\w*|революционн\w*"
                r"|мгновенн\w*|идеальн\w*|бесшовн\w*|сверхскоростн\w*"
                r"|невероятн\w*|потрясающ\w*|экстремальн\w*"
                r"|самый\s+(?:лучший|быстрый|мощный|простой|надёжный|удобный|красивый)"
                r"|на\s+100\s*%)\b", re.I),
     "Рекламное прилагательное. Удали или замени измерением, которое даёт право на утверждение."),
    ("канцелярит", "advisory-free",
     re.compile(r"(?:\bв\s+целях\b|\bв\s+связи\s+с\b|\bявляет(?:ся|ются)\b"
                r"|\bимеет\s+место\b|\bв\s+настоящее\s+время\b"
                r"|\bна\s+сегодняшний\s+день\b|\bданн(?:ый|ая|ое|ого|ому)\b|данным\s+образом"
                r"|\b(?:необходимо|следует|стоит|важно)\s+отметить\b"
                r"|\bиными\s+словами\b|\bтаким\s+образом\b|\bотносится\s+к\s+числу\b"
                r"|\bне\s+представляет\s+собой\b|\bприня(?:ть|тие|тия)\s+мер\b"
                r"|\bосуществля(?:ет|ется|ть)\b"
                r"|\bпроизвод(?:ит|ится)\s+(?:проверк|настройк|анализ|оценк|расчёт|расчет|действ|операц)"
                r"|\bоказ(?:ать|ывает|ывается|ал)\s+(?:помощь|поддержк|содействи)\w*)", re.I),
     "Канцелярский оборот. Возьми обычные слова: «для», «есть», «происходит», «этот»."),
    ("отглагольные-существительные", "advisory-free",
     re.compile(r"\b" + VERB_STEM + VERB_TAIL + r"\s+"
                r"(?:необходимую\s+|первичную\s+|полную\s+)?"
                r"(?:проверк\w*|настройк\w*|конфигурац\w*|контрол\w*|тестирован\w*"
                r"|анализ\w*|оценк\w*|расчёт\w*|расчет\w*|операц\w*|помощь|поддержк\w*"
                r"|содействи\w*|мер[ыау])\b"
                r"|\b(?:проведение|осуществление|выполнение|оказание|принятие"
                r"|настройка|обработка|реализация)\s+(?:проверк|настройк|контрол|анализ"
                r"|оценк|расчёт|расчет|помощ|поддержк|содействи|мер)\w*", re.I),
     "Действие заморожено в существительном. Верни глагол: «проверь», а не «выполни проверку»."),
    ("предложный-отглагольный", "advisory",
     # Предлоги, где оборот действительно стоит переписать в глагол.
     # «после», «перед», «во время», «в случае», «в результате» дают
     # естественные сочетания вроде «после проверки» или «перед
     # использованием». Правило ругалось ровно на то, что само же
     # называло обычным, поэтому эти предлоги убраны.
     re.compile(r"\b(?:при|для|в ходе)"
                r"\s+[а-яё]{3,}(?:ние|ния|нию|нием|ки|ке|ку|ках)\b", re.I),
     "Отглагольное существительное в предложном падеже: «при обработке». "
     "Такие обороты прячут действие за существительным, и вернуть глагол "
     "обычно читается яснее. Правило рекомендательное."),
    ("страдательный-залог", "advisory",
     # Во второй ветке запятая запрещена внутри окна: иначе любая фраза
     # вида «Видно, что нет связи с сервером» находит и «оговорку», и «агента».
     re.compile(r"\b(?:был|была|было|были|будет|будут|будет\s+быть|быть|может\s+быть|мог\s+быть"
                r"|могут\s+быть|должен\s+быть|должна\s+быть|должно\s+быть|должны\s+быть)"
                r"\s+" + PASSIVE_ANY + r"\b"
                r"|\b" + PASSIVE_ANY + r"\b[^.,;:!?\n]{0,40}?\b"
                r"(?:агентом|инструментом|системой|пользователем|сервером|клиентом"
                r"|ботом|скриптом|модулем|службой)\b", re.I),
     "Возможный страдательный залог. Назови исполнителя и поставь глагол в активный залог, "
     "если только исполнитель действительно неизвестен или не важен."),
    ("причастный-оборот", "advisory",
     re.compile(r"(?<!был\s)(?<!была\s)(?<!было\s)(?<!были\s)\b" + PARTICIPLE + r"\b", re.I),
     "Причастие прячет исполнителя и превращает действие в состояние. Верни глагол."),
]

CODE_FENCE = re.compile(r"^(?P<mark>`{3,}|~{3,})(?P<info>.*)$")
INLINE_CODE = re.compile(r"`[^`]*`")
LIST_ITEM_START = re.compile(
    r"^(?P<indent> *)(?P<marker>[-*+]|[0-9]+[.)])(?P<gap> +)(?P<body>.*)$"
)
# Всё, что не является текстом для проверки: адреса, комментарии, разметка.
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# Жирное и курсив. Сами звёзды убираются, а текст внутри остаётся: иначе
# «правило о модальности.** Более ранняя» не разрывалось на два предложения,
# и линтер считал их одним предложением на 21 слово.
EMPHASIS_MARK = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
LINK_DESTINATION = re.compile(r"\]\([^)]*\)|<[^ >]*:[^ >]*>|\S+:\S+")
# Отступ в четыре и более пробела — блок кода с отступом по CommonMark.
INDENTED_CODE = re.compile(r"^(?: {4}|\t)\S")
# Висячий союз в конце пункта списка.
CONJUNCTION_END = re.compile(r"\b(?:и|или|а|но|же|бы)\s*$", re.I)
# Сочинительные союзы для подсчёта связности предложения.
COORDINATING = re.compile(r"\b(?:и|или|а|но)\b", re.I)
MAX_COORDINATING = 3
# Подчинительные союзы и относительные местоимения: русский эквивалент
# цепочки англоязычных придаточных предложений. Два и больше в одном
# предложении — признак «спрятанного» условия.
#
# Составные союзы считаются ОДНИМ придаточным: «несмотря на то что» — это
# один союз, а не два. Считать их по частям означало бы ругаться на
# совершенно обычную русскую конструкцию.
SUBORDINATING = re.compile(
    r"(?:котор(?:ый|ая|ое|ые|ых|ому|ой|ыми|ое)\b|чтобы\b"
    r"|\b(?:что|если|когда|пока|поскольку|так\s+как|того\s+как|хотя|ежели)\b"
    r"|\bв\s+том\s+случае\b|\bвследствие\s+того\s+что\b|\bнесмотря\s+на\s+то\s+что\b"
    r"|\bв\s+случае\b|\bввиду\s+того\s+что\b|\bпо\s+мере\s+того\s+как\b)", re.I)
MAX_SUBORDINATING = 2
TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def strip_noise(line):
    """Убрать то, что не является прозой: код, комментарии, адреса.

    Всё заменяется пробелами той же длины, иначе номера колонок в находках
    поедут и редактор подсветит не то место.
    """
    def blank(match):
        return " " * len(match.group(0))

    line = INLINE_CODE.sub(blank, line)
    line = HTML_COMMENT.sub(blank, line)
    # у выделения убираются только звёзды, текст внутри остаётся
    line = EMPHASIS_MARK.sub(
        lambda m: " " * (2 * len(m.group(1)) + len(m.group(2))), line)
    return LINK_DESTINATION.sub(blank, line)


def _stem_re(base):
    r"""Слово по основе: окончания в русском меняются, основа остаётся.

    Основа может содержать чередование (`стер|сотр`), поэтому она оборачивается
    в группу, а `\w*` появляется после всей группы, а не после её первого
    варианта.
    """
    return re.compile(r"\b(?:" + base + r")\w*\b", re.I)


def _leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


def _is_list_continuation(line, content_indent):
    if not line.strip():
        return True
    if LIST_ITEM_START.match(line):
        return False
    return _leading_spaces(line) >= content_indent


def _split_table_row(line):
    """Вернуть обрезанные ячейки таблицы и их колонки в исходном тексте.

    Вертикальная черта должна разделять хотя бы две ячейки. Экранированные черты
    остаются внутри ячейки. Это обычная разметка Markdown-таблицы, без вложенных
    списков и без ленивого продолжения.
    """
    left = len(line) - len(line.lstrip())
    right = len(line.rstrip())
    content = line[left:right]
    if "|" not in content:
        return None
    if content.startswith("|"):
        content = content[1:]
        left += 1
    if content.endswith("|"):
        content = content[:-1]
    raw_cells = re.split(r"(?<!\\)\|", content)
    if len(raw_cells) < 2:
        return None

    cells = []
    column = left
    for raw_cell in raw_cells:
        leading = len(raw_cell) - len(raw_cell.lstrip())
        cells.append((raw_cell.strip(), column + leading))
        column += len(raw_cell) + 1
    return cells


def _markdown_table_cells(lines):
    """Сопоставить обычные строки Markdown-таблицы их прозаическим ячейкам.

    Разделительная строка служит якорем распознавания, поэтому проза с чертой
    не считается таблицей. Принимаются оба стиля: с чертой в начале и без неё.
    """
    table_cells = {}
    index = 1
    while index < len(lines):
        separator = _split_table_row(lines[index])
        header = _split_table_row(lines[index - 1])
        if (not separator or not header or len(separator) != len(header)
                or not all(TABLE_SEPARATOR_CELL.fullmatch(cell)
                           for cell, _ in separator)):
            index += 1
            continue

        table_cells[index - 1] = header
        table_cells[index] = []
        index += 1
        while index < len(lines):
            row = _split_table_row(lines[index])
            if not row or len(row) != len(separator):
                break
            table_cells[index] = row
            index += 1
    return table_cells


def _dangling_conjunction_findings(lines, filename):
    # Строки приходят уже очищенными от кода и разметки, поэтому заборки
    # здесь повторно искать не нужно.
    findings = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        start = LIST_ITEM_START.match(line)
        if not start:
            index += 1
            continue

        content_indent = (len(start.group("indent"))
                          + len(start.group("marker"))
                          + len(start.group("gap")))
        item_lines = [(index, start.group("body"))]
        next_index = index + 1
        item_fence = False
        while next_index < len(lines):
            candidate = lines[next_index]
            candidate_stripped = candidate.strip()
            if CODE_FENCE.match(candidate_stripped):
                item_fence = not item_fence
                next_index += 1
                continue
            if item_fence:
                next_index += 1
                continue
            if not _is_list_continuation(candidate, content_indent):
                break
            item_lines.append((next_index, candidate))
            next_index += 1

        meaningful = []
        for line_index, item_line in item_lines:
            # Встроенный код оставляем нейтральным операндом, содержимое игнорируем.
            cleaned = INLINE_CODE.sub(" КОД ", item_line).strip()
            if cleaned:
                meaningful.append((line_index, cleaned))
        if meaningful:
            end_line_index, end_line = meaningful[-1]
            conjunction = CONJUNCTION_END.search(end_line)
        else:
            end_line_index, end_line, conjunction = None, None, None
        if conjunction:
            if end_line_index == index:
                finding_line = index + 1
                finding_col = start.start("marker") + 1
            else:
                raw_end_line = next(
                    raw for line_index, raw in item_lines
                    if line_index == end_line_index
                )
                masked_end_line = INLINE_CODE.sub(
                    lambda match: " " * len(match.group(0)), raw_end_line
                )
                raw_conjunction = CONJUNCTION_END.search(masked_end_line)
                finding_line = end_line_index + 1
                finding_col = raw_conjunction.start() + 1 if raw_conjunction else 1
            findings.append({
                "file": filename,
                "line": finding_line,
                "col": finding_col,
                "rule": "висячий-союз",
                "level": "advisory-free",
                "match": end_line,
                "message": ("Пункт списка заканчивается союзом. Закончи пункт "
                            "или объедини его со следующим."),
            })
        index = next_index
    return findings


def _mask_document(text):
    """Разобрать документ один раз и вернуть список чистых строк.

    На выходе список строк той же длины, что и вход. Строки кода, front
    matter и HTML-комментарии заменены пустыми, с маркеров цитаты снят,
    встроенный код, адреса и комментарии заменены пробесами той же длины.

    Заборка кода учитывается по CommonMark: закрывает заборку только маркер
    того же типа и не короче открывшего, и только если после него ничего
    нет. Иначе находки попадали внутрь блока кода.
    """
    raw_lines = _split_lines(text)
    out = []
    fence = None
    in_frontmatter = bool(raw_lines) and raw_lines[0].strip() == "---"
    previous_was_list = False

    for index, raw in enumerate(raw_lines):
        stripped = raw.strip()

        # Маркер цитаты снимается ПЕРВЫМ. Иначе заборка кода внутри цитаты
        # («> ```») не распознаётся и её содержимое попадает в проверку.
        body = raw
        while True:
            quote = re.match(r"^\s*(?:>\s?)+", body)
            if not quote:
                break
            body = body[quote.end():]
            body = " " * (len(raw) - len(body)) + body
        stripped = body.strip()

        if in_frontmatter:
            # YAML-метаданные в начале файла — не проза
            out.append("")
            if index > 0 and stripped == "---":
                in_frontmatter = False
            continue

        match = CODE_FENCE.match(stripped)
        if fence is None and match:
            fence = (match.group("mark")[0], len(match.group("mark")))
            out.append("")
            previous_was_list = False
            continue
        if fence is not None:
            if (match and match.group("mark")[0] == fence[0]
                    and len(match.group("mark")) >= fence[1]
                    and not match.group("info").strip()):
                fence = None
            out.append("")
            previous_was_list = False
            continue

        # Отступ в четыре пробела — блок кода, но только вне списка.
        # Внутри пункта списка такой отступ означает продолжение пункта,
        # и потерять его значит потерять весь текст пункта.
        is_list_line = bool(LIST_ITEM_START.match(body))
        if (INDENTED_CODE.match(body) and not previous_was_list
                and not is_list_line):
            out.append("")
            previous_was_list = False
            continue

        out.append(strip_noise(body))
        previous_was_list = is_list_line or (
            previous_was_list and bool(stripped) and not stripped.startswith("#"))
    return out


def _split_lines(text):
    """Разбить текст на строки только по настоящим переводам строк.

    `str.splitlines()` считает разделителями ещё и невидимые символы
    U+2028, U+2029, \\x0b, \\x0c, \\x85. Из-за этого номер строки в находке
    не совпадал с тем, что показывает редактор.
    """
    return re.split(r"\r\n|\r|\n", text)


def _prose_blocks(lines, table_cells):
    """Разбить документ на блоки связного текста и вернуть их списком строк.

    Предложение в Markdown редко умещается в одну строку: редактор переносит
    его по ширине. Если проверять длину построчно, любой перенос читается как
    короткое предложение и правило перестаёт работать. Поэтому строки
    склеиваются в блоки.

    Граница блока: пустая строка, заборка кода, заголовок, начало и конец строки
    таблицы. Ячейка таблицы — всегда отдельный блок: склеивать её с соседней
    ячейкой нельзя, это разные фрагменты вёрстки, а не одна фраза.
    """
    blocks = []
    current = []

    def flush():
        if current:
            # именно копия: append(current) сохранил бы ссылку на тот же
            # список, который следующий clear() тут же опустошил
            blocks.append(list(current))
            current.clear()

    in_fence = False
    for lineno, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()
        if CODE_FENCE.match(stripped):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            continue
        segments = table_cells.get(lineno - 1)
        if segments is not None:
            flush()
            blocks.extend([[(lineno, cell)] for cell, _ in segments if cell.strip()])
            continue
        if LIST_ITEM_START.match(raw_line):
            flush()
        current.append((lineno, stripped))
    flush()
    return blocks


LIST_MARKER = re.compile(r"^(?:#{1,6}\s+|-{1,3}\s+|\d+[.)]\s+)")

# Правила, которые порождаются не из RULES: предложения считаются по
# склеенным блокам, синонимы — по первым вхождениям, висячий союз — обходом
# списков. Их имена тоже принимает --disable, иначе список «доступных правил»
# врёт и человек не может отключить то, что видит в отчёте.
GENERATED_RULES = (
    "длинное-предложение",
    "многосоюзность",
    "сложные-подчинения",
    "синонимная-ротация",
    "висячий-союз",
)


def all_rule_ids():
    """Все имена правил, которые выдаёт линтер."""
    return sorted({rule_id for rule_id, _, _, _ in RULES} | set(GENERATED_RULES))


def _sentence_findings(blocks, filename):
    """Длина и связность предложений. Считаются по склеенным блокам.

    Номер строки — та, где предложение начинается.
    """
    findings = []
    for block in blocks:
        cleaned = [LIST_MARKER.sub("", text) for _, text in block]
        joined = " ".join(cleaned)
        starts = []
        offset = 0
        for text in cleaned:
            starts.append(offset)
            offset += len(text) + 1
        cursor = 0
        for sent in re.split(r"(?<=[.!?])\s+", joined):
            stripped = sent.strip()
            begin = cursor + sent.find(stripped)
            cursor += len(sent) + 1
            if not stripped:
                continue
            lineno = block[max(bisect.bisect_right(starts, begin) - 1, 0)][0]
            count = len(stripped.split())
            if count > MAX_WORDS:
                findings.append({"file": filename, "line": lineno, "col": 1,
                                 "rule": "длинное-предложение", "level": "advisory-free",
                                 "match": f"{count} слов",
                                 "message": (f"В предложении {count} слов "
                                             f"(потолок {MAX_WORDS}). Разбей его.")})
            coordinating = len(COORDINATING.findall(stripped))
            if coordinating >= MAX_COORDINATING:
                findings.append({"file": filename, "line": lineno, "col": 1,
                                 "rule": "многосоюзность", "level": "advisory-free",
                                 "match": f"{coordinating} союзов",
                                 "message": (f"В предложении {coordinating} сочинительных союза "
                                             f"(порог {MAX_COORDINATING}). "
                                             "Одна мысль на предложение.")})
            subordinating = len(SUBORDINATING.findall(stripped))
            if subordinating >= MAX_SUBORDINATING:
                findings.append({"file": filename, "line": lineno, "col": 1,
                                 "rule": "сложные-подчинения", "level": "advisory-free",
                                 "match": f"{subordinating} придаточных",
                                 "message": (f"В предложении {subordinating} придаточных "
                                             f"(порог {MAX_SUBORDINATING}). "
                                             "Сделай условие отдельным предложением.")})
    return findings


def lint(text, filename="<stdin>"):
    findings = []
    words_total = 0
    # разбор документа делается один раз: код, front matter, комментарии и
    # адреса убираются здесь, дальше все три прохода видят чистый текст
    lines = _mask_document(text)
    table_cells = _markdown_table_cells(lines)
    # первое вхождение каждого члена группы синонимов: (индекс группы, основа) -> (строка, столбец, совпадение)
    seen_synonyms = {}
    for lineno, raw_line in enumerate(lines, 1):
        segments = table_cells.get(lineno - 1, [(raw_line, 0)])
        for segment, source_column in segments:
            line = segment
            words_total += len(line.split())
            for rule_id, level, pattern, msg in RULES:
                for m in pattern.finditer(line):
                    findings.append({"file": filename, "line": lineno,
                                     "col": source_column + m.start() + 1,
                                     "rule": rule_id, "level": level,
                                     "match": m.group(0), "message": msg})
            for gi, group in enumerate(SYNONYM_GROUPS):
                for base in group:
                    if (gi, base) in seen_synonyms:
                        continue
                    m = _stem_re(base).search(line)
                    if m:
                        seen_synonyms[(gi, base)] = (
                            lineno, source_column + m.start() + 1, m.group(0)
                        )
    # предложения считаются один раз на весь документ, а не по строкам
    findings.extend(_sentence_findings(_prose_blocks(lines, table_cells), filename))
    # синонимная ротация: отмечаем каждого члена после первого, по первому вхождению
    for gi, group in enumerate(SYNONYM_GROUPS):
        present = [(seen_synonyms[(gi, b)], b) for b in group if (gi, b) in seen_synonyms]
        if len(present) > 1:
            present.sort()
            first_base = present[0][1]
            for (lineno, col, match), base in present[1:]:
                findings.append({"file": filename, "line": lineno, "col": col,
                                 "rule": "синонимная-ротация", "level": "advisory-free",
                                 "match": match,
                                 "message": (f"«{base}» и «{first_base}» называют одно действие. "
                                             "Выбери одно слово и используй его всегда.")})
    findings.extend(_dangling_conjunction_findings(lines, filename))
    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings, words_total


def plural(count, one, few, many):
    """Согласовать существительное с числом: 1 нарушение, 2 нарушения, 5 нарушений."""
    tail, rest = count % 100, count % 10
    if 11 <= tail <= 14:
        return many
    if rest == 1:
        return one
    if 2 <= rest <= 4:
        return few
    return many

def report(findings, words_total, as_json, hard_count, baseline):
    rate = round(len(findings) * 100 / words_total, 1) if words_total else 0.0
    if as_json:
        print(json.dumps({"violations": findings, "count": len(findings),
                          "hard_count": hard_count, "baseline": baseline,
                          "words": words_total, "per_100_words": rate}, indent=2,
                         ensure_ascii=False))
        return
    for f in findings:
        print(f"{f['file']}:{f['line']}:{f['col']} {f['rule']}: {f['message']} [{f['match']}]")
    print(f"{len(findings)} {plural(len(findings), 'нарушение', 'нарушения', 'нарушений')} "
          f"({hard_count} {plural(hard_count, 'жёсткое', 'жёстких', 'жёстких')}, "
          f"baseline {baseline}), "
          f"{words_total} {plural(words_total, 'слово', 'слова', 'слов')}, "
          f"{rate} на 100 слов")
    print("Оговорки и модальность («может», «возможно») не отмечаются никогда: "
          "уверенность — это содержание.")


def selftest():
    bad = ("Панель снята; настройка уникального модуля. "
           "Осуществляется проверка состояния. "
           "Файл был удалён агентом.")
    findings, _ = lint(bad)
    rules = {f["rule"] for f in findings}
    for expected in ("точка-с-запятой", "рекламное-прилагательное",
                     "отглагольные-существительные", "страдательный-залог"):
        assert expected in rules, (expected, sorted(rules))
    assert "канцелярит" in rules, sorted(rules)

    # Оговорки не отмечаются никогда, в том числе «мог + инфинитив».
    findings, _ = lint("Запрос мог завершиться ошибкой. Возможно, причина в тайм-ауте. "
                       "Иногда диск заполняется.")
    assert findings == [], findings

    # Блоки кода пропускаются
    findings, _ = lint("```\nx = a; y = b\n```")
    assert findings == [], findings

    # Все поддерживаемые маркеры списков и висячий союз
    findings, _ = lint(
        "- Проверь цель и\n"
        "* Запиши результат ИЛИ  \n"
        "+ Закрой панель\n"
        "1. Начни задачу и\n"
        "2) Останови задачу ИЛИ"
    )
    dangling = [f for f in findings if f["rule"] == "висячий-союз"]
    assert len(dangling) == 4, dangling
    assert [f["line"] for f in dangling] == [1, 2, 4, 5], dangling
    assert [f["col"] for f in dangling] == [1, 1, 1, 1], dangling
    assert all(f["level"] == "advisory-free" for f in dangling), dangling

    # Корректные продолжения пункта и самостоятельный отступ в 4 пробела игнорируются
    findings, _ = lint("  - Проверь цель и\n    запиши результат.")
    assert not any(f["rule"] == "висячий-союз" for f in findings)
    findings, _ = lint("- Проверь цель\n  и")
    dangling = [f for f in findings if f["rule"] == "висячий-союз"]
    assert len(dangling) == 1 and dangling[0]["line"] == 2, dangling
    findings, _ = lint("- Родительский пункт и\n  - Вложенный пункт или")
    dangling = [f for f in findings if f["rule"] == "висячий-союз"]
    assert [f["line"] for f in dangling] == [1, 2], dangling

    # Обычная проза и встроенный код игнорируются
    findings, _ = lint("Процесс может включать шаги и")
    assert not any(f["rule"] == "висячий-союз" for f in findings)
    findings, _ = lint("- Используй `и` как метку")
    assert not any(f["rule"] == "висячий-союз" for f in findings)
    findings, _ = lint("```text\n- код и\n```")
    assert not any(f["rule"] == "висячий-союз" for f in findings)

    # Длина предложения
    findings, _ = lint(("слово " * 30).strip() + ".")
    assert any(f["rule"] == "длинное-предложение" for f in findings)

    # Многосоюзность: три и более сочинительных союза
    findings, _ = lint("Открой файл и прочитай строку и проверь номер и результат.")
    multi = [f for f in findings if f["rule"] == "многосоюзность"]
    assert len(multi) == 1, multi
    findings, _ = lint("Открой файл. Прочитай строку.")
    assert not any(f["rule"] == "многосоюзность" for f in findings)

    # Сложные подчинения: два и больше придаточных
    findings, _ = lint("После того как задача завершена, и при условии, что ошибок нет, "
                       "агент читает артефакт.")
    sub = [f for f in findings if f["rule"] == "сложные-подчинения"]
    assert len(sub) == 1, sub
    findings, _ = lint("Дождись окончания задачи. Затем прочитай артефакт.")
    assert not any(f["rule"] == "сложные-подчинения" for f in findings)

    # Отглагольное существительное в предложном падеже
    findings, _ = lint("При обработке запроса сервер пишет отчёт.")
    prep = [f for f in findings if f["rule"] == "предложный-отглагольный"]
    assert len(prep) == 1, prep
    findings, _ = lint("Когда сервер обрабатывает запрос, он пишет отчёт.")
    assert not any(f["rule"] == "предложный-отглагольный" for f in findings)

    # Синонимная ротация по основам, с учётом русских окончаний
    findings, _ = lint("Проверь конфигурацию. Проверь результат.")
    assert not any(f["rule"] == "синонимная-ротация" for f in findings), findings
    findings, _ = lint("Удаляю файл. Сотрите его. Снесите файл.")
    rot = [f for f in findings if f["rule"] == "синонимная-ротация"]
    assert len(rot) == 2, rot
    findings, _ = lint("Начни задачу. Приступи к работе.")
    rot = [f for f in findings if f["rule"] == "синонимная-ротация"]
    assert len(rot) == 1, rot

    # Прилагательные не считаются причастиями
    findings, _ = lint("Это самый лучший и новый подход.")
    rules = {f["rule"] for f in findings}
    assert "причастный-оборот" not in rules, findings
    assert "рекламное-прилагательное" in rules, findings

    # Разметка Markdown-таблицы — это вёрстка, а не проза; ячейки проверяются.
    # Разделительная строка не считается прозой: у неё ноль ячеек для проверки.
    short_cell = " ".join(f"слово{n}" for n in range(1, 20)) + "."
    for table in (
            "| Метка | Деталь |\n"
            "| --- | --- |\n"
            f"| Ясно | {short_cell} |",
            "Метка | Деталь\n"
            "--- | ---\n"
            f"Ясно | {short_cell}"):
        findings, words_total = lint(table)
        assert not any(f["rule"] == "длинное-предложение" for f in findings), findings
        assert words_total == 22, words_total
    long_cell = " ".join(f"слово{n}" for n in range(1, 23)) + "."
    findings, _ = lint(
        "| Метка | Деталь |\n"
        "| --- | --- |\n"
        f"| Ясно | {long_cell} |"
    )
    long_sentences = [f for f in findings if f["rule"] == "длинное-предложение"]
    assert len(long_sentences) == 1, long_sentences
    assert long_sentences[0]["match"] == "22 слов", long_sentences

    # Подписи файлов
    findings, _ = lint("а; б", filename="x.md")
    assert findings[0]["file"] == "x.md"

    # Ложные срабатывания, найденные независимой проверкой. Обычный
    # грамотный русский текст должен проходить молча.
    clean_prose = [
        "Модуль отправляет данные на сервер.",
        "Скрипт удаляет временные файлы.",
        "Следующий шаг — запустить тест.",
        "Показатель качества вырос, а отображение ошибок работает.",
        "Журнал хранит список выполненных операций.",
        "Встроенный модуль читает входящие данные.",
        "Текущий пользователь не имеет прав на запись.",
        "Женя читает отчёт и пишет вывод.",
        "Модуль даёт доступ к данным через один порт.",
        "По данным журнала видно, что модуль работал ночью.",
        "Доступен по данным журнала.",
        "Длинное имя файла ломает команду копирования.",
        "Это длинное предложение состоит из трёх частей.",
        "В отчёте есть единственная причина отказа.",
        "Проведение совещания занимает один час.",
        "Выполнение плана зависит от скорости работы сервера.",
        "Показатель задержки сети вырос.",
        "Средство проверки целостности файлов входит в состав пакета.",
        "Применение нового метода ускорило сборку.",
        "Использование кеша снизило число запросов.",
        "Стартовый скрипт проверяет наличие нужных файлов.",
        "Анна читала отчёт и проверяла итоговые числа.",
        "Пётр закончил работу раньше других.",
        "Агент обработал 100 запросов за одну минуту.",
        "Изменённых задач и удалённых файлов много.",
        "Скрипт находит свободный порт и занимает его.",
        "Сервер находит маршрут до узла за одну секунду.",
        "Наша система работает на свежей версии ядра.",
        "Наш сервер отвечает за две секунды.",
    ]
    for text in clean_prose:
        findings, _ = lint(text)
        assert findings == [], (text, findings)

    # Оговорки не отмечаются даже перед именем-агентом в творительном падеже.
    # Именно этот случай проскакивал мимо узкого варианта selftest раньше.
    for text in (
            "Вероятно, причина в том, что соединение с сервером разрывается.",
            "Возможно, причина в том, что соединение с сервером рвётся.",
            "Скорее всего, причина в том, что сервер отвечает медленно.",
            "Иногда причина в том, что соединение с сервером рвётся.",
            "Причина сбоя — слабый канал между клиентом и сервером.",
            "Обычно причина в том, что сервер перегружен.",
            # «был недоступен» — связка с прилагательным, а не страдательный
            # залог. Раньше оговорка перед таким словом давала ложную находку.
            "Вероятно, причина в том, что сервер был недоступен во время проверки.",
            "Сервер был недоступен во время проверки.",
            "Файл был виден только после сборки.",
            "Результат был известен заранее.",
    ):
        findings, _ = lint(text)
        assert findings == [], (text, findings)

    # Реальные нарушения не должны теряться после ужесточения регулярок
    for text, rule in (
            ("Выполни проверку журнала.", "отглагольные-существительные"),
            ("Проведи проверку журнала.", "отглагольные-существительные"),
            ("Осуществите проверку состояния.", "отглагольные-существительные"),
            ("Осуществите проверку состояния.", "отглагольные-существительные"),
            ("Окажите поддержку.", "отглагольные-существительные"),
            ("Проверка будет выполнена через час.", "страдательный-залог"),
            ("Файл будет удалён через минуту.", "страдательный-залог"),
            ("Агент нашёл ошибку и обнаружил вторую.", "синонимная-ротация"),
            ("Скрипт нашёл дефект и выявил его в журнале.", "синонимная-ротация"),
            ("Агент нашёл дефект и обнаружил его в журнале.", "синонимная-ротация"),
    ):
        findings, _ = lint(text)
        assert rule in {f["rule"] for f in findings}, (text, rule, findings)

    # Перенос строки внутри предложения не должен прятать его от правил длины
    wrapped = ("Это предложение намеренно длинное и перенесено на несколько "
               "строк подряд,\nчтобы проверить, что линтер склеивает абзац "
               "прежде, чем считать слова в нём.")
    findings, _ = lint(wrapped)
    long_sentences = [f for f in findings if f["rule"] == "длинное-предложение"]
    assert len(long_sentences) == 1, long_sentences
    assert long_sentences[0]["line"] == 1, long_sentences
    findings, _ = lint("Короткая строка.\nИ вторая короткая строка.")
    assert not any(f["rule"] == "длинное-предложение" for f in findings)

    # Регрессии по итогам независимой проверки 20 агентами.
    #
    # 1. Оговорки и безличные слова не должны выглядеть страдательным залогом.
    for text in (
            "Невозможно сказать, что всё в порядке с системой.",
            "Видно, что нет связи с сервером.",
            "Трудно сказать, что порядок с сервером.",
            "Сложно сказать, что порядок с клиентом.",
            "Непонятно, что делать с модулем.",
            "Маловероятно, что есть связь с сервером.",
            "Должно быть, всё в порядке с сервером.",
            "Формально связь с сервером есть.",
            "В основном связь с сервером есть.",
            "Нельзя сказать, что порядок с системой.",
            "Можно проверить, что порядок с системой.",
    ):
        findings, _ = lint(text)
        assert findings == [], (text, findings)

    # 2. Связка с прилагательным — не страдательный залог.
    for text in (
            "Порт был свободен до запуска.",
            "Статус был активен долгое время.",
            "Причина была очевидна сразу.",
            "Ошибка была заметна в журнале.",
            "Тест был стабилен на всех системах.",
            "Должна была быть причина отказа.",
    ):
        findings, _ = lint(text)
        assert findings == [], (text, findings)

    # 3. Глагол в прошедшем времени — это уже глагол, а не номинализация.
    for text in ("Провёл проверку журнала.", "Выполнил проверку.",
                 "Осуществил проверку.", "Обработал операцию."):
        findings, _ = lint(text)
        assert findings == [], (text, findings)
    # а настоящее и повелительное время по-прежнему ловится
    for text in ("Выполни проверку журнала.", "Осуществите проверку состояния.",
                 "Осуществляется настройка модуля."):
        findings, _ = lint(text)
        assert "отглагольные-существительные" in {f["rule"] for f in findings}, text

    # 4. Код не проверяется ни в каком виде.
    for text in (
            "```\nплохой ; код\n```\nпосле ; кода",
            "````\n```\nплохой ; код\n```\n````\nпосле ; кода",
            "> ```\n> код ; тут\n> ```\nпосле ; кода",
            "текст\n\n    код ; тут ; не проверять\n\nпосле ; кода",
            "```python\nплохой ; код\n```\nпосле ; кода",
    ):
        findings, _ = lint(text)
        hits = [f for f in findings if f["rule"] == "точка-с-запятой"]
        assert len(hits) == 1, (text, hits)
    # по CommonMark заборка с текстом после маркера не закрывает блок,
    # поэтому весь остаток файла остаётся кодом
    findings, _ = lint("```js\nплохой ; код\n``` хвост\nпосле ; кода")
    assert findings == [], findings

    # 5. Front matter и комментарии — не проза.
    text = "---\nname: ste\ndescription: Описание; навыка\n---\n\nТекст без нарушений."
    findings, _ = lint(text)
    assert findings == [], findings
    findings, _ = lint("<!-- ; внутри комментарий -->\nтекст без нарушений")
    assert findings == [], findings

    # 6. Адреса не проверяются.
    for text in ("Открой [страницу](https://example.com/a;b=c) сейчас.",
                 "Ссылка: <https://example.com/a;b=c>",
                 "![схема](./img.png;a=1)"):
        findings, _ = lint(text)
        assert findings == [], (text, findings)

    # 7. Номер строки считается по настоящим переводам строк.
    text = "Первая; строка.\nВторая\u2028строка; тут.\nТретья; строка."
    findings, _ = lint(text)
    assert sorted(f["line"] for f in findings) == [1, 2, 3], findings

    # 8. Колонка не должна уезжать из-за встроенного кода.
    text = "Проверь `код` значение; тест."
    findings, _ = lint(text)
    semicolon = [f for f in findings if f["rule"] == "точка-с-запятой"]
    assert semicolon and semicolon[0]["col"] == text.index(";") + 1, semicolon

    # 9. Маркер цитаты не склеивает абзацы и не считается словом.
    text = ("> Запись сделана сервером и сохранена в журнале\n"
            "> без точки в конце\n>\n"
            "> Дальше идёт проверка ответа и запись результата\n"
            "> в отдельный файл без точки\n")
    findings, words = lint(text)
    assert not [f for f in findings if f["rule"] in ("длинное-предложение",
                                                      "многосоюзность")], findings
    assert words == 23, words  # 28 минус 5 маркеров «>», они не слова

    # 10. Вложенный список с отступом 4 пробела.
    findings, _ = lint("- Родительский пункт и\n    - Вложенный пункт или")
    dangling = [f for f in findings if f["rule"] == "висячий-союз"]
    assert [f["line"] for f in dangling] == [1, 2], dangling

    # 11. Составной союз считается одним придаточным.
    findings, _ = lint("Несмотря на то что дождь шёл, проверка прошла успешно.")
    assert not [f for f in findings if f["rule"] == "сложные-подчинения"], findings

    # 12. Многострочный блок не должен давать квадратичного времени.
    import time as _time
    huge = ("Проверь файл.\n" * 3000).rstrip("\n")
    started = _time.perf_counter()
    lint(huge)
    assert _time.perf_counter() - started < 3.0, "многострочный блок слишком медленный"

    print("самопроверка пройдена")


class UserError(Exception):
    """Ошибка в аргументах командной строки."""


USAGE = """Линтер упрощённого технического русского.

Запуск:
  ste-lint.py [файл ...]            проверяет файлы, без них читает стандартный ввод
  ste-lint.py --json [файл ...]     структурированный вывод
  ste-lint.py --baseline N         код 1 только если нарушений больше N
  ste-lint.py --disable правило,... отключить правила по имени
  ste-lint.py --selftest           проверить сам линтер
  ste-lint.py -h, --help           эта справка

Коды возврата:
  0  жёстких нарушений не больше порога
  1  жёстких нарушений больше порога
  2  неверные аргументы или файл не прочитан

Правила:"""


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
    if any(a in ("-h", "--help") for a in argv):
        print(USAGE)
        print("  " + ", ".join(all_rule_ids()))
        return 0
    as_json = "--json" in argv
    baseline = 0
    disabled = set()
    paths = []
    stdin_requested = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--baseline", "--disable"):
            if i + 1 >= len(argv):
                raise UserError(f"после {a} нужно значение")
            i += 1
            if a == "--baseline":
                try:
                    baseline = int(argv[i])
                except ValueError:
                    raise UserError(f"--baseline ждёт целое число, получено {argv[i]!r}")
                if baseline < 0:
                    raise UserError("--baseline не может быть отрицательным")
            else:
                # повторный --disable дополняет предыдущий, а не затирает его
                disabled |= {name.strip() for name in argv[i].split(",") if name.strip()}
        elif a in ("--json",):
            pass  # учтён выше, в as_json
        elif a == "--":
            # конец ключей, дальше только имена файлов
            paths.extend(argv[i + 1:])
            break
        elif a == "-":
            # одиночный дефис — общепринятое обозначение стандартного ввода.
            # Проверять его надо ДО общей ветки для ключей, иначе дефис
            # считается неизвестным ключом.
            stdin_requested = True
        elif a.startswith("-"):
            # Раньше «-h» уходил в список файлов и давал невнятное
            # «файл не найден». Теперь любой незнакомый ключ — понятная ошибка
            # с подсказкой, а опечатка вроде «--jsonn» не остаётся незамеченной.
            raise UserError(f"неизвестный ключ: {a}. Справка: --help")
        else:
            paths.append(a)
        i += 1

    # Имя правила в --disable должно совпадать с реальным. Иначе опечатка
    # молча ничего не отключает, и человек ищет правило, которого нет.
    known = set(all_rule_ids())
    unknown = sorted(disabled - known)
    if unknown:
        print(f"неизвестное правило: {', '.join(unknown)}", file=sys.stderr)
        print(f"доступные правила: {', '.join(all_rule_ids())}", file=sys.stderr)
        return 2
    if paths and not disabled:
        # повторный файл в списке удваивал и находки, и счётчик слов
        seen_paths = set()
        unique = []
        for p in paths:
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen_paths:
                seen_paths.add(key)
                unique.append(p)
        paths = unique

    findings, words_total = [], 0
    failed = False
    if paths and not stdin_requested:
        for p in paths:
            if os.path.isdir(p):
                print(f"это папка, а не файл: {p}", file=sys.stderr)
                failed = True
                continue
            try:
                # utf-8-sig снимает метку порядка байтов, если она есть,
                # и при этом читает обычные файлы без метки
                with open(p, encoding="utf-8-sig") as handle:
                    f, w = lint(handle.read(), filename=p)
            except FileNotFoundError:
                print(f"файл не найден: {p}", file=sys.stderr)
                failed = True
                continue
            except PermissionError:
                # файл занят другим процессом или нет прав на чтение.
                # Раньше здесь печаталось «это папка», что сбивало с толку.
                print(f"файл занят или нет прав на чтение: {p}", file=sys.stderr)
                failed = True
                continue
            except UnicodeDecodeError:
                print(f"файл не в кодировке UTF-8: {p}", file=sys.stderr)
                failed = True
                continue
            findings.extend(f)
            words_total += w
    else:
        try:
            raw = sys.stdin.buffer.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            # раньше здесь вылезала трассировка Python, а код возврата 1
            # совпадал с «найдены нарушения» — конвейер принимал сломанный
            # вход за успешную проверку
            print("вход не в кодировке UTF-8", file=sys.stderr)
            return 2
        findings, words_total = lint(raw)
    if failed:
        # отчёт по остальным файлам всё равно полезен, но код 2 честнее
        report(findings, words_total, as_json, 0, baseline)
        return 2

    findings = [f for f in findings if f["rule"] not in disabled]
    hard_count = sum(1 for f in findings if f["level"] == "advisory-free")
    report(findings, words_total, as_json, hard_count, baseline)
    return 1 if hard_count > baseline else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except UserError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        sys.exit(2)
    except BrokenPipeError:
        # при "| head" вывод закрывается на середине печати. Трассировка
        # Python здесь была бы шумом, а не диагностикой.
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
