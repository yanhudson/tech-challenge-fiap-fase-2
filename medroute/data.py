"""Leitura das instâncias em JSON e geração de demanda diária sintética."""

import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

from .models import PRIORITY_BY_NAME, Delivery, Depot, Priority, Problem, Vehicle

DEFAULT_INSTANCE = Path(__file__).resolve().parent.parent / "data" / "instancia_sao_paulo.json"


def parse_clock(text: str) -> int:
    """Converte 'HH:MM' em minutos desde a meia-noite."""
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def load_problem(path: Union[str, Path] = DEFAULT_INSTANCE) -> Problem:
    """
    Carrega uma instância e valida se cada entrega cabe em algum veículo.

    Parameters:
    - path: caminho do arquivo JSON da instância.

    Returns:
    Problem: a instância pronta para otimização.
    """
    return problem_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def problem_from_dict(raw: dict) -> Problem:
    """Monta o problema a partir do conteúdo de uma instância."""
    departure = parse_clock(raw["departure"])

    deliveries = []
    for entry in raw["deliveries"]:
        deadline: Optional[float] = None
        if entry.get("deadline"):
            deadline = float(parse_clock(entry["deadline"]) - departure)
        deliveries.append(
            Delivery(
                id=entry["id"],
                name=entry["name"],
                kind=entry["kind"],
                lat=float(entry["lat"]),
                lon=float(entry["lon"]),
                item=entry["item"],
                demand_kg=float(entry["demand_kg"]),
                priority=PRIORITY_BY_NAME[entry["priority"]],
                deadline_min=deadline,
                service_min=float(entry["service_min"]),
                requires_cold_chain=bool(entry.get("cold_chain", False)),
            )
        )

    vehicles = [
        Vehicle(
            id=entry["id"],
            name=entry["name"],
            capacity_kg=float(entry["capacity_kg"]),
            range_km=float(entry["range_km"]),
            speed_kmh=float(entry["speed_kmh"]),
            cost_per_km=float(entry["cost_per_km"]),
            refrigerated=bool(entry.get("refrigerated", False)),
        )
        for entry in raw["vehicles"]
    ]

    _validate(deliveries, vehicles)

    depot = Depot(raw["depot"]["name"], float(raw["depot"]["lat"]), float(raw["depot"]["lon"]))
    return Problem(
        raw["name"],
        depot,
        deliveries,
        vehicles,
        departure_min=float(departure),
        shift_min=float(raw["shift_hours"]) * 60.0,
        road_factor=float(raw.get("road_factor", 1.0)),
    )


def _validate(deliveries, vehicles) -> None:
    identifiers = [delivery.id for delivery in deliveries]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("A instância tem identificadores de entrega repetidos.")

    for delivery in deliveries:
        compatible = [
            vehicle
            for vehicle in vehicles
            if vehicle.refrigerated or not delivery.requires_cold_chain
        ]
        if not any(delivery.demand_kg <= vehicle.capacity_kg for vehicle in compatible):
            raise ValueError(f"Nenhum veículo compatível comporta a entrega {delivery.id}.")


def generate_daily_problem(base: Problem, rng: random.Random, label: str) -> Problem:
    """
    Sorteia a demanda de um dia a partir da instância base.

    Entregas críticas têm mais chance de ocorrer. O peso varia em até 30%. Os
    dados são sintéticos e servem para demonstrar os relatórios periódicos.

    Parameters:
    - base: instância com todas as entregas possíveis.
    - rng: gerador de números aleatórios, que torna o sorteio reproduzível.
    - label: rótulo do dia, usado no nome da instância.

    Returns:
    Problem: a instância do dia, com a mesma frota da base.
    """
    deliveries = []
    for delivery in base.deliveries:
        chance = 0.9 if delivery.priority == Priority.CRITICAL else 0.75
        if rng.random() > chance:
            continue
        demand = round(delivery.demand_kg * rng.uniform(0.7, 1.3), 1)
        deliveries.append(replace(delivery, demand_kg=demand))
    return base.with_deliveries(deliveries, f"{base.name} - {label}")
