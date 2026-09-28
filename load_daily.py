# -*- coding: utf-8 -*-
"""
Загрузка выгрузок в базу.

Кладёшь файлы в data/, запускаешь — данные в базе. Запускать можно
сколько угодно раз: перед вставкой строки за эти даты удаляются и
заливаются заново, поэтому дубликатов не бывает.

    python load_daily.py

Три вещи, ради которых написано именно так:

  Идемпотентность. Загрузка одного и того же файла дважды не должна
  ничего портить — на практике перезапускать приходится постоянно.

  Транзакции. Между удалением старых строк и вставкой новых скрипт
  может упасть. Без транзакции день остался бы пустым, и заметили бы
  это нескоро. Здесь либо загрузилось всё, либо ничего.

  Журнал. Через месяц никто не помнит, откуда в базе дырка. load_log
  хранит, какой файл, когда и сколько строк принёс.
"""
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from config import DATA_DIR, DB_URL, DROP_BUFFER_DAY, PROJECTS, ROOT

# Как колонка называется в выгрузке -> как в базе.
CALL_COLUMNS = {
    "ID звонка": "call_id",
    "Направление звонка": "direction",
    "Номер телефона": "phone",
    "Время начала звонка": "started_at",
    "Время конца звонка": "ended_at",
    "Продолжительность, сек": "talk_sec",
    "Время удержания, сек": "hold_sec",
    "Оператор": "operator",
    "Тема звонка": "topic",
}
HOURLY_COLUMNS = {
    "Дата": "call_date", "Час": "call_hour",
    "Принято": "answered", "Не дождались": "lost", "Всего": "total",
}


def run_script(con, path: Path) -> None:
    """
    Выполняет .sql-файл по одной команде.

    У SQLAlchemy нет executescript, поэтому режем по «;» в конце
    строки — так точки с запятой внутри текста не разваливают запрос.
    """
    for stmt in re.split(r";\s*\n", path.read_text(encoding="utf-8")):
        if stmt.strip():
            con.execute(text(stmt))


def delete_days(con, table: str, project: str, days) -> int:
    """
    Убирает строки проекта за эти даты. Возвращает, сколько удалил.

    Параметры именованные: у разных драйверов свой стиль подстановки,
    а :name понимает SQLAlchemy на любом.
    """
    keys = [f"d{i}" for i in range(len(days))]
    q = text(f"DELETE FROM {table} WHERE project = :p AND call_date IN "
             f"({', '.join(':' + k for k in keys)})")
    return con.execute(q, {"p": project, **dict(zip(keys, days))}).rowcount


def write_log(con, project, source, target, days_file, buffer_day,
              kept, wiped) -> None:
    con.execute(text(
        "INSERT INTO load_log (loaded_at, project, source, target,"
        " days_file, buffer_day, rows_kept, rows_wiped)"
        " VALUES (:ts, :p, :src, :tgt, :days, :buf, :kept, :wiped)"),
        {"ts": datetime.now().isoformat(timespec="seconds"),
         "p": project, "src": source, "tgt": target, "days": days_file,
         "buf": buffer_day, "kept": kept, "wiped": wiped})


def drop_buffer(df: pd.DataFrame, enabled: bool) -> tuple:
    """
    Выбрасывает самый ранний день файла.

    Источник теряет первую запись запрошенного периода. Поэтому
    качаем с запасом в день, чтобы откушенным оказался он, а этот
    день всё равно придёт полным из предыдущего файла.

    Для месячной выгрузки правило не работает: там пропадает одна
    запись первого числа, а отрезание отняло бы сутки целиком.
    """
    days = sorted(df["call_date"].unique())
    if not enabled or not DROP_BUFFER_DAY or len(days) < 2:
        return df, None
    return df[df["call_date"] != days[0]].copy(), days[0]


