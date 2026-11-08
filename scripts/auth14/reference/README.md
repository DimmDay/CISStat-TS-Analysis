# AUTH-14 — локальный измеренный reference

08.11.2026. Это замер контейнера разработки, **не VM**; автоматическая активация отсутствует. Полные исходные samples/seed/environment — `report.json`; воспроизводимая версия — `candidate.json`; независимые holdout checks — `validation.json`.

Canonical profile payload SHA-256 (не sha256sum pretty-printed JSON): `24e14426fa8f3872502d2b50fedcaaca6c4118d975607b6dc42e89991a0efad0`.
Kernel SHA-256: `4c568af0ac3ed82d68c394c5066d794b658266ab8029f055e4ea017a1f835620`.

AMD EPYC 9V74 80-Core Processor; 9 logical CPUs; Python 3.12.14; detected memory envelope 10451427328 bytes. Scientific package versions сохранены в candidate/report. PyTorch/neuralforecast здесь отсутствуют; neural measurements не заявлены.

Команда из корня репозитория:

```bash
python scripts/auth14/benchmark.py --output scripts/auth14/reference --models ets,ets_damped --rows 80,120,180 --folds 2,3 --trials 1,2 --memory-mb 1024
```

Реально выполнено 90 samples: 60 train, 30 held-out (seed101; train17/29). Дополнительно capacity load test concurrency=1, 1 sample. PELT — smooth/breaks, min_segment20/5. Tuning — реальные grid и selected folds, не заглушки времени. Numerical failed trials учитываются как потраченное вычисление; это не fabricated metrics.

| Операция | base micro-CU | exponent | Максимум wall, c (raw) | Peak RSS, MiB (raw) | Runtime wall, мс | Runtime memory, MiB |
|---|---:|---:|---:|---:|---:|---:|
| pelt | 39739.131038552036975154 | 0.25 | 2.4699 | 178.77 | 7410 | 269 |
| tuning:ets | 178293.674996308333743433 | 0.5 | 2.9100 | 189.27 | 8730 | 284 |
| tuning:ets_damped | 570790.893896499503363509 | 0.25 | 2.7704 | 188.77 | 8312 | 284 |

Единица — начатый fold/PELT fit. unit_microCU=ceil(base × (rows×columns×grid_points)^exponent), reserve=unit×worst units, settle=unit×actual started units. 1CU=1e6 microCU; эта engineering normalization CPU microseconds с запасом не задаёт стоимость денег. Точные Decimal coefficients выше используются без округления таблицы.

Область: rows80…180; PELT columns3,grid≤180,units≤17; ETS columns1, folds≤3,trials≤2,units≤6,horizon≤4,seasonal_period≤12. Иные параметры/операции не покрыты. Полная PELT сетка250 и технически возможные большие rows здесь **не измерены**. Production ceiling не экстраполируется из этого reference.

Все 90 train/holdout checks выдержали measured CPU≤quoted attempted cost. Максимальная доля measured/quoted на holdout: 0.5472. Это наблюдение на конечной матрице, не гарантия для любых распределений/моделей.

Fit: log-log OLS exponent округляется вверх до0.25, clip0…3; base — максимум training normalized CPU×2. Runtime envelope — measured maximum wall×3/RSS×1.5 под абсолютным operator cap; memory reserve1024MiB. Holdout не участвует в подборе base/exponent; провал отклоняет candidate, не подгоняет коэффициент. Concurrency1 не является поиском максимальной throughput и не разрешает2; выше — отдельный реальный simultaneous load test.

Host-specific profile обязателен к повторному измерению/verify/install на VM: `docs/auth14/runbook.md`. При изменении kernels/dependencies/hardware/resource envelope текущий configured profile отвергается. Reference checker успешно повторно воспроизвёл profile из raw report и атомарную установку во временный файл; production environment не менялось.
