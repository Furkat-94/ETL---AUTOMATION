# -*- coding: utf-8 -*-
"""
Месячный итог KPI операторов Theta — для расчёта зарплаты.

Каждый день kpi_daily.py считает ОТЗ, ЗВ, АН и записывает в
таблицу «KPI операторов», а «Шт» и «Сумма» досчитываются там формулой.
Этот скрипт ничего не пересчитывает — просто складывает уже готовые
дневные числа за нужный месяц. Тарифная сетка гарантированно верна:
она посчитана один раз, в таблице, а не продублирована здесь.

    python kpi_monthly.py

СЧЁТ ПО ИМЕНИ, А НЕ ПО ПОЗИЦИИ
За месяц человек мог посидеть на нескольких позициях — закончил
один проект, отдохнул, начал другой. Позиция — это рабочее место,
имя — это человек, и зарплату считают на человека. Поэтому итог
собирается по имени из подписи в колонке A («12 Опер | Анна»),
а не по номеру позиции: сколько бы позиций человек ни сменил за
месяц, он попадёт в отчёт одной строкой.

ВАЖНАЯ ОГОВОРКА
Подпись в колонке A — ОДНА на позицию, на весь месяц. Если человек
ушёл с позиции и на неё сел кто-то другой, а подпись в таблице
обновили на нового — прежние дни на этой позиции в отчёте по имени
достанутся новому человеку, хотя их отработал прежний. Так уже было
в июле. Скрипт этого различить не может — он видит только то, что
написано в таблице сейчас. Поэтому рядом всегда лежит вкладка
«По дням» с разбивкой по каждой позиции и дню: перед тем как
отправлять итог супервайзерам, стоит свериться по ней, если в
течение месяца кто-то пересаживался.

Результат — Excel-файл с двумя вкладками:
    «Итог по именам» — то, что уходит супервайзерам
    «По дням»         — сырая раскладка для проверки

Логин Google не нужен — то же приложение, что у остальных скриптов:
    credentials.json в корне репозитория
"""
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from etl_core import SheetsLoader, RU_MONTHS, DATA_DIR, CREDENTIALS, env

BASE_DIR = str(DATA_DIR)   # выгрузки лежат в папке data/ в корне репозитория
# CREDENTIALS импортируется из etl_core: credentials.json в корне, в git не попадает
# Спрашивать год-месяц при запуске. False — молча взять значения ниже.
ASK = True

# Та же таблица, что заполняет kpi_daily.py.
SPREADSHEET_ID = env("KPI_SHEET_ID")
SHEET_NAME = None                   # None — собрать из года-месяца

# Значения по умолчанию — то же, что скрипт предложит на вопросе.
YEAR, MONTH = 2026, 8

# Куда сохранить файл
OUT_DIR = DATA_DIR / "kpi"

# Даты в первой строке — по пять колонок на день: ОТЗ, ЗВ, АН, Шт, Сумма.
DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y")


def ask_month(default_year: int, default_month: int) -> tuple:
    """Спрашивает год и месяц. Понимает «2026-08» и просто «08»."""
    while True:
        raw = input(f"Год-месяц (ГГГГ-ММ) "
                    f"[{default_year}-{default_month:02d}]: ").strip()
        if not raw:
            return default_year, default_month
        try:
            if "-" in raw:
                y, m = raw.split("-")
                y, m = int(y), int(m)
            else:
                y, m = default_year, int(raw)
            if 1 <= m <= 12:
                return y, m
        except ValueError:
            pass
        print("   Не понял. Формат: 2026-08 или просто 08")


def _col_letter(n: int) -> str:
    """Номер колонки (1 = A) в буквенное обозначение диапазона."""
    return get_column_letter(n)


def find_month_columns(row1: list, year: int, month: int) -> dict:
    """
    Колонки-начала дневных блоков за нужный месяц — с датой каждой.

    Дата может быть записана по-разному — «8/17/2026», «17.08.2026»,
    как Google Sheets её в итоге отдаёт, — поэтому перебираем
    форматы, а не полагаемся на один. Возвращает {колонка: дата},
    а не просто список: дата дальше нужна для вкладки «По дням».
    """
    out = {}
    for i, v in enumerate(row1, start=1):
        txt = str(v).strip()
        if not txt:
            continue
        for fmt in DATE_FORMATS:
            try:
                d = datetime.strptime(txt, fmt).date()
                if d.year == year and d.month == month:
                    out[i] = d
                break
            except ValueError:
                continue
    return out


