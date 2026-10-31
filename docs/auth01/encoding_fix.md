# AUTH-01 — Windows default encoding fix

31 октября 2026, Москва. Исправление поверх поставки AUTH-01 на dfe1941.

Наблюдение тимлида: local_gates.py → auth01 FAIL 13.5 s; auth00/rules/jest PASS.
Полного traceback нет; конкретная причина его запуска ещё не доказана.

Воспроизведён собственный дефект: два теста в test_auth01_registry.py читали
UTF-8 docs/auth00/inventory.json через Path.read_text() без encoding. При
Windows default CP1251 получено ровно два UnicodeDecodeError: byte 0x98,
position 285733. Они возникли в test_bindings_cover_all_api_and_task_aliases_of_auth00
и test_inventory_gate_rejects_new_or_removed_entry. Обычный Linux UTF-8 запуск
и чистое виртуальное окружение проходили, поэтому прежняя проверка дефект пропустила.

Процесс: повтор обычного гейта с установкой → чистый venv без system-site-packages
→ RED всего корпуса при default CP1251 → явный encoding="utf-8" в двух чтениях
→ GREEN обычного корпуса и CP1251/CP1252 → AUTH-00 --check и renderer build.
Не менять PYTHONUTF8 у пользователя и не регенерировать snapshots для сокрытия отказа.

Изменения:

- tests/unit/test_auth01_registry.py: два чтения с explicit UTF-8.
- scripts/auth01/windows_locale_check.py: весь корпус с locale-default
  CP1251 и CP1252 через scoped Path.read_text patch. Явные encodings сохранены,
  проверяется настоящий UTF-8 inventory с кириллицей, без переписывания файлов.
- .github/workflows/auth01.yml и scripts/local_gates.py: дополнительная
  обязательная locale-проверка после обычного unittest. CI и локальный порядок совпадают.
- worklog/worklog11.md, эта записка, протоколы и упаковщик узкого патча.

Эмуляция покрывает default encoding Path.read_text, не заменяет native Windows
или любую другую причину FAIL (pip/index/Python version/изменённый checkout).
Runtime API, capabilities, route inventory и generated DTO не изменяются.
AUTH-00 карта не требует регенерации; гейт проверяется обычным --check.

Применить ZIP поверх предыдущей поставки AUTH-01 и запустить:

```sh
python scripts/local_gates.py --only auth01
```

Если FAIL сохранится, сохранить полный вывод, включая первый упавший шаг:

```sh
python scripts/local_gates.py --only auth01 > auth01.log 2>&1
```

Сводка недостаточна для диагностики другого отказа. Этот патч не объявляет
состоявшийся запуск тимлида исправленным без повторного результата.
