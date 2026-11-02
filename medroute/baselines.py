"""
Abordagens usadas no comparativo com o algoritmo genético.

- sequential_routes: despacho sem otimização, na ordem dos pedidos.
- nearest_neighbour_routes: heurística gulosa do vizinho mais próximo.
- brute_force_routes: solução exata, viável apenas em instâncias muito pequenas.
- ortools_routes: solver de roteamento do Google OR-Tools (dependência opcional).

Todas devolvem uma lista de paradas por veículo. A avaliação é feita sempre pela
mesma função fitness, para que a comparação seja justa.
"""

import itertools
import math
import random
from typing import List, Optional, Sequence, Tuple

from .fitness import (
    DEFAULT_WEIGHTS,
    FitnessWeights,
    calculate_fitness,
    chromosome_genes,
    decode_chromosome,
)
from .models import Problem

Routes = List[List[int]]


class _RouteBuilder:
    """Monta a rota de um veículo respeitando as restrições rígidas."""

    def __init__(self, vehicle_index: int, problem: Problem):
        self.problem = problem
        self.vehicle = problem.vehicles[vehicle_index]
        self.stops: List[int] = []
        self.load = 0.0
        self.distance = 0.0
        self.clock = 0.0

    def _last(self) -> int:
        return self.stops[-1] if self.stops else 0

    def fits(self, node: int) -> bool:
        problem, vehicle = self.problem, self.vehicle
        if problem.cold[node] and not vehicle.refrigerated:
            return False
        if self.load + problem.demand[node] > vehicle.capacity_kg:
            return False
        leg = problem.distance_matrix[self._last()][node]
        back = problem.distance_matrix[node][0]
        if self.distance + leg + back > vehicle.range_km:
            return False
        travel_min = (leg + back) / (vehicle.speed_kmh / 60.0)
        return self.clock + travel_min + problem.service[node] <= problem.shift_min

    def add(self, node: int) -> None:
        problem = self.problem
        leg = problem.distance_matrix[self._last()][node]
        self.distance += leg
        self.clock += leg / (self.vehicle.speed_kmh / 60.0) + problem.service[node]
        self.load += problem.demand[node]
        self.stops.append(node)


def _place_leftovers(builders: Sequence[_RouteBuilder], leftovers: Sequence[int], problem: Problem) -> None:
    """Coloca as paradas que não couberam, para que nenhuma entrega seja omitida."""
    for node in leftovers:
        compatible = [
            builder
            for builder in builders
            if builder.vehicle.refrigerated or not problem.cold[node]
        ]
        target = max(compatible or builders, key=lambda builder: builder.vehicle.capacity_kg - builder.load)
        target.add(node)


def sequential_routes(problem: Problem) -> Routes:
    """
    Simula um despacho sem otimização.

    Os itens refrigerados vão primeiro para os veículos refrigerados. Depois, cada
    pedido ocupa o primeiro veículo com espaço, e as paradas seguem a ordem da lista.
    """
    builders = [_RouteBuilder(index, problem) for index in range(problem.n_vehicles)]
    cold_nodes = [node for node in range(1, problem.n_deliveries + 1) if problem.cold[node]]
    other_nodes = [node for node in range(1, problem.n_deliveries + 1) if not problem.cold[node]]

    leftovers = []
    for node in cold_nodes + other_nodes:
        for builder in builders:
            if builder.fits(node):
                builder.add(node)
                break
        else:
            leftovers.append(node)

    _place_leftovers(builders, leftovers, problem)
    return [builder.stops for builder in builders]


def _grow_route(builder, pool, unvisited, problem, rng, candidates) -> None:
    while True:
        feasible = [node for node in pool if node in unvisited and builder.fits(node)]
        if not feasible:
            return
        last = builder.stops[-1] if builder.stops else 0
        feasible.sort(key=lambda node: problem.distance_matrix[last][node])
        node = feasible[0] if rng is None else rng.choice(feasible[:candidates])
        builder.add(node)
        unvisited.discard(node)


def nearest_neighbour_routes(
    problem: Problem,
    rng: Optional[random.Random] = None,
    candidates: int = 3,
) -> Routes:
    """
    Heurística do vizinho mais próximo, sugerida em um TODO do código base.

    Os veículos refrigerados atendem primeiro à cadeia fria. Depois, cada veículo
    segue para a parada viável mais próxima.

    Parameters:
    - problem: a instância de roteamento.
    - rng: com um gerador, sorteia entre as paradas mais próximas e embaralha a
      ordem dos veículos, o que dá diversidade à população inicial.
    - candidates: quantas paradas próximas entram no sorteio.

    Returns:
    Routes: a lista de paradas de cada veículo.
    """
    builders = [_RouteBuilder(index, problem) for index in range(problem.n_vehicles)]
    all_nodes = list(range(1, problem.n_deliveries + 1))
    cold_nodes = [node for node in all_nodes if problem.cold[node]]
    unvisited = set(all_nodes)

    for builder in builders:
        if builder.vehicle.refrigerated:
            _grow_route(builder, cold_nodes, unvisited, problem, rng, candidates)

    order = list(builders)
    if rng is not None:
        rng.shuffle(order)
    for builder in order:
        _grow_route(builder, all_nodes, unvisited, problem, rng, candidates)

    _place_leftovers(builders, sorted(unvisited), problem)
    return [builder.stops for builder in builders]


