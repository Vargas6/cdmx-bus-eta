from pathlib import Path
import math
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"


def haversine(lat1, lon1, lat2, lon2):
    """Distancia aproximada entre dos coordenadas en metros."""

    R = 6_371_000

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

    return 2 * R * math.asin(math.sqrt(a))


def main():

    routes = pd.read_csv(DATA / "routes.csv", dtype={"route_id": str})
    shapes = pd.read_csv(DATA / "shapes.csv", dtype={"shape_id": str})
    route_shapes = pd.read_csv(
        DATA / "route_shapes.csv",
        dtype={
            "route_id": str,
            "shape_id": str,
            "direction_id": str,
        },
    )

    route_stops = pd.read_csv(
        DATA / "route_stops.csv",
        dtype={
            "route_id": str,
            "shape_id": str,
            "direction_id": str,
            "stop_id": str,
        },
    )

    print("Validación estática para map matching")
    print("------------------------------------")

    # 1. Cobertura route -> shape
    routes_with_shape = set(route_shapes["route_id"].dropna())
    all_routes = set(routes["route_id"].dropna())

    matched = len(all_routes & routes_with_shape)

    print(
        f"Rutas con shape: "
        f"{matched}/{len(all_routes)} "
        f"({matched / len(all_routes) * 100:.1f}%)"
    )

    # 2. Shapes existentes
    available_shapes = set(shapes["shape_id"].dropna())
    requested_shapes = set(route_shapes["shape_id"].dropna())

    matched_shapes = len(
        available_shapes & requested_shapes
    )

    print(
        f"Shapes encontrados: "
        f"{matched_shapes}/{len(requested_shapes)} "
        f"({matched_shapes / len(requested_shapes) * 100:.1f}%)"
    )

    # 3. Distancia parada -> shape
    distances = []

    for _, stop in route_stops.iterrows():

        shape_id = stop["shape_id"]

        shape = shapes[
            shapes["shape_id"] == shape_id
        ]

        if shape.empty:
            continue

        stop_lat = float(stop["stop_lat"])
        stop_lon = float(stop["stop_lon"])

        minimum = float("inf")

        for _, point in shape.iterrows():

            distance = haversine(
                stop_lat,
                stop_lon,
                float(point["shape_pt_lat"]),
                float(point["shape_pt_lon"]),
            )

            if distance < minimum:
                minimum = distance

        distances.append(minimum)

    if distances:
        series = pd.Series(distances)

        print()
        print("Distancia parada → recorrido:")
        print(f"  mediana: {series.median():.1f} m")
        print(f"  promedio: {series.mean():.1f} m")
        print(f"  p90: {series.quantile(0.90):.1f} m")
        print(f"  máximo: {series.max():.1f} m")

        close = (series <= 100).mean() * 100

        print(
            f"  paradas a <=100 m del shape: "
            f"{close:.1f}%"
        )

    print()
    print("Validación terminada.")


if __name__ == "__main__":
    main()