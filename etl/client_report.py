# -*- coding: utf-8 -*-
"""
Заполнение отчёта Gamma в Google Таблице.

Какие колонки заполняет и откуда — всё проверено по данным:

  из CRM (gamma_crm.xlsx, качает crm_reports.py)
    D  входящих на операторе     количество входящих
    R  исходящих                 количество исходящих
    T  успешных, не 0            все исходящие минус исходящие с
                                 длительностью РОВНО 0
    Y  ATT (CRM)                 среднее по входящим с длительностью > 0

  из АТС (gamma_pbx.xls — почасовой отчёт)
    C  IVR                       сумма по часам
    E  пропущенные               сумма по часам
    I  ATT (АТС)                 «Обработка операторами»: средняя по
                                 часам, взвешенная по числу звонков,
                                 ДОШЕДШИХ ДО ОПЕРАТОРА
    L  трансфер                  сумма по часам колонки «Внешний агент»
                                 (количество звонков)

Что НЕ трогает:
    H           AWT — есть только на скриншоте, вносится руками
    B, F, J, S  формулы: запись числом поверх убьёт пересчёт

    python client_report.py

Спрашивает период, считает, показывает план, пишет после «да».
"""
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import xlrd

from etl_core import SheetsLoader, DATA_DIR, CREDENTIALS, env

# ============================ НАСТРОЙКИ ============================

BASE_DIR = DATA_DIR        # выгрузки лежат в папке data/ в корне репозитория
# CREDENTIALS импортируется из etl_core: credentials.json в корне, в git не попадает
SPREADSHEET_ID = env("GAMMA_REPORT_SHEET_ID")

CRM_FILE = BASE_DIR / "gamma_crm.xlsx"
PBX_FILE = BASE_DIR / "gamma_pbx.xls"

# Колонки отчёта. Буквы взяты с листа «Сентябрь».
COL = {"C": 3, "D": 4, "E": 5, "I": 9, "L": 12,
       "R": 18, "T": 20, "Y": 25}

# Колонки с временем — им при записи ставится формат H:mm:ss.
# Без этого значение 0:02:07 в ячейке с форматом «ч:мм» покажется
# как «0:02» и потеряет секунды — так уже было в колонке Y.
TIME_COLS = ("I", "Y")

DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%m/%d/%Y", "%m/%d/%y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

# ==================================================================


# ---------------------------- окна --------------------------------
#
# Выбор делается мышкой во всплывающем окне (tkinter — он встроен в
# Python и уже есть в Anaconda, ставить ничего не надо).
#
# Если окно показать не удалось — например, скрипт запущен без
# экрана, — скрипт не падает, а спрашивает то же самое текстом.


def _period_for(mode: str, custom: tuple) -> tuple:
    """Готовые варианты периода. Считаются от вчерашнего дня."""
    y = date.today() - timedelta(days=1)
    if mode == "yesterday":
        return y, y
    if mode == "before":
        return y - timedelta(days=1), y - timedelta(days=1)
    if mode == "week":
        return y - timedelta(days=6), y
    return custom


