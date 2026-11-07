# AUTH-09 — свежие доказательства восстановленной поставки

База c2217ec. Linux, Python3.12.14, native PostgreSQL16.2; Node24.22.1. Windows/PG18 здесь не запускались; включены в обязательный CI auth09.yml.

- red-unit: 12 RED на отсутствующих owner_account_id; red-native-base: действительный native/API оракул на чистом c2217ec RED. green-unit/clean-unit: 12 PASS, второй — отдельный минимальный venv.
- native-first: 20/20 AUTH-09 PASS с реальными PostgreSQL и HTTP; native-regression: 137/137 AUTH-02…09 PASS, без skips.
- gates-core: auth09,08,07 (в т.ч. windows_parity),05,04,03,02/rules PASS. auth06/auth01 PASS в red-generated-source-drift; его AUTH-00 FAIL был fingerprint drift новых OpenAPI/TS/proxy после первой генерации. Исправлено последним inventory --write, не ослаблением проверки.
- auth00-unit: 35/35 PASS; final-routes/routes-runtime: source/generated/runtime parity PASS, 235 API/239 bindings/567 inventory. route-delta: discovery +1 POST restore, removals=0. head-parity: ожидаемый FAIL до коммита тимлида — только этот новый POST.
- jest: 253 suites/2833 tests PASS, 1 suite/2 tests skipped; renderer/typecheck/builds: renderer и обе production оболочки PASS.
- api-full: 3340 PASS/52 skipped/12 FAIL. api-baseline: 3338 PASS/52 skipped/те же 12 FAIL. api-delta.json содержит точные FAILED-ID; новых failures нет. Это не полностью зелёный API suite. В full прогоне ещё отсутствовал fakeredis: один из одинаковых failures и module skip относятся к нему.
- targeted-api: после установки dev fakeredis — 175 PASS SessionStore/trace/redis CAS/visual/migration catalogue. Полный API заново не объявляется зелёным.
- visual: два отдельных PASS (Account owner impersonation запрещена; настоящий MEMBER передан в lazy freeze). ruff: новые Python файлы PASS.
- delivery-overlay: итоговая распаковка ZIP на чистую базу с повторными unit и source/generated/runtime checks. Упаковщик сверяет exact file set, CRC и все байты.
