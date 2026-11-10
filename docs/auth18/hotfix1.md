# AUTH-18 HOTFIX1 — Windows INDEX .env.example CRLF

Применять поверх полного AUTH-18 пакета для базы3ca5e4e. Не заменяет полную поставку AUTH-18.

Лог тимлида: WORKTREE принят, INDEX отличается только deployment/cisstat-stack/.env.example.
SHA256 LF: 7d7d08b476807691f1abb47705909799e04c09fb7b28ac71cd94c399ef66fad1.
SHA256 CRLF: 3e68ecabfcc2782ccd8289c0d0ac84312ef73f0fd28c429a72f4009f54e7afaf.
Оба значения независимо воспроизведены из поставленного файла. Это пропуск нормализации текстового .env.example в AUTH-00, а не изменение значений и не отсутствующие routes.

Исправление: source_digest нормализует CRLF→LF также для точного basename .env.example, как уже для Dockerfile. Другие/binary форматы сохраняют byte-exact fingerprint. Смысловое изменение env по-прежнему даёт FAIL; реальный .env не включается в review/ZIP. Файлы/значения env, runtime/routes/migrations не меняются. Автоматического staging или регенерации карты на машине тимлида нет.

Распаковать ZIP в корень того же checkout. Явно подготовить обе поставки:

```powershell
git add --pathspec-from-file=scripts/auth18/files.txt
git add --pathspec-from-file=scripts/auth18/hotfix1-files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

После собственного commit, перед push:

```powershell
python scripts/local_gates.py --only auth00 --auth00-target head --skip-install
```

Не нужно менять core.autocrlf, отключать гейт, удалять reviewed source или генерировать новую карту для обхода FAIL. Остальные зелёные гейты тимлида остаются результатами его прогона; локальная проверка исправления — protocols/hotfix1. Образы/миграции от hotfix не меняются; первоначальная установка AUTH-18 на VM требует api+web и0030 по docs/auth18/deploy.md.
