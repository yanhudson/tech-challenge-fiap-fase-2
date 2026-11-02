"""
Codificação das rotas e função fitness.

O cromossomo é uma permutação de inteiros. Os genes de 1 a n são as entregas e
os genes acima de n são separadores: cada separador encerra a rota de um veículo
e passa para o seguinte. Assim, OX e as mutações do código base continuam válidos.

Exemplo com 5 entregas e 3 veículos (separadores 6 e 7):
    [3, 1, 6, 5, 2, 7, 4]  ->  V1: 3, 1 | V2: 5, 2 | V3: 4
"""

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from .models import Problem

TOLERANCE = 1e-9


@dataclass(frozen=True)
class FitnessWeights:
    """
    Pesos da fitness, em quilômetros equivalentes.

    As tuplas seguem a ordem das prioridades: crítica, alta e regular.
    """

    priority_per_min: Tuple[float, float, float] = (0.30, 0.10, 0.0)
    lateness_per_min: Tuple[float, float, float] = (50.0, 10.0, 2.0)
    overload_per_kg: float = 100.0
    range_excess_per_km: float = 200.0
    shift_excess_per_min: float = 50.0
    cold_chain_violation: float = 5000.0
    vehicle_activation: float = 3.0


DEFAULT_WEIGHTS = FitnessWeights()

# Reproduz o objetivo do código base: minimizar apenas a distância.
DISTANCE_ONLY_WEIGHTS = FitnessWeights(
    priority_per_min=(0.0, 0.0, 0.0),
    lateness_per_min=(0.0, 0.0, 0.0),
    vehicle_activation=0.0,
)


@dataclass
class RouteResult:
    vehicle_index: int
    stops: List[int]
    distance_km: float = 0.0
    load_kg: float = 0.0
    duration_min: float = 0.0
    arrivals_min: List[float] = field(default_factory=list)
    lateness_min: List[float] = field(default_factory=list)
    overload_kg: float = 0.0
    range_excess_km: float = 0.0
    shift_excess_min: float = 0.0
    cold_violations: int = 0
    cost: float = 0.0


@dataclass
class Evaluation:
    routes: List[RouteResult]
    fitness: float
    distance_km: float
    overload_kg: float
    range_excess_km: float
    shift_excess_min: float
    cold_violations: int

    @property
    def is_feasible(self) -> bool:
        """Indica se a solução respeita as restrições rígidas da operação."""
        return (
            self.overload_kg <= TOLERANCE
            and self.range_excess_km <= TOLERANCE
            and self.shift_excess_min <= TOLERANCE
            and self.cold_violations == 0
        )


def chromosome_genes(n_deliveries: int, n_vehicles: int) -> List[int]:
    """Lista os genes de um cromossomo: entregas mais (veículos - 1) separadores."""
    return list(range(1, n_deliveries + n_vehicles))


def decode_chromosome(chromosome: Sequence[int], n_deliveries: int) -> List[List[int]]:
    """Separa o cromossomo em uma lista de paradas por veículo."""
    routes: List[List[int]] = [[]]
    for gene in chromosome:
        if gene > n_deliveries:
            routes.append([])
        else:
            routes[-1].append(gene)
    return routes


def encode_routes(routes: Sequence[Sequence[int]], n_deliveries: int) -> List[int]:
    """Operação inversa de decode_chromosome."""
    chromosome: List[int] = []
    for index, route in enumerate(routes):
        chromosome.extend(route)
        if index < len(routes) - 1:
            chromosome.append(n_deliveries + 1 + index)
    return chromosome


def evaluate_route(
    stops: Sequence[int],
    vehicle_index: int,
    problem: Problem,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> RouteResult:
    """
    Simula a rota de um veículo, parada a parada, e calcula o custo dela.

    Parameters:
    - stops: nós visitados, em ordem, sem o CD.
    - vehicle_index: posição do veículo na frota.
    - problem: a instância de roteamento.
    - weights: pesos da fitness.

    Returns:
    RouteResult: métricas da rota e sua contribuição para a fitness.
    """
    if not stops:
        return RouteResult(vehicle_index, [])

    vehicle = problem.vehicles[vehicle_index]
    matrix = problem.distance_matrix
    km_per_min = vehicle.speed_kmh / 60.0

    previous = 0
    distance = 0.0
    clock = 0.0
    load = 0.0
    soft_cost = 0.0
    cold_violations = 0
    arrivals: List[float] = []
    lateness: List[float] = []

    for stop in stops:
        leg = matrix[previous][stop]
        distance += leg
        clock += leg / km_per_min
        arrivals.append(clock)

        rank = problem.priority[stop] - 1
        soft_cost += weights.priority_per_min[rank] * clock

        deadline = problem.deadline[stop]
        late = clock - deadline if deadline is not None and clock > deadline else 0.0
        lateness.append(late)
        soft_cost += weights.lateness_per_min[rank] * late

        clock += problem.service[stop]
        load += problem.demand[stop]
        if problem.cold[stop] and not vehicle.refrigerated:
            cold_violations += 1
        previous = stop

    back = matrix[previous][0]
    distance += back
    clock += back / km_per_min

    overload = max(0.0, load - vehicle.capacity_kg)
    range_excess = max(0.0, distance - vehicle.range_km)
    shift_excess = max(0.0, clock - problem.shift_min)

    cost = (
        distance
        + soft_cost
        + weights.vehicle_activation
        + weights.overload_per_kg * overload
        + weights.range_excess_per_km * range_excess
        + weights.shift_excess_per_min * shift_excess
        + weights.cold_chain_violation * cold_violations
    )

    return RouteResult(
        vehicle_index=vehicle_index,
        stops=list(stops),
        distance_km=distance,
        load_kg=load,
        duration_min=clock,
        arrivals_min=arrivals,
        lateness_min=lateness,
        overload_kg=overload,
        range_excess_km=range_excess,
        shift_excess_min=shift_excess,
        cold_violations=cold_violations,
        cost=cost,
    )


def evaluate_routes(
    routes: Sequence[Sequence[int]],
    problem: Problem,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> Evaluation:
    """Avalia um plano completo: a lista de paradas de cada veículo."""
    results = [
        evaluate_route(stops, index, problem, weights)
        for index, stops in enumerate(routes)
    ]
    return Evaluation(
        routes=results,
        fitness=sum(result.cost for result in results),
        distance_km=sum(result.distance_km for result in results),
        overload_kg=sum(result.overload_kg for result in results),
        range_excess_km=sum(result.range_excess_km for result in results),
        shift_excess_min=sum(result.shift_excess_min for result in results),
        cold_violations=sum(result.cold_violations for result in results),
    )


def calculate_fitness(
    chromosome: Sequence[int],
    problem: Problem,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> float:
    """
    Calcula a fitness de um cromossomo (quanto menor, melhor).

    Mantém o nome da função do código base, mas soma à distância os termos de
    prioridade, de prazo e as penalidades das restrições.
    """
    routes = decode_chromosome(chromosome, problem.n_deliveries)
    return evaluate_routes(routes, problem, weights).fitness
