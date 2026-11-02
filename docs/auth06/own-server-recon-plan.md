# AUTH-06-OPS-RECON — Переезд API с render.com на собственный сервер: разведка и план

*2026-11-02, база main@2299ad0. Задача поставлена по комментариям коллеги к AUTH-06: для первого входа администратора (`docs/auth06/first-admin.md`) рабочему API нужен PostgreSQL; на render.com создание БД — только платный тариф, поэтому контур переезжает на собственный сервер. Решение тимлида: API размещаем на своём железе за одним из собственных доменов; оболочки (Next.js) остаются на Vercel — они бесплатны.*

---

## 1. Контекст и почему переносить нечего

- **Ничего не мигрируем.** Миграция 0021 (AUTH-05 MFA-схема) на рабочем контуре не применялась, `bootstrap.py` не выполнялся, именованного ADMIN/сессий/MFA-факторов/аудита нет. Это **первичное развёртывание** на своём железе: ноль переноса данных, ноль риска потери. Если бы переезд случился после bootstrap'а, пришлось бы тащить MFA-факторы, учётки и durable-аудит.
- **Код не меняется вообще.** AUTH-06 спроектирован first-party: браузер ходит только на `ts-standalone.vercel.app` (force-dynamic Node proxy `/api/v1/[...path]`), API_URL — server-only переменная. Перенос API = сменить одно значение `API_URL` в Vercel; `ALLOWED_ORIGINS`/`CISSTAT_AUTH_ALLOWED_ORIGINS` остаются те же. Карта роутов AUTH-00 (234 API-операции, 559 entries), миграции, bootstrap, diagnose — инфраструктурно-нейтральны.
- **Уходят оба раздражителя render free-тира**: засыпание сервиса (холодный старт; на момент разведки `https://ts-standalone.vercel.app/api/v1/health` стабильно отдаёт `proxy_unavailable` — бэкенд render.com не отвечает) и платный Postgres с ограниченным сроком.
- **Ключи и env — те же** (`docs/auth06/design.md`, раздел «Конфигурация до rollout»): `CISSTAT_AUTH_CSRF_KEY` (≥32 байт), `CISSTAT_AUTH_MFA_KEYS`/`CISSTAT_AUTH_MFA_ACTIVE_KEY` (JSON-keyring AUTH-05), `CISSTAT_AUTH_DATABASE_URL` либо `DATABASE_URL`, `CISSTAT_STORAGE_MODE=required` для fail-closed durable-режима, exact HTTPS origins в `CISSTAT_AUTH_ALLOWED_ORIGINS`/`ALLOWED_ORIGINS`.

## 2. Windows сейчас или Linux для прода — решение

**Короткий ответ: разведку железа выполняем на Windows (скрипт этой задачи), прод-деплой — сразу на Linux (Ubuntu Server 24.04 LTS). Держать API-прод на Windows не рекомендуется.**

| Фактор | Linux (Ubuntu Server 24.04 LTS) | Windows 10/11 / Windows Server |
|---|---|---|
| Образ API | `apps/api/Dockerfile` = `python:3.12-slim` (Debian bookworm) + msodbcsql18 из packages.microsoft.com/debian/12 — собирается нативно | Только через Linux-контейнеры внутри WSL2-VM: двойная виртуализация, RAM-оверхед, проброс портов через VM |
| RAM на ОС | сервер без GUI: ~300–500 МБ | GUI + Defender + индексация: ~1.5–2 ГБ — при рекомендованных 4 ГБ это вытесняет uvicorn с torch (резидентно ~1+ ГБ) |
| Аптайм | `unattended-upgrades` без автоперезагрузки; `systemd` `Restart=always`/`restart: unless-stopped` | Windows Update сам перезагружает машину → Vercel-прокси отдаёт 503 до ручного входа |
| Операторский доступ | sshd из коробки; `ssh -L 5432:localhost:5432` для `migrate.py`/`bootstrap.py` | OpenSSH Server ставится отдельно |
| Совпадение с CI репозитория | `auth04/05/06.yml` гоняют native PostgreSQL 16/18 на `ubuntu-24.04` — прод повторяет CI-контур 1:1 | CI-матрица Linux не воспроизводится |
| Renderer PGV-08 | контейнер с headless Chromium (no-network/read-only/cap-drop) — Linux-паттерн | неприменим |
| Стоимость/лицензия | бесплатно | активация/лицензия Server |

**Когда Windows оправдан**: только как временная dev/стейджинг-площадка (Docker Desktop + WSL2) до переустановки, с ручным управлением перезагрузками. Если единственное железо — Windows-машина: Phase 0 (эта задача) подтверждает адекватность железа и сети → чистая установка Ubuntu Server 24.04 LTS на это железо (данные на нём не критичны, переносить нечего — см. §1). Если машина уже стоит у хостера с Windows-шаблоном — переустановить на Linux-шаблон из панели хостера.

## 3. Целевая архитектура (что соберём после разведки)

docker compose на сервере (файл — отдельная следующая задача, здесь только целевой вид):

