# -*- coding: utf-8 -*-
"""
Выгрузка детализации звонков из CRM для ноутбуков.

Заменяет ручную работу: раздел «Отчёты» -> плюс -> выбрать компанию
и даты -> создать -> скачать Детализацию. Скрипт делает это по всем
действующим проектам за один прогон и сохраняет файлы сразу под
теми именами, которые ждут ноутбуки. Переименовывать ничего не нужно.

Порядок работы:
    1. запускаешь скрипт, отвечаешь на три вопроса (можно просто
       трижды нажать Enter — подставятся значения по умолчанию),
    2. файлы легли в папку data/,
    3. запускаешь ноутбуки как обычно.

Ноутбуки никуда не деваются: скрипт заменяет только скачивание,
а разбор данных и выгрузку в Google Sheets по-прежнему делают они.

Пароль в коде НЕ хранится. Он лежит в файле .env в корне
репозитория (образец — .env.example):
    CRM_HOST=адрес CRM в локальной сети
    CRM_USER=report_user
    CRM_PASSWORD=пароль

Нужны пакеты:
    pip install requests beautifulsoup4 python-dotenv
"""
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Корень репозитория: скрипт лежит в etl/, значит на уровень выше.
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ============================ НАСТРОЙКИ ============================

IP = os.getenv("CRM_HOST", "crm.local")
BASE = f"http://{IP}/crm"

# Куда класть файлы — туда, где их ищут ноутбуки.
OUT_DIR = ROOT / "data"

# Спрашивать параметры при запуске. False — молча взять значения
# ниже. Выключай, если поставишь скрипт в Планировщик заданий:
# там некому отвечать на вопросы, и скрипт повиснет на вводе.
ASK = True

# Значения по умолчанию. Их же скрипт предлагает в вопросах —
# достаточно нажать Enter.
# Последний день выгрузки. None — вчерашний день.
END_DATE = None

# Сколько дней качать. Первый день — буферный: CRM теряет первую
# запись запрошенного периода, и ноутбуки этот день выбрасывают.
#
# ТРИ, а не два. Буфер защищает, только если в нём ЕСТЬ звонки.
# У Alpha операторы не работают в воскресенье и праздники —
# в CRM за такой день ноль строк. Тогда первой записью периода
# становится первый звонок РАБОЧЕГО дня, и теряется именно он.
# Так и было: после праздника и после воскресений пропадали первые
# звонки рабочего дня — все в самом начале смены.
# Третий день отодвигает буфер на субботу или предпраздничный день,
# где звонки есть.
#
# Если нерабочих дней подряд окажется больше (длинные выходные),
# ноутбук предупредит: он видит, что в буферном дне CRM пуст.
DAYS = 3

# Исключения по дням. Нужны, только когда ASK = False: при запуске
# с вопросами число дней задаётся прямо в консоли.
DAYS_BY_PROJECT = {
}

# Группы проектов — то, что предлагается при запуске.
GROUPS = {
    "alpha": ["alpha_crm"],
    "project6":   ["beta_crm", "gamma_crm", "delta_crm",
                   "epsilon_crm", "zeta_crm", "eta_crm"],
}

# имя файла (без .xlsx) -> номер компании в CRM.
# Номера взяты из выпадающего списка на странице «Отчёты».
# ВНИМАНИЕ: в CRM бывают компании с похожими названиями. Номер
# сверяй по списку, а не по имени: ошибка даст чужую выгрузку.
PROJECTS = {
    "alpha_crm":   101,
    "beta_crm":    102,
    "gamma_crm":   103,
    "delta_crm":   104,
    "epsilon_crm": 105,
    "zeta_crm":    106,
    "eta_crm":     107,
}

# Сколько ждать готовности отчёта, секунд
WAIT_TIMEOUT = 90

# Начиная со скольких дней спрашивать подтверждение.
# Страховка от опечатки: набрал 20 вместо 2 — скрипт покажет план
# и переспросит, а не молча скачает три недели по всем проектам.
CONFIRM_FROM_DAYS = 7

# ==================================================================

LOGIN_URL = f"{BASE}/account/login"
REPORTS_URL = f"{BASE}/report/index"
CREATE_URL = f"{BASE}/report/create"
DOWNLOAD_URL = f"{BASE}/report/download"


