# PGV-13: изолированный seccomp A/B, 18.11.2026

База857a4d94b43a0221fa508666440e81d59f355823. Холодный smoke --probe тимлида
воспроизвёл Chromium No usable sandbox!/SIGABRT; следующая выборка kernel journal
пустая. Предыдущий audit относится к host unshare/unprivileged_userns, не Chromium.
Отсутствие audit не устанавливает ни AppArmor, ни seccomp как единственную причину.
PGV-13 остаётся NOT CERTIFIED. Эта поставка — эксперимент, не готовый runtime fix.

## Что запускается

`python3 scripts/pgv13sandbox/probe.py --out /tmp/pgv13-seccomp-ab.json`

Скрипт читает image ID и AppArmorProfile работающего renderer. При профиле,
отличном от docker-default, или отсутствии единственного контейнера эксперимент
останавливается. Используется именно существующий immutable sha256 image,
`--pull=never`, без сборки или обновления образа. Три временных контейнера
запускаются последовательно и удаляются, в том числе после timeout Docker CLI:

| Вариант | Seccomp | Назначение |
| --- | --- | --- |
| builtin | текущий встроенный профиль Docker | Воспроизведение в новой контрольной среде |
| reference | vendored Moby profile без изменений | Контроль закреплённого reference |
| namespaces | тот же reference + ALLOW clone/setns/unshare | Контролируемое изменение namespace syscalls |

Reference: [moby/profiles, exact commit](https://github.com/moby/profiles/blob/f862455628f78f84c937e967e4a03902fb1dee11/seccomp/default.json).
Blob и SHA256 зафиксированы в vendor/source.json, исходные bytes проверены по
GitHub blob SHA; Apache2 LICENSE включена. Сам reference **не объявлен копией
встроенного профиля Docker29.9.2**. Поэтому успех только reference имеет отдельный
неатрибутированный статус. Все прочие правила reference, default ERRNO и
clone3→ENOSYS остаются прежними. Три ALLOW взяты как диагностический паттерн
[Playwright1.57.0](https://github.com/microsoft/playwright/blob/v1.57.0/utils/docker/seccomp_profile.json),
но старый полный профиль Playwright не подменяет свежий reference Moby.

Дополнительные ALLOW разрешают эти три syscall без фильтра аргументов. Это
осознанный объём **изолированной диагностики**, не согласованная production policy.
Перед внедрением нужны review минимальных flags/syscalls, совместимость с
актуальным Docker, проверка AppArmor и отрицательные проверки изоляции.

Все варианты: docker-default, UID10001, no-new-privileges, cap_drop ALL,
read-only root, network:none, tmpfs /tmp noexec/nosuid512m, shm256m, memory2g,
pids128, init. Это ограничения поставленного compose, не клонирование неизвестных
VM overrides. Нет host mounts, опубликованных ports, SYS_ADMIN, privileged,
unconfined или изменения sysctl/AppArmor. Не исполняются чужие URL/payload;
только штатный синтетический mini-PNG probe-cyrillic из существующего image.

Скрипт проверяет parent UID/NNP/Seccomp/CapEff, невозможность записи и создания
mount namespace без userns. Proxy над Playwright только проверяет/передаёт
реальные launchServer options: chromiumSandbox=true, без sandbox bypass-флагов.
Проверки входят в isolation_ok. Это не полная независимая проверка всех
внутренних механизмов Chromium sandbox.

Имена контейнеров уникальные cisstat-pgv13-probe-UUID. Работающий renderer,
API, compose/env/host profiles не изменяются. Эксперимент создаёт и удаляет
временные контейнеры, то есть это не read-only Docker operation. Одновременно
существует максимум один тестовый контейнер с лимитом2g; фактическое потребление
обычно меньше лимита, reservation не задаётся. Доступ к Docker должен быть
у обычного оператора. Рестарт работающих служб не требуется.

## Результаты

| conclusion | Интерпретация |
| --- | --- |
| NAMESPACE_RULES_CANDIDATE | builtin и reference не печатают, namespaces печатает при isolation_ok: три ALLOW дают работающий кандидат относительно reference |
| REFERENCE_DIFF_UNATTRIBUTED | reference уже печатает; нельзя приписать улучшение трём namespace rules |
| STILL_BLOCKED | namespace rules недостаточны; читаем ошибку конкретного arm, не объявляем AppArmor доказанным |
| BASELINE_PASSED | Новая builtin среда уже печатает; исходный инцидент в ней не воспроизведён |
| INCONCLUSIVE_SETUP / INCONCLUSIVE_ISOLATION | Неполный запуск/проверка, timeout, несовместимый профиль/зависимости или нарушение контроля; положительного вывода нет |

Exit0 — только NAMESPACE_RULES_CANDIDATE, **не сертификат PGV-13**.
Exit1 — прочие завершённые результаты, exit2 — inconclusive/setup.
На stdout печатаются arm/exit/isolation/namespace/smoke и conclusion;
полный JSON со stderr и source provenance — в --out. Передавать сначала достаточно
краткую stdout-матрицу; при необходимости ошибки конкретного arm из JSON.
Полный Docker inspect/Env/API secrets/cookies не собираются.

## Порядок на VM

После обычной цепочки ZIP→локальная распаковка→push→pull, из корня checkout:

```bash
python3 scripts/pgv13sandbox/probe.py --out /tmp/pgv13-seccomp-ab.json
```

Зависимости — Python3 stdlib и Docker CLI/daemon. Vendor-файлы поставлены,
network download/установка пакетов/npm/миграции/rebuild images не нужны.
Сам скрипт ничего не commit/push/deploy. Оператор не должен менять compose или
копировать namespaces profile в production по одному exit0. После кандидата
нужна отдельная продуктовая поставка и приёмка на VM. API loopback connection
refused, F-C13-00…03, P01/P02 PNG content этим опытом не исправляются.

## Локальная верификация и ограничения

Контроли: `python -m pytest scripts/pgv13sandbox/test_probe.py -q`.
8 RED до реализации → 8 GREEN; source pin/diff/clone3, причинная матрица,
сохранение flags/image, unique cleanup и timeout. subprocess подменён.
Node payload синтаксически проверяется, renderer tsc build и actual AUTH-00
проверяются отдельно; default gates не меняются. Промежуточный контроль ошибочно
принял запрещённый литерал внутри JS-проверки за Docker flag; он сохранён в
protocols/guard-control-intermediate.txt, scope теста исправлен на CLI flags.
Это не ошибка renderer и не скрытый runtime RED.

Docker в среде агента отсутствует: local-no-docker.txt содержит exit2
INCONCLUSIVE_SETUP, не PASS. Ни один arm на VM агентом не запущен, новый seccomp
не сертифицирован, результата кандидата пока нет. HTTP/DTO/BFF routes не менялись;
inventory/policy_review обновлены для fingerprints инструментов/vendor/local_gates.
Финальные route/INDEX/build/ZIP проверки — protocols и manifest этой поставки.

Дополнительный meaningful control: setup failure обязан заменить старый положительный JSON-отчёт. Получен целевой RED (1 FAIL/8 PASS) → исправлена запись RUNNING/error report → финальные 9 PASS. Stale-report-red.txt сохранён; при ошибке записи файла оператор видит report_write_error и exit2.
