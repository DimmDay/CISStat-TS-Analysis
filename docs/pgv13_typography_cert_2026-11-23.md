# PGV13-VIS-01-CERT — независимая проверка физической типографики

Дата: 23.11.2026, Москва. Проверенная база: `main@a6429e30f0eb4f9fed12948757e5546065267c17`.
Объект: VIS-01 — размеры pt/mm → пиксели 300 ppi, таблицы, переносы, поля и колонтитулы P01/P02.
Норматив: `spec_passport_graphics_visual.md` §3.4, §7–9, §12, AC15/16/23 и постановка тимлида.

**Вердикт: физическая шкала и декларации стилей соответствуют; полная приёмка VIS-01 НЕ ЗАКРЫТА. PGV-13 NOT CERTIFIED.**

Ни наличие чисел в теме, ни SSR/JSDOM не доказывают отсутствие наложения или crop в PNG.
Продуктовые исходники, исторические checkpoints/payload/PNG, транспорт, образы и VM не изменены.
Это сертификационный срез; исправления обнаруженных недостатков не подмешивались.

## 1. Вложение и исходные свидетельства

`1.txt` содержит только два операторских CLI-отказа:

1. `capture --bundle "$PGV13_BUNDLE"` — не передан обязательный существующий renderer project.
2. `capture --prev-bundle "$PREV_BUNDLE"` — такой аргумент отсутствует; `--bundle` по-прежнему обязателен.

Это не отчёт PNG/типографики и не доказательство успешного развёртывания `a6429e3`.
SHA вложения и продуктовых исходников — `scripts/pgv13typocert/protocols/summary.json`.
Само вложение не переписывалось. Исторический visual review 21.11 и журнал VIS-01 изучены;
старые PNG и исходный ZIP в текущем диалоге не приложены, повторная проверка их байтов не заявляется.

## 2. Подтверждённая часть

Проверены свежесобранный общий print bundle и собственные frozen P01/P02 inputs,
без заимствования авторских тестовых fixtures, без DataFrame/научного расчёта.

| Величина | Источник | Результат при 300 ppi |
|---|---|---|
| pt → px | `pt × 300 / 72` | 1 pt = 4,166667 px |
| mm → px | `mm × 300 / 25,4` | 1 mm = 11,811024 px |
| Основной текст таблиц | 9,5 pt | 39,583333 px |
| Служебный small | 8,5 pt | 35,416667 px |
| Служебный micro | 8 pt | 33,333333 px |
| Заголовок / секция | 16 / 11 pt | 66,666667 / 45,833333 px |
| Поля страницы | 12 mm | 141,732283 px |
| Ячейки по вертикали / горизонтали | 1 / 1,2 mm | 11,811024 / 14,173228 px |
| pHYs | 300 ppi | 11811 px/m, округление до целого |

| Профиль | Геометрия | P01/P02: размер текста, ячеек, полей и подвала |
|---|---|---|
| figure-landscape | 2400×1500 px | декларации PASS; фактическая вмещаемость не проверена |
| a4-landscape | 3508×2480 px | декларации PASS; фактическая вмещаемость не проверена |
| a4-portrait | 2480×3508 px | декларации PASS; фактическая вмещаемость не проверена |

Проверены переносы длинных refs и обычных ячеек (`overflowWrap: anywhere`),
номер страницы в общем подвале и служебный размер его текста. Коридор body 9–10 pt соблюдён.
Это точные проверки SSR-стилей, не layout engine JSDOM и не визуальная подпись оператора.
Границы внешней поверхности и допуск 1px проверены отдельно; HTTP 413 и retryable=false
действительно реализованы в rendererCore/server, проблема F-TYPO-03 ниже относится к их проверке.

## 3. Находки

### F-TYPO-01 — неполная наблюдаемость внутреннего переполнения (блокирует достаточность гейта)

`packages/ui/print/printLayout.tsx:491`: центральный слот имеет `flex: 1 1 auto; minHeight: 0`.
Подвал находится следующим sibling. Содержимое слота способно выходить из его выделенной высоты.
`apps/print-renderer/src/renderWorker.ts:396` измеряет только scroll/client внешней поверхности
(или полноразмерной probe-обёртки). Ни собственные границы body slot, ни пересечение с footer не наблюдаются.

