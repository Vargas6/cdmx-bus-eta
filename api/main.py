from pathlib import Path
import os
import pickle

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel


# ==================================================
# RUTAS DEL PROYECTO
# ==================================================

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
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


# ==================================================
# HEALTH CHECK
# ==================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": True,
        "openai_configured": True,
    }


# ==================================================
# RUTAS
# ==================================================

@app.get("/routes")
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

@app.get("/routes/{route_id}/stops")
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

@app.post("/eta")
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

@app.post("/chat")
def chat(request: ChatRequest):

    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="El mensaje no puede estar vacío",
        )

    system_prompt = """
Eres el asistente del proyecto CDMX Bus ETA.

Tu función es ayudar a los usuarios a entender
información sobre Metrobús de la Ciudad de México
y las estimaciones generadas por el sistema.

Reglas importantes:

1. No inventes posiciones de vehículos.
2. No inventes tiempos de llegada.
3. No inventes rutas ni paradas.
4. Si no tienes un dato en el contexto disponible,
   dilo claramente.
5. El ETA es generado por un modelo de Machine
   Learning del proyecto, no por ti.
6. Responde de forma breve, clara y amigable.
7. No afirmes que tienes información en tiempo real
   si esa información no fue proporcionada.
"""

    try:

        response = openai_client.responses.create(
            model="gpt-5.6-luna",
            instructions=system_prompt,
            input=message,
        )

        return {
            "message":
                message,

            "response":
                response.output_text,

            "source":
                "OpenAI API",
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Error al consultar OpenAI: "
                f"{str(e)}"
            ),
        )