-- Витрины. Отчёты пишутся поверх них, а не поверх сырых таблиц:
-- при переезде на другую СУБД переписать надо будет эти несколько
-- представлений, а не каждый запрос.

DROP VIEW IF EXISTS v_daily;
CREATE VIEW v_daily AS
SELECT project,
       call_date,
       COUNT(*)                                                  AS calls,
       SUM(CASE WHEN direction = 'Входящий'  THEN 1 ELSE 0 END)  AS incoming,
       SUM(CASE WHEN direction = 'Исходящий' THEN 1 ELSE 0 END)  AS outgoing,
       COUNT(DISTINCT operator)                                  AS operators,
       SUM(bill_min)                                             AS bill_min,
       ROUND(AVG(talk_sec), 1)                                   AS avg_talk_sec
FROM calls
GROUP BY project, call_date;

DROP VIEW IF EXISTS v_operator;
CREATE VIEW v_operator AS
SELECT project,
       operator,
       COUNT(DISTINCT call_date)                                 AS work_days,
       COUNT(*)                                                  AS calls,
       ROUND(1.0 * COUNT(*) / COUNT(DISTINCT call_date), 1)      AS calls_per_day,
       ROUND(AVG(talk_sec), 1)                                   AS avg_talk_sec,
       SUM(bill_min)                                             AS bill_min
FROM calls
WHERE operator IS NOT NULL AND operator <> ''
GROUP BY project, operator;

DROP VIEW IF EXISTS v_hourly;
CREATE VIEW v_hourly AS
SELECT project,
       call_hour,
       SUM(answered)                                             AS answered,
       SUM(lost)                                                 AS lost,
       SUM(total)                                                AS total,
       COUNT(DISTINCT call_date)                                 AS days,
       ROUND(1.0 * SUM(lost) / NULLIF(SUM(total), 0), 3)         AS lost_share
FROM hourly
GROUP BY project, call_hour;

-- Дневная картина по телефонии: сколько пришло, сколько не дождались.
DROP VIEW IF EXISTS v_service;
CREATE VIEW v_service AS
SELECT project,
       call_date,
       SUM(answered)                                             AS answered,
       SUM(lost)                                                 AS lost,
       SUM(total)                                                AS total,
       ROUND(1.0 * SUM(lost) / NULLIF(SUM(total), 0), 3)         AS lost_share
FROM hourly
GROUP BY project, call_date;
