#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPLOAD-DB-9-CERT — мутационный харнесс (двухуровневая схема «мутантов на своих мутантах»).

УРОВЕНЬ L1 — мутанты ЦЕЛИ сертификации (документы/артефакты UPLOAD-DB-9):
  каждый мутант вносится в рабочее дерево (с бэкапом sha256 и восстановлением),
  затем прогоняются ДВА канала убийства:
    REPO    — repo-гвард tests/unit/test_upload_db9_docs.py (для K-мутантов
              реестра знаний дополнительно tests/api/test_knowledge_api.py);
    ORACLE  — свои оракулы scripts/db9cert_oracles.py (режим check по текущим файлам).
  Классификация: DUAL / REPO-ONLY / ORACLE-ONLY / SURVIVOR (последнее — находка).
  no-op-контролы обязаны ПЕРЕЖИТЬ оба канала (защита от тривиальных убийств).

УРОВЕНЬ L2 — мутанты НА СВОИХ МУТАНТАХ:
  M2-1 реверс-мутант (применение + обратное применение = нетто-нооп): харнесс
       обязан распознать нетто-отсутствие семантической правки (sha256) и не
       засчитать убийство;
  M2-2 идемпотентный мутант (повторное применение того же паттерна): харнесс
       обязан сообщить APPLY-0 (паттерн уже отсутствует) и НЕ запускать каналы;
  M2-3 ослабленный мутант (порт только в HELP): обязан быть убит хотя бы одним
       каналом — проверка полноты покрытия по вхождениям;
  M2-4 мутанты ОРАКУЛА (перевёрнутые ожидания, режим selftest): обязаны давать
       нарушения — чувствительность собственного инструмента сертификации.

Только чтение/временная мутация рабочего дерева с гарантированным восстановлением;
без commit/push (AGENTS.md).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from db9cert_oracles import (  # noqa: E402
    ARTICLES_TS,
    DOC_PATHS,
    REGISTRY_JSON,
    check_docs,
    collect_code_facts,
)

PY = sys.executable

TARGETS = {
    "README": DOC_PATHS["README"],
    "ARCHITECTURE": DOC_PATHS["ARCHITECTURE"],
    "HELP": DOC_PATHS["HELP"],
    "SMOKE": DOC_PATHS["SMOKE"],
    "ARTICLES": ARTICLES_TS,
    "REGISTRY": REGISTRY_JSON,
}

