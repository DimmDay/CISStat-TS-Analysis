# scripts/mns6cert_red_repro.py
"""
Независимая сертификация MNS-CERT-6 — RED-воспроизведение на родителе
серии v2 (051b5fc — ответ тимлида по Q1–Q7; последний коммит БЕЗ
продуктового кода «Следующего шага» v2: MNS-SPEC-1 74fd1ca добавил
только спеку и гвард-тест) через git-worktree.

Статические факты F1–F10: v2-поверхности ОТСУТСТВУЮТ на родителе.
Оракулы сертификатора (scripts/mns6cert_oracles.py) копируются в
worktree и запускаются на родителе — ожидание: suite-RED (композиция
RED полная: GREEN достигается только реализацией серии v2). Зелёные на
родителе оракулы фиксируются честно — это регресс-пины Слоя A (v1),
не относящиеся к v2.

Запуск: python scripts/mns6cert_red_repro.py   (из корня репо на 154db51)
Протокол: scripts/mns6cert_red_repro.txt
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WT = Path("/home/z/my-project/mns6cert_parent_wt")
PARENT = "051b5fc"
PYTHON = sys.executable

FACTS_CODE = r"""
import importlib.util
import json
import sys
sys.path.insert(0, ".")

facts = {}

def module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

# F1: модуль реестра объяснимости отсутствует
facts["F1 app.core.mentor_explanations отсутствует"] = not module_exists("app.core.mentor_explanations")
# F2: файл реестра отсутствует
from pathlib import Path
facts["F2 rules/mentor_stop_explanations.json отсутствует"] = not Path("rules/mentor_stop_explanations.json").exists()
# F3-F4: константы/функция Слоя B отсутствуют в движке
import app.core.mentor_rules as mr
facts["F3 FALLBACK_ERROR_RULE_ID отсутствует"] = not hasattr(mr, "FALLBACK_ERROR_RULE_ID")
facts["F4 SCAN_STATUS_PRIORITY отсутствует"] = not hasattr(mr, "SCAN_STATUS_PRIORITY")
facts["F5 _fallback_recommendation отсутствует"] = not hasattr(mr, "_fallback_recommendation")
# F6: движок v1 не принимает node_facts
try:
    mr.evaluate_next_step({}, node_facts={})
    facts["F6 evaluate_next_step без node_facts (TypeError)"] = False
except TypeError:
    facts["F6 evaluate_next_step без node_facts (TypeError)"] = True
except Exception:
    facts["F6 evaluate_next_step без node_facts (TypeError)"] = False
# F7-F8: сборка объяснения в роутере отсутствует
prog_src = Path("apps/api/routers/progress.py").read_text(encoding="utf-8")
facts["F7 MentorExplanationOut отсутствует"] = "MentorExplanationOut" not in prog_src
facts["F8 _explanation_for_recommendation отсутствует"] = "_explanation_for_recommendation" not in prog_src
# F9: публичный доступ к статье по id отсутствует
reg_src = Path("apps/api/knowledge/registry.py").read_text(encoding="utf-8")
facts["F9 find_article_by_id отсутствует"] = "find_article_by_id" not in reg_src
# F10: фронт deep-link (MNS-LINK-3) отсутствует
facts["F10 packages/ui/lib/stopLinks.ts отсутствует"] = not Path("packages/ui/lib/stopLinks.ts").exists()

ok = all(facts.values())
for k, v in facts.items():
    print(("PASS " if v else "FAIL ") + k)
print("RED-FACTS:", "ALL-RED" if ok else "NOT-RED")
sys.exit(0 if ok else 1)
"""


def run(cmd: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "DATABASE_URL": "", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    lines: list[str] = [
        f"mns6cert RED-воспроизведение на родителе {PARENT} серии v2 (git-worktree, дерево аудита не тронуто)",
        "",
    ]
    if WT.exists():
        run(["git", "worktree", "remove", "--force", str(WT)], ROOT)
    rc, out = run(["git", "worktree", "add", str(WT), PARENT], ROOT)
    if rc != 0:
        lines.append(f"ОШИБКА worktree: {out}")
        print(lines[-1])
        return 2
    try:
        rc_facts, out_facts = run([PYTHON, "-c", FACTS_CODE], WT)
        lines.append(f"### Статические факты RED (родитель {PARENT})")
        lines += out_facts.strip().splitlines()
        lines.append("")

        wt_scripts = WT / "scripts"
        wt_scripts.mkdir(exist_ok=True)
        shutil.copy(ROOT / "scripts/mns6cert_oracles.py", wt_scripts / "mns6cert_oracles.py")
        rc_oracle, out_oracle = run(
            [PYTHON, "-m", "pytest", "scripts/mns6cert_oracles.py", "-q", "--tb=no",
             "-p", "no:cacheprovider"], WT,
        )
        failed_names = sorted(
            {
                ".".join(line.split("::")[1:3])
                for line in out_oracle.splitlines()
                if "FAILED" in line and "scripts/mns6cert_oracles.py::" in line
            }
        )
        import re as _re

        m = _re.search(r"(\d+) failed(?:, (\d+) passed)?", out_oracle)
        failed_n = int(m.group(1)) if m else -1
        passed_n = int(m.group(2) or 0) if m else 0
        lines.append("### Оракулы сертификатора на родителе")
        lines.append(
            f"pytest rc={rc_oracle}; FAILED={failed_n}; "
            f"PASSED (регресс-пины v1 вне v2)={passed_n}"
        )
        lines += ["    " + name for name in failed_names]
        lines.append(
            f"ИТОГ RED-КОМПОЗИЦИИ: {'ПОЛНАЯ (suite RED)' if rc_oracle != 0 else 'НЕ ПОЛНАЯ'}"
        )
        lines.append("")
    finally:
        run(["git", "worktree", "remove", "--force", str(WT)], ROOT)
        run(["git", "worktree", "prune"], ROOT)
    wt_gone = not WT.exists()
    diff_empty = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0
    lines += [
        f"worktree удалён (cleanup): {wt_gone}",
        f"git diff пуст (дерево аудита чистое): {diff_empty}",
    ]
    (ROOT / "scripts/mns6cert_red_repro.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if rc_facts == 0 and rc_oracle != 0 and wt_gone and diff_empty else 3


if __name__ == "__main__":
    sys.exit(main())
