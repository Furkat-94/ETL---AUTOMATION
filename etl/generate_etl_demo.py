# -*- coding: utf-8 -*-
"""
Демо-выгрузки CRM и АТС для ноутбуков etl/.

Настоящие выгрузки — данные заказчиков, в репозитории их нет. Скрипт
кладёт в data/ файлы той же структуры и под теми же именами, что
ждут ноутбуки, — чтобы их можно было запустить без доступа к CRM:

    alpha_crm.xlsx + alpha_pbx.xls        Alpha: реестр CRM + реестр АТС
    omega_crm.xlsx                        Omega: только реестр CRM
    <проект>_crm.xlsx + <проект>_pbx.xls  Beta…Eta: CRM + почасовой отчёт АТС

Форматы взяты из кода чтения (etl_core.ExcelReader и ноутбуки), а
не придуманы:
    CRM         — .xlsx, шапка в первой строке, колонки ищутся по имени;
    реестр АТС  — .xls, две строки шапки, колонки по номерам 0–8 и 20;
    почасовой   — .xls, две строки шапки, 24 часа и строка «Итого»,
    отчёт АТС     количество звонков в колонках 0–6, средний разговор
                  в колонке 8, уровень обслуживания в колонке 15.
Колонки, которые код не читает, оставлены пустыми: что в них лежит
в настоящих выгрузках, по коду не узнать.

В данные заложены правила, ради которых написан код:
    - CRM теряет первую запись запрошенного периода;
    - период три дня, как DAYS в crm_reports.py, первый — буферный;
    - в воскресенье операторы Alpha не работают, CRM за день пуст;
    - числа от тысячи в строке «Итого» АТС приходят как «1 036».

    python generate_etl_demo.py          (из папки etl/)

Нужен пакет xlwt: АТС отдаёт старый формат .xls, и pandas его
читает, но записать уже не умеет.
"""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import xlwt

from etl_core import DATA_DIR

# ============================ НАСТРОЙКИ ============================

# Последний день выгрузки. Дата фиксированная, а не «вчера»: так
# ноутбуки на демо-данных показывают одни и те же цифры в любой день.
# 17.08.2026 — понедельник: в выгрузке суббота (буферная),
# воскресенье и понедельник.
END_DAY = date(2026, 8, 17)

# Сколько дней в выгрузке CRM — столько же, сколько качает crm_reports.py
DAYS = 3

# Одно и то же зерно — одни и те же файлы при каждом запуске
SEED = 17

# Входящих в будний день по проектам «Мониторинга». Gamma нарочно
# больше тысячи: тогда итог АТС приходит как «1 036», и видно, что
# код это разбирает.
MONITORING = {"Beta": 320, "Gamma": 1500, "Delta": 30,
              "Epsilon": 20, "Zeta": 12, "Eta": 90}

# У мелких проектов ночного трафика нет: день начинается сразу
# с рабочих часов (см. USE_BUFFER_DAY в monitoring.ipynb)
DAYTIME_ONLY = {"Delta", "Epsilon", "Zeta"}

# Сколько операторов на линии у каждого проекта
TEAM_SIZE = {"Beta": 6, "Gamma": 14, "Delta": 2, "Epsilon": 1,
             "Zeta": 1, "Eta": 3, "Omega": 4}

ALPHA_CALLS = 260          # входящих на линию Alpha в будний день
OMEGA_CALLS = 140          # звонков Omega в будний день
ALPHA_WORK_HOURS = range(8, 20)   # часы, когда на линии Alpha есть операторы

# Внутренний номер линии -> как имя оператора пишет АТС и как CRM.
# В АТС регистр разный (Operator1 / operator2), поэтому ноутбук
# сопоставляет операторов по номеру линии, а не по имени.
ALPHA_LINES = {
    "Внутр. 101": ("Operator1", "Operator1"),
    "Внутр. 102": ("operator2", "Operator2"),
    "Внутр. 103": ("Operator3", "Operator3"),
}
ALPHA_LINE_NUMBER = "7000"   # номер входящей линии, один на весь день

