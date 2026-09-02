"use client";

// packages/ui/components/TsAnalysisValidation.tsx
//
// ОБЩИЙ компонент фичи "Валидация" -- используется И embedded-,
// И standalone-приложением. По структуре повторяет 3-колоночный
// лейаут TsAnalysisPreprocessing, но с собственным набором проверок
// (10 критериев Data Quality) и заголовком модуля со справкой.
//
// Компоновка:
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   ▼ Признак: price   Описание               Панель управления
//   3/10 ████░░         [текстовое поле]       описание
//   ┌─Типы данных──⚠─┐  Обзор: Типы данных    [бейдж нарушения]
//   ├─Форматы────⚠─┤   [график]               [Метрики и алгоритм]
//   └────────────────┘  [Строк][Проп][Выбр]    [Полный пайплайн]
//   [Запустить валидацию]                         [действия этапа]
//
// Справка по стандартам DQ раскрывается в центральном текстовом окне
// при нажатии кнопки «Справка» в заголовке модуля.

import { useState, useRef, useEffect, useCallback } from "react";
import { Settings, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { RulesManagementPanel } from "./RulesManagementPanel";
import { ValidationCheckChart, type ValidationCheckData } from "./ValidationCheckChart";
import {
  ValidationTypeMatrix,
  type TypeValidationMode,
  type ValidationTypeProfileItem,
} from "./ValidationTypeMatrix";
import { ValidationTypePipeline } from "./ValidationTypePipeline";
import { ValidationFormatPipeline } from "./ValidationFormatPipeline";
import { ValidationRangeOverview } from "./ValidationRangeOverview";
import { ValidationRangePipeline } from "./ValidationRangePipeline";
import { ValidationConsistencyOverview } from "./ValidationConsistencyOverview";
import { ValidationConsistencyPipeline } from "./ValidationConsistencyPipeline";
import { ValidationUniquenessOverview } from "./ValidationUniquenessOverview";
import { ValidationUniquenessPipeline } from "./ValidationUniquenessPipeline";
import { ValidationInclusionOverview } from "./ValidationInclusionOverview";
import { ValidationInclusionPipeline } from "./ValidationInclusionPipeline";
import { ValidationReferentialOverview } from "./ValidationReferentialOverview";
import { ValidationReferentialPipeline } from "./ValidationReferentialPipeline";
import { ValidationTextQualityOverview } from "./ValidationTextQualityOverview";
import { ValidationTextQualityPipeline } from "./ValidationTextQualityPipeline";
import { ValidationRegularityOverview } from "./ValidationRegularityOverview";
import { ValidationRegularityPipeline } from "./ValidationRegularityPipeline";
import { ValidationSufficiencyOverview } from "./ValidationSufficiencyOverview";
import { ValidationSufficiencyPipeline } from "./ValidationSufficiencyPipeline";
import { useAppShell } from "../context/AppShellContext";
import { sessionApiUrl } from "../lib/apiClient";
import { useTargetColumn } from "../hooks/useTargetColumn";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
  ruleSource: "system" | "template" | "session" | "not_applicable";
  mode: CheckMode;
  statusReason: CheckStatusReason;
}

type CheckMode = "auto" | "enabled" | "disabled";
type CheckStatusReason = "not_required" | "disabled" | "needs_rule" | null;

interface CheckMeta {
  id: string;
  label: string;
  description: string;
}

// ── 10 критериев Data Quality (маппинг на Streamlit app.py, шаги 1-10) ──
//
// ТОЛЬКО label/description -- документационный текст, не данные. Реальные
// status/count/items приходят из GET /v1/session/dataset/validate (см.
// apps/api/routers/session.py::get_dataset_validate,
// validation/engine.py::_run_all_checks) -- подключено 2026-08-14,
// раньше весь массив (включая status/count) был статическим моком.

const CHECK_META: CheckMeta[] = [
  { id: "data_types", label: "Типы данных",
    description: "Фактический профиль фиксирует dtype и семантический класс каждой колонки. Система строит безопасный эталон типов по dtype, приводимости значений и семантике названия; сохранённая схема сессии или выбранный шаблон имеет более высокий приоритет." },
  { id: "formats", label: "Форматы и шаблоны",
    description: "Значения, не прошедшие regex-проверку (email, телефон, ИНН, дата), не могут быть использованы в автоматическом пайплайне. Проверка validate_formats выявляет все нарушения по шаблонам из rules.yaml." },
  { id: "ranges", label: "Диапазоны значений",
    description: "Выход за допустимые min/max (отрицательная цена, дата вне горизонта, процент > 100) искажает статистику и ломает модели. validate_ranges проверяет границы из rules.yaml." },
  { id: "consistency", label: "Логика и хронология",
    description: "Нарушение бизнес-правил (close < open для цен, хронология дат, монотонность индекса) делает данные внутренне противоречивыми. validate_consistency проверяет логику и хронологию." },
  { id: "uniqueness", label: "Уникальность",
    description: "Дублирующиеся строки и временные метки ломают уникальность индекса и искажают агрегации. check_uniqueness выявляет полные и частичные дубликаты." },
  { id: "inclusion", label: "Принадлежность к набору",
    description: "Значения, не входящие в допустимый справочник (код региона, категория, единица измерения), не могут быть интерпретированы. check_inclusion проверяет membership по словарям из rules.yaml." },
  { id: "referential", label: "Ссылочная целостность",
    description: "Внешние ключи, ссылающиеся на несуществующие записи в связанных таблицах, ломают JOIN-операции. validate_referential проверяет все FK-связи. Без явного правила режим «Авто» помечает остановку как «Не требуется»; режим «Включена» запрашивает настройку." },
  { id: "text_quality", label: "Целостность текста",
    description: "Мусорные символы, некорректная кодировка, пустые строки и дубликаты пробелов искажают категориальный анализ и полнотекстовый поиск. validate_text_quality выявляет все нарушения." },
  { id: "regularity", label: "Равномерность шага",
    description: "Нерегулярный временной шаг (пропуски дат, дублирование, сбой частоты) мешает STL-декомпозиции, ACF/PACF и моделям ARIMA/SARIMA. validate_regular_step проверяет частоту и gaps." },
  { id: "sufficiency", label: "Достаточность наблюдений",
    description: "Недостаточное число наблюдений для идентификации параметров модели (минимум 2×сезонный_период для SARIMA, 30+ для ADF). validate_sufficiency оценивает длину ряда и выдаёт рекомендации." },
];

const DEFAULT_CHECK_MODES: Record<string, CheckMode> = Object.fromEntries(
  CHECK_META.map(({ id }) => [id, "auto"])
);

const RULE_SOURCE_LABELS: Record<Check["ruleSource"], string> = {
  system: "Системное правило",
  template: "Шаблон правил",
  session: "Правило сессии",
  not_applicable: "Правило не задано",
};

// NUMERIC_FEATURES-мок убран (2026-08-14) -- реальные колонки приходят
// из useTargetColumn().availableColumns (тот же GET /target-column, что
// и в Загрузке/Моделировании). Раньше "Price" в этом селекторе было
// совпадением: мок-список тикеров содержал 'price' первым, никак не
// связано с реальным выбором пользователя на Загрузке.

// ── Справка по стандартам качества данных ────────────────────

