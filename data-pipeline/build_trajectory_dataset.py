from pathlib import Path
import pandas as pd
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"

MAX_DISTANCE_TO_SHAPE_M = 100
MAX_TIME_GAP_SECONDS = 180
MAX_PLAUSIBLE_SPEED_KMH = 100


def main():
    print("Construyendo dataset de trayectorias")
    print("------------------------------------")

    df = pd.read_csv(
        DATA / "realtime_matched.csv",
        dtype={
            "vehicle_id": str,
            "route_id": str,
            "shape_id": str,
        },
    )

    print(f"Observaciones recibidas: {len(df):,}")

    # Solo map matching de buena calidad
    df = df[
        df["distance_to_shape_m"]
        <= MAX_DISTANCE_TO_SHAPE_M
    ].copy()

    print(
        f"Observaciones <=100 m del shape: "
        f"{len(df):,}"
    )

    # Timestamps
    df["collected_at"] = pd.to_datetime(
        df["collected_at"],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "collected_at",
            "vehicle_id",
            "route_id",
            "progress_m",
        ]
    ).copy()

    # Orden temporal por vehículo
    df = df.sort_values(
        [
            "vehicle_id",
            "route_id",
            "collected_at",
        ]
    )

    group_cols = [
        "vehicle_id",
        "route_id",
    ]

    # Observación anterior
    df["previous_time"] = (
        df.groupby(group_cols)["collected_at"]
        .shift(1)
    )

    df["previous_progress_m"] = (
        df.groupby(group_cols)["progress_m"]
        .shift(1)
    )

    # Diferencias temporales y espaciales
    df["delta_seconds"] = (
        df["collected_at"]
        - df["previous_time"]
    ).dt.total_seconds()

    df["delta_progress_m"] = (
        df["progress_m"]
        - df["previous_progress_m"]
    )

    # Solo intervalos temporales razonables
    valid = df[
        (df["delta_seconds"] > 0)
        & (df["delta_seconds"] <= MAX_TIME_GAP_SECONDS)
    ].copy()

    print(
        f"Intervalos temporales <=180 s: "
        f"{len(valid):,}"
    )

    # La proyección al shape puede generar pequeños retrocesos
    # por ruido GPS. Para velocidad de avance usamos solo
    # desplazamientos positivos.
    valid = valid[
        valid["delta_progress_m"] >= 0
    ].copy()

    # Velocidad observada calculada por nosotros
    valid["observed_speed_mps"] = (
        valid["delta_progress_m"]
        / valid["delta_seconds"]
    )

    valid["observed_speed_kmh"] = (
        valid["observed_speed_mps"] * 3.6
    )

    # Filtrado físico básico de outliers
    valid = valid[
        valid["observed_speed_kmh"]
        <= MAX_PLAUSIBLE_SPEED_KMH
    ].copy()

    # Variables temporales
    valid["hour"] = valid[
        "collected_at"
    ].dt.hour

    valid["minute"] = valid[
        "collected_at"
    ].dt.minute

    valid["weekday"] = valid[
        "collected_at"
    ].dt.dayofweek

    # Fracción de hora para conservar información
    # dentro de cada hora.
    valid["hour_decimal"] = (
        valid["hour"]
        + valid["minute"] / 60
    )

    # Movimiento o detención observado
    valid["is_moving"] = (
        valid["observed_speed_kmh"] > 1
    ).astype(int)

    output_columns = [
        "collected_at",
        "vehicle_id",
        "route_id",
        "direction_id",
        "shape_id",
        "latitude",
        "longitude",
        "progress_m",
        "progress_pct",
        "distance_to_shape_m",
        "speed",
        "delta_seconds",
        "delta_progress_m",
        "observed_speed_mps",
        "observed_speed_kmh",
        "hour",
        "hour_decimal",
        "weekday",
        "is_moving",
    ]

    valid = valid[output_columns]

    output = DATA / "trajectory_dataset.csv"

    valid.to_csv(
        output,
        index=False,
    )

    print()
    print(f"Intervalos válidos: {len(valid):,}")
    print(
        f"Vehículos: "
        f"{valid['vehicle_id'].nunique():,}"
    )
    print(
        f"Rutas: "
        f"{valid['route_id'].nunique():,}"
    )

    if not valid.empty:
        print()
        print("Velocidad observada calculada:")
        print(
            valid["observed_speed_kmh"]
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
        print(
            "Intervalos detenidos (<=1 km/h): "
            f"{(valid['is_moving'] == 0).mean() * 100:.1f}%"
        )

        print()
        print("Movimiento por hora:")
        hourly = (
            valid.groupby("hour")
            ["observed_speed_kmh"]
            .agg(["count", "mean", "median"])
            .round(2)
        )

        print(hourly.to_string())

    print()
    print(f"Guardado en: {output}")


if __name__ == "__main__":
    main()