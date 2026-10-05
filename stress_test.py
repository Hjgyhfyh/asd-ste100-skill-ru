"""Стресс-тесты и обход всех функций линтера.

Запуск:
    python stress_test.py            # полный набор
    python stress_test.py --quick    # только быстрые проверки

Скрипт НЕ меняет файлы навыка. Он только читает их и проверяет линтер.
"""
import importlib.util
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LINTER = os.path.join(HERE, "scripts", "ste-lint.py")

spec = importlib.util.spec_from_file_location("linter", LINTER)
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

FAILURES = []
RESULTS = []


def check(name, condition, detail=""):
    ok = bool(condition)
    RESULTS.append((name, ok, detail))
    if not ok:
        FAILURES.append((name, detail))
    return ok


# ---------------------------------------------------------------- обещания

def test_hedge_promise():
    """Главное обещание навыка: оговорки не отмечаются никогда."""
    hedges = [
        "Запрос мог завершиться ошибкой.",
        "Возможно, причина в тайм-ауте.",
        "Вероятно, диск заполнился.",
        "Иногда сеть отваливается.",
        "Может быть, файл заблокирован.",
        "Скорее всего, сервер перегружен.",
        "Вероятно, причина в том, что соединение с сервером разрывается.",
        "Иногда причина в том, что соединение с сервером рвётся.",
        "Обычно причина в том, что сервер перегружен.",
        "Причина сбоя — слабый канал между клиентом и сервером.",
        "Причина сбоя: слабый канал между клиентом и сервером.",
        "Bloggos Technologies Guide Скорее всего, причина в тайм-ауте.",
        "Вероятно, причина в том, что сервер был недоступен во время проверки.",
        "Скорее всего, причина в том, что модуль не запустился из-за прав доступа.",
    ]
    for text in hedges:
        findings, _ = L.lint(text)
        check("оговорка: " + text[:45], findings == [], repr(text) + " -> " + repr(findings))


def test_clean_prose():
    """Обычный грамотный русский текст не должен давать находок."""
    samples = [
        "Модуль отправляет данные на сервер.",
        "Скрипт удаляет временные файлы.",
        "Следующий шаг — запустить тест.",
        "Показатель качества вырос, а отображение ошибок работает.",
        "Скрипт находит свободный порт и занимает его.",
        "Наша система работает on-line и отвечает за две секунды.",
        "Текущий пользователь не имеет прав на запись.",
        "Анна читала отчёт и проверяла итоговые числа.",
        "Пётр закончил работу раньше других.",
        "Агент обработал 100 запросов за одну минуту.",
        "Изменённых задач и удалённых файлов много.",
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
        "Средний размер пакета вырос после обновления.",
        "Главная страница сайта содержит список всех главных разделов.",
        "Провёл проверку журнала и записал результат.",
        "Провели проверку журнала и записали результат.",
        "Выполнил проверку и закрыл задачу.",
    ]
    for text in samples:
        findings, _ = L.lint(text)
        # «после обновления» — отглагольное существительное. Правило
        # рекомендательное, поэтому находка допустима. Жёсткой быть не должна.
        hard = [f for f in findings if f["level"] == "advisory-free"]
        if text.endswith("после обновления."):
            check("не жёсткая находка: " + text[:45], len(hard) == 0, repr(findings))
        else:
            check("чистый текст: " + text[:45], findings == [], repr(findings))


def test_real_violations():
    """Реальные нарушения обязаны находиться."""
    cases = [
        ("Осуществляется проверка.", "канцелярит"),
        ("Проверка будет выполнена через час.", "страдательный-залог"),
        ("Выполни проверку журнала.", "отглагольные-существительные"),
        ("Проведи проверку журнала.", "отглагольные-существительные"),
        ("полный", None),  # заполнитель, см. ниже
    ]
    del cases[-1]
    expected = [
        ("Осуществляется проверка.", "канцелярит"),
        ("Проверка будет выполнена через час.", "страдательный-залог"),
        ("Выполни проверку журнала.", "отглагольные-существительные"),
        ("Проведи проверку журнала.", "отглагольные-существительные"),
        ("Осуществите проверку состояния.", "отглагольные-существительные"),
        ("Окажите поддержку.", "отглагольные-существительные"),
        ("Провести анализ журнала.", "отглагольные-существительные"),
        ("Агент нашёл ошибку и обнаружил вторую.", "синонимная-ротация"),
        ("Агент нашёл дефект и обнаружил его в журнале.", "синонимная-ротация"),
        ("Скрипт нашёл дефект и выявил его в журнале.", "синонимная-ротация"),
        ("Агент удалил файл; затем прочитал журнал.", "точка-с-запятой"),
        ("Откройте панель; затем снимите её.", "точка-с-запятой"),
        ("Это предложение намеренно длинное и перенесено на несколько строк подряд, "
         "чтобы проверить, что линтер склеивает абзац прежде, чем считать слова в нём.",
         "длинное-предложение"),
    ]
    for text, rule in expected:
        findings, _ = L.lint(text)
        rules = {f["rule"] for f in findings}
        check("нарушение: " + rule, rule in rules, repr(text) + " -> " + repr(sorted(rules)))