const DQ_STANDARDS_HELP = `Стандарты качества данных (Data Quality)

Модуль «Валидация» реализует комплексную проверку данных по 10 критериям, основанным на международной классификации DAMA DMBOK (Data Management Body of Knowledge) и дополненным спецификой временных рядов.

Классификация проверок по категориям DAMA:

1. Полнота (Completeness)
   - Пропуски (NaN, null, пустые строки) — критичны для временных рядов, ломают DatetimeIndex и STL-декомпозицию.

2. Достоверность (Accuracy)
   - Диапазоны значений — выход за допустимые min/max.
   - Типы данных — несоответствие dtype схеме (строка вместо числа).

3. Согласованность (Consistency)
   - Логика и хронология — бизнес-правила (close >= open) и монотонность индекса.
   - Ссылочная целостность — FK-связи между таблицами.
   - Равномерность шага — частота и gaps временного ряда.

4. Уникальность (Uniqueness)
   - Дубликаты строк и временных меток.

5. Валидность (Validity)
   - Форматы и шаблоны — regex-проверка (email, ИНН, дата).
   - Принадлежность к набору — membership в справочниках.

6. Целостность текста (Integrity)
   - Мусорные символы, кодировка, нормализация пробелов.

7. Достаточность (Sufficiency)
   - Минимальное число наблюдений для идентификации модели (2×сезонный_период для SARIMA, 30+ для ADF).

Интегральный Data Quality Score (DQ) равен доле успешно пройденных среди фактически выполненных применимых проверок. Остановки «Не требуется», «Отключено» и ещё не настроенные проверки не входят в знаменатель. Порог DQ >= 0.8 считается достаточным для передачи данных в модуль «Предобработка».

Ссылки:
- DAMA DMBOK, 2nd Edition, Chapter 13: Data Quality
- ISO 8000 — Data Quality Standard
- Практика Data Quality в финансовой аналитике (CBR, MOEX)`;

const DATA_TYPES_METRICS_DESCRIPTION = `Метрики и алгоритм: Типы данных

Цель
Проверка отделяет фактический профиль колонок от проверки соответствия ожидаемой схеме. Это исключает круговую валидацию, при которой dtype, найденный в самом датасете, ошибочно используется как эталон и всегда даёт «0 нарушений».

Метрики
1. Фактический профиль типов — для каждой колонки: pandas dtype, семантический класс (numeric, datetime, categorical или text), число непустых, пропусков и уникальных значений.
2. N_type = Σ n_i — суммарное число нарушений схемы по всем проверяемым колонкам.
3. r_type = N_type / N_non_null — доля значений, не приведённых к ожидаемому типу; при отсутствии непустых значений метрика не вычисляется.
4. Покрытие схемой = C_schema / C_total — доля колонок, для которых объявлен ожидаемый тип.

Алгоритм backend
1. GET /v1/session/dataset/validate получает полный DataFrame активной сессии.
2. Общая функция профилирования, уже используемая вкладкой «Загрузка», вычисляет фактические dtype и семантические классы без повторной реализации.
3. Если задана Pandera-схема, backend строит DataFrameSchema, выполняет lazy-валидацию с разрешённым правилами приведением типов и агрегирует failure cases.
4. status = done означает, что схема задана и нарушений нет; warning — найдены нарушения; pending используется, когда аналитик принудительно включил проверку, но её эталон ещё не настроен; skipped — нейтральный пропуск.

Источники правил
Если аналитик не сохранил собственную схему и не выбрал шаблон, backend строит безопасный системный эталон по dtype, приводимости значений и семантике названия колонки. Приоритет разрешения правил: схема и переопределения сессии → выбранный шаблон → системные правила. Поэтому после общего запуска проверка типов всегда получает однозначный статус: «Проверка пройдена» либо «Найдены проблемы».`;

const DATA_TYPES_PIPELINE_DESCRIPTION = `Мастер исправления типов

1. Отметьте проблемные колонки и задайте для каждой ожидаемый тип.
2. Сохраните эталон и проверьте датасет относительно него.
3. Выберите политику ошибок: отклонить весь набор либо заменить неприводимые значения пропусками.
4. Запустите предпросмотр. Предпросмотр не изменяет датасет и показывает последствия преобразования.
5. Подтвердите применение. Изменения сохраняются атомарно, после чего проверка типов запускается повторно.`;

const FORMATS_METRICS_DESCRIPTION = `Метрики и алгоритм: Форматы и шаблоны

Цель
Проверка находит непустые значения, которые не дают полное совпадение регулярному выражению из активных правил валидации. Пропуски обрабатываются отдельным критерием качества и здесь нарушениями не считаются.

Метрики
1. N_format — число значений, не совпавших с regex.
2. % match = N_valid / N_non_null × 100 — доля корректных непустых значений.
3. Порог соответствия берётся из правила колонки; примеры нарушений ограничиваются пятью уникальными значениями.

Алгоритм backend
1. Resolver выбирает правила в порядке: переопределения сессии → шаблон → системные правила.
2. Для каждой существующей колонки выполняется pandas.Series.str.fullmatch(pattern), то есть проверяется всё значение, а не отдельный фрагмент.
3. GET /v1/session/dataset/format-profile возвращает полный regex, метрики и примеры; общая валидация использует ту же функцию профилирования.
4. Нет применимого правила — статус «Эталон форматов не задан»; 0 нарушений — «Проверка пройдена»; нарушения — «Найдены проблемы».`;

const FORMATS_PIPELINE_DESCRIPTION = `Мастер исправления форматов и шаблонов

1. Выберите проблемные колонки и стратегию исправления.
2. Используйте правила текущей сессии: браузер не подменяет регулярные выражения.
3. Выберите одно из действий Streamlit: заменить нарушения пропусками, выполнить безопасную подстановку, нормализовать строки либо добавить флаг валидности.
4. Запустите предпросмотр на копии датасета и оцените, сколько нарушений останется.
5. Подтвердите применение. Изменения сохраняются атомарно, после чего общая валидация запускается повторно.`;

const RANGES_METRICS_DESCRIPTION = `Метрики и алгоритм: Диапазоны значений

Цель
Проверка сопоставляет числовые значения с предметными нижней и верхней границами. Пропуски здесь не считаются нарушениями: для них предназначена отдельная проверка полноты.

Метрики
1. N_range — количество непустых значений, для которых x < min или x > max.
2. r_range = N_range / N_non_null × 100 — доля нарушений среди непустых значений.
3. Фактические min/max показывают охват наблюдаемых данных, допустимые min/max — активный эталон.
4. Покрытие = число числовых колонок с применимым правилом / общее число числовых колонок.

Алгоритм backend
1. Resolver выбирает правила в порядке: переопределения сессии → шаблон → безопасная системная семантика.
2. Правило сопоставляется с числовой колонкой по ключевым словам без учёта регистра.
3. Единая векторная маска отмечает значения ниже min и выше max; она используется общей валидацией, профилем и мастером исправления.
4. Нет применимого правила — «Эталон диапазонов не задан»; 0 нарушений — «Проверка пройдена»; нарушения — «Найдены проблемы».

Система назначает встроенные границы только для однозначной семантики: цена неотрицательна, год 1900–2100, процент 0–100. Для неизвестной числовой колонки границы из её фактических min/max не выводятся, поскольку такая круговая проверка всегда проходила бы.`;

