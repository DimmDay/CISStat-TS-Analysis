# AUTH-14 HOTFIX-01 — точная диагностика AUTH-00 до push

08.11.2026, Москва. Патч накладывается **поверх cisstat-auth14-a16b31b.zip**, до commit/push. База Git остаётся a16b31bd0c3d49586de24d3556a39e43b9cc3321. Из приложенного auth00(1).log известен только `Inventory drift: docs/auth00/inventory.json`; прежний gate не сообщал, относится drift к WORKTREE или INDEX, и не показывал файлы. Поэтому конкретный локальный файл/причина по этому логу не установлены. Не объявляем Windows/CRLF дефект без воспроизведения.

## Изменения

`scripts/auth00/check_committed.py` теперь подписывает ошибку WORKTREE/INDEX/HEAD. При drift выводит точные reviewed source paths, ожидаемые/реальные SHA-256, изменившиеся entry IDs/поля и metadata keys. Отдельно сообщает malformed JSON и только serialization/documentation drift. Ошибка WORKTREE больше не сопровождается вводящим в заблуждение советом исправить её одним staging. Неполный INDEX получает указание проверить и явно stage согласованные source/map files.

Проверка остаётся read-only и строгой: нет автоматического regeneration inventory, staging, commit, fallback HEAD↔INDEX или принятия расхождений. Existing ignored-page/partial-source/guard-change protections сохранены. AUTH-00 карты пересобраны для изменённого helper/tests/docs. Объединённый manifest AUTH-14 включает исходную поставку и этот hotfix.

## На локальной машине (PowerShell, корень checkout)

Распаковать hotfix ZIP в тот же корень с заменой файлов. Затем:

```powershell
git status --short
git add --pathspec-from-file=scripts/auth14/files.txt
python scripts/local_gates.py --only auth00 --skip-install
Get-Content -Raw -Encoding UTF8 logs/local_gates/auth00.log
```

`files.txt` обновлён и перечисляет **весь AUTH-14 вместе с hotfix**, так что команда готовит согласованные source/map версии до commit. Runner сам не меняет index. Список только этого патча — `scripts/auth14/hotfix01/files.txt`; можно вместо объединённой команды явно stage исходный набор и hotfix manifest.

Если остаётся FAIL:

- `WORKTREE inventory check failed`: listed sources/map в рабочей папке не совпадают. Staging это не исправляет. Проверить изменения названных файлов против поставки; не запускать `inventory.py --write` ради зелёного gate. Для непредусмотренных изменений нужен отдельный review.
- `INDEX inventory check failed`: рабочая папка уже прошла проверку, но staged snapshot не согласован. Проверить named paths через `git diff --cached`, затем явно stage согласованные файлы поставки и повторить gate.
- `Reviewed worktree differs from INDEX`: оба snapshot внутренне корректны, но reviewed source/review data различаются; gate показывает пути.

Новый полный auth00.log содержит диагностические данные для следующего разбора, если локальная причина выходит за файлы поставки. Не удалять/не сбрасывать пользовательские изменения автоматически. При успехе можно повторить весь `python scripts/local_gates.py --skip-install`; после собственного commit проверять HEAD через `--auth00-target head`. Из сессии commit/push не выполняются.

## Проверка и границы

TDD:4/4 новых сценариев воспроизвели отсутствие диагностики (RED), после исправления13/13 precommit scenarios PASS. Включены реальные temporary Git repositories с unicode/spaces path, CRLF worktree/LF INDEX, неполным/пустым index, unstaged guard change, ignored page, untracked helper и запретом fallback. Патч дополнительно проверяется на чистой базе + прежний ZIP + hotfix; результаты записаны в worklog12 и protocols/.

Научные ядра, CU quotes/profiles, runtime, HTTP handlers, методы/пути, DTO и BFF не изменены. Kernel digest исходного measured reference сохраняется. Новых migrations/зависимостей нет. Hotfix относится к локальному/CI gate и не требует дополнительной пересборки images; первоначальная AUTH-14 по-прежнему разворачивается с api/web build согласно runbook. Нативный Windows в этой сессии не запускался; реальный локальный drift не объявляется устранённым без повторного лога пользователя.
