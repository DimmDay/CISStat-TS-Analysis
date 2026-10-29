"""PGV-05-CERT — Class B: RED-свидетельства находок (обязаны быть RED
на родителе ad597cb и стать GREEN после PGV-05-FIX без правки смысла
оракулов).

F-P5C1 (низкая; документная честность, класс F-P4C3): докстринг
smoke-скрипта scripts/pgv05/check_reader.py заявляет «13 метрик», тогда
как фактический паспорт платформы несёт 15 групп (собственный вывод
скрипта печатает groups=15; worklog поставки честно говорит «4 снимка
с 15 группами»; корпус поставки пинует 14 групп подмножеством). Фикс --
документация (докстринг), не поведение.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestFP5C1SmokeDocstring:
    def test_b1_smoke_docstring_does_not_understate_group_count(self):
        """B1/F-P5C1: докстринг check_reader.py не заявляет счётчик
        групп, противоречащий фактическому паспорту (15 групп);
        формулировка «13 метрик» -- устаревшая, вводит в заблуждение."""
        source = (REPO_ROOT / "scripts" / "pgv05" / "check_reader.py").read_text(
            encoding="utf-8"
        )
        assert "13 метрик" not in source, (
            "F-P5C1: докстринг smoke-скрипта заявляет «13 метрик», "
            "фактический паспорт платформы несёт 15 групп (собственный "
            "вывод скрипта печатает groups=15) -- документная честность"
        )

    def test_b2_smoke_script_exists_and_prints_groups(self):
        """B2 (инвариант, GREEN): smoke-скрипт существует и печатает
        счётчик групп из фактического контента (len(passport)) -- сам
        РАНТАЙМ скрипта честен; дефект только в докстринге."""
        source = (REPO_ROOT / "scripts" / "pgv05" / "check_reader.py").read_text(
            encoding="utf-8"
        )
        assert "groups = len(record[\"passport\"] or {})" in source
        assert 'f"  {stage:>15}' in source
