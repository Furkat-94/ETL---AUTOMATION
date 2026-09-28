# -*- coding: utf-8 -*-
"""
Настройки пайплайна. Всё, что меняется, собрано здесь.

Секретов в файле нет: адрес источника, логин и пароль читаются из
окружения. Рядом лежит .env.example — скопируй его в .env и заполни.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# --- база ---
# Строка подключения. При переезде на сервер меняется она, плюс места,
# завязанные на SQLite (см. README, «Готовность к переезду»):
#   postgresql+psycopg2://user:pass@host:5432/callcenter
#   mssql+pyodbc://user:pass@host/callcenter?driver=ODBC+Driver+17
DB_URL = os.getenv("DB_URL", f"sqlite:///{ROOT / 'callcenter.db'}")

# --- источник данных ---
SOURCE_URL = os.getenv("SOURCE_URL", "")
SOURCE_USER = os.getenv("SOURCE_USER", "")
SOURCE_PASSWORD = os.getenv("SOURCE_PASSWORD", "")

# Папка с выгрузками: <проект>_calls_month.xlsx и <проект>_hourly.xlsx
DATA_DIR = ROOT / "data"

# Проекты, по которым идёт учёт.
PROJECTS = ["alpha", "beta", "gamma", "delta"]

# --- правила предметной области ---
# Первая запись периода теряется при выгрузке, поэтому качаем с
# запасом в день и самый ранний день отбрасываем. У файлов со словом
# month в имени этого не делаем: там теряется одна запись за месяц,
# а не за день, и отрезать целые сутки ради неё бессмысленно.
DROP_BUFFER_DAY = True

# Ночная смена переходит через полночь.
NIGHT_START, NIGHT_END = "19:00:00", "08:00:00"

# --- пороги аналитики ---
ANOMALY_SIGMA = 3.0        # насколько сильно день должен отклониться
ANOMALY_MIN_REL = 0.30     # и хотя бы на треть от нормы
ANOMALY_MIN_DAYS = 8       # столько похожих дней нужно, чтобы считать норму
ANOMALY_TOP = 3            # больше событий на проект не показываем
MIN_CALLS_PER_DAY = 10     # проекты мельче не анализируем: там всё шум
