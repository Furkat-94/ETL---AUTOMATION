# -*- coding: utf-8 -*-
"""
Аналитика поверх базы: поиск аномалий и профиль нагрузки по часам.

    python analytics.py

ГЛАВНАЯ МЫСЛЬ ЭТОГО ФАЙЛА
Аномалия — редкое событие. Если отчёт находит десяток аномалий за
две недели, значит порог занижен и в список попал обычный разброс.
Такой отчёт хуже отсутствия отчёта: его перестают читать.

Поэтому день попадает в список, только если проходит все проверки:

  1. Сильно отклонился по разбросу самого проекта — не меньше трёх
     сигм. Норма считается по медиане и MAD, а не по среднему и
     стандартному отклонению: последние сносит один выброс, и после
     аномального дня норма задирается так, что следующие аномалии
     уже не находятся.

  2. Отклонился заметно и в абсолютных числах — минимум на треть.
     Иначе у мелкого проекта прыжок с 2 до 8 звонков выглядит
     катастрофой, хотя это два человека.

  3. Норма посчитана хотя бы по восьми похожим дням. На четырёх
     точках разброс считать нельзя: там аномалия что угодно.

Будни и выходные сравниваются раздельно: у выходного своя картина,
и по общей норме каждое воскресенье выглядело бы провалом.

Подряд идущие дни склеиваются в одно событие. Три дня падения —
это одна проблема, а не три строки в отчёте.
"""
import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from config import (ANOMALY_MIN_DAYS, ANOMALY_MIN_REL, ANOMALY_SIGMA,
                    ANOMALY_TOP, DB_URL, MIN_CALLS_PER_DAY)


def load_daily(engine) -> pd.DataFrame:
    """Дневная картина: звонки из реестра плюс телефония по часам."""
    calls = pd.read_sql("SELECT * FROM v_daily", engine)
    service = pd.read_sql("SELECT * FROM v_service", engine)

    df = calls.merge(service, on=["project", "call_date"], how="outer")
    df["call_date"] = pd.to_datetime(df["call_date"])
    df["Тип дня"] = np.where(df["call_date"].dt.weekday >= 5,
                             "выходной", "будний")
    df["answer_share"] = 1 - df["lost_share"]
    return df.sort_values(["project", "call_date"])


def robust_spread(v: pd.Series) -> float:
    """
    Разброс по MAD — устойчивая замена стандартному отклонению.

    Множитель 1.4826 приводит MAD к той же шкале, что и сигма для
    нормального распределения: пороги в сигмах остаются привычными.
    """
    v = v.dropna()
    if len(v) < ANOMALY_MIN_DAYS:
        return np.nan
    mad = (v - v.median()).abs().median()
    return float(mad * 1.4826) if mad > 0 else float(v.std())


def find_anomalies(daily: pd.DataFrame) -> pd.DataFrame:
    """Возвращает редкие события — по три самых сильных на проект."""
    checks = [
        ("answer_share", "дозвонились намного реже обычного", "down",
         "люди не дозвонились до нас", True),
        ("total", "звонков пришло намного больше обычного", "up",
         "поток вырос — смотреть, хватило ли людей", False),
        ("total", "звонков пришло намного меньше обычного", "down",
         "поток упал — возможно, что-то с линией", False),
    ]

    hits = []
    for project, g in daily.groupby("project"):
        if g["total"].sum() / max(len(g), 1) < MIN_CALLS_PER_DAY:
            continue

        for _, part in g.groupby("Тип дня"):
            if len(part) < ANOMALY_MIN_DAYS:
                continue

            for col, label, side, why, as_share in checks:
                med = part[col].median()
                spread = robust_spread(part[col])
                if not spread or np.isnan(spread) or not med:
                    continue

                for _, r in part.iterrows():
                    val = r[col]
                    if pd.isna(val):
                        continue
                    z = (val - med) / spread
                    if abs(val - med) / abs(med) < ANOMALY_MIN_REL:
                        continue
                    if side == "up" and z < ANOMALY_SIGMA:
                        continue
                    if side == "down" and z > -ANOMALY_SIGMA:
                        continue

                    fmt = (lambda x: f"{x * 100:.0f}%") if as_share \
                        else (lambda x: f"{x:.0f}")
                    hits.append({"Проект": project, "_d": r["call_date"],
                                 "_key": (col, label), "_z": abs(z),
                                 "Что случилось": label,
                                 "В этот день": fmt(val), "Обычно": fmt(med),
                                 "Что это значит": why})

    if not hits:
        return pd.DataFrame()

    # Склейка подряд идущих дней в одно событие.
    events = []
    df = pd.DataFrame(hits)
    for (project, key), items in df.groupby(["Проект", "_key"]):
        items = items.sort_values("_d")
        run = [items.iloc[0]]
        for _, cur in items.iloc[1:].iterrows():
            if (cur["_d"] - run[-1]["_d"]).days <= 1:
                run.append(cur)
            else:
                events.append(run)
                run = [cur]
        events.append(run)

    rows = []
    for run in events:
        best = max(run, key=lambda x: x["_z"])
        first, last = run[0]["_d"], run[-1]["_d"]
        rows.append({
            "Проект": best["Проект"],
            "Когда": (f"{first:%d.%m.%Y}" if first == last
                      else f"{first:%d.%m} — {last:%d.%m.%Y}"),
            "Что случилось": best["Что случилось"],
            "В этот день": best["В этот день"],
            "Обычно": best["Обычно"],
            "Насколько сильно": (f"{len(run)} дня подряд" if len(run) > 1
                                 else ("очень сильно" if best["_z"] >= 5
                                       else "заметно")),
            "Что это значит": best["Что это значит"],
            "_z": best["_z"], "_d": first,
        })

    out = pd.DataFrame(rows)
    out = (out.sort_values("_z", ascending=False)
              .groupby("Проект", group_keys=False).head(ANOMALY_TOP))
    return out.sort_values(["Проект", "_d"]).drop(columns=["_z", "_d"])


def hour_profile(engine) -> pd.DataFrame:
    """
    Часы, в которые чаще всего не дозваниваются.

    Отвечает на вопрос, который на самом деле волнует бизнес: не
    «сколько мы потеряли», а «когда именно и что с этим делать».
    """
    df = pd.read_sql("SELECT * FROM v_hourly", engine)
    df = df[df["total"] > 0].copy()
    df["Час"] = df["call_hour"].map(lambda h: f"{h:02d}:00-{h + 1:02d}:00")
    df["Доля неотвеченных"] = (df["lost_share"] * 100).round(1)
    worst = (df.sort_values("lost_share", ascending=False)
               .groupby("project", group_keys=False).head(3))
    return worst[["project", "Час", "total", "lost",
                  "Доля неотвеченных"]].rename(
        columns={"project": "Проект", "total": "Всего звонков",
                 "lost": "Не дождались"})


def main() -> None:
    engine = create_engine(DB_URL)
    daily = load_daily(engine)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 42)

    days = daily["call_date"].nunique()
    print(f"Период: {days} дней, проектов {daily['project'].nunique()}\n")

    print("=" * 78)
    print("АНОМАЛИИ — дни, которые выбились из обычной картины")
    print("=" * 78)
    a = find_anomalies(daily)
    print(a.to_string(index=False) if len(a) else "  ничего необычного")

    print("\n" + "=" * 78)
    print("ХУДШИЕ ЧАСЫ — когда до нас не дозваниваются")
    print("=" * 78)
    print(hour_profile(engine).to_string(index=False))
    engine.dispose()


if __name__ == "__main__":
    main()
