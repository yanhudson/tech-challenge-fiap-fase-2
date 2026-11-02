"""
Cadastro de uma operação de transporte: estado, validação e pendências.

A LLM conduz a conversa, mas é este módulo que decide o que falta. Nenhum limitador
tem valor padrão: "sem prazo" e "não refrigerado" precisam ser informados, para que
uma omissão não vire uma restrição a menos na otimização.
"""

import re
from typing import Dict, List, Optional

from .data import parse_clock, problem_from_dict
from .geocoding import Geocoder
from .models import PRIORITY_BY_NAME, PRIORITY_LABELS, haversine_km

NO_DEADLINE = "sem_prazo"
DEFAULT_ROAD_FACTOR = 1.35
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# Latitude e longitude escritas como texto, com ponto ou vírgula decimal. O que vier depois, como a cidade, é ignorado.
_TYPED_COORDINATES = re.compile(r"^\s*(-?\d{1,3}[.,]\d+)\s*[,;\s]\s*(-?\d{1,3}[.,]\d+)\s*(?:[,;].*)?$")
_PRIORITY_ALIASES = {"crítica": "critica", "urgente": "critica"}
_KINDS = ("unidade", "domiciliar")


class IntakeError(ValueError):
    """Um dado informado é inválido. A mensagem é devolvida à LLM para ela corrigir."""


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("informe um texto")
    return value.strip()


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("informe um número")
    return float(value)


def _positive(value: object) -> float:
    number = _number(value)
    if number <= 0:
        raise ValueError("informe um valor maior que zero")
    return number


def _not_negative(value: object) -> float:
    number = _number(value)
    if number < 0:
        raise ValueError("informe um valor maior ou igual a zero")
    return number


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("informe verdadeiro ou falso")
    return value


def _clock(value: object) -> str:
    match = _CLOCK.match(_text(value))
    if not match:
        raise ValueError("use o formato HH:MM")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _deadline(value: object) -> str:
    return NO_DEADLINE if value == NO_DEADLINE else _clock(value)


def _priority(value: object) -> str:
    name = _text(value).lower()
    name = _PRIORITY_ALIASES.get(name, name)
    if name not in PRIORITY_BY_NAME:
        raise ValueError(f"use uma destas: {', '.join(PRIORITY_BY_NAME)}")
    return name


def _kind(value: object) -> str:
    kind = _text(value).lower()
    if kind not in _KINDS:
        raise ValueError(f"use uma destas: {', '.join(_KINDS)}")
    return kind


def _shift_hours(value: object) -> float:
    hours = _positive(value)
    if hours > 24:
        raise ValueError("a jornada não pode passar de 24 horas")
    return hours


# campo -> (validação, nome mostrado nas pendências)
OPERATION_FIELDS = {
    "name": (_text, "nome do centro de distribuição"),
    "departure": (_clock, "horário de saída"),
    "shift_hours": (_shift_hours, "duração da jornada (horas)"),
}
VEHICLE_FIELDS = {
    "name": (_text, "nome"),
    "capacity_kg": (_positive, "capacidade de carga (kg)"),
    "range_km": (_positive, "autonomia (km)"),
    "speed_kmh": (_positive, "velocidade média (km/h)"),
    "cost_per_km": (_not_negative, "custo por km (R$)"),
    "refrigerated": (_flag, "se é refrigerado"),
}
DELIVERY_FIELDS = {
    "name": (_text, "nome do destino"),
    "kind": (_kind, "tipo (unidade ou domiciliar)"),
    "item": (_text, "item transportado"),
    "demand_kg": (_positive, "peso (kg)"),
    "priority": (_priority, "prioridade"),
    "deadline": (_deadline, "prazo (HH:MM ou sem_prazo)"),
    "service_min": (_not_negative, "tempo de atendimento (min)"),
    "cold_chain": (_flag, "se exige refrigeração"),
}
LOCATION_LABEL = "localização (endereço ou coordenadas)"


