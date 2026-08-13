# apps/api/cv.py
"""
Cross-validation стратегии для временных рядов.

Введено в Phase 1-B как фундамент для POST /v1/models/tune (Phase 1-C).
Используется tune-ендпоинтом для честной оценки гиперпараметров на
временных рядах, где KFold sklearn НЕ подходит (он мешает точки случайно,
нарушая временную причинность).

КОНТРАКТ:
  CVStrategy — абстракция. Любая реализация должна вернуть list[CVSplit]
  по split(n). Каждый CVSplit содержит train_idx и test_idx — индексы в
  исходный ряд. Train всегда строго меньше test по времени (no future
  leakage).

ИЕРАРХИЯ:
  CVStrategy (ABC)
    └── ExpandingWindowCV  — train растёт от fold к fold, test фиксирован.
                               Классический expanding-origin evaluation
                               (Tashman 2000). По умолчанию step == test_size
                               → test окна не перекрываются.

ФОРМУЛА ExpandingWindowCV:
  min_samples = min_train_size + test_size + (n_splits - 1) * step

  fold i (0-indexed):
    train_idx = [0 .. min_train_size + i*step)
    test_idx  = [min_train_size + i*step .. min_train_size + i*step + test_size)

  Если test_idx последнего fold выходит за пределы n — этот fold
  отбрасывается (return fewer folds, не ошибка).

СЦЕНАРИИ:
  - step == test_size  → test окна НЕ перекрываются (по умолчанию)
  - step <  test_size  → test окна перекрываются (легальный CV-режим)
  - step >  test_size  → между test окнами есть «дыры» (редкий случай,
                         но валидный — например, для ускорения на длинных рядах)

ИСПОЛЬЗОВАНИЕ (для tune-ендпоинта Phase 1-C):
    cv = ExpandingWindowCV(n_splits=5, test_size=2, min_train_size=10)
    if len(series) < cv.min_samples():
        raise HTTPException(422, "Слишком короткий ряд для CV")
    for split in cv.split(len(series)):
        y_train = [series[i] for i in split.train_idx]
        y_test  = [series[i] for i in split.test_idx]
        # ... fit model on y_train, predict y_test, compute metrics
    # усреднить метрики по folds → выбрать лучшие гиперпараметры
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


# ═══════════════════════════════════════════════════════════
# 1. CVSplit — структура одного fold
# ═══════════════════════════════════════════════════════════


@dataclass
class CVSplit:
    """Один fold CV: (train_indices, test_indices).

    Индексы — позиции в исходном ряде. Train всегда строго меньше test
    по времени (no future leakage): max(train_idx) < min(test_idx).

    fold: int — 0-indexed номер fold (для логирования/дебага).
    """
    fold: int
    train_idx: List[int]
    test_idx: List[int]


# ═══════════════════════════════════════════════════════════
# 2. CVStrategy — абстракция
# ═══════════════════════════════════════════════════════════


class CVStrategy(ABC):
    """Абстрактный базовый класс для CV-стратегий.

    Подклассы должны реализовать:
      - split(n): вернуть list[CVSplit], каждый с валидными индексами
                  (0 ≤ idx < n, max(train_idx) < min(test_idx))
      - min_samples(): минимальное число точек, нужное для работы

    Контракт не диктует СТРАТЕГИЮ (expanding/sliding/blocked/etc.) —
    только формат возвращаемых данных. Любая стратегия, соблюдающая
    «train строго раньше test», подходит.
    """

    @abstractmethod
    def split(self, n: int) -> List[CVSplit]:
        """Вернуть list[CVSplit] для ряда длиной n.

        Raises:
            ValueError: если n < min_samples().
        """
        ...

    @abstractmethod
    def min_samples(self) -> int:
        """Минимальное число точек, нужное для работы стратегии.

        Используется tune-ендпоинтом для валидации длины ряда ДО запуска
        grid search (чтобы не тратить время на fit'ы, которые всё равно
        упадут на коротком ряде).
        """
        ...


# ═══════════════════════════════════════════════════════════
# 3. ExpandingWindowCV
# ═══════════════════════════════════════════════════════════


class ExpandingWindowCV(CVStrategy):
    """Expanding-window cross-validation для временных рядов.

    Train-окно растёт от fold к fold (всё больше исторических данных
    используется для обучения), test-окно фиксированной длины test_size.
    Классическая стратегия expanding-origin evaluation (Tashman 2000).

    По умолчанию:
      - min_train_size = test_size (минимально разумное начальное окно)
      - step = test_size → test окна НЕ перекрываются

    Параметры:
        n_splits:       число folds (≥ 1). Больше = более стабильная
                        оценка, но дольше. Для коротких рядов (n < 50)
                        рекомендуется 3, для длинных — 5-10.
        test_size:      длина test-окна в каждом fold (≥ 1). Часто = 1
                        (one-step-ahead forecast) или = горизонту
                        прогнозирования.
        min_train_size: размер train в первом fold (default = test_size).
                        Если мало — модель не обучится. Если много —
                        мало останется данных для folds.
        step:           сдвиг test-окна между folds (default = test_size).
                        step < test_size → test окна перекрываются.
                        step > test_size → между test окнами есть «дыры».

    Пример (n_splits=3, test_size=2, min_train_size=3, step=2, n=9):
        fold 0: train=[0,1,2]    test=[3,4]
        fold 1: train=[0..4]     test=[5,6]
        fold 2: train=[0..6]     test=[7,8]

    Минимум точек: 3 + 2 + 2*2 = 9 (как раз хватает на 3 folds).
    """

    def __init__(
        self,
        n_splits: int = 5,
        test_size: int = 1,
        min_train_size: Optional[int] = None,
        step: Optional[int] = None,
    ) -> None:
        # Валидация (defensive — ValueError с понятным сообщением,
        # чтобы пользователь tune-ендпоинта понял, что не так).
        if n_splits < 1:
            raise ValueError(
                f"n_splits must be >= 1, got {n_splits}"
            )
        if test_size < 1:
            raise ValueError(
                f"test_size must be >= 1, got {test_size}"
            )
        if min_train_size is not None and min_train_size < 1:
            raise ValueError(
                f"min_train_size must be >= 1, got {min_train_size}"
            )
        if step is not None and step < 1:
            raise ValueError(
                f"step must be >= 1, got {step}"
            )

        self.n_splits = n_splits
        self.test_size = test_size
        # None → default = test_size (минимально разумное)
        self.min_train_size = min_train_size if min_train_size is not None else test_size
        # None → default = test_size → non-overlapping test windows
        self.step = step if step is not None else test_size

    def min_samples(self) -> int:
        """Минимальная длина ряда для работы стратегии.

        Формула:
            min_train_size + test_size + (n_splits - 1) * step

        Где первое слагаемое — первый train, второе — первый test,
        третье — сдвиг test-окна для оставшихся (n_splits - 1) folds.
        """
        return (
            self.min_train_size
            + self.test_size
            + (self.n_splits - 1) * self.step
        )

    def split(self, n: int) -> List[CVSplit]:
        """Сгенерировать n_splits folds (или меньше, если ряд слишком короток
        для последних folds — truncation, не ошибка).

        Raises:
            ValueError: если n < min_samples() — ряд слишком короток даже
                        для первого fold. tune-ендпоинт должен валидировать
                        до запуска grid search.
        """
        if n < self.min_samples():
            raise ValueError(
                f"Слишком короткий ряд для CV: нужно ≥ {self.min_samples()}, "
                f"есть {n}. Уменьшите n_splits, test_size или min_train_size."
            )

        splits: List[CVSplit] = []
        # train_end растёт на step каждый fold (расширение train).
        # Первый fold: train = [0, min_train_size), test = [min_train_size, min_train_size + test_size).
        train_end = self.min_train_size

        for fold in range(self.n_splits):
            test_start = train_end
            test_end = test_start + self.test_size

            # Truncation: если test выходит за пределы ряда — этот fold
            # (и все последующие) невозможны. break, не ошибка —
            # пользователь запросил больше folds, чем влезает в ряд,
            # но это лучше, чем упасть.
            if test_end > n:
                break

            splits.append(
                CVSplit(
                    fold=fold,
                    train_idx=list(range(0, train_end)),
                    test_idx=list(range(test_start, test_end)),
                )
            )
            # Расширение train на step точек (для следующего fold).
            train_end += self.step

        return splits
