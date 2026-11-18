# PGV-13-CERT-VM — разбор вывода VM, 18.11.2026

База: `338b15aa2c305a1be565289d075d2fb34e9ea46d`. Синхронизация выполнена в
отдельный checkout, прежние работы сохранены. Этот commit содержит акт/тесты
PGV-13-CERT и не меняет runtime `5d83967`. Зелёный CI, сообщённый тимлидом,
не закрывает известные RED сертификационного opt-in gate.
**PGV-13 по-прежнему NOT CERTIFIED.**

## Что теперь подтверждено на стороне VM

Источник — переданный тимлидом вывод `diagnose_vm.sh`, не собственный доступ
к серверу. Нормализованные факты: `scripts/pgv13vm/protocols/vm_evidence.json`.
Полный пользовательский stack trace не копируется; сохранён значимый fatal.

| Наблюдение | Вывод | Чего оно не доказывает |
| --- | --- | --- |
| Chromium: `No usable sandbox!`, SIGABRT; readyz=503, smoke=false | На VM реально заблокирован запуск sandboxed Chromium, до печати | Какой конкретно профиль/LSM/syscall отказал |
| userns_clone=1, max_user_namespaces=63378, AppArmor restriction=1; host unshare не может записать uid_map | Численный лимит не нулевой; userns всё равно недоступен вызывающему host-процессу | Что отказ внутри контейнера вызван только AppArmor, а не seccomp/иной политикой |
| UID=10001, CapEff=0, NoNewPrivs=1, Seccomp=2 | Декларированная защита частично подтверждена наблюдением | Содержимое seccomp-фильтра и разрешение namespace syscalls |
| renderer: network=none; API: enabled=true, URLError | Внутри renderer HTTP отвечает 503; из API запрос не получен как нормальный HTTP-ответ | Точный endpoint API и errno соединения; первопричину транспорта без дополнительных данных |
| image=:pgv08-fix с указанным image ID | Известно, какой образ запущен | Git commit внутри образа: один тег не удостоверяет возраст кода |

Сообщения crashpad о недоступных cpufreq-файлах идут после fatal; они не
заменяют его как установленную причину завершения Chromium.

В отличие от прежнего локального ProcessSingleton socket EPERM, это настоящее
свидетельство **VM sandbox blocker**. AppArmor userns restriction — ведущая
гипотеза, которую нужно привязать к kernel audit и текущему профилю контейнера.
Наличие Seccomp=2 сообщает лишь, что фильтр установлен. HTTPError=503 и URLError
различаются: отказ браузера внутри renderer не объясняет автоматически
ошибку соединения из API. Два слоя разбираются отдельно.

## Изменение диагностики

`scripts/pgv13cert/diagnose_vm.sh` дополнен без изменений runtime/compose:

- host/current AppArmor, Docker SecurityOptions, container AppArmorProfile/UsernsMode;
- container `/proc/self/attr/current`, uid_map/gid_map и AppArmor userns sysctl;
- отдельная временная `unshare -Ur true` проба внутри контейнера, если утилита
  установлена; ENOENT означает «нет утилиты», не запрет namespaces;
- безопасный target_scope API (loopback или configured_nonloopback, без URL);
- отдельно HTTPError (endpoint достигнут, но не ready) и URLError (тип reason/errno,
  без exception text/credentials). Exit=1 сохраняется для обоих отказов.

Без sudo/изменения host settings, без env dump, root/privileged, отключения
sandbox/AppArmor/seccomp, изменения сетей, рестартов или сборки образов.
Пробы создают лишь кратковременные процессы/namespace и могут оставлять audit
events. Тесты `scripts/pgv13vm/test_diagnose.py`: RED 4 FAIL → GREEN 4 PASS.
Docker подменён; API-часть исполняется как настоящий Python-код скрипта с
внедрённым клиентом/HTTP. Проверены 503, connection refusal, browser blocker,
healthy, exit codes и отсутствие URL/exception secrets. Это shell/probe regression,
не проверка исправленного sandbox на VM.

## Следующий сбор фактов на VM

После распаковки ZIP → локальный push → pull на VM, из корня репозитория:

```bash
bash scripts/pgv13cert/diagnose_vm.sh
sudo journalctl -k --since '15 minutes ago' --no-pager \
  | grep -E 'apparmor="DENIED"|userns_create|SECCOMP|seccomp'
```

Здесь grep — штатная утилита VM, установка rg не требуется. Второй шаг только
читает kernel journal с административным доступом. Readyz кэшируется 30 секунд;
при отсутствии свежих событий можно выполнить тот же диагностический скрипт
через 30 секунд. Пустая выборка журнала не означает отсутствие ограничения:
нужны применённый профиль, доступность audit и совпадение времени/PID/profile
с новым запуском Chromium. Не пересылать несвязанные записи журнала с данными
других сервисов; для анализа нужны только относящиеся к renderer denial events.

## Как выбирается исправление

После доказанного AppArmor denial — адресный профиль именно для renderer с
разрешением нужного userns и сохранением остальных ограничений. Применение
профиля к Docker container должно быть явным; профиль пути браузера хоста
не считается автоматически действующим внутри Docker. Если дополнительно
ограничивает seccomp — проверенный профиль с необходимыми namespace syscalls,
а не unconfined или SYS_ADMIN. Политика должна переживать reboot/recreate;
проверка включает положительный smoke и отрицательные проверки изоляции.

Глобальный `apparmor_restrict_unprivileged_userns=0` или `--no-sandbox` не
внесены и не предлагаются как исправление. Один rebuild не снимает host policy.
SUID sandbox при no-new-privileges/nosuid не является готовой заменой.
Это проектирование следующего исправления, **не утверждение о проверенной
готовности конкретного нового профиля**: Docker/VM здесь недоступны.

Для транспорта нужен отдельный согласованный канал API→renderer: поставленная
network:none + HTTP-only client конфигурация его не объявляет. Простое добавление
ports к network:none не создаёт такой канал. Выбор IPC/изолированной сети должен
сохранить запрет внешнего egress и пройти самостоятельные object/job/content
проверки; в этой диагностической поставке топология не изменена.

Даже readyz=200 после исправления политики не закрывает F-C13-00…03:
истинные Python P01/P02 payload → compiled SSR сейчас падают, profile/checkpoint
identity и reused presentation требуют продуктовой доработки. Окончательная
приёмка включает реальный final image и PNG-content/job/download путь.

Официальные первоисточники, проверены 18.11.2026:

- [Chromium: AppArmor user namespace restrictions](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md)
- [Docker: AppArmor profiles, current profile and audit](https://docs.docker.com/engine/security/apparmor/)
- [Playwright: non-root and seccomp namespace permissions](https://playwright.dev/docs/docker)

Роуты/DTO/OpenAPI/BFF не меняются. Карта AUTH-00 учитывает новый тестовый
Python-источник; local_gates.md дополнен явной командой probe regression.
Проверки/ZIP manifest: `scripts/pgv13vm/`. Пересборка образов для этой поставки
не нужна. Commit/push/операции на VM агентом не выполнялись.

## Локальная проверка поставки

Shell/probe regression: 4 PASS; bash и фактический Node-probe синтаксически проверены; renderer tsc build PASS. Повтор исходного PGV-13 cert gate: те же 10 FAIL / 8 PASS, exit1 NOT CERTIFIED. Локальный диагностический скрипт даёт exit2 (Docker отсутствует), не VM PASS. AUTH-00 actual/strict INDEX, semantic route parity и ZIP overlay фиксируются в protocols/routes.txt и delivery.json. Полный default/Windows/Docker/VM заново не исполнялся; production code прежний.
