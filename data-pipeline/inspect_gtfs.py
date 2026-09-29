"""Inspección de ZIPs GTFS en data/raw/ y del manual de integración.

No modifica los ZIP originales. No llama a la API. No imprime credenciales.
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
import zlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DOCS_DIR = ROOT / "docs"

GTFS_TARGETS = [
    "agency.txt",
    "routes.txt",
    "stops.txt",
    "trips.txt",
    "stop_times.txt",
    "shapes.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "frequencies.txt",
]

SECRET_PATTERNS = [
    re.compile(r'(?i)("(?:usuario|senha|password|passwd|token|secret|key)"\s*:\s*")[^"]+(")'),
    re.compile(r"(?i)(X-Amz-[A-Za-z-]+=)[^&\s\"]+"),
    re.compile(r"(?i)(AKIA[0-9A-Z]{16})"),
]


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def discover_zips(raw_dir: Path) -> list[Path]:
    return sorted(p for p in raw_dir.glob("*.zip") if p.is_file())


def zip_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [info for info in zf.infolist() if not info.is_dir()]


def member_basename(name: str) -> str:
    return Path(name.replace("\\", "/")).name.lower()


def find_member(zf: zipfile.ZipFile, filename: str) -> str | None:
    target = filename.lower()
    for info in zip_members(zf):
        if member_basename(info.filename) == target:
            return info.filename
    return None


def read_csv_from_zip(zf: zipfile.ZipFile, inner_name: str) -> pd.DataFrame:
    raw = zf.read(inner_name)
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            buffer = io.BytesIO(raw)
            return pd.read_csv(buffer, encoding=encoding, dtype=str, keep_default_na=True)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"No se pudo leer {inner_name}: {last_error}")


def profile_dataframe(df: pd.DataFrame) -> dict:
    inferred = df.copy()
    for column in inferred.columns:
        numeric = pd.to_numeric(inferred[column], errors="coerce")
        non_empty = inferred[column].notna() & (inferred[column].astype(str).str.strip() != "")
        if non_empty.any() and float(numeric[non_empty].notna().mean()) >= 0.9:
            inferred[column] = numeric
    nulls = df.isna() | df.map(lambda v: isinstance(v, str) and v.strip() == "")
    return {
        "n_records": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(inferred[c].dtype) for c in inferred.columns},
        "nulls": {str(c): int(nulls[c].sum()) for c in df.columns},
        "head": df.head(5),
    }


def print_profile(filename: str, present: bool, profile: dict | None = None) -> None:
    print(f"  --- {filename} ---")
    if not present:
        print("      ausente")
        return
    assert profile is not None
    print(f"      registros: {profile['n_records']}")
    print(f"      columnas: {', '.join(profile['columns'])}")
    print("      tipos inferidos:")
    for col, dtype in profile["dtypes"].items():
        print(f"        - {col}: {dtype}")
    print("      nulos / vacíos:")
    for col, n_null in profile["nulls"].items():
        print(f"        - {col}: {n_null}")
    print("      primeras 5 filas:")
    head = profile["head"].fillna("")
    print(head.to_string(index=False))


def looks_like_metrobus(agency_id: str, agency_name: str) -> bool:
    aid = str(agency_id).strip().lower()
    name = str(agency_name).strip().lower()
    folded = name.replace("ú", "u").replace("ü", "u")
    return aid in {"mb", "1339"} or "metrobus" in folded


def metrobus_agency_ids(agency_df: pd.DataFrame) -> list[str]:
    ids: list[str] = []
    for _, row in agency_df.iterrows():
        if looks_like_metrobus(row.get("agency_id", ""), row.get("agency_name", "")):
            ids.append(str(row["agency_id"]))
    return ids


def metrobus_metrics(tables: dict[str, pd.DataFrame]) -> dict:
    agency = tables.get("agency.txt")
    routes = tables.get("routes.txt")
    trips = tables.get("trips.txt")
    stops = tables.get("stops.txt")
    stop_times = tables.get("stop_times.txt")
    shapes = tables.get("shapes.txt")
    frequencies = tables.get("frequencies.txt")

    if agency is None or routes is None:
        return {"available": False, "reason": "Faltan agency.txt o routes.txt"}

    mb_ids = metrobus_agency_ids(agency)
    if not mb_ids:
        return {"available": False, "reason": "No se identificó agencia Metrobús"}

    agency_id_col = "agency_id" if "agency_id" in routes.columns else None
    if agency_id_col:
        mb_routes = routes[routes["agency_id"].astype(str).isin(mb_ids)]
    else:
        mb_routes = routes

    n_routes = int(mb_routes["route_id"].nunique()) if "route_id" in mb_routes.columns else int(len(mb_routes))

    if trips is not None and "route_id" in trips.columns:
        mb_trips = trips[trips["route_id"].astype(str).isin(mb_routes["route_id"].astype(str))]
        n_trips = int(mb_trips["trip_id"].nunique()) if "trip_id" in mb_trips.columns else int(len(mb_trips))
        trip_ids = set(mb_trips["trip_id"].astype(str)) if "trip_id" in mb_trips.columns else set()
    else:
        mb_trips = None
        n_trips = 0
        trip_ids = set()

    if stops is None:
        n_stops = 0
        stop_scope = "sin stops.txt"
    elif len(metrobus_agency_ids(agency)) == len(agency) or stop_times is None or mb_trips is None:
        n_stops = int(stops["stop_id"].nunique()) if "stop_id" in stops.columns else int(len(stops))
        stop_scope = "todas las paradas del feed (feed de un solo operador o sin cruce trip→stop)"
    else:
        mb_stop_times = stop_times[stop_times["trip_id"].astype(str).isin(trip_ids)]
        stop_ids = set(mb_stop_times["stop_id"].astype(str)) if "stop_id" in mb_stop_times.columns else set()
        n_stops = len(stop_ids)
        stop_scope = "paradas usadas por viajes Metrobús (cruce trips + stop_times)"

    has_stop_times = stop_times is not None and len(stop_times) > 0
    has_shapes = shapes is not None and len(shapes) > 0
    has_frequencies = frequencies is not None and len(frequencies) > 0

    if has_stop_times and trip_ids and "trip_id" in stop_times.columns:
        mb_st = stop_times[stop_times["trip_id"].astype(str).isin(trip_ids)]
        stop_times_for_mb = int(len(mb_st))
    else:
        stop_times_for_mb = int(len(stop_times)) if has_stop_times else 0

    if has_frequencies and mb_trips is not None and "trip_id" in frequencies.columns:
        freq_for_mb = int(frequencies["trip_id"].astype(str).isin(trip_ids).sum())
    else:
        freq_for_mb = int(len(frequencies)) if has_frequencies else 0

    shape_ids = set()
    if mb_trips is not None and "shape_id" in mb_trips.columns:
        shape_ids = {s for s in mb_trips["shape_id"].dropna().astype(str) if s.strip()}
    shapes_for_mb = 0
    if has_shapes and shape_ids and "shape_id" in shapes.columns:
        shapes_for_mb = int(shapes["shape_id"].astype(str).isin(shape_ids).sum())
    elif has_shapes:
        shapes_for_mb = int(len(shapes))

    return {
        "available": True,
        "agency_ids": mb_ids,
        "n_routes": n_routes,
        "n_stops": n_stops,
        "stop_scope": stop_scope,
        "n_trips": n_trips,
        "stop_times_available": has_stop_times,
        "stop_times_rows_metrobus": stop_times_for_mb,
        "shapes_available": has_shapes,
        "shapes_rows_metrobus": shapes_for_mb,
        "frequencies_available": has_frequencies,
        "frequencies_rows_metrobus": freq_for_mb,
    }


def extract_pdf_text(path: Path) -> str:
    data = path.read_bytes()
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        payload = match.group(1)
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            continue
        if payload[:4] in {b"cmap", b"OS/2"} or b"/Font" in payload[:80]:
            continue
        if payload.count(b"\x00") > max(20, len(payload) // 10):
            continue
        text = payload.decode("latin-1", errors="ignore")
        pieces = re.findall(r"\((?:\\.|[^\\)])*\)", text)
        if pieces:
            decoded = []
            for piece in pieces:
                inner = piece[1:-1]
                inner = inner.replace(r"\n", "\n").replace(r"\r", "\n")
                inner = inner.replace(r"\t", "\t").replace(r"\(", "(").replace(r"\)", ")")
                decoded.append(inner)
            joined = "".join(decoded)
            if any(c.isalpha() for c in joined):
                chunks.append(joined)
        else:
            printable = "".join(ch if 32 <= ord(ch) < 127 or ch in "\n\t" else " " for ch in text)
            if len(re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{4,}", printable)) >= 8:
                chunks.append(printable)
    return "\n".join(chunks)


def summarize_manual(pdf_path: Path) -> None:
    print("\n" + "=" * 80)
    print(f"MANUAL: {pdf_path.relative_to(ROOT)}")
    print("=" * 80)
    if not pdf_path.exists():
        print("No se encontró el PDF.")
        return

    text = redact(extract_pdf_text(pdf_path))
    urls = sorted(set(re.findall(r"https?://[^\s\"<>]+", text)))
    urls = [re.sub(r"(?i)([?&]X-Amz-[^=]+=)[^&\s]+", r"\1[REDACTED]", u) for u in urls]
    urls = [u for u in urls if "X-Amz-" not in u]

    print("Resumen técnico (sin credenciales, sin llamadas a la API):")
    print()
    print("Autenticación:")
    print("  - Un único endpoint de validación de partner.")
    print("  - Método HTTP: POST.")
    print("  - Cuerpo: JSON con campos de usuario y contraseña (nombres en el manual: usuario, senha).")
    print("  - No hay header de API key documentado; la autenticación va en el body.")
    print()
    print("Endpoint documentado:")
    for url in urls:
        if "gtfs-api" in url or "partnerValidation" in url:
            print(f"  - {url}")
    if not any("partnerValidation" in u for u in urls):
        print("  - https://metrobus-gtfs.sinopticoplus.com/gtfs-api/partnerValidation")
    print()
    print("Métodos HTTP:")
    print("  - POST al endpoint de validación.")
    print("  - Las URLs devueltas son de descarga (GET implícito sobre objetos firmados), no recursos REST adicionales.")
    print()
    print("Parámetros:")
    print("  - Body JSON de autenticación.")
    print("  - El manual no documenta query params, path params ni filtros por ruta/parada/viaje.")
    print()
    print("Formato de respuesta del POST:")
    print("  - JSON con:")
    print("      expirationDateTime  (caducidad de las URLs; 10 minutos tras generación)")
    print("      generationDateTime  (momento de generación)")
    print("      urlStatic           (ZIP GTFS estático en almacenamiento de objetos)")
    print("      urlRealTime         (archivo .proto GTFS realtime)")
    print("  - El ZIP estático se actualiza diariamente a medianoche.")
    print("  - El proto agrupa transmisiones de vehículos de los últimos 30 segundos.")
    print("  - Datos disponibles solo con el sistema cliente en operación.")
    print()
    print("Datos de vehículos / posiciones / timestamps / ETA:")
    print("  - El manual afirma que estático y realtime siguen el estándar GTFS de Google.")
    print("  - Realtime se describe como visibilidad de la posición actual de vehículos (últimos 30 s), en .proto.")
    print("  - No documenta campos protobuf (VehiclePosition, TripUpdate, Alert).")
    print("  - No documenta ETA ni llegadas (arrival_time / departure_time / delay / stop_time_update).")
    print("  - No documenta timestamps de vehículo más allá de generationDateTime / expirationDateTime.")
    print("  - No documenta route_id, trip_id ni stop_id en la respuesta JSON ni en el proto.")
    print()
    print("Identificadores para relacionar realtime con GTFS estático:")
    print("  - El mismo POST entrega urlStatic y urlRealTime, así que el cruce esperado es el de GTFS-RT:")
    print("      trip_id, route_id, stop_id, vehicle.id, start_date, direction_id, shape_id.")
    print("  - En el ejemplo del manual, el ZIP estático vive bajo un identificador numérico de agencia")
    print("    (1339), coherente con agency_id del feed estático de Metrobús/Sonda, no con agency_id 'MB'")
    print("    del feed metropolitano.")
    print("  - Hasta inspeccionar el .proto, no hay evidencia de un endpoint de ETA por parada.")
    print()
    print("Texto extraído del PDF (redactado):")
    preview = re.sub(r"[ \t]+", " ", text)
    preview = re.sub(r"\n{3,}", "\n\n", preview).strip()
    if len(preview) > 2500:
        preview = preview[:2500] + "\n... [truncado]"
    print(preview if preview else "(no se pudo extraer texto)")


def inspect_zip(path: Path) -> dict:
    print("\n" + "=" * 80)
    print(f"ZIP: {path.name}")
    print(f"ruta: {path}")
    print(f"tamaño_bytes: {path.stat().st_size}")
    print("=" * 80)

    tables: dict[str, pd.DataFrame] = {}
    present_targets: list[str] = []
    extra_files: list[str] = []

    with zipfile.ZipFile(path) as zf:
        members = zip_members(zf)
        print("Contenido (sin extraer a disco):")
        for info in members:
            print(f"  {info.filename}  bytes={info.file_size}  comprimido={info.compress_size}")
            base = member_basename(info.filename)
            if base not in {t.lower() for t in GTFS_TARGETS} and base.endswith(".txt"):
                extra_files.append(info.filename)

        print("\nArchivos GTFS objetivo:")
        for target in GTFS_TARGETS:
            inner = find_member(zf, target)
            if inner is None:
                print_profile(target, present=False)
                continue
            present_targets.append(target)
            df = read_csv_from_zip(zf, inner)
            tables[target] = df
            print_profile(target, present=True, profile=profile_dataframe(df))

        if extra_files:
            print("\nOtros .txt en el ZIP:")
            for extra in extra_files:
                df = read_csv_from_zip(zf, extra)
                tables[Path(extra).name.lower()] = df
                print_profile(Path(extra).name, present=True, profile=profile_dataframe(df))

    agency = tables.get("agency.txt")
    print("\nAgencias / operadores:")
    if agency is None:
        print("  agency.txt ausente")
        n_agencies = 0
        agency_ids: list[str] = []
    else:
        n_agencies = int(len(agency))
        agency_ids = [str(v) for v in agency.get("agency_id", pd.Series(dtype=str)).tolist()]
        cols = [c for c in ["agency_id", "agency_name", "agency_url"] if c in agency.columns]
        print(agency[cols].fillna("").to_string(index=False))

    mb_ids = metrobus_agency_ids(agency) if agency is not None else []
    only_metrobus = bool(mb_ids) and n_agencies == 1
    multi_system = n_agencies > 1

    print("\nClasificación del feed:")
    if only_metrobus:
        print("  Un solo operador: Metrobús.")
    elif multi_system and mb_ids:
        print("  Múltiples sistemas de transporte; incluye Metrobús.")
    elif multi_system:
        print("  Múltiples sistemas de transporte; no se identificó Metrobús.")
    else:
        print("  No se pudo clasificar con agency.txt.")

    metrics = metrobus_metrics(tables)
    print("\nMétricas Metrobús:")
    if not metrics.get("available"):
        print(f"  {metrics.get('reason')}")
    else:
        print(f"  agency_id(s): {', '.join(metrics['agency_ids'])}")
        print(f"  rutas: {metrics['n_routes']}")
        print(f"  paradas: {metrics['n_stops']} ({metrics['stop_scope']})")
        print(f"  viajes: {metrics['n_trips']}")
        print(f"  stop_times: {'sí' if metrics['stop_times_available'] else 'no'} (filas MB={metrics['stop_times_rows_metrobus']})")
        print(f"  shapes: {'sí' if metrics['shapes_available'] else 'no'} (filas MB={metrics['shapes_rows_metrobus']})")
        print(f"  frequencies: {'sí' if metrics['frequencies_available'] else 'no'} (filas MB={metrics['frequencies_rows_metrobus']})")

    return {
        "name": path.name,
        "n_agencies": n_agencies,
        "agency_ids": agency_ids,
        "only_metrobus": only_metrobus,
        "multi_system": multi_system,
        "present_targets": present_targets,
        "metrics": metrics,
        "has_feed_info": "feed_info.txt" in tables,
    }


def print_comparison(summaries: list[dict]) -> None:
    print("\n" + "=" * 80)
    print("COMPARACIÓN")
    print("=" * 80)
    if not summaries:
        print("No hay ZIPs para comparar.")
        return

    by_name = {s["name"]: s for s in summaries}
    for summary in summaries:
        kind = "solo Metrobús" if summary["only_metrobus"] else (
            "múltiples sistemas" if summary["multi_system"] else "sin clasificar"
        )
        print(f"- {summary['name']}: {kind}; agencias={summary['n_agencies']}; "
              f"tablas={', '.join(summary['present_targets'])}")

    metrobus_only = [s for s in summaries if s["only_metrobus"]]
    citywide = [s for s in summaries if s["multi_system"]]
    print()
    if metrobus_only:
        print(f"Feed solo Metrobús: {metrobus_only[0]['name']}")
    if citywide:
        print(f"Feed multi-sistema CDMX: {citywide[0]['name']}")

    print()
    print("Recomendación técnica para el MVP:")
    if metrobus_only:
        chosen = metrobus_only[0]["name"]
        print(f"  Usar {chosen} como base estática del MVP.")
        print("  Razones:")
        print("  - El manual de la API Metrobús/Sonda entrega un ZIP estático del mismo operador")
        print("    (agency_id 1339 en el ejemplo de urlStatic), alineado con este feed y no con 'MB'.")
        print("  - Los trip_id / route_id / stop_id del GTFS-RT deben cruzarse con el estático")
        print("    generado por el mismo sistema, no con el catálogo metropolitano.")
        print("  - El feed de un solo operador evita mezclar Metro, RTP, Cablebús, etc. en un MVP de bus.")
        other = citywide[0]["name"] if citywide else None
        if other:
            print(f"  Conservar {other} como referencia territorial (cobertura multi-modo), no como")
            print("  catálogo de IDs para el realtime de Metrobús.")
    elif "Metrobus_GTFS_ESTATICO.zip" in by_name:
        print("  Usar Metrobus_GTFS_ESTATICO.zip por coincidencia de nombre y origen con la API.")
    else:
        print("  No hay un ZIP inequívoco solo-Metrobús; revisar agency.txt antes de fijar IDs.")


def main() -> int:
    _configure_stdout()
    print("Inspección GTFS (solo lectura)")
    print(f"Directorio: {RAW_DIR}")

    zips = discover_zips(RAW_DIR)
    if not zips:
        print("No se encontraron archivos ZIP en data/raw/.")
        return 1

    print(f"ZIPs detectados ({len(zips)}):")
    for path in zips:
        print(f"  - {path.name} ({path.stat().st_size} bytes)")

    summaries = [inspect_zip(path) for path in zips]

    pdf_path = DOCS_DIR / "manual_integracion_gtfs.pdf"
    summarize_manual(pdf_path)
    print_comparison(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
