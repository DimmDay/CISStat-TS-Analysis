# Акт независимой сертификации задачи UPLOAD-DB-7 (2026-10-16)

**Задача:** Фаза C «расширение матрицы и стенд»: MySQL/MariaDB
(mysql+pymysql, порт 3306) + MS SQL Server (mssql+pyodbc, ODBC Driver 18);
ПЕРЕСМОТР по указанию тимлида из UPLOAD-DB-4 — пароль MSSQL ВЫВЕДЕН из
URL-объекта (D4-паритет всех СУБД, connect_args["PWD"] с ODBC-экранированием);
fallback pymssql (S2/RP2): явный параметр mssql_driver → env
UPLOAD_DB_MSSQL_DRIVER → авто-резолюция; version_probe MySQL/MSSQL; пины
PyMySQL+cryptography+pyodbc; условный слой unixodbc+msodbcsql18 в
apps/api/Dockerfile (commit 4c7bc16, база задачи e2fa9a1).
**Метод:** мутанты на своих мутантах + оракулы на своих данных
(двухканальная схема repo+oracle, no-op-контроль, md5-паспорт).
**Вердикт: PASSED.**
**База аудита:** main@659f8fd (HEAD, origin/main «UPLOAD-DB-4-CERT»);
объект сертификации — app/data/db_connectors.py, requirements.txt,
apps/api/requirements.txt, apps/api/Dockerfile, тесты test_db_connectors/
test_db_guard; git diff e2fa9a1..659f8fd по коду задачи содержит ТОЛЬКО
коммит 4c7bc16 (659f8fd добавил акт/оракулы/харнесс сертификации DB-4 и
не трогал перечисленные файлы — проверено git diff e2fa9a1 659f8fd --stat).
Рабочее дерево чистое на протяжении всего аудита; commit/push НЕ выполнялись.

## 1. Сверка с кодовой базой (статический аудит, все точки на месте)

1. app/data/db_connectors.py — реестр (единственная точка знания о СУБД):
   запись mysql {dialect mysql+pymysql, default_port 3306, ssl_support,
   pip_package "PyMySQL cryptography" (extra 'cryptography' в метаданных
   PyMySQL НЕ существует — подсказка перечисляет оба пакета, паттерн
   duckdb), version_probe SELECT VERSION() — работает в MySQL и MariaDB};
   запись mssql {dialect mssql+pyodbc, default_port 1433,
   pip_package "pyodbc", fallback_pip_package "pymssql" (S2),
   version_probe SELECT @@VERSION}. Прочие записи (pg/ch/duckdb/sqlite)
   fallback_pip_package=None — поле добавлено без нарушения Фазы A.
2. _odbc_quote — ODBC-экранирование: обёртка в фигурные скобки ВСЕГДА,
   удвоение '}'; применяется к PWD перед connect_args (pyodbc.connect
   добавляет неизвестные kwargs к строке соединения — докстринг pyodbc 5.x;
   kwarg timeout перехватывается как login-таймаут).
3. _resolve_mssql_driver — порядок «явный параметр → env
   UPLOAD_DB_MSSQL_DRIVER (strip+lower) → авто»: явный/env вне
   {pyodbc, pymssql} — громкий ValueError (не тихое игнорирование);
   авто: pyodbc есть → основной (S2), иначе pymssql есть → fallback (RP2),
   иначе детерминированный дефолт mssql+pyodbc (ошибка открытия —
   дружественная D2).
4. build_server_url — mssql/pyodbc: URL БЕЗ пароля (query: driver=ODBC
   Driver 18 for SQL Server, Encrypt=yes|no, TrustServerCertificate=no при
   ssl), connect_args={PWD: _odbc_quote(pw), timeout: connect_timeout};
   mssql/pymssql: URL mssql+pymssql БЕЗ пароля, connect_args={password:
   сырой, login_timeout}; misuse-гвард: mssql_driver для не-mssql →
   ValueError; docstring честно фиксирует D4-паритет «НИ ДЛЯ ОДНОЙ СУБД»
   со ссылкой на эксперимент E1 (str(url) маскирует, но
   render_as_string(hide_password=False)/url.password отдают сырой пароль).
   PG/MySQL-ветки Фазы A не изменены (connect_timeout/sslmode/
   ssl_verify_cert/ssl_disabled/statement_timeout — на месте).
