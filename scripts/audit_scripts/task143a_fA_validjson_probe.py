# scripts/audit_scripts/task143a_fA_validjson_probe.py
"""Task 143a (проб сертификации Task 143) -- класс коррапта «валидный JSON
НЕ-объект» (null / число / массив / строка) против контракта деградации
Task 143 (session_store.py).

Контракт, заявленный в работе Task 143 (worklog5.md, п.4 и docstring):
  «битый JSON/бинарный мусор -> get()=None+warning, get_or_create выдаёт
   пустую сессию; save() поверх нечитаемого документа РАЗРЕШЁН (мусор не
   несёт ревизии и не может быть "свежее")».

Тесты Сэма (tests/api/test_session_store.py) покрывают классы:
  - "{not valid json!!"          -> json.JSONDecodeError
  - b"\\xff\\xfe binary garbage" -> UnicodeDecodeError (ValueError)
  - "garbage"                    -> json.JSONDecodeError

НЕ покрытый класс: строка под ключом -- ВАЛИДНЫЙ JSON, но не объект:
  "null" / "5" / "[1,2]" / "\\"hello\\"".
Ожидание по духу контракта («мусор не несёт ревизии»): деградация
  get() -> None (+warning), save() -> успешная перезапись.
Гипотеза: session_from_dict(None).get -> AttributeError, который НЕ входит
  ни в except-кортеж get(), ни в except-кортеж save() -> сырое исключение
  (500 на API), сессия заблокирована -- ровно та ситуация, которую Task 143
  устранял для остальных классов мусора.

Запуск: python scripts/audit_scripts/task143a_fA_validjson_probe.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fakeredis

from apps.api.session_store import RedisSessionStore

PAYLOADS = [
    ("null", "null"),
    ("number", "5"),
    ("array", '[{"session_id": "x"}]'),
    ("string", '"hello"'),
]


def main() -> int:
    verdicts: list[tuple[str, str, str]] = []
    for name, raw in PAYLOADS:
        client = fakeredis.FakeStrictRedis(server=fakeredis.FakeServer())
        store = RedisSessionStore(client=client, ttl_seconds=3600)
        key = store._key(f"probe-{name}")
        client.set(key, raw)

        # -- get() --
        try:
            session = store.get(f"probe-{name}")
            get_verdict = f"OK(None)" if session is None else f"OK(session rev={session.storage_revision})"
        except Exception as exc:  # noqa: BLE001 -- проб ловит ЛЮБОЕ сырое исключение
            get_verdict = f"CRASH {type(exc).__name__}: {exc}"

        # -- save() (fresh session, revision 0) --
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id=f"probe-{name}")
        try:
            store.save(session)
            save_verdict = "OK(saved)"
        except Exception as exc:  # noqa: BLE001
            save_verdict = f"CRASH {type(exc).__name__}: {exc}"

        verdicts.append((name, get_verdict, save_verdict))
        print(f"{name:<8} get(): {get_verdict:<40} save(): {save_verdict}")

    crashes = [v for v in verdicts if "CRASH" in v[1] or "CRASH" in v[2]]
    print()
    if crashes:
        print(f"ПРОБ: контрак деградации НАРУШЕН на {len(crashes)}/{len(PAYLOADS)} классах "
              "валидного-JSON-не-объекта (сырое исключение вместо деградации).")
        # показываем полный трейс первого крэша для отчёта
        client = fakeredis.FakeStrictRedis(server=fakeredis.FakeServer())
        store = RedisSessionStore(client=client, ttl_seconds=3600)
        client.set(store._key("trace"), "null")
        try:
            store.get("trace")
        except Exception:
            traceback.print_exc()
        return 1
    print("ПРОБ: деградация покрывает все классы -- находка F-A не воспроизводится.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())