# ── L1: мутанты цели (id, описание, файл, [(old, new, все_вхождения?]) ──────
# expect: 'kill' — обязан быть убит хотя бы одним каналом; 'survive' — нооп-контроль.
L1_MUTANTS = (
    # README
    ("R1", "порт PostgreSQL в матрице README 5432→5433", "README",
     [("5432", "5433", False)], "kill"),
    ("R2", "дефолт UPLOAD_DB_ROW_LIMIT в README 1 000 000→2 000 000", "README",
     [("1 000 000", "2 000 000", False)], "kill"),
    ("R3", "маршрут /test → /check в README", "README",
     [("POST /v1/internal/upload/db/test", "POST /v1/internal/upload/db/check", False)], "kill"),
    ("R4", "драйвер ClickHouse в README → вымышленный", "README",
     [("clickhouse-connect", "ch-native-client", True)], "kill"),
    ("R5", "нечестный статус UI в README: заглушка→реализована", "README",
     [("на странице «Загрузка» — заглушка", "на странице «Загрузка» — реализована", False)], "kill"),
    ("R6", "ссылка на спеку плана в README → несуществующий файл", "README",
     [("spec_database_plan.md", "spec_database_missing.md", True)], "kill"),
    ("R7", "env UPLOAD_DB_HOST_WHITELIST → вымышленное имя в README", "README",
     [("UPLOAD_DB_HOST_WHITELIST", "UPLOAD_DB_HOST_LIMIT", True)], "kill"),
    # HELP
    ("H1", "pg_hba.conf → pg_access.conf (все вхождения)", "HELP",
     [("pg_hba.conf", "pg_access.conf", True)], "kill"),
    ("H2", "SQLite read-only URI mode=ro → mode=rw (семантический флип)", "HELP",
     [("mode=ro&uri=true", "mode=rw&uri=true", True)], "kill"),
    ("H3", "DuckDB read_only=True → read_only=False", "HELP",
     [("read_only=True", "read_only=False", True)], "kill"),
    ("H4", "caching_sha2_password → caching_sha256_password (все)", "HELP",
     [("caching_sha2_password", "caching_sha256_password", True)], "kill"),
    ("H5", "users.xml → users.yaml (все)", "HELP",
     [("users.xml", "users.yaml", True)], "kill"),
    ("H6", "фантомная env UPLOAD_DB_MAX_ROWS в таблице справки", "HELP",
     [("| Маскирование секретов |", "| Фантомный лимит | env `UPLOAD_DB_MAX_ROWS` | выдумка |\n| Маскирование секретов |", False)], "kill"),
    # ARCHITECTURE
    ("A1", "ссылка реестра на код → несуществующий путь", "ARCHITECTURE",
     [("app/data/db_connectors.py", "app/data/db_registry.py", True)], "kill"),
    ("A2", "контракт записи DbConnectorSpec → ConnectorSpec", "ARCHITECTURE",
     [("DbConnectorSpec", "ConnectorSpec", True)], "kill"),
    ("A4", "порт ClickHouse в ARCHITECTURE 8123→8124", "ARCHITECTURE",
     [("8123", "8124", True)], "kill"),
    # SMOKE
    ("S1", "INSTALL_MSODBCSQL18 → INSTALL_MSODBC18 (все)", "SMOKE",
     [("INSTALL_MSODBCSQL18", "INSTALL_MSODBC18", True)], "kill"),
    ("S2", "422 → 400 во всём смоук-чеклисте", "SMOKE",
     [("422", "400", True)], "kill"),
    ("S3", "SQLite → SQLight в смоук-чеклисте (CI-пара)", "SMOKE",
     [("SQLite", "SQLight", True)], "kill"),
    # Знание
    ("K1", "article_id статьи → upload-db-conn (articles.ts)", "ARTICLES",
     [('article_id: "upload-db-connections"', 'article_id: "upload-db-conn"', False)], "kill"),
    ("K2", "stage_id статьи upload → uploads (articles.ts)", "ARTICLES",
     [('article_id: "upload-db-connections",\n    stage_id: "upload",',
       'article_id: "upload-db-connections",\n    stage_id: "uploads",', False)], "kill"),
    ("K3", "дрейф промоушена: article_id в registry_data.json", "REGISTRY",
     [('"article_id": "upload-db-connections"', '"article_id": "upload-db-conn"', False)], "kill"),
    # no-op контролы
    ("N1", "no-op контроль: пустая строка в конец README", "README",
     [("\n", "\n", False)], "survive"),  # реверс-применение ниже обнуляет правку
    ("N2", "no-op контроль: фактически нейтральная фраза в справку", "HELP",
     [("## Матрица поддерживаемых СУБД", "## Матрица поддерживаемых СУБД (сводно)", False)], "survive"),
)