def ask_date(default: date) -> date:
    """
    Спрашивает последний день выгрузки.

    Пустой ответ — берём значение по умолчанию. При кривом вводе
    переспрашиваем, а не падаем: ошибиться в дате легко, и лучше
    поправить сразу, чем разбираться, почему файл пустой.
    """
    while True:
        raw = input(f"Последний день [{default:%Y-%m-%d}]: ").strip()
        if not raw:
            return default
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("   Не понял. Формат: 2026-08-17")


def ask_days(default: int) -> int:
    """Спрашивает, сколько дней качать (буферный плюс рабочие)."""
    while True:
        raw = input(f"Сколько дней [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= 62:
            return int(raw)
        print("   Нужно число от 1 до 62")


def ask_projects() -> dict:
    """
    Спрашивает, что качать: группу или отдельный проект.

    Понимает и название группы («project6»), и имя проекта целиком
    или частью («beta»). Пустой ответ — всё. Если ничего не
    совпало, переспрашиваем: молча скачать не то хуже, чем
    спросить лишний раз.
    """
    names = list(PROJECTS)
    print("   Группы: " + ", ".join(GROUPS))
    print("   Или проект: " + ", ".join(n.replace("_crm", "") for n in names))

    while True:
        raw = input("Что качать [всё]: ").strip().lower()
        if not raw:
            return dict(PROJECTS)

        chosen, unknown = {}, []
        for part in re.split(r"[,\s]+", raw):
            if not part:
                continue
            if part in GROUPS:
                chosen.update({n: PROJECTS[n] for n in GROUPS[part]
                               if n in PROJECTS})
                continue
            hit = [n for n in names if part in n]
            if hit:
                chosen.update({n: PROJECTS[n] for n in hit})
            else:
                unknown.append(part)

        if unknown:
            print(f"   Не нашёл: {', '.join(unknown)}")
            continue
        if chosen:
            return chosen


def confirm_plan(end: date, days: int, projects: dict,
                 per_project: dict) -> bool:
    """
    Показывает план и спрашивает подтверждение на длинных периодах.

    Срабатывает только когда дней много: обычный ежедневный запуск
    на три дня проходит без лишних вопросов. Ошибиться в числе легко,
    а разгребать три недели, разложенные по гугл-таблицам, долго.
    """
    longest = max([per_project.get(n, days) for n in projects] or [days])
    if longest < CONFIRM_FROM_DAYS:
        return True

    print(f"\n   ВНИМАНИЕ: период {longest} дней — это много для "
          f"ежедневной выгрузки.")
    print("   Будет скачано:")
    for name in projects:
        d = per_project.get(name, days)
        start = end - timedelta(days=d - 1)
        print(f"      {name:<16} {start:%d.%m.%Y} — {end:%d.%m.%Y}  ({d} дн.)")
    print("   Файлы с такими именами в папке будут перезаписаны.")

    answer = input("   Продолжить? [да/нет]: ").strip().lower()
    return answer in ("да", "д", "yes", "y")


def get_csrf(session: requests.Session, url: str) -> str:
    """
    Достаёт CSRF-токен из <meta name="csrf-token">.

    Токен нужен при каждом POST — без него сервер отклонит запрос.
    Берём свежий перед каждой отправкой: старый может протухнуть.
    """
    soup = BeautifulSoup(session.get(url, timeout=15).text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    if not meta or not meta.get("content"):
        raise RuntimeError(f"CSRF-токен не найден на {url}")
    return meta["content"]


def login(session: requests.Session) -> None:
    """Вход в CRM. Логин и пароль читаются из .env, а не из кода."""
    user = os.environ.get("CRM_USER")
    password = os.environ.get("CRM_PASSWORD")
    if not user or not password:
        raise RuntimeError("Нет CRM_USER или CRM_PASSWORD — создай .env")

    csrf = get_csrf(session, LOGIN_URL)
    session.post(LOGIN_URL, data={
        "_csrf": csrf,
        "LoginForm[username]": user,
        "LoginForm[password]": password,
    }, timeout=15)

    html = session.get(REPORTS_URL, timeout=15).text
    if "LoginForm" in html:
        raise RuntimeError("Вход не удался — проверь логин и пароль в .env")
    print(f"Вход выполнен под {user}")


def report_ids(session: requests.Session, company_id: int) -> set:
    """
    Собирает Id отчётов ЭТОЙ компании.

    Фильтруем список по компании, а не смотрим всё подряд: иначе
    чужой отчёт, созданный супервайзером в ту же секунду, мог бы
    сойти за наш. Id берём из ссылок скачивания на странице.
    """
    html = session.get(REPORTS_URL, params={
        "ReportSearch[CompanyID]": company_id,
    }, timeout=20).text
    return set(re.findall(r"download\?id=(\d+)", html))


def create_report(session: requests.Session, company_id: int,
                  d_from: date, d_to: date) -> None:
    """
    Создаёт отчёт. Поля ровно те, что уходят из браузера:
    Report[CompanyID], Report[StartDate], Report[EndDate].
    Конец дня — 23:59:59, чтобы последние звонки не потерялись.
    """
    csrf = get_csrf(session, CREATE_URL)
    session.post(CREATE_URL, params={"Reset": 1}, data={
        "_csrf": csrf,
        "Report[CompanyID]": str(company_id),
        "Report[StartDate]": f"{d_from:%Y-%m-%d} 00:00:00",
        "Report[EndDate]": f"{d_to:%Y-%m-%d} 23:59:59",
    }, timeout=60)


def wait_new_id(session: requests.Session, company_id: int,
                before: set) -> str:
    """
    Ждёт, пока в списке появится Id, которого не было до создания.

    Отчёт готовится не мгновенно — сервер собирает Excel несколько
    секунд. Опрашиваем список раз в две секунды. Если новых Id
    оказалось несколько, берём наибольший: он создан последним.
    """
    deadline = time.time() + WAIT_TIMEOUT
    while time.time() < deadline:
        new = report_ids(session, company_id) - before
        if new:
            return max(new, key=int)
        time.sleep(2)
    raise TimeoutError(f"Отчёт не появился за {WAIT_TIMEOUT} секунд")


def download(session: requests.Session, report_id: str, name: str) -> Path:
    """
    Скачивает Excel по id отчёта (format=xlsx).

    Проверяем тип ответа: если сессия истекла, CRM вернёт страницу
    логина с кодом 200, и без проверки мы бы записали HTML в файл
    с расширением .xlsx. Ноутбук потом упал бы с непонятной ошибкой.
    """
    resp = session.get(DOWNLOAD_URL,
                       params={"id": report_id, "format": "xlsx"}, timeout=120)
    resp.raise_for_status()

    ctype = resp.headers.get("Content-Type", "")
    if "spreadsheet" not in ctype and "excel" not in ctype:
        raise RuntimeError(f"Ожидал Excel, пришло {ctype!r} — "
                           f"скорее всего сессия истекла")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.xlsx"
    path.write_bytes(resp.content)
    return path


def main() -> None:
    default_end = END_DATE or (date.today() - timedelta(days=1))

    if ASK:
        end = ask_date(default_end)
        days_all = ask_days(DAYS)
        projects = ask_projects()
        per_project = {}          # при вводе с клавиатуры исключений нет
    else:
        end, days_all = default_end, DAYS
        projects = dict(PROJECTS)
        per_project = DAYS_BY_PROJECT

    if not confirm_plan(end, days_all, projects, per_project):
        print("Отменено — ничего не скачано.")
        return

    session = requests.Session()
    login(session)

    print(f"Папка: {OUT_DIR}\n")
    ok = 0
    for name, company_id in projects.items():
        days = per_project.get(name, days_all)
        start = end - timedelta(days=days - 1)
        try:
            before = report_ids(session, company_id)
            create_report(session, company_id, start, end)
            report_id = wait_new_id(session, company_id, before)
            path = download(session, report_id, name)
            size_kb = path.stat().st_size // 1024
            print(f"  {name:<16} {start:%d.%m}-{end:%d.%m} "
                  f"отчёт #{report_id:<6} {size_kb} КБ")
            ok += 1
        except Exception as e:
            print(f"  {name:<16} ОШИБКА — {type(e).__name__}: {e}")

    print(f"\nГотово: {ok} из {len(projects)}. Можно запускать ноутбуки.")


if __name__ == "__main__":
    main()