# Доля звонков по часам суток: ночью почти пусто, днём два пика
HOUR_WEIGHTS = [0.4, 0.2, 0.1, 0.1, 0.1, 0.3, 1.0, 3.0, 7.0, 8.5, 8.0, 7.5,
                6.5, 7.0, 7.5, 7.5, 7.0, 6.5, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]

# Выходные тише будней: суббота и воскресенье от буднего дня
WEEKEND_SHARE = {5: 0.6, 6: 0.35}

TOPICS = ["Статус заявки", "Консультация", "Изменение данных",
          "Жалоба", "Оплата", "Другое"]

RES_ACCEPTED = "Обработан первым оператором"
RES_LOST = "Потерян"
RES_IVR = "Обработан IVR"

CRM_COLUMNS = ["ID звонка", "Направление звонка", "Номер телефона",
               "Время начала звонка", "Время конца звонка",
               "Продолжительность, сек", "Удержание, сек", "Обработка, сек",
               "Оператор", "Тема звонка / вопросы"]

# ==================================================================

rng = np.random.default_rng(SEED)
PERIOD = [END_DAY - timedelta(days=i) for i in reversed(range(DAYS))]


def day_volume(base: int, day: date) -> int:
    """Звонков за день: будни полные, выходные тише, плюс разброс."""
    base = base * WEEKEND_SHARE.get(day.weekday(), 1.0)
    return max(0, int(rng.normal(base, base * 0.08)))


def hour_weights(daytime_only: bool = False) -> np.ndarray:
    """Суточный профиль как доли. Мелким проектам ночь обнуляется."""
    w = np.array(HOUR_WEIGHTS)
    if daytime_only:
        w = np.where((np.arange(24) >= 8) & (np.arange(24) < 20), w, 0)
    return w / w.sum()


def time_in_hour(day: date, hour: int) -> datetime:
    """Случайная секунда внутри часа."""
    return datetime.combine(day, datetime.min.time()) + timedelta(
        hours=int(hour), seconds=int(rng.integers(0, 3600)))


def phone() -> int:
    """Номер абонента: десять цифр, как в демо SQL-части."""
    return int(9_000_000_000 + rng.integers(0, 999_999_999))


def talk_seconds() -> int:
    """
    Длительность разговора. Изредка — 2–5 секунд: у Alpha такие
    звонки по правилу заказчика стоят 0 минут, пусть они будут.
    """
    if rng.random() < 0.03:
        return int(rng.integers(2, 6))
    return max(6, int(rng.lognormal(4.6, 0.6)))


def hms(sec: int) -> str:
    """Секунды -> «0:02:07», как АТС пишет длительность."""
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def pbx_number(n: int, sep: str = " ") -> object:
    """
    Число в итоговой строке АТС. От тысячи — текстом с разделителем
    разрядов, «1 036»: именно так АТС отдаёт итоги, и ради этого в
    etl_core есть _to_num.
    """
    if n < 1000:
        return n
    return f"{n:,}".replace(",", sep)


def team(project: str, first_no: int) -> tuple:
    """
    Операторы проекта и их доли звонков. Нагрузка нарочно неровная:
    иначе в аналитике по операторам сравнивать нечего.
    """
    size = TEAM_SIZE[project]
    names = [f"Operator{first_no + i}" for i in range(size)]
    weights = np.linspace(1.5, 0.5, size)
    return names, weights / weights.sum()


def crm_call(start: datetime, direction: str, number: int, sec: int,
             operator: str) -> dict:
    """Одна строка выгрузки CRM «Детализация»."""
    return {
        "Направление звонка": direction,
        "Номер телефона": number,
        "Время начала звонка": start,
        "Время конца звонка": start + timedelta(seconds=sec),
        "Продолжительность, сек": sec,
        "Удержание, сек": int(rng.integers(0, 30)) if sec else 0,
        "Обработка, сек": int(rng.integers(5, 60)) if sec else 0,
        "Оператор": operator,
        "Тема звонка / вопросы": str(rng.choice(TOPICS)) if sec else "",
    }


