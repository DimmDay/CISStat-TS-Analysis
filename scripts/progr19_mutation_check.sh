#!/bin/bash
# PROGR-19 — мутационные пробы v2 (протокол: правка → прогон → откат).
# ВАЖНО (находка протокола v1): работа НЕ закоммичена (AGENTS.md),
# git checkout стирает реализацию — restore только через backup-копию.
set -u
cd /home/z/my-project/CISStat-TS-Analysis
MR=app/core/mentor_rules.py
BK=/home/z/my-project/scripts/mentor_rules.py.impl_backup

run() { python3 -m pytest tests/api/test_mentor_rules.py -q 2>&1 | tail -1; }
restore() { cp "$BK" "$MR"; }
import_check() { python3 -c "import app.core.mentor_rules" 2>&1 | grep -E "ImportError|Error" | tail -1 || echo "(импорт прошёл -- мутант ВЫЖИЛ)"; }

echo "== Контроль до проб: реализация на месте, 96 зелёных =="
run
python3 -c "from app.core.mentor_rules import STAGE_PHASE_TEXT_RULES; print('registry ok:', len(STAGE_PHASE_TEXT_RULES), 'stages')"

echo
echo "== M-1: перестановка правил validation (счётчик вперёд проблем) =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
old = '''    "validation": (
        PhaseTextRule(_some_done_with_problems, _VALIDATION_DONE_WITH_PROBLEMS),
        PhaseTextRule(_some_done, _VALIDATION_DONE_COUNT),
    ),'''
new = '''    "validation": (
        PhaseTextRule(_some_done, _VALIDATION_DONE_COUNT),
        PhaseTextRule(_some_done_with_problems, _VALIDATION_DONE_WITH_PROBLEMS),
    ),'''
assert old in s
open(p, "w", encoding="utf-8").write(s.replace(old, new))
EOF
run; restore

echo
echo "== M-2: опечатка в плейсхолдере шаблона {done_cout} (гейт импорта) =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
needle = "выполнено {done_count} из {total_nodes} "
assert needle in s, "needle not found!"
open(p, "w", encoding="utf-8").write(s.replace(needle, "выполнено {done_cout} из {total_nodes} ", 1))
EOF
import_check; restore

echo
echo "== M-3: неизвестная стадия в ключах реестра (инвариант STAGES) =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
needle = '    "forecasting": (\n        PhaseTextRule(_forecast_generated, _FORECASTING_GENERATED),'
assert needle in s, "needle not found!"
open(p, "w", encoding="utf-8").write(s.replace(needle, '    "forecast": (\n        PhaseTextRule(_forecast_generated, _FORECASTING_GENERATED),'))
EOF
import_check; restore

echo
echo "== M-4: стадия без правил (критерий приёмки v1.1) =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
needle = '''    "preprocessing": (
        PhaseTextRule(_some_done, _PREPROCESSING_DONE_COUNT),
    ),'''
assert needle in s, "needle not found!"
open(p, "w", encoding="utf-8").write(s.replace(needle, '    "preprocessing": (),'))
EOF
import_check; restore

echo
echo "== M-5: инверсия _some_done (факт всегда «есть») =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
needle = 'def _some_done(summary, events) -> bool:\n    return summary.get("done_count", 0) > 0'
assert needle in s, "needle not found!"
open(p, "w", encoding="utf-8").write(s.replace(needle, 'def _some_done(summary, events) -> bool:\n    return summary.get("done_count", 0) >= 0'))
EOF
run; restore

echo
echo "== M-6: phase_text передаёт statuses вместо сводки в условия =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
needle = "        if rule.condition(summary, rule_events):"
assert needle in s, "needle not found!"
open(p, "w", encoding="utf-8").write(s.replace(needle, "        if rule.condition(statuses or {}, rule_events):"))
EOF
run; restore

echo
echo "== M-7: fallback возвращает пустую строку =="
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
needle = "    return PHASE_TEXT_TEMPLATES.get(stage, _PHASE_TEXT_FALLBACK)\n\n\ndef validate_explanation_template"
assert needle in s, "needle not found!"
open(p, "w", encoding="utf-8").write(s.replace(needle, '    return ""\n\n\ndef validate_explanation_template'))
EOF
run; restore

echo
echo "== M-8: снят гейт полей шаблона + шаблон с {nodes} (гейт -- единственная защита) =="
# Двухшаговый мутант: гейт roots снят И шаблон validation заменён на
# подстановку списка nodes. Ожидание: импорт ПРОХОДИТ (защиты нет),
# рантайм phase_text с фактами падает KeyError -- тесты ловят крах.
python3 - << 'EOF'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
n1 = "            if not roots <= _PHASE_TEMPLATE_FIELDS:"
n2 = '''_VALIDATION_DONE_COUNT = (
    "Идёт этап «Валидация»: выполнено {done_count} из {total_nodes} "
    "проверок качества."
)'''
assert n1 in s and n2 in s, "needles not found!"
s = s.replace(n1, "            if False and not roots <= _PHASE_TEMPLATE_FIELDS:")
s = s.replace(n2, '''_VALIDATION_DONE_COUNT = (
    "Идёт этап «Валидация»: выполнено {done_count} из {total_nodes} "
    "проверок качества, узлы: {nodes}."
)''')
open(p, "w", encoding="utf-8").write(s)
EOF
run; restore

echo
echo "== Контроль после проб: чистая реализация, 96 зелёных =="
run
diff -q "$BK" "$MR" && echo "файл идентичен бэкапу"
echo "== DONE =="