def _number_text(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _coordinates(lat: object, lon: object) -> dict:
    lat, lon = _number(lat), _number(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("coordenadas fora do intervalo válido")
    return {"lat": lat, "lon": lon}


def _coordinates_text(record: dict) -> str:
    return f"{round(record['lat'], 6)}, {round(record['lon'], 6)}"


def _missing_fields(record: dict, fields: dict, needs_location: bool = True) -> List[str]:
    missing = [label for key, (_, label) in fields.items() if key not in record]
    if needs_location and "lat" not in record:
        missing.append(LOCATION_LABEL)
    return missing


class IntakeSession:
    """
    Dados informados até o momento.

    Parameters:
    - geocoder: converte endereços em coordenadas. Sem ele, só coordenadas são aceitas.
    - draft: conteúdo de um rascunho salvo, para continuar um cadastro.
    """

    def __init__(self, geocoder: Optional[Geocoder] = None, draft: Optional[dict] = None):
        self._geocoder = geocoder
        draft = draft or {}
        self.operation: dict = dict(draft.get("operation", {}))
        self.vehicles: Dict[str, dict] = dict(draft.get("vehicles", {}))
        self.deliveries: Dict[str, dict] = dict(draft.get("deliveries", {}))

    def to_draft(self) -> dict:
        return {"operation": self.operation, "vehicles": self.vehicles, "deliveries": self.deliveries}

    def _apply(self, record: dict, arguments: dict, fields: dict, has_location: bool = True) -> dict:
        """Valida tudo antes de gravar, para não deixar um registro pela metade."""
        allowed = set(fields) | ({"address", "lat", "lon"} if has_location else set())
        errors = [f"campo desconhecido: {key}" for key in arguments if key not in allowed]
        updates = {}
        for key, (check, label) in fields.items():
            if arguments.get(key) is None:
                continue
            try:
                updates[key] = check(arguments[key])
            except ValueError as error:
                errors.append(f"{label}: {error}")

        found = {}
        if has_location and not errors:
            try:
                found = self._location(arguments)
            except (ValueError, RuntimeError) as error:
                errors.append(f"{LOCATION_LABEL}: {error}")
        if errors:
            raise IntakeError("; ".join(errors))

        record.update(updates)
        record.update(found)
        return found

    def _location(self, arguments: dict) -> dict:
        lat, lon, address = arguments.get("lat"), arguments.get("lon"), arguments.get("address")
        if lat is not None or lon is not None:
            if lat is None or lon is None:
                raise ValueError("informe latitude e longitude juntas")
            return _coordinates(lat, lon)
        if address is None:
            return {}
        typed = _TYPED_COORDINATES.match(address) if isinstance(address, str) else None
        if typed:
            return _coordinates(*(float(part.replace(",", ".")) for part in typed.groups()))
        if self._geocoder is None:
            raise ValueError("a busca de endereços está desligada; peça latitude e longitude")
        result = self._geocoder(_text(address))
        return {"lat": result.lat, "lon": result.lon, "address": result.label}

    def set_operation(self, arguments: dict) -> dict:
        """Registra os dados gerais. Campos ausentes mantêm o valor atual."""
        arguments = dict(arguments)
        road_factor = arguments.pop("road_factor", None)
        if road_factor is not None and (
            isinstance(road_factor, bool) or not isinstance(road_factor, (int, float)) or road_factor < 1
        ):
            raise IntakeError("fator de correção das ruas: informe um número maior ou igual a 1")
        found = self._apply(self.operation, arguments, OPERATION_FIELDS)
        if road_factor is not None:
            self.operation["road_factor"] = float(road_factor)
        return {"endereco_encontrado": found.get("address")}

    def _upsert(self, collection: Dict[str, dict], prefix: str, width: int, arguments: dict, fields: dict, has_location: bool) -> dict:
        arguments = dict(arguments)
        identifier = arguments.pop("id", None)
        if identifier is not None and identifier not in collection:
            raise IntakeError(f"{identifier} não está cadastrado. Para um novo cadastro, não informe o id.")
        record = dict(collection[identifier]) if identifier else {}
        found = self._apply(record, arguments, fields, has_location)
        if identifier is None:
            number = 1
            while f"{prefix}{number:0{width}d}" in collection:
                number += 1
            identifier = f"{prefix}{number:0{width}d}"
        collection[identifier] = record
        return {"id": identifier, "endereco_encontrado": found.get("address")}

    def upsert_vehicle(self, arguments: dict) -> dict:
        """Cria um veículo ou, com `id`, altera um já cadastrado."""
        return self._upsert(self.vehicles, "V", 1, arguments, VEHICLE_FIELDS, False)

    def upsert_delivery(self, arguments: dict) -> dict:
        """Cria uma entrega ou, com `id`, altera uma já cadastrada."""
        return self._upsert(self.deliveries, "E", 2, arguments, DELIVERY_FIELDS, True)

    def remove(self, identifier: str) -> None:
        for collection in (self.vehicles, self.deliveries):
            if identifier in collection:
                del collection[identifier]
                return
        raise IntakeError(f"{identifier} não está cadastrado.")

    def missing(self) -> List[str]:
        """Lista o que ainda precisa ser informado."""
        items = [f"Operação: {label}" for label in _missing_fields(self.operation, OPERATION_FIELDS)]
        if not self.vehicles:
            items.append("Frota: nenhum veículo cadastrado")
        if not self.deliveries:
            items.append("Entregas: nenhuma entrega cadastrada")
        for identifier, vehicle in self.vehicles.items():
            items.extend(f"Veículo {identifier}: {label}" for label in _missing_fields(vehicle, VEHICLE_FIELDS, False))
        for identifier, delivery in self.deliveries.items():
            items.extend(f"Entrega {identifier}: {label}" for label in _missing_fields(delivery, DELIVERY_FIELDS))
        return items

    def inconsistencies(self) -> List[str]:
        """Aponta dados completos que tornam a operação impossível. Exige `missing()` vazio."""
        if self.missing():
            return []

        problems = []
        operation = self.operation
        departure = parse_clock(operation["departure"])
        factor = operation.get("road_factor", DEFAULT_ROAD_FACTOR)
        depot = (operation["lat"], operation["lon"])
        vehicles = list(self.vehicles.values())
        refrigerated = [vehicle for vehicle in vehicles if vehicle["refrigerated"]]

        for identifier, delivery in self.deliveries.items():
            if delivery["deadline"] != NO_DEADLINE and parse_clock(delivery["deadline"]) <= departure:
                problems.append(f"Entrega {identifier}: o prazo {delivery['deadline']} não é depois da saída {operation['departure']}.")

            compatible = refrigerated if delivery["cold_chain"] else vehicles
            if not compatible:
                problems.append(f"Entrega {identifier}: exige refrigeração, e nenhum veículo é refrigerado.")
                continue
            if not any(delivery["demand_kg"] <= vehicle["capacity_kg"] for vehicle in compatible):
                problems.append(f"Entrega {identifier}: {delivery['demand_kg']:g} kg não cabem em nenhum veículo compatível.")
            round_trip = 2 * factor * haversine_km(depot, (delivery["lat"], delivery["lon"]))
            if not any(round_trip <= vehicle["range_km"] for vehicle in compatible):
                problems.append(f"Entrega {identifier}: ida e volta de {round_trip:.1f} km superam a autonomia dos veículos compatíveis.")

        total = sum(delivery["demand_kg"] for delivery in self.deliveries.values())
        capacity = sum(vehicle["capacity_kg"] for vehicle in vehicles)
        if total > capacity:
            problems.append(f"Carga total de {total:g} kg supera a capacidade da frota, de {capacity:g} kg.")
        cold_total = sum(delivery["demand_kg"] for delivery in self.deliveries.values() if delivery["cold_chain"])
        cold_capacity = sum(vehicle["capacity_kg"] for vehicle in refrigerated)
        if refrigerated and cold_total > cold_capacity:
            problems.append(f"Carga refrigerada de {cold_total:g} kg supera a capacidade refrigerada, de {cold_capacity:g} kg.")
        return problems

    def status(self) -> dict:
        """Situação do cadastro, devolvida à LLM depois de cada alteração."""
        return {
            "veiculos": len(self.vehicles),
            "entregas": len(self.deliveries),
            "pendencias": self.missing(),
            "inconsistencias": self.inconsistencies(),
        }

    def to_instance(self) -> dict:
        """Gera a instância no formato de data/instancia_sao_paulo.json. Os endereços ficam de fora."""
        operation = self.operation
        vehicles = [{"id": identifier, **vehicle} for identifier, vehicle in self.vehicles.items()]
        deliveries = []
        for identifier, delivery in self.deliveries.items():
            entry = {key: value for key, value in delivery.items() if key != "address"}
            if entry["deadline"] == NO_DEADLINE:
                entry["deadline"] = None
            deliveries.append({"id": identifier, **entry})
        return {
            "name": f"Operação cadastrada: {operation['name']}",
            "note": "Instância informada pelo usuário no cadastro assistido.",
            "depot": {"name": operation["name"], "lat": operation["lat"], "lon": operation["lon"]},
            "departure": operation["departure"],
            "shift_hours": operation["shift_hours"],
            "road_factor": operation.get("road_factor", DEFAULT_ROAD_FACTOR),
            "vehicles": vehicles,
            "deliveries": deliveries,
        }

    def build(self) -> dict:
        """Devolve a instância, depois de conferir que o otimizador consegue carregá-la."""
        problems = self.missing() + self.inconsistencies()
        if problems:
            raise IntakeError(" ".join(problems))
        instance = self.to_instance()
        try:
            problem_from_dict(instance)
        except (KeyError, ValueError) as error:
            raise IntakeError(str(error)) from error
        return instance

    def summary(self) -> str:
        """Resumo gerado pelo Python, para o usuário confirmar exatamente o que será usado."""
        operation = self.operation
        lines = [
            f"CD: {operation['name']} ({operation.get('address') or 'coordenadas ' + _coordinates_text(operation)})",
            f"Saída: {operation['departure']} | Jornada: {_number_text(operation['shift_hours'])} h | "
            f"Fator das ruas: {_number_text(operation.get('road_factor', DEFAULT_ROAD_FACTOR))}",
            "",
            f"Veículos ({len(self.vehicles)}):",
        ]
        for identifier, vehicle in self.vehicles.items():
            lines.append(
                f"  {identifier} {vehicle['name']}: {_number_text(vehicle['capacity_kg'])} kg, "
                f"{_number_text(vehicle['range_km'])} km de autonomia, {_number_text(vehicle['speed_kmh'])} km/h, "
                f"R$ {_number_text(vehicle['cost_per_km'])}/km, "
                f"{'refrigerado' if vehicle['refrigerated'] else 'não refrigerado'}"
            )
        lines.extend(["", f"Entregas ({len(self.deliveries)}):"])
        for identifier, delivery in self.deliveries.items():
            deadline = "sem prazo" if delivery["deadline"] == NO_DEADLINE else f"prazo {delivery['deadline']}"
            cold = "refrigerada" if delivery["cold_chain"] else "não refrigerada"
            lines.append(
                f"  {identifier} {delivery['name']} ({delivery['kind']}): {delivery['item']}, {_number_text(delivery['demand_kg'])} kg, "
                f"prioridade {PRIORITY_LABELS[PRIORITY_BY_NAME[delivery['priority']]]}, {deadline}, "
                f"{_number_text(delivery['service_min'])} min, {cold}"
            )
            if delivery.get("address"):
                lines.append(f"      Local reconhecido: {delivery['address']}")
            else:
                lines.append(f"      Coordenadas informadas: {_coordinates_text(delivery)}")
        return "\n".join(lines)
