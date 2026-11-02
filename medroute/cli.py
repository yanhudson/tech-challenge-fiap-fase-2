"""Interface de linha de comando: python -m medroute <comando>."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .data import DEFAULT_INSTANCE, load_problem
from .engine import GAConfig
from .experiments import COMPARISON_COLUMNS, markdown_table, run_method_comparison, write_csv
from .geocoding import NominatimGeocoder
from .intake import IntakeSession
from .llm import PROVIDERS, AssistantOutput, LLMError, RouteAssistant, create_client
from .llm.intake_agent import IntakeAgent
from .metrics import format_number
from .simulation import optimize_plan, simulate_week

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs"
DEFAULT_PLAN = DEFAULT_OUTPUT / "plan.json"
DEFAULT_HISTORY = DEFAULT_OUTPUT / "historico.json"
SOLVE_HINT = "Gere o plano antes com: python -m medroute solve"
WEEK_HINT = "Gere o histórico antes com: python -m medroute simulate-week"
EXIT_WORDS = {"sair", "exit", "quit"}


def _read_json(path: Path, hint: str) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}. {hint}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(text: str, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(data: dict, path: Path) -> Path:
    return _write_text(json.dumps(data, ensure_ascii=False, indent=2), path)


def _assistant(args: argparse.Namespace) -> RouteAssistant:
    return RouteAssistant(create_client(args.llm, args.model))


def _show(output: AssistantOutput, save_path: Optional[Path] = None) -> None:
    print(output.text)
    for warning in output.warnings:
        print(f"AVISO: {warning}", file=sys.stderr)
    if save_path is not None:
        notes = [f"> AVISO: {warning}\n" for warning in output.warnings]
        saved = _write_text("\n".join(notes + [output.text]) + "\n", save_path)
        print(f"\nSalvo em {saved}", file=sys.stderr)


def _ga_config(args: argparse.Namespace) -> GAConfig:
    return GAConfig(population_size=args.population, n_generations=args.generations, seed=args.seed)


def command_solve(args: argparse.Namespace) -> int:
    from .viz_charts import plot_convergence, plot_routes_small_multiples
    from .viz_map import build_route_map

    output = Path(args.output)
    problem = load_problem(args.instance)
    print(f"Otimizando {problem.n_deliveries} entrega(s) com {problem.n_vehicles} veículo(s)...", flush=True)

    plan, result = optimize_plan(problem, _ga_config(args))

    plan_path = _write_json(plan, output / "plan.json")
    map_path = build_route_map(plan, output / "rotas.html")
    plot_convergence({"Melhor fitness": result.best_fitness_history}, output / "convergencia.png")
    plot_routes_small_multiples(plan, output / "rotas_por_veiculo.png")

    totals = plan["totals"]
    comparison = plan["comparison"]
    print(f"Gerações: {result.generations_run} em {format_number(result.elapsed_s)} s")
    print(
        f"Distância: {format_number(totals['distance_km'])} km | "
        f"Custo: R$ {format_number(totals['cost_brl'], 2)} | Fitness: {format_number(totals['fitness'])}"
    )
    print(f"Veículos usados: {totals['vehicles_used']} de {totals['vehicles_total']}")
    print(
        f"No prazo: {format_number(totals['on_time_rate_pct'])}% | "
        f"Críticas no prazo: {format_number(totals['critical_on_time_rate_pct'])}%"
    )
    print(f"Respeita todas as restrições rígidas: {'sim' if totals['feasible'] else 'NÃO'}")
    print(
        f"Em relação a '{comparison['reference_method']}': {format_number(comparison['distance_km_saved'])} km "
        f"a menos ({format_number(comparison['distance_saved_pct'])}%)"
    )
    print(f"Plano: {plan_path}\nMapa: {map_path}")
    return 0


def command_compare(args: argparse.Namespace) -> int:
    problem = load_problem(args.instance)
    print(f"Comparando métodos com {args.seeds} execuções do algoritmo genético...", flush=True)
    rows, _ = run_method_comparison(problem, _ga_config(args), n_seeds=args.seeds)
    path = Path(args.output) / "comparativo.csv"
    write_csv(rows, path)
    print(markdown_table(rows, COMPARISON_COLUMNS))
    print(f"\nTabela salva em {path}")
    return 0


def command_simulate_week(args: argparse.Namespace) -> int:
    from .viz_charts import plot_weekly_distance

    output = Path(args.output)
    problem = load_problem(args.instance)
    print(f"Simulando {args.days} dias a partir de {args.start}...", flush=True)
    history = simulate_week(problem, args.start, args.days, args.seed, _ga_config(args))
    path = _write_json(history, output / "historico.json")
    plot_weekly_distance(history, output / "semana_distancia.png")
    print(f"Histórico: {path}")
    return 0


def command_instructions(args: argparse.Namespace) -> int:
    plan = _read_json(args.plan, SOLVE_HINT)
    assistant = _assistant(args)
    vehicles = [args.vehicle] if args.vehicle else [route["vehicle_id"] for route in plan["routes"]]
    for vehicle in vehicles:
        save_path = Path(args.plan).parent / f"instrucoes_{vehicle}.md" if args.save else None
        _show(assistant.driver_instructions(plan, vehicle), save_path)
        print()
    return 0


def command_report(args: argparse.Namespace) -> int:
    assistant = _assistant(args)
    if args.period == "weekly":
        history = _read_json(args.history, WEEK_HINT)
        save_path = Path(args.history).parent / "relatorio_semanal.md" if args.save else None
        _show(assistant.weekly_report(history), save_path)
    else:
        plan = _read_json(args.plan, SOLVE_HINT)
        save_path = Path(args.plan).parent / "relatorio_diario.md" if args.save else None
        _show(assistant.daily_report(plan), save_path)
    return 0


def command_improve(args: argparse.Namespace) -> int:
    history = _read_json(args.history, WEEK_HINT)
    save_path = Path(args.history).parent / "melhorias.md" if args.save else None
    _show(_assistant(args).suggest_improvements(history), save_path)
    return 0


def _optional_history(path: Path) -> Optional[dict]:
    return _read_json(path, WEEK_HINT) if Path(path).exists() else None


def command_ask(args: argparse.Namespace) -> int:
    plan = _read_json(args.plan, SOLVE_HINT)
    _show(_assistant(args).answer(args.question, plan, _optional_history(args.history)))
    return 0


def command_chat(args: argparse.Namespace) -> int:
    plan = _read_json(args.plan, SOLVE_HINT)
    history = _optional_history(args.history)
    assistant = _assistant(args)
    print("Pergunte sobre as rotas e entregas. Para encerrar, digite 'sair'.")
    while True:
        try:
            question = input("\nVocê: ").strip()
        except EOFError:
            return 0
        if question.lower() in EXIT_WORDS:
            return 0
        if question:
            _show(assistant.answer(question, plan, history))


def _confirm_summary(summary: str) -> bool:
    print(f"\n{summary}\n")
    try:
        return input("Estes dados estão corretos? [s/N] ").strip().lower() in {"s", "sim"}
    except EOFError:
        return False


def _intake_session(args: argparse.Namespace, draft_path: Path) -> IntakeSession:
    geocoder = None if args.geocoder == "none" else NominatimGeocoder()
    if args.resume:
        return IntakeSession(geocoder, _read_json(draft_path, "Não há rascunho para continuar."))
    if draft_path.exists():
        raise ValueError(f"Já existe um rascunho em {draft_path}. Use --resume para continuar, ou apague o arquivo.")
    return IntakeSession(geocoder)


def command_intake(args: argparse.Namespace) -> int:
    output = Path(args.output)
    draft_path = output / "rascunho_instancia.json"
    session = _intake_session(args, draft_path)

    client = create_client(args.llm, args.model)
    if client is None:
        raise LLMError("O cadastro assistido precisa de uma LLM. Defina GEMINI_API_KEY. Veja o arquivo .env.example.")

    print(f"Cadastro assistido por {client.label}. Para interromper e salvar o rascunho, digite 'sair'.")
    destinations = "a LLM" if args.geocoder == "none" else "a LLM, e os endereços também para o OpenStreetMap"
    print(f"O que você digitar vai para {destinations}. Nunca informe dados de pacientes.")
    if client.data_notice:
        print(client.data_notice)

    agent = IntakeAgent(
        client,
        session,
        say=lambda text: print(f"\nAssistente: {text}"),
        confirm=_confirm_summary,
        on_change=lambda: _write_json(session.to_draft(), draft_path),
    )
    agent.start()
    while not agent.finished:
        try:
            message = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            message = "sair"
        if message.lower() in EXIT_WORDS:
            print(f"\nRascunho em {draft_path}. Para continuar: python -m medroute intake --resume")
            return 0
        if message:
            agent.reply(message)

    instance_path = _write_json(agent.instance, output / "instancia.json")
    draft_path.unlink(missing_ok=True)
    print(f"\nInstância: {instance_path}")
    if args.no_solve:
        print(f"Para otimizar: python -m medroute solve --instance {instance_path}")
        return 0
    args.instance = str(instance_path)
    return command_solve(args)


def command_llm_models(args: argparse.Namespace) -> int:
    client = create_client(args.llm, args.model)
    if client is None:
        raise LLMError("Nenhuma credencial de LLM encontrada. Veja o arquivo .env.example.")
    print(f"Modelos disponíveis em {client.provider}:")
    for name in client.list_models():
        print(f"- {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m medroute",
        description="Otimização de rotas de medicamentos e insumos com algoritmo genético e LLM.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ga = argparse.ArgumentParser(add_help=False)
    ga.add_argument("--instance", default=str(DEFAULT_INSTANCE), help="arquivo JSON da instância")
    ga.add_argument("--output", default=str(DEFAULT_OUTPUT), help="pasta dos resultados")
    ga.add_argument("--seed", type=int, default=42, help="semente, para reproduzir o resultado")
    ga.add_argument("--population", type=int, default=200, help="tamanho da população")
    ga.add_argument("--generations", type=int, default=1000, help="máximo de gerações")

    llm = argparse.ArgumentParser(add_help=False)
    llm.add_argument(
        "--llm",
        default="auto",
        choices=["auto", "offline", *PROVIDERS],
        help="provedor; 'auto' usa a chave encontrada no ambiente e, sem chave, o modo offline",
    )
    llm.add_argument("--model", default=None, help="substitui o modelo padrão do provedor")

    plan = argparse.ArgumentParser(add_help=False)
    plan.add_argument("--plan", default=str(DEFAULT_PLAN), help="arquivo do plano")

    history = argparse.ArgumentParser(add_help=False)
    history.add_argument("--history", default=str(DEFAULT_HISTORY), help="arquivo do histórico")

    save = argparse.ArgumentParser(add_help=False)
    save.add_argument("--save", action="store_true", help="salva o texto ao lado do arquivo de entrada")

    solve = commands.add_parser("solve", parents=[ga], help="otimiza as rotas e gera o mapa")
    solve.set_defaults(handler=command_solve)

    intake = commands.add_parser(
        "intake", parents=[ga, llm], help="cadastra a operação em uma conversa com a LLM e otimiza as rotas"
    )
    intake.add_argument("--resume", action="store_true", help="continua o rascunho salvo na pasta de resultados")
    intake.add_argument("--no-solve", action="store_true", help="só salva a instância, sem rodar o otimizador")
    intake.add_argument(
        "--geocoder",
        choices=["nominatim", "none"],
        default="nominatim",
        help="busca de endereços; com 'none', só coordenadas são aceitas e nada é enviado ao OpenStreetMap",
    )
    intake.set_defaults(handler=command_intake)

    compare = commands.add_parser("compare", parents=[ga], help="compara o AG com as outras abordagens")
    compare.add_argument("--seeds", type=int, default=10, help="execuções do algoritmo genético")
    compare.set_defaults(handler=command_compare)

    week = commands.add_parser("simulate-week", parents=[ga], help="simula uma semana de operação")
    week.add_argument("--start", default="2026-11-02", help="primeiro dia (AAAA-MM-DD)")
    week.add_argument("--days", type=int, default=5, help="quantidade de dias")
    week.set_defaults(handler=command_simulate_week)

    instructions = commands.add_parser(
        "instructions", parents=[llm, plan, save], help="gera instruções para motoristas e equipes"
    )
    instructions.add_argument("--vehicle", default=None, help="identificador do veículo; sem ele, gera todos")
    instructions.set_defaults(handler=command_instructions)

    report = commands.add_parser(
        "report", parents=[llm, plan, history, save], help="gera o relatório diário ou semanal"
    )
    report.add_argument("--period", choices=["daily", "weekly"], default="daily", help="período do relatório")
    report.set_defaults(handler=command_report)

    improve = commands.add_parser("improve", parents=[llm, history, save], help="sugere melhorias")
    improve.set_defaults(handler=command_improve)

    ask = commands.add_parser("ask", parents=[llm, plan, history], help="responde a uma pergunta")
    ask.add_argument("question", help="pergunta em linguagem natural")
    ask.set_defaults(handler=command_ask)

    chat = commands.add_parser("chat", parents=[llm, plan, history], help="conversa sobre as rotas")
    chat.set_defaults(handler=command_chat)

    models = commands.add_parser("llm-models", parents=[llm], help="lista os modelos do provedor")
    models.set_defaults(handler=command_llm_models)

    return parser


def _use_utf8_output() -> None:
    """Evita erro de codificação ao imprimir acentos no console do Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Executa um comando da interface.

    Parameters:
    - argv: argumentos; sem eles, usa os da linha de comando.

    Returns:
    int: 0 em caso de sucesso e 1 em caso de erro esperado.
    """
    _use_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (LLMError, FileNotFoundError, KeyError, ValueError) as error:
        message = error.args[0] if error.args else str(error)
        print(f"Erro: {message}", file=sys.stderr)
        return 1
