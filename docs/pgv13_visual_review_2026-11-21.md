# PGV-13 — независимый просмотр результатов VM, 21.11.2026

**Вердикт: визуальная приёмка не пройдена.** Автоматический отчёт сохраняет
`automated_passed:true`; это не подтверждает `legible` или общую сертификацию.
Два блокера ниже нельзя обходить установкой всех review flags в true.

Проверен прикреплённый `pgv13-visual-review.zip`, 1 342 185 bytes, SHA-256
`595522df40313dfe534d51688f5a7fa1c0fdbb86634aa16820ddc0ac5ac460b4`.
Он совпадает с hash, полученным оператором после передачи41/41.
Внутри26 файлов:11 исходных PNG,11 frozen payload, report и review files.
Image/tool revision: `0c78766a000f4e828a4f503708d5dc5ca6fd4016`.
Report SHA-256: `410b201af782dd389b1c8bd87da33bced0b8f0aba78dccc07f396ccb8d01a8df`.

## Что подтверждено

ZIP CRC и22 hashes PNG/payload совпадают. Все11 PNG повторно прошли проверки
PNG/CRC/геометрии/pHYs≈300ppi/непрозрачности/наличия контента. Ожидаемые A4
размеры2480×3508 /3508×2480 и figure2400×1500 сохранены. Структура native
report и обязательные controls проверены; в отчёте научных session rows0,
completed workers11, held reservations0, cleanup passed. API/rules/catalog
fingerprints и4 acceptance-tool/6 compiled-renderer hashes совпадают с локально
проверенными исходниками/сборкой. Новой синхронизации GitHub не выполнялось.

Просмотрены все11 изображений, полные листы и native-resolution области с
контентом. В проверенном корпусе не обнаружено утраченных кириллических
глифов, наложения разделов или обрезанных строк. P01 start содержит n37, mean0,
r²0.25, lag1=0.5, flat, seasonality=false, periods4/9. Reused-комплект содержит
ровно start/validation/exit: mean0/7/11, periods4/9→4→4/12, три маркера БЕРЁЗА,
без четвёртого паспорта. P02 показывает0→7, delta7 и legacy delta_pct100;
следующая пара7→11, delta4 и округлённые57.1%. Category/list/boolean changes
соответствуют frozen данным. Определение нулевого базиса присутствует:
legacy100.0 не является процентом; оценивать эту ячейку без пояснения нельзя.
Missing/corrupt отображаются как явные gaps с причинами и неизвестными полями;
P02 missing не фабрикует числовую таблицу.

## PGV13-VIS-01 — физический размер текста, blocking

В physical profile300ppi тело12px соответствует **2.88pt**, определения и
примечания10px — **2.40pt**, micro9px —2.16pt. Увеличенные заголовки P0222px
соответствуют5.28pt. Это номинальный размер шрифта, не размер bounding box.
Медианная высота распознанных слов в исходном PNG —8–10px. При просмотре
с увеличением символы различимы, но штатный размер листа/рисунка не обеспечивает
читаемую печать. На P02 A4 содержимое занимает верхние≈595px из3508, при этом
таблица и определения остаются микроскопическими. На P01single —≈878px.

Это заключение по фактическим пикселям, плотности и типографике; испытание на
физическом принтере не выполнялось. Требование читаемости задано §3.4/§7/AC23
spec_passport_graphics_visual.md. OCR-вход увеличивается отдельно и может
проходить, сохраняя этот дефект исходного изображения. Поэтому `legible=false`
для всех11 случаев. Увеличение только заголовков или готового PNG недостаточно.

Исправление: задать физическую типографику в pt/mm либо логических CSS units с
явным переводом к raster300ppi. Согласовать масштаб всего layout, включая
отступы/таблицы/пояснения. Reused и длинные таблицы не втискивать мелким шрифтом:
пагинация/page-set либо честный отказ по лимиту. Это связано с PGV-14.

## PGV13-VIS-02 — противоречие unchanged, blocking

В `p02-reused.payload.json` одновременно записаны:

```text
sections[0].comparison.checkpoint.flags.unchanged = false
sections[0].comparison.confirmation.unchanged     = true
sections[0].comparison.confirmation.previous_ref = null
```

Оба поля относятся к одному checkpoint, тот же checkpoint в P01 имеет
`flags.unchanged:false`. На P02 PNG напечатано «Состояние совпало с предыдущим
снимком». Печать следует comparison payload: источник противоречия находится
до печатного компонента. В проверенном resolver `apps/api/passport_comparison.py`
строка356 вычисляет unchanged из reused+отсутствия previous, игнорируя явный
false. SHA исходника совпадает с VM fingerprint:
`eeaad8c295300370b6808d811dfff1937f6cda4cd8aadf75e1618ea257a8c425`.

Требуется разрешить противоречие контракта producer/reader/resolver и отдельно
проверить семантику отсутствующего previous. Не переписывать checkpoint/fixture
или frozen payload ради зелёной проверки. Дедупликация одинакового физического
ref и утверждение о научной неизменности — отдельные решения: отсутствие
четвёртой копии не доказывает unchanged. Нужны негативные контроли explicit
false / отсутствующий флаг / previous missing / equal / different. До выяснения
`values_and_reasons_correct=false` для p02-reused.

## Матрица осмотра

У всех11: кириллица без подмены глифов; наложений и crop не обнаружено;
`legible=false` по PGV13-VIS-01. Это AI inspection, не подпись оператора.

| Случай | Сверка содержимого | Блокеры |
| --- | --- | --- |
| p01-figure-landscape | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p01-a4-landscape | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p01-a4-portrait | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p01-reused | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p02-figure-landscape | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p02-a4-landscape | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p02-a4-portrait | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p02-reused | Числа/списки/reasons совпадают; конфликт unchanged | PGV13-VIS-01, PGV13-VIS-02 |
| p01-missing | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p01-corrupt | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |
| p02-missing | Видимые значения/reasons соответствуют payload | PGV13-VIS-01 |

## Границы и следующий шаг

Исходные PNG/payload/report/review и их flags не изменялись. `reviewer` остаётся
пустым в исходном review. Этот акт не подставлять вместо человеческой подписи.
Raw OCR TSV и release A/B/candidate/live bundle в прикреплённый ZIP не входят;
OCR/Docker/VM jobs здесь заново не выполнялись. Read-only проверки структуры
отчёта не выдаются за повторное исполнение этих сценариев.

Приложение, HTTP/renderer routes, guards/DTO/IPC/DDL и образы не менялись.
Actual check_routes выполнен отдельно; протокол рядом с этим актом. Новый build
не нужен для самого просмотра. После исправления печати/resolver потребуется
новый согласованный release, A/B/native и новый набор PNG/semantic/visual checks.
Нынешний report следует сохранить как автоматический PASS и доказательство
двух обнаруженных блокеров. `finalize` для этого набора сейчас не запускать.
