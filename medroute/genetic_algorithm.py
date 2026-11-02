"""
Operadores genéticos, derivados de genetic_algorithm_tsp/genetic_algorithm.py.

Os genes são inteiros em vez de tuplas de coordenadas. Assim, dois endereços
iguais não são confundidos e os operadores não dependem da geografia.
"""

import random
from typing import List, Sequence, Tuple

Chromosome = List[int]

DEFAULT_MUTATION_OPERATORS = ("inversion", "relocation", "gene_swap", "priority_promotion")


def generate_random_population(
    genes: Sequence[int],
    population_size: int,
    rng: random.Random = random,
) -> List[Chromosome]:
    """
    Gera uma população de permutações aleatórias.

    Parameters:
    - genes: genes de um cromossomo.
    - population_size: quantidade de indivíduos.
    - rng: gerador de números aleatórios.

    Returns:
    List[Chromosome]: os indivíduos gerados.
    """
    return [rng.sample(list(genes), len(genes)) for _ in range(population_size)]


def order_crossover(
    parent1: Sequence[int],
    parent2: Sequence[int],
    rng: random.Random = random,
) -> Chromosome:
    """
    Order crossover (OX) do código base: copia um trecho de parent1 e completa com
    os demais genes na ordem de parent2.

    Produz o mesmo resultado do original, sem as buscas lineares em lista.

    Parameters:
    - parent1: pai que cede o trecho.
    - parent2: pai que define a ordem dos demais genes.
    - rng: gerador de números aleatórios.

    Returns:
    Chromosome: o filho, sempre uma permutação válida.
    """
    length = len(parent1)
    start_index = rng.randint(0, length - 1)
    end_index = rng.randint(start_index + 1, length)

    segment = list(parent1[start_index:end_index])
    in_segment = set(segment)
    remaining_genes = [gene for gene in parent2 if gene not in in_segment]

    return remaining_genes[:start_index] + segment + remaining_genes[start_index:]


def partially_mapped_crossover(
    parent1: Sequence[int],
    parent2: Sequence[int],
    rng: random.Random = random,
) -> Chromosome:
    """
    Partially mapped crossover (PMX): copia um trecho de parent1 e herda de parent2
    os demais genes, preservando as posições sempre que possível.

    Parameters:
    - parent1: pai que cede o trecho.
    - parent2: pai que cede os demais genes.
    - rng: gerador de números aleatórios.

    Returns:
    Chromosome: o filho, sempre uma permutação válida.
    """
    length = len(parent1)
    start_index = rng.randint(0, length - 1)
    end_index = rng.randint(start_index + 1, length)

    child = [None] * length
    child[start_index:end_index] = parent1[start_index:end_index]
    copied = set(parent1[start_index:end_index])
    position_in_parent2 = {gene: index for index, gene in enumerate(parent2)}

    for index in range(start_index, end_index):
        gene = parent2[index]
        if gene in copied:
            continue
        target = index
        while start_index <= target < end_index:
            target = position_in_parent2[parent1[target]]
        child[target] = gene

    for index in range(length):
        if child[index] is None:
            child[index] = parent2[index]
    return child


def adjacent_swap(solution: Sequence[int], rng: random.Random = random) -> Chromosome:
    """Troca dois genes vizinhos: é a mutação original do código base."""
    mutated = list(solution)
    if len(mutated) < 2:
        return mutated
    index = rng.randint(0, len(mutated) - 2)
    mutated[index], mutated[index + 1] = mutated[index + 1], mutated[index]
    return mutated


def inversion(
    solution: Sequence[int],
    rng: random.Random = random,
    mutation_intensity: float = 0.25,
) -> Chromosome:
    """
    Inverte um trecho, atendendo ao TODO de mutation_intensity do código base.

    A intensidade limita o tamanho do trecho, como fração do cromossomo. A inversão
    desfaz cruzamentos entre arcos de uma rota.
    """
    mutated = list(solution)
    length = len(mutated)
    if length < 2:
        return mutated
    largest_segment = max(2, int(length * mutation_intensity))
    segment_size = rng.randint(2, largest_segment)
    start = rng.randint(0, length - segment_size)
    end = start + segment_size
    mutated[start:end] = mutated[start:end][::-1]
    return mutated


