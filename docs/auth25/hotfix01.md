# AUTH-25-HOTFIX-01 — CLI scripts/auth25 не попал в образ api

Дата: 12.11.2026. База: `main@f6dbec9` + поставка `cisstat-auth25-f6dbec9.zip`.

## Симптом

После успешных `docker compose build api` и `docker compose up -d --no-deps api` (health ok):

```
$ docker compose exec -T api python scripts/auth25/reconcile.py --report
python: can't open file '/app/scripts/auth25/reconcile.py': [Errno 2] No such file or directory
```

## Причина

1. `/app` — это WORKDIR образа api: `docker compose exec` стартует в нём, и относительный путь `scripts/auth25/reconcile.py` резолвится как `/app/scripts/auth25/reconcile.py`. Python ничего не «ищет в папке app/» — это просто текущий каталог контейнера.
2. Файла там нет: поставка AUTH-25 добавила `scripts/auth25/` в репозиторий, но НЕ добавила `COPY`-строку в `apps/api/Dockerfile`, а образ содержит только явно скопированное. Все предыдущие поставки этот шаг делали (AUTH-20: «Dockerfile — COPY auth20», AUTH-21: «Dockerfile — COPY CLI», …); в AUTH-25 он пропущен. Дефект поставки, не VM.

## Исправление

### Вариант A — немедленный прогон без пересборки (эфемерно)

```bash
cd /opt/cisstat/CISStat-TS-Analysis/deployment/cisstat-stack
docker compose exec -T api mkdir -p /app/scripts/auth25
docker compose cp ../../scripts/auth25/. api:/app/scripts/auth25/
docker compose exec -T api python scripts/auth25/reconcile.py --report
docker compose exec -T api python scripts/auth25/reconcile.py --launch-check --allow-empty-catalog
```

Скопированное пропадёт при recreate контейнера — вариант только для отчёта «прямо сейчас», не отменяет вариант B. Если после копирования возникает `ModuleNotFoundError: apps` — layout образа отличается от ожидаемого, использовать только вариант B.

### Вариант B — штатный (патч Dockerfile + пересборка api)

На машине с репозиторием (обычная цепочка zip → распаковка → push):

```bash
cd <репозиторий>
unzip -o cisstat-auth25-hotfix01-f6dbec9.zip   # поверх рабочего дерева, пути совпадают
python3 scripts/auth25/patch_dockerfile.py     # diff в stdout, .bak рядом, идемпотентно
git diff apps/api/Dockerfile                   # убедиться: +1 строка COPY scripts/auth25
git add -A && git commit -m "AUTH-25-HOTFIX-01: COPY scripts/auth25 into api image" && git push
```

На VM:

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
python3 scripts/auth25/patch_dockerfile.py     # после pull избыточен, но идемпотентен
docker compose build api
docker compose up -d --no-deps api
docker compose exec -T api ls scripts/auth25   # reconcile.py должен быть
docker compose exec -T api python scripts/auth25/reconcile.py --report
docker compose exec -T api python scripts/auth25/reconcile.py --launch-check --allow-empty-catalog
```

Если hotfix применяется прямо на VM, не дожидаясь push, — те же patch/build/up на месте, но изменение нужно протолкнуть в GitHub, чтобы следующий `git pull --ff-only` не разошёлся.

## Состав hotfix

- `scripts/auth25/patch_dockerfile.py` — NEW: идемпотентный однострочный патч `apps/api/Dockerfile`. Зеркалит стиль последней `COPY … scripts/authNN …`-строки (включая `--chown` и абсолютный destination); без анкора вставляет `COPY scripts/auth25 ./scripts/auth25` перед первой `CMD/ENTRYPOINT`; от multi-line COPY (продолжение `\`) отказывается (exit 2, без записи). Флаг `--check` — только diff. `.bak`-копия рядом. Самотест: 12/12 (стили зеркалирования, идемпотентность, fallback, отказ от продолжения, отсутствие записи при `--check`).
- `docs/auth25/deploy.md` — обновлён: шаг патча до build; быстрый путь (вариант A); watermark теперь сразу после экспорта копируется на хост (`docker compose cp`) — путь внутри контейнера не переживает recreate.
- `docs/auth25/hotfix01.md` — этот файл.
- `worklog/worklog12.md` — запись AUTH-25-HOTFIX-01.

## Что НЕ затронуто

Код api (`reconciliation.py`, `security_audit.py`), тесты, гейты, CI, схема (0033/0034/0035), роуты (281 API / 658 entries), UI — без изменений; юнит 32/32 и native 105/105 остаются в силе. Откат патча — восстановить `apps/api/Dockerfile` из `.bak` и пересобрать; CLI при этом недоступен до повторного патча.