def save_crm(rows: list, name: str, first_id: int) -> int:
    """
    Сохраняет выгрузку CRM. Возвращает, сколько строк записано.

    ID растёт вместе со временем звонка — как в настоящей CRM
    (на этом держится разбор в reconciliation.ipynb).

    Самая ранняя запись периода выбрасывается: настоящая CRM теряет
    её при выгрузке. Из-за этого период и берётся с буферным днём —
    теряется звонок буферного дня, который всё равно не грузится.
    """
    df = pd.DataFrame(rows, columns=CRM_COLUMNS[1:])
    df = df.sort_values("Время начала звонка").reset_index(drop=True)
    df.insert(0, "ID звонка", range(first_id, first_id + len(df)))
    df = df.iloc[1:]
    df.to_excel(DATA_DIR / name, index=False)
    return len(df)


def save_xls(name: str, title: str, header: dict, rows: list) -> None:
    """
    Пишет выгрузку АТС в старом формате .xls.

    Строка 0 — заголовок отчёта, строка 1 — подписи колонок, дальше
    данные: код читает такие файлы с skiprows=2. header — {номер
    колонки: подпись}; колонок, которых нет в header, код не читает.
    """
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Лист1")
    ws.write(0, 0, title)
    for col, text in header.items():
        ws.write(1, col, text)
    for r, row in enumerate(rows, start=2):
        for c, v in enumerate(row):
            if v != "":
                ws.write(r, c, v)
    wb.save(str(DATA_DIR / name))


# ------------------------------ Alpha ------------------------------

def make_alpha() -> None:
    """
    Alpha: реестр АТС (строка на звонок) и реестр CRM.

    Принятый звонок в АТС и его запись в CRM — один и тот же разговор:
    тот же номер, CRM стартует на несколько секунд позже. Исходящие
    есть только в CRM — часть из них перезвоны по потерянным.
    """
    registry, crm = [], []
    lines = list(ALPHA_LINES)
    for day in PERIOD:
        # В воскресенье операторы не работают: АТС звонки видит
        # (IVR и потерянные), а в CRM за день нет ни строки
        works_today = day.weekday() != 6
        n = day_volume(ALPHA_CALLS, day)
        hours = rng.choice(24, size=n, p=hour_weights())
        for t in sorted(time_in_hour(day, h) for h in hours):
            number = phone()
            ivr = int(rng.integers(8, 40))
            on_duty = works_today and t.hour in ALPHA_WORK_HOURS
            r = rng.random()
            if r < 0.15:
                result = RES_IVR
            elif not on_duty or r < 0.27:
                result = RES_LOST
            else:
                result = RES_ACCEPTED

            line, pbx_name, talk, total = "", "", "", ivr
            if result == RES_LOST:
                total += int(rng.integers(10, 120))         # ждал и бросил
            if result == RES_ACCEPTED:
                line = str(rng.choice(lines, p=[0.45, 0.35, 0.20]))
                pbx_name, crm_name = ALPHA_LINES[line]
                sec = talk_seconds()
                talk = hms(sec)
                total += sec
                start = t + timedelta(seconds=int(rng.integers(3, 16)))
                crm.append(crm_call(start, "Входящий", number, sec, crm_name))

            # Колонки 0–8 и 20 читает ExcelReader.read_pbx_registry,
            # 9–19 он пропускает — они пустые
            registry.append([t.strftime("%d.%m.%Y"), t.strftime("%H:%M:%S"),
                             result, ALPHA_LINE_NUMBER, f"+{number}",
                             hms(ivr), line, pbx_name, talk]
                            + [""] * 11 + [hms(total)])

            # Перезвон по потерянному — в тот же день, в рабочие часы
            if result == RES_LOST and works_today and rng.random() < 0.6:
                back = t + timedelta(minutes=int(rng.integers(5, 90)))
                if back.date() == day and back.hour in ALPHA_WORK_HOURS:
                    sec = 0 if rng.random() < 0.25 else talk_seconds()
                    crm.append(crm_call(back, "Исходящий", number, sec,
                                        ALPHA_LINES[str(rng.choice(lines))][1]))

    save_xls("alpha_pbx.xls", "Демо: реестр звонков АТС",
             {0: "Дата", 1: "Время", 2: "Результат", 3: "Номер линии",
              4: "Номер", 5: "IVR", 6: "Внутренний номер",
              7: "Имя оператора", 8: "Продолжительность", 20: "Итого"},
             registry)
    n_crm = save_crm(crm, "alpha_crm.xlsx", first_id=610000)
    print(f"  alpha_pbx.xls      {len(registry):>5} звонков в реестре АТС")
    print(f"  alpha_crm.xlsx     {n_crm:>5} строк CRM "
          f"(воскресенье пустое, первая запись периода потеряна)")


