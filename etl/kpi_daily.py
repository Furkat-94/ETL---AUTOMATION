# -*- coding: utf-8 -*-
"""
Подсчёт KPI операторов по проектам с анкетированием.

Повторяет ручную работу: поставил дату, выбрал оператора, поставил
фильтр результата, посмотрел «Показаны 1-20 из N записи».

Считает по каждому оператору за каждый день:
    ОТЗ — отказался отвечать
    ЗВ  — все звонки
    АН  — прошёл анкетирование
    Шт  — ставка за анкету (зависит от ДНЕВНОГО количества анкет)
    Сумма — Шт умножить на АН

Если включено несколько проектов, показатели по ним СКЛАДЫВАЮТСЯ
по каждому оператору: важно, сколько человек сделал за день, а не
на каком проекте он это сделал.

ВАЖНО ПРО ПРОФИЛИ
У каждого профиля CRM свои номера результатов звонка. В профиле Theta
анкетирование — это CallResult[Enum_2]=11, а в профиле Iota совсем
другое: CallResult[Enum_1]=21. Перепутать номера — значит молча
посчитать не то, поэтому они заданы отдельно для каждого проекта.

Пароли и логины в коде НЕ хранятся — только имена переменных.
Значения берутся из .env в корне репозитория и подставляются в CRM
ровно так, как записаны там: регистр букв и цифры имеют значение.
    THETA_USER=theta_user
    THETA_PASSWORD=пароль
    IOTA_USER=iota_user
    IOTA_PASSWORD=пароль
    KAPPA_USER=kappa_user
    KAPPA_PASSWORD=пароль

Профиль нужен только для того проекта, который считаешь. Если Iota
сейчас не идёт — строки IOTA можно оставить пустыми.

Результат пишется прямо в таблицу «KPI операторов»: колонка ищется по
дате в первой строке, строка — по номеру позиции в колонке A.

Нужны пакеты:
    pip install requests beautifulsoup4 python-dotenv pandas
"""
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from etl_core import SheetsLoader, DATA_DIR, CREDENTIALS, env

# ============================ НАСТРОЙКИ ============================

IP = env("CRM_HOST", "crm.local")
BASE = f"http://{IP}/crm"

# Спрашивать параметры при запуске. False — молча взять значения
# ниже. Выключай, если поставишь в Планировщик заданий: там некому
# отвечать, и скрипт повиснет на вводе.
ASK = True

# Значения по умолчанию. Их же скрипт предлагает в вопросах —
# достаточно нажать Enter. None — вчерашний день.
DATE_FROM = None
DATE_TO = None

# Куда сложить копию результата
OUT_DIR = DATA_DIR / "kpi"

# --- таблица «KPI операторов» ---
# CREDENTIALS импортируется из etl_core: credentials.json в корне, в git не попадает
SPREADSHEET_ID = env("KPI_SHEET_ID")

# Лист. None — собрать имя из даты: «Август 2026».
SHEET_NAME = None

# Только показать план, в таблицу не писать.
# При ASK = True вопрос про запись задаётся в конце, и эта
# настройка не используется.
DRY_RUN = True

# Писать ли «Шт» и «Сумма». По умолчанию НЕТ: в таблице они, скорее
# всего, формулы от АН и пересчитаются сами. Если там простые числа
# и они не обновляются — поставь True.
WRITE_RATE = False

