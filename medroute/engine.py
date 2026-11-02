"""
Laço evolutivo, derivado do laço principal de genetic_algorithm_tsp/tsp.py.

Além das restrições, corrige o cruzamento do código base, que combinava o pai com
ele mesmo (`order_crossover(parent1, parent1)`) e devolvia sempre uma cópia do pai.
"""

import itertools
import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .baselines import nearest_neighbour_routes
from .fitness import (
    DEFAULT_WEIGHTS,
    Evaluation,
    FitnessWeights,
    calculate_fitness,
    chromosome_genes,
    decode_chromosome,
    encode_routes,
    evaluate_routes,
)
from .genetic_algorithm import (
    CROSSOVERS,
    DEFAULT_MUTATION_OPERATORS,
    Chromosome,
    generate_random_population,
    mutate,
    sort_population,
    tournament_selection,
)
from .models import Priority, Problem

# Recebe geração, população e fitness; se devolver False, interrompe a evolução.
GenerationCallback = Callable[[int, List[Chromosome], List[float]], Optional[bool]]


@dataclass(frozen=True)
class GAConfig:
    population_size: int = 200
    n_generations: int = 1000
    crossover: str = "ox"  # "ox", "pmx" ou "none"
    crossover_probability: float = 0.9
    selection: str = "tournament"  # "tournament", "roulette" ou "truncation"
    tournament_size: int = 3
    truncation_size: int = 10
    mutation_probability: float = 0.5
    mutation_intensity: float = 0.25
    mutation_operators: Tuple[str, ...] = DEFAULT_MUTATION_OPERATORS
    elitism: int = 4
    seeded_fraction: float = 0.1
    stagnation_limit: Optional[int] = 300
    seed: Optional[int] = None


@dataclass
class GAResult:
    best_chromosome: Chromosome
    best_routes: List[List[int]]
    evaluation: Evaluation
    best_fitness_history: List[float] = field(default_factory=list)
    mean_fitness_history: List[float] = field(default_factory=list)
    generations_run: int = 0
    elapsed_s: float = 0.0


def _initial_population(problem: Problem, config: GAConfig, rng: random.Random) -> List[Chromosome]:
    """
    Combina indivíduos da heurística do vizinho mais próximo com indivíduos aleatórios.

    O primeiro é o vizinho mais próximo determinístico. Com elitismo, isso garante
    que o resultado do algoritmo nunca seja pior que o dessa heurística.
    """
    genes = chromosome_genes(problem.n_deliveries, problem.n_vehicles)
    n_seeded = int(config.population_size * config.seeded_fraction)

    population: List[Chromosome] = []
    for index in range(n_seeded):
        routes = nearest_neighbour_routes(problem, rng=None if index == 0 else rng)
        population.append(encode_routes(routes, problem.n_deliveries))

    population.extend(generate_random_population(genes, config.population_size - len(population), rng))
    return population


def _build_selector(population, fitness, config: GAConfig, rng: random.Random):
    """Cria a função de seleção da geração. A população já deve estar ordenada."""
    if config.selection == "tournament":
        return lambda: tournament_selection(population, fitness, config.tournament_size, rng)
    if config.selection == "roulette":
        # Seleção do código base: probabilidade proporcional a 1 / fitness. Os pesos
        # são acumulados uma vez por geração, em vez de recalculados a cada filho.
        cumulative = list(itertools.accumulate(1.0 / max(value, 1e-9) for value in fitness))
        return lambda: rng.choices(population, cum_weights=cumulative, k=1)[0]
    if config.selection == "truncation":
        # Seleção usada nos dois repositórios de referência: sorteio entre os melhores.
        top = population[: config.truncation_size]
        return lambda: rng.choice(top)
    raise ValueError(f"Seleção desconhecida: {config.selection}")


def _crossover_children(parent1, parent2, config: GAConfig, rng: random.Random):
    """Gera dois filhos por cruzamento, como no repositório de camuflagem."""
    if config.crossover == "none" or rng.random() >= config.crossover_probability:
        return list(parent1), list(parent2)
    crossover = CROSSOVERS.get(config.crossover)
    if crossover is None:
        raise ValueError(f"Cruzamento desconhecido: {config.crossover}")
    return crossover(parent1, parent2, rng), crossover(parent2, parent1, rng)


def run_genetic_algorithm(
    problem: Problem,
    config: GAConfig = GAConfig(),
    weights: FitnessWeights = DEFAULT_WEIGHTS,
    on_generation: Optional[GenerationCallback] = None,
) -> GAResult:
    """
    Executa o algoritmo genético.

    Parameters:
    - problem: a instância de roteamento.
    - config: parâmetros do algoritmo.
    - weights: pesos da fitness.
    - on_generation: função chamada a cada geração, usada na visualização ao vivo.

    Returns:
    GAResult: a melhor solução encontrada e o histórico da evolução.
    """
    rng = random.Random(config.seed)
    priority_genes = [
        node
        for node in range(1, problem.n_deliveries + 1)
        if problem.priority[node] == int(Priority.CRITICAL)
    ]

    population = _initial_population(problem, config, rng)
    best_chromosome: Chromosome = list(population[0])
    best_fitness = math.inf
    stagnant_generations = 0
    best_history: List[float] = []
    mean_history: List[float] = []
    started = time.perf_counter()

    for generation in range(config.n_generations):
        population_fitness = [calculate_fitness(individual, problem, weights) for individual in population]
        population, population_fitness = sort_population(population, population_fitness)

        if population_fitness[0] < best_fitness - 1e-9:
            best_fitness = population_fitness[0]
            best_chromosome = list(population[0])
            stagnant_generations = 0
        else:
            stagnant_generations += 1

        best_history.append(best_fitness)
        mean_history.append(sum(population_fitness) / len(population_fitness))

        if on_generation is not None and on_generation(generation, population, population_fitness) is False:
            break
        if config.stagnation_limit is not None and stagnant_generations >= config.stagnation_limit:
            break

        select_parent = _build_selector(population, population_fitness, config, rng)
        new_population = [list(individual) for individual in population[: config.elitism]]  # ELITISMO

        while len(new_population) < config.population_size:
            parent1, parent2 = select_parent(), select_parent()
            for child in _crossover_children(parent1, parent2, config, rng):
                new_population.append(
                    mutate(
                        child,
                        config.mutation_probability,
                        rng,
                        config.mutation_operators,
                        config.mutation_intensity,
                        problem.n_deliveries,
                        priority_genes,
                    )
                )

        population = new_population[: config.population_size]

    best_routes = decode_chromosome(best_chromosome, problem.n_deliveries)
    return GAResult(
        best_chromosome=best_chromosome,
        best_routes=best_routes,
        evaluation=evaluate_routes(best_routes, problem, weights),
        best_fitness_history=best_history,
        mean_fitness_history=mean_history,
        generations_run=len(best_history),
        elapsed_s=time.perf_counter() - started,
    )
