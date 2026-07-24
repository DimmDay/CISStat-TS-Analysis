# layout_prototype_preprocessing.py
"""
ПРОТОТИП нового макета для вкладки "Предобработка".
 
Цель: показать, как решить проблему "много скролла с потерей контекста",
не переделывая архитектуру приложения и не трогая существующий sidebar
(источник данных / управление правилами / лог событий) — они сохранены
как есть, просто рядом добавлен компактный степпер прогресса по подэтапам.
 
Запуск: streamlit run layout_prototype_preprocessing.py
 
Это ИЗОЛИРОВАННЫЙ прототип с моковыми данными — не подключён к реальным
app/core/*, app/validation/*, чтобы можно было потрогать макет отдельно,
не рискуя основным приложением. Если понравится — переносим структуру
в app.py, подключая реальные функции вместо моков.
"""
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
 
st.set_page_config(layout="wide", page_title="CISStat — прототип макета")
 
 
# ─────────────────────────────────────────────────────────────
# МОКОВЫЕ ДАННЫЕ (замените на реальные df/результаты валидации)
# ─────────────────────────────────────────────────────────────
@st.cache_data
def make_mock_series():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2018-01-01", periods=200, freq="D")
    trend = np.linspace(0, 10, 200)
    seasonal = 3 * np.sin(2 * np.pi * np.arange(200) / 7)
    noise = rng.normal(0, 1, 200)
    values = trend + seasonal + noise
    values[10:15] = np.nan  # искусственные пропуски для демо
    values[[50, 120, 150]] += 25  # искусственные выбросы для демо
    return pd.Series(values, index=idx, name="value")
 
 
series_raw = make_mock_series()
 
# Список подэтапов текущего модуля "Предобработка" -- статус для степпера.
# В реальном приложении статус берётся из st.session_state / AppState
# (например: "done" если пропуски уже обработаны, "warning" если найдены,
# но не тронуты, "pending" если проверка ещё не запускалась).
CHECKS = [
    {"id": "missing", "label": "Пропуски", "status": "warning", "count": 11},
    {"id": "outliers", "label": "Выбросы", "status": "warning", "count": 1145},
    {"id": "duplicates", "label": "Дубликаты", "status": "done", "count": 0},
    {"id": "regularity", "label": "Регулярность шага", "status": "pending", "count": None},
    {"id": "text_quality", "label": "Качество текста", "status": "pending", "count": None},
]
 
