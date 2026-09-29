"""Prueba de autenticación y decodificación GTFS-Realtime de Metrobús.

No imprime credenciales ni URLs firmadas. No modifica .env. No persiste descargas.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
STATIC_ZIP = ROOT / "data" / "raw" / "Metrobus_GTFS_ESTATICO.zip"

REQUIRED_ENV = ("METROBUS_API_URL", "METROBUS_API_USER", "METROBUS_API_PASSWORD")
STATIC_ID_FILES = {
    "route_id": "routes.txt",
    "trip_id": "trips.txt",
    "stop_id": "stops.txt",
}


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fail(message: str, code: int = 1) -> int:
    print(f"ERROR: {message}")
    return code


def env_present(name: str) -> bool:
    value = os.environ.get(name)
    return bool(value and value.strip())


def load_environment() -> None:
    load_dotenv(ENV_PATH, override=False)


def url_metadata(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.netloc,
        "path": parsed.path,
        "signed_query": bool(parsed.query),
    }


def print_url_metadata(label: str, url: str) -> None:
    meta = url_metadata(url)
    query = "sí (omitida)" if meta["signed_query"] else "no"
    print(
        f"  {label}: presente; "
        f"{meta['scheme']}://{meta['host']}{meta['path']}; query_firmada={query}"
    )


def redact_error_body(text: str) -> str:
    def _strip(match: str) -> str:
        parsed = urlparse(match)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else "[url]"
        return f"{base}?[REDACTED]" if parsed.query else base

    redacted = re.sub(r"https?://[^\s\"'<>]+", lambda m: _strip(m.group(0)), text)
    redacted = re.sub(
        r'(?i)("(?:usuario|senha|password|passwd|user|token)"\s*:\s*")[^"]+"',
        r'\1[REDACTED]"',
        redacted,
    )
    return redacted[:800]


def anon_id(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"anon_{digest}"


def proto_fields_set(message) -> list[str]:
    return [field.name for field, _value in message.ListFields()]


def nested_set(message, prefix: str = "") -> list[str]:
    names: list[str] = []
    for field, value in message.ListFields():
        path = f"{prefix}.{field.name}" if prefix else field.name
        names.append(path)
        if field.message_type and not field.is_repeated:
            names.extend(nested_set(value, path))
        elif field.message_type and field.label == field.LABEL_REPEATED:
            for item in value:
                names.extend(nested_set(item, path))
                break
    return names


def collect_ids(feed: gtfs_realtime_pb2.FeedMessage) -> dict[str, set[str]]:
    ids = {"route_id": set(), "trip_id": set(), "stop_id": set()}

    def add_trip(trip) -> None:
        if trip.trip_id:
            ids["trip_id"].add(trip.trip_id)
        if trip.route_id:
            ids["route_id"].add(trip.route_id)

    for entity in feed.entity:
        if entity.HasField("vehicle"):
            vp = entity.vehicle
            if vp.HasField("trip"):
                add_trip(vp.trip)
            if vp.HasField("stop_id") and vp.stop_id:
                ids["stop_id"].add(vp.stop_id)
        if entity.HasField("trip_update"):
            tu = entity.trip_update
            if tu.HasField("trip"):
                add_trip(tu.trip)
            for stu in tu.stop_time_update:
                if stu.stop_id:
                    ids["stop_id"].add(stu.stop_id)
        if entity.HasField("alert"):
            for informed in entity.alert.informed_entity:
                if informed.route_id:
                    ids["route_id"].add(informed.route_id)
                if informed.trip.trip_id:
                    ids["trip_id"].add(informed.trip.trip_id)
                if informed.stop_id:
                    ids["stop_id"].add(informed.stop_id)
    return ids


def vehicle_field_presence(feed: gtfs_realtime_pb2.FeedMessage) -> dict[str, bool]:
    flags = {
        "vehicle_id": False,
        "trip_id": False,
        "route_id": False,
        "stop_id": False,
        "timestamp": False,
        "latitude": False,
        "longitude": False,
        "current_stop_sequence": False,
        "current_status": False,
    }
    vp_fields: set[str] = set()
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vp = entity.vehicle
        vp_fields.update(nested_set(vp))
        if vp.HasField("vehicle") and vp.vehicle.id:
            flags["vehicle_id"] = True
        if vp.HasField("trip"):
            if vp.trip.trip_id:
                flags["trip_id"] = True
            if vp.trip.route_id:
                flags["route_id"] = True
        if vp.HasField("stop_id") and vp.stop_id:
            flags["stop_id"] = True
        if vp.HasField("timestamp") and vp.timestamp:
            flags["timestamp"] = True
        if vp.HasField("position"):
            if vp.position.HasField("latitude"):
                flags["latitude"] = True
            if vp.position.HasField("longitude"):
                flags["longitude"] = True
        if vp.HasField("current_stop_sequence"):
            flags["current_stop_sequence"] = True
        if vp.HasField("current_status"):
            flags["current_status"] = True
    flags["vehicleposition_fields"] = sorted(vp_fields)
    return flags
def vehicle_field_coverage(feed: gtfs_realtime_pb2.FeedMessage) -> dict[str, int]:
    """Cuenta cuántos VehiclePosition contienen cada campo útil."""
    counts = {
        "total": 0,
        "vehicle_id": 0,
        "route_id": 0,
        "direction_id": 0,
        "trip_id": 0,
        "start_time": 0,
        "start_date": 0,
        "timestamp": 0,
        "latitude": 0,
        "longitude": 0,
        "speed": 0,
        "bearing": 0,
        "odometer": 0,
        "stop_id": 0,
        "current_stop_sequence": 0,
        "current_status": 0,
    }

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue

        vp = entity.vehicle
        counts["total"] += 1

        if vp.HasField("vehicle") and vp.vehicle.id:
            counts["vehicle_id"] += 1

        if vp.HasField("trip"):
            if vp.trip.route_id:
                counts["route_id"] += 1
            if vp.trip.trip_id:
                counts["trip_id"] += 1
            if vp.trip.HasField("direction_id"):
                counts["direction_id"] += 1
            if vp.trip.start_time:
                counts["start_time"] += 1
            if vp.trip.start_date:
                counts["start_date"] += 1

        if vp.HasField("timestamp") and vp.timestamp:
            counts["timestamp"] += 1

        if vp.HasField("position"):
            if vp.position.HasField("latitude"):
                counts["latitude"] += 1
            if vp.position.HasField("longitude"):
                counts["longitude"] += 1
            if vp.position.HasField("speed"):
                counts["speed"] += 1
            if vp.position.HasField("bearing"):
                counts["bearing"] += 1
            if vp.position.HasField("odometer"):
                counts["odometer"] += 1

        if vp.HasField("stop_id") and vp.stop_id:
            counts["stop_id"] += 1

        if vp.HasField("current_stop_sequence"):
            counts["current_stop_sequence"] += 1

        if vp.HasField("current_status"):
            counts["current_status"] += 1

    return counts

def anonymized_samples(feed: gtfs_realtime_pb2.FeedMessage, limit: int = 3) -> list[dict]:
    samples: list[dict] = []
    for entity in feed.entity:
        if len(samples) >= limit:
            break
        kind = None
        payload: dict = {"entity_id": anon_id(entity.id) if entity.id else None}
        if entity.HasField("vehicle"):
            kind = "VehiclePosition"
            vp = entity.vehicle
            payload["fields"] = nested_set(vp)
            if vp.HasField("vehicle") and vp.vehicle.id:
                payload["vehicle_id"] = anon_id(vp.vehicle.id)
            if vp.HasField("trip"):
                payload["trip_id"] = anon_id(vp.trip.trip_id) if vp.trip.trip_id else None
                payload["route_id"] = anon_id(vp.trip.route_id) if vp.trip.route_id else None
            if vp.HasField("stop_id") and vp.stop_id:
                payload["stop_id"] = anon_id(vp.stop_id)
            if vp.HasField("timestamp"):
                payload["timestamp"] = int(vp.timestamp)
            if vp.HasField("position"):
                payload["latitude"] = round(vp.position.latitude, 3)
                payload["longitude"] = round(vp.position.longitude, 3)
            if vp.HasField("current_stop_sequence"):
                payload["current_stop_sequence"] = int(vp.current_stop_sequence)
            if vp.HasField("current_status"):
                payload["current_status"] = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(
                    vp.current_status
                )
        elif entity.HasField("trip_update"):
            kind = "TripUpdate"
            tu = entity.trip_update
            payload["fields"] = nested_set(tu)
            if tu.HasField("trip"):
                payload["trip_id"] = anon_id(tu.trip.trip_id) if tu.trip.trip_id else None
                payload["route_id"] = anon_id(tu.trip.route_id) if tu.trip.route_id else None
            payload["stop_time_updates"] = len(tu.stop_time_update)
        elif entity.HasField("alert"):
            kind = "Alert"
            payload["fields"] = nested_set(entity.alert)
            payload["informed_entities"] = len(entity.alert.informed_entity)
        else:
            continue
        payload["type"] = kind
        samples.append(payload)
    return samples


def load_static_ids(zip_path: Path) -> dict[str, set[str]]:
    ids = {key: set() for key in STATIC_ID_FILES}
    if not zip_path.exists():
        raise FileNotFoundError(f"No se encontró {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        names = {Path(n.replace("\\", "/")).name.lower(): n for n in zf.namelist() if not n.endswith("/")}
        for key, filename in STATIC_ID_FILES.items():
            inner = names.get(filename)
            if inner is None:
                continue
            raw = zf.read(inner)
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                value = (row.get(key) or "").strip()
                if value:
                    ids[key].add(value)
    return ids


def match_rate(found: set[str], catalog: set[str]) -> dict:
    n_found = len(found)
    n_matched = len(found & catalog) if catalog else 0
    pct = (100.0 * n_matched / n_found) if n_found else None
    return {
        "en_realtime": n_found,
        "en_estatico": len(catalog),
        "cruzados": n_matched,
        "porcentaje": pct,
    }


def authenticate() -> tuple[requests.Response | None, int]:
    url = os.environ["METROBUS_API_URL"].strip()
    user = os.environ["METROBUS_API_USER"].strip()
    password = os.environ["METROBUS_API_PASSWORD"].strip()
    payload = {"usuario": user, "senha": password}
    print("POST de autenticación (body según manual: usuario, senha).")
    print(f"  endpoint host: {urlparse(url).netloc}; path: {urlparse(url).path}")
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"ERROR de red en POST: {type(exc).__name__}")
        return None, 2
    return response, 0


def decode_feed(blob: bytes) -> tuple[gtfs_realtime_pb2.FeedMessage | None, list[str]]:
    notes: list[str] = []
    if blob.startswith(b"{") or blob.lstrip().startswith(b"{"):
        notes.append("el contenido parece JSON, no protobuf")
        return None, notes
    if blob.startswith(b"PK"):
        notes.append("el contenido parece ZIP, no protobuf")
        return None, notes
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(blob)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"ParseFromString falló: {type(exc).__name__}")
        return None, notes
    if not feed.header.gtfs_realtime_version and not feed.entity:
        notes.append("protobuf parseó pero no hay header GTFS-RT ni entidades")
        return feed, notes
    notes.append("decodificación GTFS-Realtime (definiciones oficiales) correcta")
    return feed, notes


def main() -> int:
    _configure_stdout()
    print("Prueba API GTFS-Realtime Metrobús (sin exponer secretos)")

    if not ENV_PATH.is_file():
        return fail(".env no existe; no se intentará autenticar.")

    load_environment()
    missing = [name for name in REQUIRED_ENV if not env_present(name)]
    if missing:
        return fail("faltan variables de entorno: " + ", ".join(missing))

    response, net_code = authenticate()
    if response is None:
        return net_code

    print(f"  status HTTP: {response.status_code}")
    if not response.ok:
        print("  cuerpo de error (redactado):")
        print("   ", redact_error_body(response.text))
        return fail(f"autenticación rechazada (HTTP {response.status_code})")

    try:
        data = response.json()
    except json.JSONDecodeError:
        return fail("la respuesta no es JSON válido")

    if not isinstance(data, dict):
        return fail("la respuesta JSON no es un objeto")

    expected = ("generationDateTime", "expirationDateTime", "urlStatic", "urlRealTime")
    missing_keys = [key for key in expected if key not in data]
    if missing_keys:
        return fail("JSON sin claves: " + ", ".join(missing_keys))

    print("Respuesta de validación:")
    print(f"  generationDateTime: {data.get('generationDateTime')}")
    print(f"  expirationDateTime: {data.get('expirationDateTime')}")
    print_url_metadata("urlStatic", str(data["urlStatic"]))
    print_url_metadata("urlRealTime", str(data["urlRealTime"]))

    realtime_url = str(data["urlRealTime"])
    print("Descarga temporal de urlRealTime (URL no impresa).")
    try:
        download = requests.get(realtime_url, timeout=60)
    except requests.RequestException as exc:
        return fail(f"falló la descarga realtime: {type(exc).__name__}")

    print(f"  status descarga: {download.status_code}")
    print(f"  content-type: {download.headers.get('Content-Type', 'desconocido')}")
    print(f"  bytes: {len(download.content)}")
    if not download.ok:
        return fail(f"descarga realtime HTTP {download.status_code}")

    blob = download.content
    with tempfile.NamedTemporaryFile(prefix="gtfs_rt_", suffix=".proto", delete=True) as tmp:
        tmp.write(blob)
        tmp.flush()
        print("  archivo temporal escrito; se elimina al salir (no se versiona)")

    looks_proto = not blob.lstrip().startswith(b"{") and not blob.startswith(b"PK")
    print(f"¿Parece protobuf binario (no JSON/ZIP)? {'sí' if looks_proto else 'no'}")

    feed, notes = decode_feed(blob)
    for note in notes:
        print(f"  {note}")
    if feed is None:
        return fail("no se pudo decodificar GTFS-Realtime")

    header = feed.header
    print("Header GTFS-RT:")
    print(f"  gtfs_realtime_version: {header.gtfs_realtime_version or '(vacío)'}")
    if header.HasField("timestamp"):
        print(f"  timestamp: {header.timestamp}")
    if header.HasField("incrementality"):
        print(
            "  incrementality: "
            + gtfs_realtime_pb2.FeedHeader.Incrementality.Name(header.incrementality)
        )

    kinds = Counter()
    for entity in feed.entity:
        if entity.HasField("vehicle"):
            kinds["VehiclePosition"] += 1
        elif entity.HasField("trip_update"):
            kinds["TripUpdate"] += 1
        elif entity.HasField("alert"):
            kinds["Alert"] += 1
        else:
            kinds["otra"] += 1

    n_entities = len(feed.entity)
    print("Entidades:")
    print(f"  total: {n_entities}")
    print(f"  tipos presentes: {', '.join(sorted(kinds)) if kinds else '(ninguno)'}")
    print(f"  VehiclePosition: {'sí' if kinds['VehiclePosition'] else 'no'} ({kinds['VehiclePosition']})")
    print(f"  TripUpdate: {'sí' if kinds['TripUpdate'] else 'no'} ({kinds['TripUpdate']})")
    print(f"  Alert: {'sí' if kinds['Alert'] else 'no'} ({kinds['Alert']})")

    presence = vehicle_field_presence(feed)
    print("Campos VehiclePosition observados:")
    fields = presence.pop("vehicleposition_fields")
    if fields:
        for name in fields:
            print(f"  - {name}")
    else:
        print("  (no hay VehiclePosition)")
    print("Presencia de identificadores / telemetría en VehiclePosition:")
    for key in (
        "vehicle_id",
        "trip_id",
        "route_id",
        "stop_id",
        "timestamp",
        "latitude",
        "longitude",
        "current_stop_sequence",
        "current_status",
    ):
        print(f"  {key}: {'sí' if presence[key] else 'no'}")
    coverage = vehicle_field_coverage(feed)
    total = coverage["total"]

    print("Cobertura de campos VehiclePosition:")
    for field, count in coverage.items():
        if field == "total":
            continue
        pct = (count / total * 100) if total else 0
        print(f"  {field}: {count}/{total} ({pct:.1f}%)")
    print("Muestra anonimizada (máx. 3):")
    samples = anonymized_samples(feed, limit=3)
    if not samples:
        print("  (sin entidades para mostrar)")
    else:
        print(json.dumps(samples, ensure_ascii=False, indent=2))

    print("Cruce con Metrobus_GTFS_ESTATICO.zip:")
    try:
        static_ids = load_static_ids(STATIC_ZIP)
    except FileNotFoundError as exc:
        return fail(str(exc))

    rt_ids = collect_ids(feed)
    for key in ("route_id", "trip_id", "stop_id"):
        stats = match_rate(rt_ids[key], static_ids[key])
        pct = "n/a (0 en realtime)" if stats["porcentaje"] is None else f"{stats['porcentaje']:.1f}%"
        print(
            f"  {key}: realtime={stats['en_realtime']}; "
            f"estático={stats['en_estatico']}; cruzados={stats['cruzados']}; match={pct}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
