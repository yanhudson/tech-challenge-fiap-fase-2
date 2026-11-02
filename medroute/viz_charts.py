"""Gráficos estáticos do relatório, gerados com Matplotlib."""

import math
from pathlib import Path
from typing import Dict, Sequence, Union

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator  # noqa: E402

from .metrics import format_number  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
        "axes.unicode_minus": False,
    }
)


def _style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.75)
    ax.tick_params(colors=INK_SECONDARY, length=0, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.75)
    ax.set_axisbelow(True)


def _save(fig, output_path: Union[str, Path]) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight", facecolor=SURFACE, dpi=150)
    plt.close(fig)
    return output


def plot_convergence(
    series: Dict[str, Sequence[float]],
    output_path: Union[str, Path],
    title: str = "Evolução da melhor solução",
) -> Path:
    """
    Desenha a evolução da fitness por geração.

    Parameters:
    - series: nome da série e valor da melhor fitness por geração.
    - output_path: caminho do arquivo PNG.
    - title: título do gráfico.

    Returns:
    Path: o caminho do arquivo gerado.
    """
    fig, ax = plt.subplots(figsize=(8, 4), facecolor=SURFACE)
    _style_axes(ax)
    ax.grid(False, axis="x")

    all_values = [value for values in series.values() for value in values]
    for index, (name, values) in enumerate(series.items()):
        ax.plot(values, color=SERIES[index % len(SERIES)], linewidth=1.5, label=name)
        ax.annotate(
            format_number(values[-1]),
            xy=(len(values) - 1, values[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_SECONDARY,
        )

    # Penalidades altas no início achatariam o restante da curva em escala linear.
    if min(all_values) > 0 and max(all_values) / min(all_values) > 5:
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: format_number(value, 0)))

    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="semibold")
    ax.set_xlabel("Geração", fontsize=9, color=INK_SECONDARY)
    ax.set_ylabel("Fitness (km equivalentes; menor é melhor)", fontsize=9, color=INK_SECONDARY)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY)
    return _save(fig, output_path)


def plot_method_comparison(
    labels: Sequence[str],
    values: Sequence[float],
    output_path: Union[str, Path],
    title: str,
    x_label: str,
    highlight: str = "Algoritmo genético",
) -> Path:
    """
    Compara métodos em barras horizontais, destacando um deles.

    Parameters:
    - labels: nome de cada método.
    - values: valor de cada método.
    - output_path: caminho do arquivo PNG.
    - title: título do gráfico.
    - x_label: rótulo do eixo horizontal.
    - highlight: método destacado em cor; os demais ficam em cinza.

    Returns:
    Path: o caminho do arquivo gerado.
    """
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(labels) + 1.4), facecolor=SURFACE)
    _style_axes(ax)
    ax.grid(False, axis="y")

    positions = list(range(len(labels)))
    colors = [SERIES[0] if label == highlight else AXIS for label in labels]
    ax.barh(positions, values, height=0.5, color=colors)
    ax.set_yticks(positions)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()

    for position, value in zip(positions, values):
        ax.annotate(
            format_number(value),
            xy=(value, position),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_SECONDARY,
        )

    ax.set_xlim(0, max(values) * 1.15 if max(values) > 0 else 1)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: format_number(value, 0)))
    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="semibold")
    ax.set_xlabel(x_label, fontsize=9, color=INK_SECONDARY)
    return _save(fig, output_path)