def gui_choose():
    """
    Окно выбора периода. Возвращает (с, по, брать_ли_АТС)
    или None, если нажали «Отмена» или закрыли окно.
    """
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Отчёт Gamma")
    root.resizable(False, False)
    # Поверх остальных окон: иначе оно откроется ЗА DataSpell,
    # и покажется, что скрипт завис.
    root.attributes("-topmost", True)

    y = date.today() - timedelta(days=1)
    mode = tk.StringVar(value="yesterday")
    use_inf = tk.BooleanVar(value=True)
    v_from = tk.StringVar(value=f"{y:%Y-%m-%d}")
    v_to = tk.StringVar(value=f"{y:%Y-%m-%d}")
    result = {}

    frm = ttk.Frame(root, padding=16)
    frm.grid()

    ttk.Label(frm, text="Какой период заполнить?",
              font=("Segoe UI", 11, "bold")).grid(
        row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

    presets = [("Вчера", "yesterday"), ("Позавчера", "before"),
               ("Последние 7 дней", "week"), ("Свой период", "custom")]
    for i, (text, val) in enumerate(presets, start=1):
        ttk.Radiobutton(frm, text=text, variable=mode, value=val).grid(
            row=i, column=0, columnspan=4, sticky="w")

    ttk.Label(frm, text="с").grid(row=5, column=0, sticky="e", pady=(8, 0))
    e_from = ttk.Entry(frm, textvariable=v_from, width=12)
    e_from.grid(row=5, column=1, sticky="w", pady=(8, 0))
    ttk.Label(frm, text="по").grid(row=5, column=2, sticky="e", pady=(8, 0))
    e_to = ttk.Entry(frm, textvariable=v_to, width=12)
    e_to.grid(row=5, column=3, sticky="w", pady=(8, 0))

    inf_box = ttk.Checkbutton(frm, variable=use_inf)
    inf_box.grid(row=6, column=0, columnspan=4, sticky="w", pady=(12, 0))

    err = ttk.Label(frm, text="", foreground="#b00020")
    err.grid(row=7, column=0, columnspan=4, sticky="w")

    def refresh(*_):
        """Поля дат и подпись АТС следуют за выбранным вариантом."""
        custom = mode.get() == "custom"
        state = "normal" if custom else "disabled"
        e_from.configure(state=state)
        e_to.configure(state=state)
        if not custom:
            a, b = _period_for(mode.get(), None)
            v_from.set(f"{a:%Y-%m-%d}")
            v_to.set(f"{b:%Y-%m-%d}")
        inf_box.configure(
            text=f"Взять АТС (C, E, I, L) за {v_to.get()}")

    mode.trace_add("write", refresh)
    v_to.trace_add("write", refresh)

    def ok():
        try:
            a = datetime.strptime(v_from.get().strip(), "%Y-%m-%d").date()
            b = datetime.strptime(v_to.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            err.configure(text="Дата в формате 2026-09-16")
            return
        if b < a:
            a, b = b, a
        result["v"] = (a, b, use_inf.get())
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=8, column=0, columnspan=4, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Отмена", command=root.destroy).grid(
        row=0, column=0, padx=(0, 6))
    ok_btn = ttk.Button(btns, text="Далее", command=ok)
    ok_btn.grid(row=0, column=1)

    root.bind("<Return>", lambda _e: ok())
    root.bind("<Escape>", lambda _e: root.destroy())
    refresh()
    root._ok_btn = ok_btn          # для проверки без мыши
    root.mainloop()
    return result.get("v")


def gui_confirm(lines: list) -> bool:
    """Окно с планом записи и кнопками «Записать» / «Отмена»."""
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("План записи")
    root.attributes("-topmost", True)
    result = {"ok": False}

    frm = ttk.Frame(root, padding=16)
    frm.grid()
    ttk.Label(frm, text=f"Будет записано ячеек: {len(lines)}",
              font=("Segoe UI", 11, "bold")).grid(sticky="w", pady=(0, 8))

    box = ScrolledText(frm, width=44, height=min(18, len(lines) + 1),
                       font=("Consolas", 10))
    box.grid()
    box.insert("1.0", "\n".join(lines))
    box.configure(state="disabled")

    def write():
        result["ok"] = True
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Отмена", command=root.destroy).grid(
        row=0, column=0, padx=(0, 6))
    ok_btn = ttk.Button(btns, text="Записать", command=write)
    ok_btn.grid(row=0, column=1)

    root.bind("<Escape>", lambda _e: root.destroy())
    root._ok_btn = ok_btn
    root.mainloop()
    return result["ok"]


