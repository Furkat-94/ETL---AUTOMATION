# ETL и аналитика контакт-центра

[Русский](#русский) · [English](#english)

---

## Русский

Автоматизация ежедневной отчётности аутсорсингового контакт-центра:
выгрузки из CRM и телефонии (АТС) разбираются, сверяются и ложатся
в Google Sheets, а поверх них считается аналитика.

Сделано на реальной задаче. Код — обезличенная копия рабочих
скриптов: проекты-заказчики названы греческими буквами, данных
заказчиков в репозитории нет. Вместо них — генераторы демо-данных
в тех же форматах, поэтому всё запускается без доступа к CRM и Google.

### Было и стало

**Было.** Отчётность собиралась руками: скачать семь файлов,
разложить по таблицам, посчитать показатели. Полдня ежедневно, и
половина времени уходила на перенос цифр, а не на их разбор.

- выгрузки качались из CRM вручную: «Отчёты» → компания → даты →
  создать → скачать «Детализацию», и так по каждому проекту;
- цифры переносились в Google Sheets и сверялись вручную;
- KPI операторов снимались с экрана CRM: дата, оператор, фильтр
  результата, число из строки «Показаны 1-20 из N записи».

**Стало.** Ручными остались только те шаги, где данные физически
недоступны программе.

- `crm_reports.py` качает выгрузки всех проектов за один прогон и
  кладёт их под теми именами, что ждут ноутбуки;
- ноутбуки считают сводки, сверяют их с первоисточником и пишут
  дневные листы; при расхождении запись останавливается;
- `kpi_daily.py` снимает счётчики CRM сам и пишет их в таблицу KPI;
- `reconciliation.ipynb` находит звонки, пропавшие между месячной
  выгрузкой и дневными листами, и дописывает их после подтверждения.

### Как устроено

Две части. `etl/` — ежедневная отчётность в Google Sheets, рабочий
код. Корень — SQL-часть: те же по смыслу выгрузки складываются в
базу, и по ней ищутся аномальные дни.

```
      CRM (веб)               АТС (телефония)
          │ crm_reports.py        │ файлы .xls
          ▼                       ▼
   data/*_crm.xlsx         data/*_pbx.xls
          └───────────┬───────────┘
                      ▼
    etl_core: чтение, буферный день,
              даты, сверки
                      ▼
    alpha_registry · omega_registry
          · monitoring (ноутбуки)
                      ▼
    Google Sheets: лист на каждый день
    (DEMO=1 → data/demo_output/*.xlsx)
          │                     │
          ▼                     ▼
   reconciliation        sheets_analytics
   сверка с месячной     нагрузка, качество,
   выгрузкой CRM         операторы, аномалии

   CRM (счётчики) → kpi_daily → «KPI операторов»
                           → kpi_monthly → Excel к оплате
   CRM (счётчики) → operators_report → «Отчёт операторов»
```

SQL-часть:

```
data/sql/*.xlsx → load_daily.py → SQLite → analytics.py
                                    │
                               queries.sql
```

| Проект | Источники |
|---|---|
| Alpha | реестр CRM + реестр АТС (строка на звонок) |
| Omega | только реестр CRM (проект закрыт) |
| Beta…Eta | CRM + почасовой отчёт АТС |
| Theta, Iota, Kappa | анкетирование, KPI операторов |

### Запуск демо

```bash
pip install -r requirements.txt
```

**etl/ — ежедневная отчётность.** Демо-режим пишет не в Google
Sheets, а в Excel-файлы в `data/demo_output/`, и не ходит в CRM.

```bash
cp .env.example .env      # в .env поставить DEMO=1
python etl/generate_etl_demo.py
```

Дальше в папке `etl/` открыть в Jupyter или DataSpell и выполнить
по порядку ячейки `alpha_registry.ipynb`, `omega_registry.ipynb` и
`monitoring.ipynb` (ячейки 1–3). Результат — книги
`Alpha Август 2026.xlsx`, `Omega Август 2026.xlsx` и
`monitoring.xlsx` в `data/demo_output/`.

Демо-выгрузки — за 15–17.08.2026: суббота, воскресенье, понедельник.
Даты и зерно фиксированные, поэтому цифры одни и те же при любом
запуске. Так выглядит вывод `alpha_registry.ipynb`:

```
Буферный день 15.08.2026 — 169 строк АТС,
  117 строк CRM. Грузиться НЕ будет.
16.08.26: CRM пустой — исходящие приму за 0
Посчитано дней: 2
  16.08.26: все 76, входящие 0, пропущенные 76, исходящие 0
  17.08.26: все 209, входящие 137, пропущенные 56, исходящие 16
```

В воскресенье операторы Alpha не работают: CRM пуст, но АТС видит
пропущенные звонки, и отчёт за день всё равно строится. Все пять
сверок по каждому дню сходятся.

Что делают остальные файлы `etl/` в демо-режиме:

- `crm_reports.py`, `kpi_daily.py`, `operators_report.ipynb` — всё
  берут живыми запросами к CRM; в демо сообщают об этом и
  останавливаются;
- ячейка 4 `monitoring.ipynb` (итог месяца) и `reconciliation.ipynb`
  читают из таблиц посчитанные формулы, а в демо-Excel формулы
  хранятся текстом — поэтому они останавливаются с объяснением;
- `sheets_analytics.ipynb` работает поверх демо-книг, если в ячейке 1
  поставить `REPORT_DATE = date(2026, 8, 17)`;
- `kpi_monthly.py` и `client_report.py` читают листы, которые в
  демо никто не заполняет, поэтому показывать им нечего.

**SQL-часть — база и поиск аномалий.**

```bash
python generate_demo.py      # создаст демо-выгрузки в data/sql/
python load_daily.py         # загрузит их в базу
python analytics.py          # найдёт аномалии и худшие часы
```

Графики на тех же данных — `demo_analysis.ipynb` в корне: нагрузка
по часам, доля пропущенных, аномальные дни, операторы. Выводы под
графиками не вписаны руками, их печатает код по данным в базе.

**Тесты.** `pytest` из корня проверяет правила, на которых держатся
отчёты: округление минут (и правило Alpha «до 5 секунд — 0 минут»),
тарифную сетку KPI, разбор чисел «1 036» из АТС и выбор буферного
дня — в etl/ и в SQL-части.

### Инженерные решения

#### Буферный день

CRM теряет первую запись запрошенного периода — ровно одну,
независимо от длины периода. При выгрузке за день это первый звонок
дня, и он пропадал бы каждый день.

Поэтому выгрузка берётся за три дня, и самый ранний день —
буферный: он показывается на экране, но не грузится. Теряется
первый звонок буферного дня, а рабочие дни приходят целыми
(`MultiDay.plan` в `etl_core.py`).

Три дня, а не два: по воскресеньям и праздникам у Alpha звонков в
CRM нет. Если буферный день пустой, первой записью периода
становится первый звонок рабочего дня — и теряется именно он.
`alpha_registry.ipynb` видит пустой буфер и предупреждает.

В `monitoring.ipynb` рабочая дата определяется один раз по всем
файлам, а не по каждому проекту: иначе проект без звонков в этот
день взял бы вчерашнюю дату, и вчерашние исходящие попали бы в
сегодняшний отчёт.

В SQL-части правило то же (`drop_buffer` в `load_daily.py`), но для
месячной выгрузки оно отключается: там теряется одна запись первого
числа, и отрезать ради неё целые сутки бессмысленно. Признак —
слово `month` в имени файла.

#### Сверки перед записью

Ноутбуки сверяют свои агрегаты с первоисточником и не пишут ничего,
если хоть одна сверка не сошлась (`Validator` и `assert`):

- Alpha: сумма по операторам равна принятым входящим; почасовые
  суммы — числу строк реестра АТС и CRM;
- Monitoring: почасовая сетка против строки «Итого» самого отчёта
  АТС; итог месяца — блок формул СУММЕСЛИ против почасовой сетки,
  битые формулы и вкладки с опечаткой в дате называются вслух.

`kpi_daily.py` перед записью сравнивает независимый итог с главного
экрана CRM с суммой того, что пойдёт в таблицу, и объясняет каждую
разницу: позиции Lambda, позиции вне таблицы, звонки без оператора.

`reconciliation.ipynb` сверяет месячную выгрузку CRM с дневными
листами. Ключ — ID звонка плюс телефон, а не один ID: при переводе
звонка CRM отдаёт две строки с одним ID. Пропавшие звонки
дописываются только после того, как показан план записи.

#### Защита от дублей позиций в KPI

Строка оператора на листе KPI ищется по номеру позиции в колонке A,
только в рабочем списке и только в позициях 1…`MAX_WRITE_POS`.
Разделы «Подмена» и «Выбывшие» скрипт не трогает.

Если номер позиции встретился в рабочем списке дважды, скрипт не
пишет его никуда: какая из строк правильная, ему не узнать, а на
зарплате угадывать нельзя. Остальные позиции он записывает и
говорит, какую строку исправить.

#### Идемпотентная загрузка

Один и тот же файл можно загрузить сколько угодно раз — результат
будет тем же. На практике перезапускать приходится постоянно: то
файл пришёл неполный, то нашлась ошибка в разборе.

- SQL-часть: перед вставкой строки за эти даты удаляются. Всё в
  одной транзакции на файл (`engine.begin()`): либо загрузилось всё,
  либо ничего, и сбой на одном файле не отменяет уже загруженные.
  Журнал `load_log` хранит, какой файл, когда и сколько строк принёс.
- etl/: лист ищется по дате в обоих форматах имени (`23.07.26` и
  `23.07.2026`) и очищается перед записью — перезапуск переписывает
  день, а не создаёт дубль. В `monitoring.ipynb` очищается только
  сетка A:G, блок формул I:O с ручными правками не трогается.

#### Мелочи, которые ломали отчёты

- Числа АТС от тысячи приходят как «1 036», иногда с неразрывным
  пробелом. Обычный `to_numeric` даёт на них NaN, а `fillna(0)`
  молча превращает тысячу звонков в ноль (`ExcelReader._to_num`).
- Дата отчёта берётся из данных, а не из системных часов: отчёты
  закрываются последовательно, и 23-е число делают, когда на
  календаре уже 25-е.
- Если АТС прислала реестр звонков вместо почасового отчёта, скрипт
  останавливается и показывает, что внутри файла: свернуть чужой
  файл молча опаснее, чем упасть.
- Колонки CRM берутся по имени, а не по позиции: новое поле слева
  не сдвинет данные на соседний столбец.

### Аномалия должна быть редкостью

Первая версия находила десяток аномалий за две недели. Это не
аномалии, а обычный разброс — и такой отчёт перестают читать.

Сейчас день попадает в список, только если проходит все три проверки:

1. **Отклонение не меньше трёх сигм.** Норма считается по медиане и
   MAD, а не по среднему и стандартному отклонению: последние сносит
   один выброс, и после аномального дня норма задирается так, что
   следующие аномалии уже не находятся.
2. **Отклонение не меньше трети от нормы.** Иначе у мелкого проекта
   прыжок с 2 до 8 звонков выглядит катастрофой.
3. **Норма посчитана хотя бы по восьми похожим дням.** На четырёх
   точках разброс считать нельзя.

Плюс два правила поверх:

- **Будни и выходные сравниваются раздельно.** По общей норме каждое
  воскресенье выглядело бы провалом.
- **Подряд идущие дни склеиваются в одно событие.** Три дня падения —
  это одна проблема, а не три строки.

На демонстрационных данных SQL-части в генератор заложен ровно один
сбой — три дня подряд у проекта `beta`. Аналитика находит его и
больше ничего. Пример вывода (даты и проценты зависят от дня запуска:
демо-период заканчивается вчерашним днём):

```
Проект  Когда                Что случилось
beta    15.08 — 17.08.2026   дозвонились намного реже обычного

В этот день  Обычно  Насколько сильно
43%          82%     3 дня подряд
```

Проект `delta` с восемью звонками в день отсеивается до анализа: на
таких числах любое движение укладывается в случайность, и честнее
не делать выводов, чем делать неверные.

### Оконные функции

`queries.sql` содержит разобранные примеры: ранг оператора внутри
проекта, сравнение с предыдущим днём через `LAG`, скользящая норма с
рамкой `ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING`, нарастающий итог,
поиск дырок в загрузке.

Два места, где легко ошибиться, разобраны в комментариях:

- **Текущий день исключается из скользящей нормы.** Иначе всплеск
  попадает в собственную норму и сам себя размывает.
- **Фильтровать по результату оконной функции в `WHERE` нельзя** —
  она считается позже. Нужен CTE.

### Готовность к переезду на сервер

Работа с базой идёт через SQLAlchemy, строка подключения — одна
настройка в `config.py`. Но переезд на PostgreSQL или MS SQL — это не
только она: в `schema.sql` поле `id INTEGER PRIMARY KEY` рассчитано на
автоинкремент SQLite, а в `queries.sql` есть функции SQLite (`printf`,
`julianday`). Эти места придётся переписать.

### Структура

```
config.py            настройки SQL-части, секреты из .env
generate_demo.py     демо-выгрузки для SQL-части
load_daily.py        загрузка в базу
analytics.py         аномальные дни и худшие часы
schema.sql views.sql таблицы и витрины
queries.sql          разборы оконных функций
demo_analysis.ipynb  графики на демо-данных SQL-части
tests/test_rules.py  тесты правил (pytest)
etl/
  etl_core.py        общий модуль: пути, .env, чтение
                     Excel, даты, Google Sheets, сверки,
                     демо-режим
  generate_etl_demo.py  демо-выгрузки CRM и АТС
  crm_reports.py     скачивает выгрузки из CRM
  alpha_registry.ipynb  Alpha: CRM + реестр АТС
  omega_registry.ipynb  Omega: только CRM
  monitoring.ipynb   Beta…Eta: почасовой отчёт АТС
                     + исходящие из CRM
  reconciliation.ipynb  сверка с месячной выгрузкой
  operators_report.ipynb отчёт операторов по CRM
  kpi_daily.py       KPI операторов на анкетировании
  kpi_monthly.py     месячный итог KPI для оплаты
  client_report.py   отчёт для заказчика Gamma
  sheets_analytics.ipynb аналитика поверх таблиц
etl-basics/          мой первый учебный ETL
data/                выгрузки и результаты, в git не
                     попадают
```

Секреты — только в `.env` (образец — `.env.example`); `.env`,
`credentials.json`, выгрузки и база в git не попадают.

### Что дальше

- Расписание вместо ручного запуска
- Перенос на серверную СУБД
- Дашборд поверх витрин

---

## English

Automated daily reporting for an outsourcing contact center: exports
from the CRM and the phone system (PBX) are parsed, reconciled and
written to Google Sheets, and analytics is built on top of them.

Built for a real job. The code is an anonymized copy of production
scripts: client projects are named after Greek letters, and no client
data is in the repository. Instead there are demo data generators
that produce files in the same formats, so everything runs without
access to the CRM or Google.

### Before and after

**Before.** Reporting was manual: download seven files, spread them
across spreadsheets, calculate the metrics. Half a day, every day,
and half of that time went into copying numbers rather than
analysing them.

- CRM exports were downloaded by hand: "Reports" → client → dates →
  create → download the call detail export, for every project;
- numbers were copied into Google Sheets and checked by hand;
- operator KPIs were read off the CRM screen: date, operator, result
  filter, the number from "Showing 1-20 of N records".

**After.** Only the steps where the data is physically unavailable
to a program remain manual.

- `crm_reports.py` downloads the exports of all projects in one run
  and saves them under the names the notebooks expect;
- the notebooks build the summaries, reconcile them against the
  source and write the daily sheets; any mismatch stops the write;
- `kpi_daily.py` reads the CRM counters itself and writes them to
  the KPI spreadsheet;
- `reconciliation.ipynb` finds calls lost between the monthly export
  and the daily sheets and writes them back after confirmation.

### How it works

Two parts. `etl/` is daily reporting into Google Sheets, the
production code. The repository root is the SQL part: similar
exports are loaded into a database used to find anomalous days.

```
     CRM (web)                 PBX (phone system)
          │ crm_reports.py        │ .xls files
          ▼                       ▼
   data/*_crm.xlsx         data/*_pbx.xls
          └───────────┬───────────┘
                      ▼
    etl_core: reading, buffer day,
              dates, reconciliation
                      ▼
    alpha_registry · omega_registry
          · monitoring (notebooks)
                      ▼
    Google Sheets: one sheet per day
    (DEMO=1 → data/demo_output/*.xlsx)
          │                     │
          ▼                     ▼
   reconciliation        sheets_analytics
   vs. the monthly       load, quality,
   CRM export            operators, anomalies

   CRM (counters) → kpi_daily → "Operator KPI"
                          → kpi_monthly → Excel for payroll
   CRM (counters) → operators_report → "Operators report"
```

The SQL part:

```
data/sql/*.xlsx → load_daily.py → SQLite → analytics.py
                                    │
                               queries.sql
```

| Project | Sources |
|---|---|
| Alpha | CRM log + PBX call log (one row per call) |
| Omega | CRM log only (project closed) |
| Beta…Eta | CRM + hourly PBX report |
| Theta, Iota, Kappa | surveys, operator KPIs |

### Running the demo

```bash
pip install -r requirements.txt
```

**etl/ — daily reporting.** Demo mode writes to Excel files in
`data/demo_output/` instead of Google Sheets and never calls the CRM.

```bash
cp .env.example .env      # set DEMO=1 in .env
python etl/generate_etl_demo.py
```

Then open `etl/` in Jupyter or DataSpell and run the cells of
`alpha_registry.ipynb`, `omega_registry.ipynb` and
`monitoring.ipynb` (cells 1–3) in order. The result is the workbooks
`Alpha Август 2026.xlsx`, `Omega Август 2026.xlsx` and
`monitoring.xlsx` in `data/demo_output/`.

The demo exports cover 15–17 Aug 2026: Saturday, Sunday, Monday.
Dates and the random seed are fixed, so the numbers are the same on
every run. The output of `alpha_registry.ipynb` (messages are in
Russian):

```
Буферный день 15.08.2026 — 169 строк АТС,
  117 строк CRM. Грузиться НЕ будет.
16.08.26: CRM пустой — исходящие приму за 0
Посчитано дней: 2
  16.08.26: все 76, входящие 0, пропущенные 76, исходящие 0
  17.08.26: все 209, входящие 137, пропущенные 56, исходящие 16
```

The buffer day (15 Aug) is shown but not loaded. On Sunday Alpha's
operators are off: the CRM is empty, but the PBX still sees missed
calls, and the report for that day is built anyway. All five checks
pass for each day.

What the other `etl/` files do in demo mode:

- `crm_reports.py`, `kpi_daily.py`, `operators_report.ipynb` get
  everything from live CRM requests; in demo mode they say so and
  stop;
- cell 4 of `monitoring.ipynb` (month total) and
  `reconciliation.ipynb` read calculated formulas back from the
  sheets, while the demo Excel stores formulas as text, so they stop
  with an explanation;
- `sheets_analytics.ipynb` works on top of the demo workbooks if
  cell 1 sets `REPORT_DATE = date(2026, 8, 17)`;
- `kpi_monthly.py` and `client_report.py` read sheets that nobody
  fills in demo mode, so they have nothing to show.

**The SQL part — database and anomaly search.**

```bash
python generate_demo.py      # demo exports into data/sql/
python load_daily.py         # load them into the database
python analytics.py          # anomalies and worst hours
```

Charts on the same data are in `demo_analysis.ipynb` at the root:
hourly load, share of missed calls, anomalous days, operators. The
conclusions under the charts are not typed by hand — the code prints
them from the data in the database.

**Tests.** `pytest` from the root checks the rules the reports rely
on: minute rounding (including Alpha's "up to 5 seconds is 0
minutes"), the KPI rate table, parsing "1 036" numbers from the PBX,
and picking the buffer day — in etl/ and in the SQL part.

### Engineering decisions

#### Buffer day

The CRM drops the first record of the requested period — exactly
one, whatever the period length. With a one-day export that is the
first call of the day, and it would be lost every day.

So the export covers three days, and the earliest day is a buffer:
it is shown on screen but not loaded. The first call of the buffer
day is lost, and the working days arrive complete (`MultiDay.plan`
in `etl_core.py`).

Three days, not two: on Sundays and holidays Alpha has no calls in
the CRM. If the buffer day is empty, the first record of the period
becomes the first call of a working day — and that is the one lost.
`alpha_registry.ipynb` detects an empty buffer and warns about it.

In `monitoring.ipynb` the report date is determined once across all
files, not per project: otherwise a project with no calls that day
would take yesterday's date, and yesterday's outgoing calls would
land in today's report.

The SQL part uses the same rule (`drop_buffer` in `load_daily.py`),
but switches it off for monthly exports: there a single record of
the 1st is lost, and cutting a whole day for it makes no sense. The
marker is the word `month` in the file name.

#### Checks before writing

The notebooks reconcile their aggregates against the source and
write nothing if any check fails (`Validator` and `assert`):

- Alpha: the per-operator total equals accepted inbound calls; the
  hourly totals equal the row counts of the PBX log and the CRM;
- Monitoring: the hourly grid against the "Итого" (total) row of the
  PBX report itself; the month total — the SUMIF formula block
  against the hourly grid, with broken formulas and tabs with a
  mistyped date reported explicitly.

Before writing, `kpi_daily.py` compares an independent total from
the CRM main screen with the sum going into the sheet and explains
every difference: Lambda positions, positions missing from the
sheet, calls without an operator.

`reconciliation.ipynb` compares the monthly CRM export with the daily
sheets. The key is call ID plus phone number, not the ID alone: a
transferred call produces two CRM rows with the same ID. Missing
calls are written back only after the write plan has been shown.

#### Protection against duplicate positions in KPI

An operator's row on the KPI sheet is found by the position number
in column A, only within the working list and only for positions
1…`MAX_WRITE_POS`. The "Подмена" (substitutes) and "Выбывшие" (left)
sections are never touched.

If a position number appears twice in the working list, the script
writes it nowhere: it cannot know which row is right, and payroll is
no place for guessing. It writes all other positions and says which
row to fix.

#### Idempotent loading

The same file can be loaded any number of times with the same
result. In practice reruns happen all the time: a file arrived
incomplete, or a parsing bug was found.

- SQL part: rows for the file's dates are deleted before insert, in
  one transaction per file (`engine.begin()`): either everything is
  loaded or nothing, and a failure on one file does not roll back the
  others. The `load_log` table records which file brought how many
  rows and when.
- etl/: the sheet is looked up by date in both name formats
  (`23.07.26` and `23.07.2026`) and cleared before writing, so a
  rerun overwrites the day instead of creating a duplicate. In
  `monitoring.ipynb` only the A:G grid is cleared; the I:O formula
  block with manual edits is left alone.

#### Small things that used to break reports

- PBX numbers from a thousand up arrive as "1 036", sometimes with a
  non-breaking space. Plain `to_numeric` returns NaN for them, and
  `fillna(0)` silently turns a thousand calls into zero
  (`ExcelReader._to_num`).
- The report date comes from the data, not from the system clock:
  reports are closed one after another, and the 23rd is processed
  when the calendar already says the 25th.
- If the PBX sends a call log instead of the hourly report, the
  script stops and shows what is inside the file: silently folding
  someone else's file is more dangerous than failing.
- CRM columns are read by name, not by position: a new field on the
  left will not shift the data into the neighbouring column.

### An anomaly must be rare

The first version found a dozen anomalies in two weeks. Those are not
anomalies but ordinary variation — and people stop reading such a
report.

Now a day is listed only if it passes all three checks:

1. **Deviation of at least three sigmas.** The baseline uses the
   median and MAD rather than the mean and standard deviation: a
   single outlier inflates the latter, and after an anomalous day the
   baseline rises so much that the next anomalies go unnoticed.
2. **Deviation of at least a third of the baseline.** Otherwise a
   jump from 2 to 8 calls looks like a disaster for a small project.
3. **The baseline is built from at least eight similar days.** Four
   points are not enough to estimate variation.

Two more rules on top:

- **Weekdays and weekends are compared separately.** Against a
  common baseline every Sunday would look like a failure.
- **Consecutive days are merged into one event.** Three days of
  decline are one problem, not three rows.

The SQL demo generator plants exactly one failure — three days in a
row for project `beta`. The analytics finds it and nothing else.
Sample output (dates and percentages depend on the run date: the
demo period ends yesterday):

```
Проект  Когда                Что случилось
beta    15.08 — 17.08.2026   дозвонились намного реже обычного

В этот день  Обычно  Насколько сильно
43%          82%     3 дня подряд
```

("fewer callers got through than usual: 43% on that day vs. 82%
usually, 3 days in a row".) Project `delta`, with eight calls a day,
is filtered out before the analysis: at such numbers any movement is
within chance, and it is more honest to draw no conclusions than
wrong ones.

### Window functions

`queries.sql` contains annotated examples: operator rank within a
project, day-over-day comparison with `LAG`, a rolling baseline with
a `ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING` frame, a running total,
finding gaps in the loaded data.

Two easy-to-miss points are explained in the comments:

- **The current day is excluded from the rolling baseline.**
  Otherwise a spike becomes part of its own baseline and dilutes
  itself.
- **You cannot filter on a window function result in `WHERE`** — it
  is evaluated later. A CTE is needed.

### Ready to move to a server

The database is accessed through SQLAlchemy, and the connection string
is a single setting in `config.py`. But moving to PostgreSQL or MS SQL
takes more than that: `id INTEGER PRIMARY KEY` in `schema.sql` relies
on SQLite autoincrement, and `queries.sql` uses SQLite functions
(`printf`, `julianday`). Those places will need rewriting.

### Layout

```
config.py            SQL part settings, secrets from .env
generate_demo.py     demo exports for the SQL part
load_daily.py        loading into the database
analytics.py         anomalous days and worst hours
schema.sql views.sql tables and views
queries.sql          window function walkthroughs
demo_analysis.ipynb  charts on the SQL part demo data
tests/test_rules.py  tests of the rules (pytest)
etl/
  etl_core.py        shared module: paths, .env, Excel
                     reading, dates, Google Sheets,
                     checks, demo mode
  generate_etl_demo.py  demo CRM and PBX exports
  crm_reports.py     downloads exports from the CRM
  alpha_registry.ipynb  Alpha: CRM + PBX call log
  omega_registry.ipynb  Omega: CRM only
  monitoring.ipynb   Beta…Eta: hourly PBX report
                     + outgoing calls from the CRM
  reconciliation.ipynb  checks against the monthly export
  operators_report.ipynb operators report from the CRM
  kpi_daily.py       survey operators' KPIs
  kpi_monthly.py     monthly KPI totals for payroll
  client_report.py   report for client Gamma
  sheets_analytics.ipynb analytics on top of the sheets
etl-basics/          my first learning ETL project
data/                exports and results, never
                     committed
```

Secrets live only in `.env` (template: `.env.example`); `.env`,
`credentials.json`, exports and the database are never committed.

### Next steps

- A schedule instead of manual runs
- Moving to a server database
- A dashboard on top of the views
