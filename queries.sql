-- ============================================================
--  Запросы к базе. Проверены на демонстрационных данных.
-- ============================================================

-- ------------------------------------------------------------
-- 1. Что вообще лежит в базе
-- ------------------------------------------------------------
SELECT project,
       COUNT(*)                  AS calls,
       COUNT(DISTINCT call_date) AS days,
       MIN(call_date)            AS first_day,
       MAX(call_date)            AS last_day
FROM calls
GROUP BY project
ORDER BY calls DESC;


-- ------------------------------------------------------------
-- 2. Ранг оператора внутри своего проекта
--
-- PARTITION BY project означает: нумеровать заново для каждого
-- проекта, а не сквозным списком. SUM без ORDER BY внутри OVER
-- даёт итог по всей группе — одно и то же число во всех строках,
-- именно это и нужно для доли.
-- ------------------------------------------------------------
SELECT project,
       operator,
       calls,
       RANK() OVER (PARTITION BY project ORDER BY calls DESC)   AS place,
       ROUND(100.0 * calls / SUM(calls) OVER (PARTITION BY project), 1)
                                                                AS pct_of_project,
       MAX(calls) OVER (PARTITION BY project) - calls           AS behind_top
FROM v_operator
ORDER BY project, place;


-- ------------------------------------------------------------
-- 3. День к дню: LAG
--
-- LAG берёт значение из предыдущей строки окна. Второй аргумент —
-- на сколько строк назад, третий — чем заменить пустоту в самой
-- первой строке.
-- ------------------------------------------------------------
SELECT call_date,
       calls,
       LAG(calls) OVER (PARTITION BY project ORDER BY call_date) AS prev_day,
       calls - LAG(calls) OVER (PARTITION BY project ORDER BY call_date)
                                                                 AS diff
FROM v_daily
WHERE project = 'alpha'
ORDER BY call_date;


-- ------------------------------------------------------------
-- 4. Скользящая норма и отклонение
--
-- ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING — шесть предыдущих дней
-- БЕЗ текущего. Исключать текущий день обязательно: иначе всплеск
-- попадает в собственную норму и сам себя размывает.
-- ------------------------------------------------------------
SELECT call_date,
       calls,
       ROUND(AVG(calls) OVER (
           PARTITION BY project ORDER BY call_date
           ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING), 0)         AS norm_7d,
       ROUND(100.0 * calls / NULLIF(AVG(calls) OVER (
           PARTITION BY project ORDER BY call_date
           ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING), 0) - 100, 1)
                                                                 AS deviation_pct
FROM v_daily
WHERE project = 'alpha'
ORDER BY call_date;


-- ------------------------------------------------------------
-- 5. Только отклонившиеся дни
--
-- Здесь важная ловушка: оконные функции считаются ПОСЛЕ WHERE,
-- поэтому написать WHERE deviation_pct > 20 нельзя — база ещё не
-- знает такой колонки. Нужен CTE: сначала считаем окно, потом
-- фильтруем результат.
-- ------------------------------------------------------------
WITH d AS (
    SELECT project, call_date, calls,
           AVG(calls) OVER (
               PARTITION BY project ORDER BY call_date
               ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING) AS norm
    FROM v_daily
)
SELECT project, call_date, calls,
       ROUND(norm, 0)                       AS norm_7d,
       ROUND(100.0 * calls / norm - 100, 1) AS deviation_pct
FROM d
WHERE norm IS NOT NULL
  AND ABS(100.0 * calls / norm - 100) > 25
ORDER BY ABS(100.0 * calls / norm - 100) DESC;


-- ------------------------------------------------------------
-- 6. Нарастающий итог минут за месяц
--
-- Как только в OVER появляется ORDER BY, SUM превращается из итога
-- по группе в нарастающий итог. Одна строчка разницы с запросом 2,
-- а смысл другой.
-- ------------------------------------------------------------
SELECT call_date,
       bill_min                                                  AS minutes_day,
       SUM(bill_min) OVER (
           PARTITION BY project, substr(call_date, 1, 7)
           ORDER BY call_date)                                    AS minutes_total
FROM v_daily
WHERE project = 'alpha'
ORDER BY call_date;


-- ------------------------------------------------------------
-- 7. Часы, где чаще всего не дозваниваются
--
-- Отвечает на вопрос, который волнует бизнес: не «сколько потеряли»,
-- а «когда именно» — потому что на это можно повлиять расстановкой.
-- ------------------------------------------------------------
SELECT project,
       printf('%02d:00-%02d:00', call_hour, call_hour + 1) AS hour_range,
       total,
       lost,
       ROUND(100.0 * lost_share, 1)                        AS lost_pct
FROM v_hourly
WHERE total > 50
ORDER BY lost_share DESC
LIMIT 15;


-- ------------------------------------------------------------
-- 8. Контроль качества: что в данных не так
--
-- Такой запрос стоит гонять после каждой загрузки. Дубли call_id
-- здесь не ошибка: при переводе звонка между операторами
-- появляются две строки с одним номером.
-- ------------------------------------------------------------
SELECT 'звонков без оператора' AS check_name, COUNT(*) AS cnt
FROM calls WHERE operator IS NULL OR operator = ''
UNION ALL
SELECT 'разговор дольше часа', COUNT(*)
FROM calls WHERE talk_sec > 3600
UNION ALL
SELECT 'нулевая длительность', COUNT(*)
FROM calls WHERE talk_sec = 0
UNION ALL
SELECT 'повторяющийся id звонка', COUNT(*) FROM (
    SELECT call_id FROM calls GROUP BY call_id HAVING COUNT(*) > 1
);


-- ------------------------------------------------------------
-- 9. Пропущенные дни — дырки в загрузке
--
-- LAG по датам показывает разрыв между соседними днями. Полезно
-- после отпуска: сразу видно, за какие дни данные не заехали.
-- ------------------------------------------------------------
WITH d AS (
    SELECT project, call_date,
           LAG(call_date) OVER (PARTITION BY project ORDER BY call_date) AS prev
    FROM (SELECT DISTINCT project, call_date FROM calls)
)
SELECT project, prev AS after_day, call_date AS next_day,
       CAST(julianday(call_date) - julianday(prev) AS INT) - 1 AS missing_days
FROM d
WHERE prev IS NOT NULL
  AND julianday(call_date) - julianday(prev) > 1
ORDER BY project, prev;