# Строки, с которых начинаются служебные разделы листа. Всё между
# ними и следующим таким же заголовком — не обычная позиция, а
# отдельная группа людей: подменные операторы из другого филиала
# подключаются, когда своих не хватает, и у них нет номера
# позиции — только имя.
SECTION_HEADERS = ("Подмена", "Выбывшие")


def read_operators(col_a: list) -> dict:
    """
    Строка -> (позиция, имя, подпись целиком, раздел).

    Обычная позиция — «10 Опер | Анна»: позиция 10, имя Анна.
    Без имени в подписи («13 Опер») — сама по себе, под номером,
    сгруппировать её с кем-то по имени нельзя.

    Подмена — просто «Иван Петров», без номера впереди: позиция
    None, имя — сама подпись.

    Выбывшие читаем ТОЖЕ, а не пропускаем. Человек, ушедший в
    середине месяца, свои отработанные дни заслужил, и если строку
    выбросить целиком, он останется без оплаты. Раздел запоминаем,
    чтобы ниже спросить день ухода.
    """
    out = {}
    section = None
    for i, r in enumerate(col_a, start=1):
        txt = " ".join(str(r[0]).split()) if r else ""
        if not txt:
            continue
        if txt in SECTION_HEADERS:
            section = txt
            continue

        m = re.match(r"(\d+)\s*Опер\s*\|?\s*(.*)", txt, re.I)
        if m:
            pos, name = int(m.group(1)), m.group(2).strip()
            out[i] = (pos, name or None, txt, section)
        elif section in ("Подмена", "Выбывшие"):
            out[i] = (None, txt, txt, section)
    return out


def to_num(v) -> float:
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def build_detail(loader, sheet_name: str, year: int, month: int) -> tuple:
    """
    Собирает сырые дневные строки: одна строка — одна позиция за
    один день, где по ней было хоть что-то ненулевое.

    Все строки операторов читаются ОДНИМ batch_get, а не по одному
    вызову в цикле — иначе полсотни операторов дали бы полсотни
    обращений к Google Sheets вместо одного.
    """
    q = loader.quote_sheet
    row1_res, col_a = loader.batch_get(
        [f"{q(sheet_name)}!A1:GZ1", f"{q(sheet_name)}!A1:A200"])
    row1 = row1_res[0] if row1_res else []

    date_by_col = find_month_columns(row1, year, month)
    operators = read_operators(col_a)
    if not date_by_col:
        return pd.DataFrame(), {}
    print(f"Дней в месяце с данными: {len(date_by_col)}, "
          f"операторов на листе: {len(operators)}")

    last_col = _col_letter(max(date_by_col) + 4)
    ranges = [f"{q(sheet_name)}!A{r}:{last_col}{r}" for r in operators]
    grid = loader.batch_get(ranges) if ranges else []

    rows = []
    for (row_no, (pos, name, label, section)), row_result in zip(
            operators.items(), grid):
        # Диапазон в одну строку — Sheets отдаёт его как список из
        # ОДНОЙ строки-списка, тот же формат, что и для row1 выше.
        values = row_result[0] if row_result else []
        for col, day in date_by_col.items():
            i = col - 1
            otz = to_num(values[i]) if i < len(values) else 0
            zv = to_num(values[i + 1]) if i + 1 < len(values) else 0
            an = to_num(values[i + 2]) if i + 2 < len(values) else 0
            summ = to_num(values[i + 4]) if i + 4 < len(values) else 0
            if otz or zv or an or summ:
                rows.append({
                    "Дата": day, "Позиция": pos if pos is not None else "",
                    "Оператор": label, "Имя": name or "",
                    "Раздел": section or "",
                    "ОТЗ": int(otz), "ЗВ": int(zv),
                    "АН": int(an), "Сумма": int(summ),
                })
    return pd.DataFrame(rows), operators


# Дни ухода, если уже известны: {позиция: "ГГГГ-ММ-ДД"}, например
# {12: "2026-09-12"}. Заполняется, чтобы не отвечать на те же вопросы
# при каждом перезапуске: что здесь есть — про то не спрашивается.
DEPARTURES = {}


