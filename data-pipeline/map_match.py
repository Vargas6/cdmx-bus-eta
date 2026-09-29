from pathlib import Path
import math

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

RAW_REALTIME = ROOT / "data" / "raw" / "realtime"
PROCESSED = ROOT / "data" / "processed"


def haversine(lat1, lon1, lat2, lon2):
    """Distancia entre dos coordenadas en metros."""
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


def load_realtime():
    files = list(RAW_REALTIME.glob("*.csv"))

    if not files:
        raise FileNotFoundError(
            "No se encontraron archivos realtime."
        )

    frames = [pd.read_csv(file) for file in files]

    return pd.concat(frames, ignore_index=True)


def prepare_shapes(shapes):
    """Precalcula distancia acumulada sobre cada shape."""

    result = {}

    for shape_id, group in shapes.groupby("shape_id"):

        group = group.sort_values(
            "shape_pt_sequence"
        ).copy()

        cumulative = [0.0]

        rows = group.to_dict("records")

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

        result[str(shape_id)] = group

    return result


def nearest_shape_point(lat, lon, shape):
    """Encuentra el punto del shape más cercano."""

    best_index = None
    best_distance = float("inf")

    for index, point in shape.iterrows():

        distance = haversine(
            lat,
            lon,
            point["shape_pt_lat"],
            point["shape_pt_lon"],
        )

        if distance < best_distance:
            best_distance = distance
            best_index = index

    return best_index, best_distance


def main():

    print("Map matching Metrobús")
    print("---------------------")

    realtime = load_realtime()

    shapes = pd.read_csv(
        PROCESSED / "shapes.csv",
        dtype={"shape_id": str},
    )

    route_shapes = pd.read_csv(
        PROCESSED / "route_shapes.csv",
        dtype={
            "route_id": str,
            "direction_id": str,
            "shape_id": str,
        },
    )

    realtime["route_id"] = (
        realtime["route_id"]
        .astype("Int64")
        .astype(str)
        .replace("<NA>", pd.NA)
    )

    realtime["direction_id"] = (
        realtime["direction_id"]
        .astype("Int64")
        .astype(str)
        .replace("<NA>", pd.NA)
    )

    # Para esta etapa solo podemos usar observaciones
    # que tengan ruta, dirección y coordenadas.
    # Para el map matching necesitamos ruta y coordenadas.
    # direction_id se conserva como dato, pero no se usa
    # como llave contra el GTFS estático.
    usable = realtime.dropna(
        subset=[
            "route_id",
            "latitude",
            "longitude",
        ]
    ).copy()

    print(f"Observaciones realtime: {len(realtime):,}")
    print(f"Utilizables para matching: {len(usable):,}")

        # En este feed estático, cada route_id ya representa
    # una variante concreta del recorrido.
    # El direction_id realtime NO se usa como llave,
    # porque el estático lo reporta siempre como 0.
    mapping = (
        route_shapes[
            [
                "route_id",
                "shape_id",
            ]
        ]
        .drop_duplicates("route_id")
    )

    usable = usable.merge(
        mapping,
        on="route_id",
        how="left",
    )   

    print(
        f"Con shape identificado: "
        f"{usable['shape_id'].notna().sum():,}"
    )

    usable = usable.dropna(
        subset=["shape_id"]
    ).copy()

    shape_cache = prepare_shapes(shapes)

    results = []

    for n, row in enumerate(
        usable.to_dict("records"),
        start=1,
    ):
        shape_id = str(row["shape_id"])

        shape = shape_cache.get(shape_id)

        if shape is None or shape.empty:
            continue

        index, distance_to_shape = nearest_shape_point(
            float(row["latitude"]),
            float(row["longitude"]),
            shape,
        )

        matched_point = shape.loc[index]

        route_length = float(
            shape["shape_distance_m"].iloc[-1]
        )

        progress_m = float(
            matched_point["shape_distance_m"]
        )

        if route_length > 0:
            progress_pct = (
                progress_m / route_length * 100
            )
        else:
            progress_pct = 0.0

        results.append(
            {
                "collected_at": row["collected_at"],
                "vehicle_timestamp": row["vehicle_timestamp"],
                "vehicle_id": row["vehicle_id"],
                "route_id": row["route_id"],
                "direction_id": row["direction_id"],
                "shape_id": shape_id,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "speed": row["speed"],
                "bearing": row["bearing"],
                "odometer": row["odometer"],
                "shape_pt_sequence": int(
                    matched_point["shape_pt_sequence"]
                ),
                "distance_to_shape_m": round(
                    distance_to_shape, 2
                ),
                "progress_m": round(
                    progress_m, 2
                ),
                "route_length_m": round(
                    route_length, 2
                ),
                "progress_pct": round(
                    progress_pct, 2
                ),
            }
        )

        if n % 500 == 0:
            print(
                f"Procesadas {n:,}/{len(usable):,}"
            )

    matched = pd.DataFrame(results)

    output = PROCESSED / "realtime_matched.csv"

    matched.to_csv(
        output,
        index=False,
    )

    print()
    print(f"Observaciones matched: {len(matched):,}")

    if len(matched):

        print()
        print("Distancia vehículo -> shape:")
        print(
            f"  mediana: "
            f"{matched['distance_to_shape_m'].median():.1f} m"
        )
        print(
            f"  promedio: "
            f"{matched['distance_to_shape_m'].mean():.1f} m"
        )
        print(
            f"  p90: "
            f"{matched['distance_to_shape_m'].quantile(0.90):.1f} m"
        )

        within_100 = (
            matched["distance_to_shape_m"] <= 100
        ).mean() * 100

        print(
            f"  <=100 m: {within_100:.1f}%"
        )

        print()
        print("Progreso sobre ruta:")
        print(
            matched["progress_pct"]
            .describe()
            .round(2)
        )

    print()
    print(f"Guardado en: {output}")


if __name__ == "__main__":
    main()