5. open_server_engine — обработчик ModuleNotFoundError (эксперимент
   E4-correct: create_engine инициализирует dbapi-слой и даёт СЫРОЙ
   ModuleNotFoundError): ImportError с label, exc.name, pip-подсказкой
   основного И fallback-драйвера + «(и env UPLOAD_DB_MSSQL_DRIVER=pymssql)»;
   обработчик NoSuchModuleError Фазы A сохранён.
6. Guarded-импорты pyodbc/pymysql — модуль импорт-безопасен без обоих
   драйверов; реестр читаем; dc.pyodbc/pymssql = None.
7. requirements.txt (корень) + apps/api/requirements.txt — пины
   PyMySQL>=1.1.0, cryptography>=41.0.0 (caching_sha2_password MySQL 8),
   pyodbc>=5.0.0; pymssql СОЗНАТЕЛЬНО не пиннен (RP2: опциональный
   fallback + env-переключатель); комментарии фиксируют уточнение записи
   плана «PyMySQL[cryptography]» по метаданным PyMySQL.
8. apps/api/Dockerfile — слой unixodbc+msodbcsql18 ПЕРЕД pip-слоем с
   build-arg INSTALL_MSODBCSQL18=true|false (RP2: закрытый контур без
   apt-репозитория MS собирается без слоя → pymssql-fallback); odbcinst-гвард
   регистрации «ODBC Driver 18 for SQL Server»; unixodbc в обоих режимах
   (без libodbc.so.2 не импортируется сам pyodbc); build-гвард pip-цепочки
   import pyodbc, pymysql, cryptography.
9. tests/unit/test_db_connectors.py — 25 новых тестов DB-7 в 5 классах
   (Registry 4, MysqlUrl 3, MssqlUrl 5, MssqlFallback 9, DriverHandoff 4);
   tests/unit/test_db_guard.py — autouse-фикстура детерминизма
   (dc.pyodbc=object()) для D3-тестов ssl-флагов.

## 2. Окружение и независимая верификация

venv Python 3.12.15 (восстановлен с нуля в сессии аудита): sqlalchemy
2.1.5, duckdb 1.5.6, PyMySQL 2.2.8, pyodbc 5.3.0, cryptography 44.0.3,
clickhouse-connect, duckdb-engine, psycopg[binary], fastapi 0.128.0,
fakeredis 2.34.1, PyWavelets/pandera/arch (известный средовой класс),
statsmodels 0.14.5 (средовой класс: пин 0.15.0). pymssql в venv НЕ
установлен — авто-резолюция в этом окружении даёт pyodbc; матрица
авто-резолюции покрыта оракулом O15 через monkeypatch (pyodbc/pymssql
объекты/None), handshake pymssql — оракулом O22 через честную fake-DBAPI.

GREEN repo: DB-трек юниты 155/155 (test_db_connectors 60 + test_db_guard +
test_db_connection + test_db_embedded) — в точности заявление worklog
UPLOAD-DB-7; tests/api/test_upload_db 31/31 + test_docker_image_layout
4/4 (в точности заявление worklog). Остальные импортёры
db_connectors/file_loader (test_file_loader, test_jsonstat,
test_distribution) — 32/32.

Полный tests/api: 2009 passed / 29 failed / 41 skipped — все 29 ID падений
ИДЕНТИЧНЫ базлайну scripts/db4cert_baseline_api_failed_ids.txt (средовые:
forecasting_session 16, modeling_workflow 4, models_backtest_real 2,
dataset_profile_detail_level 2, progress_audit_6c 1, models_candidates 1,
neural 1, feature_regressors 1 при statsmodels 0.14.5) — НИ ОДНОГО падения
в DB-контуре, ДЕЛЬТА 0.

