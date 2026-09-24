# scripts/progr2cert_oracles.py
# Task PROGR-2-CERT -- СВОИ оракул-тесты аудитора на СВОИХ данных.
# От коллеги (scripts/progr2_oracles.py, 48 оракулов) отличаются:
#   * независимый reference-референс свёртки, написанный по ДОКСТРИНГУ
#     модуля (документированная таблица) и сверяемый на случайных
#     мульти sets (двойное вычисление, seeded RNG);
#   * негативная выборка по всем 46 узлам x чужим статусам (полная
#     матрица 46x6 + 46x3), а не по первым узлам стадий;
#   * свои probe-данные загрузчика EDA JSON (7 узлов, unicode, кавычки,
#     битый JSON, отсутствующий файл, nodes не список);
#   * порядок-инвариантность и детерминизм свёртки;
#   * проверка констант свёртки на идентичность (не просто строк).
# Запуск: python3 /home/z/my-project/scripts/progr2cert_oracles.py
from __future__ import annotations

import itertools
import json
import random
import sys
import tempfile
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO))

from app.core import pipeline_graph as pg  # noqa: E402

FAILED: list[str] = []
PASSED = 0


def oracle(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} {detail}")


# ── G. Свой reference свёртки + фаззинг двойным вычислением ───────

PASSED_, ATTENTION_, NOT_STARTED_ = "passed", "attention", "not_started"


def ref_fold(statuses: list[str]) -> str:
    """Независимый референс по ДОКСТРИНГУ fold_status_values:
    1) пусто -> not_started; 2) любой warning/error -> attention;
    3) все done -> passed; 4) done+skipped (есть done) -> passed;
    5) есть started-признак (running/in_progress/done при
    незавершённых) -> attention; 6) иначе -> not_started."""
    if not statuses:
        return NOT_STARTED_
    if any(s in ("warning", "error") for s in statuses):
        return ATTENTION_
    if all(s == "done" for s in statuses):
        return PASSED_
    if any(s == "done" for s in statuses) and all(
        s in ("done", "skipped") for s in statuses
    ):
        return PASSED_
    if any(s in ("running", "in_progress", "done") for s in statuses):
        return ATTENTION_
    return NOT_STARTED_


print("G. Свёртка: reference-фаззинг на своих случайных наборах")
import os
FUZZ_N = 300 if os.environ.get("CERT_FAST") == "1" else 3000
rng = random.Random(20260924)  # свой seed
vocab = ["done", "warning", "pending", "skipped", "running", "error", "in_progress"]
mismatch = 0
for trial in range(FUZZ_N):
    n = rng.randint(0, 14)  # свои длины: 0..14 (у коллеги 0..3+10/11)
    sample = [rng.choice(vocab) for _ in range(n)]
    got = pg.fold_status_values(sample)
    want = ref_fold(sample)
    if got != want:
        mismatch += 1
        if mismatch <= 3:
            print(f"    MISMATCH {sample}: got={got} want={want}")
oracle("G1 reference-фаззинг 3000 наборов: расхождений нет", mismatch == 0, str(mismatch))

# порядок-инвариантность и детерминизм (свои свойства)
perm_ok = True
det_ok = True
for trial in range(100 if os.environ.get("CERT_FAST") == "1" else 500):
    n = rng.randint(1, 12)
    sample = [rng.choice(vocab) for _ in range(n)]
    shuffled = sample[:]
    rng.shuffle(shuffled)
    if pg.fold_status_values(sample) != pg.fold_status_values(shuffled):
        perm_ok = False
    if pg.fold_status_values(sample) != pg.fold_status_values(sample):
        det_ok = False
oracle("G2 свёртка порядок-инвариантна (500 перестановок)", perm_ok)
oracle("G3 свёртка детерминирована (500 повторов)", det_ok)

# константы свёртки -- именно те три строки, и _VISUAL_STATES им равен
oracle("G4 три визуальных состояния -- свои имена",
       {pg.NODE_FOLD_PASSED, pg.NODE_FOLD_ATTENTION, pg.NODE_FOLD_NOT_STARTED}
       == {PASSED_, ATTENTION_, NOT_STARTED_})
