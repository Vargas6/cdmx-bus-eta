import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "raw" / "realtime"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INTERVAL_SECONDS = 60

FIELDS = [
    "collected_at",
    "vehicle_timestamp",
    "vehicle_id",
    "route_id",
    "direction_id",
    "start_date",
    "start_time",
    "latitude",
    "longitude",
    "speed",
    "bearing",
    "odometer",
]


def authenticate():
    load_dotenv(ROOT / ".env")

    url = os.getenv("METROBUS_API_URL")
    user = os.getenv("METROBUS_API_USER")
    password = os.getenv("METROBUS_API_PASSWORD")

    if not all([url, user, password]):
        raise RuntimeError(
            "Faltan METROBUS_API_URL, METROBUS_API_USER o "
            "METROBUS_API_PASSWORD en .env"
        )

    response = requests.post(
        url,
        json={
            "usuario": user,
            "senha": password,
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    realtime_url = data.get("urlRealTime")

    if not realtime_url:
        raise RuntimeError("La autenticación no devolvió urlRealTime.")

    return realtime_url


def download_feed(realtime_url):
    response = requests.get(realtime_url, timeout=30)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    return feed


def extract_rows(feed):
    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue

        vp = entity.vehicle

        vehicle_id = ""
        if vp.HasField("vehicle"):
            vehicle_id = vp.vehicle.id or ""

        vehicle_timestamp = vp.timestamp if vp.HasField("timestamp") else ""

        route_id = ""
        direction_id = ""
        start_date = ""
        start_time = ""

        if vp.HasField("trip"):
            route_id = vp.trip.route_id or ""
            start_date = vp.trip.start_date or ""
            start_time = vp.trip.start_time or ""

            if vp.trip.HasField("direction_id"):
                direction_id = vp.trip.direction_id

        latitude = ""
        longitude = ""
        speed = ""
        bearing = ""
        odometer = ""

        if vp.HasField("position"):
            position = vp.position

            if position.HasField("latitude"):
                latitude = position.latitude

            if position.HasField("longitude"):
                longitude = position.longitude

            if position.HasField("speed"):
                speed = position.speed

            if position.HasField("bearing"):
                bearing = position.bearing

            if position.HasField("odometer"):
                odometer = position.odometer

        if not vehicle_id or not vehicle_timestamp:
            continue

        rows.append(
            {
                "collected_at": collected_at,
                "vehicle_timestamp": vehicle_timestamp,
                "vehicle_id": vehicle_id,
                "route_id": route_id,
                "direction_id": direction_id,
                "start_date": start_date,
                "start_time": start_time,
                "latitude": latitude,
                "longitude": longitude,
                "speed": speed,
                "bearing": bearing,
                "odometer": odometer,
            }
        )

    return rows


def append_rows(csv_path, rows, seen):
    new_rows = []

    for row in rows:
        key = (row["vehicle_id"], row["vehicle_timestamp"])

        if key in seen:
            continue

        seen.add(key)
        new_rows.append(row)

    if not new_rows:
        return 0

    file_exists = csv_path.exists()

    with csv_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)

        if not file_exists:
            writer.writeheader()

        writer.writerows(new_rows)

    return len(new_rows)


def main():
    print("Recolector GTFS-Realtime Metrobús")
    print(f"Intervalo: {INTERVAL_SECONDS} segundos")
    print("Presiona Ctrl+C para detenerlo.")
    print()

    csv_path = OUTPUT_DIR / f"metrobus_{datetime.now():%Y%m%d}.csv"

    seen = set()
    realtime_url = None
    url_obtained_at = 0

    while True:
        try:
            # Renovamos la URL firmada periódicamente.
            # El manual indica que estas URLs son temporales.
            if realtime_url is None or time.time() - url_obtained_at >= 8 * 60:
                realtime_url = authenticate()
                url_obtained_at = time.time()
                print("URL realtime renovada correctamente.")

            feed = download_feed(realtime_url)
            rows = extract_rows(feed)

            saved = append_rows(csv_path, rows, seen)

            with_route = sum(1 for row in rows if row["route_id"])

            now = datetime.now().strftime("%H:%M:%S")

            print(
                f"[{now}] "
                f"vehículos={len(rows)} | "
                f"con_ruta={with_route} | "
                f"nuevos_guardados={saved}"
            )

        except KeyboardInterrupt:
            print()
            print("Recolector detenido por el usuario.")
            break

        except requests.RequestException as exc:
            print(
                f"Error de red: {type(exc).__name__}. "
                "Se renovará la URL en el siguiente intento."
            )
            realtime_url = None

        except Exception as exc:
            print(f"Error: {type(exc).__name__}: {exc}")
            realtime_url = None

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())