Полный tests/unit: 1675 passed / 45 failed / 24 skipped + 3 errors — все
падения/ошибки средовые (tbats 8, prophet 8, structural_breaks 5,
forecasting 4, neural-интеграции, model_readiness, снапшоты
test_preprocessing), согласуются с базлайном worklog UPLOAD-DB-7
(1678/45/24, класс тот же); НИ ОДНОГО в DB-контуре (grep
db/upload/connector по ID падений — пуст).

## 3. RED-воспроизведение (scripts/db7cert_red_repro.py/.txt)

Родитель e2fa9a1 (родитель коммита задачи 4c7bc16) через git-worktree
(дерево аудита не тронуто, cleanup: worktree удалён, git diff пуст).
Статические факты — 10/10 RED: F1 mysql.version_probe is None; F2
mssql.version_probe is None; F3 mssql.fallback_pip_package отсутствует;
F4 _odbc_quote отсутствует; F5 kwarg mssql_driver отклонён (TypeError);
F6 родитель держит пароль MSSQL В URL-объекте (D4-исключение Фазы A —
пересмотр DB-7 подтверждён фактом); F7 connect_args mssql пуст (нет
PWD/timeout); F8 пины PyMySQL/cryptography/pyodbc отсутствуют в обоих
requirements; F9 Dockerfile без msodbcsql18; F10 mysql.pip_package =
"PyMySQL" (без cryptography).

Оракулы аудитора на родителе: suite RED (rc=1) — 22/27 FAILED, 5 PASSED.
Зелёные на родителе — честные регресс-пины scope'ов Фазы A, НЕ относящихся
к DB-7: O01 (D4 mysql), O02 (порт 3306), O03 (ssl-флаги mysql),
O04 (connect_timeout mysql), O07 (Encrypt/TrustServerCertificate — ODBC-флаги
появились в Фазе A; DB-7 менял только обработку пароля). Каждая DB-7-поверхность
(пароль вне URL, PWD-экранирование, fallback-цепочка, probes, пины
зависимостей, Dockerfile-слой, D2-подсказка с fallback) прикрыта минимум
одним КРАСНЫМ на родителе оракулом. Композиция RED полная: GREEN
достигается только реализацией UPLOAD-DB-7.

## 4. Оракулы на СВОИХ данных — 27/27 PASS (scripts/db7cert_oracles.py)

Корпус «высокогорная метеосеть Памира» (гляциологический пост, ледник
Федченко) ДИЗЪЮНКТЕН repo-корпусу (h/db.corp/dw/pw/mysql-pw/mssql-pw) и
корпусам прошлых сертификаций (db4cert «припортовая гидрологическая
сеть»; db3cert — embedded-файлы): host meteo.pamir.gla, база
pamir_observations, пользователь hydrolog_pamir, пароли с юникодом и
спецсимволами ODBC — «ледник;Федченко{2026}» и «p@ss;w0rd}}Памир»
(';' + удвоенная '}') — честная проверка экранирования на СВОИХ данных.
Автофикстура детерминизма: env-переключатели очищаются в каждом тесте.

