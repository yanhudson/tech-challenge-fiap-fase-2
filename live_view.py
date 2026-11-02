"""
Visualização da evolução em tempo real, derivada de tsp.py e draw_functions.py.

Uso:
    python live_view.py            # instância de São Paulo, com uma cor por veículo
    python live_view.py --att48    # benchmark do código base

Para encerrar, feche a janela ou pressione Q.
"""

import argparse
import sys
from typing import List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pygame  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402

from medroute.benchmark_att48 import att_48_cities_locations  # noqa: E402
from medroute.data import load_problem  # noqa: E402
from medroute.engine import GAConfig, run_genetic_algorithm  # noqa: E402
from medroute.fitness import DEFAULT_WEIGHTS, DISTANCE_ONLY_WEIGHTS, decode_chromosome  # noqa: E402
from medroute.genetic_algorithm import DEFAULT_MUTATION_OPERATORS  # noqa: E402
from medroute.models import Priority, Problem  # noqa: E402

# Define constant values
# pygame
WIDTH, HEIGHT = 1100, 620
NODE_RADIUS = 6
FPS = 30
PLOT_X_OFFSET = 420
PLOT_REFRESH_GENERATIONS = 10
MARGIN = 30

# Define colors
WHITE = (255, 255, 255)
BLACK = (11, 11, 11)
GRAY = (195, 194, 183)
ROUTE_COLORS = ((42, 120, 214), (235, 104, 52), (27, 175, 122), (237, 161, 0), (232, 123, 164))


def draw_plot(x: Sequence[int], y: Sequence[float], x_label: str = "Geração", y_label: str = "Fitness") -> pygame.Surface:
    """
    Desenha o gráfico em uma superfície do Pygame.

    Corrige o original: `renderer.tostring_rgb()` não existe nas versões atuais do
    Matplotlib, e a figura nunca era fechada, o que vazava memória a cada quadro.
    """
    fig, ax = plt.subplots(figsize=(4, 4), dpi=100)
    ax.plot(x, y, color="#2a78d6", linewidth=1.5)
    ax.set_ylabel(y_label)
    ax.set_xlabel(x_label)
    ax.grid(True, color="#e1e0d9", linewidth=0.75)
    fig.tight_layout()

    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    raw_data = bytes(canvas.buffer_rgba())
    size = canvas.get_width_height()
    plt.close(fig)
    return pygame.image.frombuffer(raw_data, size, "RGBA")


def draw_cities(screen: pygame.Surface, locations: Sequence[Tuple[int, int]], rgb_color, node_radius: int) -> None:
    for location in locations:
        pygame.draw.circle(screen, rgb_color, location, node_radius)


def draw_paths(screen: pygame.Surface, path: Sequence[Tuple[int, int]], rgb_color, width: int = 1) -> None:
    pygame.draw.lines(screen, rgb_color, True, path, width=width)


def to_screen(problem: Problem, geographic: bool) -> List[Tuple[int, int]]:
    """Converte as coordenadas de cada nó em pixels, à direita do gráfico."""
    points = [(problem.depot.lat, problem.depot.lon)] + [(d.lat, d.lon) for d in problem.deliveries]
    # Nas instâncias geográficas, a longitude é o eixo x e a latitude cresce para o norte.
    xs = [point[1] if geographic else point[0] for point in points]
    ys = [point[0] if geographic else point[1] for point in points]
    x_span = (max(xs) - min(xs)) or 1.0
    y_span = (max(ys) - min(ys)) or 1.0
    area_width = WIDTH - PLOT_X_OFFSET - 2 * MARGIN
    area_height = HEIGHT - 2 * MARGIN

    pixels = []
    for x, y in zip(xs, ys):
        pixel_x = PLOT_X_OFFSET + MARGIN + (x - min(xs)) / x_span * area_width
        relative_y = (y - min(ys)) / y_span
        pixel_y = MARGIN + (1.0 - relative_y if geographic else relative_y) * area_height
        pixels.append((int(pixel_x), int(pixel_y)))
    return pixels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--att48", action="store_true", help="usa o benchmark att48 do código base")
    parser.add_argument("--population", type=int, default=200)
    parser.add_argument("--generations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.att48:
        problem = Problem.from_points(att_48_cities_locations, "att48")
        weights = DISTANCE_ONLY_WEIGHTS
        operators = tuple(name for name in DEFAULT_MUTATION_OPERATORS if name != "priority_promotion")
    else:
        problem = load_problem()
        weights = DEFAULT_WEIGHTS
        operators = DEFAULT_MUTATION_OPERATORS

    config = GAConfig(
        population_size=args.population,
        n_generations=args.generations,
        mutation_operators=operators,
        stagnation_limit=None,
        seed=args.seed,
    )

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Evolução das rotas: {problem.name}")
    clock = pygame.time.Clock()

    pixels = to_screen(problem, geographic=not args.att48)
    critical_pixels = [
        pixels[node]
        for node in range(1, problem.n_deliveries + 1)
        if problem.priority[node] == int(Priority.CRITICAL)
    ]
    best_fitness_values: List[float] = []
    plot_surface = None

    def on_generation(generation: int, population, fitness) -> bool:
        nonlocal plot_surface
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_q):
                return False

        best_fitness_values.append(fitness[0])
        # Gerar a figura é muito mais lento que desenhar as rotas.
        if plot_surface is None or generation % PLOT_REFRESH_GENERATIONS == 0:
            plot_surface = draw_plot(list(range(len(best_fitness_values))), best_fitness_values)

        screen.fill(WHITE)
        screen.blit(plot_surface, (0, 100))

        for index, stops in enumerate(decode_chromosome(population[0], problem.n_deliveries)):
            if stops:
                path = [pixels[0]] + [pixels[node] for node in stops]
                color = ROUTE_COLORS[index % len(ROUTE_COLORS)]
                draw_paths(screen, path, color, width=3 if args.att48 else 2)

        draw_cities(screen, pixels[1:], GRAY, NODE_RADIUS)
        draw_cities(screen, critical_pixels, BLACK, NODE_RADIUS)
        pygame.draw.rect(screen, BLACK, (pixels[0][0] - 7, pixels[0][1] - 7, 14, 14))

        pygame.display.flip()
        clock.tick(FPS)
        print(f"Geração {generation + 1}: melhor fitness = {round(fitness[0], 2)}")
        return True

    result = run_genetic_algorithm(problem, config, weights, on_generation)
    pygame.quit()
    print(f"Melhor fitness: {result.evaluation.fitness:.2f} | Distância: {result.evaluation.distance_km:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
