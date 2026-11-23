# PGV13-VIS-02 — семантика `unchanged`: явный false не превращается в true

Задача сертификации PGV-13 (docs/pgv13_visual_review_2026-11-21.md, PGV13-VIS-02,
blocking). Постановка тимлида: «Явный `false` не должен превращаться в `true`
из-за отсутствующего `previous_ref`. Отдельно обрабатывать неизвестность и
дедупликацию одинаковых refs. Закрыть случаи тестами, сохранив исходные
checkpoint и payload». Негативные контроли review: explicit false / отсутствующий
флаг / previous missing / equal / different.

## 1. Проблема

Frozen-fixture `p02-reused.payload.json` (строка 356 резолвера
`apps/api/passport_comparison.py`, SHA исходника совпадает с VM fingerprint):
`checkpoint.flags = {created:false, reused:true, unchanged:false}`,
`previous_ref = null`, `reused_ref` = ref exit-снимка (последняя запись пути).
Резолвер выводил `confirmation.unchanged = true` по деривации
«reused + отсутствующий previous» — печатная строка P02
«Состояние совпало с предыдущим снимком» противоречила явному false.

## 2. Причина — контрактная, не точечная

- Продюсер (`apps/api/passport_checkpoints.py`) писал `unchanged: False`
  ВСЕГДА («не заявляется»), в том числе для доказуемо-unchanged reuse.
- Резолвер компенсировал деривацией «freeze не пишет previous при
  previous == подтверждённый снимок ⟹ previous отсутствует ⟹ unchanged».
- Следствие: явный false и «флаг не заявлен» неразличимы; отсутствие
  previous трактуется как доказательство — нарушение честности (review:
  «отсутствие четвёртой копии не доказывает unchanged»).

## 3. Решение

### 3.1 Продюсер: заявлять доказуемое

`build_passport_checkpoint_payload`:
- modeling_entry: `unchanged = (not created_snapshot) and
  checkpoint.previous_snapshot_id == checkpoint.snapshot_id` — ТОТ ЖЕ
  доказуемый критерий, что уже использует session-контур
  (`routers/session.py:6059`, `unchanged_from_previous`): unchanged-reuse
  переиспользует ПОСЛЕДНИЙ паспорт (previous == сам снимок; самоссылка
  по-прежнему не пишется — запрет F-P2C4 сохранён).
- panel_entry: `unchanged = False` — previous==self у панели конвенция
  (`modeling_session.py:3621`), а 409-гейты гарантируют, что новое
  подтверждение несёт изменённый fingerprint; «не заявляется» честно.
- Валидатор AC11 (`visual_artifacts.validate_passport_checkpoint`):
  unchanged⊆reused, unchanged несовместим с created — новый флаг
  удовлетворяет (previous==self ⟹ не created ⟹ reused=True).

### 3.2 Резолвер: tri-state с явным приоритетом «доказательство > заявление > неизвестность»

`confirmation.unchanged` — `true | false | null`; новое аддитивное поле
`confirmation.unchanged_basis` (код основания):

| # | previous | flags.unchanged | unchanged | basis |
|---|---|---|---|---|
| 1 | есть, ref равен подтверждённому | любой | true | `previous_ref_identity` |
| 2 | есть, ref отличен | любой | false | `previous_ref_differs` |
| 3 | нет | явный true | true | `producer_flag` |
| 4 | нет | явный false | **false** | `producer_flag_false` |
| 5 | нет | флага нет/None | **null** | `unknown_no_evidence` |

- Строки 1–2: доказательство по refs сильнее заявления (равенство refs —
  та же физическая rs-запись: научная неизменность доказана; различие —
  опровергнуто). Явный false блокирует только вывод из ОТСУТСТВИЯ
  previous (деривацию), но не опровергается/не подтверждается им.
- Строка 4 — ядро фикса VIS-02 (fixture-случай).
- Строка 5 — неизвестность выделена отдельно: без флага и без previous
  утверждение не делается ни в плюс, ни в минус.
- Конфликтные входы (явный true при доказанном различии; явный false при
  доказанном равенстве) производителем нового контракта не порождаются
  (см. §3.1); ветки 1–2 детерминированы refs.

### 3.3 Дедупликация — отдельное решение, физическое

Этап подтверждения исключается из пути тогда и только тогда, когда его
запись — ФИЗИЧЕСКИЙ алиас непосредственно предыдущего элемента пути (тот
же snapshot_ref): иначе сравнение было бы нулевой самопарой (запрещено
§9/AC11). Правило не зависит от `unchanged`:
- unchanged-reuse (алиас exit = последняя запись) — исключается; путь
  fixture `start, validation, exit` сохраняется байт-в-байт семантически;
- reuse более старого снимка (алиас validation, предыдущий элемент — exit)
  — ОСТАЁТСЯ: пара возврата (exit → modeling_entry) научно осмысленна;
  старый код терял её при выводе unchanged=true (дефект дедупликации);
- created — не исключается никогда.

### 3.4 Печать (`packages/ui/print/printComparison.tsx`)

- Тип: `unchanged: boolean | null`, `unchanged_basis?: string | null`.
- Фразы по tri-state (и по `reused` для false-ветки):
  - true: прежняя — «Состояние совпало с предыдущим снимком — …»;
  - false: reused ? «Используется ранее рассчитанный снимок без
    повторного расчёта; совпадение состояния с предыдущим снимком
    чекпоинтом не подтверждено.» : «Снимок рассчитан заново; совпадение
    с предыдущим состоянием не применимо.»;
  - null: «Совпадение состояния с предыдущим снимком неизвестно: в
    чекпоинте нет ни явного флага, ни ссылки на предыдущий снимок.»
- Метка `previous ref: "нет (unchanged)"` заменена на честное
  «нет в записи чекпоинта» (отсутствие ref больше не выдаётся за
  неизменность).

### 3.5 Что НЕ меняется

- Frozen fixture (checkpoint/payload/PNG/report/review) — только вход;
  байты не переписываются.
- Формат ключей confirmation: прежние поля сохранены, `unchanged_basis`
  и null-допустимость `unchanged` — аддитивно (JSON-потребители печати —
  единственные читатели).
- `unchanged_from_previous` session-сравнения (schemas.py:3300) — другой
  слой, не трогается.
- Роуты/DTO/BFF/образы/миграции — не затронуты.

## 4. Последствия для существующих данных

Durable-чекпоинты, замороженные старым продюсером (флаг false при
доказуемом unchanged), после обновления честно печатают
«не подтверждено» до повторного capture/backfill (backfill уже
замороженные пропускает по producer_key — перезаписи нет). Новые
capture/backfill пишут корректный флаг. Это осознанный переход к
честности (review предпочитает её выводу-догадке).

## 5. Тесты (TDD)

RED (новые):
- резолвер: явный false + previous нет → false; флага нет + previous нет
  → null; flags=None → null; дедупликация не теряет пару возврата
  (алиас середины пути остаётся в пути);
- продюсер: unchanged-reuse последнего снимка → durable
  `flags.unchanged is True`; panel-подтверждение → False;
- печать: null-фраза без «совпало»; false-фраза «не подтверждено»;
  отсутствие метки «нет (unchanged)».

GREEN-стражи (закрепляют прежнее корректное поведение): явный true + previous
нет → true; previous равен → true; previous отличен → false; алиас последнего
элемента пути исключается (fixture-паритет); живые session-тесты pgv06
(unchanged-reuse → true, alias-return → false) — без правок утверждений
(флаг теперь несётся продюсером).