Поверхности дизъюнктны/глубже repo: O01-O04 MySQL (D4 на юникод-пароле,
порт+rendered-строка, эксклюзивность ssl-флагов, connect_timeout +
ENV-переопределение — repo env-override для mysql не пинит); O05-O09 MSSQL
(D4 пересмотренный, PWD-экранирование спец-паролей с удвоением '}',
ODBC-флаги query, login-таймаут + env-override, таблица _odbc_quote на
своих пинах: '', кавычка, '}', ';;', юникод, уже-удвоенные); O10-O16
fallback-цепочка (pymssql: СЫРОЙ пароль без ODBC-скобок + D4 + отсутствие
ODBC-флагов; pyodbc-явный; неизвестный → ValueError; env « PYMSSQL »
— кейс/пробелы нормализуются; env-неверное «jtds» → громкий ValueError с
именем переменной; матрица авто-резолюции через monkeypatch; misuse-гвард
для mysql); O17-O18 реестр (probe-матрица mysql/mssql + регресс pg/ch;
пин-подсказки: mysql «PyMySQL cryptography», mssql pyodbc+pymssql-fallback,
прочим None); O19-O20 D2-подсказка ModuleNotFoundError (label + pyodbc +
pymssql + env-переключатель для mssql; PyMySQL + cryptography для mysql;
у mysql fallback в подсказке отсутствует — негативный пин); O21-O22
handshake на СВОИХ паролях (pyodbc: строка соединения БЕЗ PWD и сырья,
PWD kwarg-ом экранирован, timeout kwarg-ом, UID из URL, DRIVER/Encrypt;
pymssql: пароль kwarg-ом СЫРЫМ, login_timeout kwarg-ом — repo pymssql-
handshake не имеет); O23 импорт-безопасность subprocess-ом без
pyodbc/pymysql (реестр читаем, авто-дефолт детерминирован, build работает);
O24 сквозное делегирование file_loader.init_db_connection (capture
create_engine: connect_args PWD/timeout доходят до движка, URL без пароля,
ошибка транспорта обёрнута ConnectionError с маскированием **** — D4
сквозное, repo пинит только unit-уровень); O25 D4-МАТРИЦА всех четырёх
серверных путей (pg/mysql/mssql-pyodbc/mssql-pymssql: url.password is None
— замысел пересмотра одним пином); O26-O27 статические пины поставки
(обоих requirements: три пина + pymssql СОЗНАТЕЛЬНО НЕ пиннен; Dockerfile:
build-arg, msodbcsql18, unixodbc, odbcinst-гвард, apt-репозиторий MS,
build-гвард импорта — repo-тест docker-layout структуру ODBC-слоя не пинит).

В ходе отладки исправлены 5 ошибок СВОЕГО корпуса (НЕ кода): хелпер
подавал **kw вместо **base; арифметика ODBC-скобок в ожиданиях (удваивается
ТОЛЬКО '}': «ледник;Федченко{2026}» → «{ледник;Федченко{2026}}}»);
render_as_string URL-энкодит пробелы ('+'); fake-DBAPI pymssql без
__version__ (диалект SQLAlchemy mssql+pymssql читает dbapi.__version__);
маркер маскирования — «****», не слово. Код репозитория при отладке
оракулов НЕ менялся (md5-контроль).

## 5. Мутационный прогон — свои мутанты, двухканальная схема (repo 190 + oracle 27)

scripts/db7cert_mutations.py, протокол .txt; объект — app/data/
db_connectors.py (единственная точка изменения DB-7); md5-паспорт,
побайтовое восстановление каждого шага, финальный контроль — md5 СХОДИТСЯ,
git diff пуст. MB-00 no-op — SURVIVED ОБОИМИ каналами (харнесс достоверен).
KILLED ОБОИМИ — 21/21: MB-01 (обёртка скобок снята), MB-02 (удвоение '}'
снято), MB-03 (пароль MSSQL ВЕРНУТ в URL-объект — регрессия пересмотра D4/
E1), MB-04 (PWD без экранирования), MB-05 (PWD удалён — аутентификация
потеряна), MB-06 (login-таймаут снят), MB-07 (Encrypt инвертирован), MB-08
(TrustServerCertificate снят), MB-09 (порт 3307), MB-10 (mysql ssl-ветки
инвертированы), MB-11 (mysql connect_timeout снят), MB-12 (env-неверное
значение тихо игнорируется), MB-13 (авто-резолюция отдаёт fallback-диалект),
MB-14 (fallback-подсказка D2 снята), MB-15 (обработчик ModuleNotFoundError
снят — сырая ошибка dbapi), MB-16 (probe mysql снят), MB-17 (probe mssql
испорчен), MB-18 (подсказка без cryptography), MB-19 (fallback_pip_package
снят), MB-20 (misuse-гвард снят), MB-21 (валидация явного драйвера снята).
DUAL-SURVIVORS: 0. Первый круг чистый — усиления оракулов в ходе мутационного
прогона НЕ потребовалось (в отличие от DB-4-CERT, где MB-09 пережил первый
круг и потребовал усиления O08).

