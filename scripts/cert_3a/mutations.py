# -*- coding: utf-8 -*-
"""PANEL-MODELS-3a-CERT: мутационная кампания (двухканальная схема repo+oracle).

Мутант = точечная байтовая замена в продуктовом файле (ровно 1 вхождение),
паспорт md5 до/после, побайтовое восстановление. Каналы:
  REPO   -- адресные repo-тесты поставки 3a (tests/unit/test_panel_preprocessing.py,
            tests/api/test_panel_contract.py, указанные node IDs);
  ORACLE -- независимые оракулы scripts/cert_3a/oracle_backend.py (109 проверок).
Мутант KILLED, если хотя бы один канал упал; DUAL -- оба.

No-op-контроли (CTL) обязаны быть ALIVE в обоих каналах (достоверность харнесса).

Запуск из корня репозитория: python3 scripts/cert_3a/mutations.py [id...]
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path.cwd()
CERT = Path("/home/z/my-project/scripts/cert_3a")
ORACLE = CERT / "oracle_backend.py"

PANEL = Path("app/preprocessing/panel.py")
STORE = Path("apps/api/session_store.py")
WORKFLOW = Path("apps/api/modeling_workflow.py")

U = "tests/unit/test_panel_preprocessing.py"
A = "tests/api/test_panel_contract.py"
TP = U + "::TestPanelPassportGates"
BF = U + "::TestBuildPanelFrameFailClosed"

# ── Определения мутантов ────────────────────────────────────────────────────
MUTANTS = [
    # panel.py -- контракт build_panel_frame
    dict(id="MP-A01", file=PANEL, old="    if duplicated.any():", new="    if False and duplicated.any():",
         repo=[BF + "::test_duplicates_entity_date_rejected"], note="отключена проверка дубликатов (entity, date)"),
    dict(id="MP-A02", file=PANEL, old="    if gaps > 0:", new="    if False and gaps > 0:",
         repo=[BF + "::test_irregular_entity_rejected"], note="отключён запрет гэпов внутри сущности"),
    dict(id="MP-A05", file=PANEL, old="        converted = converted.dt.tz_convert(None)",
         new="        converted = converted  # no-op: tz не приводится",
         repo=[], note="tz-aware даты не нормализуются к naive UTC"),
    dict(id="MP-A13", file=PANEL,
         old="    valid_mask = target.notna().to_numpy() & finite_target",
         new="    valid_mask = target.notna().to_numpy() | finite_target",
         repo=[], note="n_valid учитывает inf (| вместо &)"),
    dict(id="MP-A14", file=PANEL,
         old="        if original_non_null > 0 and int(converted.notna().sum()) == 0:",
         new="        if False and original_non_null > 0:",
         repo=[BF + "::test_entirely_non_numeric_value_column_rejected"], note="не-числовая колонка не отклоняется"),
    dict(id="MP-A15", file=PANEL,
         old="f\"(пример сущностей: {sample}); панельный контракт требует \"",
         new="f\"(сущности не названы); панельный контракт требует \"",
         repo=[], note="пример сущностей удалён из сообщения о дубликатах"),
    dict(id="MP-A16", file=PANEL,
         old="    working = working.sort_values([entity_column, date_column], kind=\"mergesort\").reset_index(drop=True)",
         new="    working = working.reset_index(drop=True)",
         repo=[U + "::TestBuildPanelFrameFacts::test_frame_is_sorted_normalized_copy"],
         note="нормализованная копия не сортируется"),
    # panel.py -- преобразования
    dict(id="MP-A03", file=PANEL, old="        result[f\"{column}_lag{lag}\"] = grouped.shift(lag)",
         new="        result[f\"{column}_lag{lag}\"] = result[column].shift(lag)",
         repo=[U + "::TestPanelLag"], note="panel_lag -> плоский shift (утечка между сущностями)"),
    dict(id="MP-A16b", file=PANEL,
         old="    result = df.copy()\n    grouped = result.groupby(entity_column, sort=False)\n    for column in columns:\n        result[column] = grouped[column].transform(lambda s: s - s.mean())",
         new="    result = df.copy()\n    grouped = result.groupby(entity_column, sort=False)\n    for column in columns:\n        result[column] = result[column] - result[column].mean()",
         repo=[U + "::TestWithinBetweenTransforms::test_within_has_zero_mean_per_entity"],
         note="within -> плоское центрирование (общее среднее вместо среднего сущности)"),
    # panel.py -- fingerprint
    dict(id="MP-A04", file=PANEL, old="    canonical = canonical.sort_values([entity_column, date_column], kind=\"mergesort\")",
         new="    pass  # canonical не сортируется",
         repo=[U + "::TestPanelFingerprint"], note="fingerprint зависит от порядка строк"),
    # panel.py -- гейты и капы
    dict(id="MP-A06", file=PANEL, old="MIN_ENTITIES_FE_RE = 5", new="MIN_ENTITIES_FE_RE = 1",
         repo=[TP + "::test_fe_re_gates_fail_on_small_panel"], note="гейт сущностей ослаблен 5->1"),
    dict(id="MP-A07", file=PANEL, old="MIN_T_PER_ENTITY_FE_RE = 10", new="MIN_T_PER_ENTITY_FE_RE = 1",
         repo=[TP + "::test_fe_re_gates_fail_on_small_panel"], note="гейт длины ослаблен 10->1"),
    dict(id="MP-A08", file=PANEL, old="    if frame.balance != BALANCED:", new="    if False and frame.balance != BALANCED:",
         repo=[TP + "::test_panel_var_requires_balance"], note="PVAR снимает гейт сбалансированности"),
    dict(id="MP-A09", file=PANEL, old="PANEL_VAR_RECOMMENDED_BASE = 3", new="PANEL_VAR_RECOMMENDED_BASE = 2",
         repo=[], note="warning VAR(2) никогда не срабатывает"),
    dict(id="MP-A10", file=PANEL, old="CAPACITY_WARN_ENTITIES = 200", new="CAPACITY_WARN_ENTITIES = 10**9",
         repo=[TP + "::test_capacity_warning_above_200_entities"], note="warning-кап снят"),
    dict(id="MP-A11", file=PANEL, old="CAPACITY_REFUSE_ENTITIES = 2000", new="CAPACITY_REFUSE_ENTITIES = 10**9",
         repo=[], note="жёсткий кап снят (риск OOM)"),
    # session_store.py
    dict(id="MS-01", file=STORE, old="        if not self.target_column:\n            raise ValueError(\"Для панельного паспорта не выбрана target_column\")",
         new="        if False and not self.target_column:\n            raise ValueError(\"Для панельного паспорта не выбрана target_column\")",
         repo=[A + "::TestPanelEntryCheckpointStorage::test_requires_target_column"],
         note="снимок панели возможен без target_column"),
    dict(id="MS-02", file=STORE,
         old="        stored_snapshot = self.panel_passport_snapshot(snapshot.snapshot_id)\n        if stored_snapshot is None:",
         new="        stored_snapshot = self.panel_passport_snapshot(snapshot.snapshot_id)\n        if False and stored_snapshot is None:",
         repo=[], note="checkpoint ссылается на чужой снимок (панельный метод)"),
    dict(id="MS-03", file=STORE,
         old="        return next(\n            (item for item in reversed(self.panel_entry_checkpoints)\n             if item.stage == \"panel_entry\"),\n            None,\n        )",
         new="        return next(\n            (item for item in self.panel_entry_checkpoints\n             if item.stage == \"panel_entry\"),\n            None,\n        )",
         repo=[A + "::TestPanelEntryCheckpointStorage::test_append_only_history"],
         note="latest возвращает ПЕРВЫЙ checkpoint вместо последнего"),
    dict(id="MS-04", file=STORE, old="        self.panel_passport_history = []\n        self.panel_entry_checkpoints = []\n        self.eda_validation_strategy = {}",
         new="        self.eda_validation_strategy = {}",
         repo=[A + "::TestPanelEntryCheckpointStorage::test_reset_passports_clears_panel_universe"],
         note="reset_passports не чистит панельную вселенную"),
    dict(id="MS-05", file=STORE, old="        # PANEL-MODELS-3a: новый датасет = новая панельная вселенная.\n        self.panel_passport_history = []\n        self.panel_entry_checkpoints = []",
         new="        # PANEL-MODELS-3a: новый датасет = новая панельная вселенная.",
         repo=[], note="set_dataset не чистит панельную вселенную"),
    dict(id="MS-06", file=STORE, old="        \"panel_passport_history\": [asdict(item) for item in session.panel_passport_history],",
         new="        \"panel_passport_history\": [],",
         repo=[A + "::TestPanelEntryCheckpointStorage::test_serialization_roundtrip"],
         note="панельная история не сериализуется"),
    dict(id="MS-07", file=STORE, old="            for item in d.get(\"panel_passport_history\", []) or []",
         new="            for item in d[\"panel_passport_history\"]",
         repo=[A + "::TestPanelEntryCheckpointStorage::test_legacy_document_backcompat"],
         note="backcompat-дефолт удалён (KeyError на старых документах)"),
    # modeling_workflow.py
    dict(id="MW-01", file=WORKFLOW,
         old="    checkpoint = session.latest_panel_entry_checkpoint()\n    if checkpoint is None:\n        raise ValueError(",
         new="    checkpoint = session.latest_panel_entry_checkpoint()\n    if False and checkpoint is None:\n        raise ValueError(",
         repo=[A + "::TestPanelModelingContextGate::test_requires_confirmed_checkpoint"],
         note="гейт подтверждённого checkpoint снят"),
    dict(id="MW-02", file=WORKFLOW,
         old="    except PanelContractError as error:\n        raise ValueError(f\"Панель не проходит контракт: {error}\") from error\n    if fingerprint != checkpoint.fingerprint:",
         new="    except PanelContractError as error:\n        raise ValueError(f\"Панель не проходит контракт: {error}\") from error\n    if False and fingerprint != checkpoint.fingerprint:",
         repo=[A + "::TestPanelModelingContextGate::test_expired_on_data_change"],
         note="fingerprint-истечение отключено"),
    dict(id="MW-03", file=WORKFLOW,
         old="    stored_columns = dict(passport.get(\"columns\") or {})\n    if stored_columns and stored_columns != requested_columns:",
         new="    stored_columns = dict(passport.get(\"columns\") or {})\n    if False and stored_columns and stored_columns != requested_columns:",
         repo=[A + "::TestPanelModelingContextGate::test_column_mismatch_rejected"],
         note="сверка состава колонок отключена"),
    dict(id="MW-04", file=WORKFLOW, old="        raise ValueError(f\"Панель не проходит контракт: {error}\") from error",
         new="        raise",
         repo=[], note="PanelContractError пробрасывается без честной обёртки"),
]

CONTROLS = [
    dict(id="CTL-01", file=PANEL, old="CONTRACT_VERSION = \"panel-contract-v1\"",
         new="CONTRACT_VERSION = \"panel-contract-v1\"  # cert no-op", note="комментарий-контроль"),
    dict(id="CTL-02", file=PANEL, old="\"\"\"Панельный контракт и паспорт панели (PANEL-MODELS-3a, спека",
         new="\"\"\"Панельный контракт и паспорт панели (PANEL-MODELS-3a, спека/контроль",
         note="docstring-контроль"),
    dict(id="CTL-03", file=STORE, old="PANEL_PASSPORT_STAGES = (\"panel_entry\",)",
         new="PANEL_PASSPORT_STAGES = (\"panel_entry\",)  # cert no-op", note="константа-контроль"),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_mutant(path: Path, old: str, new: str) -> None:
    data = path.read_text(encoding="utf-8")
    count = data.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: ожидано 1 вхождение, найдено {count}: {old[:60]!r}")
    path.write_text(data.replace(old, new, 1), encoding="utf-8")


def run_repo(node_ids: list[str]) -> tuple[bool, str]:
    if not node_ids:
        return True, "n/a"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *node_ids, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": ".",
             "HOME": "/home/z", "VIRTUAL_ENV": "/home/z/.venv", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    tail = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode == 0, tail[-1] if tail else ""


def run_oracle() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(ORACLE)], cwd=REPO, capture_output=True, text=True, timeout=900,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": ".",
             "HOME": "/home/z", "VIRTUAL_ENV": "/home/z/.venv", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("TOTAL=")]
    return result.returncode == 0, lines[-1] if lines else result.stdout[-200:]


def main() -> int:
    only = set(sys.argv[1:])
    targets = [m for m in (CONTROLS + MUTANTS) if not only or m["id"] in only]
    print(f"mutants={len(MUTANTS)} controls={len(CONTROLS)} selected={len(targets)}")
    report: list[str] = []
    killed = dual = alive_controls = 0
    for mutant in targets:
        path = REPO / mutant["file"]
        original_bytes = path.read_bytes()
        passport = md5(path)
        try:
            apply_mutant(path, mutant["old"], mutant["new"])
            repo_ok, repo_tail = run_repo(mutant.get("repo", []))
            oracle_ok, oracle_tail = run_oracle()
            status = ("KILLED-DUAL" if (not repo_ok and not oracle_ok)
                      else "KILLED-REPO" if not repo_ok
                      else "KILLED-ORACLE" if not oracle_ok
                      else "ALIVE")
            restored = False
        finally:
            # побайтовое восстановление
            path.write_bytes(original_bytes)
            restored = md5(path) == passport
        if not restored:
            report.append(f"{mutant['id']}: RESTORE-FAIL -- файл не восстановлен!")
            print(report[-1])
            return 2
        if mutant["id"].startswith("CTL"):
            if status == "ALIVE":
                alive_controls += 1
            print(f"{mutant['id']}: {status} (control, ожидался ALIVE) | repo={repo_tail[:60]} | oracle={oracle_tail}")
            report.append(f"{mutant['id']}: {status} | {mutant['note']} | repo={repo_tail} | oracle={oracle_tail}")
            continue
        if status != "ALIVE":
            killed += 1
            dual += status == "KILLED-DUAL"
        print(f"{mutant['id']}: {status} | {mutant['note']} | repo={repo_tail[:70]} | oracle={oracle_tail}")
        report.append(f"{mutant['id']}: {status} | {mutant['note']} | repo={repo_tail} | oracle={oracle_tail}")
    with open(CERT / "mutations_protocol.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(report) + "\n")
    print(f"\nKILLED={killed} (DUAL={dual}) ALIVE_CONTROLS={alive_controls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
