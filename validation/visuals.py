# validation/visuals.py
"""Вспомогательные функции для отрисовки в Streamlit"""
import pandas as pd
import plotly.express as px
import missingno as msno
import matplotlib.pyplot as plt
from io import BytesIO

def plot_missing_matrix(df: pd.DataFrame, figsize=(10, 4)):
    """Возвращает figure missingno для st.pyplot()"""
    plt.figure(figsize=figsize)
    msno.matrix(df, color=(0.25, 0.25, 0.75), fontsize=10)
    fig = plt.gcf()
    plt.close()
    return fig

def plot_outlier_boxplots(df: pd.DataFrame, columns: list, title="Распределение и выбросы"):
    """Boxplot по указанным колонкам"""
    return px.box(df, y=columns, title=title, points="all", 
                  boxmode="overlay", template="plotly_white")