## 6. Находки и вердикт

N1 (положительное наблюдение): repo-канал УБИЛ все 21 мутанта — для DB-7
repo-покрытие полное (25 новых тестов пинают каждую поверхность); оракулы
добавили ГЛУБИНУ (env-override, кейс-нормализация env, D4-матрица 4 путей,
сквозное делегирование, handshake pymssql, статические пины поставки), а не
закрывали repo-гэпы. Контраст с DB-4-CERT (4 repo-SURVIVED) объясним: DB-7
меняла ядро с точечными repo-тестами, DB-4 создавала новый API-слой, где
сквозные свойства (персистенция, авто-цель) repo не пинил.

N2 (DoD-остаток подтверждён честно): «Docker-сборка с ODBC-драйвером
успешна» требует docker-демона — в песочнице аудита недоступен (тот же
остаток, что зафиксирован в worklog задачи). Статический оракул O27
покрывает слой по содержимому (build-arg, msodbcsql18, unixodbc,
odbcinst-гвард, apt-репозиторий MS, build-гвард импорта); верификация
самой сборки остаётся в среде тимлида. DoD «URL-билдеры без пароля в
строке» закрыт оракулами O05/O06/O10/O24/O25 + repo-тестами.

N3 (главная методологическая гарантия подтверждена независимо): пересмотр
D4 (пароль вне URL-объекта НИ ДЛЯ ОДНОЙ СУБД, включая pymssql-путь),
ODBC-экранирование спецсимволов, fallback-цепочка с громкими ValueError,
D2-подсказки с fallback, misuse-гварды — мутанты этих свойств не переживают
ни одного канала; юникод-пароли собственного корпуса проходят сквозной
путь build → connect_args → fake-connect без утечки в URL/conn_str/исключения.

ВЕРДИКТ: PASSED — ядро приёмки UPLOAD-DB-7 подтверждено независимо;
DoD задачи подтверждён (URL-билдеры mysql+pymysql/mssql+pyodbc без пароля
в строке; пины PyMySQL/cryptography/pyodbc в обоих requirements; Docker-слой
ODBC с условной установкой и гвардами — статически, сборка за тимлидом).
Код и тесты репозитория аудитом не менялись.

Deliverable: ZIP cisstat-upload-db-7-cert.zip → открытый контейнер сессии
(download + upload): акт docs/, оракулы + мутационный харнесс + RED-протокол
scripts/, worklog/worklog10.md. Без commit/push (AGENTS.md).

Примечания тимлиду: (1) следующий шаг по плану — UPLOAD-DB-8 «Тест-стенд +
интеграции + PG-семейство» (docker-compose.db-bench.yml, tests/integration,
вендор-детекция по SELECT version()/SELECT VERSION()/SELECT @@VERSION —
probes уже в реестре и сертифицированы); (2) env UPLOAD_DB_MSSQL_DRIVER —
переключатель деплоя, документировать в UPLOAD-DB-9 (README env-лимиты/
драйверы; громкий ValueError на неверном значении — поведение зафиксировано
оракулом O14); (3) pymssql в среде аудита не установлен — перед стендом
UPLOAD-DB-8 для MSSQL-ноги через fallback потребуется pip install pymssql
+ env UPLOAD_DB_MSSQL_DRIVER=pymssql (handshake-поверхность диалекта
проверена fake-DBAPI, включая чтение __version__).