# Проекты и их профили в CRM. При запуске скрипт спросит, какой
# считать: проекты сменяют друг друга, и каждый живёт в своём
# профиле со своими номерами результатов.
#
# Если выбрать оба, показатели СЛОЖАТСЯ по каждому оператору —
# на случай, когда в одном месяце шли два проекта сразу.
PROJECTS = {
    "theta": {
        "user": "THETA_USER",
        "password": "THETA_PASSWORD",
        "param": "CallResult[Enum_2]",
        "survey": 11,          # Прошёл анкетирование
        "refused": 13,         # Отказался отвечать
    },
    "iota": {
        "user": "IOTA_USER",
        "password": "IOTA_PASSWORD",
        # Номера проверены на реальных данных: выборочный прогон
        # сошёлся с таблицей.
        # Проект месяц стоял; если его заводили в CRM заново, номера
        # могли смениться — сверь первый прогон с экраном CRM.
        "param": "CallResult[Enum_1]",
        "survey": 21,         # Прошёл анкетирование
        "refused": 23,        # Отказался отвечать
        # Позиции 1–9 — Lambda, для Iota не считаются. Как и у
        # kappa: число звонков по ним узнаётся одним запросом,
        # чтобы итог сходился с CRM, но в оплату они не идут.
        "min_pos": 10,
    },
    "kappa": {
        "user": "KAPPA_USER",
        "password": "KAPPA_PASSWORD",
        # У каждого профиля свои номера результатов, и совпадений
        # между ними нет: Theta — Enum_2 (11/13), Iota — Enum_1
        # (21/23), kappa — Enum_3. Списывать с соседа нельзя.
        "param": "CallResult[Enum_3]",
        "survey": 31,         # Прошёл анкетирование
        "refused": 33,        # Отказался отвечать
        # Позиции ниже этой не считаются вовсе. У kappa операторы
        # с 1 по 9 — это Lambda, их звонки сюда не нужны. Такие
        # позиции даже не запрашиваются в CRM.
        "min_pos": 10,
    },
}

# Тарифная сетка: от скольких анкет за ДЕНЬ сколько платить за штуку.
# Смотрится по количеству анкет именно за этот день, не за месяц.
TARIFF = [
    (40, 900),            # 40 и больше — по 900
    (25, 600),            # 25..39      — по 600
    (0, 300),             # 0..24       — по 300
]

# Последняя позиция рабочего списка. Скрипт пишет только в строки
# «N Опер» с номером от 1 до этого числа. Подмена и Выбывшие
# не трогает: кто из подменных на какой позиции работал, скрипту
# неизвестно — их числа ложатся на верхнюю строку позиции, а вниз
# их переносят вручную.
MAX_WRITE_POS = 30

# Позиции с 1 по это число принадлежат проекту Lambda. Их нет
# в таблице анкетирования, и это норма — в итоге они показываются
# отдельной строкой, чтобы не путать с настоящими пропусками.
LAMBDA_MAX_POS = 9

# Пауза между запросами, секунд. Учётки общие с супервайзерами —
# сплошная очередь может сбросить им фильтры прямо во время работы.
PAUSE = 0.25

# ==================================================================

HERE = Path(__file__).parent
load_dotenv(HERE.parent / ".env")   # .env лежит в корне репозитория

LOGIN_URL = f"{BASE}/account/login"
CALLS_URL = f"{BASE}/calls/index"