def brute_force_routes(
    problem: Problem,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
    max_genes: int = 10,
) -> Tuple[Routes, float]:
    """
    Testa todas as permutações do cromossomo e devolve a melhor.

    Serve de referência exata em instâncias muito pequenas. O número de
    permutações cresce fatorialmente, por isso há um limite de genes.
    """
    genes = chromosome_genes(problem.n_deliveries, problem.n_vehicles)
    if len(genes) > max_genes:
        raise ValueError(f"Força bruta limitada a {max_genes} genes; a instância tem {len(genes)}.")

    best_chromosome = None
    best_fitness = math.inf
    for candidate in itertools.permutations(genes):
        fitness = calculate_fitness(candidate, problem, weights)
        if fitness < best_fitness:
            best_fitness = fitness
            best_chromosome = candidate
    return decode_chromosome(best_chromosome, problem.n_deliveries), best_fitness


def ortools_routes(
    problem: Problem,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
    time_limit_s: int = 30,
) -> Optional[Routes]:
    """
    Resolve o problema com o solver de roteamento do OR-Tools.

    O objetivo reproduz a fitness: distância, custo por veículo usado, tempo de espera
    ponderado pela prioridade e atraso. Capacidade, autonomia, jornada e cadeia fria
    são restrições rígidas. Distâncias usam metros, pesos usam décimos de kg e tempos
    usam décimos de minuto, porque o solver trabalha com inteiros.

    Parameters:
    - problem: a instância de roteamento.
    - weights: pesos da fitness, convertidos para os coeficientes do solver.
    - time_limit_s: tempo máximo de busca, em segundos.

    Returns:
    Routes ou None, quando o solver não encontra uma solução viável.
    """
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError as exc:
        raise RuntimeError("OR-Tools não instalado. Execute: pip install ortools") from exc

    vehicles = problem.vehicles
    matrix = problem.distance_matrix
    manager = pywrapcp.RoutingIndexManager(problem.n_deliveries + 1, problem.n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(round(matrix[from_node][to_node] * 1000))

    distance_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(distance_index)
    routing.SetFixedCostOfAllVehicles(int(round(weights.vehicle_activation * 1000)))

    def demand_callback(from_index):
        return int(round(problem.demand[manager.IndexToNode(from_index)] * 10))

    demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_index, 0, [int(vehicle.capacity_kg * 10) for vehicle in vehicles], True, "Capacity"
    )
    routing.AddDimensionWithVehicleCapacity(
        distance_index, 0, [int(vehicle.range_km * 1000) for vehicle in vehicles], True, "Range"
    )

    def make_time_callback(km_per_min):
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            minutes = matrix[from_node][to_node] / km_per_min + problem.service[from_node]
            return int(round(minutes * 10))

        return time_callback

    # O solver não guarda referência às funções em Python; a lista as mantém vivas.
    time_callbacks = [make_time_callback(vehicle.speed_kmh / 60.0) for vehicle in vehicles]
    time_indexes = [routing.RegisterTransitCallback(callback) for callback in time_callbacks]
    horizon = int(problem.shift_min * 10)
    routing.AddDimensionWithVehicleTransits(time_indexes, 0, horizon, True, "Time")
    # Cada nó aceita um único limite flexível por dimensão. Por isso, uma segunda
    # dimensão de tempo representa o custo de espera ponderado pela prioridade.
    routing.AddDimensionWithVehicleTransits(time_indexes, 0, horizon, True, "PriorityTime")
    time_dimension = routing.GetDimensionOrDie("Time")
    priority_dimension = routing.GetDimensionOrDie("PriorityTime")

    refrigerated = [index for index, vehicle in enumerate(vehicles) if vehicle.refrigerated]

    for node in range(1, problem.n_deliveries + 1):
        index = manager.NodeToIndex(node)
        rank = problem.priority[node] - 1

        deadline = problem.deadline[node]
        if deadline is not None:
            # De km por minuto para metros por décimo de minuto: multiplica por 100.
            late_coefficient = int(round(weights.lateness_per_min[rank] * 100))
            if late_coefficient > 0:
                time_dimension.SetCumulVarSoftUpperBound(index, int(deadline * 10), late_coefficient)

        wait_coefficient = int(round(weights.priority_per_min[rank] * 100))
        if wait_coefficient > 0:
            priority_dimension.SetCumulVarSoftUpperBound(index, 0, wait_coefficient)

        if problem.cold[node]:
            routing.VehicleVar(index).SetValues([-1] + refrigerated)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_parameters.time_limit.FromSeconds(int(time_limit_s))

    solution = routing.SolveWithParameters(search_parameters)
    if solution is None:
        return None

    routes: Routes = []
    for vehicle_index in range(problem.n_vehicles):
        stops = []
        index = routing.Start(vehicle_index)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                stops.append(node)
            index = solution.Value(routing.NextVar(index))
        routes.append(stops)
    return routes