Независимый тест извлекает **настоящий callback surface.evaluate** через TypeScript AST
и исполняет его, затем вызывает **настоящий detectSurfaceOverflow** на конечной модели DOM-измерений:
внешний лист 2480×3508, scroll такой же; слот clientHeight=3000 / scrollHeight=3090;
конец контента y=3232, начало подвала y=3189. Callback+guard принимают страницу.
Это воспроизводимый недостаток покрытия алгоритма измерений, а не показанный испорченный PNG.
**Получение именно таких метрик реальным Chromium/финальным образом пока НЕ ПРОВЕРЕНО.**

Закрытие: наблюдать выделенный content slot/границы текста относительно footer и полей;
обеспечить явный отказ либо пагинацию. Добавить браузерные проверки на границе вместимости
для каждого профиля, длинные refs/строки и номера страниц. Одного сравнения размеров внешнего листа недостаточно.
Для такого изменения нужен новый RED→GREEN product fix; в текущем срезе его нет.

### F-TYPO-02 — в локальном «11-case» runner отсутствует p01-corrupt (P2)

`scripts/pgv13vis01/render_samples.mjs:105`: массив `names` содержит **10**, а не 11 случаев.
Отсутствует `p01-corrupt`, присутствующий в исходном `scripts/pgv13accept/client.py:CASES`.
Документ и worklog заявляют 11. Независимый exact-set oracle воспроизводит RED.
Изменять историческую fixture для закрытия этой находки не нужно; нужно восстановить полноту проверки и числа отчёта.

### F-TYPO-03 — ложный успех проверки отказа 413 (P2)

`scripts/pgv13vis01/render_samples.mjs:198–201`: итоговый `ok` для отказов проверяет статус,
но не `error.code` и не `X-Render-Retryable`/`error.retryable`.

Контроль исполняет **весь реальный runner**, транспилированный без изменения его логики,
с явными fs/http/child-process doubles. Все десять основных статусов соответствуют его матрице,
adapted-ответы дают PNG-сигнатуру; вместо `render_content_overflow` подставлен
`payload_too_large`, header/body retryable=true. Runner печатает `VIS01_LOCAL_RENDER_OK`, exit 0.
Требующий отказа oracle получает RED. Это дефект сертификационного инструмента,
**не доказательство неверного ответа реального renderer**.

Закрытие: проверять точный код, header и DTO retryability во всех 413-ветках, включая crafted overflow;
отдельно проверить, что подмена семейства ошибки/повторяемости отклоняется.

## 4. Несогласованные заявления и границы

- `docs/pgv13_visual_typography.md` §2.7 описывает три отказа 413, но §3 утверждает,
  что все 11 образцов помещаются. Это противоречие требует исправления вместе с итоговой матрицей.
- Старая native document acceptance в `scripts/pgv13accept/client.py:281` требует ready/PNG для каждого
  из 11 случаев. Исторически заявленная новая матрица с тремя 413 этим гейтом не принимается.
  Отказы допустимы в рамках §7, но их нельзя выдавать за 11 готовых PNG. Нужно явно согласовать
  сценарии «PNG»/«ожидаемый терминальный отказ», не удаляя dense/corrupt/reused inputs ради зелёного отчёта.
- Некоторые малые интервалы остались raw px (например, padding подтверждения 8px и margin заголовка 4px).
  Это не уменьшает основной текст, но утверждение «абсолютно все отступы переведены в mm-токены» не подтверждается.
- PGV-14 page-set/ZIP не реализован этой проверкой. VIS-02 tri-state семантики — отдельный срез.

## 5. Воспроизведение и результаты

Из корня checkout после `npm ci`:

```bash
npm run build --workspace=@cisstat/print-renderer
node --test scripts/pgv13typocert/oracle.spec.js
node --test scripts/pgv13typocert/contracts.spec.js
```

Последняя команда на `a6429e3` **ожидаемо exit 1: 9 PASS / 3 FAIL**, без skip/xfail.
Не выдавать её за успешную сертификацию и не включать красные оракулы в default Jest.
Oracle controls: **6/6 PASS**, до реализации измерительного oracle сохранён ImportError RED.
Первоначальный черновик имел неверные ожидания формы retryability, delta/меток и band-ячеек;
они исправлены по контрактам, первоначальный лог сохранён и не считается product evidence.
HTTP double F-TYPO-03 усилен проверкой завершения и точного количества/совпадения статусов;
ранний отказ исполнения не считается подтверждением находки.

