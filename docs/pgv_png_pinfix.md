# PGV-PNG-PINFIX — Compose dependency images

База exact7e09e57e79223a9772ef5fa58e0a59e20f1ab304,26.11.2026 (Москва).

Факт VM: current API image bc38cf4e… совпадает с одним из результатов
`config --images api`; второй результат postgres:16. Exit0/stderr empty.
worker credential missing, renderer ready. Предыдущий repair остановился
до bootstrap/ключа/recreate. Ошибка в нашем preflight: singleton equality
ошибочно считала dependency image признаком несовпадения API.

Проект/риски до кода: простое membership тоже недостаточно — старый API image
может оказаться образом зависимости при изменённом API. Не читать dotenv/
resolved config, не полагаться на порядок вывода. Два read-only Compose
`config --images api` с теми же фактическими ordered inputs/env/project:
original и probe с дополнительным временным JSON overlay только api.image.
Probe image — уникальная публичная метка, не credential. Сравнить multiset
после замены ровно одной probe-метки на живой API image. Зависимости могут
повторять API image и менять порядок — проверка остаётся однозначной.

Временный overlay используется ТОЛЬКО для config, удаляется и при отказе;
не передаётся в bootstrap run/recreate up и не меняет runtime labels/pins.
Никакой build/pull/Docker mutation во время probe. Compose error отдельно
от image mismatch; raw stderr/keys/config не выдавать. Unsupported/error
остаются fail-closed до private key mutation. Новых HTTP/DDL/зависимостей нет.

TDD: replay двух VM image строк, порядок/дубликаты, настоящий mismatch,
current image только у зависимости, config/probe failures и cleanup.
Существующий private append/bootstrap/recreate порядок сохраняется.
Проверки: unit/gates/AUTH00/check_routes, Python compile, task-only ZIP,
worklog12. VM/Docker не доступны агенту; успешный repair и UI PNG не заявляются
до результата оператора. Пересборка образов не нужна: меняется host CLI.

Первичный источник Compose: docker/compose v2.39.4 cmd/compose/config.go,
runConfigImages печатает project.Services (включая зависимости) с
cli.WithoutEnvironmentResolution. Мы вызываем только images, не полный config. URL: https://github.com/docker/compose/blob/v2.39.4/cmd/compose/config.go


Локально: RED5tests/2F+2E (включая replay VM), GREEN13/13. Unit adapter
проверяет actual/probe CLI, multiset и cleanup; bootstrap/recreate получают
только исходные ordered inputs. Docker/Compose live агентом не запускались.
Python compilation и финальные gates/routes/INDEX — протоколы в
scripts/pgv_png_pinfix/protocols; результаты доставки также в worklog12.
