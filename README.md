# PGV1314 route streams fix —24.11.2026

Применяется поверх предыдущего CI пакета для086b4f6.
Извлечь CISStat-PGV1314-route-streams-fix.zip в корень текущего репозитория
с заменой файлов. Это21 новый/изменённый файл только текущего исправления.
CISStat-PGV1314-local-evidence-route-streams.zip — новый14-file local proof:
распаковывать вне checkout. Старый пользовательский FAIL не переписан в PASS.
Новый proof не является native сертификатом PGV13/14.

Node22.23.5/npm10.9.9 уже установлены пользователем. Зависимости прежние.
PowerShell из корня репозитория:

```powershell
python scripts/local_gates.py --only pgv1314cert --skip-install
git add --pathspec-from-file=scripts/pgv1314cert/routefix/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

При успехе commit/push выполняет тимлид. Новый CI/native Windows run требует
подтверждения; Linux controls/OS stderr probe его не подменяют.
Дизайн: docs/pgv1314_route_streams_fix.md. Protocols и полный список файлов:
scripts/pgv1314cert/routefix/. Основной код: scripts/pgv1314cert/local.py;
regressions: tests/unit/test_pgv1314_ci.py. AUTH00 карта обновлена.
Все21 source ZIP files и переносимость/hash coverage proof проверены.
Полный local gate PASS175с:164pytest/357Jest/18typography/CP1252/обе сборки.
AUTH00 PASS54.6с/61tests, strict INDEX parity, рабочий INDEX неизменен.
HTTP routes/runtime/SQL/Dockerfiles прежние. Пересборка образов, миграции,
перезапуск на VM не нужны. VM не затрагивалась; commit/push не выполнялись.
