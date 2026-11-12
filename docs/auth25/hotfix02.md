# AUTH-25-HOTFIX-02 — патч Dockerfile: только существующие источники + repair

Дата: 12.11.2026. База: `main@f6dbec9` + AUTH-25 + AUTH-25-HOTFIX-01.

## Симптом

После применения HOTFIX-01 (первый `patch_dockerfile.py`) сборка api падает:

```
=> ERROR [36/55] COPY scripts/auth25/migrate.py scripts/auth25/reconcile.py ./scripts/auth25/
failed to solve: failed to compute cache key: "/scripts/auth25/migrate.py": not found
```

## Причина

Патчер v1 отзеркалил последнюю `COPY … scripts/authNN …`-строку Dockerfile дословно (подстановка `auth20→auth25`) — а это была auth20 в стиле «список файлов»:

```
COPY scripts/auth20/migrate.py scripts/auth20/reconcile.py ./scripts/auth20/
```

У AUTH-25 `migrate.py` нет и не должно быть: миграций в задаче нет (схема 0033/0034/0035 применена AUTH-21/22/23), поэтому в `scripts/auth25/` только `reconcile.py` / `verify_postgres.py` / `package_delivery.py` / `requirements.txt`. Внутрь образа нужен единственный in-container CLI — `reconcile.py` (verify_postgres и package_delivery — dev-гейты с хоста, requirements.txt — гейтовый).

## Исправление

`scripts/auth25/patch_dockerfile.py` **v2** (этот hotfix):

- парсит COPY-строку (`shlex`: флаги / источники / dest) вместо дословного зеркалирования;
- оставляет только источники, **существующие в build-context** (корень определяется по пути Dockerfile; при пустом результате — канонический `scripts/auth25/reconcile.py`);
- **чинит на месте** уже вставленную неверную auth25-строку (валидация источников, repair сохраняет отступ и флаги строки);
- всё из v1 сохранено: dir-стиль зеркалится целиком, `--chown`/абсолютный dest переносятся, без анкора — вставка перед `CMD/ENTRYPOINT`, multi-line COPY отклоняется, `--check`, `.bak`, идемпотентность.

Итоговая строка в `apps/api/Dockerfile` должна быть ровно:

```
COPY scripts/auth25/reconcile.py ./scripts/auth25/
```

Самотест: 16/16, включая точный кейс с VM (кривая строка из лога сборки → заменена, отступ сохранён; повторный прогон — `OK: valid` без записи).

### Вариант A — прямо на VM, без ожидания цепочки push/pull

```bash
cd /opt/cisstat/CISStat-TS-Analysis
sed -i 's|COPY scripts/auth25/migrate.py scripts/auth25/reconcile.py ./scripts/auth25/|COPY scripts/auth25/reconcile.py ./scripts/auth25/|' apps/api/Dockerfile
grep -n "scripts/auth25" apps/api/Dockerfile

docker compose build api
docker compose up -d --no-deps api
docker compose exec -T api ls scripts/auth25
docker compose exec -T api python scripts/auth25/reconcile.py --report
docker compose exec -T api python scripts/auth25/reconcile.py --launch-check --allow-empty-catalog
```

Эквивалентно можно распаковать этот zip поверх репо и запустить `python3 scripts/auth25/patch_dockerfile.py` — он сам заменит кривую строку (sed нужен только если zip ещё не распакован).

### Вариант B — штатная цепочка (zip → локальная машина → push → VM pull)

Локально: `unzip -o cisstat-auth25-hotfix02-f6dbec9.zip` поверх репо → `python3 scripts/auth25/patch_dockerfile.py` (diff: кривая строка заменена на каноническую) → `git add -A && git commit && git push`. На VM: `git pull --ff-only` → `python3 scripts/auth25/patch_dockerfile.py` (скажет `OK: … valid`, если строка уже верна) → `docker compose build api` → `up -d --no-deps api` → прогоны по `docs/auth25/deploy.md`.

## Состав hotfix

- `scripts/auth25/patch_dockerfile.py` — v2 (см. выше).
- `docs/auth25/hotfix02.md` — этот файл.
- `docs/auth25/deploy.md` — проверка итоговой строки патча в шагах.
- `worklog/worklog12.md` — запись AUTH-25-HOTFIX-02.

## Что НЕ затронуто

Код api (`reconciliation.py`, `security_audit.py`), тесты, гейты, CI, схема (0033/0034/0035), роуты (281 API / 658 entries), UI — без изменений; юнит 32/32 и native 105/105 остаются в силе; пересборка по-прежнему только api. Откат — `.bak` рядом с Dockerfile (состояние до HOTFIX-01) или повторный прогон патчера после ручной правки.

## Урок

Чужую COPY-строку можно зеркалировать только с проверкой существования источников в build-context — стиль строки (каталог / список файлов / один файл) не переносится между задачами: у задач с миграциями в образ кладётся migrate.py, у AUTH-25 — только reconcile.py. Проверка состава образа (`docker compose exec api ls scripts/auth25`) сразу после первого up — урок HOTFIX-01, остаётся в чеклисте.