# ---------------------------------------------------------------- синтаксис

def test_syntax_syntax():
    """Синтаксис не должен ломаться: код, Markdown, спецсимволы."""
    weird = [
        "", " ", "\n", "\n\n\n", "\t", "a", "a;b", ";;;;", "1", "1.2.3",
        "а" * 5000, "а\n" * 2000, "**" * 500, "|" * 100, "#" * 50,
        "```\n```", "```python\nx = 1; y = 2\n```", "````\n```\n````",
        "```", "``` unclosed", "    indented code; here",
        "| a | b |\n| --- | --- |\n| 1 | 2 |", "not a table | but pipe",
        "*emphasis* и **strong**", "~~strike~~", "<!-- comment; here -->",
        "Ссылка [текст](https://example.com; \"title\")",
        "![картинка](./img.png)", "&amp; &lt; &#65;", "\\* экранированный *",
        "Смешение\r\n\r\nWindows\r\nпереносов\r\nстрок.",
        "ЁЖИК ёжик Ёж", "🜁🜂🜃🜄", "𝕳𝖊𝖑𝖑𝖔", "ｆｕｌｌｗｉｄｔｈ",
        "Ω≈ç√∫˜µ≤≥÷", "ЗАГЛАВНЫЕ ВСЕ БУКВЫ; ТАК НЕЛЬЗЯ; ТОЧКА С ЗАПЯТОЙ",
    ]
    for text in weird:
        try:
            findings, words = L.lint(text)
            assert isinstance(findings, list) and isinstance(words, int)
            # у каждой находки должны быть все ключи и корректные координаты
            for f in findings:
                for key in ("file", "line", "col", "rule", "level", "match", "message"):
                    assert key in f, (text[:30], f)
                assert f["line"] >= 1, (text[:30], f)
                assert f["col"] >= 1, (text[:30], f)
                assert f["level"] in ("advisory-free", "advisory"), f
        except Exception as exc:  # noqa: BLE001
            check("синтаксис: " + repr(text[:30]), False, "%s: %s" % (type(exc).__name__, exc))


def test_regex_catastrophic():
    """Нельзя, чтобы регулярка зависла на длинном несовпадении."""
    long_no_match = [
        "а" * 2000 + " ",
        "абв " * 500 + "б",
        ("Проверь журнал " * 200) + "я",
        ("Модуль отправляет данные на сервер. " * 200),
        ("а " * 3000) + ";",
    ]
    for text in long_no_match:
        start = time.perf_counter()
        try:
            L.lint(text)
        except Exception as exc:  # noqa: BLE001
            check("регулярка: " + repr(text[:25]), False, str(exc))
            continue
        elapsed = time.perf_counter() - start
        check("регулярка не встала: " + repr(text[:25]), elapsed < 3.0, "%.2f с" % elapsed)


def test_reentrant():
    """Повторные вызовы не должны накапливать состояние."""
    text = "Осуществляется проверка; модуль уникальный."
    first, _ = L.lint(text)
    for _ in range(50):
        again, _ = L.lint(text)
        check("повторный вызов даёт тот же результат", again == first, repr(again))
    # наоборот, разные документы не должны влиять друг на друга
    a, _ = L.lint("Агент удалил файл и стёр его.")
    b, _ = L.lint("Короткий текст без нарушений.")
    c, _ = L.lint("Агент удалил файл и стёр его.")
    check("нет утечки состояния между документами", a == c, repr(a) + " / " + repr(c))
    del b


# ---------------------------------------------------------------- Markdown

