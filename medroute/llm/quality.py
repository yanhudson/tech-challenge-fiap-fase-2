"""Validação do texto gerado pela LLM, feita em Python, depois da resposta."""

import re
from typing import List, Set

_NUMBERED_LINE = re.compile(r"^\s*[*_#]*\s*\d+\s*[.)]")
_TIME = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")
_NUMBER = re.compile(r"(?<![\w.,:])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\w:])|(?<![\w.,:])\d+(?:[.,]\d+)?(?![\w:])")
# Inteiros pequenos costumam ser numeração de lista ou contagens simples.
SMALL_INTEGER_LIMIT = 10


def check_stop_order(text: str, route: dict) -> List[str]:
    """
    Confere se o texto cita todas as paradas da rota, na ordem do plano.

    Olha primeiro as linhas numeradas. Se nelas não houver identificadores, olha o
    texto inteiro. Conta apenas a primeira menção de cada parada.

    Parameters:
    - text: texto gerado.
    - route: rota do plano, com as paradas em ordem.

    Returns:
    List[str]: problemas encontrados; lista vazia quando a ordem está correta.
    """
    expected = [stop["id"] for stop in route["stops"]]
    if not expected:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(identifier) for identifier in expected) + r")\b")

    numbered = "\n".join(line for line in text.splitlines() if _NUMBERED_LINE.match(line))
    matches = pattern.findall(numbered) or pattern.findall(text)
    mentioned = list(dict.fromkeys(matches))

    missing = [identifier for identifier in expected if identifier not in mentioned]
    if missing:
        return [f"Paradas ausentes: {', '.join(missing)}."]
    if mentioned != expected:
        return [f"Ordem incorreta. Esperado: {', '.join(expected)}. Recebido: {', '.join(mentioned)}."]
    return []


def _to_number(token: str) -> float:
    if "," in token:
        return float(token.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
        return float(token.replace(".", ""))
    return float(token)


def _collect_facts(value: object, numbers: Set[float], times: Set[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _collect_facts(item, numbers, times)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_facts(item, numbers, times)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        numbers.update({round(float(value), 2), round(float(value), 1), float(round(value))})
    elif isinstance(value, str):
        times.update(_normalize_time(token) for token in _TIME.findall(value))
        numbers.update(_to_number(token) for token in _NUMBER.findall(value))


def _normalize_time(token: str) -> str:
    return token.zfill(5)


def find_unsupported_numbers(text: str, facts: object) -> List[str]:
    """
    Procura números e horários do texto que não aparecem nos dados.

    É uma heurística: um total calculado pela LLM também aparece aqui. Por isso, o
    resultado vira um aviso para o leitor conferir, não um erro.

    Parameters:
    - text: texto gerado.
    - facts: dados enviados à LLM.

    Returns:
    List[str]: números e horários sem correspondência nos dados.
    """
    numbers: Set[float] = set()
    times: Set[str] = set()
    _collect_facts(facts, numbers, times)

    unsupported = []
    for token in dict.fromkeys(_TIME.findall(text)):
        if _normalize_time(token) not in times:
            unsupported.append(token)

    without_times = _TIME.sub(" ", text)
    for token in dict.fromkeys(_NUMBER.findall(without_times)):
        value = _to_number(token)
        if value.is_integer() and value <= SMALL_INTEGER_LIMIT:
            continue
        if not any(abs(value - known) <= 0.051 for known in numbers):
            unsupported.append(token)
    return unsupported
