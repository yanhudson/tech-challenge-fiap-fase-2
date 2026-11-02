"""Modelos de domínio: entregas, veículos e o problema de roteamento."""

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]


class Priority(IntEnum):
    CRITICAL = 1
    HIGH = 2
    REGULAR = 3


PRIORITY_LABELS = {
    Priority.CRITICAL: "crítica",
    Priority.HIGH: "alta",
    Priority.REGULAR: "regular",
}

PRIORITY_BY_NAME = {
    "critica": Priority.CRITICAL,
    "alta": Priority.HIGH,
    "regular": Priority.REGULAR,
}


@dataclass(frozen=True)
class Depot:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Delivery:
    id: str
    name: str
    kind: str  # "unidade" ou "domiciliar"
    lat: float
    lon: float
    item: str
    demand_kg: float
    priority: Priority
    deadline_min: Optional[float]  # minutos após a saída do CD; None = sem prazo
    service_min: float
    requires_cold_chain: bool = False


@dataclass(frozen=True)
class Vehicle:
    id: str
    name: str
    capacity_kg: float
    range_km: float
    speed_kmh: float
    cost_per_km: float
    refrigerated: bool = False


def calculate_distance(point1: Point, point2: Point) -> float:
    """
    Distância euclidiana entre dois pontos (função do código base).

    Usada no benchmark att48, em que as coordenadas não são geográficas.
    """
    return math.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)


def haversine_km(point1: Point, point2: Point) -> float:
    """Distância em linha reta, em km, entre dois pontos (latitude, longitude)."""
    lat1, lon1 = math.radians(point1[0]), math.radians(point1[1])
    lat2, lon2 = math.radians(point2[0]), math.radians(point2[1])
    half_chord = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(half_chord))


class Problem:
    """
    Instância de roteamento com matriz de distâncias pré-calculada.

    Os nós são numerados assim: 0 é o centro de distribuição (CD) e i >= 1 é a
    entrega deliveries[i - 1]. Sem `distance_fn`, a distância é a de Haversine
    multiplicada por `road_factor`, que aproxima o traçado real das ruas.
    """

    def __init__(
        self,
        name: str,
        depot: Depot,
        deliveries: Sequence[Delivery],
        vehicles: Sequence[Vehicle],
        departure_min: float = 480.0,
        shift_min: float = 480.0,
        road_factor: float = 1.0,
        distance_fn: Optional[Callable[[Point, Point], float]] = None,
    ):
        if not vehicles:
            raise ValueError("O problema precisa de ao menos um veículo.")

        self.name = name
        self.depot = depot
        self.deliveries = tuple(deliveries)
        self.vehicles = tuple(vehicles)
        self.departure_min = departure_min
        self.shift_min = shift_min
        self.road_factor = road_factor
        self.distance_fn = distance_fn
        self.n_deliveries = len(self.deliveries)
        self.n_vehicles = len(self.vehicles)

        measure = distance_fn or (lambda a, b: haversine_km(a, b) * road_factor)
        points = [(depot.lat, depot.lon)] + [(d.lat, d.lon) for d in self.deliveries]
        self.distance_matrix = [[measure(a, b) for b in points] for a in points]

        # Vetores indexados pelo nó, para acesso rápido dentro da fitness.
        self.demand = [0.0] + [d.demand_kg for d in self.deliveries]
        self.service = [0.0] + [d.service_min for d in self.deliveries]
        self.priority = [int(Priority.REGULAR)] + [int(d.priority) for d in self.deliveries]
        self.deadline = [None] + [d.deadline_min for d in self.deliveries]
        self.cold = [False] + [d.requires_cold_chain for d in self.deliveries]

    @classmethod
    def from_points(cls, points: List[Point], name: str = "TSP") -> "Problem":
        """Cria um TSP puro (um veículo, sem restrições), como no código base."""
        depot = Depot("Origem", points[0][0], points[0][1])
        deliveries = [
            Delivery(
                id=f"C{index}",
                name=f"Cidade {index}",
                kind="unidade",
                lat=point[0],
                lon=point[1],
                item="-",
                demand_kg=0.0,
                priority=Priority.REGULAR,
                deadline_min=None,
                service_min=0.0,
            )
            for index, point in enumerate(points[1:], start=1)
        ]
        vehicle = Vehicle("V1", "Caixeiro", math.inf, math.inf, 60.0, 0.0)
        return cls(name, depot, deliveries, [vehicle], shift_min=math.inf, distance_fn=calculate_distance)

    def with_deliveries(self, deliveries: Sequence[Delivery], name: str) -> "Problem":
        """Cria uma instância com a mesma frota e outras entregas."""
        return Problem(
            name,
            self.depot,
            deliveries,
            self.vehicles,
            self.departure_min,
            self.shift_min,
            self.road_factor,
            self.distance_fn,
        )

    def delivery(self, node: int) -> Delivery:
        return self.deliveries[node - 1]

    def clock(self, minutes_after_departure: float) -> str:
        """Converte minutos após a saída em um horário no formato HH:MM."""
        total = int(round(self.departure_min + minutes_after_departure))
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"