def find_handovers(detail: pd.DataFrame, operators: dict) -> dict:
    """
    Находит позиции, где за месяц сменился человек.

    Как устроена таблица. Ушедший переезжает в раздел «Выбывшие»
    вместе со своим номером позиции («12 Опер | Анна»), а наверху
    на этой позиции имя убирают — остаётся голый «12 Опер». Числа
    при этом продолжают копиться на ВЕРХНЕЙ строке, за весь месяц
    подряд: и те дни, что отработал ушедший, и те, что отработал
    пришедший ему на смену.

    Значит одну строку надо разделить между двумя людьми, а границу
    знает только человек — дата увольнения лежит в чек-листе, к
    которому у скрипта доступа нет.

    Возвращает {позиция: (кто был, кто теперь)}. «Кто теперь» — имя
    сверху, если его уже вписали, иначе None: тогда после ухода там
    работал либо новичок без подписи, либо кто-то из подмена.
    """
    top, gone = {}, {}
    for pos, name, label, section in operators.values():
        if pos is None:
            continue
        if section == "Выбывшие":
            gone[pos] = name or label
        elif section is None:
            top[pos] = name

    with_data = set(detail.loc[detail["Позиция"] != "", "Позиция"])
    return {pos: (gone[pos], top.get(pos))
            for pos in gone if pos in top and pos in with_data}


def show_activity(detail: pd.DataFrame, pos) -> None:
    """
    Показывает, в какие дни на позиции были звонки.

    Перерыв в середине — сильная подсказка: человек ушёл, позиция
    постояла пустой, потом на неё сел другой. Точную дату это не
    даёт, но подсказывает, где её искать в чек-листе.
    """
    g = detail[detail["Позиция"] == pos].sort_values("Дата")
    days = sorted(g["Дата"].unique())
    if not days:
        return

    line, prev = [], None
    for d in days:
        if prev and (d - prev).days > 1:
            line.append(f"··· перерыв {(d - prev).days - 1} дн ···")
        line.append(f"{d:%d}")
        prev = d
    print("      дни со звонками: " + " ".join(line))


def ask_departures(detail: pd.DataFrame, operators: dict) -> dict:
    """
    Спрашивает дату ухода по каждой спорной позиции.

    Пустой ответ — считать, что все дни месяца заработал тот, кто
    указан сверху сейчас. Это безопасный ответ для случая, когда
    человек ушёл ещё в прошлом месяце и в этом не работал вовсе.
    """
    hand = find_handovers(detail, operators)
    if not hand:
        return {}

    out = {int(k): (v if isinstance(v, date)
                    else datetime.strptime(v, "%Y-%m-%d").date())
           for k, v in DEPARTURES.items()}

    print("\nНа этих позициях за месяц сменился человек:")
    for pos, (was, now) in sorted(hand.items()):
        if pos in out:
            continue
        print(f"\n   Позиция {pos}: был {was}, "
              f"теперь {now or 'имя не вписано'}")
        show_activity(detail, pos)
        while True:
            raw = input("      Последний день ушедшего (ГГГГ-ММ-ДД) "
                        "[Enter — все дни новому]: ").strip()
            if not raw:
                break
            try:
                out[pos] = datetime.strptime(raw, "%Y-%m-%d").date()
                break
            except ValueError:
                print("      Не понял. Формат: 2026-09-12")
    return out


def apply_departures(detail: pd.DataFrame, operators: dict,
                     departures: dict) -> pd.DataFrame:
    """
    Переписывает имя в строках, отработанных ДО ухода.

    Дни до даты включительно достаются ушедшему, остальные остаются
    за тем, кто на позиции сейчас. Ничего не выбрасывается: обе
    части — чей-то реальный заработок, просто у разных людей.

    Строки самого раздела «Выбывшие» из расчёта убираем: числа
    лежат на верхней строке позиции, и если считать обе, заработок
    задвоится.
    """
    hand = find_handovers(detail, operators)
    d = detail[detail["Раздел"] != "Выбывшие"].copy()

    for pos, day in departures.items():
        was, _ = hand.get(pos, (None, None))
        if not was:
            continue
        mask = (d["Позиция"] == pos) & (d["Дата"] <= day)
        d.loc[mask, "Оператор"] = was
        d.loc[mask, "Имя"] = was
    return d


