"""
Gráficos do site, em Altair.

Sempre com uma série só por gráfico, ou com uma série destacada e as demais em cinza.
A paleta é a de viz_charts.py, validada para daltonismo. Os textos dos rótulos e das
dicas já chegam formatados no padrão brasileiro.
"""

from typing import List

import altair as alt
import pandas as pd

from .metrics import format_number

PRIMARY = "#2a78d6"
MUTED = "#c3c2b7"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e1e0d9"
BAR_SIZE = 16
ROW_HEIGHT = 34
AXIS_BAND = 44
FONT = "Source Sans, system-ui, Segoe UI, sans-serif"


def _styled(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_axis(
            grid=False,
            domainColor=MUTED,
            tickColor=MUTED,
            labelColor=INK_SECONDARY,
            titleColor=INK_SECONDARY,
            labelFont=FONT,
            titleFont=FONT,
            labelFontSize=12,
            titleFontSize=12,
            titleFontWeight="normal",
            labelLimit=260,
        )
        .configure_axisX(grid=True, gridColor=GRID, gridWidth=0.75)
        .configure_view(strokeWidth=0)
        .configure_legend(labelColor=INK_SECONDARY, labelFont=FONT, labelFontSize=12, orient="top")
        .configure_text(font=FONT)
        .configure(background="transparent")
    )


def limit_use_chart(rows: List[dict], field: str, label: str) -> alt.Chart:
    """Barras com o percentual usado de um limite, em uma escala comum de 0 a 100%."""
    data = pd.DataFrame(
        [
            {
                "Veículo": row["vehicle_name"],
                "Uso": row[field],
                "Rótulo": f"{format_number(row[field], 0)}%",
            }
            for row in rows
        ]
    )
    largest = max([120.0] + [row[field] + 20 for row in rows])
    y = alt.Y("Veículo:N", sort=None, title=None)
    x = alt.X(
        "Uso:Q",
        title=f"{label} (% do limite)",
        scale=alt.Scale(domain=[0, largest]),
        axis=alt.Axis(values=[0, 50, 100], format="d"),
    )
    bars = alt.Chart(data).mark_bar(size=BAR_SIZE, cornerRadiusEnd=4, color=PRIMARY).encode(
        y=y, x=x, tooltip=[alt.Tooltip("Veículo:N"), alt.Tooltip("Rótulo:N", title=label)]
    )
    labels = alt.Chart(data).mark_text(align="left", dx=5, color=INK, fontSize=12).encode(y=y, x="Uso:Q", text="Rótulo:N")
    limit = alt.Chart(pd.DataFrame({"limite": [100]})).mark_rule(color=INK_SECONDARY, size=1).encode(x="limite:Q")
    return _styled((bars + limit + labels).properties(height=ROW_HEIGHT * len(rows) + AXIS_BAND))


def cost_chart(rows: List[dict]) -> alt.Chart:
    """Barras do custo por veículo, do maior para o menor."""
    ranked = sorted(rows, key=lambda row: row["cost_brl"], reverse=True)
    data = pd.DataFrame(
        [
            {
                "Veículo": row["vehicle_name"],
                "Custo": row["cost_brl"],
                "Rótulo": f"R$ {format_number(row['cost_brl'], 2)}",
            }
            for row in ranked
        ]
    )
    y = alt.Y("Veículo:N", sort=None, title=None)
    x = alt.X(
        "Custo:Q",
        title="Custo (R$)",
        scale=alt.Scale(domain=[0, max(row["cost_brl"] for row in ranked) * 1.3 or 1]),
        axis=alt.Axis(format="d", tickCount=4),
    )
    bars = alt.Chart(data).mark_bar(size=BAR_SIZE, cornerRadiusEnd=4, color=PRIMARY).encode(
        y=y, x=x, tooltip=[alt.Tooltip("Veículo:N"), alt.Tooltip("Rótulo:N", title="Custo")]
    )
    labels = alt.Chart(data).mark_text(align="left", dx=5, color=INK, fontSize=12).encode(y=y, x="Custo:Q", text="Rótulo:N")
    return _styled((bars + labels).properties(height=ROW_HEIGHT * len(ranked) + AXIS_BAND))