def test_markdown_shapes():
    """Разные формы Markdown не должны ложно ругаться."""
    docs = [
        "Заголовок\n\nТекст под ним.\n\n## Другой\n\nЕщё текст.",
        "- пункт один\n- пункт два\n- пункт три",
        "1. первый\n2. второй\n3. третий",
        "> цитата с точкой; с запятой",
        "Список:\n\n1. первый\n2. второй\n",
        "---\n\nПосле линиииии разделителя.\n\n---\n",
        "| Заголовок | Ещё |\n|---|---|\n| ячейка | ячейка |\n",
        "Термин: **жирный**, *курсив*, `код`.\n",
        "Сноска[^1].\n\n[^1]: текст сноски.\n",
        "Список дефисом\n- первый\n- второй\n\nАбзац после списка.",
    ]
    for text in docs:
        findings, _ = L.lint(text)
        # Точка с запятой внутри цитаты или таблицы — настоящее нарушение.
        # Проверять надо, что нет находок, КРОМЕ явно ожидаемых.
        allowed = {"точка-с-запятой"} if ";" in text and not text.startswith("|") else set()
        unexpected = [f for f in findings
                      if f["level"] == "advisory-free" and f["rule"] not in allowed]
        check("markdown: " + repr(text[:40]), len(unexpected) == 0, repr(unexpected))


def test_fence_state():
    """Заборка кода: незакрытая не должна ломать разбор, но и не должна
    «съесть» нарушения, которые идут после закрывающей строки."""
    text = "```\nкод; здесь\n```\n\nТекст с точкой; с запятой.\n"
    findings, _ = L.lint(text)
    hard = [f for f in findings if f["level"] == "advisory-free"]
    check("заборка кода закрывается", any(f["rule"] == "точка-с-запятой" for f in hard),
          repr(hard))
    only_code = "```\nа; б; в\n```"
    findings, _ = L.lint(only_code)
    check("код внутри заборки не проверяется", findings == [], repr(findings))


def test_table_cells():
    """Ячейки таблиц считаются отдельно друг от друга."""
    long_cell = " ".join("слово%d" % n for n in range(1, 23)) + "."
    text = "| A | B |\n|---|---|\n| Ясно | %s |\n" % long_cell
    findings, _ = L.lint(text)
    long_sentences = [f for f in findings if f["rule"] == "длинное-предложение"]
    check("длинная ячейка найдена", len(long_sentences) == 1, repr(long_sentences))
    check("номер строки длинной ячейки", long_sentences and long_sentences[0]["line"] == 3,
          repr(long_sentences))
    for name in L.all_rule_ids():
        check("имя правила в списке: " + name, name == name.strip() and " " not in name)


# ---------------------------------------------------------------- CLI

def run_cli(args, stdin_text=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, LINTER] + args,
        input=stdin_text, capture_output=True, text=True,
        encoding="utf-8", env=env, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_cli_all():
    """Все ключи запуска и все коды возврата."""
    clean_file = os.path.join(tempfile.gettempdir(), "ste-clean.md")
    with open(clean_file, "w", encoding="utf-8") as fh:
        fh.write("Модуль отправляет данные на сервер.\n")
    cases = [
        (["--selftest"], None, 0, "selftest"),
        (["--disable"], None, 2, "нет значения"),
        (["--baseline"], None, 2, "нет значения"),
        (["--baseline", "abc"], None, 2, "не число"),
        (["--baseline", "3.5"], None, 2, "не целое"),
        ([clean_file], None, 0, "существующий чистый файл"),
        (["/нет/такого/файла.md"], None, 2, "нет файла"),
        ([HERE], None, 2, "это папка"),
        (["--json"], "текст;", 1, "json со stdin"),
        (["--json", "--baseline", "1"], "текст;", 0, "baseline 1"),
        (["--baseline", "0", "--disable", "точка-с-запятой"], "текст;", 0, "отключение"),
        (["--disable", "точка-с-запятой,канцелярит"], "текст; осуществляется;",
         0, "два правила"),
        (["--unknown-flag"], "текст", 2, "длинный неизвестный ключ"),
        (["--"], "текст", 0, "двойное тире разделяет ключи"),
        (["-h"], "текст", 0, "короткая справка"),
        (["--help"], "текст", 0, "справка"),
        (["-x"], "текст", 2, "неизвестный короткий ключ"),
        ([], "", 0, "пустой ввод"),
        (["--selftest", "файл.md"], None, 0, "selftest игнорирует файлы"),
    ]
    for args, stdin_text, expected_code, label in cases:
        code, out, err = run_cli(args, stdin_text)
        ok = check("CLI %s -> %d" % (label, expected_code), code == expected_code,
                   "код %d, stdout=%r, stderr=%r" % (code, out[:120], err[:120]))
        if not ok:
            continue
        if expected_code == 2:
            check("CLI %s: есть сообщение" % label, bool(err.strip()), "stderr пуст")
        check("CLI %s: нет трассировки" % label, "Traceback" not in err, err[:200])
    code, out, _ = run_cli(["--help"])
    check("справка перечисляет правила", "длинное-предложение" in out, out[:200])
    check("справка на русском", "Запуск" in out, out[:200])
    try:
        os.remove(clean_file)
    except OSError:
        pass


