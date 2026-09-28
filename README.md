# ETL и аналитика контакт-центра

[Русский](#русский) · [English](#english)

---

## Русский

Я работаю специалистом по отчётности в аутсорсинговом контакт-центре.
Раньше отчётность собиралась вручную: семь файлов, полдня каждый день.
Я её автоматизировал. Здесь лежит обезличенная копия моих рабочих
скриптов.

Проекты-заказчики названы греческими буквами, данных заказчиков в
репозитории нет. Вместо них я сделал генераторы демо-данных в тех же
форматах, поэтому всё запускается без доступа к CRM и Google.

### Зачем это

Раньше я скачивал выгрузки из CRM по каждому проекту отдельно:
«Отчёты», компания, даты, «создать», скачать «Детализацию». Потом
переносил цифры в Google Sheets и сверял их вручную. KPI операторов
снимал с экрана CRM: дата, оператор, фильтр результата и число из
строки «Показаны 1-20 из N записи». Половина этого времени уходила
на перенос цифр.

Теперь это делают скрипты:

- `crm_reports.py` скачивает выгрузки всех проектов за один запуск и
  сохраняет их под теми именами, которые ждут ноутбуки.
- Ноутбуки считают сводки, сверяют их с исходными файлами и пишут
  дневные листы. Если сверка не сошлась, запись останавливается.
- `kpi_daily.py` сам снимает счётчики CRM и пишет их в таблицу KPI.
- `reconciliation.ipynb` находит звонки, которые потерялись между
  месячной выгрузкой и дневными листами, и после подтверждения
  дописывает их.

Вручную я делаю только то, для чего у скрипта нет доступа к данным.

### Как устроено

В репозитории две части. В `etl/` лежит рабочий код ежедневной
отчётности в Google Sheets. В корне лежит SQL-часть: похожие
выгрузки загружаются в базу, и по ней я ищу аномальные дни.

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

**etl/.** В демо-режиме запись идёт в Excel-файлы в
`data/demo_output/`, в Google Sheets ничего не пишется, в CRM
скрипты не ходят.

```bash
cp .env.example .env      # в .env поставить DEMO=1
python etl/generate_etl_demo.py
```

Потом откройте папку `etl/` в Jupyter или DataSpell и выполните по
порядку ячейки `alpha_registry.ipynb`, `omega_registry.ipynb`,
`monitoring.ipynb` (ячейки 1–3) и `sheets_analytics.ipynb`. Результат
появится в `data/demo_output/`: `Alpha Август 2026.xlsx`,
`Omega Август 2026.xlsx`, `monitoring.xlsx` и `analytics.xlsx`.

Демо-выгрузки сделаны за 15–17.08.2026: суббота, воскресенье и
понедельник. Даты и зерно генератора фиксированные, поэтому цифры
при каждом запуске одинаковые. Вывод `alpha_registry.ipynb`:

```
Буферный день 15.08.2026 — 169 строк АТС,
  117 строк CRM. Грузиться НЕ будет.
16.08.26: CRM пустой — исходящие приму за 0
Посчитано дней: 2
  16.08.26: все 76, входящие 0, пропущенные 76, исходящие 0
  17.08.26: все 209, входящие 137, пропущенные 56, исходящие 16
```

Суббота буферная и не загружается. В воскресенье операторы Alpha не
работают: CRM пустой, но АТС видит пропущенные звонки, и отчёт за
день всё равно строится. Все пять сверок по каждому дню сходятся.

Остальные файлы `etl/` в демо-режиме:

- `crm_reports.py`, `kpi_daily.py` и `operators_report.ipynb` берут
  данные из CRM. В демо они пишут об этом и останавливаются.
- Ячейка 4 в `monitoring.ipynb` (итог месяца) и
  `reconciliation.ipynb` читают из таблиц посчитанные формулы. В
  демо-Excel формулы хранятся текстом, поэтому они останавливаются
  с объяснением.
- `kpi_monthly.py` и `client_report.py` читают листы, которые в демо
  никто не заполняет, поэтому показывать им нечего.

**SQL-часть.**

```bash
python generate_demo.py      # демо-выгрузки в data/sql/
python load_daily.py         # загрузка в базу
python analytics.py          # аномалии и худшие часы
```

Графики на этих данных лежат в `demo_analysis.ipynb` в корне:
нагрузка по часам, доля пропущенных, аномальные дни и операторы.
Выводы под графиками печатает код по данным из базы.

**Тесты.** `pytest` из корня проверяет правила, на которых держатся
отчёты: округление минут (и правило Alpha: звонок до 5 секунд
включительно стоит 0 минут), тарифную сетку KPI, разбор чисел «1 036» из АТС и выбор
буферного дня в `etl/` и в SQL-части.

### Что пришлось решать

#### Буферный день

Я заметил, что CRM теряет первую запись запрошенного периода. Ровно
одну, какой бы длины ни был период. Если качать выгрузку за один
день, каждый день пропадал бы первый звонок.

Поэтому я качаю выгрузку за три дня. Самый ранний день буферный:
скрипт показывает его на экране, но не загружает. Пропадает первый
звонок буферного дня, а рабочие дни приходят целыми (`MultiDay.plan`
в `etl_core.py`).

Двух дней мало. По воскресеньям и праздникам у Alpha в CRM нет
звонков. Если буферный день пустой, первой записью периода
становится первый звонок рабочего дня, и пропадает именно он.
Поэтому дней три, а `alpha_registry.ipynb` предупреждает, если в
буферном дне CRM пуст.

В `monitoring.ipynb` рабочая дата определяется один раз по всем
файлам. Если бы каждый проект брал свою дату, проект без звонков в
этот день взял бы вчерашнюю, и его вчерашние исходящие попали бы в
сегодняшний отчёт.

В SQL-части правило то же (`drop_buffer` в `load_daily.py`). Для
месячной выгрузки оно отключено: там теряется одна запись за первое
число, и отрезать ради неё целые сутки нет смысла. Месячную выгрузку
скрипт узнаёт по слову `month` в имени файла.

#### Сверки перед записью

Перед записью ноутбуки сверяют свои суммы с исходными файлами. Если
хоть одна сверка не сошлась, в таблицу ничего не пишется
(`Validator` и `assert`):

- Alpha: сумма по операторам равна принятым входящим, почасовые
  суммы равны числу строк в реестре АТС и в CRM.
- Monitoring: почасовая сетка сверяется со строкой «Итого» из
  отчёта АТС. Для итога месяца блок формул СУММЕСЛИ сверяется с
  почасовой сеткой, а сломанные формулы и вкладки с опечаткой в
  дате выводятся списком.

`kpi_daily.py` перед записью сравнивает итог с главного экрана CRM
(это отдельный запрос) с суммой того, что пойдёт в таблицу, и
объясняет каждую разницу: позиции Lambda, позиции, которых нет в
таблице, звонки без оператора.

`reconciliation.ipynb` сверяет месячную выгрузку CRM с дневными
листами. Звонки сравниваются по ID и телефону вместе, потому что при
переводе между операторами CRM отдаёт две строки с одним ID.
Пропавшие звонки дописываются только после того, как скрипт покажет
план записи.

#### Защита от дублей позиций в KPI

Строку оператора на листе KPI скрипт ищет по номеру позиции в
колонке A. Он смотрит только рабочий список и только позиции
1…`MAX_WRITE_POS`, разделы «Подмена» и «Выбывшие» не трогает.

Если номер позиции встретился в рабочем списке дважды, скрипт не
пишет его ни в одну строку. Он не может знать, какая из двух строк
правильная. По этим цифрам считается зарплата, поэтому такую позицию
он пропускает. Остальные позиции он записывает и сообщает, какую
строку исправить.

#### Идемпотентная загрузка

Один и тот же файл можно загрузить несколько раз, результат будет
тот же. Перезапускать приходится часто: то файл пришёл неполный, то
я нашёл ошибку в разборе.

- SQL-часть: перед вставкой строки за эти даты удаляются. Всё идёт
  в одной транзакции на файл (`engine.begin()`): загружается либо
  весь файл, либо ничего, и сбой на одном файле не отменяет уже
  загруженные. В таблице `load_log` видно, какой файл, когда и
  сколько строк принёс.
- `etl/`: лист ищется по дате в обоих форматах имени (`23.07.26` и
  `23.07.2026`) и очищается перед записью. Перезапуск переписывает
  день, второй лист за ту же дату не появляется. В `monitoring.ipynb`
  очищается только сетка A:G, блок формул I:O с ручными правками
  остаётся.

#### На чём я спотыкался

- Числа из АТС от тысячи приходят как «1 036», иногда с неразрывным
  пробелом. Обычный `to_numeric` превращает их в NaN, а после
  `fillna(0)` тысяча звонков незаметно становится нулём. Для этого
  есть `ExcelReader._to_num`.
- Дату отчёта скрипт берёт из колонки со временем звонка. Я закрываю
  отчёты по очереди и 23-е число могу делать, когда на календаре уже
  25-е.
- Если АТС прислала реестр звонков вместо почасового отчёта, скрипт
  останавливается и показывает, что внутри файла. Если свернуть такой
  файл по часам молча, чужие цифры попадут в таблицу, и этого никто
  не заметит.
- Колонки CRM скрипт ищет по имени. Если CRM добавит поле слева,
  данные не съедут в соседний столбец.

### Поиск аномалий

Первая версия находила десяток аномалий за две недели. На деле это
был обычный разброс, и такой отчёт перестают читать. Пришлось
ужесточить правила. Теперь день попадает в список, только если
проходит все три проверки:

1. **Отклонение не меньше трёх сигм.** Норму я считаю по медиане и
   MAD. Среднее и стандартное отклонение сильно сдвигает один выброс:
   после аномального дня норма задирается, и следующие аномалии уже
   не находятся.
2. **Отклонение не меньше трети от нормы.** Иначе у мелкого проекта
   скачок с 2 до 8 звонков выглядит катастрофой.
3. **Норма посчитана хотя бы по восьми похожим дням.** По четырём
   точкам разброс не посчитать.

И ещё два правила:

- Будни и выходные сравниваются отдельно. С общей нормой каждое
  воскресенье выглядело бы провалом.
- Дни подряд склеиваются в одно событие: три дня падения дают одну
  строку в отчёте.

В генератор SQL-части заложен один сбой: три дня подряд у проекта
`beta`. Аналитика находит его и больше ничего. Вывод `analytics.py`
(даты демо фиксированные, сентябрь 2026):

```
Проект  Когда               Что случилось
beta    15.09 — 17.09.2026  дозвонились намного реже обычного

В этот день  Обычно  Насколько сильно
42%          82%     3 дня подряд
```

Проект `delta` с восемью звонками в день отсеивается ещё до анализа.
На таких числах любое движение укладывается в случайность, поэтому
выводов по нему я не делаю.

### Оконные функции

В `queries.sql` лежат примеры с разбором: ранг оператора внутри
проекта, сравнение с предыдущим днём через `LAG`, скользящая норма с
рамкой `ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING`, нарастающий итог,
поиск дырок в загрузке.

В комментариях разобраны два места, где легко ошибиться:

- Текущий день не входит в скользящую норму. Иначе всплеск попадает
  в собственную норму и размывает сам себя.
- По результату оконной функции нельзя фильтровать в `WHERE`, она
  считается позже. Нужен CTE.

### Если переезжать на сервер

С базой я работаю через SQLAlchemy, строка подключения задаётся одной
настройкой в `config.py`. Для PostgreSQL или MS SQL этого мало: в
`schema.sql` поле `id INTEGER PRIMARY KEY` рассчитано на
автоинкремент SQLite, а в `queries.sql` есть функции SQLite
(`printf`, `julianday`). Эти места придётся переписать.

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
etl-basics/          мой первый ETL
data/                выгрузки и результаты, в git не
                     попадают
```

Секреты хранятся только в `.env`, образец лежит в `.env.example`.
`.env`, `credentials.json`, выгрузки и база в git не попадают.

### Что дальше

- Запуск по расписанию вместо ручного
- Переезд на серверную СУБД
- Дашборд поверх витрин

---

## English

I work as a reporting specialist at an outsourcing contact center.
Reporting used to be manual: seven files, half a day, every day. I
automated it. This repository is an anonymized copy of my working
scripts.

Client projects are named after Greek letters, and there is no
client data here. Instead I wrote demo data generators that produce
files in the same formats, so everything runs without access to the
CRM or Google.

### Why

I used to download CRM exports for each project separately:
"Reports", client, dates, "create", download the call detail export.
Then I copied the numbers into Google Sheets and checked them by
hand. I read operator KPIs off the CRM screen: date, operator, result
filter and the number from "Showing 1-20 of N records". Half of that
time went into copying numbers.

Now scripts do it:

- `crm_reports.py` downloads the exports of all projects in one run
  and saves them under the names the notebooks expect.
- The notebooks build the summaries, check them against the source
  files and write the daily sheets. If a check fails, nothing is
  written.
- `kpi_daily.py` reads the CRM counters itself and writes them to
  the KPI spreadsheet.
- `reconciliation.ipynb` finds calls lost between the monthly export
  and the daily sheets and writes them back after confirmation.

I only do by hand what the scripts have no access to.

### How it works

The repository has two parts. `etl/` holds the working code for daily
reporting into Google Sheets. The root holds the SQL part: similar
exports are loaded into a database, and I use it to find anomalous
days.

```
     CRM (web)                 PBX (phone system)
          │ crm_reports.py        │ .xls files
          ▼                       ▼
   data/*_crm.xlsx         data/*_pbx.xls
          └───────────┬───────────┘
                      ▼
    etl_core: reading, buffer day,
              dates, checks
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

**etl/.** In demo mode the scripts write to Excel files in
`data/demo_output/`, write nothing to Google Sheets and never call
the CRM.

```bash
cp .env.example .env      # set DEMO=1 in .env
python etl/generate_etl_demo.py
```

Then open `etl/` in Jupyter or DataSpell and run the cells of
`alpha_registry.ipynb`, `omega_registry.ipynb`, `monitoring.ipynb`
(cells 1–3) and `sheets_analytics.ipynb` in order. The results land
in `data/demo_output/`: `Alpha Август 2026.xlsx`,
`Omega Август 2026.xlsx`, `monitoring.xlsx` and `analytics.xlsx`.

The demo exports cover 15–17 Aug 2026: Saturday, Sunday and Monday.
The dates and the generator's seed are fixed, so the numbers are the
same on every run. Output of `alpha_registry.ipynb` (in Russian):

```
Буферный день 15.08.2026 — 169 строк АТС,
  117 строк CRM. Грузиться НЕ будет.
16.08.26: CRM пустой — исходящие приму за 0
Посчитано дней: 2
  16.08.26: все 76, входящие 0, пропущенные 76, исходящие 0
  17.08.26: все 209, входящие 137, пропущенные 56, исходящие 16
```

Saturday is the buffer day and is not loaded. On Sunday Alpha's
operators are off: the CRM is empty, but the PBX still sees missed
calls, so the report for that day is built anyway. All five checks
pass for each day.

The other `etl/` files in demo mode:

- `crm_reports.py`, `kpi_daily.py` and `operators_report.ipynb` get
  their data from the CRM. In demo mode they say so and stop.
- Cell 4 of `monitoring.ipynb` (month total) and
  `reconciliation.ipynb` read calculated formulas from the sheets.
  The demo Excel stores formulas as text, so they stop with an
  explanation.
- `kpi_monthly.py` and `client_report.py` read sheets that nobody
  fills in demo mode, so they have nothing to show.

**The SQL part.**

```bash
python generate_demo.py      # demo exports into data/sql/
python load_daily.py         # load into the database
python analytics.py          # anomalies and worst hours
```

Charts on this data are in `demo_analysis.ipynb` at the root: hourly
load, share of missed calls, anomalous days and operators. The code
prints the conclusions under the charts from the data in the
database.

**Tests.** `pytest` from the root checks the rules the reports rely
on: minute rounding (including Alpha's rule: a call of up to 5
seconds counts as 0 minutes), the KPI rate table, parsing "1 036" numbers from the PBX,
and picking the buffer day in `etl/` and in the SQL part.

### Problems I had to solve

#### Buffer day

I noticed that the CRM drops the first record of the requested
period. Exactly one, whatever the period length. With one-day exports
the first call would be lost every day.

So I download three days. The earliest day is a buffer: the script
shows it on screen but does not load it. The first call of the
buffer day is lost, and the working days arrive complete
(`MultiDay.plan` in `etl_core.py`).

Two days are not enough. On Sundays and holidays Alpha has no calls
in the CRM. If the buffer day is empty, the first record of the
period is the first call of a working day, and that call is lost. So
I use three days, and `alpha_registry.ipynb` warns when the CRM is
empty on the buffer day.

In `monitoring.ipynb` the report date is determined once across all
files. If each project took its own date, a project with no calls
that day would take yesterday's date, and its outgoing calls from
yesterday would end up in today's report.

The SQL part uses the same rule (`drop_buffer` in `load_daily.py`).
It is switched off for monthly exports: there one record of the 1st
is lost, and cutting a whole day for it makes no sense. The script
recognizes a monthly export by the word `month` in the file name.

#### Checks before writing

Before writing, the notebooks check their totals against the source
files. If any check fails, nothing is written (`Validator` and
`assert`):

- Alpha: the per-operator total equals accepted inbound calls, and
  the hourly totals equal the row counts in the PBX log and the CRM.
- Monitoring: the hourly grid is checked against the "Итого" (total)
  row of the PBX report. For the month total, the SUMIF formula block
  is checked against the hourly grid, and broken formulas and tabs
  with a mistyped date are listed.

Before writing, `kpi_daily.py` compares the total from the CRM main
screen (a separate request) with the sum going into the sheet, and
explains every difference: Lambda positions, positions missing from
the sheet, calls without an operator.

`reconciliation.ipynb` compares the monthly CRM export with the daily
sheets. Calls are matched by ID and phone number together, because a
call transferred between operators produces two CRM rows with the
same ID. Missing calls are written back only after the script shows
the write plan.

#### Duplicate positions in KPI

The script finds an operator's row on the KPI sheet by the position
number in column A. It only looks at the working list and positions
1…`MAX_WRITE_POS`, and never touches the "Подмена" (substitutes) and
"Выбывшие" (left) sections.

If a position number appears twice in the working list, the script
writes it to neither row. It cannot know which of the two rows is
right. These numbers are used for payroll, so it skips such a
position. It writes all other positions and says which row to fix.

#### Idempotent loading

The same file can be loaded several times with the same result. I
rerun loads often: a file arrived incomplete, or I found a parsing
bug.

- SQL part: rows for the file's dates are deleted before insert. It
  all runs in one transaction per file (`engine.begin()`): either the
  whole file is loaded or nothing, and a failure on one file does not
  roll back the others. The `load_log` table shows which file brought
  how many rows and when.
- `etl/`: the sheet is looked up by date in both name formats
  (`23.07.26` and `23.07.2026`) and cleared before writing. A rerun
  overwrites the day, and no second sheet for the same date appears.
  In `monitoring.ipynb` only the A:G grid is cleared; the I:O formula
  block with manual edits stays.

#### Things I tripped over

- PBX numbers from a thousand up arrive as "1 036", sometimes with a
  non-breaking space. Plain `to_numeric` turns them into NaN, and
  after `fillna(0)` a thousand calls quietly becomes zero.
  `ExcelReader._to_num` handles this.
- The script takes the report date from the call time column. I
  close reports one after another and may work on the 23rd when the
  calendar already says the 25th.
- If the PBX sends a call log instead of the hourly report, the
  script stops and shows what is inside the file. If such a file were
  silently folded by hour, someone else's numbers would go into the
  sheet unnoticed.
- The script finds CRM columns by name. If the CRM adds a field on
  the left, the data does not shift into the neighbouring column.

### Anomaly search

The first version found a dozen anomalies in two weeks. In fact it
was ordinary variation, and people stop reading such a report. I had
to make the rules stricter. Now a day is listed only if it passes all
three checks:

1. **Deviation of at least three sigmas.** I compute the baseline
   from the median and MAD. A single outlier shifts the mean and
   standard deviation a lot: after an anomalous day the baseline goes
   up, and the next anomalies are no longer found.
2. **Deviation of at least a third of the baseline.** Otherwise a
   jump from 2 to 8 calls looks like a disaster for a small project.
3. **The baseline is built from at least eight similar days.** Four
   points are not enough to estimate variation.

Two more rules:

- Weekdays and weekends are compared separately. Against a common
  baseline every Sunday would look like a failure.
- Consecutive days are merged into one event: three days of decline
  give one row in the report.

The SQL demo generator has one planted failure: three days in a row
for project `beta`. The analytics finds it and nothing else. Output
of `analytics.py` (demo dates are fixed, September 2026):

```
Проект  Когда               Что случилось
beta    15.09 — 17.09.2026  дозвонились намного реже обычного

В этот день  Обычно  Насколько сильно
42%          82%     3 дня подряд
```

That is: fewer callers got through, 42% on those days against 82%
usually, three days in a row. Project `delta`, with eight calls a
day, is filtered out before the analysis. At such numbers any
movement is within chance, so I draw no conclusions for it.

### Window functions

`queries.sql` contains annotated examples: operator rank within a
project, day-over-day comparison with `LAG`, a rolling baseline with
a `ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING` frame, a running total,
finding gaps in the loaded data.

The comments cover two places where it is easy to make a mistake:

- The current day is not part of the rolling baseline. Otherwise a
  spike becomes part of its own baseline and dilutes itself.
- You cannot filter on a window function result in `WHERE`, because
  it is evaluated later. You need a CTE.

### Moving to a server

I work with the database through SQLAlchemy, and the connection
string is one setting in `config.py`. For PostgreSQL or MS SQL that
is not enough: `id INTEGER PRIMARY KEY` in `schema.sql` relies on
SQLite autoincrement, and `queries.sql` uses SQLite functions
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
etl-basics/          my first ETL project
data/                exports and results, never
                     committed
```

Secrets live only in `.env`, the template is `.env.example`. `.env`,
`credentials.json`, exports and the database are never committed.

### Next steps

- A schedule instead of manual runs
- Moving to a server database
- A dashboard on top of the views