def get_csrf(session: requests.Session, url: str) -> str:
    """Токен из <meta name="csrf-token">. Нужен при каждом POST."""
    soup = BeautifulSoup(session.get(url, timeout=15).text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    if not meta or not meta.get("content"):
        raise RuntimeError(f"CSRF-токен не найден на {url}")
    return meta["content"]


def login(user_key: str, pass_key: str) -> requests.Session:
    """Вход под профилем проекта. Логин и пароль берутся из .env."""
    user = os.environ.get(user_key)
    password = os.environ.get(pass_key)
    if not user or not password:
        raise RuntimeError(f"Нет {user_key} или {pass_key} — проверь .env")

    session = requests.Session()
    csrf = get_csrf(session, LOGIN_URL)
    session.post(LOGIN_URL, data={
        "_csrf": csrf,
        "LoginForm[username]": user,
        "LoginForm[password]": password,
    }, timeout=15)

    if "LoginForm" in session.get(CALLS_URL, timeout=15).text:
        raise RuntimeError(f"Вход не удался под {user} — проверь пароль")
    print(f"   вход под {user}")
    return session


def set_period(session: requests.Session, day: date) -> None:
    """
    Задаёт период. Это POST, а не параметр в адресе.

    Дата после него держится в сессии, поэтому дальше можно слать
    сколько угодно GET-запросов с фильтрами — период не слетит.
    """
    csrf = get_csrf(session, CALLS_URL)
    session.post(CALLS_URL, params={"Reset": 1}, data={
        "_csrf": csrf,
        "period_start": f"{day:%Y-%m-%d} 00:00:00",
        "period_end": f"{day:%Y-%m-%d} 23:59:59",
    }, timeout=30)


def parse_count(html: str) -> int:
    """
    Число записей из строки «Показаны 1-20 из N записи».

    Само это число и есть ответ: CRM уже посчитала, сколько строк
    подходит под фильтры, качать сами строки не нужно. Тысячи в
    разметке разделены пробелом («4 971»), поэтому оставляем только
    цифры. Нет блока совсем — значит ничего не нашлось, это ноль.
    """
    el = BeautifulSoup(html, "html.parser").find(class_="summary")
    if not el:
        return 0
    m = re.search(r"из\s+([\d\s\u00a0]+?)\s*запис", el.get_text(" ", strip=True))
    return int(re.sub(r"\D", "", m.group(1))) if m else 0


def count_calls(session, param: str, operator_value: str,
                enum: int = None) -> int:
    """
    Один запрос — одно число.

    Когда фильтр результата не нужен, параметр НЕ отправляется вовсе.
    Пустое значение здесь не игнорируется, а фильтрует по пустому
    результату — и обнуляет ответ. Проверено на реальных данных:
    без параметра у оператора есть звонки, с пустым — ровно 0.

    Что фильтр не залипает в сессии между запросами, тоже проверено:
    без фильтра, с фильтром анкет и снова без фильтра числа сходятся.
    """
    params = {"CallSearch[Operator]": operator_value}
    if enum is not None:
        params[param] = str(enum)

    resp = session.get(CALLS_URL, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(PAUSE)
    return parse_count(resp.text)


def count_day_total(session) -> int:
    """
    Сколько звонков у проекта за сутки — прямо с главного экрана,
    БЕЗ фильтра по оператору. Это то же число, что ты видишь в CRM.

    Нужен как НЕЗАВИСИМАЯ проверка. Сумма по операторам считается
    из тех же запросов, что и всё остальное, и сравнивать её саму с
    собой бессмысленно — совпадёт всегда. А итог с экрана получен
    отдельно: если какие-то звонки не привязаны ни к одному
    оператору, по нему это станет видно.

    Параметр оператора НЕ передаём вовсе: пустое значение в этой CRM
    не игнорируется, а фильтрует по пустому и даёт ноль.
    """
    resp = session.get(CALLS_URL, timeout=30)
    resp.raise_for_status()
    time.sleep(PAUSE)
    return parse_count(resp.text)


def operator_values(session) -> dict:
    """
    Соответствие «номер позиции -> значение фильтра».

    В выпадающем списке подпись «Operator10», а в запрос уходит
    другое число. В таблице позиции называются «10 Опер», то есть
    номером из подписи — по нему и связываем.
    """
    soup = BeautifulSoup(session.get(CALLS_URL, timeout=15).text, "html.parser")
    sel = soup.find("select", {"name": "CallSearch[Operator]"})
    if not sel:
        raise RuntimeError("Список операторов не найден на странице")

    out = {}
    for o in sel.find_all("option"):
        m = re.fullmatch(r"\s*operator\s*(\d+)\s*", o.get_text(), re.I)
        if m and o.get("value"):
            out[int(m.group(1))] = o["value"]
    return dict(sorted(out.items()))


def rate_for(surveys: int) -> int:
    """Ставка за одну анкету по дневному количеству."""
    for threshold, rate in TARIFF:
        if surveys >= threshold:
            return rate
    return 0


def collect(days: list, projects: dict = None) -> tuple:
    """
    Собирает показатели по выбранным проектам.

    По каждому проекту свой вход в CRM и свои номера результатов.
    Итоги складываются по паре «день + позиция оператора»: важно,
    сколько человек сделал за день, а не где именно.
    """
    parts = []
    # Позиции ниже порога min_pos: в оплату не идут, но их звонки
    # надо знать, чтобы в итоговой проверке сходилось с CRM и было
    # видно, куда делась разница.
    excluded = []
    crm_totals = {}          # (день, проект) -> итог с главного экрана
    for name, cfg in (projects or PROJECTS).items():
        # Проект без номеров результатов считать нельзя: подставив
        # чужие, получим правдоподобные, но неверные числа, и заметит
        # это только оператор, недополучивший деньги.
        missing = [k for k in ("param", "survey", "refused")
                   if cfg.get(k) is None]
        if missing:
            # Проверяем ВСЕ три, а не только часть. Если оставить
            # refused пустым, фильтр просто не отправится, и в отказы
            # попадут ВСЕ звонки оператора — число получится огромным
            # и при этом правдоподобным на вид.
            print(f"\n{name}: в PROJECTS не заполнено "
                  f"{', '.join(missing)} — пропускаю")
            continue
        print(f"\n{name}")
        session = login(cfg["user"], cfg["password"])
        values = operator_values(session)
        print(f"   позиций в списке: {len(values)}")

        for day in days:
            set_period(session, day)
            crm_totals[(day, name)] = count_day_total(session)
            min_pos = cfg.get("min_pos", 0)
            for pos, value in values.items():
                if pos < min_pos:
                    # В оплату не берём, но число звонков узнаём — одним
                    # запросом, без анкет и отказов. Иначе позиция
                    # исчезла бы молча, и итог с CRM разошёлся бы без
                    # объяснения.
                    n = count_calls(session, cfg["param"], value)
                    if n:
                        excluded.append({"Дата": day, "Проект": name,
                                         "Позиция": pos, "ЗВ": n})
                    continue
                calls = count_calls(session, cfg["param"], value)
                if calls == 0:
                    continue          # позиция в этот день не работала

                surveys = count_calls(session, cfg["param"], value,
                                      cfg["survey"])
                refused = count_calls(session, cfg["param"], value,
                                      cfg["refused"])
                parts.append({"Дата": day, "Позиция": pos, "Проект": name,
                              "ОТЗ": refused, "ЗВ": calls, "АН": surveys})
                print(f"   {day:%d.%m} Опер {pos:>2}:  ОТЗ {refused:>4}"
                      f"   ЗВ {calls:>5}   АН {surveys:>4}")

    if not parts:
        return pd.DataFrame(), excluded, crm_totals

    raw = pd.DataFrame(parts)
    # Складываем проекты по каждому оператору за день. Ставка
    # считается ПОСЛЕ сложения: она зависит от дневного числа анкет,
    # а не от того, на скольких проектах человек их набрал.
    df = raw.groupby(["Дата", "Позиция"], as_index=False)[
        ["ОТЗ", "ЗВ", "АН"]].sum()
    df["Шт"] = df["АН"].apply(rate_for)
    df["Сумма"] = df["Шт"] * df["АН"]
    return (df.sort_values(["Дата", "Позиция"]).reset_index(drop=True),
            excluded, crm_totals)


RU_MONTHS = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
             5: "Май", 6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь",
             10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}


def _col_letter(n: int) -> str:
    """Номер колонки (1 = A) в буквенное обозначение для диапазона."""
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def explain(plan, skipped, excluded, crm_totals, dups=None) -> None:
    """
    Объясняет простыми словами, откуда число в таблице.

    Идёт от итога CRM вниз: сколько всего звонков, какие из них не
    идут в таблицу и почему, сколько должно остаться — и сверяет с
    тем, что реально записывается.
    """
    excluded = excluded or []
    crm_totals = crm_totals or {}
    dups = dups or {}
    days = sorted({p[0] for p in plan} | {x["Дата"] for x in skipped}
                  | {x["Дата"] for x in excluded}
                  | {d for d, _ in crm_totals})

    for day in days:
        crm = {p: n for (d, p), n in crm_totals.items() if d == day}
        written = sum(int(v[1]) for d, _, _, v in plan if d == day)
        exc = [x for x in excluded if x["Дата"] == day]
        skp = [x for x in skipped if x["Дата"] == day]
        dup = [x for x in skp if int(x["Позиция"]) in dups]
        skp = [x for x in skp if int(x["Позиция"]) not in dups]
        tad = [x for x in skp if int(x["Позиция"]) <= LAMBDA_MAX_POS]
        oth = [x for x in skp if int(x["Позиция"]) > LAMBDA_MAX_POS]

        def zv(rows):
            return sum(int(x["ЗВ"]) for x in rows)

        def pos(rows):
            return ", ".join(str(p) for p in sorted(
                {int(x["Позиция"]) for x in rows}))

        print(f"\n   ИТОГ ЗА {day:%d.%m}")

        if not crm:
            print(f"      Записывается в таблицу   {written:>6}")
            continue

        crm_total = sum(crm.values())
        by_ops = written + zv(exc) + zv(skp) + zv(dup)
        no_op = crm_total - by_ops

        print(f"\n      Всего звонков в CRM      {crm_total:>6}")
        for p, n in crm.items():
            print(f"         {p:<22}{n:>6}")

        cuts = []
        if exc:
            cuts.append((zv(exc), f"позиции {pos(exc)}",
                         "Lambda — по правилу не считаем"))
        if tad:
            cuts.append((zv(tad), f"позиции {pos(tad)}",
                         "Lambda — в таблице их нет"))
        if oth:
            cuts.append((zv(oth), f"позиции {pos(oth)}",
                         "их нет в таблице — не наша команда"))
        if dup:
            cuts.append((zv(dup), f"позиции {pos(dup)}",
                         "номер в таблице дважды — не записано, исправь"))
        if no_op > 0:
            cuts.append((no_op, "без оператора",
                         "в CRM есть, но ни к кому не привязаны"))

        if cuts:
            print(f"\n      Не идут в таблицу:")
            for n, who, why in cuts:
                print(f"         − {n:>4}  {who}")
                print(f"                 {why}")

        expected = crm_total - sum(n for n, _, _ in cuts)
        mark = "✓ совпадает" if expected == written else "✗ НЕ СОВПАДАЕТ"
        print(f"\n      Должно быть в таблице    {expected:>6}")
        print(f"      Записывается в таблицу   {written:>6}   {mark}")

        if no_op > 0:
            print(f"\n      Внимание: {no_op} звонков в CRM ни к одному "
                  f"оператору не привязаны.")
            print(f"      Проверь их в CRM — в таблицу они не попадут.")
        if no_op < 0:
            print(f"\n      Внимание: по операторам вышло больше, чем "
                  f"в CRM, на {-no_op}.")
            print(f"      Так быть не должно — где-то звонок посчитан "
                  f"дважды.")
        if oth:
            print(f"\n      Позиции {pos(oth)} проверь глазами: вдруг "
                  f"кого-то забыли вписать в колонку A.")


def write_to_sheet(df: pd.DataFrame, dry_run: bool = True,
                   quiet: bool = False, excluded: list = None,
                   crm_totals: dict = None) -> None:
    """
    Пишет показатели в таблицу «KPI операторов».

    Колонку ищем ПО ДАТЕ в первой строке, а не отсчитываем от начала
    месяца: на листе бывают сдвинутые и просто неверные заголовки,
    и слепой отсчёт запишет цифры не в тот день. Строку так же ищем
    по номеру позиции в колонке A, а не по порядку: состав операторов
    меняется от месяца к месяцу.

    Если для даты или оператора места на листе нет — пишем
    предупреждение и пропускаем. Дорисовывать чужую таблицу опаснее,
    чем недописать: неверная зарплата обнаружится не сразу.
    """
    if df.empty:
        return

    loader = SheetsLoader(CREDENTIALS, SPREADSHEET_ID)
    loader.connect()

    day = df["Дата"].iloc[0]
    name = SHEET_NAME or f"{RU_MONTHS[day.month]} {day.year}"
    q = loader.quote_sheet

    try:
        grids = loader.batch_get([f"{q(name)}!A1:GZ1", f"{q(name)}!A1:A60"])
    except Exception as e:
        print(f"\nЛист «{name}» прочитать не удалось: {e}")
        return

    # Дата -> номер колонки. В первой строке даты стоят через пять
    # столбцов: ОТЗ, ЗВ, АН, Шт, Сумма.
    # Форматы дат. Google Sheets отдаёт их так, как показывает на
    # экране, а не в одном виде: в этой таблице «8/1/2026», то есть
    # месяц первым. Поэтому перебираем варианты, а не гадаем.
    DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                    "%d.%m.%Y", "%d.%m.%y",
                    "%d/%m/%Y")

    col_by_date = {}
    for i, v in enumerate(grids[0][0] if grids[0] else [], start=1):
        txt = str(v).strip()
        if not txt:
            continue
        for fmt in DATE_FORMATS:
            try:
                col_by_date[datetime.strptime(txt, fmt).date()] = i
                break
            except ValueError:
                continue

    # Позиция оператора -> номер строки. В колонке A записи вида
    # «5 Опер | Анна» — берём число в начале.
    #
    # Читаем ТОЛЬКО рабочий список, до первого служебного раздела.
    # Ниже идут «Подмена» и «Выбывшие». В «Выбывшие» у ушедших
    # сохранён их номер позиции — например «12 Опер | Анна», — и если
    # читать всю колонку, эта строка перезапишет рабочую строку
    # позиции 12 (раздел стоит ниже, значит встречается позже). Тогда
    # числа нового оператора уйдут ушедшему. Так и было.
    SECTION_HEADERS = ("Подмена", "Выбывшие")
    rows_of_pos = {}                 # позиция -> все строки с этим номером
    labels = {}                      # строка -> подпись, для сообщений
    for i, r in enumerate(grids[1] or [], start=1):
        txt = " ".join(str(r[0]).split()) if r else ""
        if txt in SECTION_HEADERS:
            break
        m = re.match(r"\s*(\d+)\s*Опер", txt, re.I)
        if m and int(m.group(1)) <= MAX_WRITE_POS:
            rows_of_pos.setdefault(int(m.group(1)), []).append(i)
            labels[i] = txt

    # Номер, встретившийся в рабочем списке дважды, НЕ пишем никуда.
    # Какая из строк правильная, скрипту не узнать: так было с 26 —
    # строка ушедшего оператора осталась с номером 26, а новому
    # сотруднику тоже подписали 26. Взять первую — значит
    # отдать звонки пустой строке; взять вторую — угадать. На зарплате
    # угадывать нельзя, поэтому останавливаемся и говорим, что чинить.
    row_by_pos = {p: rs[0] for p, rs in rows_of_pos.items() if len(rs) == 1}
    dups = {p: rs for p, rs in rows_of_pos.items() if len(rs) > 1}

    if not quiet:
        print(f"\nЛист «{name}»: дат {len(col_by_date)}, "
              f"операторов {len(row_by_pos)}")
    if dups and not quiet:
        print("\n   СТОП ПО ДВОЙНЫМ НОМЕРАМ — эти позиции в таблицу НЕ пишу:")
        for p, rs in sorted(dups.items()):
            where = ", ".join(f"строка {r} «{labels[r]}»" for r in rs)
            print(f"      позиция {p}: {where}")
        print("   Один номер — одна строка. Исправь подпись лишней строки "
              "в колонке A")
        print("   и запусти заново: тогда эти звонки запишутся.")
    if col_by_date and not quiet:
        sample = sorted(col_by_date)[:3]
        print("   найденные даты: " + ", ".join(
            f"{d:%d.%m} -> колонка {col_by_date[d]}" for d in sample))

    payload, plan, missing, skipped = [], [], set(), []
    for _, r in df.iterrows():
        col = col_by_date.get(r["Дата"])
        row = row_by_pos.get(r["Позиция"])
        if col is None:
            missing.add(f"нет колонки за {r['Дата']:%d.%m.%Y}")
            continue
        if row is None:
            # Считаем не только факт пропуска, но и сколько звонков
            # при этом не попадёт в таблицу. Иначе недостача видна
            # только потом, когда дневной итог не сойдётся с CRM.
            # Для двойного номера «нет строки» было бы неправдой —
            # строк как раз две. Про них уже сказано выше, в «СТОП».
            if int(r["Позиция"]) not in dups:
                missing.add(f"нет строки для позиции {r['Позиция']}")
            skipped.append(r)
            continue

        values = [int(r["ОТЗ"]), int(r["ЗВ"]), int(r["АН"])]
        if WRITE_RATE:
            values += [int(r["Шт"]), int(r["Сумма"])]
        cell = f"{_col_letter(col)}{row}"
        payload.append({"range": f"{q(name)}!{cell}", "values": [values]})
        plan.append((r["Дата"], r["Позиция"], cell, values))

    if not quiet:
        for note in sorted(missing):
            print(f"   {note}")
        explain(plan, skipped, excluded, crm_totals, dups)

    if not payload:
        if not quiet:
            print("   Писать нечего.")
        return

    if not quiet:
        print(f"   Будет записано {len(payload)} строк:")
        for d, pos, cell, v in plan[:12]:
            print(f"      {d:%d.%m}  Опер {pos:>2}  {cell:<6} {v}")
        if len(plan) > 12:
            print(f"      ... и ещё {len(plan) - 12}")

    if dry_run:
        if not ASK:
            print("\n   Ничего не записано. Чтобы записать, "
                  "поставь DRY_RUN = False.")
        return

    loader.sh.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": payload,
    })
    print(f"   Записано в лист «{name}»: строк {len(payload)}.")