const RANGES_PIPELINE_DESCRIPTION = `Мастер исправления диапазонов

1. Выберите колонки с нарушениями и проверьте активные min/max.
2. Выберите стратегию Streamlit: кэпирование, медиана корректных значений, пропуск, удаление строк либо флаг валидности.
3. Запустите предпросмотр на глубокой копии датасета. Он показывает число изменённых значений, оставшихся нарушений и удаляемых строк.
4. Подтвердите применение. Подготовленная копия сохраняется атомарно, после чего общая валидация запускается повторно.

Неоднозначная Streamlit-стратегия «0 или NaN» разделена: веб-мастер использует безопасный пропуск, потому что 0 сам может нарушать положительную нижнюю границу.`;

const CONSISTENCY_METRICS_DESCRIPTION = `Метрики и алгоритм: Логика и хронология

Цель
Проверка выявляет два класса внутренних противоречий: нарушение порядка времени внутри ряда или панели и несоблюдение явно заданных связей между колонками. Предметные связи не выводятся из наблюдаемых значений, поскольку это создавало бы круговой эталон.

Метрики
1. N_logic — число нарушенных сравнений: временных переходов либо строк, не удовлетворяющих бизнес-правилу.
2. r_logic = N_logic / N_checked × 100 — доля нарушений среди реально сопоставимых переходов или строк.
3. Affected rows — число строк, участвующих в нарушениях; для одного обратного временного перехода отмечаются обе соседние строки.
4. Покрытие — число применимых правил относительно всех настроенных правил.

Алгоритм backend
1. Resolver выбирает правила в порядке: переопределения сессии → шаблон → безопасная системная хронология.
2. Единый профилировщик правил строит маски для общей валидации, обзора и мастера исправления.
3. Хронология проверяется в исходном порядке отдельно внутри каждой группы. Бизнес-правила используют ограниченный набор типизированных сравнений без eval() и выполнения произвольного кода.
4. Несопоставившееся или неподдерживаемое правило получает «Не применимо» и не может дать ложный статус «Проверка пройдена».

Система автоматически задаёт только базовую хронологию при уверенно распознанной колонке года/даты. Сравнения выручки и прибыли, начала и окончания периода и другие предметные связи задаются через «Управление правилами».`;

const CONSISTENCY_PIPELINE_DESCRIPTION = `Мастер исправления логики и хронологии

1. Выберите применимые правила с найденными нарушениями и изучите примеры конфликтов.
2. Выберите совместимую стратегию: групповая сортировка для хронологии, удаление затронутых строк, перенос конфликтующего значения в пропуск или добавление флага.
3. Запустите предпросмотр на глубокой копии датасета. Он показывает нарушения до и после, число изменённых значений, удаляемых строк и новые колонки.
4. Подтвердите применение. Копия сохраняется атомарно, метаданные сессии обновляются, затем общая валидация запускается повторно.

Небезопасная Streamlit-замена медианой/модой исключена: она не гарантирует соблюдение связи между колонками. Сортировка учитывает группирующую колонку правила и сохраняет порядок групп.`;

const UNIQUENESS_METRICS_DESCRIPTION = `Метрики и алгоритм: Уникальность

Цель
Проверка выявляет повторяющиеся записи по предметному составному ключу или по безопасному системному ключу. Для временных рядов дубли ключа «сущность + время» создают неоднозначный индекс и искажают агрегации, resample, STL и прогнозирование.

Метрики
1. Duplicate rows — все строки, входящие в группы с одинаковым ключом; соответствует duplicated(keep=False).
2. Duplicate groups — число различных значений ключа, повторившихся более одного раза.
3. Redundant rows — число реально лишних копий после сохранения одной строки каждой группы.
4. r_dup = Duplicate rows / N_rows × 100 — доля строк в группах дублей.

Алгоритм backend
1. Resolver выбирает ключ в порядке: правило сессии → шаблон → системная логика.
2. Система ищет уверенно распознанные колонки сущности и времени; если времени нет, проверяет полные строки.
3. Единый profile_uniqueness используется общей валидацией, обзором и мастером — счётчики не расходятся.
4. Явный ключ применяется только целиком. Отсутствующая колонка делает правило неприменимым, а не сокращает ключ и не создаёт ложное «Проверка пройдена».

Составной ключ можно изменить в «Управлении правилами». Для FAO шаблон задаёт Country + Year.`;

const UNIQUENESS_PIPELINE_DESCRIPTION = `Мастер исправления уникальности

1. Проверьте активный ключ и группы повторов. Различайте все строки в дублях и реально лишние копии.
2. Выберите стратегию Streamlit: оставить первую или последнюю строку, удалить всю группу, агрегировать mean/first либо добавить флаг.
3. Запустите предпросмотр на глубокой копии. Он показывает точное число удаляемых строк и оставшихся дублей без изменения датасета.
4. Подтвердите применение. Копия сохраняется атомарно, метаданные сессии обновляются, затем общая валидация запускается повторно.

Агрегация доступна только для ключевой проверки: числовые неключевые значения усредняются, категориальные сохраняют первое значение. При проверке полных строк эта стратегия не имеет смысла и скрыта.`;

const INCLUSION_METRICS_DESCRIPTION = `Метрики и алгоритм: Принадлежность к набору

Цель
Проверка сопоставляет каждое непустое значение с явным предметным справочником. Допустимый набор нельзя выводить из того же датасета: такой круговой эталон по определению пропустил бы все наблюдаемые ошибки.

Метрики
1. N_inclusion — число непустых значений вне допустимого набора.
2. r_inclusion = N_inclusion / N_non_null × 100 — доля нарушений среди проверенных значений.
3. Покрытие — число существующих колонок с непустым правилом набора.
4. Частоты недопустимых значений помогают отличить единичную опечатку от системного нового кода.

Алгоритм backend
1. Resolver выбирает правило в порядке: override сессии → выбранный шаблон; системный слой не выдумывает предметный справочник.
2. profile_inclusion нормализует новый YAML-формат allowed_values и прежний формат списка.
3. Единая векторная маска membership используется общей валидацией, обзором и мастером исправления.
4. Нет применимого правила — «Эталон допустимых наборов не задан»; 0 нарушений — «Проверка пройдена»; нарушения — «Найдены проблемы».`;

const INCLUSION_PIPELINE_DESCRIPTION = `Мастер исправления принадлежности к набору

1. Проверьте активный допустимый набор и отметьте колонки с нарушениями.
2. Выберите стратегию: мода среди корректных значений, явное значение по умолчанию, пропуск, удаление строк либо флаг валидности.
3. Запустите предпросмотр на глубокой копии и оцените число изменений, оставшихся нарушений и удаляемых строк.
4. Подтвердите применение. Копия сохраняется атомарно, после чего общая валидация запускается повторно.

Значение по умолчанию разрешено только когда оно явно входит в справочник. Мода вычисляется только по уже допустимым наблюдениям.`;

