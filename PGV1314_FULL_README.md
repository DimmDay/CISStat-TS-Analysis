# Полный пакет PGV13/PGV14, 24.11.2026

База:77cbd70251d9dc46eff82f78ac2b5f92ebc0d155.

- cisstat-pgv13-pgv14-finalcert-77cbd70.zip —61 новых/обновлённых файлов кода,
  тестов, gates, карты, документации, протоколов и журнала. Распаковать В КОРЕНЬ
  checkout после review; staging manifest — scripts/pgv1314cert/files.txt.
- pgv1314-local-evidence-77cbd70.zip —13 raw local proof файлов. Распаковать
  ВНЕ checkout в captured bundle/pgv1314-local. Это не native certificate.
- VM_COMMANDS_PGV1314.md — полный порядок VM, включая подготовку PYC до plan,
  продолжение capture, native run, review и issue.
- worklog12.md, pgv1314-files.txt,
  pgv1314_final_certification.md и pgv1314_operator_resume.md — журнал/состав/дизайн.
- SHA256SUMS — hashes вложений. Сам этот файл в себя не хешируется.

Локальные проверки прошли; итоговый task certificate НЕ выдан. Для него нужны
настоящий VM native run и review каждой страницы всех11 случаев. Docker в сессии
отсутствовал, Chromium был BLOCKED/EPERM. Commit/push/VM rollout агент не выполнял.

Внешний полный ZIP — контейнер поставки, не распаковывать его содержимое как
код поверх репозитория: для этого используйте именно внутренний source ZIP.
