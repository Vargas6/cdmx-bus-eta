from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"

MAX_VEHICLE_DISTANCE_TO_SHAPE_M = 100
MAX_STOP_DISTANCE_TO_SHAPE_M = 100


def main():
    print("Asignando próxima parada según sentido real")
    print("-------------------------------------------")

    vehicles = pd.read_csv(
        DATA / "realtime_matched.csv",
        dtype={
            "route_id": str,
            "shape_id": str,
            "vehicle_id": str,
        },
    )

    stops = pd.read_csv(
        DATA / "route_stops_mapped.csv",
        dtype={
            "route_id": str,
            "shape_id": str,
            "stop_id": str,
        },
    )

    directions = pd.read_csv(
        DATA / "route_direction_diagnostic.csv",
        dtype={"route_id": str},
    )

    print(f"Observaciones recibidas: {len(vehicles):,}")

    # -------------------------------------------------
    # Calidad del map matching
    # -------------------------------------------------

    vehicles = vehicles[
        vehicles["distance_to_shape_m"]
        <= MAX_VEHICLE_DISTANCE_TO_SHAPE_M
    ].copy()

    stops = stops[
        stops["distance_to_shape_m"]
        <= MAX_STOP_DISTANCE_TO_SHAPE_M
    ].copy()

    print(
        f"Observaciones <=100 m del recorrido: "
        f"{len(vehicles):,}"
    )

    # -------------------------------------------------
    # Nos quedamos solo con rutas cuyo sentido
    # pudimos determinar.
    # -------------------------------------------------

    directions = directions[
        directions["observed_direction"].isin(
            ["increasing", "decreasing"]
        )
    ].copy()

    direction_map = dict(
        zip(
            directions["route_id"],
            directions["observed_direction"],
        )
    )

    print(
        f"Rutas con sentido identificado: "
        f"{len(direction_map):,}"
    )

    # -------------------------------------------------
    # Evitar duplicados exactos de parada
    # -------------------------------------------------

    stops = (
        stops.sort_values(
            [
                "route_id",
                "shape_id",
                "stop_progress_m",
            ]
        )
        .drop_duplicates(
            [
                "route_id",
                "shape_id",
                "stop_id",
            ]
        )
    )

    # Cache de paradas por recorrido
    stop_cache = {}

    for (route_id, shape_id), group in stops.groupby(
        ["route_id", "shape_id"]
    ):
        stop_cache[
            (str(route_id), str(shape_id))
        ] = group.copy()

    results = []

    # -------------------------------------------------
    # Buscar siguiente parada
    # -------------------------------------------------

    for n, row in enumerate(
        vehicles.to_dict("records"),
        start=1,
    ):
        route_id = str(row["route_id"])
        shape_id = str(row["shape_id"])

        observed_direction = direction_map.get(
            route_id
        )

        if observed_direction is None:
            continue

        route_stops = stop_cache.get(
            (route_id, shape_id)
        )

        if route_stops is None or route_stops.empty:
            continue

        current_progress = float(
            row["progress_m"]
        )

        # ---------------------------------------------
        # Si el vehículo avanza aumentando progress
        # ---------------------------------------------

        if observed_direction == "increasing":

            upcoming = route_stops[
                route_stops["stop_progress_m"]
                > current_progress
            ].copy()

            if upcoming.empty:
                continue

            next_stop = upcoming.sort_values(
                "stop_progress_m",
                ascending=True,
            ).iloc[0]

            remaining_distance = (
                float(next_stop["stop_progress_m"])
                - current_progress
            )

        # ---------------------------------------------
        # Si el vehículo avanza disminuyendo progress
        # ---------------------------------------------

        else:

            upcoming = route_stops[
                route_stops["stop_progress_m"]
                < current_progress
            ].copy()

            if upcoming.empty:
                continue

            next_stop = upcoming.sort_values(
                "stop_progress_m",
                ascending=False,
            ).iloc[0]

            remaining_distance = (
                current_progress
                - float(next_stop["stop_progress_m"])
            )

        results.append(
            {
                "collected_at":
                    row["collected_at"],

                "vehicle_timestamp":
                    row["vehicle_timestamp"],

                "vehicle_id":
                    row["vehicle_id"],

                "route_id":
                    route_id,

                "direction_id":
                    row["direction_id"],

                "shape_id":
                    shape_id,

                "observed_direction":
                    observed_direction,

                "latitude":
                    row["latitude"],

                "longitude":
                    row["longitude"],

                "speed":
                    row["speed"],

                "bearing":
                    row["bearing"],

                "progress_m":
                    current_progress,

                "progress_pct":
                    row["progress_pct"],

                "distance_to_shape_m":
                    row["distance_to_shape_m"],

                "next_stop_id":
                    next_stop["stop_id"],

                "next_stop_name":
                    next_stop["stop_name"],

                "next_stop_progress_m":
                    next_stop["stop_progress_m"],

                "distance_to_next_stop_m":
                    round(
                        remaining_distance,
                        2,
                    ),
            }
        )

        if n % 5000 == 0:
            print(
                f"Procesadas "
                f"{n:,}/{len(vehicles):,}"
            )

    assigned = pd.DataFrame(results)

    output = DATA / "vehicles_next_stop.csv"

    assigned.to_csv(
        output,
        index=False,
    )

    print()
    print(
        f"Observaciones con próxima parada: "
        f"{len(assigned):,}"
    )

    if not assigned.empty:

        coverage = (
            len(assigned)
            / len(vehicles)
            * 100
        )

        print(
            f"Cobertura sobre observaciones válidas: "
            f"{coverage:.1f}%"
        )

        print()
        print("Sentido observado:")
        print(
            assigned[
                "observed_direction"
            ].value_counts().to_string()
        )

        print()
        print("Distancia a próxima parada:")
        print(
            assigned[
                "distance_to_next_stop_m"
            ]
            .describe(
                percentiles=[
                    .25,
                    .50,
                    .75,
                    .90,
                    .95,
                    .99,
                ]
            )
            .round(1)
        )

        print()
        print("Ejemplos:")
        print(
            assigned[
                [
                    "route_id",
                    "observed_direction",
                    "progress_pct",
                    "next_stop_name",
                    "distance_to_next_stop_m",
                ]
            ]
            .head(15)
            .to_string(index=False)
        )

    print()
    print(f"Guardado en: {output}")


if __name__ == "__main__":
    main()