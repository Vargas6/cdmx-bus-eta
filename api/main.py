from pathlib import Path
import os
import pickle
import re

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from api.realtime_service import get_live_vehicles


# ==================================================
# RUTAS DEL PROYECTO
# ==================================================

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "api" / "data"

MODEL_PATH = ROOT / "api" / "models" / "eta_model.pkl"


# ==================================================
# VARIABLES DE ENTORNO
# ==================================================

load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError(
        "No se encontró OPENAI_API_KEY en .env"
    )


# ==================================================
# CLIENTE OPENAI
# ==================================================

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ==================================================
# FASTAPI
# ==================================================

app = FastAPI(
    title="CDMX Bus ETA API",
    description=(
        "API experimental para estimación de tiempos "
        "de llegada de Metrobús CDMX."
    ),
    version="0.1.0",
)


# ==================================================
# CORS
# ==================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# CARGAR MODELO ETA
# ==================================================

with open(MODEL_PATH, "rb") as f:
    eta_model = pickle.load(f)


# ==================================================
# CARGAR CATÁLOGOS
# ==================================================

routes = pd.read_csv(
    DATA / "routes.csv",
    dtype={
        "route_id": str,
    },
)

stops = pd.read_csv(
    DATA / "route_stops_mapped.csv",
    dtype={
        "route_id": str,
        "stop_id": str,
        "shape_id": str,
    },
)


# ==================================================
# MODELOS DE ENTRADA
# ==================================================

class ETARequest(BaseModel):
    route_id: str
    next_stop_id: str
    distance_to_next_stop_m: float
    progress_pct: float
    hour_decimal: float


class ChatRequest(BaseModel):
    message: str
    route_id: str | None = None


# ==================================================
# CONFIGURACIÓN DEL ASISTENTE
# ==================================================

OUT_OF_SCOPE_MESSAGE = (
    "Solo puedo ayudarte con consultas relacionadas con "
    "CDMX Bus ETA, Metrobús CDMX, las rutas del proyecto, "
    "unidades disponibles, próximas paradas y estimaciones "
    "de llegada."
)


# Palabras y expresiones directamente relacionadas
# con el dominio del proyecto.
PROJECT_TERMS = [
    "metrobus",
    "metrobús",
    "ruta",
    "rutas",
    "unidad",
    "unidades",
    "autobus",
    "autobús",
    "camion",
    "camión",
    "parada",
    "paradas",
    "eta",
    "llegada",
    "llegar",
    "tiempo",
    "tarda",
    "tardar",
    "distancia",
    "avance",
    "gtfs",
    "gtfs-rt",
    "realtime",
    "tiempo real",
    "transporte",
    "cdmx",
    "bus",
    "modelo",
    "machine learning",
    "prediccion",
    "predicción",
    "estimacion",
    "estimación",
    "mapa",
    "ubicacion",
    "ubicación",
    "siguiente",
    "proxima",
    "próxima",
    "cerca",
    "cercana",
    "cercano",
]


# Preguntas cortas que tienen sentido cuando ya existe
# una ruta seleccionada.
CONTEXTUAL_TERMS = [
    "cuanto falta",
    "cuánto falta",
    "cuanto tarda",
    "cuánto tarda",
    "cual llega",
    "cuál llega",
    "cual esta",
    "cuál está",
    "donde esta",
    "dónde está",
    "hay alguna",
    "hay uno",
    "hay una",
    "que sigue",
    "qué sigue",
    "mas cerca",
    "más cerca",
    "primero",
]


def normalize_text(text: str) -> str:
    """
    Normaliza texto para realizar una validación básica
    del dominio del chatbot.
    """

    return re.sub(
        r"\s+",
        " ",
        text.lower().strip(),
    )


def is_project_question(
    message: str,
    route_id: str | None = None,
) -> bool:
    """
    Filtro preliminar.

    No pretende comprender lenguaje natural por completo.
    Su función es bloquear preguntas evidentemente ajenas
    al proyecto antes de realizar una llamada a OpenAI.
    """

    normalized = normalize_text(message)

    if not normalized:
        return False

    if any(
        term in normalized
        for term in PROJECT_TERMS
    ):
        return True

    if route_id and any(
        term in normalized
        for term in CONTEXTUAL_TERMS
    ):
        return True

    return False