Исторический контроль чувствительности: отдельный detached `73ff44d`, собственная свежая сборка,
те же семь оракулов физической шкалы — **7 FAIL** (шесть assertion failures размера + отсутствие ptToPx).
На `a6429e3` те же семь GREEN. Исходники приложения не мутировались.

Адресный регресс: **17 Jest suites / 346 tests PASS** (вся print-зона, renderer, PGV07/08 cert);
**82 Python tests PASS** (PGV13 author39 + independent24 + local acceptance19, Memory);
renderer TypeScript build и typecheck обеих Next-оболочек PASS.
Новый полный scientific/default32/Jest-всей-платформы, PostgreSQL и Docker/VM не заявляются.

Native проверка:

```bash
node scripts/pgv13typocert/native.js --out /NEW/OUTSIDE/DIRECTORY
# Только если требуется явный путь к закреплённому браузеру:
node scripts/pgv13typocert/native.js --browser /PATH/TO/PINNED/CHROMIUM --out /ANOTHER/NEW/DIRECTORY
```

Использует compiled HTML, собственные P01/P02 и 63 граничных P01 (69 случаев),
не получает пользовательские credentials, блокирует сетевые запросы и требует chromiumSandbox=true.
Exit 0 — только local layout PASS, 1 — FAIL, 2 — BLOCKED/setup. Всегда full_pgv13_certified=false;
это не HTTP/UDS/jobs/download/PNG/OCR и не final-container acceptance.
В текущем executor системный Chromium завершился **до страницы**: ProcessSingleton `socket() EPERM`,
report BLOCKED/cases=0. Sandbox не отключался. Загрузка pinned headless shell не удалась по egress;
другой предоставленный браузер запретил локальный file URL, обход запрета не выполнялся.
Новых продуктовых PNG, физического осмотра и operator review нет.

## 6. Роуты, карта и поставка

HTTP/renderer methods/paths, DTO, OpenAPI, BFF, workers, IPC и SQL не меняются.
AUTH-00: API284 = reviewed284, bindings288, renderer4, inventory668; added/missing=[];
PGV13 task gate показывает только прежнюю пару routes относительно `fc510f0`.
`policy_review.reviewed_sources` дополнен сертификационными исходниками; inventory обновлён
официальным collector. Политики и все entries должны оставаться семантически идентичны `a6429e3`.
`scripts/local_gates.md` дополнен opt-in командами; default runner не менялся.
Строгий INDEX проверяется отдельным GIT_INDEX_FILE, пользовательский INDEX/HEAD не меняется.
Итоговые протоколы AUTH00, parity и упаковки добавляются после выполнения.

ZIP содержит только файлы `scripts/pgv13typocert/files.txt`, включая новый акт и worklog12.
Эта сертификационная поставка не требует пересборки/переключения образов, миграций или изменения VM.
Будущее изменение product guard/layout потребует согласованного релиза и новой native приёмки.

## 7. Исправленная команда из вложения

Сначала **прочитать** реальные production compose labels; candidate не выбирать:

```bash
cd /opt/cisstat/CISStat-TS-Analysis
docker ps --filter label=com.docker.compose.service=print-renderer \
  --format '{{.Names}}  project={{.Label "com.docker.compose.project"}}'
read -r -p 'Production renderer project из вывода выше: ' PGV13_RENDERER_PROJECT
: "${PGV13_RENDERER_PROJECT:?Production project required}"
: "${PGV13_BUNDLE:?Path of NEW successfully BUILT bundle required}"
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  python3 scripts/pgv13release/release.py capture \
  --bundle "$PGV13_BUNDLE" --renderer-project "$PGV13_RENDERER_PROJECT"
```

`--bundle` — новый успешно собранный bundle, **не PREV_BUNDLE**. Capture сам читает действующий
baseline; его JSON immutable. Для нестандартного stack добавить `--stack-project` с реальным именем.
Не угадывать project, не переписывать baseline и не добавлять вымышленный `--prev-bundle`.
Команда capture только сохраняет baseline и сама по себе не принимает типографику/образы.
Apply/finalize в этой проверке не выполнялись и не предлагаются как закрытие находок.