| Сервис | Образ | Роль | Ключевые условия |
|---|---|---|---|
| postgres | `postgres:16` (матрица CI auth04/05/06 = 16/18; берём 16 LTS) | durable-хранилище AUTH-02/04/05 (`0021`), research_runs, DOCLOG | `ports:` НЕ публикуем — только docker-сеть; volume `pgdata`; healthcheck `pg_isready` |
| api | сборка `apps/api/Dockerfile`, контекст = корень репо | FastAPI-бэкенд (uvicorn, PORT=8000) | env: `DATABASE_URL`/`CISSTAT_AUTH_DATABASE_URL`, `CISSTAT_STORAGE_MODE=required`, `CISSTAT_AUTH_CSRF_KEY`, `CISSTAT_AUTH_MFA_KEYS`+`CISSTAT_AUTH_MFA_ACTIVE_KEY`, `ALLOWED_ORIGINS`/`CISSTAT_AUTH_ALLOWED_ORIGINS=https://ts-standalone.vercel.app` |
| caddy | `caddy:2` | единственная точка входа 80/443, автоматический TLS Let's Encrypt по A-записи домена | `reverse_proxy api:8000`; volumes `caddy_data`/`caddy_config` |

- Наружу открыты **только 80/443** (и 22 для SSH). Файрвол сервера: 22/80/443.
- Postgres наружу не выставляется; операторские команды (`scripts/auth05/migrate.py --check/--apply`, `scripts/auth05/bootstrap.py prepare/create`, `verify_postgres.py`) — через SSH-туннель с локальной машины, затем по `docs/auth06/first-admin.md` без изменений.
- Vercel (server-only, без `NEXT_PUBLIC_`): `API_URL=https://<домен-API>`, `CISSTAT_AUTH_PUBLIC_ORIGIN=https://ts-standalone.vercel.app`.
- render.com выводится из контура после приёмки; откат = вернуть прежний `API_URL` (null-downtime переключение на Vercel env).

## 4. Требования к железу и сети (чек-лист разведки)

| Показатель | Минимум (коллегиальная оценка) | Комфорт | Что проверяет скрипт |
|---|---|---|---|
| RAM | 4 ГБ («2 ГБ — впритык»: базовый резидентный набор uvicorn с torch уже ~1+ ГБ) | 8 ГБ | `ram_total_gb`, `ram_free_gb`, top-5 процессов |
| CPU | 2 vCPU | 4+ потоков | `cpu_cores`, `cpu_logical` |
| Диск | 30–40 ГБ SSD, свободно ≥35 ГБ | 60+ ГБ SSD | `logical_disks`, `physical_media` (SSD/HDD) |
| Архитектура | x64 | — | `os_architecture` |
| Виртуализация | VT-x/AMD-V включена (для Windows Docker-пути) | — | `hypervisor_present`, `virtualization_firmware_enabled`, фичи WSL/VMP/Hyper-V |
| Режим питания | always-on 24/7 | — | `uptime_hours`, `last_boot`, батарея, план электропитания |
| Сеть | белый публичный IP (не CGNAT 100.64.0.0/10), проброс 80/443, не занятые порты | статический IP | `public_ip`, `nat_classification`, `listening_ports`, IIS/sshd |
| Домен | A-запись → публичный IP, доступ к управлению DNS | — | `domain_status` (по `-Domain`) |
| Docker | Docker Engine + compose plugin (на целевой ОС ставится в Phase 1) | — | `docker_*`, `wsl_*` |

Postgres для auth-схемы при этом крошечный (учётки/сессии/MFA/аудит) — отдельного ресурса не требует.

## 5. Как выполнить разведку

```console
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\auth06ops\recon_windows.ps1 -Domain api.your-domain.ru
```