def relocation(solution: Sequence[int], rng: random.Random = random) -> Chromosome:
    """Move um gene para outra posição, o que pode trocar a parada de veículo."""
    mutated = list(solution)
    if len(mutated) < 2:
        return mutated
    gene = mutated.pop(rng.randrange(len(mutated)))
    mutated.insert(rng.randint(0, len(mutated)), gene)
    return mutated


def gene_swap(solution: Sequence[int], rng: random.Random = random) -> Chromosome:
    """Troca dois genes quaisquer, permitindo permutar paradas entre veículos."""
    mutated = list(solution)
    if len(mutated) < 2:
        return mutated
    first, second = rng.sample(range(len(mutated)), 2)
    mutated[first], mutated[second] = mutated[second], mutated[first]
    return mutated


def priority_promotion(
    solution: Sequence[int],
    rng: random.Random = random,
    n_deliveries: int = 0,
    priority_genes: Sequence[int] = (),
) -> Chromosome:
    """Antecipa uma entrega crítica dentro da rota do próprio veículo."""
    mutated = list(solution)
    if not priority_genes:
        return mutated
    index = mutated.index(rng.choice(list(priority_genes)))
    route_start = index
    while route_start > 0 and mutated[route_start - 1] <= n_deliveries:
        route_start -= 1
    target = rng.randint(route_start, index)
    gene = mutated.pop(index)
    mutated.insert(target, gene)
    return mutated


def mutate(
    solution: Sequence[int],
    mutation_probability: float,
    rng: random.Random = random,
    operators: Sequence[str] = DEFAULT_MUTATION_OPERATORS,
    mutation_intensity: float = 0.25,
    n_deliveries: int = 0,
    priority_genes: Sequence[int] = (),
) -> Chromosome:
    """
    Com a probabilidade indicada, aplica um dos operadores sorteado.

    Parameters:
    - solution: cromossomo original, que não é alterado.
    - mutation_probability: chance de ocorrer mutação.
    - rng: gerador de números aleatórios.
    - operators: nomes dos operadores que podem ser sorteados.
    - mutation_intensity: tamanho máximo do trecho invertido.
    - n_deliveries: quantidade de entregas, para reconhecer os separadores.
    - priority_genes: genes das entregas críticas.

    Returns:
    Chromosome: uma cópia, com ou sem mutação.
    """
    if rng.random() >= mutation_probability:
        return list(solution)

    operator = rng.choice(list(operators))
    if operator == "adjacent_swap":
        return adjacent_swap(solution, rng)
    if operator == "inversion":
        return inversion(solution, rng, mutation_intensity)
    if operator == "relocation":
        return relocation(solution, rng)
    if operator == "gene_swap":
        return gene_swap(solution, rng)
    if operator == "priority_promotion":
        return priority_promotion(solution, rng, n_deliveries, priority_genes)
    raise ValueError(f"Operador de mutação desconhecido: {operator}")


def sort_population(
    population: Sequence[Chromosome],
    fitness: Sequence[float],
) -> Tuple[List[Chromosome], List[float]]:
    """
    Ordena a população pela fitness, do melhor para o pior (função do código base).

    Parameters:
    - population: os indivíduos.
    - fitness: a fitness de cada indivíduo.

    Returns:
    Tuple[List[Chromosome], List[float]]: população e fitness ordenadas.
    """
    combined_lists = sorted(zip(population, fitness), key=lambda pair: pair[1])
    return [pair[0] for pair in combined_lists], [pair[1] for pair in combined_lists]


def tournament_selection(
    population: Sequence[Chromosome],
    fitness: Sequence[float],
    tournament_size: int,
    rng: random.Random = random,
) -> Chromosome:
    """Sorteia alguns indivíduos e devolve o melhor entre eles."""
    size = min(tournament_size, len(population))
    contestants = rng.sample(range(len(population)), size)
    return population[min(contestants, key=lambda index: fitness[index])]


CROSSOVERS = {"ox": order_crossover, "pmx": partially_mapped_crossover}
