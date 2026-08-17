"""
Phase 1-B: Тесты для apps/api/cv.py — CVStrategy + ExpandingWindowCV.

Покрывают:
  1. CVSplit dataclass — структура
  2. CVStrategy ABC — нельзя инстанцировать, подкласс должен реализовать split()
  3. ExpandingWindowCV.__init__ — валидация параметров
  4. ExpandingWindowCV.min_samples — формула минимального размера ряда
  5. ExpandingWindowCV.split — корректные индексы, расширяющееся train окно
  6. Edge cases: n_splits=1, короткий ряд, custom step, overlap, последний fold overflow
  7. Совместимость со списком — индексы можно использовать для list[float]
"""
import pytest

from apps.api.cv import CVSplit, CVStrategy, ExpandingWindowCV


# ═══════════════════════════════════════════════════════════
# 1. CVSplit — DATACLASS
# ═══════════════════════════════════════════════════════════

class TestCVSplit:
    """Простая структура данных для одного fold."""

    def test_construct(self):
        s = CVSplit(fold=0, train_idx=[0, 1, 2], test_idx=[3, 4])
        assert s.fold == 0
        assert s.train_idx == [0, 1, 2]
        assert s.test_idx == [3, 4]

    def test_equality(self):
        """Два CVSplit с одинаковыми полями равны (dataclass)."""
        a = CVSplit(fold=0, train_idx=[0, 1], test_idx=[2])
        b = CVSplit(fold=0, train_idx=[0, 1], test_idx=[2])
        assert a == b

    def test_inequality(self):
        a = CVSplit(fold=0, train_idx=[0, 1], test_idx=[2])
        b = CVSplit(fold=1, train_idx=[0, 1], test_idx=[2])
        assert a != b


# ═══════════════════════════════════════════════════════════
# 2. CVStrategy — ABC
# ═══════════════════════════════════════════════════════════