def test_cli_encoding():
    """Файлы в другой кодировке — понятная ошибка, а не падение."""
    with tempfile.TemporaryDirectory() as tmp:
        cp1251 = os.path.join(tmp, "cp1251.md")
        with open(cp1251, "w", encoding="cp1251") as fh:
            fh.write("Проверка была выполнена агентом.\n")
        code, out, err = run_cli([cp1251])
        check("файл не в UTF-8: код 2", code == 2, "код %d, %r" % (code, err[:150]))
        check("файл не в UTF-8: нет трассировки", "Traceback" not in err, err[:200])

        utf8_bom = os.path.join(tmp, "bom.md")
        with open(utf8_bom, "w", encoding="utf-8-sig") as fh:
            fh.write("Осуществляется проверка; модуль уникальный.\n")
        code, out, err = run_cli([utf8_bom])
        check("файл с BOM читается", code == 1, "код %d, %r" % (code, err[:200]))
        check("файл с BOM: нет трассировки", "Traceback" not in err, err[:200])
        check("файл с BOM: нарушения найдены", "нарушени" in out, out[:200])

        empty = os.path.join(tmp, "empty.md")
        open(empty, "w", encoding="utf-8").close()
        code, out, err = run_cli([empty])
        check("пустой файл: код 0", code == 0, "код %d, %r" % (code, err[:200]))

        binary = os.path.join(tmp, "bin.md")
        with open(binary, "wb") as fh:
            fh.write(bytes(range(256)))
        code, out, err = run_cli([binary])
        check("двоичный файл: нет трассировки", "Traceback" not in err, err[:200])


def test_cli_json_contract():
    """Формат --json обязан быть стабильным."""
    code, out, err = run_cli(["--json"], "Осуществляется проверка; модуль уникальный.")
    check("--json: код 1", code == 1, "код %d" % code)
    try:
        data = json.loads(out)
    except Exception as exc:  # noqa: BLE001
        check("--json парсится", False, "%s: %s / %r" % (type(exc).__name__, exc, out[:200]))
        return
    check("--json парсится", True)
    for key in ("count", "hard_count", "words", "violations"):
        check("--json содержит " + key, key in data, repr(sorted(data)))
    for v in data.get("violations", []):
        for key in ("file", "line", "col", "rule", "level", "match", "message"):
            check("--json находка содержит " + key, key in v, repr(sorted(v)))


def test_json_matches_text_report():
    """Числа в текстовом отчёте должны совпадать с --json."""
    text = "Осуществляется проверка; модуль уникальный и безупречен."
    _, jout, _ = run_cli(["--json"], text)
    _, tout, _ = run_cli([], text)
    data = json.loads(jout)
    check("отчёт: число жёстких совпало",
          ("%d %s" % (data["hard_count"], L.plural(data["hard_count"], "жёсткое", "жёстких", "жёстких"))) in tout, repr(tout[:200]))
    check("отчёт: всего совпало",
          ("%d %s" % (data["count"], L.plural(data["count"], "нарушение", "нарушения", "нарушений"))) in tout, repr(tout[:200]))


def test_multiple_files():
    """Несколько файлов за один вызов."""
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.md")
        b = os.path.join(tmp, "b.md")
        with open(a, "w", encoding="utf-8") as fh:
            fh.write("Осуществляется проверка.\n")
        with open(b, "w", encoding="utf-8") as fh:
            fh.write("Короткий текст.\n")
        code, out, err = run_cli([a, b])
        check("два файла: код 1", code == 1, "код %d" % code)
        code, out, err = run_cli([b, b, b])
        check("один файл трижды: код 0", code == 0, "код %d" % code)
        code, out, err = run_cli(["--baseline", "999", a, b])
        check("baseline 999: код 0", code == 0, "код %d" % code)


# ---------------------------------------------------------------- стресс