const REFERENTIAL_METRICS_DESCRIPTION = `Метрики и алгоритм: Ссылочная целостность

Цель
Проверка выявляет «сиротские» дочерние ключи: непустые значения child_column, для которых нет соответствующего ключа в явно заданном родительском справочнике. Такие записи ломают JOIN, агрегирование панелей и многомерные модели.

Метрики
1. N_ref — число проверенных непустых дочерних ключей.
2. N_orphan — число записей, отсутствующих в справочнике родительских ключей.
3. r_orphan = N_orphan / N_ref × 100 — доля сиротских записей.
4. Покрытие связи — число уникальных родительских ключей и частоты сиротских значений.

Алгоритм backend
1. Resolver выбирает правила сессии → шаблон → системный слой.
2. Для каждого явного правила проверяются child_column и непустой allowed_values. Строковые значения редактора безопасно приводятся к dtype дочерней колонки.
3. Векторная маска child.notna() & ~child.isin(parent_keys) используется общей валидацией, обзором и мастером.
4. Ноль сирот при применимом правиле означает «Проверка пройдена». Без явной связи режим «Авто» даёт нейтральное «Не требуется», а режим «Включена» — «Требуется настройка».

Платформа не выводит родительский справочник из самого исследуемого датасета: это сделало бы проверку круговой и автоматически признало бы любую сироту корректной.`;

const REFERENTIAL_PIPELINE_DESCRIPTION = `Мастер исправления ссылочной целостности

1. Проверьте дочернюю колонку, эталон родительских ключей и найденные сиротские значения.
2. Выберите безопасную стратегию: мода среди связанных значений, явный допустимый default, пропуск, удаление строк либо флаг связности.
3. Выполните предпросмотр на глубокой копии и оцените исправленные значения, оставшиеся сироты, удаляемые строки и добавляемые колонки.
4. Подтвердите применение. Копия сохраняется атомарно, после чего общая валидация запускается повторно.

Default разрешён только когда он входит в родительский справочник; мода вычисляется только по уже связанным наблюдениям.`;

const TEXT_QUALITY_METRICS_DESCRIPTION = `Метрики и алгоритм: Целостность текста

Цель
Проверка находит скрытые управляющие символы и артефакты кодировки, пустые строки, слишком короткие и длинные значения, пробелы по краям и повторяющиеся пробелы. Если для колонки явно задан разрешённый regex, он также участвует в проверке.

Метрики
1. N_text — число строк хотя бы с одним нарушением; одна строка не суммируется повторно при нескольких причинах.
2. r_text = N_text / N_non_null × 100 — доля проблемных непустых значений.
3. Разбивка по причинам: мусор, пустые, длина, пробелы и шаблон.
4. Примеры ограничены пятью уникальными значениями и помогают оценить стратегию очистки.

Алгоритм backend
1. Системная проверка автоматически применяется ко всем object/string-колонкам; ручной эталон для старта не требуется.
2. Общая функция profile_text_quality строит отдельные векторные маски причин и их объединение.
3. Те же маски используют общая валидация, обзор и мастер исправления — расхождение счётчиков исключено.
4. Пропуски не считаются нарушением текста: их обрабатывает отдельная остановка предобработки. Нет текстовых колонок — «Не требуется»; 0 нарушений — «Проверка пройдена»; нарушения — «Найдены проблемы».`;

const TEXT_QUALITY_PIPELINE_DESCRIPTION = `Мастер исправления целостности текста

1. Отметьте текстовые колонки с найденными нарушениями.
2. Выберите стратегию Streamlit: очистка и нормализация, замена пропуском, замена на «Неизвестно», удаление строк либо флаг валидности.
3. Выполните предпросмотр на глубокой копии и проверьте число изменений, оставшихся нарушений, удаляемых строк и новых колонок.
4. Подтвердите применение. Копия сохраняется атомарно, после чего общая валидация запускается повторно.

Нормализация удаляет управляющие и повреждённые символы, обрезает края, сжимает пробелы и приводит текст к нижнему регистру. Она может объединить ранее разные категории, поэтому результат обязательно показывается до применения.`;

const REGULARITY_METRICS_DESCRIPTION = `Метрики и алгоритм: Равномерность шага

Цель
Проверка определяет, упорядочены ли временные метки и образуют ли они стабильную сетку отдельно внутри каждой сущности панельного датасета. Нерегулярность мешает корректной интерполяции, STL, ACF/PACF и моделям семейства ARIMA.

Метрики
1. Некорректные даты — непустые значения, которые нельзя преобразовать во временную метку.
2. Нарушения сортировки — переходы назад во времени в исходном порядке строк.
3. Дубли дат — повторные метки внутри одной сущности.
4. Разрывы — интервалы больше модального шага × порог; отдельно оценивается число пропущенных периодов.

Алгоритм backend
1. Resolver использует явные date_column, entity_column, frequency и порог из правил сессии; иначе применяет системные детекторы структуры.
2. Профиль строится отдельно по каждой группе и не смешивает временные шкалы разных сущностей.
3. Общая валидация, обзор и мастер используют один профиль причин нарушений.
4. Нет надёжной временной оси — «Не требуется» в режиме «Авто» или «Требуется настройка» в режиме «Включена»; ноль причин — «Проверка пройдена».`;

const REGULARITY_PIPELINE_DESCRIPTION = `Мастер исправления равномерности шага

1. Проверьте определённые системой временную ось, группировку, частоту и найденные причины нерегулярности.
2. Выберите стратегию Streamlit: сортировка, построение полной сетки с интерполяцией/протяжкой/пропусками, фиктивные нули либо диагностический флаг.
3. Выполните предпросмотр на глубокой копии и оцените добавленные строки, агрегированные дубли и оставшиеся нарушения.
4. Подтвердите применение. Датасет сохраняется атомарно, затем общая валидация запускается повторно.

Ресемплирование выполняется отдельно внутри каждой сущности. Некорректные даты требуют сначала исправить тип или формат; ошибки преобразования не скрываются.`;

const SUFFICIENCY_METRICS_DESCRIPTION = `Метрики и алгоритм: Достаточность наблюдений

Цель
Проверка определяет, для каких классов методов длины каждого временного ряда достаточно. Это ограничение применимости моделей, а не ошибка отдельных строк.

Метрики
1. Валидные наблюдения — строки, где одновременно корректны временная метка и числовое значение исследуемого признака.
2. Уникальные временные метки — фактическая длина временной оси без дублей.
3. Эквивалент сезонных циклов — число уникальных меток, делённое на сезонный период из правил или системной частоты.
4. Недоступные требования — пороги тренда, сезонности, ARIMA/ETS, FFT, ML и минимального числа циклов, которые группа не выполняет.

Алгоритм backend
1. Resolver использует явные date_column, entity_column, target_column, частоту и пороги правил; иначе применяет системные детекторы и активный исследуемый признак.
2. Расчёт выполняется отдельно по каждой сущности и не смешивает панельные ряды.
3. Общая валидация, обзор и мастер используют один профиль достаточности.
4. Порог означает доступность класса методов, а точные ограничения конкретной модели дополнительно проверяются на этапе «Моделирование».`;

