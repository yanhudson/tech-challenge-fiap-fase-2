"""
Conversão de endereços em coordenadas, usada no cadastro assistido.

O cadastro recebe apenas uma função `Geocoder`, de modo que outro serviço pode
substituir o Nominatim sem mudanças no restante do projeto.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# A política de uso do Nominatim exige identificação e no máximo um pedido por segundo.
USER_AGENT = "medroute-tech-challenge/1.0"
MIN_INTERVAL_S = 1.0


class GeocodingError(RuntimeError):
    """O endereço não foi encontrado ou o serviço não respondeu."""


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    label: str  # endereço reconhecido, para o usuário conferir


Geocoder = Callable[[str], GeoResult]


class NominatimGeocoder:
    """Consulta o Nominatim, o serviço de endereços do OpenStreetMap."""

    def __init__(self, opener=urllib.request.urlopen):
        self._opener = opener
        self._last_call = 0.0

    def __call__(self, address: str) -> GeoResult:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

        query = urllib.parse.urlencode({"q": address, "format": "jsonv2", "limit": 1, "countrycodes": "br"})
        request = urllib.request.Request(f"{NOMINATIM_URL}?{query}", headers={"User-Agent": USER_AGENT})
        try:
            with self._opener(request, timeout=20) as response:
                results = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise GeocodingError(f"O serviço de endereços não respondeu: {error}") from error

        if not results:
            raise GeocodingError(f"Endereço não encontrado: {address}")
        best = results[0]
        return GeoResult(float(best["lat"]), float(best["lon"]), best.get("display_name", address))
