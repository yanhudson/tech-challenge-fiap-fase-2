"""
Reproduz os experimentos do relatório técnico.

Uso:
    python run_experiments.py            # grava em docs/results e atualiza as tabelas do relatório
    python run_experiments.py --quick    # teste rápido em outputs/quick_results; não altera o relatório

A execução completa roda o algoritmo genético dezenas de vezes e leva alguns minutos.
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from medroute.baselines import sequential_routes
from medroute.data import load_problem
from medroute.engine import GAConfig
from medroute.experiments import (
    ABLATION_COLUMNS,
    COMPARISON_COLUMNS,
    markdown_table,
    replace_marked_section,
    run_att48_ablation,
    run_method_comparison,
    run_sensitivity,
    write_csv,
)
from medroute.metrics import attach_comparison, find_patterns, format_number, summarize_plan
from medroute.simulation import GA_METHOD, REFERENCE_METHOD, simulate_week
from medroute.viz_charts import (
    plot_convergence,
    plot_method_comparison,
    plot_routes_small_multiples,
    plot_weekly_distance,
)
from medroute.viz_map import build_route_map

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "docs" / "results"
QUICK_RESULTS_DIR = PROJECT_ROOT / "outputs" / "quick_results"
REPORT_PATH = PROJECT_ROOT / "docs" / "relatorio_tecnico.md"

WEEK_COLUMNS = (
    ("date", "Data"),
    ("weekday", "Dia"),
    ("deliveries", "Entregas"),
    ("distance_km", "Distância do AG (km)"),
    ("reference_distance_km", "Distância da referência (km)"),
    ("critical_on_time_rate_pct", "Críticas no prazo (%)"),
)


def _step(text: str) -> None:
    print(f"\n>>> {text}", flush=True)


def week_summary(patterns: dict) -> str:
    """Resume o período, para acompanhar a tabela diária."""
    totals = patterns["totals"]
    savings = patterns["savings"]
    service = patterns["service_level"]
    return (
        f"**Total do período:** {totals['deliveries']} entregas e {format_number(totals['distance_km'])} km. "
        f"Em relação à referência simulada: {format_number(savings['distance_km_saved'])} km a menos "
        f"({format_number(savings['distance_saved_pct'])}%), R$ {format_number(savings['cost_brl_saved'], 2)} a menos "
        f"({format_number(savings['cost_saved_pct'])}%) e {format_number(savings['route_minutes_saved'])} min "
        f"a menos em rota ({format_number(savings['route_minutes_saved_pct'])}%). "
        f"Dias com violação de restrição: {service['infeasible_days']}."
    )


def build_results_markdown(tables: dict, seeds: int, quick: bool) -> str:
    """Monta o documento com todas as tabelas de resultados."""
    note = "Execução rápida, apenas para testar a instalação. Não use no relatório." if quick else ""
    return "\n\n".join(
        part
        for part in (
            "# Resultados dos experimentos",
            f"Gerados por `run_experiments.py`, com {seeds} sementes no comparativo. {note}".strip(),
            "## Comparativo entre métodos",
            tables["comparativo"],
            "## Efeito de cada correção no att48",
            tables["ablacao"],
            "## Sensibilidade aos parâmetros",
            tables["sensibilidade"],
            "## Semana simulada",
            tables["semana"],
        )
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="orçamento reduzido; não altera o relatório")
    parser.add_argument("--seeds", type=int, default=None, help="execuções do AG no comparativo")
    args = parser.parse_args()

    if args.quick:
        results = QUICK_RESULTS_DIR
        config = GAConfig(population_size=60, n_generations=100)
        seeds = args.seeds or 2
        sensitivity_seeds, ablation_seeds, ablation_generations, ortools_limit = 1, 1, 100, 5
    else:
        results = RESULTS_DIR
        config = GAConfig()
        seeds = args.seeds or 10
        sensitivity_seeds, ablation_seeds, ablation_generations, ortools_limit = 5, 5, 1500, 30

    results.mkdir(parents=True, exist_ok=True)
    problem = load_problem()
    tables = {}

    _step(f"Comparativo entre métodos ({seeds} execuções do AG)")
    comparison, best = run_method_comparison(problem, config, n_seeds=seeds, ortools_time_limit_s=ortools_limit)
    write_csv(comparison, results / "comparativo.csv")
    tables["comparativo"] = markdown_table(comparison, COMPARISON_COLUMNS)
    print(tables["comparativo"])

    labels = [row["method"] for row in comparison]
    plot_method_comparison(
        labels,
        [row["distance_km_mean"] for row in comparison],
        results / "comparativo_distancia.png",
        "Distância total por método",
        "Distância média (km)",
    )
    plot_method_comparison(
        labels,
        [row["fitness_mean"] for row in comparison],
        results / "comparativo_fitness.png",
        "Fitness por método (menor é melhor)",
        "Fitness média (km equivalentes)",
    )

    plan = summarize_plan(problem, best.best_routes, GA_METHOD)
    attach_comparison(plan, summarize_plan(problem, sequential_routes(problem), REFERENCE_METHOD))
    (results / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    build_route_map(plan, results / "rotas.html")
    plot_routes_small_multiples(plan, results / "rotas_por_veiculo.png")
    plot_convergence({"Melhor fitness": best.best_fitness_history}, results / "convergencia.png")

    _step("Efeito de cada correção sobre o código base (att48)")
    ablation = run_att48_ablation(ablation_seeds, ablation_generations)
    write_csv(ablation, results / "att48_ablacao.csv")
    tables["ablacao"] = markdown_table(ablation, ABLATION_COLUMNS)
    print(tables["ablacao"])

    _step("Sensibilidade aos parâmetros")
    sensitivity = run_sensitivity(problem, config, n_seeds=sensitivity_seeds)
    write_csv(sensitivity, results / "sensibilidade.csv")
    sensitivity_columns = (("method", "Configuração"),) + COMPARISON_COLUMNS[1:]
    tables["sensibilidade"] = markdown_table(sensitivity, sensitivity_columns)
    print(tables["sensibilidade"])

    _step("Semana simulada")
    history = simulate_week(problem, config=replace(config, seed=None))
    (results / "historico.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    plot_weekly_distance(history, results / "semana_distancia.png")
    patterns = find_patterns(history)
    write_csv(patterns["daily"], results / "semana.csv")
    tables["semana"] = markdown_table(patterns["daily"], WEEK_COLUMNS) + "\n\n" + week_summary(patterns)
    print(tables["semana"])

    (results / "resultados.md").write_text(build_results_markdown(tables, seeds, args.quick), encoding="utf-8")

    if args.quick:
        print(f"\nResultados rápidos em {results}. O relatório não foi alterado.")
        return 0

    report = REPORT_PATH.read_text(encoding="utf-8")
    for marker, table in tables.items():
        report = replace_marked_section(report, marker, table)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\nResultados em {results}. Tabelas atualizadas em {REPORT_PATH}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