def text_choose():
    """Запасной путь, если окна нет: то же самое цифрой."""
    y = date.today() - timedelta(days=1)
    print("Какой период заполнить?")
    print(f"  1. вчера ({y:%d.%m})")
    print(f"  2. позавчера ({y - timedelta(days=1):%d.%m})")
    print("  3. последние 7 дней")
    print("  4. свой период")
    modes = {"1": "yesterday", "2": "before", "3": "week", "4": "custom"}
    while True:
        m = modes.get(input("Номер [1]: ").strip() or "1")
        if m:
            break
    if m == "custom":
        def ask(label):
            while True:
                try:
                    return datetime.strptime(
                        input(f"{label} (ГГГГ-ММ-ДД): ").strip(),
                        "%Y-%m-%d").date()
                except ValueError:
                    print("   Формат: 2026-09-16")
        a, b = ask("с"), ask("по")
        a, b = (b, a) if b < a else (a, b)
    else:
        a, b = _period_for(m, None)
    inf = input(f"Взять АТС за {b:%d.%m}? [да/нет] (да): ").strip().lower()
    return a, b, inf not in ("нет", "н", "no")


def choose():
    """Окно, а если не получилось — текстом."""
    try:
        return gui_choose()
    except Exception as e:
        print(f"(окно не открылось: {type(e).__name__} — спрашиваю текстом)")
        return text_choose()


def confirm(lines: list) -> bool:
    try:
        return gui_confirm(lines)
    except Exception as e:
        print(f"(окно не открылось: {type(e).__name__} — спрашиваю текстом)")
        print("\n".join(lines))
        return input("Записать? [нет/да]: ").strip().lower() in ("да", "д")


def parse_date(v):
    """Дата из ячейки — в каком бы виде её ни отдал Google Sheets."""
    txt = str(v).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------- CRM ---------------------------------

def crm_metrics(path: Path) -> dict:
    """
    {дата: {D, R, T, Y}} из выгрузки CRM.

    T считается как у тебя вручную: все исходящие минус те, у кого
    длительность РОВНО ноль. Пустая длительность под «ноль» не
    попадает — фильтр «= 0» на главном экране CRM её тоже пропускает,
    и так совпало в 12 днях из 13.
    """
    df = pd.read_excel(path)
    df["_d"] = pd.to_datetime(df["Время начала звонка"],
                              errors="coerce").dt.date
    df["_sec"] = pd.to_numeric(df["Продолжительность, сек"], errors="coerce")
    df = df[df["_d"].notna()]

    out = {}
    for d, g in df.groupby("_d"):
        inc = g[g["Направление звонка"] == "Входящий"]
        outg = g[g["Направление звонка"] == "Исходящий"]
        talk = inc[inc["_sec"] > 0]["_sec"]
        out[d] = {
            "D": len(inc),
            "R": len(outg),
            "T": len(outg) - int((outg["_sec"] == 0).sum()),
            "Y": talk.mean() if len(talk) else None,
        }
    return out


# -------------------------- АТС ------------------------------

def _sec(v) -> int:
    m = re.match(r"^(\d+):(\d{2}):(\d{2})$", str(v).strip())
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else 0


def _num(v) -> int:
    try:
        return int(float(str(v).replace("\xa0", "").replace(" ", "")))
    except ValueError:
        return 0


