# -*- coding: utf-8 -*-
"""
Тесты чистых функций — тех правил, что проверены на реальных данных
и на которых держатся отчёты.

    pytest            (из корня репозитория)

Функции берутся из рабочего кода, а не копируются сюда: тест должен
упасть, если правило в коде поменяли.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

# Модули лежат в корне (SQL-часть) и в etl/ — добавляем обе папки,
# иначе import их не найдёт
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "etl"))

from etl_core import ExcelReader, MultiDay, bill_minutes
from kpi_daily import rate_for
from load_daily import drop_buffer


# ---------------------------- округление минут ----------------------------

@pytest.mark.parametrize("sec, minutes", [
    (0, 0), (1, 1), (59, 1), (60, 1), (61, 2), (125, 3),
])
def test_minutes_round_up(sec, minutes):
    # Без порога — всегда вверх: 61 секунда — уже две минуты
    assert bill_minutes(sec) == minutes


@pytest.mark.parametrize("sec, minutes", [
    (0, 0), (3, 0), (5, 0), (6, 1), (60, 1), (61, 2),
])
def test_minutes_free_threshold(sec, minutes):
    # Правило заказчика Alpha: до 5 секунд включительно — 0 минут
    assert bill_minutes(sec, free_under_sec=5) == minutes


def test_minutes_whole_export():
    # Функция работает и на всей выгрузке сразу, а не по одному звонку
    sec = pd.Series([4, 5, 6, 60, 61])
    assert list(bill_minutes(sec, free_under_sec=5)) == [0, 0, 1, 1, 2]


# ----------------------------- тарифная сетка -----------------------------

@pytest.mark.parametrize("surveys, rate", [
    (0, 300), (24, 300), (25, 600), (39, 600), (40, 900), (100, 900),
])
def test_tariff_by_daily_surveys(surveys, rate):
    # Ставка за анкету зависит от числа анкет за день; границы — 25 и 40
    assert rate_for(surveys) == rate


# --------------------------- числа «1 036» из АТС ---------------------------

def test_plain_to_numeric_loses_thousands():
    # Ради этого и написан _to_num: обычный разбор даёт NaN,
    # а fillna(0) потом молча превращает тысячу звонков в ноль
    assert pd.to_numeric(pd.Series(["1 036"]), errors="coerce").isna().all()


def test_to_num_thousands():
    s = pd.Series(["1 036", "1\xa0036", "1 036", "12", "7,5", 15])
    assert ExcelReader._to_num(s).tolist() == [1036, 1036, 1036, 12, 7.5, 15]


def test_to_num_garbage_is_nan():
    # Пустое и мусор — NaN, а не ноль: «нет данных» и «ноль» — разное
    s = pd.Series(["", "-", None, "Итого"])
    assert ExcelReader._to_num(s).isna().all()


# ------------------------------ буферный день ------------------------------

def days(*dates) -> dict:
    """Выгрузка, разложенная по дням: по одной строке на день."""
    return {d: pd.DataFrame({"ID звонка": [1]}) for d in dates}


def test_buffer_is_earliest_day():
    table, to_load, buffer_day = MultiDay.plan(
        days(date(2026, 8, 17), date(2026, 8, 15), date(2026, 8, 16)))
    assert buffer_day == date(2026, 8, 15)
    assert to_load == [date(2026, 8, 16), date(2026, 8, 17)]
    # Буферный день не выброшен молча — он в таблице с пометкой
    assert "НЕ грузится" in table.loc[0, "Что делаем"]


def test_single_day_has_no_buffer():
    # Один день в файле: отбросить нечего, но предупреждаем о потере
    table, to_load, buffer_day = MultiDay.plan(days(date(2026, 8, 17)))
    assert buffer_day is None
    assert to_load == [date(2026, 8, 17)]
    assert "буфера нет" in table.loc[0, "Примечание"]


def test_buffer_switched_off():
    _, to_load, buffer_day = MultiDay.plan(
        days(date(2026, 8, 16), date(2026, 8, 17)), use_buffer=False)
    assert buffer_day is None
    assert len(to_load) == 2


def test_empty_export_stops():
    with pytest.raises(ValueError):
        MultiDay.plan({})


def test_split_by_day_drops_bad_dates():
    df = pd.DataFrame({"Время начала звонка": [
        "2026-08-16 09:00:00", "мусор", "2026-08-15 23:59:00",
        "2026-08-16 10:00:00"]})
    parts = MultiDay.split(df, "Время начала звонка")
    assert list(parts) == [date(2026, 8, 15), date(2026, 8, 16)]
    assert len(parts[date(2026, 8, 16)]) == 2


def test_sql_part_drops_buffer_day():
    df = pd.DataFrame({"call_date": ["2026-08-15", "2026-08-16", "2026-08-16"]})
    kept, buffer_day = drop_buffer(df, enabled=True)
    assert buffer_day == "2026-08-15"
    assert len(kept) == 2


def test_sql_part_month_file_keeps_first_day():
    # Для месячной выгрузки правило выключено: load_daily передаёт
    # enabled=False, если в имени файла есть month
    df = pd.DataFrame({"call_date": ["2026-08-01", "2026-08-02"]})
    kept, buffer_day = drop_buffer(df, enabled=False)
    assert buffer_day is None
    assert len(kept) == 2
