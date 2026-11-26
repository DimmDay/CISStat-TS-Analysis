# PGV-PNG-DATE — дата отображаемого представления в запросе PNG

База804d41138a8688cda5958d691bf1b4bfac6a91aa,26.11.2026 (Москва).
AGENTS/спецификация/журнал и upload→producer→snapshot→worker изучены.
Worker на VM восстановлен; оператор подтвердил ready/сохранение image/inputs.
Новый датасет и hard reload не устраняют source_unavailable у chart/distribution.
VM: freeze failures0, нужные visual_result существуют. Значит отсутствие
артефакта не доказано; общий UI текст объединяет разные отказы.

Локальный native PostgreSQL replay реального UI-порядка: upload → GET current/
target/dataset/stats/structure-detection/timeseries/distribution без POST
/date-column → все frozen результаты имеются → POST /visuals 409
source_unavailable, message «обязательный ref снапшота недоступен: date_column».
Важная граница прежних тестов: prepare() заранее подтверждал date-column.

Проект до кода: API уже принимает optional date_column, клиент visualExports.ts
уже сериализует dateColumn, но VisualExportButton/ChartScope и Upload не
передают это поле. Передать отображаемую колонку дат в этот существующий
контракт. Для самого ряда — date_column ответа timeseries; для остальных
upload views — тот же выбор detection, которым пользуется экранный график.
Отсутствие явной даты не заполнять выдуманным именем и не подтверждать
структуру за пользователя: у Upload disabled с точной причиной. Undefined
для прежних consumers сохраняет backend/session resolution.

Риски: не менять научную сессию/target/date-confirmation/ledger; экспорт не
вызывает вычисляющий GET; не снимать required_refs/CAS/доступ/лимиты. SVG
по-прежнему только своего контейнера. Новых HTTP/DTO/DDL нет; backend и
renderer bytes не меняются. Нужен новый web image, штатный coherent release
собирает согласованные три образа; git pull сам не обновляет работающий UI.

TDD: полный Upload с настоящими Button/ChartScope/api client, fake научными
HTTP ответами и SVG renderer stubs: fresh/restored → chart+3 distributions,
raw POST включает date_column, никаких POST /date-column. Отдельно no-date
UI reason и компонентная совместимость. Native: без подтверждения даты,
явная дата в export →202, snapshot refs/date, сессионная дата остаётся None,
science GET не выполняется при export. Реальный Chromium/VM UI итог не
заявляется по protocol double/native admission. Гейты/routes/build/ZIP/worklog.


Результаты: UI RED4F/8P → GREEN12/12 (2 suites); существующие Upload regressions
72/72 (5 suites). Native PostgreSQL16.2 TCP/UTF85/5, skips0, leftovers=[];
новый case проверяет без date confirmation четыре202 и точную refs.date_column,
при старом payload —409 с имеющимся frozen result. Остальные native cases
включают настоящий AUTH13 worker/lifecycle/PNG bytes с renderer HTTP protocol
double; новый UI фикс сам по себе не является Chromium/VM PNG certification.
Обе Next production builds PASS (embedded20/standalone27), renderer tsc PASS;
реальные локальные Inter5.3.0 через штатный offline font hook, fonts/hook не
поставляются. Full Jest/Windows/PG18/remote CI не заявляются. Node dependencies
установлены в этом checkout для правильного разрешения workspace imports.

Default pgv-png расширен двумя UI suites, native остаётся strict opt-in.
AUTH00 actual routes/inventory и final INDEX/delivery proof — в протоколах и
worklog12. Runtime только TsAnalysisUpload.tsx и VisualExportButton.tsx.
