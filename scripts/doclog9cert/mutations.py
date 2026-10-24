# scripts/doclog9cert/mutations.py
"""DOCLOG-9-CERT: мутационная кампания «мутанты на своих мутантах».

Двухканальная схема (прецедент DOCLOG-7/8-CERT):
- REPO-канал: tests/api/test_doclog9_profiles.py + test_doclog5_formats_worker.py
  + test_doclog4_document_delivery.py (поверхность DOCLOG-9 + фундаментальные
  пины каталога форматов/доставки). Флакующий repo-тест pdfa-детерминизма
  ИСКЛЮЧЁН из канала (--deselect, см. F-D9C1: он зависит от границы
  wall-clock секунды и дал бы ложные киллы);
- ORACLE-канал: scripts/doclog9cert (71 оракул на своих данных).

Классификация: DUAL-KILLED / ORACLE-ONLY / REPO-ONLY / SURVIVED;
контроли C1–C3 (no-op) обязаны остаться ALIVE.
Мета-валидация: MV1 (сухой прогон якорей), MV2 (self-test классификатора),
MV3 (байт-в-байт восстановление после каждого мутанта), MV4 (контроли
ALIVE), MV5 (скан хвостов киллов на посторонние файлы).

«Мутанты на своих мутантах» (2-й порядок, HO-срез):
- SECOND_ORDER: композиции пар боевых мутантов из разных функций --
  обязаны остаться убитыми (детекция маскирования);
- ATTRIBUTION: для ORACLE-ONLY мутантов -- перепрогон ORACLE-канала
  без файла-киллера: мутант обязан ожить (килл атрибутирован конкретному
  оракулу, а не среде).

Запуск:  /home/z/.venv/bin/python -m scripts.doclog9cert.mutations dry
         /home/z/.venv/bin/python -m scripts.doclog9cert.mutations run
         /home/z/.venv/bin/python -m scripts.doclog9cert.mutations second
         /home/z/.venv/bin/python -m scripts.doclog9cert.mutations attr
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DP = "apps/api/doc_profiles.py"
RT = "apps/api/routers/doc_profiles.py"
DJ = "apps/api/document_jobs.py"
DR = "apps/api/document_renditions.py"
WK = "apps/api/document_render_worker.py"

REPO_TARGETS = [
    "tests/api/test_doclog9_profiles.py",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog4_document_delivery.py",
]
REPO_DESELECT = [
    "--deselect",
    "tests/api/test_doclog9_profiles.py::TestProfileFormatCatalog"
    "::test_pdfa_render_markers_and_determinism",
]
ORACLE_TARGETS = ["scripts/doclog9cert"]

PY = sys.executable

# ── Боевые мутанты и контроли ────────────────────────────────────────
# (id, файл, якорь, замена, описание)

MUTANTS: list[dict] = [
    # -- Валидаторы conformance (DP) --
    dict(id="M01", file=DP,
         find='    if b"GTS_PDFA1" not in content:\n'
              '        findings.append("outputintent_missing: GTS_PDFA1 OutputIntent отсутствует")',
         replace='    if False:\n'
                 '        findings.append("outputintent_missing: GTS_PDFA1 OutputIntent отсутствует")',
         desc="валидатор пропускает выпуск без GTS_PDFA1 OutputIntent"),
    dict(id="M02", file=DP,
         find='    if b"FontFile2" not in content:\n'
              '        findings.append("fonts_missing: встроенные шрифты (FontFile2) отсутствуют")',
         replace='    if False:\n'
                 '        findings.append("fonts_missing: встроенные шрифты (FontFile2) отсутствуют")',
         desc="валидатор пропускает выпуск без встроенных шрифтов"),
    dict(id="M03", file=DP,
         find="""        if b'TargetMode="External"' in data:""",
         replace="""        if False:""",
         desc="docx-валидатор пропускает внешние связи (AC16 off)"),
    # -- Подпись (DP) --
    dict(id="M04", file=DP,
         find="    if hmac.compare_digest(mac, expected):",
         replace="    if not hmac.compare_digest(mac, expected):",
         desc="результат сравнения MAC инвертирован"),
    dict(id="M05", file=DP,
         find='    digest_input = canonical.encode("utf-8") + b"\\x00" + content',
         replace='    digest_input = canonical.encode("utf-8")',
         desc="MAC не привязан к байтам содержимого (только метаданные)"),
    # -- Права/жизненный цикл профиля (DP) --
    dict(id="M06", file=DP,
         find='        if "policy.admin" not in scopes:\n'
              '            raise OrgProfileAccessDenied(',
         replace='        if False:\n'
                 '            raise OrgProfileAccessDenied(',
         desc="право policy.admin не проверяется (§15 off)"),
    dict(id="M07", file=DP,
         find="""        if subject is None or getattr(subject, "is_anonymous", True):
            raise OrgProfileNotFound("Контур профилей недоступен")
        role = (getattr(subject, "role", None) or "")
        if role == "admin":""",
         replace="""        role = (getattr(subject, "role", None) or "")
        if role == "admin":""",
         desc="анонимный гейт управления профилями снят (uniform-404 off)"),
    dict(id="M08", file=DP,
         find="""        if profile.status != PROFILE_ACTIVE:
            raise OrgProfileRetired(""",
         replace="""        if False:
            raise OrgProfileRetired(""",
         desc="retired-профиль резолвится как активный (policy off)"),
    dict(id="M09", file=DP,
         find="""        if profile.format != fmt:
            raise OrgProfileFormatMismatch(""",
         replace="""        if False:
            raise OrgProfileFormatMismatch(""",
         desc="формат профиля не сверяется с форматом рендера"),
    dict(id="M10", file=DP,
         find="""        duplicate = self.registry.find_duplicate(name, version_no)
        if duplicate is not None:""",
         replace="""        duplicate = self.registry.find_duplicate(name, version_no)
        if False:""",
         desc="дубль (name, version_no) допускается (UNIQUE off)"),
    dict(id="M11", file=DP,
         find="""        if profile.status == PROFILE_RETIRED:
            return profile  # идемпотентно (паритет cancel_job §17)""",
         replace="""        if False:
            return profile  # идемпотентно (паритет cancel_job §17)""",
         desc="повторный retire не идемпотентен (двойной audit)"),
    dict(id="M12", file=DP,
         find="""        self.registry.append_validation(record)
        self._audit(
            "rendition_validated",""",
         replace="""        if validation.result == "failed":
            self.registry.append_validation(record)
        self._audit(
            "rendition_validated",""",
         desc="passed-запись валидации НЕ пишется (§19-доказательство off)"),
    dict(id="M13", file=DP,
         find='                hold_reason=f"{WORM_REASON_PREFIX}:{profile.profile_id}",',
         replace="                hold_reason=WORM_REASON_PREFIX,",
         desc="WORM-причина теряет привязку к профилю"),
    dict(id="M14", file=DP,
         find="""        if not document_id:
            return False""",
         replace="""        if True:
            return False""",
         desc="WORM-холд никогда не ставится (§16 off)"),
    dict(id="M15", file=DP,
         find="""        record = (
            record_mandatory if requirement == "mandatory" else record_standard
        )""",
         replace="""        record = (
            record_standard if requirement == "mandatory" else record_mandatory
        )""",
         desc="класс аудита инвертирован (mandatory -> standard, fail-open)"),
    dict(id="M16", file=DP,
         find="""        if profile.validate_conformance:
            return validate_profile_output(content, fmt, profile)""",
         replace="""        if True:
            return validate_profile_output(content, fmt, profile)""",
         desc="переключатель политики validate_conformance игнорируется"),
    dict(id="M17", file=DP,
         find="""        if fmt:
            profiles = [p for p in profiles if p.format == fmt]""",
         replace="""        if False:
            profiles = [p for p in profiles if p.format == fmt]""",
         desc="фильтр списка профилей по формату отключён"),
    dict(id="M18", file=DP,
         find="        return sorted(profiles, key=lambda p: (p.name, p.version_no))",
         replace="        return profiles",
         desc="сортировка списка профилей снята"),
    dict(id="M19", file=DP,
         find='    return f"{prefix}-{uuid.uuid4().hex}"',
         replace='    return f"x{prefix}-{uuid.uuid4().hex}"',
         desc="префиксы идентификаторов искажены (prof-/val-/anchor-)"),
    # -- Роутер (RT) --
    dict(id="M20", file=RT,
         find="""    except OrgProfileNotFound:
        return JSONResponse(
            status_code=404, content={"detail": _PROFILES_NOT_FOUND_DETAIL}
        )""",
         replace="""    except OrgProfileNotFound:
        return JSONResponse(
            status_code=403, content={"detail": _PROFILES_NOT_FOUND_DETAIL}
        )""",
         desc="uniform 404 списка заменён на 403 (дисклоужение)"),
    dict(id="M21", file=RT,
         find='            status_code=409,\n'
              '            detail={"code": "org_profile_duplicate", "message": str(exc)},',
         replace='            status_code=422,\n'
                 '            detail={"code": "org_profile_duplicate", "message": str(exc)},',
         desc="конфликт дубля 409 -> 422 (каталог кодов сломан)"),
    dict(id="M22", file=RT,
         find="""        raise HTTPException(
            status_code=404,
            detail={
                "code": "org_profile_not_found",""",
         replace="""        raise HTTPException(
            status_code=422,
            detail={
                "code": "org_profile_not_found",""",
         desc="неизвестный профиль при retire 404 -> 422"),
    dict(id="M23", file=RT,
         find="""            status_code=410,
            content={
                "detail": {
                    "code": "purged_artifact",""",
         replace="""            status_code=404,
            content={
                "detail": {
                    "code": "purged_artifact",""",
         desc="tombstone 410 purged_artifact -> 404 (честность хранения off)"),
    dict(id="M24", file=RT,
         find="    record = signature_records[-1]",
         replace="    record = signature_records[0]",
         desc="верификация берёт ПЕРВУЮ подпись вместо последней"),
    # -- Заказ рендера/готовность (DJ) --
    dict(id="M25", file=DJ,
         find="""            if not org_profile_id:
                raise _dp.OrgProfileRequired(""",
         replace="""            if False:
                raise _dp.OrgProfileRequired(""",
         desc="безымянный выпуск docx/pdfa разрешён (§19 off)"),
    dict(id="M26", file=DJ,
         find="""            if format not in _dp.PROFILE_FORMATS:
                raise _dp.OrgProfileFormatMismatch(""",
         replace="""            if False:
                raise _dp.OrgProfileFormatMismatch(""",
         desc="профиль применим к любому формату (каталог off)"),
    dict(id="M27", file=DJ,
         find="""            profile_service.resolve_profile(
                org_profile_id, fmt=format, subject=subject
            )  # NotFound/Retired/FormatMismatch -- честные ошибки сервисного слоя""",
         replace="""            pass  # resolve-at-request отключён""",
         desc="resolve профиля на постановке отключён (404/409 позже)"),
    dict(id="M28", file=DJ,
         find="""            if org_profile_id and existing.org_profile_id != org_profile_id:""",
         replace="""            if False:""",
         desc="mismatch готовой цели отключён (вторая визуальная форма)"),
    dict(id="M29", file=DJ,
         find="""            if org_profile_id and active.org_profile_id != org_profile_id:""",
         replace="""            if False:""",
         desc="mismatch активного задания отключён"),
    dict(id="M30", file=DJ,
         find="""            if validation.result != "passed":""",
         replace="""            if False:""",
         desc="failed-валидация не останавливает выпуск (AC08 off)"),
    dict(id="M31", file=DJ,
         find="""                profile_service.record_validation(
                    profile,
                    validation=validation,""",
         replace="""                if False: profile_service.record_validation(
                    profile,
                    validation=validation,""",
         desc="failed-запись валидации не пишется (доказательство off)"),
    dict(id="M32", file=DJ,
         find="""            if signature_manifest is not None:
                profile_service.record_signature(""",
         replace="""            if False:
                profile_service.record_signature(""",
         desc="манифест подписи не персистится (verify всегда not_signed)"),
    dict(id="M33", file=DJ,
         find="""                except _dp.SignatureKeyUnavailable:
                    # Честный отказ (AC12-дух): тихая неподписанная
                    # ready запрещена.
                    return (
                        self.fail_render(job, "sign_key_unavailable"),
                        None,
                    )""",
         replace="""                except _dp.SignatureKeyUnavailable:
                    signature_manifest = None""",
         desc="отсутствие ключа подписи -- тихий неподписанный ready"),
    dict(id="M34", file=DJ,
         find="""            if profile.anchor_registry:
                profile_service.record_anchor(""",
         replace="""            if False:
                profile_service.record_anchor(""",
         desc="append-only якорь не пишется (§16 off)"),
    dict(id="M35", file=DJ,
         find="""            if profile.worm_lock:
                revision = (""",
         replace="""            if False:
                revision = (""",
         desc="WORM-холд не ставится при выпуске (§16 off)"),
    dict(id="M36", file=DJ,
         find="""            org_profile_id=job.org_profile_id,
            content_bytes=(""",
         replace="""            org_profile_id="",
            content_bytes=(""",
         desc="профиль не фиксируется в metadata rendition"),
    dict(id="M37", file=DJ,
         find="""            profile_service.record_validation(
                profile,
                validation=passed_validation,""",
         replace="""            if False:
                profile_service.record_validation(
                    profile,
                    validation=passed_validation,""",
         desc="passed-доказательство готового выпуска не пишется (§19 off)"),
    # -- Рендеры (DR) --
    dict(id="M38", file=DR,
         find="""def _docx_escape(value: Any) -> str:
    \"\"\"Недоверенный текст -> безопасный XML-текст OOXML (AC16).\"\"\"
    return _html.escape(str(value if value is not None else ""), quote=True)""",
         replace="""def _docx_escape(value: Any) -> str:
    \"\"\"Недоверенный текст -> безопасный XML-текст OOXML (AC16).\"\"\"
    return str(value if value is not None else "")""",
         desc="экранирование недоверенного текста в DOCX снято (AC16 off)"),
    dict(id="M39", file=DR,
         find='    heading_title = f"{title_prefix} · Документ исследования" if title_prefix else "Документ исследования"',
         replace='    heading_title = "Документ исследования"',
         desc="оформление профиля (гриф) не входит в байты DOCX"),
    dict(id="M40", file=DR,
         find="""    base = render_snapshot_pdf(snapshot)
    return _pdfa_postprocess(base, snapshot, profile)""",
         replace="""    return render_snapshot_pdf(snapshot)""",
         desc="pdfa -- переименованный обычный PDF без XMP/OutputIntent (§7 P2 off)"),
    dict(id="M41", file=DR,
         find='    root[NameObject("/OutputIntents")] = ArrayObject([intent_ref])',
         replace='    root[NameObject("/OutputIntents")] = ArrayObject([])',
         desc="OutputIntent отвязан от каталога PDF (структурно, не текстуально)"),
    dict(id="M42", file=DR,
         find="""HEAVY_RENDITION_FORMATS = frozenset(
    {"pdf", "xlsx", "parquet", "svg", "png", "zip", "docx", "pdfa"}
)""",
         replace="""HEAVY_RENDITION_FORMATS = frozenset(
    {"pdf", "xlsx", "parquet", "svg", "png", "zip"}
)""",
         desc="docx/pdfa перестают быть тяжёлыми (async-контур off)"),
    dict(id="M43", file=DR,
         find="_DOCX_FIXED_DATE_TIME = (2026, 1, 1, 0, 0, 0)",
         replace="_DOCX_FIXED_DATE_TIME = (2027, 5, 6, 7, 8, 9)",
         desc="фиксированные даты DOCX подменены (пин AC03 статикой)"),
    # -- Worker (WK) --
    dict(id="M44", file=WK,
         find="""            if (
                profile is None
                or profile.status != _dp.PROFILE_ACTIVE
                or profile.format != claimed.format
            ):""",
         replace="""            if False:""",
         desc="policy-перепроверка профиля на исполнении снята (retire между)"),
    dict(id="M45", file=WK,
         find='''                return self._fail_or_requeue(
                    claimed, "org_profile_unavailable"
                )''',
         replace='''                return self._fail_or_requeue(
                    claimed, "snapshot_unavailable"
                )''',
         desc="код ошибки unavailable профиля подменён чужим кодом"),
    # -- Контроли (no-op, обязаны остаться ALIVE) --
    dict(id="C1", file=DP, control=True,
         find="PROFILE_FORMATS = frozenset({\"docx\", \"pdfa\"})",
         replace="PROFILE_FORMATS = frozenset({\"docx\", \"pdfa\"})  # d9cert control",
         desc="контроль: хвостовой комментарий каталога"),
    dict(id="C2", file=RT, control=True,
         find="router = APIRouter()",
         replace="router = APIRouter()  # d9cert no-op control",
         desc="контроль: хвостовой комментарий роутера"),
    dict(id="C3", file=DR, control=True,
         find="_DOCX_FIXED_DATE_TIME = (2026, 1, 1, 0, 0, 0)",
         replace="_DOCX_FIXED_DATE_TIME = (2026, 1, 1, 0, 0, 0)  # d9cert control",
         desc="контроль: хвостовой комментарий константы"),
]

# «Мутанты на своих мутантах»: композиции 2-го порядка (пары боевых
# мутантов из РАЗНЫХ функций) -- обязаны остаться убитыми (маскирования
# нет). Формат: (id, [идентификаторы мутантов 1-го порядка]).

SECOND_ORDER: list[dict] = [
    dict(id="H01", parts=["M01", "M02"],
         desc="два маркера pdfa-валидатора сняты одновременно"),
    dict(id="H02", parts=["M04", "M05"],
         desc="подпись: инверсия сравнения + отвязка байтов"),
    dict(id="H03", parts=["M25", "M27"],
         desc="гейт обязательности профиля + resolve на постановке"),
    dict(id="H04", parts=["M38", "M39"],
         desc="DOCX: экранирование + гриф профиля сняты вместе"),
    dict(id="H05", parts=["M32", "M34"],
         desc="манифест подписи + якорь не пишутся вместе"),
    dict(id="H06", parts=["M08", "M28"],
         desc="retired-резолв + mismatch готовой цели"),
]

# Атрибуция киллов ORACLE-ONLY: перепрогон ORACLE-канала БЕЗ одного
# файла-оракула -- мутант обязан ожить (килл пришёл именно оттуда).

ATTRIBUTION_ORACLE_FILES = {
    "unit": "scripts/doclog9cert/test_d9cert_oracle_unit.py",
    "api": "scripts/doclog9cert/test_d9cert_oracle_api.py",
    "static": "scripts/doclog9cert/test_d9cert_oracle_static.py",
}


def _apply(file_rel: str, find: str, replace: str) -> None:
    path = REPO_ROOT / file_rel
    source = path.read_text("utf-8")
    assert source.count(find) == 1, f"anchor not unique in {file_rel}"
    path.write_text(source.replace(find, replace, 1), "utf-8")


def _apply_many(pairs: list[tuple[str, str, str]]) -> None:
    for file_rel, find, replace in pairs:
        _apply(file_rel, find, replace)


def mutant_by_id(mid: str) -> dict:
    for mutant in MUTANTS:
        if mutant["id"] == mid:
            return mutant
    raise KeyError(mid)


def _md5(file_rel: str) -> str:
    return hashlib.md5((REPO_ROOT / file_rel).read_bytes()).hexdigest()


def _run_channel(targets: list[str], timeout: int = 900,
                 extra: list[str] | None = None) -> dict:
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           *targets, *(extra or [])]
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=timeout)
    return {
        "cmd": " ".join(cmd),
        "exit": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "tail": "\n".join(proc.stdout.strip().splitlines()[-12:]),
        "stdout": proc.stdout,
    }