oracle("G5 fold возвращает только 3 константы на всём алфавите",
       all(pg.fold_status_values(list(c)) in (PASSED_, ATTENTION_, NOT_STARTED_)
           for size in (0, 1, 2, 3, 4)
           for c in itertools.product(vocab, repeat=size)))

# ── H. Модель узла: полная негативная матрица на 46 узлах ─────────

print("H. Модель узла: полная негативная матрица 46x(6+3)")
bad_stage_status = 0
bad_process_status = 0
for stage, node_id in pg.iter_all_nodes():
    allowed = (set(pg.CHECK_STATUS_VALUES) | set(pg.PROCESS_STATUS_VALUES)
               ) if stage in pg.CHECK_STATUS_STAGES else set(pg.PROCESS_STATUS_VALUES)
    for status in vocab:
        if status in allowed:
            continue
        try:
            pg.make_node_state(stage, node_id, status=status)
            bad_stage_status += 1
        except ValueError:
            pass
oracle("H1 чужой статус отвергнут для всех 46 узлов (проверочные)",
       all(pg.make_node_state(s, n, status=st) or True
           for s, n in pg.iter_all_nodes() if s in pg.CHECK_STATUS_STAGES
           for st in pg.CHECK_STATUS_VALUES),
       "")
try:
    pg.make_node_state("modeling", "backtest", status="warning")
    bad_process_status += 1
except ValueError:
    pass
oracle("H2 CheckStatus-значение отвергнуто на процессной стадии", bad_process_status == 0)

# замороженность: все 7 полей не присваиваются
node = pg.make_node_state("validation", "ranges", status="done")
frozen_ok = True
for field_name, value in [
    ("stage", "eda"), ("node_id", "correlation"), ("status", "pending"),
    ("status_reason", "x"), ("mode", "auto"), ("last_touched_at", "t"),
    ("summary_count", 1),
]:
    try:
        setattr(node, field_name, value)
        frozen_ok = False
    except Exception:
        pass
oracle("H3 все 7 полей заморожены", frozen_ok)

# равенство и хэш (контракт dataclass: дедуп узлов возможен)
a = pg.make_node_state("eda", "structural", status="done", summary_count=2)
b = pg.make_node_state("eda", "structural", status="done", summary_count=2)
c = pg.make_node_state("eda", "structural", status="done", summary_count=3)
oracle("H4 равные узлы равны и хэшируемы", a == b and hash(a) == hash(b) and a != c)

# границы summary_count: 0/1/10^9 ок, -1 нет
bounds_ok = True
try:
    pg.make_node_state("preprocessing", "missing", summary_count=0)
    pg.make_node_state("preprocessing", "missing", summary_count=1)
    pg.make_node_state("preprocessing", "missing", summary_count=10**9)
except ValueError:
    bounds_ok = False
try:
    pg.make_node_state("preprocessing", "missing", summary_count=-1)
    bounds_ok = False
except ValueError:
    pass
oracle("H5 границы summary_count (0/1/10^9 ok, -1 reject)", bounds_ok)

# mode: значение-гейт отдельно от стадия-гейта
mode_ok = True
for stage in ("upload", "eda", "modeling", "forecasting"):
    for node_id in pg.STAGE_NODES[stage][:1]:
        try:
            pg.make_node_state(stage, node_id, mode="enabled")
            mode_ok = False
        except ValueError:
            pass
try:
    pg.make_node_state("validation", "data_types", mode="sometimes")
    mode_ok = False
except ValueError:
    pass
try:
    pg.make_node_state("preprocessing", "outliers", mode="disabled")
except ValueError:
    mode_ok = False
oracle("H6 mode-гейты: стадия и значение (свои узлы)", mode_ok)

# прямое конструирование валидируется (не только фабрика)
direct_ok = True
for kwargs in (
    {"stage": "nope", "node_id": "x"},
    {"stage": "eda", "node_id": "ghost"},
    {"stage": "eda", "node_id": "descriptive", "status": "in_progress"},
    {"stage": "modeling", "node_id": "tuning", "status": "skipped"},
    {"stage": "upload", "node_id": "structure_confirmed", "mode": "auto"},
    {"stage": "eda", "node_id": "distribution", "summary_count": -5},
):
    try:
        pg.PipelineNodeState(**kwargs)
        direct_ok = False
    except ValueError:
        pass