def ask_date(label: str, default: date) -> date:
    """
    Спрашивает дату. Пустой ответ — значение по умолчанию.

    При кривом вводе переспрашиваем, а не падаем: ошибиться в дате
    легко, а считать не тот период — потом искать, откуда взялись
    чужие цифры в зарплате.
    """
    while True:
        raw = input(f"{label} [{default:%Y-%m-%d}]: ").strip()
        if not raw:
            return default
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("   Не понял. Формат: 2026-08-18")


def ask_projects() -> dict:
    """
    Спрашивает, какие проекты считать.

    Пустой ответ — все включённые. Если выбрано несколько, их
    показатели складываются по каждому оператору.
    """
    names = list(PROJECTS)
    if len(names) < 2:
        return dict(PROJECTS)

    print("   Проекты: " + ", ".join(names))
    while True:
        raw = input("Какой проект считать [все, со сложением]: ").strip().lower()
        if not raw:
            return dict(PROJECTS)

        chosen, unknown = {}, []
        for part in re.split(r"[,\s]+", raw):
            if not part:
                continue
            hit = [n for n in names if part in n.lower()]
            if hit:
                chosen.update({n: PROJECTS[n] for n in hit})
            else:
                unknown.append(part)

        if unknown:
            print(f"   Не нашёл: {', '.join(unknown)}")
            continue
        if chosen:
            return chosen