const SUFFICIENCY_PIPELINE_DESCRIPTION = `Мастер решений по достаточности

1. Проверьте целевой ряд, временную ось, группировку, частоту и пороги применимости.
2. Выберите безопасное решение: ограничить набор моделей, добавить диагностический флаг либо исключить недостаточные группы панельного ряда.
3. Выполните предпросмотр и оцените охват, добавляемые признаки или число удаляемых строк.
4. Подтвердите решение. План сохраняется в сессии, затем общая валидация запускается повторно.

Мастер не создаёт синтетические наблюдения и не предлагает агрегацию как способ увеличить n: агрегация уменьшает длину ряда. Сбор новых данных остаётся внешним организационным действием.`;

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisValidation() {
  const { activeDataset } = useAppShell();
  const [activeCheckId, setActiveCheckId] = useState(CHECK_META[0].id);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | "rules" | null>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // ── Единый "исследуемый признак" (target_column) для всей платформы
  // (2026-08-14) -- тот же хук, что и в Загрузке. Раньше activeFeature
  // был отдельным useState(NUMERIC_FEATURES[0]) -- мок-список тикеров,
  // никак не связанный с реальным выбором пользователя на Загрузке.
  const {
    targetColumn: activeFeature,
    availableColumns: numericFeatures,
    setColumn: setActiveFeature,
    refetch: refetchTargetColumn,
  } = useTargetColumn(activeDataset?.name);

  // ── Реальная валидация датасета сессии (GET /dataset/validate) ──
  // Заменяет статический мок -- см. apps/api/routers/session.py::get_dataset_validate,
  // validation/engine.py::_run_all_checks (подключено 2026-08-14).
  // column=activeFeature (2026-08-14) -- часть проверок (ranges/formats/
  // inclusion/referential/text_quality/sufficiency) скоупятся до
  // выбранного признака, часть принципиально dataset-wide -- см.
  // ValidationCheckData.scope и докстринг _run_all_checks.
  const [checksData, setChecksData] = useState<Record<string, ValidationCheckData> | null>(null);
  const [checksLoading, setChecksLoading] = useState(false);
  const [datasetSummary, setDatasetSummary] = useState<{ totalRows: number; totalColumns: number } | null>(null);
  const [typeProfile, setTypeProfile] = useState<ValidationTypeProfileItem[]>([]);
  const [typeValidationMode, setTypeValidationMode] = useState<TypeValidationMode>("profile");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validationHasRun, setValidationHasRun] = useState(false);
  const [validationVersion, setValidationVersion] = useState(0);
  const [checkModes, setCheckModes] = useState<Record<string, CheckMode>>(DEFAULT_CHECK_MODES);
  const [modeSaving, setModeSaving] = useState<string | null>(null);
  const [modeError, setModeError] = useState<{ checkId: string; message: string } | null>(null);
  const validationRequestId = useRef(0);

  const fetchValidation = useCallback(async () => {
    if (!activeDataset) {
      setChecksData(null);
      setDatasetSummary(null);
      setTypeProfile([]);
      setTypeValidationMode("profile");
      setValidationError(null);
      setValidationHasRun(false);
      setChecksLoading(false);
      return;
    }
    const requestId = ++validationRequestId.current;
    setChecksLoading(true);
    setValidationError(null);
    const url = sessionApiUrl("/dataset/validate");
    try {
      const response = await fetch(url, { credentials: "include" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (requestId !== validationRequestId.current || !data) return;
      setChecksData(data.checks);
      setCheckModes((current) => ({
        ...current,
        ...Object.fromEntries(
          Object.entries(data.checks ?? {})
            .filter(([, value]) => Boolean((value as ValidationCheckData).mode))
            .map(([id, value]) => [id, (value as ValidationCheckData).mode as CheckMode])
        ),
      }));
      setDatasetSummary({ totalRows: data.total_rows, totalColumns: data.total_columns });
      setTypeProfile(Array.isArray(data.type_profile) ? data.type_profile : []);
      setTypeValidationMode(data.type_validation_mode === "schema" ? "schema" : "profile");
      setValidationHasRun(true);
      setValidationVersion((current) => current + 1);
    } catch {
      if (requestId !== validationRequestId.current) return;
      setChecksData(null);
      setDatasetSummary(null);
      setTypeProfile([]);
      setTypeValidationMode("profile");
      setValidationError("Не удалось выполнить проверку");
      setValidationHasRun(true);
    } finally {
      if (requestId === validationRequestId.current) setChecksLoading(false);
    }
  }, [activeDataset]);

  useEffect(() => {
    validationRequestId.current += 1;
    setChecksData(null);
    setDatasetSummary(null);
    setTypeProfile([]);
    setTypeValidationMode("profile");
    setValidationError(null);
    setValidationHasRun(false);
    setValidationVersion(0);
    setCheckModes(DEFAULT_CHECK_MODES);
    setModeSaving(null);
    setModeError(null);
    setChecksLoading(false);
    return () => {
      validationRequestId.current += 1;
    };
  }, [activeDataset?.name]);

  useEffect(() => {
    if (!activeDataset) return;
    let cancelled = false;
    const fetchModes = async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/validation-check-modes"), {
          credentials: "include",
        });
        if (!response.ok) return;
        const data = await response.json();
        if (!cancelled && data?.modes) {
          setCheckModes({ ...DEFAULT_CHECK_MODES, ...data.modes });
        }
      } catch {
        // Старый API не блокирует основную валидацию: остаётся режим «Авто».
      }
    };
    void fetchModes();
    return () => {
      cancelled = true;
    };
  }, [activeDataset?.name]);

  // Реальные status/count поверх статических label/description. Пока
  // датасет не загружен или проверка ещё не пришла -- честное "pending",
  // не фейковый 0.
  const CHECKS: Check[] = CHECK_META.map((meta) => ({
    ...meta,
    status: checksData?.[meta.id]?.status ?? "pending",
    count: checksData?.[meta.id]?.count ?? null,
    ruleSource: checksData?.[meta.id]?.rule_source ?? "not_applicable",
    mode: checksData?.[meta.id]?.mode ?? checkModes[meta.id] ?? "auto",
    statusReason: checksData?.[meta.id]?.status_reason ?? null,
  }));

  // Сворачиваем при смене секции
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [descriptionSection]);

  // Click-outside: сворачиваем при клике вне description box
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (descRef.current && !descRef.current.contains(e.target as Node)) {
      setDescriptionExpanded(false);
    }
  }, []);
  useEffect(() => {
    if (descriptionExpanded) {
      document.addEventListener("mousedown", handleOutsideClick);
      return () => document.removeEventListener("mousedown", handleOutsideClick);
    }
  }, [descriptionExpanded, handleOutsideClick]);

  // Отключённые и автоматически неприменимые остановки нейтральны: они
  // исключаются из DQ Score и знаменателя прогресса. Pending означает,
  // что включённая аналитиком проверка ещё требует настройки.
  const applicableChecks = CHECKS.filter((c) => c.status !== "skipped");
  const evaluatedChecks = applicableChecks.filter((c) => c.status === "done" || c.status === "warning");
  const doneCount = evaluatedChecks.filter((c) => c.status === "done").length;
  const dqScore = evaluatedChecks.length > 0 ? doneCount / evaluatedChecks.length : null;
  const progressPct = applicableChecks.length > 0
    ? Math.round((evaluatedChecks.length / applicableChecks.length) * 100)
    : 100;
  const activeCheck = CHECKS.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...CHECKS].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  const displayedStatus = (check: Check): CheckStatus =>
    check.status === "pending" && check.statusReason === "needs_rule" ? "warning" : check.status;

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  const runValidation = () => {
    if (!activeDataset) return;
    void fetchValidation();
  };

  const handleCheckModeChange = async (checkId: string, mode: CheckMode) => {
    if (!activeDataset || modeSaving) return;
    const previousModes = checkModes;
    setCheckModes((current) => ({ ...current, [checkId]: mode }));
    setModeSaving(checkId);
    setModeError(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/validation-check-modes"), {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modes: { [checkId]: mode } }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data?.modes) setCheckModes({ ...DEFAULT_CHECK_MODES, ...data.modes });
      if (validationHasRun) await fetchValidation();
    } catch {
      setCheckModes(previousModes);
      setModeError({ checkId, message: "Не удалось сохранить режим проверки" });
    } finally {
      setModeSaving(null);
    }
  };

  // Показать справку по стандартам DQ
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? null : "help");
  };

  // Показать/скрыть «Управление правилами»
  const handleRulesClick = () => {
    setDescriptionSection((prev) => prev === "rules" ? null : "rules");
  };

  // ── Overflow detection для expandable description ──
  useEffect(() => {
    const el = descRef.current;
    if (!el) return;
    const checkOverflow = () => {
      setHasOverflow(el.scrollHeight > el.clientHeight + 2);
    };
    checkOverflow();
    const observer = new ResizeObserver(checkOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [descriptionSection]); // ResizeObserver отслеживает контент

  // Текст описания для центрального поля
  const descriptionContent = (() => {
    if (descriptionSection === "help") return DQ_STANDARDS_HELP;
    if (descriptionSection === "rules") return null; // RulesManagementPanel рендерится отдельно
    if (!descriptionSection) return null;
    if (descriptionSection === "metrics") {
      if (activeCheck.id === "data_types") return DATA_TYPES_METRICS_DESCRIPTION;
      if (activeCheck.id === "formats") return FORMATS_METRICS_DESCRIPTION;
      if (activeCheck.id === "ranges") return RANGES_METRICS_DESCRIPTION;
      if (activeCheck.id === "consistency") return CONSISTENCY_METRICS_DESCRIPTION;
      if (activeCheck.id === "uniqueness") return UNIQUENESS_METRICS_DESCRIPTION;
      if (activeCheck.id === "inclusion") return INCLUSION_METRICS_DESCRIPTION;
      if (activeCheck.id === "referential") return REFERENTIAL_METRICS_DESCRIPTION;
      if (activeCheck.id === "text_quality") return TEXT_QUALITY_METRICS_DESCRIPTION;
      if (activeCheck.id === "regularity") return REGULARITY_METRICS_DESCRIPTION;
      if (activeCheck.id === "sufficiency") return SUFFICIENCY_METRICS_DESCRIPTION;
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    if (activeCheck.id === "data_types") return DATA_TYPES_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "formats") return FORMATS_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "ranges") return RANGES_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "consistency") return CONSISTENCY_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "uniqueness") return UNIQUENESS_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "inclusion") return INCLUSION_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "referential") return REFERENTIAL_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "text_quality") return TEXT_QUALITY_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "regularity") return REGULARITY_PIPELINE_DESCRIPTION;
    if (activeCheck.id === "sufficiency") return SUFFICIENCY_PIPELINE_DESCRIPTION;
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка по стандартам качества данных";
    if (descriptionSection === "rules") return "Управление правилами валидации";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (descriptionSection === "metrics") return `Метрики и алгоритм — ${activeCheck.label}`;
    if (activeCheck.id === "data_types") return "Мастер исправления типов";
    if (activeCheck.id === "formats") return "Мастер исправления форматов и шаблонов";
    if (activeCheck.id === "ranges") return "Мастер исправления диапазонов";
    if (activeCheck.id === "consistency") return "Мастер исправления логики и хронологии";
    if (activeCheck.id === "uniqueness") return "Мастер исправления уникальности";
    if (activeCheck.id === "inclusion") return "Мастер исправления принадлежности к набору";
    if (activeCheck.id === "referential") return "Мастер исправления ссылочной целостности";
    if (activeCheck.id === "text_quality") return "Мастер исправления целостности текста";
    if (activeCheck.id === "regularity") return "Мастер исправления равномерности шага";
    if (activeCheck.id === "sufficiency") return "Мастер решений по достаточности";
    return `Полный пайплайн — ${activeCheck.label}`;
  })();

  return (
    <div className="flex gap-6">
      {/* ── ЛЕВАЯ КОЛОНКА: селектор признака + прогресс + степпер ── */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        {/* Заголовок модуля + справка */}
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-neutral-800">
              Data Quality
            </h2>
            <button
              onClick={handleHelpClick}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                descriptionSection === "help"
                  ? "bg-brand text-white"
                  : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
              }`}
            >
              Справка
            </button>
          </div>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Контроль качества данных
          </p>
        </div>

        {/* Селектор числового признака */}
        {numericFeatures.length > 0 && (
          <div>
            <label className="text-[11px] text-neutral-500 block mb-1">
              Исследуемый признак:
            </label>
            <select
              value={activeFeature ?? numericFeatures[0]}
              onChange={(e) => setActiveFeature(e.target.value)}
              className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
            >
              {numericFeatures.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        )}

        <Button
          disabled={!activeDataset || checksLoading}
          onClick={runValidation}
          className="w-full disabled:cursor-not-allowed disabled:opacity-50"
        >
          {checksLoading ? "Валидация выполняется…" : "Запустить валидацию"}
        </Button>

        {/* Прогресс */}
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-neutral-500 tabular-nums">
            {evaluatedChecks.length}/{applicableChecks.length}
          </p>
          <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
            <div
              className="bg-brand h-1.5 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Степпер: прямоугольные карточки с текстом + иконка */}
        <div className="flex flex-col gap-1.5">
          {CHECKS.map((check) => (
            <button
              key={check.id}
              onClick={() => {
                setActiveCheckId(check.id);
                if (check.id !== activeCheckId) setDescriptionSection(null);
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                check.id === activeCheckId
                  ? "bg-brand text-white border-brand"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{check.label}</span>
              <span className="ml-2 shrink-0">
                {validationHasRun && check.status === "skipped" ? (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    check.id === activeCheckId ? "bg-white/20 text-white" : "bg-neutral-100 text-neutral-600"
                  }`}>
                    {check.statusReason === "disabled" ? "Отключено" : "Не требуется"}
                  </span>
                ) : validationHasRun && check.status === "pending" && check.statusReason === "needs_rule" ? (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    check.id === activeCheckId ? "bg-white/20 text-white" : "bg-amber-50 text-amber-700"
                  }`}>
                    Настроить
                  </span>
                ) : validationHasRun && ["formats", "ranges", "consistency", "uniqueness", "inclusion"].includes(check.id) && check.status === "pending" && check.ruleSource === "not_applicable" ? (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    check.id === activeCheckId ? "bg-white/20 text-white" : "bg-amber-50 text-amber-700"
                  }`}>
                    Нет эталона
                  </span>
                ) : (
                  <StatusIcon status={displayedStatus(check)} />
                )}
              </span>
            </button>
          ))}
        </div>

        {/* ── Кнопка «Управление правилами» — внизу степпера ── */}
        {/* Визуально отличается от степпер-бейджей: dashed border, */}
        {/* brand-colored text, Settings icon — не заливка, а outline-стиль */}
        <div className="mt-3 pt-3 border-t border-neutral-200">
          <button
            onClick={handleRulesClick}
            data-testid="rules-management-btn"
            className={`w-full flex items-center justify-center gap-2 rounded-md border-2 border-dashed px-3 py-2.5 text-sm font-medium transition-colors ${
              descriptionSection === "rules"
                ? "border-brand bg-brand/10 text-brand"
                : "border-brand/40 text-brand hover:border-brand hover:bg-brand/5"
            }`}
          >
            <Settings size={16} />
            Управление правилами
          </button>
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: описание + график + метрики ── */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Описание
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          {/* ── Expandable Description Box ──
              collapsed: min-h=220px, max-h=220px, scroll (in-flow)
              expanded: position:absolute overlay over graph, max-h=calc(100vh-180px)
              chevron: shown only when hasOverflow
          */}
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px] bg-brand-light"
                  : "max-h-[220px] min-h-[220px] bg-brand-light/50"
              }`}
            >
              {descriptionSection === "rules" ? (
                <RulesManagementPanel onRulesApplied={runValidation} />
              ) : descriptionContent ? (
                descriptionContent
              ) : (
                <span className="text-neutral-400 italic">
                  Нажмите «Метрики и алгоритм», «Исправить этап проверки», «Справка» или «Управление правилами»
                </span>
              )}
              {/* Collapse chevron — sticky прилипает к низу scroll-области */}
              {descriptionExpanded && (
                <div className="sticky bottom-0 flex justify-center py-1 bg-brand-light rounded-b-lg">
                  <button
                    onClick={() => setDescriptionExpanded(false)}
                    className="flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                    aria-label="Свернуть описание"
                    data-testid="desc-collapse-btn"
                  >
                    <ChevronUp size={14} />
                  </button>
                </div>
              )}
            </div>
            {/* Expand chevron — только при overflow, collapsed */}
            {hasOverflow && !descriptionExpanded && (
              <button
                onClick={() => setDescriptionExpanded(true)}
                className="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                aria-label="Развернуть описание"
                data-testid="desc-expand-btn"
              >
                <ChevronDown size={14} />
              </button>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">
            {activeCheckId === "data_types" && descriptionSection === "pipeline"
              ? "Мастер исправления типов"
              : activeCheckId === "formats" && descriptionSection === "pipeline"
              ? "Мастер исправления форматов и шаблонов"
              : activeCheckId === "ranges" && descriptionSection === "pipeline"
              ? "Мастер исправления диапазонов"
              : activeCheckId === "consistency" && descriptionSection === "pipeline"
              ? "Мастер исправления логики и хронологии"
              : activeCheckId === "uniqueness" && descriptionSection === "pipeline"
              ? "Мастер исправления уникальности"
              : activeCheckId === "inclusion" && descriptionSection === "pipeline"
              ? "Мастер исправления принадлежности к набору"
              : activeCheckId === "referential" && descriptionSection === "pipeline"
              ? "Мастер исправления ссылочной целостности"
              : activeCheckId === "text_quality" && descriptionSection === "pipeline"
              ? "Мастер исправления целостности текста"
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Мастер исправления равномерности шага"
              : activeCheckId === "sufficiency" && descriptionSection === "pipeline"
              ? "Мастер решений по достаточности"
              : `Обзор: ${activeCheck.label}`}
          </h3>
          <p className="text-xs text-neutral-500 mb-3">
            {activeCheckId === "data_types" && descriptionSection === "pipeline"
              ? "Выберите преобразования, проверьте последствия и примените их к активному датасету."
              : activeCheckId === "formats" && descriptionSection === "pipeline"
              ? "Выберите правила и стратегию, проверьте последствия и примените исправления к активному датасету."
              : activeCheckId === "ranges" && descriptionSection === "pipeline"
              ? "Выберите проблемные колонки и стратегию, оцените последствия и примените исправления."
              : activeCheckId === "consistency" && descriptionSection === "pipeline"
              ? "Выберите нарушенные правила и совместимую стратегию, проверьте последствия и примените исправления."
              : activeCheckId === "uniqueness" && descriptionSection === "pipeline"
              ? "Проверьте ключ, выберите стратегию, оцените точное число удаляемых строк и примените исправление."
              : activeCheckId === "inclusion" && descriptionSection === "pipeline"
              ? "Проверьте справочник, выберите стратегию, оцените последствия и примените исправления."
              : activeCheckId === "referential" && descriptionSection === "pipeline"
              ? "Проверьте связи, выберите стратегию, оцените последствия и устраните сиротские ключи."
              : activeCheckId === "text_quality" && descriptionSection === "pipeline"
              ? "Выберите колонки и стратегию, оцените последствия очистки и примените исправления."
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Проверьте временную сетку, выберите стратегию, оцените последствия и примените исправление."
              : activeCheckId === "sufficiency" && descriptionSection === "pipeline"
              ? "Проверьте длину рядов, выберите безопасное решение и сохраните план анализа."
              : activeCheckId === "data_types"
              ? "Распределение фактических типов и построчная матрица колонок."
              : activeCheckId === "ranges"
              ? "Соотношение корректных и нарушающих значения, фактические и допустимые границы."
              : activeCheckId === "consistency"
              ? "Соблюдение хронологических и предметных правил, затронутые строки и примеры конфликтов."
              : activeCheckId === "uniqueness"
              ? "Распределение строк и группы повторов по активному составному или системному ключу."
              : activeCheckId === "inclusion"
              ? "Соотношение допустимых и недопустимых значений и матрица активных справочников."
              : activeCheckId === "referential"
              ? "Соотношение связанных и сиротских записей и матрица активных внешних ключей."
              : activeCheckId === "text_quality"
              ? "Соотношение чистых и проблемных значений и матрица причин по текстовым колонкам."
              : activeCheckId === "regularity"
              ? "Равномерность временной сетки по группам, разрывы, дубли и нарушения сортировки."
              : activeCheckId === "sufficiency"
              ? "Достаточные и ограниченные группы, валидные наблюдения, сезонные циклы и доступные классы методов."
              : "Визуализация результатов проверки по активному критерию."}
          </p>

          {activeCheckId === "data_types" && descriptionSection === "pipeline" ? (
            <ValidationTypePipeline
              profile={typeProfile}
              activeTargetColumn={activeFeature}
              onApplied={(nextProfile, targetColumnReset) => {
                setTypeProfile(nextProfile);
                runValidation();
                if (targetColumnReset) void refetchTargetColumn();
              }}
              onSchemaSaved={runValidation}
            />
          ) : activeCheckId === "formats" && descriptionSection === "pipeline" ? (
            <ValidationFormatPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "ranges" && descriptionSection === "pipeline" ? (
            <ValidationRangePipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "consistency" && descriptionSection === "pipeline" ? (
            <ValidationConsistencyPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "uniqueness" && descriptionSection === "pipeline" ? (
            <ValidationUniquenessPipeline onApplied={runValidation} />
          ) : activeCheckId === "inclusion" && descriptionSection === "pipeline" ? (
            <ValidationInclusionPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "referential" && descriptionSection === "pipeline" ? (
            <ValidationReferentialPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "text_quality" && descriptionSection === "pipeline" ? (
            <ValidationTextQualityPipeline onApplied={runValidation} />
          ) : activeCheckId === "regularity" && descriptionSection === "pipeline" ? (
            <ValidationRegularityPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "sufficiency" && descriptionSection === "pipeline" ? (
            <ValidationSufficiencyPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : validationHasRun && activeCheck.status === "skipped" ? (
            <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
              {activeCheck.statusReason === "disabled"
                ? `Проверка «${activeCheck.label}» отключена аналитиком и не участвует в DQ Score.`
                : `Проверка «${activeCheck.label}» не требуется для текущего датасета в режиме «Авто».`}
            </div>
          ) : activeCheckId === "data_types" ? (
            validationHasRun || checksLoading ? (
              <ValidationTypeMatrix
                profile={typeProfile}
                mode={typeValidationMode}
                loading={checksLoading}
                hasDataset={Boolean(activeDataset)}
              />
            ) : (
              <div className="rounded-lg h-[468px] flex items-center justify-center bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить матрицу типов и получить статусы проверок.
              </div>
            )
          ) : activeCheckId === "ranges" ? (
            validationHasRun ? (
              <ValidationRangeOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль диапазонов и получить статус проверки.
              </div>
            )
          ) : activeCheckId === "consistency" ? (
            validationHasRun ? (
              <ValidationConsistencyOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль логики и хронологии и получить статус проверки.
              </div>
            )
          ) : activeCheckId === "uniqueness" ? (
            validationHasRun ? (
              <ValidationUniquenessOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль уникальности и получить статус проверки.
              </div>
            )
          ) : activeCheckId === "inclusion" ? (
            validationHasRun ? (
              <ValidationInclusionOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы проверить принадлежность значениям предметных справочников.
              </div>
            )
          ) : activeCheckId === "referential" ? (
            validationHasRun ? (
              <ValidationReferentialOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы проверить внешние ключи относительно предметных справочников.
              </div>
            )
          ) : activeCheckId === "text_quality" ? (
            validationHasRun ? (
              <ValidationTextQualityOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль целостности текстовых колонок.
              </div>
            )
          ) : activeCheckId === "regularity" ? (
            validationHasRun ? (
              <ValidationRegularityOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы проверить равномерность временной сетки по каждой сущности.
              </div>
            )
          ) : activeCheckId === "sufficiency" ? (
            validationHasRun ? (
              <ValidationSufficiencyOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы оценить применимость методов по длине каждого временного ряда.
              </div>
            )
          ) : (
            <ValidationCheckChart
              checkLabel={activeCheck.label}
              data={checksData?.[activeCheckId] ?? null}
              loading={checksLoading}
              selectedColumn={activeFeature}
            />
          )}

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value={datasetSummary ? String(datasetSummary.totalRows) : "—"} />
            <Metric label="Нарушений" value={activeCheck.count !== null ? String(activeCheck.count) : "—"} />
            <Metric label="DQ Score" value={dqScore !== null ? dqScore.toFixed(2) : "—"} />
            <Metric label="Колонок" value={datasetSummary ? String(datasetSummary.totalColumns) : "—"} />
          </div>
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: панель управления + список проверок ── */}
      <aside className="w-80 shrink-0 pt-1">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-neutral-800">
            Панель управления
          </h2>
        </div>
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-5 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={displayedStatus(check)} /> Проверка: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              <label className="mb-2 block text-[11px] font-medium text-neutral-600">
                Режим проверки
                <select
                  aria-label={`Режим проверки ${check.label}`}
                  value={checkModes[check.id] ?? check.mode}
                  disabled={!activeDataset || modeSaving !== null}
                  onChange={(event) => void handleCheckModeChange(check.id, event.target.value as CheckMode)}
                  className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm font-normal text-neutral-800 focus:outline-none focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="auto">Авто</option>
                  <option value="enabled">Включена</option>
                  <option value="disabled">Отключена</option>
                </select>
              </label>
              {modeSaving === check.id && (
                <p role="status" className="mb-2 text-[11px] text-brand">Сохранение режима…</p>
              )}
              {modeError?.checkId === check.id && (
                <p role="alert" className="mb-2 text-[11px] text-red-700">{modeError.message}</p>
              )}

              {checksLoading && (
                <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                  Проверка выполняется
                </p>
              )}
              {!checksLoading && validationHasRun && (validationError || checksData?.[check.id]?.error) && (
                <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                  Ошибка выполнения
                </p>
              )}
              {!checksLoading && !validationHasRun && (
                <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                  Проверка не запускалась
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "warning" && (
                <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                  Найдены проблемы: {check.count ?? 0}
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "done" && (
                <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                  Проверка пройдена
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "skipped" && (
                <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                  {check.statusReason === "disabled" ? "Отключено" : "Не требуется"}
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "pending" && (
                <p role="status" className={`text-sm rounded px-3 py-2 mb-2 ${
                  check.statusReason === "needs_rule"
                    ? "text-amber-700 bg-amber-50"
                    : "text-neutral-600 bg-neutral-50"
                }`}>
                  {check.statusReason === "needs_rule"
                    ? "Требуется настройка"
                    : check.id === "formats" && check.ruleSource === "not_applicable"
                    ? "Эталон форматов не задан"
                    : check.id === "ranges" && check.ruleSource === "not_applicable"
                  ? "Эталон диапазонов не задан"
                    : check.id === "consistency" && check.ruleSource === "not_applicable"
                    ? "Эталон логики и хронологии не задан"
                    : check.id === "uniqueness" && check.ruleSource === "not_applicable"
                    ? "Ключ уникальности неприменим"
                    : check.id === "inclusion" && check.ruleSource === "not_applicable"
                    ? "Эталон допустимых наборов не задан"
                    : "Не применимо: правило или необходимые данные отсутствуют"}
                </p>
              )}

              {validationHasRun && !checksLoading && check.status !== "skipped" && (
                <p className="mb-2 text-[11px] font-medium text-neutral-500">
                  {RULE_SOURCE_LABELS[check.ruleSource]}
                </p>
              )}

              {/* Кнопка «Метрики и алгоритм» — активирует контент в центральном поле */}
              <button
                onClick={() => handleDescriptionClick(check, "metrics")}
                className={`w-full mb-2 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "metrics"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Метрики и алгоритм
              </button>

              {/* Для реализованных остановок открываются специализированные мастера. */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                {check.id === "data_types"
                  ? "Исправить типы данных"
                  : check.id === "formats"
                  ? "Исправить форматы и шаблоны"
                  : check.id === "ranges"
                  ? "Исправить диапазоны значений"
                  : check.id === "consistency"
                  ? "Исправить логику и хронологию"
                  : check.id === "uniqueness"
                  ? "Исправить уникальность"
                  : check.id === "inclusion"
                  ? "Исправить принадлежность к набору"
                  : check.id === "referential"
                  ? "Исправить ссылочную целостность"
                  : check.id === "text_quality"
                  ? "Исправить целостность текста"
                  : check.id === "regularity"
                  ? "Исправить равномерность шага"
                  : check.id === "sufficiency"
                  ? "Настроить план анализа"
                  : "Полный пайплайн"}
              </button>

            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
