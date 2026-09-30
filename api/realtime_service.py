from pathlib import Path
from datetime import datetime
import math
import os
import pickle

import pandas as pd
import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

import truststore
truststore.inject_into_ssl()


# ==================================================
# CONFIGURACIÓN
# ==================================================

ROOT = Path(__file__).resolve().parents[1]
API_DATA = ROOT / "api" / "data"
MODEL_PATH = ROOT / "api" / "models" / "eta_model.pkl"

load_dotenv(ROOT / ".env")

MAX_DISTANCE_TO_SHAPE_M = 100
MAX_STOP_DISTANCE_TO_SHAPE_M = 100


# ==================================================
# CARGAR ARTEFACTOS
# ==================================================

shapes = pd.read_csv(
    API_DATA / "shapes.csv",
    dtype={"shape_id": str},
)

route_shapes = pd.read_csv(
    API_DATA / "route_shapes.csv",
    dtype={
        "route_id": str,
        "shape_id": str,
    },
)

route_stops = pd.read_csv(
    API_DATA / "route_stops_mapped.csv",
    dtype={
        "route_id": str,
        "shape_id": str,
        "stop_id": str,
    },
)

directions = pd.read_csv(
    API_DATA / "route_direction_diagnostic.csv",
    dtype={"route_id": str},
)

routes = pd.read_csv(
    API_DATA / "routes.csv",
    dtype={"route_id": str},
)

with open(MODEL_PATH, "rb") as file:
    eta_model = pickle.load(file)


# ==================================================
# HAVERSINE
# ==================================================

def haversine(lat1, lon1, lat2, lon2):
    r = 6_371_000

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * r * math.asin(math.sqrt(a))


# ==================================================
# PREPARAR SHAPES
# ==================================================

def prepare_shapes():
    cache = {}

    for shape_id, group in shapes.groupby("shape_id"):

        group = group.sort_values(
            "shape_pt_sequence"
        ).copy()

        rows = group.to_dict("records")

        cumulative = [0.0]

        for i in range(1, len(rows)):

            previous = rows[i - 1]
            current = rows[i]

            distance = haversine(
                previous["shape_pt_lat"],
                previous["shape_pt_lon"],
                current["shape_pt_lat"],
                current["shape_pt_lon"],
            )

            cumulative.append(
                cumulative[-1] + distance
            )

        group["shape_distance_m"] = cumulative

        cache[str(shape_id)] = group

    return cache


SHAPE_CACHE = prepare_shapes()


# ==================================================
# MAPAS AUXILIARES
# ==================================================

ROUTE_SHAPE_MAP = (
    route_shapes[
        ["route_id", "shape_id"]
    ]
    .drop_duplicates("route_id")
    .set_index("route_id")["shape_id"]
    .to_dict()
)


valid_directions = directions[
    directions["observed_direction"].isin(
        ["increasing", "decreasing"]
    )
]

DIRECTION_MAP = dict(
    zip(
        valid_directions["route_id"],
        valid_directions["observed_direction"],
    )
)


route_stops = route_stops[
    route_stops["distance_to_shape_m"]
    <= MAX_STOP_DISTANCE_TO_SHAPE_M
].copy()


STOP_CACHE = {}

for (route_id, shape_id), group in route_stops.groupby(
    ["route_id", "shape_id"]
):

    group = (
        group
        .sort_values("stop_progress_m")
        .drop_duplicates("stop_id")
    )

    STOP_CACHE[
        (str(route_id), str(shape_id))
    ] = group


# ==================================================
# AUTENTICACIÓN METROBÚS
# ==================================================