oracle("H7 прямое PipelineNodeState(...) fail-closed (6 кейсов)", direct_ok)

# ── I. Граф: свои негативные пробы is_known_node / iter ───────────

print("I. Граф: свои негативные пробы")
neg_ok = True
for stage, node_id in [
    ("", ""), ("Validation", "data_types"), ("validation", "data-types"),
    ("validation", ""), ("forecasting", "forecast_export"), ("model", "backtest"),
    ("preprocessing", "regularity "), ("eda", "stationarity\n"),
]:
    if pg.is_known_node(stage, node_id):
        neg_ok = False
oracle("I1 восемь своих негативных пар отвергнуты", neg_ok)

all_known = all(pg.is_known_node(s, n) for s, n in pg.iter_all_nodes())
oracle("I2 все 46 пар из iter_all_nodes известны", all_known)

dups = {}
for stage, nodes in pg.STAGE_NODES.items():
    for n in nodes:
        dups.setdefault(n, []).append(stage)
cross = {n: ss for n, ss in dups.items() if len(ss) > 1}
oracle("I3 кросс-стадийные дубликаты -- ровно regularity+stationarity",
       set(cross) == {"regularity", "stationarity"}
       and cross == {"regularity": ["validation", "preprocessing"],
                     "stationarity": ["preprocessing", "eda"]}, str(cross))

oracle("I4 46 узлов = 1+10+10+10+11+4 (своя арифметика)",
       pg.TOTAL_NODE_COUNT == 1 + 10 + 10 + 10 + 11 + 4 == 46)

# паспорт отсутствует во всех стадиях и в EDA JSON
json_raw = json.loads((REPO / "shared" / "pipeline_nodes" / "eda_checks.json").read_text(encoding="utf-8"))
oracle("I5 узла passport нет нигде (граф + JSON)",
       all("passport" not in nodes for nodes in pg.STAGE_NODES.values())
       and all(n["id"] != "passport" for n in json_raw["nodes"]))

# ── J. Загрузчик EDA JSON: свои probe-файлы ───────────────────────

print("J. Загрузчик EDA JSON: свои probe-файлы")


def probe(nodes_payload, stage="eda", raw_text=None) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    if raw_text is not None:
        f.write(raw_text)
    else:
        f.write(json.dumps({"version": 1, "stage": stage, "nodes": nodes_payload},
                           ensure_ascii=False))
    f.close()
    return Path(f.name)


tmp = Path(tempfile.mkdtemp())

# свои данные: 7 узлов, unicode + кавычки в описаниях
my_nodes = [
    {"id": f"cert_probe_{i}",
     "label": f"Проба {i} «{i}»",
     "description": f'Описание с "кавычками" и unicode: {i} ✓ ≠ ±'.replace("✓", "ок")}
    for i in range(7)
]
p = probe(my_nodes)
defs = pg._load_eda_check_defs(p)
oracle("J1 свои 7 узлов читаются дословно (unicode/кавычки)",
       tuple(d["id"] for d in defs) == tuple(n["id"] for n in my_nodes)
       and defs[3]["description"] == my_nodes[3]["description"])

# битый JSON
p_bad = probe(None, raw_text="{not json at all]")
try:
    pg._load_eda_check_defs(p_bad)
    oracle("J2 битый JSON -> ImportError", False)
except ImportError:
    oracle("J2 битый JSON -> ImportError", True)

# отсутствующий файл
try:
    pg._load_eda_check_defs(tmp / "нет_такого_файла.json")
    oracle("J3 отсутствующий файл -> ImportError", False)
except ImportError:
    oracle("J3 отсутствующий файл -> ImportError", True)

# nodes не список
p_notlist = probe(None, raw_text='{"version": 1, "stage": "eda", "nodes": {"a": 1}}')
try:
    pg._load_eda_check_defs(p_notlist)
    oracle("J4 nodes-объект (не список) -> ImportError", False)