def build_summary(detail: pd.DataFrame) -> pd.DataFrame:
    """
    Сводит детализацию по именам.

    Группа — имя, если оно есть; иначе подпись целиком («13 Опер»),
    чтобы позиции без имени не потерялись и не слились друг с другом
    под пустой группой.
    """
    d = detail.copy()
    d["Группа"] = d["Имя"].where(d["Имя"] != "", d["Оператор"])

    g = d.groupby("Группа").agg(
        Позиции=("Позиция", lambda s: ", ".join(
            sorted({str(x) for x in s if x != ""},
                  key=lambda v: (0, int(v)) if v.isdigit() else (1, v)))),
        Дней=("Дата", "nunique"),
        ОТЗ=("ОТЗ", "sum"), ЗВ=("ЗВ", "sum"),
        АН=("АН", "sum"), Сумма=("Сумма", "sum"),
    ).reset_index().rename(columns={"Группа": "Оператор"})
    return g.sort_values("Сумма", ascending=False).reset_index(drop=True)


def write_excel(path: Path, summary: pd.DataFrame, detail: pd.DataFrame,
                title: str) -> None:
    """
    Пишет два листа с базовым оформлением — файл уходит супервайзерам,
    поэтому не голые числа, а читаемая шапка и нужная ширина колонок.
    """
    wb = openpyxl.Workbook()
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="305496")
    body_font = Font(name="Arial")
    note_font = Font(name="Arial", italic=True, color="C00000")

    def write_sheet(ws, df, note=None):
        row0 = 1
        if note:
            ws.cell(row0, 1, note).font = note_font
            ws.merge_cells(start_row=row0, start_column=1,
                           end_row=row0, end_column=len(df.columns))
            row0 += 2
        for c, col_name in enumerate(df.columns, start=1):
            cell = ws.cell(row0, c, col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        for r, rec in enumerate(df.itertuples(index=False), start=row0 + 1):
            for c, val in enumerate(rec, start=1):
                ws.cell(r, c, val).font = body_font
        for c, col_name in enumerate(df.columns, start=1):
            width = max([len(str(col_name))] +
                       [len(str(v)) for v in df[col_name]]) if len(df) \
                else len(str(col_name))
            ws.column_dimensions[get_column_letter(c)].width = min(width + 3, 40)
        ws.freeze_panes = ws.cell(row0 + 1, 1)

    ws1 = wb.active
    ws1.title = "Итог по именам"
    write_sheet(ws1, summary,
               note=f"{title}. Позиции без имени в подписи оставлены "
                    f"отдельной строкой под своим номером — сопоставить "
                    f"их с человеком отчёт сам не может.")

    ws2 = wb.create_sheet("По дням")
    detail2 = detail.copy()
    detail2["Дата"] = detail2["Дата"].astype(str)
    write_sheet(ws2, detail2,
               note="Сырая раскладка по позициям и дням — для проверки, "
                    "если в течение месяца кто-то менял позицию: колонка A "
                    "листа хранит одну подпись на позицию на весь месяц, "
                    "и дни ДО смены человека в отчёте по именам достанутся "
                    "тому, кто указан там сейчас.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> None:
    year, month = YEAR, MONTH
    if ASK:
        year, month = ask_month(YEAR, MONTH)

    loader = SheetsLoader(CREDENTIALS, SPREADSHEET_ID)
    loader.connect()

    name = SHEET_NAME or f"{RU_MONTHS[month]} {year}"
    print(f"Лист «{name}»")

    detail, operators = build_detail(loader, name, year, month)
    if detail.empty:
        print(f"За {RU_MONTHS[month]} {year} на листе нет данных — "
              f"считать нечего.")
        return

    departures = (ask_departures(detail, operators) if ASK
                  else {int(k): datetime.strptime(v, "%Y-%m-%d").date()
                        for k, v in DEPARTURES.items()})
    detail = apply_departures(detail, operators, departures)

    summary = build_summary(detail)
    print(f"\n{summary.to_string(index=False)}")
    print(f"\nВсего: ОТЗ {summary['ОТЗ'].sum()}, ЗВ {summary['ЗВ'].sum()}, "
          f"АН {summary['АН'].sum()}, к оплате "
          f"{summary['Сумма'].sum():,} сум".replace(",", " "))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"kpi_итог_{RU_MONTHS[month]}_{year}.xlsx"
    write_excel(path, summary, detail,
               title=f"Итог за {RU_MONTHS[month]} {year}")
    print(f"\nФайл: {path}")


if __name__ == "__main__":
    main()
