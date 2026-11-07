# Локальные гейты перед передачей в GitHub

База AUTH-09 — c2217ec; AUTH-09-HOTFIX01 применяется поверх cisstat-auth09-c2217ec.zip. Команды исполняются из корня checkout. scripts/local_gates.py --list показывает состав гейтов.

## До коммита: явно подготовить Git index

После распаковки исходного AUTH-09 и hotfix просмотрите изменения, добавьте только файлы обеих поставок в index и запустите гейты:

```bash
git status --short
git add --pathspec-from-file=scripts/auth09/files.txt
git add --pathspec-from-file=scripts/auth09/hotfix01/files.txt
git diff --cached --stat
python scripts/local_gates.py
```

При уже установленных зависимостях добавьте --skip-install. Быстрый повтор исправленного гейта:

```bash
python scripts/local_gates.py --only auth00 --skip-install
```

Default AUTH-00 target=INDEX: проверяется точный подготовленный Git tree, а не старый HEAD. Проверка сама ничего не stage/commit/push. Оба snapshots должны пройти inventory drift/classification; затем сравнивается полный reviewed report, включая source fingerprints. Несохранённый в index guard/helper/generated metadata либо ignored/untracked route — FAIL. Пустой index — FAIL. LF/CRLF нормализуются существующим inventory collector. `git write-tree` создаёт tree objects, не commit.

После изменения файлов снова выполните git add нужных путей и гейты. Если local HEAD уже содержит всю поставку, повторный git add тех же файлов безопасен. Эти команды не затрагивают посторонние пути; содержимое изменённых файлов предварительно просматривает тимлид.

## После коммита: проверить будущий push

После вашего локального commit, до push:

```bash
python scripts/local_gates.py --auth00-target head --skip-install
```

Прямой вызов `python scripts/auth00/check_committed.py` сохраняет строгий HEAD по умолчанию; для precommit явно `--target index`. Несуществующий/устаревший HEAD не подменяется index. CI работает на checkout commit и выполняет unit/adversarial tests плюс inventory --check на Ubuntu/Windows. Исходная ошибка поставки была в требовании нового POST уже в старом HEAD до коммита, а не в тестах приложения.

## Состав проверок

Default: auth09, auth08, auth06, auth07, auth05, auth04, auth03, auth02, auth01, auth00, rules, jest. Jest включает renderer build и typecheck обеих оболочек. Production builds — отдельно `npm run build:all`. Native PostgreSQL требует opt-in; отсутствие native проверки не считается доказательством долговечности.

Для AUTH-09 нужен disposable CISSTAT_AUTH_TEST_DSN в защищённом окружении (не production БД):

```bash
python scripts/local_gates.py --only auth09,auth09-postgres --skip-install
# либо вместе с default:
python scripts/local_gates.py --with-auth09-postgres --skip-install
```

Без DSN/при skips native не PASS. CI auth09.yml — Ubuntu/Windows unit и PostgreSQL16/18 native. auth08 и остальные существующие PostgreSQL opt-in сохранены. auth07 дополнительно проверяет импорт без Unix-only resource. Полный scientific pytest — --with-pytest; при средовых сбоях сравниваются FAILED-ID с чистой базой.

AUTH-09 добавил ровно POST /v1/progress/runs/{run_id}/restore: API235, registry239, full inventory567, discovery541. HOTFIX01 не меняет routes или runtime приложения. Подробности и границы воспроизведения — docs/auth09/hotfix01.md.