- `-Domain` опционален, но **желательно указать сразу** — скрипт сверит A-запись домена с обнаруженным публичным IP (это же условие будущего сертификата Caddy/Let's Encrypt).
- Права администратора не требуются; при запуске от админа дополнительно определяются Windows-фичи (WSL/VirtualMachinePlatform/Hyper-V) и тип физических дисков (SSD/HDD).
- Скрипт **только читает**: ни одна команда ничего не меняет (гвард-тест запрещает мутирующие командлеты).
- Результат в `-OutDir` (по умолчанию `.\cisstat-recon`): `cisstat_recon_<timestamp>.json` (полный машиночитаемый отчёт) и `cisstat_recon_<timestamp>.txt` (сводка с вердиктом). **Оба файла прислать тимлиду** — они вход приёмки Phase 0.
- Вердикт трёхуровневый (культура TASK-144): `PASS` — соответствует; `ATTENTION` — не блокер, но требуется решение (NAT-проброс, десктоп-редакция Windows, занятые 80/443, ноутбук, HDD); `FAIL` — блокер переезда (CGNAT, <2 ядер, <3 ГБ RAM, нет места, нет виртуализации).

## 6. Сетевые ловушки собственного размещения

- **CGNAT** (`100.64.0.0/10`): скрипт пометит `FAIL`. Входящие 80/443 невозможны без релея → либо белый IP/другой тариф у провайдера, либо размещение в стойке/VPS. Это единственный класс неисправимых на месте блокеров.
- **Домашний роутер**: проброс 80/443 на сервер; локальный IP сервера закрепить (DHCP reservation).
- **Динамический публичный IP**: DDNS-клиент или статический IP у провайдера; Let's Encrypt перевыпустит сертификат при смене A-записи.
- **Блокировка портов провайдером** (изредка 80): надёжно проверяется только извне после Phase 2 — curl с внешней машины на `https://<домен>/health`.
- **Порт 80/443 занят локально** (IIS и т.п.): скрипт покажет слушающий процесс; решить до caddy-фазы.

## 7. Поэтапный план

| Фаза | Содержание | Критерий приёмки |
|---|---|---|
| Phase 0 (эта задача) | Разведка Windows + этот план | Оба файла отчёта у тимлида; FAIL-блокеров нет либо решения приняты |
| Phase 1 | Чистая установка Ubuntu Server 24.04 LTS; sshd; UFW 22/80/443; unattended-upgrades; Docker Engine + compose plugin; git clone репо | Приложение А (после-установочный чек-лист) зелёное |
| Phase 2 | compose-стек postgres:16 + api + caddy; DNS A-запись; выпуск TLS | `https://<домен>/health` = 200; `/health/ops` показывает durable-бэкенд (Postgres, `CISSTAT_STORAGE_MODE=required`); извне домен доступен |
| Phase 3 | Операторская процедура AUTH-05: через SSH-туннель `migrate.py --apply` (если 0021 не применена) → `--check` = `ok:true`; `bootstrap.py prepare` → `create --login dimm.day` (пароль скрытым вводом, ≥15 символов) | `docs/auth06/first-admin.md` выполняется без отклонений; ledger создан |
| Phase 4 | Первый вход: `https://ts-standalone.vercel.app/login?return_to=%2Fupload`, настройка TOTP, сохранение recovery codes; загрузка датасета под админом | Вход выполнен; файл загружен (401/403/503-пути уже обработаны TsAnalysisUpload на 2299ad0); run создан в Postgres |
| Phase 5 | Переключение Vercel `API_URL` на новый домен; вывод render.com из контура; `pg_dump` по cron (ежедневно, ≥14 дней); ключи `CISSTAT_AUTH_*` в `.env` (права 600) вне репо + офлайн-копия в менеджере паролей | Приёмка через собственный домен; render-сервис остановлен; бэкап восстановлен тестово |

## 8. Что берёт на себя тимлид (фиксация договорённости)

Аптайм и бэкапы (`pg_dump` по cron + хранение MFA/CSRF-ключей в менеджере паролей), обновления безопасности, файрвол (наружу только 22/80/443), DNS-управление доменом. Оболочки на Vercel остаются бесплатными — платных тарифов в контуре не будет.

## 9. Риски и честные границы этой задачи

- Скрипт разведки **не исполнялся на реальной Windows** (в песочнице разработки Windows нет). Валидация: полный синтаксический разбор парсером PowerShell 7.4.6 (`scripts/auth06ops/protocols/pwsh-parse.txt`), fail-soft smoke-прогон на Linux pwsh (`scripts/auth06ops/protocols/linux-smoke.txt` — все Windows-специфичные секции деградируют по design'у, JSON/TXT-артефакты формируются) и статические гварды `tests/api/test_auth06ops_recon_script.py` (ASCII-безопасность PS 5.1, отсутствие PS7-синтаксиса, баланс скобок, контрактная поверхность, запрет мутирующих командлетов).
- `generate_secrets.py` в репозитории **отсутствует** (упоминался коллегой): ключи генерируются вручную (`openssl rand -base64 32` для CSRF; MFA-keyring — JSON вида `{"key-id-1": "<base64 32 байта>"}` + active key-id, формат в `docs/auth05/design.md`) либо делаем генератор отдельной задачей. Phase 2 это не блокирует.
- Белый IP/блокировки провайдера выявляются только вне сервера — после Phase 2 внешней проверкой.
- Задача **не меняет runtime платформы**: ни маршрутов (карта AUTH-00 не изменялась, `check_routes` не требуется), ни миграций, ни UI; новые файлы — только разведочный скрипт, этот план, тест-гварды и протоколы.

## Приложение А. После-установочный чек-лист Ubuntu (Phase 1, ~1 минута)

```console
nproc                          # >= 2
free -h                        # >= 4 ГБ RAM
lsblk -d -o NAME,SIZE,ROTA     # ROTA=0 -> SSD
df -h /                        # >= 35 ГБ свободно
timedatectl                    # часовой пояс (для cron pg_dump)
ip -4 addr show                # локальный IP для DHCP reservation
curl -4 https://ifconfig.me    # публичный IP (сравнить с A-записью; альтернативы: ipinfo.io/ip, 2ip.ru)
sudo ufw status                # только 22/80/443
sudo systemctl status docker
docker compose version
git clone https://github.com/DimmDay/CISStat-TS-Analysis.git   # ветка main
```
