from pathlib import Path
import math
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"


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


def prepare_shapes(shapes):
    result = {}

    for shape_id, group in shapes.groupby("shape_id"):
        group = (
            group
            .sort_values("shape_pt_sequence")
            .copy()
        )

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

        result[str(shape_id)] = group

    return result


def nearest_shape_point(lat, lon, shape):
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
    print("Mapeando paradas a recorridos")
    print("-----------------------------")

    shapes = pd.read_csv(
        DATA / "shapes.csv",
        dtype={"shape_id": str},
    )

    route_stops = pd.read_csv(
        DATA / "route_stops.csv",
        dtype={
            "route_id": str,
            "shape_id": str,
            "stop_id": str,
        },
    )

    shape_cache = prepare_shapes(shapes)

    results = []

    for n, row in enumerate(
        route_stops.to_dict("records"),
        start=1,
    ):
        shape_id = str(row["shape_id"])

        shape = shape_cache.get(shape_id)

        if shape is None or shape.empty:
            continue

        index, distance = nearest_shape_point(
            float(row["stop_lat"]),
            float(row["stop_lon"]),
            shape,
        )

        matched_point = shape.loc[index]

        results.append(
            {
                "route_id": row["route_id"],
                "direction_id": row["direction_id"],
                "shape_id": shape_id,
                "stop_id": row["stop_id"],
                "stop_name": row["stop_name"],
                "stop_lat": row["stop_lat"],
                "stop_lon": row["stop_lon"],
                "stop_sequence": row["stop_sequence"],
                "shape_pt_sequence": int(
                    matched_point["shape_pt_sequence"]
                ),
                "stop_progress_m": round(
                    float(
                        matched_point[
                            "shape_distance_m"
                        ]
                    ),
                    2,
                ),
                "distance_to_shape_m": round(
                    distance,
                    2,
                ),
            }
        )

        if n % 500 == 0:
            print(
                f"Procesadas {n:,}/{len(route_stops):,}"
            )

    mapped = pd.DataFrame(results)

    output = DATA / "route_stops_mapped.csv"

    mapped.to_csv(
        output,
        index=False,
    )

    print()
    print(f"Paradas mapeadas: {len(mapped):,}")

    print()
    print("Distancia parada -> shape:")
    print(
        f"  mediana: "
        f"{mapped['distance_to_shape_m'].median():.1f} m"
    )
    print(
        f"  promedio: "
        f"{mapped['distance_to_shape_m'].mean():.1f} m"
    )
    print(
        f"  p90: "
        f"{mapped['distance_to_shape_m'].quantile(.90):.1f} m"
    )

    within_100 = (
        mapped["distance_to_shape_m"] <= 100
    ).mean() * 100

    print(
        f"  <=100 m: {within_100:.1f}%"
    )

    print()
    print(f"Guardado en: {output}")


if __name__ == "__main__":
    main()