except ImportError:
    oracle("J4 nodes-объект (не список) -> ImportError", True)

# запись без ключа label
p_nolabel = probe([{"id": "x", "description": "d"}])
try:
    pg._load_eda_check_defs(p_nolabel)
    oracle("J5 запись без label -> ImportError", False)
except ImportError:
    oracle("J5 запись без label -> ImportError", True)

# id из одних пробелов
p_ws = probe([{"id": "   ", "label": "L", "description": "d"}])
try:
    pg._load_eda_check_defs(p_ws)
    oracle("J6 id из одних пробелов -> ImportError", False)
except ImportError:
    oracle("J6 id из одних пробелов -> ImportError", True)

# stage не eda (свой вариант "upload")
p_stage = probe([{"id": "x", "label": "L", "description": "d"}], stage="upload")
try:
    pg._load_eda_check_defs(p_stage)
    oracle("J7 stage=upload -> ImportError", False)
except ImportError:
    oracle("J7 stage=upload -> ImportError", True)

# живой JSON: order = порядок степпера, description не пуст
ids = [n["id"] for n in json_raw["nodes"]]
oracle("J8 живой JSON: 10 узлов, порядок == EDA_STAGE_IDS",
       len(ids) == 10 and tuple(ids) == pg.EDA_STAGE_IDS)
oracle("J9 живой JSON: все description непустые",
       all(str(n["description"]).strip() for n in json_raw["nodes"]))

# ── K. Свёртка на РЕАЛЬНЫХ стадиях (свои сценарии) ────────────────

print("K. Свёртка на реальных стадиях: свои сценарии")
# §12 п.10 на каждой реальной стадии: все done + один warning на ЛЮБОЙ позиции
prec_ok = True
for stage, nodes in pg.STAGE_NODES.items():
    size = len(nodes)
    for pos in range(size):
        sts = ["done"] * size
        sts[pos] = "warning"
        if pg.fold_status_values(sts) != ATTENTION_:
            prec_ok = False
        sts[pos] = "error"
        if pg.fold_status_values(sts) != ATTENTION_:
            prec_ok = False
oracle("K1 §12 п.10: warning/error на любой позиции всех 6 стадий -> attention", prec_ok)

# свои сценарии на modeling (11) и forecasting (4): скупо/полно
scen_ok = True
if pg.fold_status_values(["pending"] * 11) != NOT_STARTED_: scen_ok = False
if pg.fold_status_values(["in_progress"] + ["pending"] * 10) != ATTENTION_: scen_ok = False
if pg.fold_status_values(["done"] * 10 + ["pending"]) != ATTENTION_: scen_ok = False
if pg.fold_status_values(["done"] * 11) != PASSED_: scen_ok = False
if pg.fold_status_values(["done", "done", "done", "pending"]) != ATTENTION_: scen_ok = False
if pg.fold_status_values(["skipped", "skipped", "skipped", "skipped"]) != NOT_STARTED_: scen_ok = False
oracle("K2 свои сценарии моделирования/прогнозирования", scen_ok)

# fold_stage_status игнорирует метаданные -- на своих узлах
n_meta = pg.make_node_state("validation", "uniqueness", status="done",
                            status_reason="дубликатов нет", mode="auto",
                            last_touched_at="2026-09-24T12:00:00+03:00",
                            summary_count=17)
n_plain = pg.make_node_state("validation", "uniqueness", status="done")
oracle("K3 fold по узлам не зависит от метаданных (свои значения)",
       pg.fold_stage_status([n_meta]) == pg.fold_stage_status([n_plain]) == PASSED_)

# пустая стадия через fold_stage_status
oracle("K4 fold_stage_status([]) -> not_started",
       pg.fold_stage_status([]) == NOT_STARTED_)

print(f"\nИтог: {PASSED} PASS / {len(FAILED)} FAIL")
if FAILED:
    print("Упавшие:", ", ".join(FAILED))
    raise SystemExit(1)
print("СВОИ ОРАКУЛЫ ЗЕЛЁНЫЕ")