def run_repo() -> dict:
    return _run_channel(REPO_TARGETS, extra=REPO_DESELECT)


def run_oracle(skip: list[str] | None = None) -> dict:
    targets = [t for t in ORACLE_TARGETS if t not in (skip or [])]
    return _run_channel(targets)


def classify(repo: dict, oracle: dict) -> str:
    repo_killed = repo["exit"] != 0
    oracle_killed = oracle["exit"] != 0
    if repo_killed and oracle_killed:
        return "DUAL-KILLED"
    if oracle_killed:
        return "ORACLE-ONLY"
    if repo_killed:
        return "REPO-ONLY"
    return "SURVIVED"


def mv1_dry_run(entries: list[dict] | None = None) -> list[str]:
    """MV1: каждый якорь встречается в своём файле РОВНО один раз."""
    problems: list[str] = []
    for mutant in entries if entries is not None else MUTANTS:
        source = (REPO_ROOT / mutant["file"]).read_text("utf-8")
        count = source.count(mutant["find"])
        if count != 1:
            problems.append(
                f"{mutant['id']}: anchor count {count} in {mutant['file']}"
            )
    return problems


def self_test_classifier() -> bool:
    """MV2: классификатор сверен с синтетикой."""
    cases = [
        ({"exit": 1}, {"exit": 1}, "DUAL-KILLED"),
        ({"exit": 0}, {"exit": 1}, "ORACLE-ONLY"),
        ({"exit": 1}, {"exit": 0}, "REPO-ONLY"),
        ({"exit": 0}, {"exit": 0}, "SURVIVED"),
    ]
    for repo, oracle, expected in cases:
        if classify(repo, oracle) != expected:
            return False
    return True


