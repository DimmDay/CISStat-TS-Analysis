# AUTH-09-HOTFIX01 — AUTH-00 до локального коммита

Поставка поверх cisstat-auth09-c2217ec.zip. В исходном ZIP AUTH-00 проверял рабочее дерево против HEAD, хотя до коммита HEAD ещё c2217ec и не содержит POST restore. Воспроизведено единственное discovery-расхождение api:POST:/v1/progress/runs/{run_id}/restore. По одной итоговой сводке нельзя исключить иной подшаг на машине тимлида; исправление покрывает воспроизведённый дефект рабочего процесса.

Решение: локальный default AUTH-00 проверяет Git index (подготовленный commit) после явного git add. Ничего не добавляет/коммитит автоматически. Strict HEAD остаётся --auth00-target head / check_committed.py --target head. Прямой вызов check_committed.py без флага сохраняет HEAD по умолчанию. Оба режима проверяют inventory snapshot целевого Git tree и полное совпадение reviewed reports с рабочим деревом: забытый helper/guard/metadata блокирует PASS даже при неизменном числе маршрутов. Ignored/untracked surface остаётся отказом. CI дополнительно включает adversarial precommit tests на Ubuntu/Windows.

TDD/риски: staged snapshot при старом/отсутствующем HEAD; пустой index; unstaged body без новых routes; partially staged inventory; omitted helper; ignored page; Windows CRLF; Unicode/space paths; строгий HEAD и отсутствие изменений index/HEAD. Git tree создаётся write-tree, commit не создаётся. Роуты и образы приложения не меняются. Проверяются actual ASGI count и source/generated contract parity, CLI compilation и полный AUTH-00 на распакованной составной поставке.


## Применение

Распаковать hotfix в корень уже применённого исходного AUTH-09, затем просмотреть изменения и явно подготовить index обоих архивов (без commit/push):

```bash
git status --short
git add --pathspec-from-file=scripts/auth09/files.txt
git add --pathspec-from-file=scripts/auth09/hotfix01/files.txt
git diff --cached --stat
python scripts/local_gates.py --only auth00 --skip-install
# затем обычный полный прогон при необходимости:
python scripts/local_gates.py --skip-install
```

После вашего локального commit перед push: `python scripts/local_gates.py --auth00-target head --skip-install`. Прямой check_committed.py сохраняет head default. Без явного staging default локального runner откажет: это нужная проверка будущего commit, а не пропуск гейта.

## Проверки

Новый положительный оракул на исходном checker: RED (неумеющий index checker требует отсутствующий HEAD). Новый checker: 9/9 Git/CRLF/adversarial tests PASS, общий AUTH-00 44/44 PASS. Никаких Git commits при тестах не создаётся; проверяется неизменность index. CI Ubuntu/Windows запускает оба набора. Windows здесь не запускался, воспроизведены CRLF и Unicode/space paths на Linux. Python CLI compilation и Ruff новых модулей PASS. Actual ASGI count остаётся 235, registry239, inventory567; новых HTTP/page/worker routes нет.

Составная доставка (original ZIP → hotfix → explicit git add → local AUTH-00) и строгий HEAD на чистой исходной базе проверяются отдельно; протоколы scripts/auth09/hotfix01/protocols/. Исходный ZIP идентифицируется SHA256 16afa81fe202ddfb4d7d6dd110951e91657c7524b58771bba79b6eef5979b20e. Hotfix packager включает только реальные отличия от него/его базы, сверяет CRC/байты. Образы VM для этого исправления гейтов пересобирать не требуется.