def ask_write() -> bool:
    """Спрашивает, писать ли в таблицу. По умолчанию — нет."""
    raw = input("\n   Записать в таблицу? [нет/да]: ").strip().lower()
    return raw in ("да", "д", "yes", "y")


def main() -> None:
    yesterday = date.today() - timedelta(days=1)
    d_from = DATE_FROM or yesterday
    d_to = DATE_TO or yesterday
    projects = dict(PROJECTS)
    dry_run = DRY_RUN

    if ASK:
        d_from = ask_date("Период с", d_from)
        d_to = ask_date("Период по", max(d_to, d_from))
        if d_to < d_from:
            d_from, d_to = d_to, d_from
        projects = ask_projects()

    days = []
    d = d_from
    while d <= d_to:
        days.append(d)
        d += timedelta(days=1)

    df, excluded, crm_totals = collect(days, projects)
    if df.empty:
        print("\nНи по одной позиции звонков не найдено.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = (f"kpi_{d_from:%Y-%m-%d}.csv" if d_from == d_to
            else f"kpi_{d_from:%Y-%m-%d}_{d_to:%Y-%m-%d}.csv")
    path = OUT_DIR / name
    df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")

    print("\nИТОГО ПО ДНЯМ")
    by_day = df.groupby("Дата")[["ЗВ", "АН", "ОТЗ", "Сумма"]].sum()
    for d, r in by_day.iterrows():
        print(f"   {d:%d.%m}: звонков {int(r['ЗВ']):>5}, анкет "
              f"{int(r['АН']):>4}, отказов {int(r['ОТЗ']):>4}, "
              f"к оплате {int(r['Сумма']):>8,} сум".replace(",", " "))

    total = int(df["Сумма"].sum())
    print(f"\n   Всего к оплате: {total:,} сум".replace(",", " "))
    print(f"   Файл: {path}")

    # Сначала показываем план, потом спрашиваем. Так решение
    # принимается по конкретным ячейкам, а не вслепую.
    # Второй вызов идёт молча: план уже на экране, повторять незачем.
    write_to_sheet(df, dry_run=True, excluded=excluded,
                   crm_totals=crm_totals)
    if ASK:
        if ask_write():
            write_to_sheet(df, dry_run=False, quiet=True)
        else:
            print("   Отменено — в таблицу ничего не записано.")
    elif not dry_run:
        write_to_sheet(df, dry_run=False, quiet=True)


if __name__ == "__main__":
    main()
