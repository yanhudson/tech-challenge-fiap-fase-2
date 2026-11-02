"""Mapa interativo das rotas, em HTML, gerado com Folium."""

import html
from pathlib import Path
from statistics import mean
from typing import Union

import folium

from .metrics import format_number

# Paleta categórica. Cada veículo mantém sempre a mesma cor em todas as figuras.
ROUTE_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
# O amarelo é o único tom da paleta que pede texto escuro por cima.
DARK_TEXT_FILLS = {"#eda100"}


def route_color(vehicle_index: int) -> str:
    return ROUTE_COLORS[vehicle_index % len(ROUTE_COLORS)]


def _stop_icon(stop: dict, color: str) -> folium.DivIcon:
    text_color = INK if color in DARK_TEXT_FILLS else "#ffffff"
    # Entregas críticas ganham um contorno escuro, para não dependerem só da cor.
    is_critical = stop["priority"] == "crítica"
    border = f"3px solid {INK}" if is_critical else "2px solid #ffffff"
    label = f"{stop['sequence']}"
    style = (
        f"width:26px;height:26px;border-radius:50%;"
        f"background:{color};color:{text_color};border:{border};text-align:center;"
        f"font:600 12px/{20 if is_critical else 22}px system-ui,'Segoe UI',sans-serif;box-sizing:border-box;"
    )
    return folium.DivIcon(icon_size=(26, 26), icon_anchor=(13, 13), html=f'<div style="{style}">{label}</div>')


def _depot_icon() -> folium.DivIcon:
    style = (
        f"width:30px;height:30px;border-radius:6px;background:{INK};color:#ffffff;border:2px solid #ffffff;"
        "text-align:center;font:700 11px/26px system-ui,'Segoe UI',sans-serif;box-sizing:border-box;"
    )
    return folium.DivIcon(icon_size=(30, 30), icon_anchor=(15, 15), html=f'<div style="{style}">CD</div>')


def _stop_popup(stop: dict, vehicle_name: str) -> str:
    deadline = stop["deadline"] or "sem prazo"
    lines = [
        f"<b>{stop['sequence']}. {html.escape(stop['name'])}</b> ({html.escape(stop['id'])})",
        f"Veículo: {html.escape(vehicle_name)}",
        f"Item: {html.escape(stop['item'])} ({stop['demand_kg']} kg)",
        f"Prioridade: {html.escape(stop['priority'])}",
        f"Chegada prevista: {stop['arrival']} | Prazo: {deadline}",
    ]
    if stop["cold_chain"]:
        lines.append("Cadeia fria: manter refrigerado")
    if stop["late_min"] > 0:
        lines.append(f"<b>Atraso previsto: {stop['late_min']} min</b>")
    return "<br>".join(lines)


def _legend(plan: dict) -> str:
    rows = "".join(
        '<div style="margin:2px 0">'
        f'<span style="display:inline-block;width:18px;height:3px;background:{route_color(route["vehicle_index"])};'
        'vertical-align:middle;margin-right:6px"></span>'
        f'{html.escape(route["vehicle_name"])}: {format_number(route["distance_km"])} km, {len(route["stops"])} paradas'
        "</div>"
        for route in plan["routes"]
    )
    totals = plan["totals"]
    return (
        f'<div style="position:fixed;bottom:24px;left:16px;z-index:9999;background:{SURFACE};color:{INK};'
        "padding:10px 12px;border-radius:8px;box-shadow:0 1px 6px rgba(11,11,11,.25);"
        "font:12px system-ui,'Segoe UI',sans-serif;max-width:320px\">"
        f'<div style="font-weight:600;margin-bottom:4px">{html.escape(plan["method"])}</div>'
        f"{rows}"
        f'<div style="margin-top:6px;color:{INK_SECONDARY}">'
        f'Total: {format_number(totals["distance_km"])} km | Críticas no prazo: {format_number(totals["critical_on_time_rate_pct"])}%<br>'
        "CD é o centro de distribuição. O número indica a ordem da parada. Contorno escuro indica entrega crítica. "
        "As linhas ligam as paradas em reta e não seguem as ruas."
        "</div></div>"
    )


def build_route_map(plan: dict, output_path: Union[str, Path], legend: bool = True) -> Path:
    """
    Gera o mapa interativo de um plano.

    Cada veículo fica em uma camada que pode ser ligada ou desligada. As paradas
    mostram os detalhes da entrega ao clicar.

    Parameters:
    - plan: resumo do plano, gerado por metrics.summarize_plan.
    - output_path: caminho do arquivo HTML.
    - legend: inclui a legenda fixa. Quem embute o mapa pode explicá-lo fora dele, porque
      em uma área menor a legenda cobre paradas.

    Returns:
    Path: o caminho do arquivo gerado.
    """
    depot = plan["depot"]
    depot_point = [depot["lat"], depot["lon"]]
    stops = [stop for route in plan["routes"] for stop in route["stops"]]
    latitudes = [depot["lat"]] + [stop["lat"] for stop in stops]
    longitudes = [depot["lon"]] + [stop["lon"] for stop in stops]

    route_map = folium.Map(location=[mean(latitudes), mean(longitudes)], zoom_start=11, tiles=None)
    # O fundo atenuado deixa as rotas em primeiro plano.
    folium.TileLayer("OpenStreetMap", opacity=0.45, control=False).add_to(route_map)

    for route in plan["routes"]:
        color = route_color(route["vehicle_index"])
        layer = folium.FeatureGroup(name=f'{html.escape(route["vehicle_name"])} ({format_number(route["distance_km"])} km)')
        points = [depot_point] + [[stop["lat"], stop["lon"]] for stop in route["stops"]] + [depot_point]
        folium.PolyLine(
            points,
            color=color,
            weight=3,
            opacity=0.9,
            tooltip=f'{html.escape(route["vehicle_name"])}: {format_number(route["distance_km"])} km',
        ).add_to(layer)
        for stop in route["stops"]:
            folium.Marker(
                [stop["lat"], stop["lon"]],
                icon=_stop_icon(stop, color),
                tooltip=f'{stop["sequence"]}. {html.escape(stop["name"])} ({stop["arrival"]})',
                popup=folium.Popup(_stop_popup(stop, route["vehicle_name"]), max_width=320),
            ).add_to(layer)
        layer.add_to(route_map)

    folium.Marker(
        depot_point,
        tooltip=html.escape(depot["name"]),
        popup=folium.Popup(f'<b>{html.escape(depot["name"])}</b><br>Saída: {plan["departure"]}', max_width=320),
        icon=_depot_icon(),
    ).add_to(route_map)

    route_map.fit_bounds(
        [[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]],
        padding=(40, 40),
    )
    folium.LayerControl(collapsed=False).add_to(route_map)
    if legend:
        route_map.get_root().html.add_child(folium.Element(_legend(plan)))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    route_map.save(str(output))
    return output
