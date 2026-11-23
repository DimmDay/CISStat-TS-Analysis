# PGV14 CI FIX — UTF-8 вместо Windows CP1252

База: `2db9f9c8700ce726b69291541a541889e05caa76`, 23.11.2026.
Проверены реальные GitHub Actions jobs PGV14:

- Ubuntu137717737956 — success.
- Windows137717738350 — failure, 17 package tests PASS, затем33 unittest с3errors.
- Лог: https://github.com/DimmDay/CISStat-TS-Analysis/actions/runs/45181960169/job/137717738350

Все три traceback указывают на `test_pgv13_accept.py:305`: `.read_text()`
читает UTF-8 report.json через CP1252 и падает на байте0x81. Это тесты
PGV14 every-page pipeline/finalize и два PGV13 pipeline/finalize. Строка
`Document workload requires the dedicated release candidate` — штатный вывод
negative control, не причина ненулевого exit. Сохранён raw excerpt actual log.

Почему локально прошло: `local_gates._utf8_environment()` задаёт
`PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`. В CI Windows прямой unittest использует
системное default text encoding. Linux также не воспроизводит CP1252 сам собой.
Это ошибка переносимости предыдущей поставки.

## Решение и риски

Все19 неявных pathlib text boundaries в host verifier PGV13/14 и двух test
harness получили explicit `encoding='utf-8'`: report/review/payload/evidence,
fixture writes. JSON/OCR остаются настоящим Unicode; нет ensure_ascii замены
контента, permissive decode, игнорирования ошибок, удаления cases или skips.
Мalformed UTF-8 продолжает отклоняться. Binary PNG/ZIP/source hashes прежние.

Новый `scripts/pgv14/cifix/windows_parity.py` запускает именно три упавших
исходных теста. Он принудительно делает implicit Path read/write/open CP1252,
сохраняя explicit encodings/binary I/O. Это работает даже при PYTHONUTF8=1:
отдельный negative probe сначала обязан упасть на UTF-8 кириллице, затем
explicit UTF-8 обязан прочитать её без изменений. Изначально probe опирался
только на Path.open; UTF8 mode уже подставлял туда utf-8 — такой недостаточный
контроль был отвергнут, initial log сохранён. Окончательная модель воспроизвела
ровно3 UnicodeDecodeError на исходном коде; после fix те же3 tests GREEN.
Проверяются все11 исходных scenarios в каждом pipeline, включая corrupt/reused,
PNG/ZIP, finalize и hash-bound evidence. Doubles не называются VM acceptance.

Parity теперь входит и в default `pgv14` local gate, и в обе CI matrix ветви.
Локальный UTF8 environment больше не может скрыть этот класс ошибки. Настоящий
Windows post-fix CI потребуется после commit/push тимлида; Linux CP1252 model
не объявляется выполненным Windows job.

```bash
python scripts/local_gates.py --only pgv14 --skip-install
# Адресное воспроизведение даже при локальном UTF8 режиме:
python scripts/pgv14/cifix/windows_parity.py
```

## Передача

Изменены только host tools/tests/gates/workflow/docs/reviewed fingerprints.
API/renderer/print layout, HTTP paths/methods/DTO/BFF, SQL/volumes и11 CASES
не меняются. Новых operation/authority surfaces нет. AUTH00 карта обновляется
штатным collector после review, strict INDEX сохраняется. `files.txt` содержит
только текущий hotfix, его нельзя заменять прежним89-file PGV14 manifest.

```bash
git add --pathspec-from-file=scripts/pgv14/cifix/files.txt
python scripts/local_gates.py --only auth00,pgv14 --skip-install
```

Commit/push не выполняются агентом. Hotfix не требует image rebuild или
recreate на VM. Старые hash-bound acceptance reports не редактировать: при новом
запуске host verifier берёт новые tool hashes; finalize прежнего report с
другой версией tools закономерно откажет. Runtime native Chromium/UDS/OCR
сертификация исходной PGV14 остаётся отдельным этапом.