# ------------------------------ Omega ------------------------------

def make_omega() -> None:
    """Omega: только реестр CRM, входящие и обзвон."""
    names, weights = team("Omega", first_no=11)
    rows = []
    for day in PERIOD:
        n = day_volume(OMEGA_CALLS, day)
        hours = rng.choice(24, size=n, p=hour_weights(daytime_only=True))
        for h in hours:
            outgoing = rng.random() < 0.2
            sec = 0 if outgoing and rng.random() < 0.3 else talk_seconds()
            rows.append(crm_call(time_in_hour(day, h),
                                 "Исходящий" if outgoing else "Входящий",
                                 phone(), sec, str(rng.choice(names, p=weights))))
    n_crm = save_crm(rows, "omega_crm.xlsx", first_id=710000)
    print(f"  omega_crm.xlsx     {n_crm:>5} строк CRM")


# ---------------------------- Мониторинг ----------------------------

def pbx_hour(arrived: int, hour: int, big: bool) -> dict:
    """
    Разбивает пришедшие за час звонки так, как их считает АТС:
    IVR, первый оператор, операторы, внешний агент, потерянные.
    Рано утром и поздно вечером теряется больше: смена неполная.
    """
    ivr = rng.binomial(arrived, 0.10)
    rest = arrived - ivr
    lost = rng.binomial(rest, 0.25 if hour < 9 or hour >= 20 else 0.08)
    rest -= lost
    ext = rng.binomial(rest, 0.02) if big else 0     # перевод во внешний агент
    rest -= ext
    second = rng.binomial(rest, 0.03)                # взял не первый оператор
    first = rest - second
    # int(): numpy-числа xlwt записать не умеет
    return {"IVR": int(ivr), "Первый": int(first), "Операторы": int(second),
            "Внешний": int(ext), "Потеряно": int(lost)}


