# scripts/pgv02cert/mutations.py
"""Каталог мутационной кампании PGV-02-CERT («мутанты на своих мутантах»).

Каждый боевой мутант -- ровно одно поведенческое изменение поставки
PGV-02 (якорь обязан быть УНИКАЛЬНЫМ в файле, MV1). Ожидания
пре-регистрированы ДО прогона; эволюция ожиданий в ходе кампании
фиксируется в акте (прецедент PGV-00/01-CERT).

Каналы:
  REPO    = tests/api/test_pgv02_durable_inputs.py (+ пины миграций
            doclog4/5/6/8) -- корпус исполнителя;
  ORACLE  = Class A корпуса сертификатора (89 оракулов; Class B
            исключён -- он RED на цели по дизайну и не даёт осмысленных
            киллов).

Классификация: DUAL-KILLED / REPO-ONLY / ORACLE-ONLY / SURVIVED
(боевой выживший -- находка покрытия) / EQUIVALENT (с обоснованием).
Контроли K01-K03 -- no-op, обязаны остаться ALIVE.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    mid: str
    file: str
    anchor: str
    replacement: str
    expectation: str  # DUAL | REPO-ONLY | ORACLE-ONLY | SURVIVED | CONTROL
    note: str = ""


REPO_NODES = [
    "tests/api/test_pgv02_durable_inputs.py",
    "tests/api/test_doclog4_document_delivery.py::TestOpsWiringAndMigration",
    "tests/api/test_doclog5_formats_worker.py::TestMigration0011",
    "tests/api/test_doclog6_approvals_archive.py::TestMigration0012",
    "tests/api/test_doclog8_monitoring.py::TestStaticCatalogs::test_migration_catalog_counts",
]

ORACLE_NODES = [
    "scripts/pgv02cert/test_p2cert_oracle_unit.py",
    "scripts/pgv02cert/test_p2cert_oracle_api.py",
    "scripts/pgv02cert/test_p2cert_oracle_static.py",
]

MUTANTS: list[Mutant] = [
    # ── apps/api/visual_artifacts.py ─────────────────────────────────
    Mutant(
        "M01", "apps/api/visual_artifacts.py",
        '"visual_result": PRINT_RESULT_SCHEMA_VERSION,',
        '"visual_result": PRINT_SNAPSHOT_SCHEMA_VERSION,',
        "DUAL",
        "перепутанные версии схем visual_result/snapshot",
    ),
    Mutant(
        "M02", "apps/api/visual_artifacts.py",
        'CHECKPOINT_STAGES = ("modeling_entry", "panel_entry")',
        'CHECKPOINT_STAGES = ("modeling_entry",)',
        "DUAL",
        "panel_entry выпал из каталога стадий (AC14)",
    ),
    Mutant(
        "M03", "apps/api/visual_artifacts.py",
        "    if unchanged and not reused:\n"
        "        out.append(\n"
        "            _violation(\n"
        '                "conflicting_flags",\n'
        '                "flags.unchanged",\n'
        '                "unchanged подразумевает reused исходного снимка",\n'
        "            )\n"
        "        )\n",
        "    if False and unchanged and not reused:  # P2C-M03\n"
        "        pass\n",
        "DUAL",
        "AC11: unchanged без reused разрешён (позиционный маркер вместо "
        "пустой замены -- урок PGV-00-CERT)",
    ),
    Mutant(
        "M04", "apps/api/visual_artifacts.py",
        '_CHECKPOINT_ID_PATTERN = re.compile(r"^pck-[0-9a-zA-Z][0-9a-zA-Z_.:-]{0,127}$")',
        '_CHECKPOINT_ID_PATTERN = re.compile(r"^p[0-9a-zA-Z_.:-]{0,127}$")',
        "DUAL",
        "ослабление формата checkpoint_id (идемпотентность §8)",
    ),
    Mutant(
        "M05", "apps/api/visual_artifacts.py",
        "    if expected_context_id is not None and run.context_id != expected_context_id:",
        "    if expected_context_id is not None and run.context_id == expected_context_id:",
        "DUAL",
        "инверсия CAS по context_id (AC07)",
    ),
    Mutant(
        "M06", "apps/api/visual_artifacts.py",
        "    if expected_data_revision is not None and run.data_revision != expected_data_revision:\n"
        "        raise PrintContextConflict(\n"
        '            f"{source}: data_revision изменилась "\n'
        '            f"(ожидалась {expected_data_revision!r}, текущая {run.data_revision!r}) -- "\n'
        '            "409 context_changed"\n'
        "        )\n",
        "    if False and expected_data_revision is not None:  # P2C-M06\n"
        "        pass\n",
        "ORACLE-ONLY",
        "CAS по ревизии снят -- repo-канал пинует только context_id",
    ),
    Mutant(
        "M07", "apps/api/visual_artifacts.py",
        "    elif isinstance(raw_revision, str) and raw_revision.strip().isdigit():",
        "    elif isinstance(raw_revision, str) and raw_revision.strip().isalpha():",
        "ORACLE-ONLY",
        "числовая строка ревизии перестаёт сверяться (a13)",
    ),
    Mutant(
        "M08", "apps/api/visual_artifacts.py",
        '            reason=f"print_snapshot:{artifact.artifact_id}",',
        '            reason=f"print_snapshot:unlinked:{artifact.artifact_id}",',
        "ORACLE-ONLY",
        "точная причина пина зависимости нарушена (§16); repo пинует "
        "подстроку id, не шаблон",
    ),
    Mutant(
        "M09", "apps/api/visual_artifacts.py",
        "    artifacts = get_artifact_registry().list_artifacts(run_id, kind=\"visual_result\")\n"
        "    if view_id is None:\n"
        "        return artifacts\n"
        "    return [a for a in artifacts if a.refs.get(\"view_id\") == view_id]",
        "    artifacts = get_artifact_registry().list_artifacts(run_id, kind=\"visual_result\")\n"
        "    return artifacts",
        "ORACLE-ONLY",
        "фильтр list_visual_results по view_id снят (a21)",
    ),
    Mutant(
        "M10", "apps/api/visual_artifacts.py",
        "    for artifact in get_artifact_registry().list_artifacts(run_id, kind=\"passport_checkpoint\"):\n"
        "        if artifact.refs.get(\"checkpoint_id\") == checkpoint_id:\n"
        "            return artifact\n"
        "    return None",
        "    for artifact in get_artifact_registry().list_artifacts(run_id, kind=\"passport_checkpoint\"):\n"
        "        return artifact\n"
        "    return None",
        "ORACLE-ONLY",
        "get_passport_checkpoint игнорирует id -- фабкация чужого факта (a21)",
    ),
    # ── apps/api/artifact_promotion.py ───────────────────────────────
    Mutant(
        "M11", "apps/api/artifact_promotion.py",
        "        violations = validate_visual_artifact_payload(kind, payload)\n"
        "        if violations:\n"
        "            raise ArtifactPayloadInvalid(violations)\n",
        "        violations: list = []  # P2C-M11: гейт снят\n"
        "        if False and violations:\n"
        "            raise ArtifactPayloadInvalid(violations)\n",
        "DUAL",
        "валидационный гейт снят -- невалидный payload регистрируется",
    ),
    Mutant(
        "M12", "apps/api/artifact_promotion.py",
        "            if existing.payload_sha256 != artifact_content_sha256(content):\n"
        "                raise ArtifactConflictError(\n"
        "                    \"Тот же producer_key с другим payload -- 409 (§11: \"\n"
        "                    \"иной payload с прежним idempotency-ключом конфликтует)\"\n"
        "                )\n",
        "            if False:  # P2C-M12: сверка снята\n"
        "                raise ArtifactConflictError(\"disabled\")\n",
        "DUAL",
        "контентная сверка §11 снята -- подмена маскируется",
    ),
    Mutant(
        "M13", "apps/api/artifact_promotion.py",
        "            schema_version=schema_version or ARTIFACT_SCHEMA_VERSION_DEFAULT,",
        "            schema_version=ARTIFACT_SCHEMA_VERSION_DEFAULT,",
        "ORACLE-ONLY",
        "per-kind schema_version потерян -- repo пинует словарь, не артефакт",
    ),
    # ── apps/api/report_snapshot.py ──────────────────────────────────
    Mutant(
        "M14", "apps/api/report_snapshot.py",
        '    "P02": ("passport_comparison", "Сравнение паспортов"),',
        '    "P02": ("passport_compare", "Сравнение паспортов"),',
        "DUAL",
        "kind-имя P02 искажено (§10.2)",
    ),
    Mutant(
        "M15", "apps/api/report_snapshot.py",
        "            print_hint = \"\"\n"
        "            if str(item) in PRINT_DOCUMENT_KIND_CODES:\n"
        "                print_hint = (\n"
        "                    f\"; {item!r} -- печатный тип (PGV-02, каталог \"\n"
        "                    f\"{DOCUMENT_CATALOG_VERSION}): его ревизии создаются \"\n"
        "                    \"печатным потоком документации, а не секциями отчёта\"\n"
        "                )\n",
        "            print_hint = \"\"\n",
        "ORACLE-ONLY",
        "подсказка resolve_kinds ослеплена -- repo пинует только отказ",
    ),
    Mutant(
        "M16", "apps/api/report_snapshot.py",
        '        return "print_document"',
        '        return "print"',
        "DUAL",
        "семейство document_kind_family искажено",
    ),
    # ── apps/api/document_jobs.py ────────────────────────────────────
    Mutant(
        "M17", "apps/api/document_jobs.py",
        '    return _new_id("dprint-")',
        '    return _new_id("drev-")  # P2C-M17',
        "ORACLE-ONLY",
        "префикс печатных ревизий столкнут со snapshot-ревизиями",
    ),
    Mutant(
        "M18", "apps/api/document_jobs.py",
        "                    \"basis_artifact_ids\": basis_ids,\n"
        "                    \"snapshot_id\": snapshot_id,\n"
        "                    \"profile_id\": profile_id,\n",
        "                    \"basis_artifact_ids\": basis_ids,\n"
        "                    \"snapshot_id\": snapshot_id,\n",
        "DUAL",
        "profile_id вне basis_fingerprint -- смена профиля не создаёт версию",
    ),
    Mutant(
        "M19", "apps/api/document_jobs.py",
        "        with self._lock:\n"
        "            self._print_revisions[revision.print_revision_id] = revision.copy()\n"
        "            document = self._documents.get(revision.document_id)\n"
        "            if document is not None:\n"
        "                document.current_revision_id = revision.print_revision_id\n"
        "            return revision.copy()",
        "        with self._lock:\n"
        "            self._print_revisions[revision.print_revision_id] = revision.copy()\n"
        "            return revision.copy()",
        "SURVIVED",
        "указатель current_revision_id не обновляется -- пинуют ли это "
        "корпуса? (пре-регистрация выжившего: проверка класса)",
    ),
    Mutant(
        "M20", "apps/api/document_jobs.py",
        "        revisions = self.registry.list_print_revisions(document.document_id)\n"
        "        version_no = (revisions[-1].version_no + 1) if revisions else 1",
        "        revisions = self.registry.list_print_revisions(document.document_id)\n"
        "        version_no = 1",
        "ORACLE-ONLY",
        "монотонность version_no нарушена -- repo пинует только v1/v2 профиля",
    ),
    Mutant(
        "M21", "apps/api/document_jobs.py",
        "        self._authorized_run(run_id, subject, session_id=session_id, action=\"read\")\n"
        "        documents = []\n"
        "        for code in codes:\n"
        "            document = self.registry.find_document_by_kind(run_id, code)",
        "        documents = []\n"
        "        for code in codes:\n"
        "            document = self.registry.find_document_by_kind(run_id, code)",
        "ORACLE-ONLY",
        "авторизация list_print_documents снята -- чужое чтение (a29)",
    ),
    Mutant(
        "M22", "apps/api/document_jobs.py",
        '                reason=f"print_revision:{revision.print_revision_id}",',
        '                reason=f"print_revision:shifted:{revision.print_revision_id}",',
        "ORACLE-ONLY",
        "причина пина basis искажена -- repo пинует подстроку id",
    ),
    # ── apps/api/research_runs.py ────────────────────────────────────
    Mutant(
        "M23", "apps/api/research_runs.py",
        "        UNIQUE (document_id, version_no),\n"
        "        UNIQUE (document_id, basis_fingerprint)\n",
        "        UNIQUE (document_id, version_no)\n",
        "DUAL",
        "UNIQUE(document_id, basis_fingerprint) выпал из DDL 0016",
    ),
    Mutant(
        "M24", "apps/api/research_runs.py",
        "    + MIGRATION_STATEMENTS_0015 + MIGRATION_STATEMENTS_0016\n",
        "    + MIGRATION_STATEMENTS_0015\n",
        "DUAL",
        "0016 выпала из конкатенации -- счётчик 96→93",
    ),
    # ── 2-й порядок (композиции из разных функций) ───────────────────
    Mutant(
        "S1", "apps/api/visual_artifacts.py",
        "    if expected_context_id is not None and run.context_id != expected_context_id:",
        "    if expected_context_id is not None and run.context_id == expected_context_id:",
        "DUAL",
        "2-й порядок: M05 (инверсия CAS) + M11 (гейт снят) -- каскад "
        "маскировки: конфликт мимо гейта",
    ),
    Mutant(
        "S2", "apps/api/report_snapshot.py",
        '    "V01": ("scientific_visual", "Научная визуализация"),',
        '    "V01": ("visual", "Научная визуализация"),',
        "DUAL",
        "2-й порядок: kind-имя V01 искажено вместе с каталогом лимитов",
    ),
    Mutant(
        "S3", "apps/api/document_jobs.py",
        "        existing = self.registry.find_print_revision_by_fingerprint(\n"
        "            document.document_id, fingerprint\n"
        "        )\n"
        "        if existing is not None:\n"
        "            return document, existing, False\n",
        "        existing = None  # P2C-S3: идемпотентный поиск снят\n"
        "        if False:\n"
        "            return document, existing, False\n",
        "DUAL",
        "2-й порядок: идемпотентный поиск снят + дубли версий",
    ),
    # ── No-op контроли (обязаны остаться ALIVE) ──────────────────────
    Mutant(
        "K01", "apps/api/visual_artifacts.py",
        "# ── Контракты версий схем durable inputs ─────",
        "# ── Контракты версий схем durable inputs ── (K01 no-op) ──",
        "CONTROL",
        "комментарий -- поведения нет",
    ),
    Mutant(
        "K02", "apps/api/artifact_promotion.py",
        '"""PGV-02 (spec_passport_graphics_visual.md §6/§8): запись',
        '"""PGV-02 (spec_passport_graphics_visual.md §6/§8, K02): запись',
        "CONTROL",
        "docstring -- поведения нет",
    ),
    Mutant(
        "K03", "apps/api/report_snapshot.py",
        "DOCUMENT_CATALOG_VERSION = \"pgv.document_catalog/2\"",
        "DOCUMENT_CATALOG_VERSION = \"pgv.document_catalog/2\"  # K03",
        "CONTROL",
        "хвостовой комментарий -- поведения нет",
    ),
]
