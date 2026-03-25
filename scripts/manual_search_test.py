"""
Prueba manual de la lógica de búsqueda (sin depender de que el navegador esté abierto).
Ejecutar desde la raíz del proyecto: python scripts/manual_search_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys

# Raíz del proyecto (padre de scripts/)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

# Misma forma de JSON que API-Ninjas (ej. Cape Lion)
CAPE_LION = {
    "name": "Cape Lion",
    "taxonomy": {
        "kingdom": "Animalia",
        "phylum": "Chordata",
        "class": "Mammalia",
        "order": "Carnivora",
        "family": "Felidae",
        "genus": "Panthera",
        "scientific_name": "Panthera leo melanochaitus",
    },
    "locations": ["Africa"],
    "characteristics": {
        "prey": "Wildebeests, antelopes",
        "habitat": "plains",
        "diet": "Carnivore",
        "common_name": "Cape Lion",
        "location": "South Africa",
    },
}


def test_query_matches_record() -> None:
    from main import _query_matches_record

    cases: list[tuple[str, bool]] = [
        # Nombre común (raíz y characteristics.common_name)
        ("Cape Lion", True),
        ("cape", True),
        ("lion", True),
        # Científico (taxonomy.scientific_name y genus)
        ("Panthera leo", True),
        ("Panthera", True),
        ("melanochaitus", True),
        # Hábitat
        ("plains", True),
        # Locations
        ("Africa", True),
        # Negativo
        ("xyznonexistent999", False),
    ]
    print("--- Prueba unitaria _query_matches_record (JSON Cape Lion) ---")
    for q, expected in cases:
        got = _query_matches_record(q, CAPE_LION)
        status = "OK" if got == expected else "FALLO"
        print(f"  [{status}] query={q!r} -> {got} (esperado {expected})")
        assert got == expected, f"query={q!r} got={got} expected={expected}"
    print("  Todas las aserciones pasaron.\n")


async def test_live_api() -> None:
    import main as app_main

    app_main.NINJAS_API_KEY = os.getenv("NINJAS_API_KEY", "")
    app_main.UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")

    if not app_main.NINJAS_API_KEY:
        print("--- API en vivo: omitida (NINJAS_API_KEY vacía en .env) ---\n")
        return

    print("--- Prueba en vivo GET /animal (Ninjas + Unsplash) ---")
    for term in ("lion", "Panthera leo", "plains"):
        r = await app_main.get_animal(term)
        print(f"  query={term!r}")
        if r.get("search_mode") == "habitat_many":
            res = r.get("results") or []
            print(
                f"    -> habitat_many: {len(res)} especies (ej. primera: {(res[0] or {}).get('name')!r})"
            )
        else:
            ok = bool(r.get("scientific_name"))
            name = r.get("name")
            sci = r.get("scientific_name")
            print(f"    -> ficha_ok={ok} name={name!r} scientific_name={sci!r}")
        err = r.get("ninjas_error")
        if err:
            print(f"    -> ninjas_error={err!r}")
        if r.get("unsplash_error"):
            print(f"    -> unsplash_error={r.get('unsplash_error')!r}")
    print()


def main() -> None:
    test_query_matches_record()
    asyncio.run(test_live_api())
    print("Listo.")


if __name__ == "__main__":
    main()
