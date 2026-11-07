# AUTH-10-HOTFIX01 — подготовка INDEX и диагностика AUTH-00

Дополнение поверх cisstat-auth10-c13a52b.zip (база c13a52b). Исходный ZIP не изменяется. Тимлид подтвердил: перед упавшим локальным прогоном команда git add task manifest не выполнялась. AUTH-00 проверял старый Git INDEX, тогда как после распаковки рабочее дерево уже содержало AUTH-10. Это воспроизведено на чистом c13a52b + исходный ZIP без staging: четыре HTTP метода api-keys, operator surface и reviewed sources присутствуют только в рабочем дереве. Следовательно FAIL правильный; отключать INDEX/route/source проверки нельзя. Полного исходного Windows traceback нет; воспроизведён подтверждённый сценарий неподготовленного index, а не произвольная Windows runtime ошибка.

Изменения runner:

- Добавлена ранняя проверка выбранного Git snapshot перед длительным unit suite; финальная parity проверка сохранена, чтобы поймать изменение исходников во время прогона. Пропущенный git add выявляется сразу.
- AUTH-00 stdout/stderr сохраняются в UTF-8 `logs/local_gates/auth00.log` одновременно с выводом на экран. Python child явно UTF-8, legacy Windows console при необходимости получает escaped Unicode. Exit code дочернего процесса сохраняется, FAIL не становится PASS.
- В итоговой сводке повторяется FAILED STEP и путь полного лога. Для snapshot mismatch печатается порядок явной подготовки index. Другие гейты исполняются прежним способом.
- Режимы INDEX/HEAD, strict source parity, ignored/untracked route защита и запрет автоматического staging/commit сохранены. Обновлён только fingerprint runner в inventory.json, methods/paths/counts и runtime приложения прежние.

## Применение в PowerShell из корня репозитория

Распаковать hotfix поверх уже распакованного исходного AUTH-10 ZIP, затем:

```powershell
git status --short
git add --pathspec-from-file=scripts/auth10/files.txt
git add --pathspec-from-file=scripts/auth10/hotfix01/files.txt
git diff --cached --stat
python scripts/local_gates.py --only auth00 --skip-install
# Затем полный прогон при установленных зависимостях:
python scripts/local_gates.py --skip-install
```

Если после этого остаётся FAIL, приложить `logs/local_gates/auth00.log` (не добавлять его в Git). После вашего локального commit, перед push: `python scripts/local_gates.py --auth00-target head --skip-install`. Git add этих manifests повторно безопасен; он не добавляет посторонние пути. Просмотр содержимого перед staging остаётся обязанностью автора будущего commit.

Hotfix не требует пересборки api/web и не добавляет SQL/ENV. При первом развёртывании самого AUTH-10 остаются прежние команды build api web + explicit migration0024 из design.md. Commit/push и VM этой сессией не меняются.
