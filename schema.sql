-- Схема витрины звонков.
-- Типы заданы явно: телефон текстом (номера не влезают в INTEGER
-- и теряют ведущие нули), даты строкой ISO — так сортировка
-- совпадает с хронологией на любой СУБД.

CREATE TABLE IF NOT EXISTS calls (
    id          INTEGER PRIMARY KEY,
    project     TEXT    NOT NULL,
    call_id     TEXT,               -- не уникален: при переводе звонка
                                    -- между операторами появляются две
                                    -- строки с одним id
    direction   TEXT,               -- Входящий / Исходящий
    phone       TEXT,
    started_at  TEXT,
    ended_at    TEXT,
    talk_sec    INTEGER,
    hold_sec    INTEGER,
    bill_min    INTEGER,            -- минуты с округлением вверх
    operator    TEXT,
    topic       TEXT,
    call_date   TEXT    NOT NULL,
    call_hour   INTEGER,
    loaded_at   TEXT
);

CREATE INDEX IF NOT EXISTS ix_calls_project_date ON calls (project, call_date);
CREATE INDEX IF NOT EXISTS ix_calls_operator     ON calls (operator);

-- Почасовая сводка телефонии: сколько пришло и сколько не дождались.
CREATE TABLE IF NOT EXISTS hourly (
    id          INTEGER PRIMARY KEY,
    project     TEXT    NOT NULL,
    call_date   TEXT    NOT NULL,
    call_hour   INTEGER NOT NULL,
    answered    INTEGER,
    lost        INTEGER,
    total       INTEGER,
    loaded_at   TEXT
);

CREATE INDEX IF NOT EXISTS ix_hourly_project_date ON hourly (project, call_date);

-- Журнал загрузок: что, когда и сколько строк заехало.
-- Без него через месяц не вспомнить, почему в базе дырка.
CREATE TABLE IF NOT EXISTS load_log (
    id          INTEGER PRIMARY KEY,
    loaded_at   TEXT,
    project     TEXT,
    source      TEXT,
    target      TEXT,
    days_file   TEXT,
    buffer_day  TEXT,
    rows_kept   INTEGER,
    rows_wiped  INTEGER
);