L2_MUTANTS = (
    ("M2-1", "реверс-мутант R1: применить 5432→5433 и тут же 5433→5432 (нетто-нооп)"),
    ("M2-2", "идемпотентный мутант H2: повторное применение того же паттерна"),
    ("M2-3", "ослабленный мутант R1w: порт 5432→5433 ТОЛЬКО в HELP"),
    ("M2-4", "мутанты оракула: 3 перевёрнутых ожидания (режим selftest db9cert_oracles.py)"),
)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_mutant(path: Path, subs) -> tuple[int, str | None]:
    """Применить мутант; вернуть (число_замен, ошибка). Файл не тронут при ошибке."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return 0, f"read fail: {exc}"
    total = 0
    for old, new, all_occ in subs:
        n = text.count(old)
        if n == 0:
            return total, f"паттерн не найден: {old[:60]!r}"
        if all_occ:
            total += n
            text = text.replace(old, new)
        else:
            total += 1
            text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    return total, None


def run_repo_channel(knowledge_too: bool) -> tuple[bool, str]:
    cmd = [PY, "-m", "pytest", "tests/unit/test_upload_db9_docs.py", "-q", "--no-header", "-p", "no:cacheprovider"]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    tail = (p.stdout or "").strip().splitlines()[-1] if (p.stdout or "").strip() else "?"
    if p.returncode != 0:
        return True, f"REPO-KILL ({tail})"
    if knowledge_too:
        p2 = subprocess.run(
            [PY, "-m", "pytest", "tests/api/test_knowledge_api.py", "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=REPO, capture_output=True, text=True, timeout=600,
        )
        tail2 = (p2.stdout or "").strip().splitlines()[-1] if (p2.stdout or "").strip() else "?"
        if p2.returncode != 0:
            return True, f"REPO-KILL knowledge-api ({tail2})"
    return False, "repo-green"


def run_oracle_channel(facts) -> tuple[bool, str]:
    docs = {k: p.read_text(encoding="utf-8") for k, p in DOC_PATHS.items()}
    docs["ARTICLES"] = ARTICLES_TS.read_text(encoding="utf-8")
    docs["REGISTRY"] = REGISTRY_JSON.read_text(encoding="utf-8")
    vs = check_docs(docs, facts)
    if vs:
        codes = sorted({v.split(":")[0] for v in vs})
        return True, f"ORACLE-KILL {codes} ({len(vs)} наруш.)"
    return False, "oracle-clean"


def main() -> int:
    facts = collect_code_facts()
    out: list[str] = [
        "UPLOAD-DB-9-CERT: мутационный харнесс (L1 мутанты цели + L2 мутанты на своих мутантах)",
        f"HEAD: {facts.head}",
        "",
        "── УРОВЕНЬ L1: мутанты цели (двухканальная схема REPO + ORACLE) ──",
    ]
    originals = {name: sha256_of(p) for name, p in TARGETS.items()}
    rows = []
    dual = repo_only = oracle_only = survivors = 0
    findings: list[str] = []

    for mid, desc, target, subs, expect in L1_MUTANTS:
        path = TARGETS[target]
        knowledge_too = target in ("ARTICLES", "REGISTRY")
        n, err = apply_mutant(path, subs)
        if err:
            out.append(f"{mid} [{target}] {desc}: ОШИБКА ПРИМЕНЕНИЯ ({err}) — ПРОПУСК")
            findings.append(f"{mid}: ошибка применения")
            rows.append((mid, "APPLY-FAIL"))
            continue
        repo_killed, repo_msg = run_repo_channel(knowledge_too)
        oracle_killed, oracle_msg = run_oracle_channel(facts)
        if expect == "survive":
            verdict = "SURVIVOR-OK (контроль)" if not (repo_killed or oracle_killed) else \
                f"ЛОЖНОЕ УБИЙСТВО КОНТРОЛЯ repo={repo_killed} oracle={oracle_killed}"
            if repo_killed or oracle_killed:
                findings.append(f"{mid}: no-op контроль убит (ложное срабатывание каналов)")
                ok = False
            else:
                ok = True
            out.append(f"{mid} [{target}] {desc}: {verdict} | repo: {repo_msg} | oracle: {oracle_msg}")
        else:
            if repo_killed and oracle_killed:
                verdict = "DUAL-KILLED"
                dual += 1
                ok = True
            elif repo_killed:
                verdict = "REPO-ONLY"
                repo_only += 1
                ok = True
            elif oracle_killed:
                verdict = "ORACLE-ONLY (repo-гэп канала — см. примечание)"
                oracle_only += 1
                ok = True
            else:
                verdict = "DUAL-SURVIVOR — НАХОДКА СЕРТИФИКАЦИИ"
                survivors += 1
                findings.append(f"{mid}: пережил ОБА канала ({desc})")
                ok = False
            out.append(f"{mid} [{target}] {desc}: {verdict} | repo: {repo_msg} | oracle: {oracle_msg}")
        _restore(path, originals[target])
        rows.append((mid, verdict))

    out.append("")
    out.append("── УРОВЕНЬ L2: мутанты на своих мутантах ──")

    # M2-1 реверс-мутант
    p = TARGETS["README"]
    n1, e1 = apply_mutant(p, [("5432", "5433", False)])
    n2, e2 = apply_mutant(p, [("5433", "5432", False)])
    net_noop = sha256_of(p) == originals["README"]
    if net_noop and n1 > 0 and n2 > 0:
        rk, rm = run_repo_channel(False)
        ok_m21, om = run_oracle_channel(facts)
        verdict = "OK: нетто-нооп распознан по sha256, каналы не насчитали убийства" if not (rk or ok_m21) else \
            "ПРОВАЛ: нетто-нооп засчитан каналами как мутант"
        out.append(f"M2-1 реверс-мутант (применений {n1}+{n2}): {verdict} | repo: {rm} | oracle: {om}")
        if rk or ok_m21:
            findings.append("M2-1: реверс-мутант ошибочно засчитан")
    else:
        out.append(f"M2-1: ОШИБКА (n1={n1}, n2={n2}, net_noop={net_noop})")

    # M2-2 идемпотентный мутант
    p = TARGETS["HELP"]
    n1, e1 = apply_mutant(p, [("mode=ro&uri=true", "mode=rw&uri=true", True)])
    n2, e2 = apply_mutant(p, [("mode=ro&uri=true", "mode=rw&uri=true", True)])
    if n1 > 0 and n2 == 0 and e2 is not None:
        out.append("M2-2 идемпотентный мутант H2: OK: повторное применение ОТЛОВЛЕНО "
                   "(APPLY-0, паттерн уже отсутствует) — двойная мутация не проходит незамеченной")
        _restore(p, originals["HELP"])
    else:
        out.append(f"M2-2: ОШИБКА (первое применение {n1}, повторное {n2}, err2={e2})")
        _restore(p, originals["HELP"])

    # M2-3 ослабленный мутант (порт только в HELP)
    p = TARGETS["HELP"]
    n, err = apply_mutant(p, [("5432", "5433", True)])
    if n and not err:
        rk, rm = run_repo_channel(False)
        okill, om = run_oracle_channel(facts)
        if rk or okill:
            out.append(f"M2-3 ослабленный мутант R1w (порт только в HELP): УБИТ "
                       f"({'repo' if rk else 'oracle'}-каналом) — покрытие вхождений полно")
        else:
            out.append("M2-3: DUAL-SURVIVOR — НАХОДКА (ослабленный мутант пережил оба канала)")
            findings.append("M2-3: ослабленный мутант пережил оба канала")
        _restore(p, originals["HELP"])
    else:
        out.append(f"M2-3: ОШИБКА ПРИМЕНЕНИЯ ({err})")

    # M2-4 мутанты оракула
    p = subprocess.run([PY, str(REPO / "scripts" / "db9cert_oracles.py"), "selftest"],
                       capture_output=True, text=True, timeout=300)
    self_ok = p.returncode == 0
    caught = sum(1 for line in (p.stdout or "").splitlines() if "ПОЙМАНО" in line)
    out.append(f"M2-4 мутанты оракула (3 перевёрнутых ожидания): "
               f"{'OK: все перевёрнутые ожидания пойманы (' + str(caught) + '/3)' if self_ok else 'ПРОВАЛ'}")

    # Восстановление + верификация
    out.append("")
    restored = True
    for name, path in TARGETS.items():
        _restore(path, originals[name])
        if sha256_of(path) != originals[name]:
            restored = False
            out.append(f"!! ВОССТАНОВЛЕНИЕ НЕ ПОДТВЕРЖДЕНО: {name}")
    out.append(f"Восстановление рабочего дерева: {'ПОДТВЕРЖДЕНО sha256 всех 6 целей' if restored else 'ПРОВАЛ'}")

    out.append("")
    out.append(f"Итог L1: DUAL-KILLED={dual}, REPO-ONLY={repo_only}, ORACLE-ONLY={oracle_only}, "
               f"DUAL-SURVIVOR={survivors}; контролов no-op=2")
    if findings:
        out.append("НАХОДКИ:")
        out.extend(f"  - {x}" for x in findings)
    else:
        out.append("НАХОДОК НЕТ (все kill-мутанты убиты хотя бы одним каналом, "
                   "no-op-контролы пережили, L2-контроль пройден)")
    report = "\n".join(out)
    print(report)
    protocol = REPO / "scripts" / "db9cert_mutations.txt"
    protocol.write_text(report + "\n", encoding="utf-8")
    return 0 if (not findings and restored) else 1


def _restore(path: Path, expected_sha: str) -> None:
    """Восстановить файл из git-индекса и проверить sha256 (идемпотентно)."""
    subprocess.run(["git", "checkout", "--", str(path.relative_to(REPO))],
                   cwd=REPO, capture_output=True, text=True, timeout=60)
    if sha256_of(path) != expected_sha:
        # повтор на случай гонки файловых операций
        subprocess.run(["git", "checkout", "--", str(path.relative_to(REPO))],
                       cwd=REPO, capture_output=True, text=True, timeout=60)


if __name__ == "__main__":
    raise SystemExit(main())