def slack_chart(rows: List[dict], limit: int = 8) -> alt.Chart:
    """Folga até o prazo nas entregas mais apertadas, com as críticas em destaque."""
    tightest = rows[:limit]
    data = pd.DataFrame(
        [
            {
                "Entrega": f"{row['name']} ({row['id']})",
                "Folga": row["slack_min"],
                "Grupo": "Crítica" if row["priority"] == "crítica" else "Outras prioridades",
                "Rótulo": f"{row['slack_min']} min" if row["slack_min"] >= 0 else f"atraso de {-row['slack_min']} min",
                "Chegada": row["arrival"],
                "Prazo": row["deadline"],
                "Veículo": row["vehicle_name"],
            }
            for row in tightest
        ]
    )
    largest = max(row["slack_min"] for row in tightest)
    smallest = min(0, min(row["slack_min"] for row in tightest))
    y = alt.Y("Entrega:N", sort=None, title=None)
    x = alt.X(
        "Folga:Q",
        title="Folga até o prazo (min)",
        scale=alt.Scale(domain=[smallest * 1.4, max(largest * 1.25, 30)]),
        axis=alt.Axis(format="d", tickCount=5),
    )
    bars = alt.Chart(data).mark_bar(size=BAR_SIZE, cornerRadiusEnd=4).encode(
        y=y,
        x=x,
        color=alt.Color(
            "Grupo:N",
            scale=alt.Scale(domain=["Crítica", "Outras prioridades"], range=[PRIMARY, MUTED]),
            title=None,
        ),
        tooltip=["Entrega:N", "Veículo:N", "Chegada:N", "Prazo:N", alt.Tooltip("Rótulo:N", title="Folga")],
    )
    labels = alt.Chart(data).mark_text(align="left", dx=5, color=INK, fontSize=12).encode(y=y, x="Folga:Q", text="Rótulo:N")
    return _styled((bars + labels).properties(height=ROW_HEIGHT * len(tightest) + AXIS_BAND + 24))


def week_distance_chart(daily: List[dict], method: str = "Otimizado", reference: str = "Despacho simulado") -> alt.Chart:
    """Distância por dia: o plano otimizado em destaque e a referência em cinza."""
    rows = []
    for position, day in enumerate(daily):
        label = f"{day['weekday'].split('-')[0].capitalize()} {day['date'][8:]}/{day['date'][5:7]}"
        for series, value in ((method, day["distance_km"]), (reference, day["reference_distance_km"])):
            rows.append(
                {
                    "Dia": label,
                    "Ordem": position,
                    "Série": series,
                    "Distância": value,
                    "Rótulo": f"{format_number(value)} km",
                }
            )
    data = pd.DataFrame(rows)
    color = alt.Color("Série:N", scale=alt.Scale(domain=[method, reference], range=[PRIMARY, MUTED]), title=None)
    x = alt.X("Dia:N", sort=alt.SortField("Ordem"), title=None, axis=alt.Axis(labelAngle=0, grid=False))
    y = alt.Y("Distância:Q", title="Distância (km)", scale=alt.Scale(zero=True), axis=alt.Axis(format="d", grid=True, gridColor=GRID, gridWidth=0.75))
    base = alt.Chart(data).encode(x=x, y=y, color=color)
    lines = base.mark_line(strokeWidth=2)
    points = base.mark_point(filled=True, size=70, opacity=1, stroke="#fcfcfb", strokeWidth=2).encode(
        tooltip=["Dia:N", "Série:N", alt.Tooltip("Rótulo:N", title="Distância")]
    )
    last = data[data["Ordem"] == data["Ordem"].max()]
    end_labels = alt.Chart(last).mark_text(align="center", dy=-14, color=INK, fontSize=12).encode(
        x=x, y=y, text="Rótulo:N"
    )
    return _styled((lines + points + end_labels).properties(height=300))
