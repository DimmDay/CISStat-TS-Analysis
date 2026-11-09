# AUTH-16 HOTFIX-01 — переносимый hash Dockerfile

Диагноз по приложенному auth00(3).log: WORKTREE прошёл, INDEX не прошёл. Expected SHA256 `3465909327f0c2c407fb79b9b41ae877d9c81c3503bffd1ffb08bafcaa65867a` — точные LF bytes поставки apps/api/Dockerfile. Actual `0da21e1fb29204145854faa9328446f87d570c3353a69a03460c089dad62a418` — те же bytes, где LF заменены CRLF. Никаких других содержательных изменений это расхождение не доказывает. Причина конкретной Git-настройки клиента из лога не устанавливается и для исправления не нужна.

Ошибка поставки: collector нормализовал известные текстовые extensions, но не Dockerfile без расширения. Исправление добавляет только известный текстовый basename Dockerfile. Оно не меняет hashes LF-файлов, policy, маршруты, semantic/content comparison или binary fingerprints. Изменение RUN instruction по-прежнему FAIL; отдельный binary newline test остаётся FAIL на изменение bytes.

TDD: два RED теста воспроизводят ошибку; GREEN — Dockerfile portability/content drift, настоящий Git INDEX CRLF при LF WORKTREE без изменения INDEX гейтом, binary byte guard. Полный AUTH-00 PASS (57/57 tests + strict INDEX), actual check_routes255/255 PASS. Отдельный checkout базы + исходный ZIP + hotfix с принудительно записанным CRLF Dockerfile в INDEX воспроизвёл точный клиентский SHA256 и прошёл strict INDEX/actual ASGI. Изменённые Python-файлы прошли py_compile. Native/production web builds не повторяются: runtime/image bytes не менялись относительно уже проверенной AUTH-16 поставки. Из-за hotfix новая пересборка образов на VM не требуется; первоначальная установка AUTH-16 по deploy.md остаётся в силе.

Распаковать hotfix ZIP **поверх ранее распакованной AUTH-16 поставки**, в корень того же checkout. Включён объединённый scripts/auth16/files.txt и отдельный scripts/auth16/hotfix01/files.txt. Ничего не сбрасывать/не удалять, Git config не менять, inventory самостоятельно не генерировать.

```powershell
git add --pathspec-from-file=scripts/auth16/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

После PASS — обычный собственный commit; перед push можно проверить HEAD через `python scripts/local_gates.py --only auth00 --auth00-target head --skip-install`. Сессия не commit/push и не обращается к VM. Если снова FAIL, передать `Get-Content -Raw -Encoding UTF8 .\logs\local_gates\auth00.log`.