def get_realtime_url():

    api_url = os.getenv("METROBUS_API_URL")
    api_user = os.getenv("METROBUS_API_USER")
    api_password = os.getenv("METROBUS_API_PASSWORD")

    if not all(
        [api_url, api_user, api_password]
    ):
        raise RuntimeError(
            "Faltan credenciales de Metrobús en .env"
        )

    response = requests.post(
        api_url,
        json={
            "usuario": api_user,
            "senha": api_password,
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    realtime_url = data.get("urlRealTime")

    if not realtime_url:
        raise RuntimeError(
            "La API de Metrobús no devolvió urlRealTime"
        )

    return realtime_url


# ==================================================
# DESCARGAR GTFS-REALTIME
# ==================================================

def download_realtime_feed():

    realtime_url = get_realtime_url()

    response = requests.get(
        realtime_url,
        timeout=60,
    )

    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()

    feed.ParseFromString(
        response.content
    )

    return feed


# ==================================================
# EXTRAER VEHÍCULOS
# ==================================================

def extract_vehicles(feed):

    vehicles = []

    for entity in feed.entity:

        if not entity.HasField("vehicle"):
            continue

        vehicle = entity.vehicle

        if not vehicle.HasField("position"):
            continue

        if not vehicle.HasField("trip"):
            continue

        route_id = vehicle.trip.route_id

        if not route_id:
            continue

        latitude = float(
            vehicle.position.latitude
        )

        longitude = float(
            vehicle.position.longitude
        )

        if latitude == 0 or longitude == 0:
            continue

        timestamp = None

        if vehicle.HasField("timestamp"):
            timestamp = int(
                vehicle.timestamp
            )

        direction_id = None

        if vehicle.trip.HasField("direction_id"):
            direction_id = int(
                vehicle.trip.direction_id
            )

        vehicles.append(
            {
                "route_id": str(route_id),
                "direction_id": direction_id,
                "latitude": latitude,
                "longitude": longitude,
                "vehicle_timestamp": timestamp,
            }
        )

    return vehicles


# ==================================================
# PUNTO MÁS CERCANO DEL SHAPE
# ==================================================

def nearest_shape_point(
    latitude,
    longitude,
    shape,
):

    best_row = None
    best_distance = float("inf")

    for _, point in shape.iterrows():

        distance = haversine(
            latitude,
            longitude,
            point["shape_pt_lat"],
            point["shape_pt_lon"],
        )

        if distance < best_distance:

            best_distance = distance
            best_row = point

    return best_row, best_distance


# ==================================================
# MAP MATCHING DE UN VEHÍCULO
# ==================================================

def match_vehicle(vehicle):

    route_id = vehicle["route_id"]

    shape_id = ROUTE_SHAPE_MAP.get(
        route_id
    )

    if shape_id is None:
        return None

    shape = SHAPE_CACHE.get(
        str(shape_id)
    )

    if shape is None or shape.empty:
        return None

    matched_point, distance_to_shape = (
        nearest_shape_point(
            vehicle["latitude"],
            vehicle["longitude"],
            shape,
        )
    )

    if matched_point is None:
        return None

    if (
        distance_to_shape
        > MAX_DISTANCE_TO_SHAPE_M
    ):
        return None

    progress_m = float(
        matched_point["shape_distance_m"]
    )

    route_length_m = float(
        shape["shape_distance_m"].iloc[-1]
    )

    if route_length_m <= 0:
        return None

    progress_pct = (
        progress_m
        / route_length_m
        * 100
    )

    return {
        **vehicle,
        "shape_id": str(shape_id),
        "distance_to_shape_m":
            distance_to_shape,
        "progress_m":
            progress_m,
        "route_length_m":
            route_length_m,
        "progress_pct":
            progress_pct,
    }


# ==================================================
# PRÓXIMA PARADA
# ==================================================

def assign_next_stop(vehicle):

    route_id = vehicle["route_id"]
    shape_id = vehicle["shape_id"]

    observed_direction = (
        DIRECTION_MAP.get(route_id)
    )

    if observed_direction is None:
        return None

    stops_for_route = STOP_CACHE.get(
        (route_id, shape_id)
    )

    if (
        stops_for_route is None
        or stops_for_route.empty
    ):
        return None

    current_progress = float(
        vehicle["progress_m"]
    )

    if observed_direction == "increasing":

        upcoming = stops_for_route[
            stops_for_route["stop_progress_m"]
            > current_progress
        ]

        if upcoming.empty:
            return None

        next_stop = upcoming.sort_values(
            "stop_progress_m",
            ascending=True,
        ).iloc[0]

        remaining_distance = (
            float(
                next_stop["stop_progress_m"]
            )
            - current_progress
        )

    else:

        upcoming = stops_for_route[
            stops_for_route["stop_progress_m"]
            < current_progress
        ]

        if upcoming.empty:
            return None

        next_stop = upcoming.sort_values(
            "stop_progress_m",
            ascending=False,
        ).iloc[0]

        remaining_distance = (
            current_progress
            - float(
                next_stop["stop_progress_m"]
            )
        )

    return {
        **vehicle,
        "observed_direction":
            observed_direction,
        "next_stop_id":
            str(next_stop["stop_id"]),
        "next_stop_name":
            str(next_stop["stop_name"]),
        "distance_to_next_stop_m":
            remaining_distance,
    }


# ==================================================
# PREDECIR ETA
# ==================================================

def predict_live_eta(vehicle):

    now = datetime.now()

    hour_decimal = (
        now.hour
        + now.minute / 60
        + now.second / 3600
    )

    X = pd.DataFrame(
        [
            {
                "distance_to_next_stop_m":
                    vehicle[
                        "distance_to_next_stop_m"
                    ],

                "progress_pct":
                    vehicle["progress_pct"],

                "hour_decimal":
                    hour_decimal,

                "route_id":
                    vehicle["route_id"],

                "next_stop_id":
                    vehicle["next_stop_id"],
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

    return prediction


# ==================================================
# NOMBRE DE RUTA
# ==================================================

def get_route_name(route_id):

    match = routes[
        routes["route_id"] == route_id
    ]

    if match.empty:
        return ""

    row = match.iloc[0]

    short_name = row.get(
        "route_short_name",
        "",
    )

    long_name = row.get(
        "route_long_name",
        "",
    )

    if pd.isna(short_name):
        short_name = ""

    if pd.isna(long_name):
        long_name = ""

    return (
        str(long_name)
        if str(long_name).strip()
        else str(short_name)
    )


# ==================================================
# OBTENER ESTADO LIVE
# ==================================================

def get_live_vehicles(
    route_id=None,
    limit=50,
):

    feed = download_realtime_feed()

    raw_vehicles = extract_vehicles(feed)

    results = []

    for vehicle in raw_vehicles:

        if (
            route_id is not None
            and vehicle["route_id"]
            != str(route_id)
        ):
            continue

        matched = match_vehicle(
            vehicle
        )

        if matched is None:
            continue

        assigned = assign_next_stop(
            matched
        )

        if assigned is None:
            continue

        distance = float(
            assigned[
                "distance_to_next_stop_m"
            ]
        )

        # El modelo fue construido principalmente
        # con observaciones de hasta 3 km.
        if not 0 <= distance <= 3000:
            continue

        eta_minutes = predict_live_eta(
            assigned
        )

        results.append(
            {
                "route_id":
                    assigned["route_id"],

                "route_name":
                    get_route_name(
                        assigned["route_id"]
                    ),

                "direction_id":
                    assigned["direction_id"],

                "latitude":
                    round(
                        assigned["latitude"],
                        6,
                    ),

                "longitude":
                    round(
                        assigned["longitude"],
                        6,
                    ),

                "next_stop_id":
                    assigned["next_stop_id"],

                "next_stop_name":
                    assigned["next_stop_name"],

                "distance_to_next_stop_m":
                    round(distance, 1),

                "progress_pct":
                    round(
                        assigned["progress_pct"],
                        2,
                    ),

                "eta_minutes":
                    round(
                        eta_minutes,
                        2,
                    ),

                "eta_seconds":
                    round(
                        eta_minutes * 60
                    ),

                "vehicle_timestamp":
                    assigned[
                        "vehicle_timestamp"
                    ],
            }
        )

        if len(results) >= limit:
            break

    return results