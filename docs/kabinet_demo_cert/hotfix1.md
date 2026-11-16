# AUTH-KABINET-DEMO CERT HOTFIX1 — явная UTF-8 кодировка тестов

Поверх полной cert-поставки для53ebba5. Поставляется исправленный test_kabinet_demo_cert.py, matching inventory и новые протоколы/запись worklog. Runtime/маршруты/Docker/env/migrations не меняются.

В сводке тимлида30 остальных gates PASS, включая AUTH00 и Jest. Приложенный вывод — AUTH00 (успешен); traceback kabinet-demo-cert не предоставлен. Поэтому точная причина конкретного прогона не подтверждена.

При проверке найден реальный дефект поставки: Path.read_text() без encoding использовал системную кодировку. На Windows CP1251 чтение UTF-8 YAML/env вызывало UnicodeDecodeError (byte0x98) и искажало русский текст DemoLanding, нарушая acceptance assert. Воспроизведено на неизменённых файлах deterministic oracle с CP1251 default (RED). Исправление — encoding='utf-8-sig' для всех входных source/manifest файлов, universal newlines сохранены. Не меняем locale/PYTHONUTF8 на машине тимлида и не ослабляем asserts.

GREEN: все5 исходных oracles проходят под эмуляцией CP1251; дополнительный полный fixture checkout UTF-8 BOM+CRLF тоже проходит, а подмена смыслового текста ожидаемо отклоняется. Верхний suite теперь7 tests (5+2 portability), без skips.

Распаковать поверх текущего checkout с cert-поставкой, затем:

```powershell
git add --pathspec-from-file=scripts/kabinet_demo_cert/hotfix1-files.txt
python scripts/local_gates.py --only kabinet-demo-cert,auth00 --skip-install
```

Если нет PyYAML: `python -m pip install -r scripts/kabinet_demo_cert/requirements.txt` (не добавлять другие workaround). После собственного commit перед push проверить `--auth00-target head`.

Если повторный FAIL остаётся, нужен вывод самого падающего шага, а не AUTH00:

```powershell
python -m unittest discover -s tests/unit -p test_kabinet_demo_cert.py -v 2>&1 | Tee-Object -FilePath kabinet-demo-cert-error.log
```

При наличии подтверждённого traceback последующий диагноз строится по нему; CP1251 не объявляется доказанной причиной конкретного пользовательского прогона без этого лога.

Из-за этого hotfix дополнительных VM команд/миграций/rebuild нет. Первоначальная cert-поставка требует web rebuild по прежнему deploy.md, если её ещё не разворачивали.