# ==================================================
# HEALTH CHECK
# ==================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "model_loaded": True,
        "openai_configured": True,
    }


# ==================================================
# RUTAS
# ==================================================

@app.get("/api/routes")
def get_routes():

    columns = [
        "route_id",
        "route_short_name",
        "route_long_name",
    ]

    available = [
        column
        for column in columns
        if column in routes.columns
    ]

    result = (
        routes[available]
        .drop_duplicates()
        .fillna("")
        .to_dict(orient="records")
    )

    return result


# ==================================================
# PARADAS POR RUTA
# ==================================================

@app.get("/api/routes/{route_id}/stops")
def get_route_stops(route_id: str):

    route_data = stops[
        stops["route_id"] == route_id
    ].copy()

    if route_data.empty:
        raise HTTPException(
            status_code=404,
            detail="Ruta no encontrada",
        )

    route_data = (
        route_data
        .sort_values("stop_sequence")
        .drop_duplicates("stop_id")
    )

    columns = [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "stop_sequence",
    ]

    result = (
        route_data[columns]
        .fillna("")
        .to_dict(orient="records")
    )

    return result


# ==================================================
# PREDICCIÓN ETA
# ==================================================

@app.post("/api/eta")
def predict_eta(request: ETARequest):

    if request.distance_to_next_stop_m < 0:
        raise HTTPException(
            status_code=400,
            detail="La distancia no puede ser negativa",
        )

    if not 0 <= request.progress_pct <= 100:
        raise HTTPException(
            status_code=400,
            detail=(
                "progress_pct debe estar "
                "entre 0 y 100"
            ),
        )

    if not 0 <= request.hour_decimal < 24:
        raise HTTPException(
            status_code=400,
            detail=(
                "hour_decimal debe estar "
                "entre 0 y 24"
            ),
        )

    X = pd.DataFrame(
        [
            {
                "distance_to_next_stop_m":
                    request.distance_to_next_stop_m,

                "progress_pct":
                    request.progress_pct,

                "hour_decimal":
                    request.hour_decimal,

                "route_id":
                    request.route_id,

                "next_stop_id":
                    request.next_stop_id,
            }
        ]
    )

    prediction = float(
        eta_model.predict(X)[0]
    )

    prediction = max(
        0.25,
        min(20.0, prediction),
    )

    return {
        "route_id":
            request.route_id,

        "next_stop_id":
            request.next_stop_id,

        "distance_to_next_stop_m":
            request.distance_to_next_stop_m,

        "eta_minutes":
            round(prediction, 2),

        "eta_seconds":
            round(prediction * 60),

        "model":
            "HistGradientBoostingRegressor",
    }


# ==================================================
# CHATBOT OPENAI
# ==================================================