def test_fuzz_mutation():
    """Случайные правки чистого текста: находка не должна появляться
    из воздуха, а программа не должна падать."""
    base = [
        "Модуль отправляет данные на сервер.",
        "Скрипт удаляет временные файлы.",
        "Показатель качества вырос, а отображение ошибок работает.",
        "Анна читала отчёт и проверяла итоговые числа.",
    ]
    alphabet = list("абвгдеёжзийклмнопрстуфхцчшщыэюя ,.;:-—()«»\n\t!?")
    rng = random.Random(20261005)
    crashes = 0
    for i in range(4000):
        text = " ".join(rng.choice(base) for _ in range(rng.randint(1, 3)))
        for _ in range(rng.randint(0, 4)):
            if not text:
                break
            pos = rng.randrange(len(text))
            action = rng.random()
            if action < 0.4:
                text = text[:pos] + rng.choice(alphabet) + text[pos:]
            elif action < 0.7:
                text = text[:pos] + text[pos + 1:]
            else:
                text = text[:pos] + rng.choice(alphabet) + text[pos + 1:]
        try:
            findings, _ = L.lint(text)
            assert isinstance(findings, list)
        except Exception as exc:  # noqa: BLE001
            crashes += 1
            if crashes <= 3:
                check("фаззинг не падает", False,
                      "вход=%r ошибка=%s: %s" % (text[:80], type(exc).__name__, exc))
    check("фаззинг: 4000 случайных текстов без падений", crashes == 0,
          "падений: %d" % crashes)


def test_fuzz_random_bytes():
    """Случайные строки из любых символов."""
    alphabet = ([chr(c) for c in range(32, 127)]
                + [chr(c) for c in range(0x400, 0x460)]
                + list(" \n\t|;"))
    rng = random.Random(777)
    crashes = 0
    for _ in range(2000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))
        try:
            L.lint(text)
        except Exception:  # noqa: BLE001
            crashes += 1
    check("фаззинг байтов: 2000 строк без падений", crashes == 0, "падений: %d" % crashes)


def test_deep_nesting():
    """Глубокая вложенность Markdown."""
    for depth in (10, 50, 200):
        text = "\n".join("  " * i + "- пункт" for i in range(depth))
        try:
            L.lint(text)
        except Exception as exc:  # noqa: BLE001
            check("вложенность %d" % depth, False, str(exc))
            return
    check("глубокая вложенность списков не ломает разбор", True)


def test_scale():
    """Большой документ: время линейное, а не квадратичное."""
    para = ("Модуль отправляет данные на сервер. Скрипт удаляет временные файлы. "
            "Показатель качества вырос, а отображение ошибок работает. ")
    for size in (50, 200, 800):
        text = (para * size)
        start = time.perf_counter()
        findings, words = L.lint(text)
        elapsed = time.perf_counter() - start
        check("масштаб %d абзацев: быстро" % size, elapsed < 5.0, "%.2f с, %d слов" % (elapsed, words))


def test_rule_consistency():
    """Каждое имя правила из отчёта должно быть отключаемым."""
    text = ("Осуществляется проверка; модуль уникальный. "
            "Проверка была выполнена агентом. "
            "Агент удалил файл и стёр его. "
            + " ".join("слово%d" % n for n in range(1, 25)) + ".")
    _, out, _ = run_cli(["--json"], text)
    data = json.loads(out)
    for v in data["violations"]:
        rule = v["rule"]
        check("правило в списке отключаемых: " + rule, rule in L.all_rule_ids(), rule)
        # Отключение одного правила убирает его находки. Код может остаться 1,
        # потому что другие правила всё ещё срабатывают.
        _, out2, _ = run_cli(["--json", "--disable", rule], text)
        left = [x for x in json.loads(out2)["violations"] if x["rule"] == rule]
        check("находки правила исчезают: " + rule, left == [], repr(left))


# ---------------------------------------------------------------- отчёт

def main():
    quick = "--quick" in sys.argv
    tests = [
        test_hedge_promise, test_clean_prose, test_real_violations,
        test_syntax_syntax, test_regex_catastrophic, test_reentrant,
        test_markdown_shapes, test_fence_state, test_table_cells,
        test_cli_all, test_cli_encoding, test_cli_json_contract,
        test_json_matches_text_report, test_multiple_files,
        test_rule_consistency,
        test_deep_nesting, test_scale,
    ]
    if not quick:
        tests += [test_fuzz_mutation, test_fuzz_random_bytes]

    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            import traceback
            check(test.__name__, False, "ИСКЛЮЧЕНИЕ %s: %s" % (type(exc).__name__, exc))
            traceback.print_exc()

    total = len(RESULTS)
    bad = len(FAILURES)
    print("=" * 70)
    print("проверок: %d, провалено: %d" % (total, bad))
    print("=" * 70)
    if bad:
        seen = set()
        for name, detail in FAILURES:
            if name in seen:
                continue
            seen.add(name)
            print("ПРОВАЛ: %s" % name)
            if detail:
                print("        %s" % detail[:400])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
