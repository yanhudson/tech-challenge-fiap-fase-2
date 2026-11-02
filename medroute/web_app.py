"""
Site do projeto, em Streamlit: cadastro assistido, painel de insights e assistente.

Este módulo só cuida da tela. Os números vêm de metrics.py e insights.py, e a LLM só
é chamada quando o usuário pede, para não gastar a cota ao abrir uma página.
"""

import json
from pathlib import Path
from typing import List, Optional

import streamlit as st

from . import web_charts
from .data import DEFAULT_INSTANCE, load_problem, problem_from_dict
from .geocoding import NominatimGeocoder
from .insights import Insight, fleet_rows, plan_insights, slack_rows, week_insights
from .intake import NO_DEADLINE, IntakeSession
from .llm import AssistantOutput, LLMError, RouteAssistant, create_client
from .llm.intake_agent import IntakeAgent
from .metrics import find_patterns, format_number
from .models import PRIORITY_BY_NAME, PRIORITY_LABELS
from .simulation import optimize_plan, simulate_week
from .viz_map import build_route_map

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "docs" / "results"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "web"
DRAFT_PATH = OUTPUT_DIR / "rascunho_instancia.json"
MIN_DELIVERIES_FOR_WEEK = 5
PENDING = "falta"
LEVELS = {
    "critical": ("Crítico", "red", ":material/error:"),
    "warning": ("Atenção", "orange", ":material/warning:"),
    "good": ("Bom resultado", "green", ":material/check_circle:"),
    "info": ("Para avaliar", "gray", ":material/lightbulb:"),
}


def _state():
    return st.session_state


def _client():
    """Cria o cliente uma vez por sessão. Devolve None no modo offline."""
    if "client" not in _state():
        _state().client = create_client("auto")
    return _state().client