def prepare_calls(df: pd.DataFrame, project: str) -> pd.DataFrame:
    """Приводит реестр звонков к схеме базы."""
    df = df.rename(columns=CALL_COLUMNS)
    df["started_at"] = pd.to_datetime(df["started_at"], errors="coerce")
    df = df[df["started_at"].notna()].copy()

    df["call_date"] = df["started_at"].dt.date.astype(str)
    df["call_hour"] = df["started_at"].dt.hour
    df["ended_at"] = pd.to_datetime(df["ended_at"],
                                    errors="coerce").astype(str)
    df["started_at"] = df["started_at"].astype(str)

    for col in ("talk_sec", "hold_sec"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(0).astype(int)

    # Минуты для тарификации округляются ВВЕРХ: разговор в 61 секунду
    # оплачивается как две минуты.
    df["bill_min"] = np.ceil(df["talk_sec"] / 60).astype(int)

    # Телефон только текстом: номера не влезают в INTEGER и теряют
    # ведущие нули.
    df["phone"] = df["phone"].astype(str).str.replace(r"\.0$", "", regex=True)

    df["project"] = project
    df["loaded_at"] = datetime.now().isoformat(timespec="seconds")
    return df[["project", "call_id", "direction", "phone", "started_at",
               "ended_at", "talk_sec", "hold_sec", "bill_min", "operator",
               "topic", "call_date", "call_hour", "loaded_at"]]


def prepare_hourly(df: pd.DataFrame, project: str) -> pd.DataFrame:
    """Приводит почасовую сводку к схеме базы."""
    df = df.rename(columns=HOURLY_COLUMNS)
    df["call_date"] = pd.to_datetime(df["call_date"],
                                     errors="coerce").dt.date.astype(str)
    for col in ("call_hour", "answered", "lost", "total"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["project"] = project
    df["loaded_at"] = datetime.now().isoformat(timespec="seconds")
    return df[["project", "call_date", "call_hour", "answered", "lost",
               "total", "loaded_at"]]


def load_file(con, path: Path, project: str, kind: str) -> None:
    raw = pd.read_excel(path)
    if kind == "calls":
        df = prepare_calls(raw, project)
        days_all = sorted(df["call_date"].unique())
        # month в имени = месячная выгрузка, первый день не режем
        df, buf = drop_buffer(df, "month" not in path.stem)
        table = "calls"
    else:
        df = prepare_hourly(raw, project)
        days_all, buf = sorted(df["call_date"].unique()), None
        table = "hourly"

    if df.empty:
        print(f"  {path.name}: нет строк с датой, пропускаю")
        return

    days = sorted(df["call_date"].unique())
    wiped = delete_days(con, table, project, days)
    df.to_sql(table, con, if_exists="append", index=False)
    write_log(con, project, path.name, table, ", ".join(days_all),
              buf or "", len(df), wiped)

    period = days[0] if len(days) == 1 else f"{days[0]}..{days[-1]}"
    note = f", буфер {buf} выброшен" if buf else ""
    print(f"  {path.name:<28} -> {project}: {len(df)} строк "
          f"за {period}{note}")


def main() -> None:
    engine = create_engine(DB_URL)

    with engine.begin() as con:
        run_script(con, ROOT / "schema.sql")
        run_script(con, ROOT / "views.sql")

    found = []
    for path in sorted(DATA_DIR.glob("*.xlsx")):
        for project in PROJECTS:
            if path.stem.startswith(project):
                kind = "hourly" if "hourly" in path.stem else "calls"
                found.append((path, project, kind))
                break

    if not found:
        print(f"В папке {DATA_DIR} нет файлов. "
              f"Сначала: python generate_demo.py")
        return

    print(f"Найдено файлов: {len(found)}\n")
    for path, project, kind in found:
        # Своя транзакция на каждый файл: engine.begin() сам делает
        # COMMIT в конце и ROLLBACK при ошибке. Значит день либо
        # загрузился целиком, либо не загрузился вовсе. И сбой на
        # одном файле не отменяет уже загруженные.
        try:
            with engine.begin() as con:
                load_file(con, path, project, kind)
        except Exception as e:
            print(f"  {path.name}: ОШИБКА — {type(e).__name__}: {e}")

    with engine.connect() as con:
        print(f"\nБаза: {engine.url}")
        for table, label in (("calls", "звонки"), ("hourly", "почасовые")):
            rows = con.execute(text(
                f"SELECT project, COUNT(*), MIN(call_date), MAX(call_date)"
                f" FROM {table} GROUP BY project ORDER BY project")).fetchall()
            if rows:
                print(f"  {table} — {label}:")
                for p, n, a, b in rows:
                    print(f"    {p:<10} {n:>7} строк   {a} — {b}")
    engine.dispose()


if __name__ == "__main__":
    main()
