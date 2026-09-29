from pathlib import Path
import zipfile
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

GTFS_ZIP = ROOT / "data" / "raw" / "Metrobus_GTFS_ESTATICO.zip"
OUTPUT = ROOT / "data" / "processed"

OUTPUT.mkdir(parents=True, exist_ok=True)


def read_gtfs(zip_file, filename):
    with zipfile.ZipFile(zip_file) as z:
        with z.open(filename) as f:
            return pd.read_csv(f, dtype=str)


def main():
    print("Preparando GTFS estático de Metrobús...")

    routes = read_gtfs(GTFS_ZIP, "routes.txt")
    stops = read_gtfs(GTFS_ZIP, "stops.txt")
    trips = read_gtfs(GTFS_ZIP, "trips.txt")
    stop_times = read_gtfs(GTFS_ZIP, "stop_times.txt")
    shapes = read_gtfs(GTFS_ZIP, "shapes.txt")

    print(f"Rutas: {len(routes):,}")
    print(f"Paradas: {len(stops):,}")
    print(f"Viajes: {len(trips):,}")
    print(f"Stop times: {len(stop_times):,}")
    print(f"Puntos shapes: {len(shapes):,}")

    # -------------------------
    # RUTAS
    # -------------------------

    routes_clean = routes[
        [
            "route_id",
            "route_short_name",
            "route_long_name",
            "route_color",
            "route_text_color",
        ]
    ].copy()

    routes_clean = routes_clean.drop_duplicates("route_id")

    # -------------------------
    # PARADAS
    # -------------------------

    stops_clean = stops[
        [
            "stop_id",
            "stop_name",
            "stop_lat",
            "stop_lon",
        ]
    ].copy()

    stops_clean["stop_lat"] = pd.to_numeric(
        stops_clean["stop_lat"], errors="coerce"
    )

    stops_clean["stop_lon"] = pd.to_numeric(
        stops_clean["stop_lon"], errors="coerce"
    )

    stops_clean = stops_clean.dropna(
        subset=["stop_lat", "stop_lon"]
    )

    # -------------------------
    # SHAPES
    # -------------------------

    shapes_clean = shapes[
        [
            "shape_id",
            "shape_pt_lat",
            "shape_pt_lon",
            "shape_pt_sequence",
        ]
    ].copy()

    shapes_clean["shape_pt_lat"] = pd.to_numeric(
        shapes_clean["shape_pt_lat"], errors="coerce"
    )

    shapes_clean["shape_pt_lon"] = pd.to_numeric(
        shapes_clean["shape_pt_lon"], errors="coerce"
    )

    shapes_clean["shape_pt_sequence"] = pd.to_numeric(
        shapes_clean["shape_pt_sequence"], errors="coerce"
    )

    shapes_clean = shapes_clean.dropna(
        subset=[
            "shape_pt_lat",
            "shape_pt_lon",
            "shape_pt_sequence",
        ]
    )

    shapes_clean = shapes_clean.sort_values(
        ["shape_id", "shape_pt_sequence"]
    )

    # -------------------------
    # ROUTE -> SHAPE
    # -------------------------

    route_shapes = trips[
        [
            "route_id",
            "direction_id",
            "shape_id",
            "trip_headsign",
        ]
    ].drop_duplicates()

    # -------------------------
    # ROUTE -> STOPS
    # -------------------------

    trip_info = trips[
        [
            "trip_id",
            "route_id",
            "direction_id",
            "shape_id",
        ]
    ].copy()

    trip_stops = stop_times[
        [
            "trip_id",
            "stop_id",
            "stop_sequence",
        ]
    ].copy()

    route_stops = trip_stops.merge(
        trip_info,
        on="trip_id",
        how="inner",
    )

    route_stops = route_stops.merge(
        stops_clean,
        on="stop_id",
        how="left",
    )

    route_stops["stop_sequence"] = pd.to_numeric(
        route_stops["stop_sequence"],
        errors="coerce",
    )

    # Muchos viajes repiten exactamente la misma secuencia.
    # Para el MVP conservamos combinaciones únicas.
    route_stops = route_stops[
        [
            "route_id",
            "direction_id",
            "shape_id",
            "stop_id",
            "stop_name",
            "stop_lat",
            "stop_lon",
            "stop_sequence",
        ]
    ].drop_duplicates()

    route_stops = route_stops.sort_values(
        [
            "route_id",
            "direction_id",
            "stop_sequence",
        ]
    )

    # -------------------------
    # GUARDAR
    # -------------------------

    routes_clean.to_csv(
        OUTPUT / "routes.csv",
        index=False,
    )

    stops_clean.to_csv(
        OUTPUT / "stops.csv",
        index=False,
    )

    shapes_clean.to_csv(
        OUTPUT / "shapes.csv",
        index=False,
    )

    route_shapes.to_csv(
        OUTPUT / "route_shapes.csv",
        index=False,
    )

    route_stops.to_csv(
        OUTPUT / "route_stops.csv",
        index=False,
    )

    print()
    print("Archivos procesados creados:")
    print(f"  routes.csv: {len(routes_clean):,}")
    print(f"  stops.csv: {len(stops_clean):,}")
    print(f"  shapes.csv: {len(shapes_clean):,}")
    print(f"  route_shapes.csv: {len(route_shapes):,}")
    print(f"  route_stops.csv: {len(route_stops):,}")
    print()
    print(f"Directorio: {OUTPUT}")


if __name__ == "__main__":
    main()