def plot_routes_small_multiples(plan: dict, output_path: Union[str, Path]) -> Path:
    """
    Desenha um painel por veículo, para a figura estática do relatório.

    Com vários veículos em um só desenho, as cores se confundem e as linhas se
    cruzam. Em painéis separados, cada rota pode ser lida sozinha, tendo as demais
    paradas ao fundo como referência.

    Parameters:
    - plan: resumo do plano, gerado por metrics.summarize_plan.
    - output_path: caminho do arquivo PNG.

    Returns:
    Path: o caminho do arquivo gerado.
    """
    routes = plan["routes"]
    columns = 3
    rows = max(1, math.ceil(len(routes) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(11, 3.6 * rows), facecolor=SURFACE, squeeze=False)
    flat_axes = [ax for row in axes for ax in row]

    depot = plan["depot"]
    every_stop = [stop for route in routes for stop in route["stops"]]
    aspect = 1.0 / math.cos(math.radians(depot["lat"]))

    for ax, route in zip(flat_axes, routes):
        color = SERIES[route["vehicle_index"] % len(SERIES)]
        ax.set_facecolor(SURFACE)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.set_aspect(aspect)

        ax.scatter(
            [stop["lon"] for stop in every_stop],
            [stop["lat"] for stop in every_stop],
            s=10,
            color=GRID,
            zorder=1,
        )
        path_lon = [depot["lon"]] + [stop["lon"] for stop in route["stops"]] + [depot["lon"]]
        path_lat = [depot["lat"]] + [stop["lat"] for stop in route["stops"]] + [depot["lat"]]
        ax.plot(path_lon, path_lat, color=color, linewidth=1.5, zorder=2)

        for stop in route["stops"]:
            ax.scatter(
                stop["lon"],
                stop["lat"],
                s=70 if stop["priority"] == "crítica" else 40,
                marker="D" if stop["priority"] == "crítica" else "o",
                color=color,
                edgecolors=SURFACE,
                linewidths=1.5,
                zorder=3,
            )
            ax.annotate(
                str(stop["sequence"]),
                xy=(stop["lon"], stop["lat"]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
                color=INK_SECONDARY,
                zorder=4,
            )
        ax.scatter(depot["lon"], depot["lat"], s=80, marker="s", color=INK, edgecolors=SURFACE, linewidths=1.5, zorder=5)

        ax.set_title(
            f'{route["vehicle_name"]}: {format_number(route["distance_km"])} km, '
            f'{format_number(route["capacity_used_pct"], 0)}% da carga',
            loc="left",
            fontsize=10,
            color=INK,
        )

    for ax in flat_axes[len(routes):]:
        ax.axis("off")

    handles = [
        Line2D([], [], marker="s", linestyle="", color=INK, label="Centro de distribuição"),
        Line2D([], [], marker="D", linestyle="", color=INK_SECONDARY, label="Entrega crítica"),
        Line2D([], [], marker="o", linestyle="", color=INK_SECONDARY, label="Demais entregas"),
        Line2D([], [], marker="o", linestyle="", color=GRID, label="Paradas de outros veículos"),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=4,
        frameon=False,
        fontsize=9,
        labelcolor=INK_SECONDARY,
    )
    fig.suptitle(
        f'Rotas por veículo: {plan["method"]}',
        x=0.01,
        ha="left",
        fontsize=12,
        color=INK,
        fontweight="semibold",
    )
    fig.subplots_adjust(bottom=0.1)
    return _save(fig, output_path)


def plot_weekly_distance(history: dict, output_path: Union[str, Path]) -> Path:
    """
    Compara, dia a dia, a distância do plano otimizado e a da referência.

    Parameters:
    - history: histórico gerado por simulation.simulate_week.
    - output_path: caminho do arquivo PNG.

    Returns:
    Path: o caminho do arquivo gerado.
    """
    days = history["days"]
    labels = [day["weekday"].split("-")[0].capitalize() for day in days]
    optimized = [day["totals"]["distance_km"] for day in days]
    reference = [day["savings"]["reference_totals"]["distance_km"] for day in days]

    fig, ax = plt.subplots(figsize=(8, 4), facecolor=SURFACE)
    _style_axes(ax)
    ax.grid(False, axis="x")

    positions = list(range(len(days)))
    for values, name, color in (
        (reference, history["reference_method"], SERIES[1]),
        (optimized, history["method"], SERIES[0]),
    ):
        ax.plot(positions, values, color=color, linewidth=1.5, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=name)
        ax.annotate(
            format_number(values[-1]),
            xy=(positions[-1], values[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_SECONDARY,
        )

    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Distância total (km)", fontsize=9, color=INK_SECONDARY)
    ax.set_title("Distância percorrida por dia", loc="left", fontsize=12, color=INK, fontweight="semibold")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY, loc="lower left")
    return _save(fig, output_path)