@app.post("/api/chat")
def chat(request: ChatRequest):

    # --------------------------------------------------
    # 1. Validar que la pregunta pertenezca al proyecto
    # --------------------------------------------------

    if not is_project_question(
        request.message,
        request.route_id,
    ):
        return {
            "answer": OUT_OF_SCOPE_MESSAGE,
            "realtime_count": 0,
            "out_of_scope": True,
        }

    # --------------------------------------------------
    # 2. Obtener información REAL del sistema
    # --------------------------------------------------

    try:
        live_vehicles = get_live_vehicles(
            route_id=request.route_id,
            limit=10,
        )

    except Exception as exc:

        print(
            "Error obteniendo información realtime:",
            type(exc).__name__,
        )

        live_vehicles = []

    # --------------------------------------------------
    # 3. Preparar contexto controlado para OpenAI
    # --------------------------------------------------

    if live_vehicles:

        context_lines = []

        for vehicle in live_vehicles:

            context_lines.append(
                (
                    f"Ruta {vehicle['route_id']} "
                    f"({vehicle['route_name']}): "
                    f"próxima parada "
                    f"{vehicle['next_stop_name']}; "
                    f"distancia aproximada "
                    f"{vehicle['distance_to_next_stop_m']} metros; "
                    f"avance de la unidad "
                    f"{vehicle['progress_pct']}%; "
                    f"ETA estimado por el modelo ML "
                    f"{vehicle['eta_minutes']} minutos "
                    f"({vehicle['eta_seconds']} segundos)."
                )
            )

        system_context = "\n".join(
            context_lines
        )

    else:

        system_context = (
            "No hay observaciones realtime válidas "
            "disponibles para esta consulta."
        )

    # --------------------------------------------------
    # 4. Instrucciones especializadas para OpenAI
    # --------------------------------------------------

    instructions = """
Eres el asistente especializado del proyecto CDMX Bus ETA.

Tu función EXCLUSIVA es ayudar al usuario con información
relacionada con este proyecto de transporte público y con
los datos proporcionados por su backend.

PUEDES HABLAR SOBRE:

- CDMX Bus ETA.
- Metrobús de la Ciudad de México dentro del contexto
  disponible en el proyecto.
- Rutas incluidas en el sistema.
- Unidades observadas por GTFS-Realtime.
- Próximas paradas.
- Distancias mostradas por el sistema.
- Avance de las unidades.
- ETA o tiempos estimados de llegada.
- El modelo de Machine Learning utilizado para generar
  las estimaciones.
- GTFS y GTFS-Realtime cuando sea relevante al proyecto.
- El funcionamiento general del proyecto cuando la
  información necesaria esté disponible en el contexto.

NO DEBES RESPONDER preguntas que no estén relacionadas
con CDMX Bus ETA o con el dominio del proyecto.

Ejemplos de temas que debes rechazar:

- Historia general.
- Cultura general.
- Matemáticas que no tengan relación con el proyecto.
- Recetas.
- Deportes.
- Política.
- Entretenimiento.
- Preguntas personales.
- Programación no relacionada con este proyecto.
- Cualquier otro tema ajeno al sistema.

Si el usuario hace una pregunta fuera del alcance,
responde ÚNICAMENTE:

"Solo puedo ayudarte con consultas relacionadas con
CDMX Bus ETA, Metrobús CDMX, las rutas del proyecto,
unidades disponibles, próximas paradas y estimaciones
de llegada."

REGLAS SOBRE LOS DATOS:

- No inventes rutas.
- No inventes paradas.
- No inventes posiciones.
- No inventes unidades.
- No inventes tiempos.
- No calcules un ETA por tu cuenta.
- Los ETA proporcionados fueron generados por el modelo
  de Machine Learning del proyecto.
- Utiliza únicamente los datos incluidos en CONTEXTO DEL
  SISTEMA para hablar de información realtime.
- Si el contexto no contiene la información necesaria,
  dilo claramente.
- Si no existen observaciones realtime válidas, no
  inventes unidades para responder.
- No afirmes que un ETA es exacto.
- Describe los ETA como estimaciones.
- Responde en español.
- Sé claro y breve.
"""

    # --------------------------------------------------
    # 5. Construir prompt
    # --------------------------------------------------

    prompt = f"""
PREGUNTA DEL USUARIO:

{request.message}

RUTA SELECCIONADA:

{request.route_id or "No especificada"}

CONTEXTO DEL SISTEMA:

{system_context}
"""

    # --------------------------------------------------
    # 6. Consultar OpenAI
    # --------------------------------------------------

    try:

        response = openai_client.responses.create(
            model="gpt-5.6-luna",
            instructions=instructions,
            input=prompt,
        )

        answer = response.output_text

    except Exception as exc:

        print(
            "Error consultando OpenAI:",
            type(exc).__name__,
        )

        return {
            "answer":
                "No fue posible consultar el asistente "
                "en este momento.",

            "realtime_count":
                len(live_vehicles),

            "out_of_scope":
                False,
        }

    # --------------------------------------------------
    # 7. RESPUESTA
    # --------------------------------------------------

    return {
        "answer": answer,

        "realtime_count":
            len(live_vehicles),

        "out_of_scope":
            False,
    }


# ==================================================
# DATOS EN TIEMPO REAL
# ==================================================

@app.get("/api/live")
def live_vehicles(
    route_id: str | None = None,
    limit: int = 20,
):
    """
    Obtiene posiciones actuales de Metrobús,
    realiza map matching, identifica la próxima
    parada y estima el ETA con el modelo ML.
    """

    limit = max(
        1,
        min(limit, 100),
    )

    vehicles = get_live_vehicles(
        route_id=route_id,
        limit=limit,
    )

    return {
        "count": len(vehicles),
        "vehicles": vehicles,
    }