def pbx_metrics(path: Path) -> tuple:
    """
    {C, E, I, L} из почасового отчёта АТС.

    Дня в самом отчёте нет — в строках только часы. Поэтому день,
    к которому относится файл, спрашивается при запуске отдельно.

    I — ATT, то есть время РАЗГОВОРА, а не всего звонка. Поэтому берём
    строку «Обработка операторами», а не «Средняя продолжительность
    звонков»: во вторую входят ещё IVR и ожидание в очереди, и
    разница получается огромной — почти вдвое.

    Средняя по операторам (колонка 8) взвешивается по числу звонков,
    дошедших до оператора в этом часе (колонки 2 и 3). Сверено со
    скриншотом отчёта: совпадает с точностью до секунды. Эта секунда —
    округление: в файле средние по часам записаны в целых секундах,
    а скриншот считает по каждому звонку.

    L — трансфер. В отчёте «Внешний агент» встречается трижды: в
    количестве звонков, в средней и в максимальной длительности.
    Берём КОЛИЧЕСТВО (колонка 4) — это число переведённых звонков.
    Сумма по часам совпала со скриншотом отчёта.
    """
    ws = xlrd.open_workbook(path, logfile=io.StringIO()).sheet_by_index(0)
    rows = [[ws.cell_value(r, c) for c in range(ws.ncols)]
            for r in range(2, ws.nrows)
            if re.match(r"^\d{1,2}:", str(ws.cell_value(r, 0)).strip())]
    answered = sum(_num(r[2]) + _num(r[3]) for r in rows)
    return {
        "C": sum(_num(r[1]) for r in rows),
        "E": sum(_num(r[5]) for r in rows),
        "L": sum(_num(r[4]) for r in rows),
        "I": (sum(_sec(r[8]) * (_num(r[2]) + _num(r[3])) for r in rows)
              / answered if answered else None),
    }


# ---------------------------- запись ------------------------------

def to_time(sec) -> str:
    """Секунды в «ч:мм:сс» — так Google Sheets поймёт это как время."""
    s = int(round(sec))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def find_rows(loader) -> dict:
    """
    {дата: (вкладка, строка)} по ВСЕМ вкладкам таблицы.

    Ищем по дате в колонке A, а не по названию вкладки: август у тебя
    разбит на две («Август» и «Август2»), названия непостоянные. Так
    неважно, как вкладка называется и на сколько частей разбит месяц.
    """
    q = loader.quote_sheet
    titles = [w.title for w in loader.sh.worksheets()]
    grids = loader.batch_get([f"{q(t)}!A1:A60" for t in titles])

    out = {}
    for title, col in zip(titles, grids):
        for i, r in enumerate(col or [], start=1):
            d = parse_date(r[0]) if r else None
            if d:
                out[d] = (title, i)
    return out


def main() -> None:
    choice = choose()
    if choice is None:
        print("Отменено — ничего не записано.")
        return
    d_from, d_to, use_inf = choice
    # В почасовом отчёте АТС нет даты, только часы. Считаем, что
    # файл — за последний день периода: так при ежедневном запуске.
    inf_day = d_to if use_inf else None

    crm = crm_metrics(CRM_FILE)
    inf = pbx_metrics(PBX_FILE) if use_inf else {}

    loader = SheetsLoader(CREDENTIALS, SPREADSHEET_ID)
    loader.connect()
    rows = find_rows(loader)
    q = loader.quote_sheet

    payload, lines, time_cells, missing = [], [], [], []
    d = d_from
    while d <= d_to:
        where = rows.get(d)
        if where is None:
            missing.append(d)
            d += timedelta(days=1)
            continue
        tab, row = where

        vals = dict(crm.get(d, {}))
        if d == inf_day:
            vals.update(inf)

        for col, v in vals.items():
            if v is None:
                continue
            cell = f"{chr(64 + COL[col])}{row}"
            text = to_time(v) if col in TIME_COLS else int(v)
            payload.append({"range": f"{q(tab)}!{cell}", "values": [[text]]})
            lines.append(f"{d:%d.%m}  {tab:<10} {col}  {text}")
            if col in TIME_COLS:
                time_cells.append((tab, cell))
        d += timedelta(days=1)

    for m in missing:
        print(f"  {m:%d.%m}: строки с этой датой нет ни на одной вкладке")

    if not payload:
        print("Писать нечего.")
        return

    if not confirm(lines):
        print("Отменено — ничего не записано.")
        return

    loader.sh.values_batch_update({"valueInputOption": "USER_ENTERED",
                                   "data": payload})
    for tab, cell in time_cells:
        loader.sh.worksheet(tab).format(
            cell, {"numberFormat": {"type": "TIME", "pattern": "H:mm:ss"}})
    print(f"Записано ячеек: {len(payload)}. H и формулы не тронуты.")


if __name__ == "__main__":
    main()
