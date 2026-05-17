import asyncio
import hashlib
import os
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# Carga variables desde `.env` en raíz del proyecto.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
FRONTEND_INDEX_PATH = os.path.join(FRONTEND_DIR, "index.html")
DOTENV_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", ".env"))
load_dotenv(dotenv_path=DOTENV_PATH)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
ORIGEN_PERMITIDO = os.getenv("ORIGEN_PERMITIDO", "http://127.0.0.1:5500")
NINJAS_API_URL = os.getenv("NINJAS_API_URL", "https://api.api-ninjas.com/v1/animals")
UNSPLASH_API_URL = os.getenv("UNSPLASH_API_URL", "https://api.unsplash.com/search/photos")
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

app = FastAPI()

if os.path.isdir(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

# Permite que tu Frontend (futuro) consuma la API sin bloqueos CORS.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in ORIGEN_PERMITIDO.split(",")
    if origin is not None and origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["http://127.0.0.1:5500"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cargadas en el evento de inicio del servidor.
NINJAS_API_KEY: str = ""
UNSPLASH_ACCESS_KEY: str = ""

# --- Persistencia SQLite (SQLAlchemy) ---
# En Railway el volumen debe montarse en /app/data (no en /app/backend: ocultaría el código).
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.getenv("WILDINFO_DATA_DIR", BASE_DIR), "wildinfo2.db"),
)
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# `check_same_thread=False` ayuda con SQLite cuando Uvicorn usa threads.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

BADGE_CATALOG: List[Dict[str, str]] = [
    {"badge_code": "bioma_trofeo", "label": "León Dorado: maestro del bioma"},
    {"badge_code": "aguila_andina", "label": "Águila Andina: vista de explorador"},
    {"badge_code": "tiburon_profundo", "label": "Tiburón de Profundidad: leyenda oceánica"},
    {"badge_code": "zorro_desierto", "label": "Zorro del Desierto: sigilo total"},
    {"badge_code": "jaguar_selva", "label": "Jaguar de Selva: cazador nocturno"},
    {"badge_code": "lobo_alpha", "label": "Lobo Alfa: líder de manada"},
    {"badge_code": "oso_guardian", "label": "Oso Guardián: fuerza de la montaña"},
    {"badge_code": "delfin_inteligente", "label": "Delfín Inteligente: mente marina"},
    {"badge_code": "buho_sabio", "label": "Búho Sabio: estratega de trivia"},
    {"badge_code": "elefante_ancestral", "label": "Elefante Ancestral: memoria de fauna"},
]


class Sighting(Base):
    """Avistamiento guardado en la bitácora (antes FavoriteAnimal)."""

    __tablename__ = "sightings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True, default="guest")
    name = Column(String, nullable=False)
    scientific_name = Column(String, nullable=False)
    image_url = Column(String, nullable=False)
    habitat = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    conservation_status = Column(String, default="", nullable=False)
    fun_fact = Column(String, default="", nullable=False)
    # Copia estructurada de API-Ninjas (JSON en SQLite).
    taxonomy = Column(JSON, nullable=True)
    characteristics = Column(JSON, nullable=True)
    locations_json = Column(JSON, nullable=True)


class UserBadge(Base):
    """Insignias desbloqueadas por usuario."""

    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_code", name="uq_user_badge_code"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    badge_code = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)
    unlocked_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserProfile(Base):
    """Perfil simple de usuario para asociar progreso."""

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False, default="")
    role = Column(String, nullable=False, default="user")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def migrate_sightings_json_columns() -> None:
    """Añade columnas JSON en bases SQLite ya existentes."""
    import sqlite3

    if not os.path.isfile(DATABASE_PATH):
        return
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sightings'"
        )
        if not cur.fetchone():
            return
        cur.execute("PRAGMA table_info(sightings)")
        cols = {row[1] for row in cur.fetchall()}
        for stmt in (
            "ALTER TABLE sightings ADD COLUMN user_id TEXT NOT NULL DEFAULT 'guest'",
            "ALTER TABLE sightings ADD COLUMN taxonomy TEXT",
            "ALTER TABLE sightings ADD COLUMN characteristics TEXT",
            "ALTER TABLE sightings ADD COLUMN locations_json TEXT",
        ):
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            if col not in cols:
                cur.execute(stmt)
                cols.add(col)
        if "user_id" in cols:
            cur.execute("UPDATE sightings SET user_id='guest' WHERE user_id IS NULL OR TRIM(user_id)=''")
        conn.commit()
    finally:
        conn.close()


def migrate_user_profiles_columns() -> None:
    """Añade columnas de autenticación a user_profiles en bases ya existentes."""
    import sqlite3

    if not os.path.isfile(DATABASE_PATH):
        return
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'"
        )
        if not cur.fetchone():
            return
        cur.execute("PRAGMA table_info(user_profiles)")
        cols = {row[1] for row in cur.fetchall()}
        stmts = (
            "ALTER TABLE user_profiles ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE user_profiles ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
        )
        for stmt in stmts:
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            if col not in cols:
                cur.execute(stmt)
                cols.add(col)
        conn.commit()
    finally:
        conn.close()


def migrate_user_cleanup_triggers() -> None:
    """
    Crea triggers SQLite para borrar en cascada datos por usuario.
    Así evitamos registros huérfanos aunque cambie la lógica de API.
    """
    import sqlite3

    if not os.path.isfile(DATABASE_PATH):
        return
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_user_profiles_delete_badges
            AFTER DELETE ON user_profiles
            FOR EACH ROW
            BEGIN
                DELETE FROM user_badges WHERE user_id = OLD.username;
            END;
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_user_profiles_delete_sightings
            AFTER DELETE ON user_profiles
            FOR EACH ROW
            BEGIN
                DELETE FROM sightings WHERE user_id = OLD.username;
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def load_env_on_startup() -> None:
    # Lee el archivo .env en la raíz del proyecto (si existe).
    load_dotenv(dotenv_path=DOTENV_PATH)
    global NINJAS_API_KEY, UNSPLASH_ACCESS_KEY, API_SECRET_KEY
    # Acepta NINJA_API_KEY (requerimiento práctica) y fallback legado NINJAS_API_KEY.
    NINJAS_API_KEY = os.getenv("NINJA_API_KEY", "") or os.getenv("NINJAS_API_KEY", "")
    UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
    API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
    init_db()
    migrate_sightings_json_columns()
    migrate_user_profiles_columns()
    migrate_user_cleanup_triggers()
    _ensure_default_admin()
    _cleanup_orphan_user_data()


@app.get("/")
def root():
    """Entrega la SPA `index.html` en la ruta principal."""
    if not os.path.isfile(FRONTEND_INDEX_PATH):
        raise HTTPException(status_code=404, detail="No se encontró frontend/index.html")
    return FileResponse(FRONTEND_INDEX_PATH, media_type="text/html")


@app.get("/tailwind.css")
def tailwind_css():
    """CSS compilado (mismo origen que la SPA en Railway / uvicorn)."""
    path = os.path.join(FRONTEND_DIR, "tailwind.css")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No se encontró frontend/tailwind.css")
    return FileResponse(path, media_type="text/css")


@app.get("/status")
def status():
    """Endpoint simple de healthcheck para el frontend."""
    return {
        "status": "Servidor Arriba",
        "message": "Bienvenido a la API de WildInfo",
    }


@app.get("/config")
def config_check():
    """Verifica carga de variables de entorno y conexión DB."""
    db_connected = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    return {
        "status": "Running in Staging",
        "port": PORT,
        "db_connected": db_connected,
    }