STATUS_ICON = {"done": "✅", "warning": "⚠️", "pending": "⬜"}
 
 
# ─────────────────────────────────────────────────────────────
# SIDEBAR: существующие блоки СОХРАНЕНЫ + новый компактный степпер
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    # --- Существующий блок "Источник данных" (как на скриншоте) ---
    st.markdown("### Источник данных")
    st.radio("Выберите источник:", ["Файл .xlsx, .xls, .csv, .json", "База данных (SQL)"], index=0)
    st.file_uploader("Загрузите файл", label_visibility="collapsed")
    st.success("Файл выбран: train.csv")
    st.button("Загрузить файл", type="primary", use_container_width=True)
 
    with st.expander("Управление правилами"):
        st.caption("(существующий блок -- не тронут)")
 
    st.divider()
 
    # --- НОВОЕ: компактный степпер прогресса по подэтапам модуля ---
    st.markdown("### Прогресс: Предобработка")
    if "active_check" not in st.session_state:
        st.session_state.active_check = CHECKS[0]["id"]
 
    for check in CHECKS:
        icon = STATUS_ICON[check["status"]]
        label = f"{icon} {check['label']}"
        if check["count"]:
            label += f" ({check['count']})"
        is_active = st.session_state.active_check == check["id"]
        if st.button(
            label,
            key=f"nav_{check['id']}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.active_check = check["id"]
            st.rerun()
 
    st.caption("Клик по пункту разворачивает и поднимает нужную "
               "проверку наверх списка справа — не нужно скроллить вручную.")
 
    st.divider()
 
    # --- Существующий блок "Лог событий" (как на скриншоте) ---
    st.markdown("### Лог событий")
    st.dataframe(
        pd.DataFrame([{"№": 0, "Время": "09:16:58", "Уровень": "INFO", "Сообщение": "✅ Загружен файл"}]),
        hide_index=True, use_container_width=True,
    )
    st.button("Очистить лог", use_container_width=True)
 
 
# ─────────────────────────────────────────────────────────────
# ВЕРХНИЕ ВКЛАДКИ (уже существуют в приложении -- здесь для контекста)
# ─────────────────────────────────────────────────────────────
tabs = st.tabs(["Загрузка", "Валидация", "Предобработка", "Разведочный EDA",
                "Моделирование", "Прогнозирование", "Задачи"])
 
with tabs[2]:  # "Предобработка"
    st.warning("⚠️ Платформа находится в разработке. Некоторые функции могут "
               "работать нестабильно или быть недоступны.")
 
    st.markdown(
        "> *«Если бы Кеплер опирался на точные данные, учитывающие все сложности "
        "взаимного влияния планет, он никогда бы не сформулировал свои законы. "
        "Именно огрубление данных Тихо Браге позволило увидеть главное»* "
        "— Арнольд Зоммерфельд"
    )
 
    with st.expander("Цели модуля и результаты его прохождения"):
        st.write("(существующий текст -- не тронут)")
 
    st.markdown("---")
 
    # ── ДВЕ КОЛОНКИ: слева прокручиваемый список проверок, справа -- обзор ──
    left_col, right_col = st.columns([2, 1], gap="large")
 
    with right_col:
        st.markdown("#### Обзор ряда")
        st.caption("Эта панель никуда не уезжает, пока вы листаете проверки слева.")
 
        view_mode = st.radio("Показать:", ["Исходный ряд", "После обработки"],
                              horizontal=True, label_visibility="collapsed")
 
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=series_raw.index, y=series_raw.values,
            mode="lines", name="value", line=dict(color="#1f77b4"),
        ))
        if view_mode == "После обработки":
            series_clean = series_raw.interpolate().clip(
                upper=series_raw.mean() + 3 * series_raw.std()
            )
            fig.add_trace(go.Scatter(
                x=series_clean.index, y=series_clean.values,
                mode="lines", name="после обработки", line=dict(color="#2ca02c", dash="dot"),
            ))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                           showlegend=(view_mode == "После обработки"))
        st.plotly_chart(fig, use_container_width=True)
 
        m1, m2 = st.columns(2)
        m1.metric("Строк", len(series_raw))
        m2.metric("Пропусков", int(series_raw.isna().sum()))
        m3, m4 = st.columns(2)
        m3.metric("Выбросов (демо)", 3)
        m4.metric("Частота", "D")
 
    with left_col:
        # Активная проверка поднимается наверх списка -- имитация "перехода"
        # без необходимости настоящей прокрутки к якорю.
        ordered_checks = sorted(
            CHECKS, key=lambda c: c["id"] != st.session_state.active_check
        )
 
        with st.container(height=620, border=False):
            for check in ordered_checks:
                is_active = check["id"] == st.session_state.active_check
                border_style = "border-left: 4px solid #1f77b4; padding-left: 12px;" if is_active else ""
                st.markdown(f'<div style="{border_style}">', unsafe_allow_html=True)
 
                st.markdown(f"### {STATUS_ICON[check['status']]} Проверка: {check['label']}")
 
                descriptions = {
                    "missing": "Пропуски нарушают `DatetimeIndex`, делают невозможной "
                               "STL-декомпозицию, искажают ACF/PACF и ломают ARIMA/SARIMA.",
                    "outliers": "Выбросы завышают дисперсию, искажают оценки тренда "
                                "и ломают тесты стационарности (ADF/KPSS).",
                    "duplicates": "Дублирующиеся временные метки ломают уникальность индекса.",
                    "regularity": "Нерегулярный шаг мешает корректной декомпозиции и прогнозированию.",
                    "text_quality": "Мусорные символы и пустые строки искажают категориальный анализ.",
                }
                st.caption(descriptions.get(check["id"], ""))
 
                with st.expander("Метрики и алгоритм", expanded=is_active):
                    st.write("(существующее содержимое -- не тронуто)")
 
                if check["count"]:
                    st.warning(f"Найдено {check['count']} {'пропусков' if check['id']=='missing' else 'выбросов'}")
                elif check["status"] == "done":
                    st.success("Проверка пройдена, нарушений не найдено")
 
                with st.expander(f"Полный пайплайн обработки: {check['label'].lower()}", expanded=is_active):
                    st.write("(существующее содержимое -- не тронуто)")
 
                st.button(
                    f"Пересчитать свойства после преобразования ({check['label'].lower()})",
                    key=f"recalc_{check['id']}",
                    type="primary",
                )
 
                st.markdown("</div>", unsafe_allow_html=True)
                st.divider()
 
with tabs[0]:
    st.info("Вкладка 'Загрузка' -- в прототипе не реализована, для контекста верхней навигации.")
for t in tabs[1:2] + tabs[3:]:
    with t:
        st.info("Не реализовано в прототипе -- показывает только 'Предобработка'.")
 