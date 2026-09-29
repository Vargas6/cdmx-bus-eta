from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"

MAX_DISTANCE_TO_STOP_M = 3000
MAX_GAP_SECONDS = 180
MAX_ETA_MINUTES = 20

# Para aceptar una transición como llegada,
# la última observación de la parada anterior
# debe estar razonablemente cerca.
ARRIVAL_ZONE_M = 250

# Permitimos pequeños aumentos por ruido del GPS/matching.
DISTANCE_TOLERANCE_M = 100


def main():
    print("Construyendo dataset supervisado de ETA")
    print("--------------------------------------")

    df = pd.read_csv(
        DATA / "vehicles_next_stop.csv",
        dtype={
            "vehicle_id": str,
            "route_id": str,
            "shape_id": str,
            "next_stop_id": str,
        },
    )

    print(f"Observaciones recibidas: {len(df):,}")

    df["collected_at"] = pd.to_datetime(
        df["collected_at"],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "collected_at",
            "vehicle_id",
            "route_id",
            "next_stop_id",
            "distance_to_next_stop_m",
        ]
    ).copy()

    df = df[
        (df["distance_to_next_stop_m"] > 0)
        & (
            df["distance_to_next_stop_m"]
            <= MAX_DISTANCE_TO_STOP_M
        )
    ].copy()

    # Evitamos snapshots repetidos.
    df = df.sort_values(
        [
            "vehicle_id",
            "route_id",
            "collected_at",
        ]
    )

    df = df.drop_duplicates(
        subset=[
            "vehicle_id",
            "route_id",
            "vehicle_timestamp",
        ],
        keep="last",
    ).copy()

    print(
        f"Observaciones después de filtros: "
        f"{len(df):,}"
    )

    # Variables temporales
    df["hour"] = df["collected_at"].dt.hour
    df["minute"] = df["collected_at"].dt.minute
    df["weekday"] = df["collected_at"].dt.dayofweek

    df["hour_decimal"] = (
        df["hour"]
        + df["minute"] / 60
    )

    # -------------------------------------------------
    # Crear segmentos continuos
    # -------------------------------------------------

    group_cols = [
        "vehicle_id",
        "route_id",
    ]

    df["previous_time"] = (
        df.groupby(group_cols)["collected_at"]
        .shift(1)
    )

    df["gap_seconds"] = (
        df["collected_at"]
        - df["previous_time"]
    ).dt.total_seconds()

    df["new_segment"] = (
        df["previous_time"].isna()
        | (df["gap_seconds"] <= 0)
        | (df["gap_seconds"] > MAX_GAP_SECONDS)
    )

    df["segment_id"] = (
        df.groupby(group_cols)["new_segment"]
        .cumsum()
    )

    samples = []

    groups = df.groupby(
        [
            "vehicle_id",
            "route_id",
            "segment_id",
        ]
    )

    total_groups = groups.ngroups

    print(f"Segmentos temporales: {total_groups:,}")

    accepted_transitions = 0
    rejected_far = 0

    # -------------------------------------------------
    # Analizar cada trayectoria continua
    # -------------------------------------------------

    for n, (_, group) in enumerate(
        groups,
        start=1,
    ):
        group = (
            group.sort_values("collected_at")
            .reset_index(drop=True)
        )

        if len(group) < 2:
            continue

        # Identificar bloques consecutivos de
        # la misma próxima parada.
        block_start = 0

        while block_start < len(group) - 1:

            current_stop = str(
                group.iloc[block_start]["next_stop_id"]
            )

            block_end = block_start

            while (
                block_end + 1 < len(group)
                and str(
                    group.iloc[
                        block_end + 1
                    ]["next_stop_id"]
                )
                == current_stop
            ):
                block_end += 1

            # Si no hay una observación posterior,
            # no sabemos cuándo llegó.
            if block_end + 1 >= len(group):
                break

            last_before_change = group.iloc[block_end]
            first_after_change = group.iloc[block_end + 1]

            # Verificar que el cambio ocurrió con
            # continuidad temporal.
            transition_gap = (
                first_after_change["collected_at"]
                - last_before_change["collected_at"]
            ).total_seconds()

            if (
                transition_gap <= 0
                or transition_gap > MAX_GAP_SECONDS
            ):
                block_start = block_end + 1
                continue

            # La parada anterior debe haber estado
            # suficientemente cerca antes del cambio.
            last_distance = float(
                last_before_change[
                    "distance_to_next_stop_m"
                ]
            )

            if last_distance > ARRIVAL_ZONE_M:
                rejected_far += 1
                block_start = block_end + 1
                continue

            accepted_transitions += 1

            # Aproximamos la llegada en el punto medio
            # entre el último snapshot antes del cambio
            # y el primero después del cambio.
            arrival_time = (
                last_before_change["collected_at"]
                + (
                    first_after_change["collected_at"]
                    - last_before_change["collected_at"]
                ) / 2
            )

            # -------------------------------------------------
            # Generar ejemplos pertenecientes al bloque
            # -------------------------------------------------

            previous_distance = None

            for i in range(block_start, block_end + 1):

                row = group.iloc[i]

                distance = float(
                    row["distance_to_next_stop_m"]
                )

                eta_minutes = (
                    arrival_time
                    - row["collected_at"]
                ).total_seconds() / 60

                if (
                    eta_minutes <= 0
                    or eta_minutes > MAX_ETA_MINUTES
                ):
                    continue

                # Si la distancia creció demasiado respecto
                # al snapshot anterior, puede ser ruido.
                if previous_distance is not None:
                    if (
                        distance
                        > previous_distance
                        + DISTANCE_TOLERANCE_M
                    ):
                        previous_distance = distance
                        continue

                samples.append(
                    {
                        "collected_at":
                            row["collected_at"],

                        "vehicle_id":
                            row["vehicle_id"],

                        "route_id":
                            row["route_id"],

                        "direction_id":
                            row["direction_id"],

                        "shape_id":
                            row["shape_id"],

                        "observed_direction":
                            row["observed_direction"],

                        "next_stop_id":
                            row["next_stop_id"],

                        "next_stop_name":
                            row["next_stop_name"],

                        "progress_m":
                            row["progress_m"],

                        "progress_pct":
                            row["progress_pct"],

                        "distance_to_next_stop_m":
                            distance,

                        "reported_speed":
                            row["speed"],

                        "hour":
                            row["hour"],

                        "hour_decimal":
                            row["hour_decimal"],

                        "weekday":
                            row["weekday"],

                        "eta_real_minutes":
                            round(eta_minutes, 3),
                    }
                )

                previous_distance = distance

            block_start = block_end + 1

        if n % 1000 == 0:
            print(
                f"Segmentos procesados: "
                f"{n:,}/{total_groups:,}"
            )

    eta = pd.DataFrame(samples)

    output = DATA / "eta_dataset.csv"

    eta.to_csv(output, index=False)

    print()
    print(
        f"Transiciones aceptadas: "
        f"{accepted_transitions:,}"
    )
    print(
        f"Transiciones rechazadas por distancia: "
        f"{rejected_far:,}"
    )
    print()
    print(f"Muestras ETA creadas: {len(eta):,}")

    if not eta.empty:

        print(
            f"Vehículos: "
            f"{eta['vehicle_id'].nunique():,}"
        )
        print(
            f"Rutas: "
            f"{eta['route_id'].nunique():,}"
        )
        print(
            f"Paradas: "
            f"{eta['next_stop_id'].nunique():,}"
        )

        print()
        print("ETA real (minutos):")
        print(
            eta["eta_real_minutes"]
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
            .round(2)
        )

        print()
        print("Distancia a parada:")
        print(
            eta["distance_to_next_stop_m"]
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
        print("Correlación distancia vs ETA:")
        print(
            round(
                eta[
                    [
                        "distance_to_next_stop_m",
                        "eta_real_minutes",
                    ]
                ]
                .corr()
                .iloc[0, 1],
                3,
            )
        )

        print()
        print("Muestras por hora:")
        print(
            eta.groupby("hour")
            .size()
            .to_string()
        )

        print()
        print("Ejemplos:")
        print(
            eta[
                [
                    "route_id",
                    "next_stop_name",
                    "distance_to_next_stop_m",
                    "hour_decimal",
                    "eta_real_minutes",
                ]
            ]
            .head(15)
            .to_string(index=False)
        )

    print()
    print(f"Guardado en: {output}")


if __name__ == "__main__":
    main()