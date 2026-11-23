# PGV-14 — измеряемая пагинация P01/P02 и проверяемый page-set

База: 5be3e29b32d954f9abe009236c4546d876ec2b9b. Норматив: spec_passport_graphics_visual.md §7–12, AC15/16/20/21/23. Предыдущий акт VIS-01-CERT и приложенный 1.txt (CLI capture errors, не PNG-отчёт) изучены.

## Решение и границы

- Источники остаются frozen P01/P02; версия builder повышается, старые basis/jobs/renditions не переписываются. Никаких DataFrame/capture/научных вычислений.
- Existing POST /v1/render получает additive options.page_set=true только для P01/P02. Ответ wire — bounded ZIP с PNG каждой страницы, manifest.json и metadata.json. Manifest расширяет общий `pgv.print_manifest/1`: set_id, render_version, data_included=false, metadata_filename, page roles/dimensions/PNG hashes; page_set_version=pgv.page_set/1. V01/probe/smoke остаются single-PNG.
- Один browser/admission/deadline на весь job. Сначала реальный Chromium layout/fonts, потом полное разбиение, затем проверка всех страниц, затем screenshots. Размеры 9.5pt/8–8.5pt не уменьшаются. Лимиты20 страниц/12MP/50MiB/60s, отказ целиком при oversized atom/width/limit/cancel; partial ready запрещён.
- DOM atoms: целые строки таблиц, абзацы/пункты списков и неделимые banners. Заголовок документа/идентификаторы frozen source/колонтитулы повторяются; заголовки таблиц и band-групп повторяются на затронутых страницах. Комплект сохраняет порядок физических паспортов, confirmation не становится четвёртым паспортом.
- Внутренний slot, поля и footer измеряются явно — закрываем недостаточность outer-only guard. Все atom IDs покрыты ровно один раз до rasterization. Неделимый слишком высокий блок даёт413; широкая строка не ужимается шрифтом.
- Renderer ZIP проверяется API до staging: exact filenames/order/count, CRC/geometry/pHYs PNG каждой страницы, hashes manifest/metadata, frozen input binding, limits. Один main rendition (PNG при одной странице; ZIP при нескольких/режиме set) и JSON sidecar с manifest/metadata используют существующие document_renditions/ObjectStore и одну публикацию AUTH13. Новая SQL-схема не нужна. Job.format сохраняет requested PNG intent, rendition.format/media_type/extension — реальные PNG/ZIP. Ready replay идёт по job.rendition_id, чтобы ZIP не породил повторный job.
- JSON sidecar доступен через прежний защищённый rendition content route; его URL добавляется в ready job DTO. Authority/cancel/publication/mandatory delivery audit прежние, raw series не добавляются. Memory-публикация защищена тем же lock и rollback снимком метаданных; production — существующий bound PostgreSQL publication transaction.
- Все11 CASES сохраняются, включая p01-corrupt/reused/figure. Проверка раскрывает ZIP, проверяет КАЖДУЮ страницу (PNG/pHYs/pixels/OCR/header/footer), затем семантику всего документа. Ни исключения dense cases, ни ожидаемых413 вместо их проверки.

## Риски и проверка

TDD: pure package/manifest corruption/limits; SSR→DOM pagination logical controls; worker/client/lifecycle/idempotency/cancel/JSON-sidecar;11-case acceptance. Native Chromium/UDS/final-image/OCR отдельно; doubles не называются VM приёмкой. Routes/DTO/registry inventory проверяются после реализации; default gates сохраняют strict INDEX. Новые coherent API/web/renderer images и новый bundle/A-B/candidate/recreate/live/11-case report необходимы после push тимлида; старые evidence не переписываются.