def _write_json(data: dict, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_plan(plan: dict, instance: Optional[dict], history: Optional[dict] = None) -> None:
    """Troca o plano em uso e descarta tudo o que foi derivado do plano anterior."""
    _state().plan = plan
    _state().instance = instance
    _state().history = history
    _state().generated = {}
    _state().answers = []
    _state().pop("map_path", None)


def _load_example() -> None:
    plan = json.loads((RESULTS_DIR / "plan.json").read_text(encoding="utf-8"))
    history = json.loads((RESULTS_DIR / "historico.json").read_text(encoding="utf-8"))
    instance = json.loads(Path(DEFAULT_INSTANCE).read_text(encoding="utf-8"))
    _set_plan(plan, instance, history)


def _show_insights(insights: List[Insight], columns: int = 2) -> None:
    if not insights:
        st.success("Nenhum alerta neste plano.", icon=":material/check_circle:")
        return
    grid = st.columns(columns)
    for index, insight in enumerate(insights):
        label, color, icon = LEVELS[insight.level]
        with grid[index % columns].container(border=True):
            st.badge(label, icon=icon, color=color)
            st.markdown(f"**{insight.title}**")
            st.write(insight.detail)
            if insight.action:
                st.caption(f"O que fazer: {insight.action}")


def _map_path(plan: dict) -> Path:
    if "map_path" not in _state() or not _state().map_path.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _state().map_path = build_route_map(plan, OUTPUT_DIR / "rotas.html", legend=False)
    return _state().map_path


def _change(value: float, unit: str = " km", prefix: str = "", decimals: int = 1) -> Optional[str]:
    """Texto da variação de um indicador. O sinal vem primeiro, porque é ele que define a seta."""
    if round(value, decimals) == 0:
        return None
    sign = "-" if value < 0 else ""
    return f"{sign}{prefix}{format_number(abs(value), decimals)}{unit}"


def _chart(column, chart) -> None:
    # Sem o tema do Streamlit, que sobrescreveria as cores e a posição da legenda.
    column.altair_chart(chart, width="stretch", theme=None)


def _need_plan() -> Optional[dict]:
    plan = _state().get("plan")
    if plan is None:
        st.info("Ainda não há um plano. Comece em **Novo planejamento**, cadastrando a operação ou abrindo o exemplo.")
    return plan


def _show_output(output: AssistantOutput, file_name: str) -> None:
    if output.source == "offline":
        st.warning("Texto gerado por template, sem LLM. Configure GEMINI_API_KEY para usar o modelo.")
    else:
        st.caption(f"Gerado por {output.source}. Revise antes de usar.")
    st.markdown(output.text)
    for warning in output.warnings:
        st.warning(warning)
    st.download_button("Baixar texto", output.text, file_name=file_name, key=f"baixar-{file_name}")


# Novo planejamento


def _start_intake(resume: bool) -> None:
    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8")) if resume else None
    _state().intake_session = IntakeSession(NominatimGeocoder(), draft)
    _begin_conversation()


def _begin_conversation() -> None:
    """Abre uma conversa com os dados atuais. Serve também para recomeçar depois de um erro."""
    session = _state().intake_session
    _state().messages = []
    _state().pending_summary = None

    def confirm_on_screen(summary: str) -> None:
        _state().pending_summary = summary

    def save_draft() -> None:
        _write_json(session.to_draft(), DRAFT_PATH.name)

    agent = IntakeAgent(
        _client(),
        session,
        say=lambda text: _state().messages.append(("assistant", text)),
        confirm=confirm_on_screen,
        on_change=save_draft,
    )
    _state().agent = agent
    agent.start()


def _finish_intake() -> None:
    agent = _state().agent
    agent.accept()
    problem = problem_from_dict(agent.instance)
    plan, _ = optimize_plan(problem)
    _write_json(agent.instance, "instancia.json")
    _write_json(plan, "plan.json")
    DRAFT_PATH.unlink(missing_ok=True)
    _set_plan(plan, agent.instance)
    for key in ("agent", "intake_session", "messages", "pending_summary"):
        _state().pop(key, None)


def _filled(value: Optional[float], unit: str) -> str:
    return PENDING if value is None else f"{format_number(value, 0 if float(value).is_integer() else 1)}{unit}"


def _priority_label(name: Optional[str]) -> str:
    return PRIORITY_LABELS[PRIORITY_BY_NAME[name]] if name else PENDING


def _deadline_label(deadline: Optional[str]) -> str:
    if deadline is None:
        return PENDING
    return "sem prazo" if deadline == NO_DEADLINE else deadline


def _session_panel(session: IntakeSession) -> None:
    status = session.status()
    missing = status["pendencias"]
    problems = status["inconsistencias"]
    if missing:
        st.markdown(f"**Falta informar {len(missing)} item(ns)**")
        for item in missing[:8]:
            st.write(f"- {item}")
        if len(missing) > 8:
            st.caption(f"E mais {len(missing) - 8}.")
    elif problems:
        st.markdown("**Dados que precisam de ajuste**")
        for item in problems:
            st.write(f"- {item}")
    else:
        st.success("Dados completos. Se não houver mais entregas, peça para finalizar.", icon=":material/check_circle:")

    st.metric("Veículos", status["veiculos"])
    if session.vehicles:
        st.dataframe(
            [
                {
                    "Veículo": vehicle.get("name", identifier),
                    "Carga": _filled(vehicle.get("capacity_kg"), " kg"),
                    "Autonomia": _filled(vehicle.get("range_km"), " km"),
                    "Frio": {True: "sim", False: "não"}.get(vehicle.get("refrigerated"), PENDING),
                }
                for identifier, vehicle in session.vehicles.items()
            ],
            hide_index=True,
        )
    st.metric("Entregas", status["entregas"])
    if session.deliveries:
        st.dataframe(
            [
                {
                    "Destino": delivery.get("name", identifier),
                    "Peso": _filled(delivery.get("demand_kg"), " kg"),
                    "Prioridade": _priority_label(delivery.get("priority")),
                    "Prazo": _deadline_label(delivery.get("deadline")),
                }
                for identifier, delivery in session.deliveries.items()
            ],
            hide_index=True,
        )


def _intake_view() -> None:
    client = _client()
    st.caption(f"Assistente: {client.label}. O que você digita vai para a LLM, e os endereços, para o OpenStreetMap.")
    if client.data_notice:
        st.warning(client.data_notice, icon=":material/privacy_tip:")

    # Fica antes da resposta da LLM para continuar na tela, travado, durante a espera.
    waiting = "waiting_message" in _state()
    message = st.chat_input(
        "Aguarde a resposta..." if waiting else "Digite os dados da operação...", disabled=waiting
    )
    if message:
        _state().messages.append(("user", message))
        _state().pending_summary = None
        _state().waiting_message = message
        st.rerun()

    chat, panel = st.columns([3, 2], gap="large")
    with panel:
        with st.container(border=True):
            _session_panel(_state().intake_session)

    with chat:
        for role, text in _state().messages:
            with st.chat_message("assistant" if role == "assistant" else "user"):
                st.markdown(text)

        if waiting:
            # A mensagem sai da fila antes da chamada: trocar de página não a envia de novo.
            pending = _state().pop("waiting_message")
            with st.chat_message("assistant"):
                with st.spinner("O assistente está respondendo..."):
                    try:
                        _state().agent.reply(pending)
                    except LLMError as error:
                        _state().messages.append(("assistant", f"Não consegui responder agora. {error}"))
            st.rerun()

        timing = _state().agent.timing
        if timing["llm_calls"]:
            st.caption(
                f"Última resposta: LLM {format_number(timing['llm_s'])} s em {timing['llm_calls']} chamada(s), "
                f"endereços e validação {format_number(timing['tools_s'])} s."
            )

        summary = _state().pending_summary
        if summary:
            with st.container(border=True):
                st.markdown("**Confira os dados antes de otimizar**")
                st.code(summary, language=None, wrap_lines=True)
                confirm, fix = st.columns(2)
                if confirm.button("Confirmar e otimizar", type="primary", width="stretch"):
                    with st.spinner("Otimizando as rotas..."):
                        _finish_intake()
                    st.switch_page(st.session_state.pages["painel"])
                if fix.button("Quero corrigir algo", width="stretch"):
                    _state().pending_summary = None
                    st.rerun()

        if st.button("Recomeçar a conversa, mantendo os dados", help="Use se o assistente falhar ou se perder."):
            with st.spinner("Reabrindo a conversa..."):
                try:
                    _begin_conversation()
                except LLMError as error:
                    st.error(str(error))
            st.rerun()


def page_new_plan() -> None:
    st.title("Novo planejamento")
    if "agent" in _state():
        _intake_view()
        return

    st.write("Informe a operação e receba as rotas otimizadas, com alertas sobre prazos, frota e custos.")
    assistant, example = st.columns(2)
    with assistant.container(border=True):
        st.subheader("Cadastrar com o assistente")
        st.write("Uma conversa que pede tudo o que o transporte exige: frota, limites, entregas, prioridades e prazos.")
        if _client() is None:
            st.warning("Configure GEMINI_API_KEY no arquivo .env para usar o assistente.")
        elif st.button("Começar", type="primary"):
            try:
                with st.spinner("Abrindo a conversa..."):
                    _start_intake(resume=False)
            except LLMError as error:
                st.error(str(error))
            else:
                st.rerun()
        if _client() is not None and DRAFT_PATH.exists() and st.button("Continuar o rascunho salvo"):
            try:
                with st.spinner("Abrindo a conversa..."):
                    _start_intake(resume=True)
            except LLMError as error:
                st.error(str(error))
            else:
                st.rerun()

    with example.container(border=True):
        st.subheader("Ver um exemplo")
        st.write("Abre o plano de demonstração, com 30 entregas fictícias em São Paulo e 5 veículos. Não usa a LLM.")
        if st.button("Abrir o exemplo"):
            _load_example()
            st.switch_page(st.session_state.pages["painel"])


# Painel do dia


def page_dashboard() -> None:
    st.title("Painel do dia")
    plan = _need_plan()
    if plan is None:
        return

    totals = plan["totals"]
    st.caption(f"{plan['instance']} | Saída às {plan['departure']} | {plan['method']}")
    if not totals["feasible"]:
        st.error("Este plano viola limites da operação. Veja os alertas abaixo.", icon=":material/error:")

    tiles = st.columns(5)
    tiles[0].metric("Entregas", totals["deliveries"], border=True)
    tiles[1].metric("Críticas no prazo", f"{format_number(totals['critical_on_time_rate_pct'])}%", border=True)
    tiles[2].metric("Distância", f"{format_number(totals['distance_km'])} km", border=True)
    tiles[3].metric("Custo", f"R$ {format_number(totals['cost_brl'], 0)}", border=True)
    tiles[4].metric("Último retorno", totals["last_return"], border=True)

    st.subheader("O que merece sua atenção")
    _show_insights(plan_insights(plan))

    comparison = plan.get("comparison")
    if comparison:
        st.subheader("Comparação com um despacho simples")
        st.caption("A referência é um despacho simulado, sem otimização. Não é a operação real do hospital.")
        reference = comparison["reference_totals"]
        columns = st.columns(3)
        columns[0].metric(
            "Distância",
            f"{format_number(totals['distance_km'])} km",
            _change(-comparison["distance_km_saved"]),
            delta_color="inverse",
            help=f"Referência: {format_number(reference['distance_km'])} km",
            border=True,
        )
        columns[1].metric(
            "Custo",
            f"R$ {format_number(totals['cost_brl'], 2)}",
            _change(-comparison["cost_brl_saved"], "", "R$ ", 2),
            delta_color="inverse",
            help=f"Referência: R$ {format_number(reference['cost_brl'], 2)}",
            border=True,
        )
        columns[2].metric(
            "Críticas no prazo",
            f"{format_number(totals['critical_on_time_rate_pct'])}%",
            _change(comparison["critical_on_time_gain_points"], " pontos"),
            help=f"Referência: {format_number(reference['critical_on_time_rate_pct'])}%",
            border=True,
        )

    st.subheader("Mapa das rotas")
    st.caption(
        "CD é o centro de distribuição. O número indica a ordem da parada, e o contorno escuro, uma entrega crítica. "
        "Clique em uma parada para ver os detalhes. As linhas ligam as paradas em reta e não seguem as ruas."
    )
    st.iframe(_map_path(plan), height=640)

    rows = fleet_rows(plan)
    st.subheader("Quanto cada veículo usa dos seus limites")
    st.caption("A linha marca 100% do limite. Perto dela, o veículo tem pouca folga.")
    charts = st.columns(3)
    _chart(charts[0], web_charts.limit_use_chart(rows, "capacity_pct", "Carga"))
    _chart(charts[1], web_charts.limit_use_chart(rows, "range_pct", "Autonomia"))
    _chart(charts[2], web_charts.limit_use_chart(rows, "shift_pct", "Jornada"))
    with st.expander("Ver como tabela"):
        st.dataframe(
            [
                {
                    "Veículo": row["vehicle_name"],
                    "Paradas": row["stops"],
                    "Carga (kg)": f"{format_number(row['load_kg'])} de {format_number(row['capacity_kg'])}",
                    "Distância (km)": f"{format_number(row['distance_km'])} de {format_number(row['range_km'])}",
                    "Em rota (min)": format_number(row["duration_min"]),
                    "Custo (R$)": format_number(row["cost_brl"], 2),
                }
                for row in rows
            ],
            hide_index=True,
        )

    slack = slack_rows(plan)
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Entregas com menos folga")
        if slack:
            _chart(st, web_charts.slack_chart(slack))
            with st.expander("Ver todas as entregas com prazo"):
                st.dataframe(
                    [
                        {
                            "Entrega": f"{row['name']} ({row['id']})",
                            "Veículo": row["vehicle_name"],
                            "Prioridade": row["priority"],
                            "Chegada": row["arrival"],
                            "Prazo": row["deadline"],
                            "Folga (min)": row["slack_min"],
                        }
                        for row in slack
                    ],
                    hide_index=True,
                )
        else:
            st.write("Nenhuma entrega tem prazo definido.")
    with right:
        st.subheader("Custo por veículo")
        _chart(st, web_charts.cost_chart(rows))

    st.subheader("Rotas")
    for route in plan["routes"]:
        title = (
            f"{route['vehicle_name']}: {len(route['stops'])} paradas, "
            f"{format_number(route['distance_km'])} km, retorno às {route['return_time']}"
        )
        with st.expander(title):
            st.dataframe(
                [
                    {
                        "Ordem": stop["sequence"],
                        "Destino": f"{stop['name']} ({stop['id']})",
                        "Item": stop["item"],
                        "Peso (kg)": format_number(stop["demand_kg"]),
                        "Prioridade": stop["priority"],
                        "Refrigerado": "sim" if stop["cold_chain"] else "não",
                        "Chegada": stop["arrival"],
                        "Prazo": stop["deadline"] or "sem prazo",
                    }
                    for stop in route["stops"]
                ],
                hide_index=True,
            )
    st.download_button(
        "Baixar o plano (JSON)", json.dumps(plan, ensure_ascii=False, indent=2), file_name="plano.json"
    )


# Semana


def page_week() -> None:
    st.title("Visão da semana")
    plan = _need_plan()
    if plan is None:
        return

    history = _state().get("history")
    if history is None:
        instance = _state().get("instance")
        n_deliveries = len(instance["deliveries"]) if instance else 0
        st.write("Simula cinco dias de operação com a sua frota, para revelar padrões de atraso e de uso.")
        if n_deliveries < MIN_DELIVERIES_FOR_WEEK:
            st.info(f"A simulação precisa de ao menos {MIN_DELIVERIES_FOR_WEEK} entregas cadastradas; este plano tem {n_deliveries}.")
            return
        if st.button("Simular a semana", type="primary"):
            with st.spinner("Otimizando cada dia..."):
                _state().history = simulate_week(problem_from_dict(instance))
            st.rerun()
        return

    patterns = find_patterns(history)
    st.warning(patterns["data_note"], icon=":material/science:")

    totals = patterns["totals"]
    tiles = st.columns(4)
    tiles[0].metric("Entregas", totals["deliveries"], border=True)
    tiles[1].metric(
        "Críticas no prazo", f"{format_number(patterns['service_level']['average_critical_on_time_rate_pct'])}%", border=True
    )
    tiles[2].metric("Distância", f"{format_number(totals['distance_km'])} km", border=True)
    tiles[3].metric("Custo", f"R$ {format_number(totals['cost_brl'], 2)}", border=True)

    st.subheader("O que os dados da semana mostram")
    _show_insights(week_insights(patterns))

    st.subheader("Distância por dia")
    _chart(st, web_charts.week_distance_chart(patterns["daily"]))
    with st.expander("Ver como tabela"):
        st.dataframe(
            [
                {
                    "Data": day["date"],
                    "Dia": day["weekday"],
                    "Entregas": day["deliveries"],
                    "Otimizado (km)": format_number(day["distance_km"]),
                    "Despacho simulado (km)": format_number(day["reference_distance_km"]),
                    "Críticas no prazo (%)": format_number(day["critical_on_time_rate_pct"]),
                }
                for day in patterns["daily"]
            ],
            hide_index=True,
        )

    st.subheader("Uso da frota na semana")
    st.dataframe(
        [
            {
                "Veículo": row["vehicle_name"],
                "Dias em uso": row["days_used"],
                "Carga média (%)": format_number(row["average_capacity_used_pct"]),
                "Autonomia média (%)": format_number(row["average_range_used_pct"]),
            }
            for row in patterns["fleet_usage"]
        ],
        hide_index=True,
    )


# Assistente


def _generate(key: str, label: str, file_name: str, produce) -> None:
    """Gera o texto só quando o usuário pede e guarda o resultado para não repetir a chamada."""
    generated = _state().generated
    if st.button(label, key=f"gerar-{key}", type="primary"):
        try:
            with st.spinner("Gerando..."):
                generated[key] = produce()
        except LLMError as error:
            st.error(str(error))
    if key in generated:
        _show_output(generated[key], file_name)


def page_assistant() -> None:
    st.title("Assistente")
    plan = _need_plan()
    if plan is None:
        return

    assistant = RouteAssistant(_client())
    history = _state().get("history")
    questions, instructions, daily, weekly, improvements = st.tabs(
        ["Perguntas", "Instruções aos motoristas", "Relatório do dia", "Relatório da semana", "Sugestões de melhoria"]
    )

    with questions:
        st.write("Pergunte sobre as rotas e as entregas deste plano.")
        for question, output in _state().answers:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                st.markdown(output.text)
                for warning in output.warnings:
                    st.warning(warning)
        with st.form("pergunta", clear_on_submit=True):
            question = st.text_input("Sua pergunta", placeholder="Qual veículo leva a insulina?")
            if st.form_submit_button("Perguntar") and question.strip():
                try:
                    with st.spinner("Consultando..."):
                        _state().answers.append((question, assistant.answer(question, plan, history)))
                except LLMError as error:
                    st.error(str(error))
                else:
                    st.rerun()

    with instructions:
        vehicles = {route["vehicle_name"]: route["vehicle_id"] for route in plan["routes"]}
        name = st.selectbox("Veículo", list(vehicles))
        identifier = vehicles[name]
        _generate(
            f"instrucoes-{identifier}",
            "Gerar as instruções",
            f"instrucoes_{identifier}.md",
            lambda: assistant.driver_instructions(plan, identifier),
        )

    with daily:
        _generate("diario", "Gerar o relatório do dia", "relatorio_diario.md", lambda: assistant.daily_report(plan))

    with weekly:
        if history is None:
            st.info("Simule a semana na página **Visão da semana** para gerar este relatório.")
        else:
            _generate("semanal", "Gerar o relatório da semana", "relatorio_semanal.md", lambda: assistant.weekly_report(history))

    with improvements:
        if history is None:
            st.info("Simule a semana na página **Visão da semana** para receber sugestões.")
        else:
            _generate("melhorias", "Gerar as sugestões", "melhorias.md", lambda: assistant.suggest_improvements(history))


def main() -> None:
    st.set_page_config(page_title="Rotas hospitalares", page_icon=":material/local_shipping:", layout="wide")
    pages = {
        "novo": st.Page(page_new_plan, title="Novo planejamento", icon=":material/add_circle:", default=True),
        "painel": st.Page(page_dashboard, title="Painel do dia", icon=":material/dashboard:", url_path="painel"),
        "semana": st.Page(page_week, title="Visão da semana", icon=":material/calendar_month:", url_path="semana"),
        "assistente": st.Page(page_assistant, title="Assistente", icon=":material/forum:", url_path="assistente"),
    }
    st.session_state.pages = pages
    try:
        current = st.navigation(list(pages.values()))
        current.run()
    except LLMError as error:
        st.error(str(error))