def _protocols_dir() -> Path:
    d = Path(__file__).resolve().parent / "protocols"
    d.mkdir(exist_ok=True)
    return d


def run_campaign(only: list[str] | None = None) -> dict:
    started = time.time()
    baseline_files = {m["file"] for m in MUTANTS}
    # GUARD: продуктовые файлы обязаны быть чистыми vs HEAD перед
    # стартом порции (урок: убитый посреди apply процесс оставляет
    # мутанта в дереве -- база была бы грязной, MV3 врал бы).
    dirty = subprocess.run(
        ["git", "status", "--porcelain", *sorted(baseline_files)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(
            "GUARD: продуктовые файлы НЕ чисты vs HEAD -- восстановите "
            f"дерево (git checkout --) перед кампанией:\n{dirty}"
        )
    baseline_md5 = {f: _md5(f) for f in sorted(baseline_files)}
    summary: list[dict] = []
    protocols = _protocols_dir()

    for mutant in MUTANTS:
        mid = mutant["id"]
        if only and mid not in only:
            continue
        entry = {
            "id": mid,
            "file": mutant["file"],
            "desc": mutant["desc"],
            "control": bool(mutant.get("control")),
        }
        try:
            _apply(mutant["file"], mutant["find"], mutant["replace"])
        except AssertionError as exc:
            entry.update(status="PATCH-FAIL", error=str(exc))
            summary.append(entry)
            print(f"[{mid}] PATCH-FAIL: {exc}")
            continue
        try:
            repo = run_repo()
            oracle = run_oracle()
        finally:
            # MV3: байт-в-байт восстановление из HEAD (git checkout --).
            subprocess.run(["git", "checkout", "--", mutant["file"]],
                           cwd=REPO_ROOT, capture_output=True, text=True)
            restored = _md5(mutant["file"])
            entry["restore_ok"] = restored == baseline_md5[mutant["file"]]
        entry["repo_exit"] = repo["exit"]
        entry["oracle_exit"] = oracle["exit"]
        entry["repo_seconds"] = repo["seconds"]
        entry["oracle_seconds"] = oracle["seconds"]
        entry["repo_tail"] = repo["tail"]
        entry["oracle_tail"] = oracle["tail"]
        if mutant.get("control"):
            entry["status"] = "ALIVE" if (repo["exit"] == 0
                                          and oracle["exit"] == 0) \
                else "CONTROL-KILLED"
        else:
            entry["status"] = classify(repo, oracle)
        summary.append(entry)
        print(f"[{mid}] {entry['status']} "
              f"(repo {repo['exit']}, oracle {oracle['exit']}) "
              f"{mutant['desc']}")
        (protocols / f"mut_{mid}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), "utf-8"
        )

    # Слияние с предыдущими порциями (среда обрывает долгие процессы --
    # кампания гоняется порционно; аккумулятор -- mutations_summary.json).
    prev_path = protocols / "mutations_summary.json"
    if prev_path.exists() and only:
        try:
            prev = json.loads(prev_path.read_text("utf-8"))
            prev_by_id = {e["id"]: e for e in prev.get("mutants", [])}
            for entry in summary:
                prev_by_id[entry["id"]] = entry
            merged = [
                prev_by_id[m["id"]] for m in MUTANTS
                if m["id"] in prev_by_id
            ]
            summary = merged
        except Exception:  # noqa: BLE001 -- битый аккумулятор игнорируем
            pass

    # MV5: скан хвостов киллов на посторонние файлы (ложные киллы).
    channel_files = {
        "repo": {Path(p).name for p in REPO_TARGETS},
        "oracle": {Path(p).name for p in ORACLE_TARGETS}
        | {"conftest.py", "test_d9cert_oracle_unit.py",
           "test_d9cert_oracle_api.py", "test_d9cert_oracle_static.py"},
    }
    tail_scan = []
    for entry in summary:
        if entry.get("control") or entry["status"] in ("ALIVE",
                                                       "PATCH-FAIL"):
            continue
        for channel in ("repo", "oracle"):
            tail = entry.get(f"{channel}_tail", "")
            for line in tail.splitlines():
                if ((line.startswith("FAILED") or line.startswith("ERROR"))
                        and "::" in line):
                    path_part = line.split()[1].split("::")[0]
                    fname = Path(path_part).name
                    if fname not in channel_files[channel]:
                        tail_scan.append(
                            {"id": entry["id"], "channel": channel,
                             "foreign": fname}
                        )
    result = {
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.time() - started, 1),
        "mv2_classifier_self_test": self_test_classifier(),
        "mv3_all_restored": all(
            e.get("restore_ok", False) for e in summary
            if e.get("status") != "PATCH-FAIL"
        ),
        "mv5_foreign_tails": tail_scan,
        "mutants": summary,
    }
    (protocols / "mutations_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), "utf-8"
    )
    return result


def run_second_order() -> dict:
    """2-й порядок: пары мутантов применяются ОДНОВРЕМЕННО -- кампания
    обязана убить каждую композицию (нет маскирования)."""
    protocols = _protocols_dir()
    baseline_md5 = {f: _md5(f) for f in {m["file"] for m in MUTANTS}}
    summary = []
    for combo in SECOND_ORDER:
        parts = [mutant_by_id(pid) for pid in combo["parts"]]
        entry = {
            "id": combo["id"],
            "parts": combo["parts"],
            "desc": combo["desc"],
        }
        try:
            _apply_many([(p["file"], p["find"], p["replace"]) for p in parts])
        except AssertionError as exc:
            entry.update(status="PATCH-FAIL", error=str(exc))
            summary.append(entry)
            continue
        try:
            repo = run_repo()
            oracle = run_oracle()
        finally:
            for f in {p["file"] for p in parts}:
                subprocess.run(["git", "checkout", "--", f],
                               cwd=REPO_ROOT, capture_output=True)
                assert _md5(f) == baseline_md5[f], f"restore failed: {f}"
        entry["repo_exit"] = repo["exit"]
        entry["oracle_exit"] = oracle["exit"]
        entry["repo_tail"] = repo["tail"]
        entry["oracle_tail"] = oracle["tail"]
        entry["status"] = classify(repo, oracle)
        summary.append(entry)
        print(f"[{combo['id']}] {entry['status']} "
              f"(repo {repo['exit']}, oracle {oracle['exit']}) "
              f"{combo['desc']}")
        (protocols / f"ho_{combo['id']}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), "utf-8"
        )
    (protocols / "second_order_summary.json").write_text(
        json.dumps({"mutants": summary}, ensure_ascii=False, indent=2),
        "utf-8",
    )
    return summary


def run_attribution() -> dict:
    """Атрибуция: для мутантов, убитых ТОЛЬКО oracle-каналом, повторный
    прогон канала без одного файла-оракула -- мутант обязан ожить
    (доказательство, что килл атрибутирован оракулу, а не среде)."""
    protocols = _protocols_dir()
    summary_path = protocols / "mutations_summary.json"
    assert summary_path.exists(), "сначала запустите run"
    summary = json.loads(summary_path.read_text("utf-8"))
    oracle_only = [m for m in summary["mutants"]
                   if m.get("status") == "ORACLE-ONLY"]
    baseline_md5 = {f: _md5(f) for f in {m["file"] for m in MUTANTS}}
    results = []
    for entry in oracle_only:
        mid = entry["id"]
        mutant = mutant_by_id(mid)
        for skip_name, skip_path in ATTRIBUTION_ORACLE_FILES.items():
            _apply(mutant["file"], mutant["find"], mutant["replace"])
            try:
                channel = _run_channel(
                    [t for t in ORACLE_TARGETS if t != skip_path]
                )
            finally:
                subprocess.run(["git", "checkout", "--", mutant["file"]],
                               cwd=REPO_ROOT, capture_output=True)
                assert _md5(mutant["file"]) == baseline_md5[mutant["file"]]
            alive = channel["exit"] == 0
            results.append({
                "id": mid, "skip": skip_name,
                "exit": channel["exit"], "alive_without": alive,
            })
            print(f"[{mid}] without {skip_name}: "
                  f"{'ALIVE' if alive else 'still-KILLED'} "
                  f"(exit {channel['exit']})")
    verdict = {}
    for entry in oracle_only:
        mid = entry["id"]
        rows = [r for r in results if r["id"] == mid]
        # Мутант оживает хотя бы без одного файла-оракула => килл
        # атрибутирован конкретному файлу.
        verdict[mid] = any(r["alive_without"] for r in rows)
    (protocols / "attribution.json").write_text(
        json.dumps({"rows": results, "attributed": verdict},
                   ensure_ascii=False, indent=2),
        "utf-8",
    )
    print("attribution:", verdict)
    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry"
    if mode == "dry":
        problems = mv1_dry_run()
        print(f"MV1 anchors: {len(MUTANTS) - len(problems)}/"
              f"{len(MUTANTS)} OK")
        for problem in problems:
            print("  PROBLEM:", problem)
        print("MV2 classifier self-test:",
              "PASS" if self_test_classifier() else "FAIL")
        sys.exit(1 if problems else 0)
    elif mode == "run":
        only = sys.argv[2:] or None
        result = run_campaign(only)
        counts: dict[str, int] = {}
        for entry in result["mutants"]:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        print("MV3 all restored:", result["mv3_all_restored"])
        print("MV5 foreign tails:", result["mv5_foreign_tails"] or "none")
    elif mode == "second":
        rows = run_second_order()
        counts: dict[str, int] = {}
        for entry in rows:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        print(json.dumps(counts, ensure_ascii=False, indent=2))
    elif mode == "attr":
        run_attribution()
    else:
        print("modes: dry | run [ids...] | second | attr")
        sys.exit(2)