def make_monitoring_project(project: str, base: int, first_no: int) -> None:
    """
    Проект «Мониторинга»: почасовой отчёт АТС за последний день и
    выгрузка CRM за весь период (буферные дни плюс рабочий).

    Входящие в CRM рабочего дня — это звонки, дошедшие до оператора
    по отчёту АТС, час в час. Исходящие — перезвоны по потерянным;
    у мелких проектов их 0–1 в день.
    """
    names, weights = team(project, first_no)
    small = project in DAYTIME_ONLY
    big = base >= 300
    p_hours = hour_weights(daytime_only=small)
    crm = []

    def add_crm(day: date, hour: int, direction: str) -> None:
        sec = talk_seconds()
        if direction == "Исходящий" and rng.random() < 0.3:
            sec = 0                                  # не дозвонились
        crm.append(crm_call(time_in_hour(day, hour), direction, phone(), sec,
                            str(rng.choice(names, p=weights))))

    def add_outgoing(day: date, lost: int) -> None:
        n_out = int(rng.integers(0, 2)) if small else rng.binomial(lost, 0.5)
        for h in rng.choice(24, size=n_out, p=hour_weights(daytime_only=True)):
            add_crm(day, h, "Исходящий")

    # Буферные дни: АТС за них не нужен, только CRM
    for day in PERIOD[:-1]:
        arrived = rng.multinomial(day_volume(base, day), p_hours)
        lost = 0
        for h in range(24):
            part = pbx_hour(arrived[h], h, big)
            lost += part["Потеряно"]
            for _ in range(part["Первый"] + part["Операторы"]):
                add_crm(day, h, "Входящий")
        add_outgoing(day, lost)

    # Рабочий день: почасовой отчёт АТС и CRM, согласованные по часам
    day = PERIOD[-1]
    arrived = rng.multinomial(day_volume(base, day), p_hours)
    rows, totals = [], {k: 0 for k in ["IVR", "Первый", "Операторы",
                                       "Внешний", "Потеряно", "Итого"]}
    for h in range(24):
        part = pbx_hour(arrived[h], h, big)
        answered = part["Первый"] + part["Операторы"]
        total = sum(part.values())
        for _ in range(answered):
            add_crm(day, h, "Входящий")
        for k, v in part.items():
            totals[k] += v
        totals["Итого"] += total

        avg_talk = hms(rng.normal(150, 25)) if answered else ""
        # Уровень обслуживания АТС считает сама, в процентах;
        # в тихий час без звонков ячейка пустая
        sl = ""
        if answered:
            share_lost = part["Потеряно"] / max(total, 1)
            sl = round(float(np.clip(rng.normal(92 - 60 * share_lost, 3),
                                     40, 100)), 1)
        rows.append([f"{h}:00:00", part["IVR"], part["Первый"],
                     part["Операторы"], part["Внешний"], part["Потеряно"],
                     total, "", avg_talk] + [""] * 6 + [sl])
    add_outgoing(day, totals["Потеряно"])

    # Строка «Итого». Разделитель разрядов у «Первого оператора» —
    # неразрывный пробел, у остальных обычный: бывают оба
    rows.append(["Итого", pbx_number(totals["IVR"]),
                 pbx_number(totals["Первый"], "\xa0"),
                 pbx_number(totals["Операторы"]),
                 pbx_number(totals["Внешний"]),
                 pbx_number(totals["Потеряно"]),
                 pbx_number(totals["Итого"])])

    key = project.lower()
    save_xls(f"{key}_pbx.xls", f"Демо: почасовой отчёт АТС, {project}",
             {0: "Время", 1: "IVR", 2: "Первый оператор", 3: "Операторы",
              4: "Внешний агент", 5: "Потеряно", 6: "Итого",
              8: "Обработка операторами", 15: "Уровень обслуживания, %"},
             rows)
    n_crm = save_crm(crm, f"{key}_crm.xlsx", first_id=first_no * 10000)
    print(f"  {key + '_pbx.xls':<18} входящих за {day:%d.%m}: "
          f"{totals['Первый']:>5}, потеряно {totals['Потеряно']:>4}")
    print(f"  {key + '_crm.xlsx':<18} {n_crm:>5} строк CRM за {DAYS} дня")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Период CRM: {PERIOD[0]:%d.%m.%Y} — {PERIOD[-1]:%d.%m.%Y}, "
          f"буферный день {PERIOD[0]:%d.%m}\n")
    make_alpha()
    make_omega()
    for i, (project, base) in enumerate(MONITORING.items()):
        make_monitoring_project(project, base, first_no=21 + i * 20)
    print(f"\nФайлы в {DATA_DIR}")
    print("Дальше: ноутбуки alpha_registry, omega_registry, monitoring "
          "(в .env DEMO=1 — запись в Excel вместо Google Sheets)")


if __name__ == "__main__":
    main()
