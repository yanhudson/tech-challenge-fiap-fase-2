"""
Demonstração completa: otimiza as rotas, simula a semana e aciona o assistente.

Uso:
    python demo.py                 # usa a LLM configurada ou, sem chave, o modo offline
    python demo.py --quick         # orçamento pequeno, para testar a instalação
    python demo.py --llm gemini    # escolhe o provedor
"""

import argparse
import json
import sys
from pathlib import Path

from medroute.cli import DEFAULT_OUTPUT, main as cli_main
from medroute.llm import PROVIDERS

QUESTIONS = (
    "Qual veículo leva a insulina?",
    "Quais entregas têm atraso previsto?",
    "Qual foi a economia da semana?",
    "Quem ganhou a Copa do Mundo de 2002?",
)


def _title(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="roda com população e gerações reduzidas")
    parser.add_argument("--llm", default="auto", choices=["auto", "offline", *PROVIDERS])
    parser.add_argument("--model", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    output = Path(args.output)
    plan_path = output / "plan.json"
    history_path = output / "historico.json"
    budget = ["--population", "60", "--generations", "100"] if args.quick else []
    llm = ["--llm", args.llm] + (["--model", args.model] if args.model else [])
    files = ["--plan", str(plan_path), "--history", str(history_path)]

    def run(title: str, *command: str) -> None:
        _title(title)
        if cli_main(list(command)) != 0:
            raise SystemExit(1)

    run("1. Algoritmo genético: rotas do dia", "solve", "--output", str(output), *budget)
    run("2. Simulação de uma semana", "simulate-week", "--output", str(output), *budget)

    first_vehicle = json.loads(plan_path.read_text(encoding="utf-8"))["routes"][0]["vehicle_id"]
    run(
        f"3. Instruções para o motorista ({first_vehicle})",
        "instructions", "--vehicle", first_vehicle, "--plan", str(plan_path), "--save", *llm,
    )
    run("4. Relatório diário", "report", "--period", "daily", *files, "--save", *llm)
    run("5. Relatório semanal", "report", "--period", "weekly", *files, "--save", *llm)
    run("6. Sugestões de melhoria", "improve", "--history", str(history_path), "--save", *llm)

    for question in QUESTIONS:
        run(f"7. Pergunta: {question}", "ask", question, *files, *llm)

    _title("Fim da demonstração")
    print(f"Abra o mapa no navegador: {output / 'rotas.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