class TestCVStrategyABC:
    """CVStrategy — абстрактный класс, нельзя инстанцировать напрямую."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            CVStrategy()  # type: ignore[abstract]

    def test_subclass_must_implement_split(self):
        """Подкласс без split() и min_samples() не инстанцируется."""
        class BadStrategy(CVStrategy):
            pass
        with pytest.raises(TypeError):
            BadStrategy()  # type: ignore[abstract]

    def test_subclass_with_methods_works(self):
        class DummyStrategy(CVStrategy):
            def split(self, n: int) -> list[CVSplit]:
                return [CVSplit(fold=0, train_idx=[0], test_idx=[1])]
            def min_samples(self) -> int:
                return 2
        s = DummyStrategy()
        assert len(s.split(10)) == 1
        assert s.min_samples() == 2


# ═══════════════════════════════════════════════════════════
# 3. ExpandingWindowCV — КОНСТРУКТОР (ВАЛИДАЦИЯ)
# ═══════════════════════════════════════════════════════════

class TestExpandingWindowCVConstructor:
    """Все параметры валидируются в __init__."""

    @pytest.mark.parametrize("n_splits", [0, -1, -5])
    def test_n_splits_must_be_positive(self, n_splits):
        with pytest.raises(ValueError, match="n_splits"):
            ExpandingWindowCV(n_splits=n_splits)

    @pytest.mark.parametrize("test_size", [0, -1])
    def test_test_size_must_be_positive(self, test_size):
        with pytest.raises(ValueError, match="test_size"):
            ExpandingWindowCV(test_size=test_size)

    @pytest.mark.parametrize("min_train_size", [0, -1])
    def test_min_train_size_must_be_positive_if_given(self, min_train_size):
        with pytest.raises(ValueError, match="min_train_size"):
            ExpandingWindowCV(min_train_size=min_train_size)

    @pytest.mark.parametrize("step", [0, -1])
    def test_step_must_be_positive_if_given(self, step):
        with pytest.raises(ValueError, match="step"):
            ExpandingWindowCV(step=step)

    def test_defaults(self):
        """Дефолтные значения: n_splits=5, test_size=1, step=test_size, min_train=test_size."""
        cv = ExpandingWindowCV()
        assert cv.n_splits == 5
        assert cv.test_size == 1
        assert cv.min_train_size == 1
        assert cv.step == 1

    def test_min_train_defaults_to_test_size(self):
        cv = ExpandingWindowCV(n_splits=3, test_size=5)
        assert cv.min_train_size == 5
        assert cv.step == 5


# ═══════════════════════════════════════════════════════════
# 4. min_samples — ФОРМУЛА
# ═══════════════════════════════════════════════════════════

class TestMinSamples:
    """min_samples = min_train_size + test_size + (n_splits - 1) * step."""

    def test_default(self):
        cv = ExpandingWindowCV()  # n_splits=5, test_size=1, step=1, min_train=1
        # 1 + 1 + (5-1) * 1 = 6
        assert cv.min_samples() == 6

    def test_custom(self):
        cv = ExpandingWindowCV(n_splits=3, test_size=5, min_train_size=10, step=5)
        # 10 + 5 + (3-1) * 5 = 25
        assert cv.min_samples() == 25

    def test_one_split(self):
        cv = ExpandingWindowCV(n_splits=1, test_size=10, min_train_size=20)
        # 20 + 10 + 0 = 30
        assert cv.min_samples() == 30

    def test_step_greater_than_test_size(self):
        """Шаг > test_size — между folds «дыра». min_samples растёт быстрее."""
        cv = ExpandingWindowCV(n_splits=3, test_size=2, step=5, min_train_size=4)
        # 4 + 2 + 2 * 5 = 16
        assert cv.min_samples() == 16


# ═══════════════════════════════════════════════════════════
# 5. split — КОРРЕКТНОСТЬ ИНДЕКСОВ
# ═══════════════════════════════════════════════════════════

class TestSplitCorrectness:
    """split(n) возвращает список CVSplit с правильными индексами."""

    def test_basic_3_folds(self):
        """3 folds, test_size=2, min_train=3, step=2.
        Ожидаемая структура:
          fold 0: train=[0,1,2]    test=[3,4]
          fold 1: train=[0..4]      test=[5,6]
          fold 2: train=[0..6]      test=[7,8]
        n_min = 3 + 2 + 2*2 = 9
        """
        cv = ExpandingWindowCV(n_splits=3, test_size=2, min_train_size=3, step=2)
        splits = cv.split(9)
        assert len(splits) == 3

        assert splits[0].fold == 0
        assert splits[0].train_idx == [0, 1, 2]
        assert splits[0].test_idx == [3, 4]

        assert splits[1].fold == 1
        assert splits[1].train_idx == [0, 1, 2, 3, 4]
        assert splits[1].test_idx == [5, 6]

        assert splits[2].fold == 2
        assert splits[2].train_idx == [0, 1, 2, 3, 4, 5, 6]
        assert splits[2].test_idx == [7, 8]

    def test_train_expands_between_folds(self):
        """Контракт expanding window: каждый fold train включает предыдущий train + test."""
        cv = ExpandingWindowCV(n_splits=4, test_size=2, min_train_size=4, step=2)
        splits = cv.split(14)
        assert len(splits) == 4

        for i in range(1, len(splits)):
            prev_train = set(splits[i - 1].train_idx)
            curr_train = set(splits[i].train_idx)
            # Текущий train — надмножество предыдущего
            assert prev_train.issubset(curr_train), (
                f"Fold {i}: train должен расширяться, "
                f"но {prev_train} не subset of {curr_train}"
            )
            # Размер увеличился на step
            size_diff = len(curr_train) - len(prev_train)
            assert size_diff == cv.step

    def test_no_future_leakage(self):
        """Все test индексы > всех train индексов в каждом fold (временная причинность)."""
        cv = ExpandingWindowCV(n_splits=5, test_size=2, min_train_size=4, step=2)
        splits = cv.split(16)
        for s in splits:
            max_train = max(s.train_idx)
            min_test = min(s.test_idx)
            assert min_test > max_train, (
                f"Fold {s.fold}: test начинается с {min_test}, "
                f"но train заканчивается на {max_train} — leakage!"
            )

    def test_non_overlapping_test_windows_by_default(self):
        """При step == test_size test окна не перекрываются (по умолчанию)."""
        cv = ExpandingWindowCV(n_splits=3, test_size=3)  # step=3
        splits = cv.split(15)
        all_test = []
        for s in splits:
            all_test.extend(s.test_idx)
        # Все test индексы уникальны
        assert len(all_test) == len(set(all_test)), "Test windows overlapping"


# ═══════════════════════════════════════════════════════════
# 6. EDGE CASES
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Граничные сценарии."""

    def test_n_splits_one(self):
        """Один fold: train = [0..min_train_size), test = [min_train_size..+test_size)."""
        cv = ExpandingWindowCV(n_splits=1, test_size=3, min_train_size=5)
        splits = cv.split(8)
        assert len(splits) == 1
        assert splits[0].train_idx == [0, 1, 2, 3, 4]
        assert splits[0].test_idx == [5, 6, 7]

    def test_short_series_raises(self):
        """Ряд короче min_samples → ValueError с понятным сообщением."""
        cv = ExpandingWindowCV(n_splits=3, test_size=2, min_train_size=4, step=2)
        # min_samples = 4 + 2 + 2*2 = 10
        with pytest.raises(ValueError, match="Слишком короткий ряд"):
            cv.split(9)

    def test_exact_min_samples_ok(self):
        """Ровно min_samples — работает, возвращает n_splits folds."""
        cv = ExpandingWindowCV(n_splits=3, test_size=2, min_train_size=4, step=2)
        # min_samples = 10
        splits = cv.split(10)
        assert len(splits) == 3

    def test_last_fold_overflow_raises(self):
        """Если n чуть меньше min_samples — ValueError, а не truncation.

        Дизайн-решение: явное лучше молчаливого. Запросил 5 folds —
        или получишь 5, или понятную ошибку (не молча 4). Пользователь
        может явно уменьшить n_splits, если ряд короче. Молчаливое
        truncation — плохой UX: пользователь думает, чтоCV сработал
        на 5 folds, а на самом деле на 4 — метрики будут искажены.
        """
        cv = ExpandingWindowCV(n_splits=5, test_size=2, min_train_size=4, step=2)
        # min_samples = 4 + 2 + 4*2 = 14
        with pytest.raises(ValueError, match="Слишком короткий ряд"):
            cv.split(13)

    def test_custom_step_greater_than_test_size(self):
        """step > test_size — между test окнами есть «дыры» (необработанные окна)."""
        cv = ExpandingWindowCV(n_splits=2, test_size=2, min_train_size=4, step=5)
        splits = cv.split(13)
        assert len(splits) == 2
        # fold 0: train [0..3], test [4, 5]
        # fold 1: train [0..8] (расширился на step=5), test [9, 10]
        # индексы 6, 7, 8 — между test окнами, не попали в test ни одного fold
        assert splits[0].test_idx == [4, 5]
        assert splits[1].test_idx == [9, 10]
        assert 8 not in splits[0].test_idx
        assert 8 not in splits[1].test_idx

    def test_custom_step_less_than_test_size_overlapping(self):
        """step < test_size — test окна перекрываются (легальный режим CV)."""
        cv = ExpandingWindowCV(n_splits=2, test_size=4, min_train_size=4, step=2)
        splits = cv.split(14)
        assert len(splits) == 2
        # fold 0: train [0..3], test [4,5,6,7]
        # fold 1: train [0..5], test [6,7,8,9]
        # test окна перекрываются на индексах 6, 7
        overlap = set(splits[0].test_idx) & set(splits[1].test_idx)
        assert overlap == {6, 7}

    def test_returns_list_of_cvsplit_instances(self):
        cv = ExpandingWindowCV(n_splits=2, test_size=1)
        splits = cv.split(4)
        assert all(isinstance(s, CVSplit) for s in splits)
        assert [s.fold for s in splits] == [0, 1]


# ═══════════════════════════════════════════════════════════
# 7. ИНТЕГРАЦИЯ СО СПИСКОМ
# ═══════════════════════════════════════════════════════════

class TestListIntegration:
    """Индексы можно использовать для среза list[float] (как используют модели)."""

    def test_slice_series(self):
        series = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0]
        cv = ExpandingWindowCV(n_splits=3, test_size=2, min_train_size=3, step=2)
        splits = cv.split(len(series))
        assert len(splits) == 3

        # fold 0
        y_train_0 = [series[i] for i in splits[0].train_idx]
        y_test_0 = [series[i] for i in splits[0].test_idx]
        assert y_train_0 == [10.0, 11.0, 12.0]
        assert y_test_0 == [13.0, 14.0]

        # fold 2 (последний)
        y_train_2 = [series[i] for i in splits[2].train_idx]
        y_test_2 = [series[i] for i in splits[2].test_idx]
        assert y_train_2 == [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        assert y_test_2 == [17.0, 18.0]
