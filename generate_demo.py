# -*- coding: utf-8 -*-
"""
Генератор демонстрационных данных.

Настоящие выгрузки — коммерческие данные заказчиков, поэтому в
репозитории их нет. Скрипт делает файлы такой же структуры, чтобы
пайплайн можно было запустить и посмотреть, как он работает.

Данные не случайный шум: заложены суточный профиль нагрузки,
разница между буднями и выходными, разные по размеру проекты и
один настоящий сбой на три дня подряд — чтобы было видно, как
поиск аномалий отличает его от обычного разброса.

    python generate_demo.py
"""
import argparse
import random
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from config import DATA_DIR, PROJECTS

# Доля звонков по часам суток. Ночью почти пусто, два пика — утром
# и вечером, когда людям удобно звонить.
HOUR_WEIGHTS = [
    0.4, 0.2, 0.1, 0.1, 0.1, 0.3, 1.0, 3.0, 7.0, 8.5, 8.0, 7.5,
    6.5, 7.0, 7.5, 7.5, 7.0, 6.5, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0,
]

# Размер проектов: от крупного до совсем мелкого. Мелкий нужен,
# чтобы показать, как аналитика отказывается делать выводы там,
# где данных мало.
PROJECT_SIZE = {"alpha": 900, "beta": 600, "gamma": 120, "delta": 8}

# Последний день демо-периода. Дата фиксированная, а не «вчера»: так
# analytics.py и demo_analysis.ipynb показывают одни и те же цифры при
# любом запуске. По умолчанию период — сентябрь 2026 целиком, и
# заложенный сбой (15–17 число) приходится на будни.
END_DAY = date(2026, 9, 30)

TOPICS = ["Статус заказа", "Доставка", "Возврат", "Оплата",
          "Режим работы", "Жалоба", "Другое"]


def day_volume(project: str, day: date, rng) -> int:
    """Сколько звонков за день: будни полные, выходные вполовину."""
    base = PROJECT_SIZE[project]
    if day.weekday() >= 5:
        base = int(base * 0.45)
    return max(0, int(rng.normal(base, base * 0.08)))


def lost_share(project: str, day: date, hour: int, rng) -> float:
    """
    Доля неотвеченных звонков.

    Утром и вечером теряется больше: смена ещё не вышла или уже
    заканчивается. У проекта beta с 15 по 17 число заложен сбой —
    настоящее событие, которое аналитика должна найти.
    """
    share = 0.12
    if hour in (7, 8, 18, 19, 20):
        share = 0.35
    if hour < 7 or hour > 21:
        share = 0.55
    if project == "beta" and day.day in (15, 16, 17):
        share = 0.60
    return min(0.95, max(0.0, rng.normal(share, 0.04)))


def make_calls(project: str, days: list, rng) -> pd.DataFrame:
    """Реестр звонков: одна строка — один разговор."""
    operators = [f"Оператор {i}" for i in range(1, 9)]
    rows, call_no = [], 1

    for day in days:
        total = day_volume(project, day, rng)
        if total == 0:
            continue
        hours = rng.choice(24, size=total,
                           p=np.array(HOUR_WEIGHTS) / sum(HOUR_WEIGHTS))
        # Днём операторов больше, ночью на линии двое.
        for hour in hours:
            on_shift = operators[:6] if 8 <= hour <= 19 else operators[6:]
            talk = max(0, int(rng.lognormal(4.4, 0.7)))
            start = datetime.combine(day, datetime.min.time()) + timedelta(
                hours=int(hour), minutes=int(rng.integers(0, 60)),
                seconds=int(rng.integers(0, 60)))
            rows.append({
                "ID звонка": 100000 + call_no,
                "Направление звонка": ("Исходящий" if rng.random() < 0.12
                                       else "Входящий"),
                "Номер телефона": f"9{rng.integers(10**8, 10**9 - 1)}",
                "Время начала звонка": start,
                "Время конца звонка": start + timedelta(seconds=talk),
                "Продолжительность, сек": talk,
                "Время удержания, сек": int(max(0, rng.normal(3, 5))),
                "Оператор": random.choice(on_shift),
                "Тема звонка": random.choice(TOPICS),
            })
            call_no += 1
    return pd.DataFrame(rows)


def make_hourly(project: str, days: list, rng) -> pd.DataFrame:
    """Почасовая сводка телефонии: принято, не дождались, всего."""
    rows = []
    for day in days:
        total_day = day_volume(project, day, rng)
        for hour in range(24):
            share = HOUR_WEIGHTS[hour] / sum(HOUR_WEIGHTS)
            total = int(total_day * share)
            if total == 0:
                rows.append({"Дата": day, "Час": hour, "Принято": 0,
                             "Не дождались": 0, "Всего": 0})
                continue
            lost = int(total * lost_share(project, day, hour, rng))
            rows.append({"Дата": day, "Час": hour,
                         "Принято": total - lost, "Не дождались": lost,
                         "Всего": total})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Демонстрационные выгрузки")
    ap.add_argument("--days", type=int, default=30, help="сколько дней")
    ap.add_argument("--seed", type=int, default=42, help="одинаковые числа при каждом запуске")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    random.seed(args.seed)

    days = [END_DAY - timedelta(days=i) for i in reversed(range(args.days))]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Период: {days[0]:%d.%m.%Y} — {days[-1]:%d.%m.%Y}\n")

    for project in PROJECTS:
        calls = make_calls(project, days, rng)
        hourly = make_hourly(project, days, rng)
        calls.to_excel(DATA_DIR / f"{project}_calls_month.xlsx", index=False)
        hourly.to_excel(DATA_DIR / f"{project}_hourly.xlsx", index=False)
        print(f"  {project:<8} {len(calls):>6} звонков, "
              f"{len(hourly):>4} часовых строк")

    print(f"\nФайлы в {DATA_DIR}")
    print("Дальше: python load_daily.py")


if __name__ == "__main__":
    main()