def _first_if_list(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def _characteristics_dict(ninjas_obj: Dict[str, Any]) -> Dict[str, Any]:
    ch = ninjas_obj.get("characteristics")
    if isinstance(ch, dict):
        return ch
    return {}


def _threats_to_text(threats: Any) -> str:
    if threats is None:
        return ""
    if isinstance(threats, list):
        return " ".join(str(x) for x in threats).lower()
    return str(threats).lower()


def _species_at_risk(characteristics: Dict[str, Any]) -> bool:
    """
    Heurística educativa: usa prevalent_threats y estimated_population_size
    de API-Ninjas para marcar posible riesgo de conservación.
    """
    threats_raw = characteristics.get("prevalent_threats") or characteristics.get(
        "prevalentThreats"
    )
    pop_raw = characteristics.get("estimated_population_size") or characteristics.get(
        "estimatedPopulationSize"
    )

    t = _threats_to_text(threats_raw).strip()
    trivial = {"", "none", "unknown", "n/a", "not listed"}
    if t and t not in trivial:
        risk_tokens = (
            "habitat loss",
            "poaching",
            "hunting",
            "pollution",
            "climate",
            "deforestation",
            "threat",
            "decline",
            "fragmentation",
            "illegal",
        )
        if any(tok in t for tok in risk_tokens) or len(t) > 12:
            return True

    p = str(pop_raw).lower() if pop_raw is not None else ""
    if any(
        x in p
        for x in (
            "critical",
            "critically",
            "endangered",
            "vulnerable",
            "declin",
            "decreas",
            "fewer than",
            "less than",
        )
    ):
        return True

    nums = re.findall(r"\d[\d,]*", p.replace(",", ""))
    for n in nums:
        try:
            if int(n) < 50000:
                return True
        except ValueError:
            continue
    return False


def _conservation_from_characteristics(chars: Dict[str, Any]) -> str:
    for key in (
        "conservation_status",
        "Conservation Status",
        "population_trend",
        "Population Trend",
    ):
        v = chars.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()[:240]
    return ""


def _fun_fact_from_characteristics(chars: Dict[str, Any]) -> str:
    for key in (
        "group_behavior",
        "type_of_food",
        "gestation_period",
        "lifespan",
        "biggest_threat",
    ):
        v = chars.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()[:500]
    return ""


def _locations_blob(ninjas_obj: Dict[str, Any]) -> str:
    loc = ninjas_obj.get("locations")
    parts: List[str] = []
    if isinstance(loc, list):
        parts.extend(str(x) for x in loc)
    elif isinstance(loc, str):
        parts.append(loc)
    elif isinstance(loc, dict):
        parts.extend(str(v) for v in loc.values() if v is not None)
    return " ".join(parts).lower()


def _taxonomy_text_blob(ninjas_obj: Dict[str, Any]) -> str:
    t = ninjas_obj.get("taxonomy")
    if not isinstance(t, dict):
        return ""
    return " ".join(str(v) for v in t.values() if v is not None).lower()


def _characteristics_habitat_blob(ninjas_obj: Dict[str, Any]) -> str:
    ch = ninjas_obj.get("characteristics")
    if not isinstance(ch, dict):
        return ""
    parts: List[str] = []
    for k, v in ch.items():
        if v is None:
            continue
        kl = str(k).lower()
        if "habitat" in kl or kl in ("location", "locations", "region", "regions"):
            parts.append(str(v))
    return " ".join(parts).lower()


def _characteristics_values_blob(ninjas_obj: Dict[str, Any]) -> str:
    ch = ninjas_obj.get("characteristics")
    if not isinstance(ch, dict):
        return ""
    return " ".join(str(v) for v in ch.values() if v is not None).lower()


def _top_level_scientific_name(ninjas_obj: Dict[str, Any]) -> str:
    return str(
        ninjas_obj.get("scientific_name")
        or ninjas_obj.get("scientificName")
        or ninjas_obj.get("latin_name")
        or ninjas_obj.get("latinName")
        or ""
    ).lower()


def _taxonomy_scientific_name(ninjas_obj: Dict[str, Any]) -> str:
    tax = ninjas_obj.get("taxonomy")
    if not isinstance(tax, dict):
        return ""
    return str(
        tax.get("scientific_name") or tax.get("scientificName") or ""
    ).lower()


def _query_matches_record(query: str, ninjas_obj: Dict[str, Any]) -> bool:
    """
    Comprueba coincidencia del término de búsqueda con la ficha API-Ninjas.

    Rutas típicas del JSON (como en la API real):
    - Nombre común: ``name`` (raíz) y ``characteristics.common_name``
    - Nombre científico: raíz ``scientific_name`` si existe, y siempre
      ``taxonomy.scientific_name`` (p. ej. ``Panthera leo melanochaitus``)
    - Hábitat: ``characteristics.habitat`` (p. ej. ``plains``)
    """
    q = query.strip().lower()
    if not q:
        return True

    # --- Nombre común (raíz) ---
    name = str(ninjas_obj.get("name") or "").lower()
    if q in name:
        return True

    # --- Nombre científico en raíz (si la API lo envía duplicado) ---
    sci_top = _top_level_scientific_name(ninjas_obj)
    if sci_top and q in sci_top:
        return True

    # --- Taxonomía: scientific_name, genus, etc. (incl. búsqueda "Panthera") ---
    tax = ninjas_obj.get("taxonomy")
    if isinstance(tax, dict):
        t_sci = _taxonomy_scientific_name(ninjas_obj)
        if t_sci and q in t_sci:
            return True
        for v in tax.values():
            if v is not None and q in str(v).lower():
                return True

    if q in _taxonomy_text_blob(ninjas_obj):
        return True

    # --- characteristics: common_name, habitat, scientific_name (anidados) ---
    ch = ninjas_obj.get("characteristics")
    if isinstance(ch, dict):
        cn = str(ch.get("common_name") or ch.get("Common Name") or "").lower()
        if cn and q in cn:
            return True
        hab = str(ch.get("habitat") or ch.get("Habitat") or "").lower()
        if hab and q in hab:
            return True
        sci_ch = str(ch.get("scientific_name") or ch.get("scientificName") or "").lower()
        if sci_ch and q in sci_ch:
            return True

    if q in _locations_blob(ninjas_obj):
        return True

    if q in _characteristics_habitat_blob(ninjas_obj):
        return True

    # Coincidencia en el resto de valores de characteristics (p. ej. texto largo);
    # evita términos de 1–2 letras por ruido.
    if len(q) >= 3 and q in _characteristics_values_blob(ninjas_obj):
        return True

    # Búsqueda binomial: cada término debe aparecer como palabra completa (evita
    # que "leo" coincida dentro de "leopard").
    tokens = [t for t in q.split() if len(t) >= 2]
    if len(tokens) >= 2:
        blob = " ".join(
            [
                str(ninjas_obj.get("name") or ""),
                _top_level_scientific_name(ninjas_obj),
                _taxonomy_scientific_name(ninjas_obj),
                _taxonomy_text_blob(ninjas_obj),
            ]
        ).lower()
        ch2 = ninjas_obj.get("characteristics")
        if isinstance(ch2, dict):
            blob += " " + str(ch2.get("common_name") or "").lower()
        words = set(re.findall(r"[a-z]+", blob))
        if all(tok in words for tok in tokens):
            return True

    return False


def _single_search_match_score(query: str, rec: Dict[str, Any]) -> int:
    """
    Puntuación de relevancia para elegir una ficha entre varias devueltas por Ninjas
    (solo `name=` en la API; el científico se compara en cliente).
    """
    q = query.strip().lower()
    if not q:
        return 0
    score = 0
    name = str(rec.get("name") or "").strip().lower()
    cn = ""
    ch = rec.get("characteristics")
    if isinstance(ch, dict):
        cn = str(ch.get("common_name") or "").strip().lower()
    sci = (
        _taxonomy_scientific_name(rec) or _top_level_scientific_name(rec) or ""
    ).strip().lower()

    for dn in (x for x in (name, cn) if x):
        if dn == q:
            score = max(score, 1000)
        elif dn.startswith(q + " "):
            score = max(score, 880)
        elif (" " + q + " ") in dn or dn.endswith(" " + q):
            score = max(score, 840)
        elif q in dn:
            score = max(score, 650 - min(200, abs(len(dn) - len(q)) * 2))

    if sci:
        if sci == q:
            score = max(score, 990)
        elif q in sci:
            score = max(score, 820)
        q_tokens = [t for t in q.split() if len(t) >= 2]
        if len(q_tokens) >= 2:
            sci_words = set(re.findall(r"[a-z]+", sci))
            if all(tok in sci_words for tok in q_tokens):
                score = max(score, 860)

    tax = rec.get("taxonomy")
    if isinstance(tax, dict):
        genus = str(tax.get("genus") or "").strip().lower()
        if genus and len(q.split()) == 1 and len(q) >= 3:
            if genus == q:
                score = max(score, 720)
            elif q in genus:
                score = max(score, 450)

    if score < 120 and _query_matches_record(query, rec):
        score = 120
    return score


def _pick_best_matching_record(
    query: str, merged: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    matches = [r for r in merged if _query_matches_record(query, r)]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    scored: List[tuple[int, int, str, Dict[str, Any]]] = []
    for r in matches:
        s = _single_search_match_score(query, r)
        nm = str(r.get("name") or "").lower()
        scored.append((s, len(nm), nm, r))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return scored[0][3]


def _ninjas_response_to_records(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _record_dedupe_key(rec: Dict[str, Any]) -> str:
    """Clave estable: prioriza nombre científico (raíz o taxonomy.scientific_name)."""
    s = str(
        rec.get("scientific_name")
        or rec.get("scientificName")
        or rec.get("latin_name")
        or ""
    ).strip().lower()
    if not s:
        s = _taxonomy_scientific_name(rec)
    if not s:
        s = str(rec.get("name") or "").strip().lower()
    return s or str(id(rec))


def _unique_ordered_strings(candidates: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for s in candidates:
        if not s:
            continue
        t = s.strip()
        if len(t) < 1:
            continue
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


# Términos alternativos para la API (name=...) cuando el usuario busca un hábitat
# y la primera petición devuelve lista vacía.
HABITAT_NAME_QUERY_HINTS: Dict[str, List[str]] = {
    "plains": ["prairie", "grassland", "bison", "horse"],
    "grassland": ["prairie", "bison"],
    "prairie": ["grassland", "bison"],
    "savanna": ["lion", "zebra", "giraffe"],
    "savannah": ["lion", "zebra"],
    "forest": ["bear", "deer", "wolf"],
    "ocean": ["shark", "whale", "dolphin"],
    "desert": ["camel", "lizard"],
}

# API Ninjas: máx. 10 especies por petición `name=`. Para acercarnos a “todas” las
# de un hábitat, lanzamos muchas búsquedas por nombre y filtramos por `habitat`.
MAX_HABITAT_API_ATTEMPTS = 56
MAX_HABITAT_RESULTS = 100

_PLAINS_GRASS: List[str] = [
    "zebra",
    "antelope",
    "wildebeest",
    "gazelle",
    "cheetah",
    "hyena",
    "bison",
    "buffalo",
    "elk",
    "deer",
    "horse",
    "rabbit",
    "coyote",
    "fox",
    "badger",
    "prairie dog",
    "meerkat",
    "mongoose",
    "gnu",
    "oryx",
    "kudu",
    "jackal",
    "giraffe",
    "rhinoceros",
    "ostrich",
    "emu",
    "eagle",
    "vulture",
    "lion",
    "leopard",
    "serval",
    "caracal",
    "groundhog",
    "snake",
]

_FOREST: List[str] = [
    "bear",
    "deer",
    "wolf",
    "tiger",
    "gorilla",
    "orangutan",
    "chimpanzee",
    "jaguar",
    "tapir",
    "sloth",
    "monkey",
    "lemur",
    "owl",
    "woodpecker",
    "squirrel",
    "raccoon",
    "lynx",
    "bobcat",
    "marten",
    "bat",
    "python",
    "boa",
    "frog",
    "newt",
]

_OCEAN: List[str] = [
    "shark",
    "whale",
    "dolphin",
    "octopus",
    "seal",
    "turtle",
    "crab",
    "ray",
    "jellyfish",
    "squid",
    "eel",
    "lobster",
    "shrimp",
    "walrus",
    "manatee",
    "narwhal",
    "fish",
    "coral",
    "starfish",
    "seahorse",
    "orca",
]

_DESERT: List[str] = [
    "camel",
    "lizard",
    "scorpion",
    "snake",
    "meerkat",
    "fox",
    "tortoise",
    "antelope",
    "jackrabbit",
    "armadillo",
    "vulture",
    "owl",
    "dingo",
]

_TUNDRA: List[str] = [
    "reindeer",
    "caribou",
    "arctic fox",
    "polar bear",
    "musk ox",
    "wolf",
    "snowy owl",
    "lemming",
    "hare",
    "walrus",
    "seal",
    "ptarmigan",
    "yak",
    "penguin",
]

_JUNGLE: List[str] = [
    "jaguar",
    "toucan",
    "parrot",
    "anaconda",
    "capybara",
    "peccary",
    "gorilla",
    "orangutan",
    "macaw",
    "chimpanzee",
    "tiger",
    "elephant",
    "okapi",
    "tapir",
    "sloth",
    "frog",
]

_MOUNTAIN: List[str] = [
    "goat",
    "sheep",
    "ibex",
    "mountain lion",
    "cougar",
    "bear",
    "yak",
    "marmot",
    "eagle",
    "vulture",
    "snow leopard",
    "puma",
    "elk",
    "deer",
]

_RIVER_LAKE: List[str] = [
    "beaver",
    "otter",
    "duck",
    "frog",
    "crocodile",
    "alligator",
    "hippo",
    "salmon",
    "trout",
    "piranha",
    "turtle",
    "swan",
    "muskrat",
]

_WETLAND: List[str] = [
    "heron",
    "crane",
    "flamingo",
    "alligator",
    "crocodile",
    "frog",
    "newt",
    "salamander",
    "duck",
    "goose",
    "swan",
    "otter",
    "boa",
    "python",
]

_URBAN: List[str] = [
    "pigeon",
    "rat",
    "cat",
    "dog",
    "raccoon",
    "fox",
    "bat",
    "crow",
    "sparrow",
    "coyote",
    "squirrel",
    "mouse",
    "owl",
]

_CAVE: List[str] = [
    "bat",
    "bear",
    "salamander",
    "fish",
    "cricket",
    "spider",
    "snake",
    "frog",
]

_REEF: List[str] = [
    "shark",
    "ray",
    "eel",
    "fish",
    "coral",
    "octopus",
    "turtle",
    "lobster",
    "shrimp",
    "clownfish",
]

# Sinónimos habituales en `characteristics.habitat` de API-Ninjas (texto libre).
HABITAT_SYNONYM_GROUPS: List[frozenset] = [
    frozenset(
        {
            "plains",
            "plain",
            "grassland",
            "grasslands",
            "prairie",
            "meadow",
            "steppe",
            "open plains",
        }
    ),
    frozenset({"savanna", "savannah", "veldt"}),
    frozenset({"forest", "woodland", "woods", "woodlands"}),
    frozenset({"jungle", "rainforest", "tropical forest"}),
    frozenset({"ocean", "sea", "marine", "saltwater", "pelagic"}),
    frozenset({"desert", "arid"}),
    frozenset({"tundra", "arctic", "polar", "ice", "sub-arctic", "subarctic"}),
    frozenset({"wetland", "wetlands", "marsh", "swamp", "bog", "fen"}),
    frozenset({"mountain", "alpine", "highland", "mountains"}),
    frozenset({"river", "stream", "lake", "freshwater", "rivers", "lakes"}),
    frozenset({"coastal", "shore", "intertidal", "mudflat", "estuary"}),
    frozenset({"reef", "coral reef", "coral"}),
    frozenset({"urban", "city"}),
    frozenset({"cave", "cavern"}),
]

HABITAT_WIDE_SEEDS: Dict[str, List[str]] = {
    "plains": _PLAINS_GRASS,
    "plain": _PLAINS_GRASS,
    "grassland": _PLAINS_GRASS,
    "grasslands": _PLAINS_GRASS,
    "prairie": _PLAINS_GRASS,
    "meadow": _PLAINS_GRASS,
    "steppe": _PLAINS_GRASS,
    "savanna": _PLAINS_GRASS + ["elephant"],
    "savannah": _PLAINS_GRASS + ["elephant"],
    "veldt": _PLAINS_GRASS,
    "open plains": _PLAINS_GRASS,
    "forest": _FOREST,
    "woodland": _FOREST,
    "woods": _FOREST,
    "woodlands": _FOREST,
    "jungle": _JUNGLE,
    "rainforest": _JUNGLE,
    "tropical forest": _JUNGLE,
    "ocean": _OCEAN,
    "sea": _OCEAN,
    "marine": _OCEAN,
    "saltwater": _OCEAN,
    "pelagic": _OCEAN,
    "desert": _DESERT,
    "arid": _DESERT,
    "tundra": _TUNDRA,
    "arctic": _TUNDRA,
    "polar": _TUNDRA,
    "ice": _TUNDRA,
    "sub-arctic": _TUNDRA,
    "subarctic": _TUNDRA,
    "wetland": _WETLAND,
    "wetlands": _WETLAND,
    "marsh": _WETLAND,
    "swamp": _WETLAND,
    "bog": _WETLAND,
    "fen": _WETLAND,
    "mountain": _MOUNTAIN,
    "alpine": _MOUNTAIN,
    "highland": _MOUNTAIN,
    "mountains": _MOUNTAIN,
    "river": _RIVER_LAKE,
    "rivers": _RIVER_LAKE,
    "stream": _RIVER_LAKE,
    "lake": _RIVER_LAKE,
    "lakes": _RIVER_LAKE,
    "freshwater": _RIVER_LAKE,
    "coastal": _OCEAN + ["seagull", "pelican", "crab"],
    "shore": _OCEAN + ["seagull", "pelican", "crab"],
    "intertidal": _OCEAN + ["crab", "snail"],
    "mudflat": _WETLAND + ["crab", "shorebird"],
    "estuary": _RIVER_LAKE + _WETLAND,
    "reef": _REEF,
    "coral reef": _REEF,
    "coral": _REEF,
    "urban": _URBAN,
    "city": _URBAN,
    "cave": _CAVE,
    "cavern": _CAVE,
}


def _habitat_focused_text_blob(rec: Dict[str, Any]) -> str:
    """Texto donde suele aparecer el hábitat en API-Ninjas (sin ruido de otros campos)."""
    ch = rec.get("characteristics")
    if not isinstance(ch, dict):
        return ""
    parts: List[str] = []
    for k, v in ch.items():
        if v is None:
            continue
        kl = str(k).lower()
        if "habitat" in kl or kl in ("lifestyle",):
            parts.append(str(v))
        elif kl in ("location", "origin", "group"):
            parts.append(str(v))
    return " ".join(parts).lower()


def _term_matches_in_habitat_blob(term: str, blob: str) -> bool:
    if not term or not blob:
        return False
    t = term.strip().lower()
    if len(t) < 2:
        return False
    if len(t) <= 3:
        return bool(re.search(rf"\b{re.escape(t)}\b", blob))
    return t in blob


def _habitat_expanded_terms(query: str) -> set:
    ql = query.strip().lower()
    terms: set[str] = set()
    if len(ql) >= 2:
        terms.add(ql)
    for group in HABITAT_SYNONYM_GROUPS:
        if ql in group:
            for g in group:
                gs = str(g).strip().lower()
                if len(gs) >= 2:
                    terms.add(gs)
    return terms


def _record_matches_habitat_listing(query: str, rec: Dict[str, Any]) -> bool:
    """
    True si el hábitat declarado en la ficha coincide con la consulta o sus sinónimos.
    Evita listar especies que solo coincidían por nombre o por texto irrelevante.
    """
    blob = _habitat_focused_text_blob(rec)
    if not blob.strip():
        return False
    for term in _habitat_expanded_terms(query):
        if _term_matches_in_habitat_blob(term, blob):
            return True
    return False


def _is_habitat_multi_query(q: str) -> bool:
    ql = q.strip().lower()
    if not ql:
        return False
    if ql in HABITAT_NAME_QUERY_HINTS:
        return True
    if ql in HABITAT_WIDE_SEEDS:
        return True
    for group in HABITAT_SYNONYM_GROUPS:
        if ql in group:
            return True
    return False


def _build_habitat_collection_attempts(user_query: str) -> List[str]:
    q = user_query.strip()
    ql = q.lower()
    parts = _build_ninjas_name_attempts(user_query)
    extra: List[str] = []
    for key in (ql,):
        extra.extend(HABITAT_WIDE_SEEDS.get(key, []))
    for group in HABITAT_SYNONYM_GROUPS:
        if ql in group:
            for syn in group:
                sk = str(syn).strip().lower()
                extra.extend(HABITAT_WIDE_SEEDS.get(sk, []))
            break
    merged = _unique_ordered_strings(parts + extra)
    return merged[:MAX_HABITAT_API_ATTEMPTS]


def _ninjas_record_to_payload(
    rec: Dict[str, Any], image_url: Optional[str] = None
) -> Dict[str, Any]:
    """Construye un objeto de ficha (sin llamadas externas) para JSON."""
    ch = rec.get("characteristics")
    name_from_chars = ""
    if isinstance(ch, dict):
        name_from_chars = str(ch.get("common_name") or "").strip()
    display_name = str(rec.get("name") or name_from_chars or "")
    tax = rec.get("taxonomy")
    sci_from_tax = ""
    if isinstance(tax, dict):
        sci_from_tax = str(
            tax.get("scientific_name") or tax.get("scientificName") or ""
        ).strip()
    scientific_name = (
        rec.get("scientific_name")
        or rec.get("scientificName")
        or rec.get("latin_name")
        or rec.get("latinName")
        or sci_from_tax
        or rec.get("name")
    )
    raw_ch = rec.get("characteristics")
    chars = _characteristics_dict(rec)
    cs = _conservation_from_characteristics(chars)
    ff = _fun_fact_from_characteristics(chars)
    return {
        "name": display_name,
        "scientific_name": scientific_name,
        "taxonomy": rec.get("taxonomy"),
        "locations": rec.get("locations"),
        "characteristics": raw_ch if isinstance(raw_ch, dict) else None,
        "image_url": image_url,
        "at_risk": _species_at_risk(chars),
        "conservation_status": cs or None,
        "fun_fact": ff or None,
    }


def _scientific_query_api_hints(user_query: str) -> List[str]:
    """
    API Ninjas a veces no devuelve subespecies si se busca el binomio completo.
    Añade nombres comunes típicos para ampliar resultados y luego filtrar.
    """
    ql = user_query.strip().lower()
    hints: List[str] = []
    if "panthera" in ql and "leo" in ql:
        hints.extend(["lion", "african lion"])
    if "panthera" in ql and "tigris" in ql:
        hints.append("tiger")
    if "homo" in ql and "sapiens" in ql:
        hints.append("human")
    return hints


# La API solo acepta `name=` en inglés (coincidencia parcial). Mapa español → inglés
# para búsquedas comunes sin servicio de traducción externo.
SPANISH_TO_ENGLISH_ANIMAL: Dict[str, str] = {
    "león": "lion",
    "leon": "lion",
    "leona": "lion",
    "tigre": "tiger",
    "oso": "bear",
    "lobo": "wolf",
    "zorro": "fox",
    "elefante": "elephant",
    "rinoceronte": "rhinoceros",
    "jirafa": "giraffe",
    "cebra": "zebra",
    "hipopótamo": "hippopotamus",
    "hipopotamo": "hippopotamus",
    "jaguar": "jaguar",
    "guepardo": "cheetah",
    "chita": "cheetah",
    "puma": "cougar",
    "mono": "monkey",
    "chimpancé": "chimpanzee",
    "chimpance": "chimpanzee",
    "gorila": "gorilla",
    "orangután": "orangutan",
    "orangutan": "orangutan",
    "delfín": "dolphin",
    "delfin": "dolphin",
    "ballena": "whale",
    "tiburón": "shark",
    "tiburon": "shark",
    "águila": "eagle",
    "aguila": "eagle",
    "búho": "owl",
    "buho": "owl",
    "pingüino": "penguin",
    "pinguino": "penguin",
    "canguro": "kangaroo",
    "koala": "koala",
    "serpiente": "snake",
    "cocodrilo": "crocodile",
    "caimán": "alligator",
    "caiman": "alligator",
    "lagarto": "lizard",
    "rana": "frog",
    "murciélago": "bat",
    "murcielago": "bat",
    "venado": "deer",
    "ciervo": "deer",
    "carnero": "sheep",
    "oveja": "sheep",
    "cerdo": "pig",
    "vaca": "cow",
    "toro": "bull",
    "caballo": "horse",
    "burro": "donkey",
    "perro": "dog",
    "gato": "cat",
    "conejo": "rabbit",
    "ardilla": "squirrel",
    "castor": "beaver",
    "nutria": "otter",
    "pato": "duck",
    "ganso": "goose",
    "cisne": "swan",
    "flamenco": "flamingo",
    "halcón": "falcon",
    "halcon": "falcon",
    "búfalo": "buffalo",
    "bufalo": "buffalo",
    "bisonte": "bison",
    "camello": "camel",
    "hiena": "hyena",
    "comadreja": "weasel",
    "mapache": "raccoon",
    "perezoso": "sloth",
    "armadillo": "armadillo",
    "tortuga": "turtle",
    "pulpo": "octopus",
    "calamar": "squid",
    "medusa": "jellyfish",
    "foca": "seal",
    "morsa": "walrus",
    "orca": "orca",
    "hombre": "human",
    "humano": "human",
}


def _spanish_animal_search_aliases(user_query: str) -> List[str]:
    ql = user_query.strip().lower()
    if not ql:
        return []
    en = SPANISH_TO_ENGLISH_ANIMAL.get(ql)
    return [en] if en else []


def _build_ninjas_name_attempts(user_query: str) -> List[str]:
    q = user_query.strip()
    if not q:
        return []
    from_es = _spanish_animal_search_aliases(q)
    parts = q.split()
    candidates = from_es + [q]
    if len(parts) > 1:
        candidates.append(parts[0])
        if parts[-1].lower() != parts[0].lower():
            candidates.append(parts[-1])
    base = _unique_ordered_strings(candidates)
    extra = HABITAT_NAME_QUERY_HINTS.get(q.lower(), [])
    sci = _scientific_query_api_hints(q)
    return _unique_ordered_strings(base + extra + sci)


async def _fetch_ninjas_by_name(
    client: httpx.AsyncClient, name_param: str
) -> tuple[Optional[str], Any]:
    """Llama a API Ninjas con ?name=... Devuelve (error, json o None)."""
    if not NINJAS_API_KEY:
        return "Falta configurar 'NINJA_API_KEY' en el archivo .env.", None
    url = NINJAS_API_URL
    headers = {"X-Api-Key": NINJAS_API_KEY}
    params = {"name": name_param}
    try:
        resp = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        return f"Error de conexión llamando a API Ninjas: {exc}", None

    if resp.status_code != 200:
        return f"API Ninjas devolvió status {resp.status_code}.", None

    try:
        return None, resp.json()
    except ValueError:
        return "API Ninjas devolvió una respuesta que no es JSON.", None


async def _unsplash_search_first_url(
    client: httpx.AsyncClient, query: str
) -> Optional[str]:
    """Devuelve URL de la primera foto de Unsplash o None."""
    if not UNSPLASH_ACCESS_KEY:
        return None
    q = query.strip()
    if not q:
        return None
    url = UNSPLASH_API_URL
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": q, "per_page": 1}
    try:
        resp = await client.get(url, params=params, headers=headers)
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list) and results:
        first = results[0] if isinstance(results[0], dict) else {}
        urls = first.get("urls", {}) if isinstance(first, dict) else {}
        if isinstance(urls, dict):
            return urls.get("regular") or urls.get("raw")
    return None


HABITAT_UNSPLASH_CAP = 22


async def _collect_merged_ninjas_records(
    client: httpx.AsyncClient,
    user_query: str,
    *,
    habitat_wide: bool = False,
) -> tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Ejecuta intentos de nombre y fusiona registros únicos.
    Con ``habitat_wide=True`` usa muchas semillas y peticiones en lotes (API Ninjas
    devuelve máx. 10 resultados por llamada).
    """
    if habitat_wide:
        attempts = _build_habitat_collection_attempts(user_query)
    else:
        attempts = _build_ninjas_name_attempts(user_query)
    if not attempts:
        return "Consulta vacía.", []

    merged: List[Dict[str, Any]] = []
    seen_keys: set = set()
    last_error: Optional[str] = None
    batch_size = 10

    for i in range(0, len(attempts), batch_size):
        chunk = attempts[i : i + batch_size]
        batch_out = await asyncio.gather(
            *[_fetch_ninjas_by_name(client, a) for a in chunk]
        )
        for err, raw in batch_out:
            if err:
                last_error = err
                continue
            for rec in _ninjas_response_to_records(raw):
                key = _record_dedupe_key(rec)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(rec)

    if not merged and last_error:
        return last_error, []
    return None, merged


async def _resolve_ninjas_record(
    client: httpx.AsyncClient, user_query: str
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Varias peticiones ``name=`` (único parámetro documentado; admite coincidencia parcial
    en nombre común), fusiona hasta 10 resultados por llamada y elige la mejor ficha
    según nombre común, nombre científico y taxonomía.
    """
    attempts = _build_ninjas_name_attempts(user_query)
    if not attempts:
        return "Consulta vacía.", None

    merged: List[Dict[str, Any]] = []
    seen_keys: set = set()
    last_error: Optional[str] = None
    batch_size = 10

    for i in range(0, len(attempts), batch_size):
        chunk = attempts[i : i + batch_size]
        batch_out = await asyncio.gather(
            *[_fetch_ninjas_by_name(client, a) for a in chunk]
        )
        for err, raw in batch_out:
            if err:
                last_error = err
                continue
            for rec in _ninjas_response_to_records(raw):
                key = _record_dedupe_key(rec)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(rec)

    best = _pick_best_matching_record(user_query, merged)
    if best is not None:
        return None, best
    if merged:
        return (
            "Sin coincidencias para nombre común, nombre científico o hábitat indicados.",
            None,
        )
    if last_error:
        return last_error, None
    return "No se encontraron resultados en API Ninjas para la búsqueda.", None


@app.get("/animal/{name}")
async def get_animal(name: str):
    """Busca animales en APIs externas (Ninjas + Unsplash) y combina la respuesta."""
    animal_name = name.strip()
    response: Dict[str, Any] = {
        "name": animal_name,
        "scientific_name": None,
        "taxonomy": None,
        "locations": None,
        "characteristics": None,
        "image_url": None,
        "at_risk": False,
        "conservation_status": None,
        "fun_fact": None,
        "data_locale": "en",
        "locale_note": (
            "Para mejores resultados, conviene buscar en inglés (idioma de la API). "
            "Algunos nombres en español funcionan por sugerencias. "
            "La interfaz muestra en español etiquetas y muchos términos cortos; los textos largos pueden seguir en inglés."
        ),
    }

    if not animal_name:
        response["error"] = "El parámetro 'name' no puede estar vacío."
        return response

    if not NINJAS_API_KEY and not UNSPLASH_ACCESS_KEY:
        response["error"] = (
            "Faltan credenciales. Completa 'NINJA_API_KEY' y 'UNSPLASH_ACCESS_KEY' en el archivo .env."
        )
        return response

    unsplash_error: Optional[str] = None
    unsplash_json: Any = None
    ninjas_obj: Optional[Dict[str, Any]] = None
    ninjas_error: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            if _is_habitat_multi_query(animal_name) and NINJAS_API_KEY:
                merge_err, merged = await _collect_merged_ninjas_records(
                    client, animal_name, habitat_wide=True
                )
                matches = [
                    r for r in merged if _record_matches_habitat_listing(animal_name, r)
                ]
                matches.sort(key=lambda r: str(r.get("name") or "").lower())
                matches = matches[:MAX_HABITAT_RESULTS]
                if len(matches) >= 1:
                    payload_list = [_ninjas_record_to_payload(r) for r in matches]
                    response["listing_note"] = (
                        "API Ninjas devuelve como máximo 10 especies por cada búsqueda "
                        "por nombre; el listado combina muchas búsquedas y filtra por el "
                        "campo `habitat` (y sinónimos). Puede haber más especies en la API "
                        "que no aparecen aquí."
                    )
                    if UNSPLASH_ACCESS_KEY:

                        async def _thumb_pair(
                            idx: int, rec: Dict[str, Any]
                        ) -> tuple[int, Optional[str]]:
                            nm = str(rec.get("name") or "").strip()
                            if not nm:
                                return idx, None
                            u = await _unsplash_search_first_url(client, nm)
                            return idx, u

                        thumb_tasks = [
                            _thumb_pair(i, rec)
                            for i, rec in enumerate(matches[:HABITAT_UNSPLASH_CAP])
                        ]
                        for pair in await asyncio.gather(*thumb_tasks):
                            idx, u_url = pair
                            if u_url:
                                payload_list[idx]["image_url"] = u_url
                    response["search_mode"] = "habitat_many"
                    response["habitat_query"] = animal_name
                    response["results_count"] = len(payload_list)
                    response["results"] = payload_list
                    ninjas_error = None
                    ninjas_obj = None
                else:
                    ninjas_error, ninjas_obj = await _resolve_ninjas_record(
                        client, animal_name
                    )
            else:
                ninjas_error, ninjas_obj = await _resolve_ninjas_record(
                    client, animal_name
                )

            if response.get("search_mode") != "habitat_many":
                image_query = animal_name
                if isinstance(ninjas_obj, dict):
                    image_query = str(
                        ninjas_obj.get("name")
                        or ninjas_obj.get("scientific_name")
                        or ninjas_obj.get("scientificName")
                        or animal_name
                    )

                async def fetch_unsplash() -> None:
                    nonlocal unsplash_error, unsplash_json
                    if not UNSPLASH_ACCESS_KEY:
                        unsplash_error = "Falta configurar 'UNSPLASH_ACCESS_KEY' en el archivo .env."
                        return

                    url = UNSPLASH_API_URL
                    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
                    params = {"query": image_query, "per_page": 1}
                    try:
                        resp = await client.get(url, params=params, headers=headers)
                    except httpx.RequestError as exc:
                        unsplash_error = f"Error de conexión llamando a Unsplash: {exc}"
                        return

                    if resp.status_code != 200:
                        unsplash_error = f"Unsplash devolvió status {resp.status_code}."
                        return

                    try:
                        unsplash_json = resp.json()
                    except ValueError:
                        unsplash_error = "Unsplash devolvió una respuesta que no es JSON."

                try:
                    await fetch_unsplash()
                except Exception as exc:
                    response["error"] = f"Error inesperado consultando Unsplash: {exc}"
                    return response
    except Exception as exc:
        response["error"] = f"Error inesperado preparando la consulta: {exc}"
        return response

    if response.get("search_mode") == "habitat_many":
        return response

    if ninjas_error:
        response["ninjas_error"] = ninjas_error
    elif isinstance(ninjas_obj, dict):
        ch = ninjas_obj.get("characteristics")
        name_from_chars = ""
        if isinstance(ch, dict):
            name_from_chars = str(ch.get("common_name") or "").strip()
        response["name"] = str(
            ninjas_obj.get("name") or name_from_chars or animal_name
        )
        tax = ninjas_obj.get("taxonomy")
        sci_from_tax = ""
        if isinstance(tax, dict):
            sci_from_tax = str(
                tax.get("scientific_name") or tax.get("scientificName") or ""
            ).strip()
        response["scientific_name"] = (
            ninjas_obj.get("scientific_name")
            or ninjas_obj.get("scientificName")
            or ninjas_obj.get("latin_name")
            or ninjas_obj.get("latinName")
            or sci_from_tax
            or ninjas_obj.get("name")
        )
        response["taxonomy"] = ninjas_obj.get("taxonomy")
        response["locations"] = ninjas_obj.get("locations")
        raw_ch = ninjas_obj.get("characteristics")
        response["characteristics"] = raw_ch if isinstance(raw_ch, dict) else None
        chars = _characteristics_dict(ninjas_obj)
        response["at_risk"] = _species_at_risk(chars)
        cs = _conservation_from_characteristics(chars)
        response["conservation_status"] = cs or None
        ff = _fun_fact_from_characteristics(chars)
        response["fun_fact"] = ff or None
    else:
        response["ninjas_error"] = "Estructura inesperada en la respuesta de API Ninjas."

    if unsplash_error:
        response["unsplash_error"] = unsplash_error
    else:
        results = None
        if isinstance(unsplash_json, dict):
            results = unsplash_json.get("results")

        if isinstance(results, list) and results:
            first = results[0] if isinstance(results[0], dict) else {}
            urls = first.get("urls", {}) if isinstance(first, dict) else {}
            if isinstance(urls, dict):
                response["image_url"] = urls.get("regular") or urls.get("raw")

    return response


class SightingCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    image_url: str = Field(min_length=1)
    habitat: str = Field(min_length=1)
    conservation_status: str = Field(default="")
    fun_fact: str = Field(default="")
    taxonomy: Optional[Any] = None
    characteristics: Optional[Any] = None
    locations: Optional[Any] = None

    @field_validator("name", "scientific_name", "image_url", "habitat", mode="before")
    @classmethod
    def strip_and_require_non_empty(cls, v: Any) -> str:
        if v is None:
            raise ValueError("El valor no puede ser vacío.")
        s = str(v).strip()
        if not s:
            raise ValueError("El valor no puede ser vacío.")
        return s

    @field_validator("conservation_status", "fun_fact", mode="before")
    @classmethod
    def strip_optional(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()


class SightingUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    scientific_name: Optional[str] = None
    image_url: Optional[str] = None
    habitat: Optional[str] = None
    conservation_status: Optional[str] = None
    fun_fact: Optional[str] = None
    taxonomy: Optional[Any] = None
    characteristics: Optional[Any] = None
    locations: Optional[Any] = None


class BadgeCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(min_length=1, default="default_user")
    badge_code: str = Field(min_length=1, default="bioma_trofeo")
    label: str = Field(min_length=1, default="León Dorado: maestro del bioma")

    @field_validator("user_id", "badge_code", "label", mode="before")
    @classmethod
    def strip_non_empty(cls, v: Any) -> str:
        if v is None:
            raise ValueError("El valor no puede ser vacío.")
        s = str(v).strip()
        if not s:
            raise ValueError("El valor no puede ser vacío.")
        return s


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(min_length=1)
    password: str = Field(min_length=4)

    @field_validator("username", mode="before")
    @classmethod
    def clean_username(cls, v: Any) -> str:
        if v is None:
            raise ValueError("El usuario no puede estar vacío.")
        raw = str(v).strip().lower()
        cleaned = re.sub(r"[^a-z0-9_\-\.]", "", raw)
        if len(cleaned) < 3:
            raise ValueError("Usa al menos 3 caracteres válidos (a-z, 0-9, _, -, .).")
        return cleaned[:40]

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, v: Any) -> str:
        if v is None:
            raise ValueError("La contraseña no puede estar vacía.")
        s = str(v).strip()
        if len(s) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres.")
        return s


class RegisterPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(min_length=1)
    password: str = Field(min_length=4)

    @field_validator("username", mode="before")
    @classmethod
    def clean_username(cls, v: Any) -> str:
        if v is None:
            raise ValueError("El usuario no puede estar vacío.")
        raw = str(v).strip().lower()
        cleaned = re.sub(r"[^a-z0-9_\-\.]", "", raw)
        if len(cleaned) < 3:
            raise ValueError("Usa al menos 3 caracteres válidos (a-z, 0-9, _, -, .).")
        return cleaned[:40]

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, v: Any) -> str:
        if v is None:
            raise ValueError("La contraseña no puede estar vacía.")
        s = str(v).strip()
        if len(s) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres.")
        return s

def _hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AdminUserCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str = Field(min_length=1)
    password: str = Field(min_length=4)
    role: str = Field(default="user")

    @field_validator("username", mode="before")
    @classmethod
    def clean_username(cls, v: Any) -> str:
        if v is None:
            raise ValueError("El usuario no puede estar vacío.")
        raw = str(v).strip().lower()
        cleaned = re.sub(r"[^a-z0-9_\-\.]", "", raw)
        if len(cleaned) < 3:
            raise ValueError("Usa al menos 3 caracteres válidos (a-z, 0-9, _, -, .).")
        return cleaned[:40]

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, v: Any) -> str:
        if v is None:
            raise ValueError("La contraseña no puede estar vacía.")
        s = str(v).strip()
        if len(s) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres.")
        return s

    @field_validator("role", mode="before")
    @classmethod
    def clean_role(cls, v: Any) -> str:
        return "admin" if str(v or "user").strip().lower() == "admin" else "user"


class AdminUserUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    password: Optional[str] = None
    role: Optional[str] = None

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        if len(s) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres.")
        return s

    @field_validator("role", mode="before")
    @classmethod
    def clean_role(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        raw = str(v).strip().lower()
        if not raw:
            return None
        return "admin" if raw == "admin" else "user"


def _ensure_default_admin() -> None:
    """Crea el admin por defecto si no existe."""
    session = SessionLocal()
    try:
        existing = (
            session.query(UserProfile)
            .filter(UserProfile.username == "admin1")
            .first()
        )
        if existing is None:
            row = UserProfile(
                username="admin1",
                display_name="admin1",
                password_hash=_hash_password("yoadmin1"),
                role="admin",
                created_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
            return

        changed = False
        if (existing.role or "").strip().lower() != "admin":
            existing.role = "admin"
            changed = True
        if not (existing.password_hash or "").strip():
            existing.password_hash = _hash_password("yoadmin1")
            changed = True
        if changed:
            session.add(existing)
            session.commit()
    finally:
        session.close()


def _cleanup_orphan_user_data() -> None:
    """
    Limpia datos huérfanos que queden de usuarios eliminados.
    Conserva `guest` por sesiones anónimas.
    """
    session = SessionLocal()
    try:
        valid_users = {
            str(u).strip().lower()
            for (u,) in session.query(UserProfile.username).all()
            if u is not None and str(u).strip()
        }
        valid_users.add("guest")

        for row in session.query(UserBadge).all():
            uid = str(row.user_id or "").strip().lower()
            if uid not in valid_users:
                session.delete(row)

        for row in session.query(Sighting).all():
            uid = str(row.user_id or "").strip().lower()
            if uid not in valid_users:
                session.delete(row)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _require_admin_user(x_user_id: Optional[str]) -> UserProfile:
    uid = str(x_user_id or "").strip().lower()
    if not uid:
        raise HTTPException(status_code=401, detail="Falta cabecera X-User-Id.")
    session = SessionLocal()
    try:
        user = (
            session.query(UserProfile)
            .filter(UserProfile.username == uid)
            .first()
        )
        if user is None:
            raise HTTPException(status_code=401, detail="Usuario no autenticado.")
        if (user.role or "").strip().lower() != "admin":
            raise HTTPException(status_code=403, detail="Acceso solo para administradores.")
        # Se devuelve una copia simple para no depender de sesión abierta.
        return UserProfile(
            username=user.username,
            display_name=user.display_name,
            password_hash=user.password_hash,
            role=user.role,
            created_at=user.created_at,
        )
    finally:
        session.close()


def _require_api_key(x_api_key: Optional[str]) -> None:
    expected = str(API_SECRET_KEY or "").strip()
    provided = str(x_api_key or "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="API_SECRET_KEY no configurada en servidor.")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized: X-API-KEY inválida.")


@app.post("/favorites")
def save_sighting(
    payload: SightingCreate,
    x_user_id: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    """Registra un avistamiento en SQLite (ruta /favorites por compatibilidad con el frontend)."""
    _require_api_key(x_api_key)
    uid = str(x_user_id or "guest").strip().lower() or "guest"
    session = SessionLocal()
    try:
        row = Sighting(
            user_id=uid,
            name=payload.name,
            scientific_name=payload.scientific_name,
            image_url=payload.image_url,
            habitat=payload.habitat,
            conservation_status=payload.conservation_status or "",
            fun_fact=payload.fun_fact or "",
            timestamp=datetime.utcnow(),
            taxonomy=payload.taxonomy,
            characteristics=payload.characteristics,
            locations_json=payload.locations,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"status": "guardado", "id": row.id}
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error guardando avistamiento: {exc}")
    finally:
        session.close()


@app.get("/favorites")
def list_sightings(x_user_id: Optional[str] = Header(default=None)):
    """Lista todos los avistamientos de la bitácora."""
    uid = str(x_user_id or "guest").strip().lower() or "guest"
    session = SessionLocal()
    try:
        rows: List[Sighting] = (
            session.query(Sighting)
            .filter(Sighting.user_id == uid)
            .order_by(Sighting.timestamp.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "name": r.name,
                "scientific_name": r.scientific_name,
                "image_url": r.image_url,
                "habitat": r.habitat,
                "timestamp": r.timestamp.isoformat() + "Z" if r.timestamp else None,
                "conservation_status": r.conservation_status,
                "fun_fact": r.fun_fact,
                "taxonomy": r.taxonomy,
                "characteristics": r.characteristics,
                "locations": r.locations_json,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.delete("/favorites/{id}")
def delete_sighting(
    id: int,
    x_user_id: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    """Elimina un avistamiento por id."""
    _require_api_key(x_api_key)
    uid = str(x_user_id or "guest").strip().lower() or "guest"
    session = SessionLocal()
    try:
        row = (
            session.query(Sighting)
            .filter(Sighting.id == id, Sighting.user_id == uid)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Avistamiento no encontrado.")

        session.delete(row)
        session.commit()
        return {"message": "Animal eliminado de la colección"}
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error eliminando avistamiento: {exc}")
    finally:
        session.close()


@app.get("/admin/users")
def admin_list_users(x_user_id: Optional[str] = Header(default=None)):
    """Listado administrativo de usuarios (solo admin)."""
    _require_admin_user(x_user_id)
    session = SessionLocal()
    try:
        rows: List[UserProfile] = (
            session.query(UserProfile).order_by(UserProfile.created_at.desc()).all()
        )
        return [
            {
                "id": r.id,
                "username": r.username,
                "display_name": r.display_name,
                "role": (r.role or "user"),
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.post("/admin/users")
def admin_create_user(
    payload: AdminUserCreatePayload,
    x_user_id: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    """Crea usuario desde panel admin."""
    _require_api_key(x_api_key)
    _require_admin_user(x_user_id)
    session = SessionLocal()
    try:
        existing = (
            session.query(UserProfile)
            .filter(UserProfile.username == payload.username)
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="El usuario ya existe.")
        row = UserProfile(
            username=payload.username,
            display_name=payload.username,
            password_hash=_hash_password(payload.password),
            role=payload.role,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"status": "created", "username": row.username}
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error creando usuario: {exc}")
    finally:
        session.close()


@app.put("/admin/users/{username}")
def admin_update_user(
    username: str,
    payload: AdminUserUpdatePayload,
    x_user_id: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    """Actualiza usuario desde panel admin (solo admin)."""
    _require_api_key(x_api_key)
    current_admin = _require_admin_user(x_user_id)
    target = str(username or "").strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail="Usuario objetivo inválido.")
    session = SessionLocal()
    try:
        row = session.query(UserProfile).filter(UserProfile.username == target).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        if payload.password is not None:
            row.password_hash = _hash_password(payload.password)
        if payload.role is not None:
            if row.username == current_admin.username and payload.role != "admin":
                raise HTTPException(
                    status_code=400,
                    detail="No puedes quitarte a ti mismo el rol admin.",
                )
            row.role = payload.role

        session.add(row)
        session.commit()
        return {"status": "updated", "username": row.username}
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error actualizando usuario: {exc}")
    finally:
        session.close()


@app.delete("/admin/users/{username}")
def admin_delete_user(
    username: str,
    x_user_id: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    """Elimina usuario desde panel admin (solo admin)."""
    _require_api_key(x_api_key)
    current_admin = _require_admin_user(x_user_id)
    target = str(username or "").strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail="Usuario objetivo inválido.")
    if target == "admin1":
        raise HTTPException(status_code=400, detail="No se puede eliminar el admin principal.")
    if target == current_admin.username:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario admin.")
    session = SessionLocal()
    try:
        row = session.query(UserProfile).filter(UserProfile.username == target).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        # Limpieza completa: también borra datos dependientes del usuario.
        badges_deleted = (
            session.query(UserBadge)
            .filter(UserBadge.user_id == target)
            .delete(synchronize_session=False)
        )
        sightings_deleted = (
            session.query(Sighting)
            .filter(Sighting.user_id == target)
            .delete(synchronize_session=False)
        )
        session.delete(row)
        session.commit()
        return {
            "status": "deleted",
            "username": target,
            "deleted_badges": int(badges_deleted),
            "deleted_sightings": int(sightings_deleted),
        }
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error eliminando usuario: {exc}")
    finally:
        session.close()


@app.post("/badges")
def save_badge(payload: BadgeCreate, x_api_key: Optional[str] = Header(default=None)):
    """Guarda una insignia asociada al usuario si aún no existe."""
    _require_api_key(x_api_key)
    session = SessionLocal()
    try:
        existing = (
            session.query(UserBadge)
            .filter(
                UserBadge.user_id == payload.user_id,
                UserBadge.badge_code == payload.badge_code,
            )
            .first()
        )
        if existing is not None:
            return {
                "status": "exists",
                "badge": {
                    "id": existing.id,
                    "user_id": existing.user_id,
                    "badge_code": existing.badge_code,
                    "label": existing.label,
                    "unlocked_at": existing.unlocked_at.isoformat() + "Z",
                },
            }

        row = UserBadge(
            user_id=payload.user_id,
            badge_code=payload.badge_code,
            label=payload.label,
            unlocked_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            "status": "saved",
            "badge": {
                "id": row.id,
                "user_id": row.user_id,
                "badge_code": row.badge_code,
                "label": row.label,
                "unlocked_at": row.unlocked_at.isoformat() + "Z",
            },
        }
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error guardando insignia: {exc}")
    finally:
        session.close()


@app.get("/badges/user/{user_id}")
def list_badges_by_user(user_id: str):
    """Lista insignias desbloqueadas por un usuario."""
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="El usuario no puede estar vacío.")
    session = SessionLocal()
    try:
        rows: List[UserBadge] = (
            session.query(UserBadge)
            .filter(UserBadge.user_id == uid)
            .order_by(UserBadge.unlocked_at.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "badge_code": r.badge_code,
                "label": r.label,
                "unlocked_at": r.unlocked_at.isoformat() + "Z" if r.unlocked_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.get("/badges/catalog")
def list_badge_catalog():
    """Catálogo global de trofeos disponibles."""
    return BADGE_CATALOG


@app.get("/badges/overview")
def badges_overview():
    """
    Resumen de trofeos:
    - catálogo total
    - para cada usuario: ganados y faltantes
    """
    session = SessionLocal()
    try:
        rows: List[UserBadge] = session.query(UserBadge).all()
        profiles: List[UserProfile] = session.query(UserProfile).all()
        by_user: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            uid = str(r.user_id).strip() or "default_user"
            entry = by_user.setdefault(
                uid,
                {"user_id": uid, "earned_codes": set(), "earned": []},
            )
            if r.badge_code in entry["earned_codes"]:
                continue
            entry["earned_codes"].add(r.badge_code)
            entry["earned"].append(
                {
                    "badge_code": r.badge_code,
                    "label": r.label,
                    "unlocked_at": r.unlocked_at.isoformat() + "Z" if r.unlocked_at else None,
                }
            )

        role_map: Dict[str, str] = {}
        for p in profiles:
            uid = str(p.username).strip()
            if not uid:
                continue
            by_user.setdefault(uid, {"user_id": uid, "earned_codes": set(), "earned": []})
            role_map[uid] = (str(p.role or "user").strip().lower() or "user")

        users_payload: List[Dict[str, Any]] = []
        for uid, entry in by_user.items():
            earned_codes = entry["earned_codes"]
            missing = [b for b in BADGE_CATALOG if b["badge_code"] not in earned_codes]
            users_payload.append(
                {
                    "user_id": uid,
                    "role": role_map.get(uid, "user"),
                    "earned": entry["earned"],
                    "missing": missing,
                    "earned_count": len(entry["earned"]),
                    "missing_count": len(missing),
                }
            )

        users_payload.sort(key=lambda x: (-x["earned_count"], x["user_id"]))
        return {"catalog": BADGE_CATALOG, "users": users_payload}
    finally:
        session.close()


@app.post("/auth/register")
def auth_register(payload: RegisterPayload, x_api_key: Optional[str] = Header(default=None)):
    """Registro de usuario con rol y contraseña."""
    _require_api_key(x_api_key)
    session = SessionLocal()
    try:
        existing = (
            session.query(UserProfile)
            .filter(UserProfile.username == payload.username)
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="El usuario ya existe.")

        row = UserProfile(
            username=payload.username,
            display_name=payload.username,
            password_hash=_hash_password(payload.password),
            role="user",
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            "status": "created",
            "user": {
                "username": row.username,
                "display_name": row.display_name,
                "role": row.role,
                "created_at": row.created_at.isoformat() + "Z",
            },
        }
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error en registro: {exc}")
    finally:
        session.close()


@app.post("/auth/login")
def auth_login(payload: LoginPayload, x_api_key: Optional[str] = Header(default=None)):
    """Login por usuario y contraseña."""
    _require_api_key(x_api_key)
    session = SessionLocal()
    try:
        existing = (
            session.query(UserProfile)
            .filter(UserProfile.username == payload.username)
            .first()
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        incoming_hash = _hash_password(payload.password)
        stored_hash = (existing.password_hash or "").strip()
        if not stored_hash:
            # Migración suave: si el usuario viene del esquema anterior sin contraseña,
            # la primera contraseña usada en login queda establecida.
            existing.password_hash = incoming_hash
            session.add(existing)
            session.commit()
            session.refresh(existing)
        elif stored_hash != incoming_hash:
            raise HTTPException(status_code=401, detail="Contraseña incorrecta.")

        return {
            "status": "ok",
            "user": {
                "username": existing.username,
                "display_name": existing.display_name,
                "role": existing.role or "user",
                "created_at": existing.created_at.isoformat() + "Z",
            },
        }
    finally:
        session.close()


@app.post("/auth/logout")
def auth_logout(x_api_key: Optional[str] = Header(default=None)):
    """Logout local (stateless)."""
    _require_api_key(x_api_key)
    return {"status": "ok"}


def _tax_pick(row: Sighting, *keys: str) -> Optional[str]:
    tax = row.taxonomy
    if not isinstance(tax, dict):
        return None
    for k in keys:
        v = tax.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()[:220]
    return None


def _char_pick(row: Sighting, *keys: str) -> Optional[str]:
    ch = row.characteristics
    if not isinstance(ch, dict):
        return None
    for k in keys:
        v = ch.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()[:220]
    return None


def _sighting_habitat_label(row: Sighting) -> Optional[str]:
    if row.habitat and str(row.habitat).strip():
        return str(row.habitat).strip()[:180]
    return _char_pick(row, "habitat", "Habitat")


def _two_distractor_values(
    rows: List[Sighting],
    exclude_id: int,
    correct_val: str,
    getter: Any,
) -> Optional[tuple[str, str]]:
    cl = correct_val.strip().lower()
    pool: List[str] = []
    seen: set = set()
    order = rows[:]
    random.shuffle(order)
    for r in order:
        if r.id == exclude_id:
            continue
        v = getter(r)
        if not v:
            continue
        t = v.strip()
        tl = t.lower()
        if tl == cl or tl in seen:
            continue
        seen.add(tl)
        pool.append(t)
        if len(pool) >= 2:
            return (pool[0], pool[1])
    return None


def _shuffle_three_unique(
    correct: str, w1: str, w2: str
) -> Optional[tuple[List[str], int]]:
    c, a, b = correct.strip(), w1.strip(), w2.strip()
    opts = [c, a, b]
    if len({x.lower() for x in opts}) < 3:
        return None
    random.shuffle(opts)
    cl = c.lower()
    idx = next(i for i, x in enumerate(opts) if x.lower() == cl)
    return opts, idx


def _quiz_scientific(all_rows: List[Sighting], correct: Sighting) -> Optional[Dict[str, Any]]:
    csci = (correct.scientific_name or "").strip()
    if not csci:
        return None
    wrong = _two_distractor_values(
        all_rows,
        correct.id,
        csci,
        lambda r: (r.scientific_name or "").strip() or None,
    )
    if wrong is None:
        return None
    sh = _shuffle_three_unique(csci, wrong[0], wrong[1])
    if sh is None:
        return None
    options, ci = sh
    return {
        "question": f'¿Cuál es el nombre científico de «{correct.name}»?',
        "options": options,
        "correct_index": ci,
        "question_kind": "scientific_name",
    }


def _quiz_habitat(all_rows: List[Sighting], correct: Sighting) -> Optional[Dict[str, Any]]:
    h = _sighting_habitat_label(correct)
    if not h:
        return None
    wrong = _two_distractor_values(all_rows, correct.id, h, _sighting_habitat_label)
    if wrong is None:
        return None
    sh = _shuffle_three_unique(h, wrong[0], wrong[1])
    if sh is None:
        return None
    options, ci = sh
    return {
        "question": f'¿Qué hábitat corresponde a «{correct.name}» en tu bitácora?',
        "options": options,
        "correct_index": ci,
        "question_kind": "habitat",
    }


def _quiz_kingdom(all_rows: List[Sighting], correct: Sighting) -> Optional[Dict[str, Any]]:
    k = _tax_pick(correct, "kingdom", "Kingdom")
    if not k:
        return None
    wrong = _two_distractor_values(
        all_rows, correct.id, k, lambda r: _tax_pick(r, "kingdom", "Kingdom")
    )
    if wrong is None:
        return None
    sh = _shuffle_three_unique(k, wrong[0], wrong[1])
    if sh is None:
        return None
    options, ci = sh
    return {
        "question": f'¿En qué reino taxonómico está «{correct.name}»?',
        "options": options,
        "correct_index": ci,
        "question_kind": "kingdom",
    }


def _quiz_order(all_rows: List[Sighting], correct: Sighting) -> Optional[Dict[str, Any]]:
    o = _tax_pick(correct, "order", "Order")
    if not o:
        return None
    wrong = _two_distractor_values(
        all_rows, correct.id, o, lambda r: _tax_pick(r, "order", "Order")
    )
    if wrong is None:
        return None
    sh = _shuffle_three_unique(o, wrong[0], wrong[1])
    if sh is None:
        return None
    options, ci = sh
    return {
        "question": f'¿A qué orden pertenece «{correct.name}»?',
        "options": options,
        "correct_index": ci,
        "question_kind": "order",
    }


def _quiz_diet(all_rows: List[Sighting], correct: Sighting) -> Optional[Dict[str, Any]]:
    d = _char_pick(correct, "diet", "Diet")
    if not d:
        return None
    wrong = _two_distractor_values(
        all_rows, correct.id, d, lambda r: _char_pick(r, "diet", "Diet")
    )
    if wrong is None:
        return None
    sh = _shuffle_three_unique(d, wrong[0], wrong[1])
    if sh is None:
        return None
    options, ci = sh
    return {
        "question": f'¿Qué tipo de dieta tiene «{correct.name}» según tu bitácora?',
        "options": options,
        "correct_index": ci,
        "question_kind": "diet",
    }


_QUIZ_BUILDERS = [
    _quiz_habitat,
    _quiz_kingdom,
    _quiz_order,
    _quiz_diet,
    _quiz_scientific,
]


@app.get("/quiz")
def get_quiz():
    """
    Trivia a partir de los datos guardados (taxonomía y características alineados
    con el esquema de API Ninjas): hábitat, reino, orden, dieta o nombre científico.
    """
    session = SessionLocal()
    try:
        all_rows: List[Sighting] = session.query(Sighting).all()
        if len(all_rows) < 3:
            raise HTTPException(
                status_code=400,
                detail="Necesitas al menos 3 avistamientos en la bitácora para jugar al trivia.",
            )

        for _ in range(24):
            correct = random.choice(all_rows)
            builders = _QUIZ_BUILDERS[:]
            random.shuffle(builders)
            for fn in builders:
                payload = fn(all_rows, correct)
                if payload is not None:
                    return payload

        raise HTTPException(
            status_code=500,
            detail="No se pudo generar una pregunta con los datos actuales de la bitácora.",
        )
    finally:
        session.close()
