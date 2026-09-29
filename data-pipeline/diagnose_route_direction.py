from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"


def main():
    print("Diagnosticando sentido real de las rutas")
    print("----------------------------------------")

    df = pd.read_csv(
        DATA / "realtime_matched.csv",
        dtype={
            "vehicle_id": str,
            "route_id": str,
            "shape_id": str,
        },
    )

    df["collected_at"] = pd.to_datetime(
        df["collected_at"],
        errors="coerce",
    )

    # Solo posiciones con buen map matching
    df = df[
        df["distance_to_shape_m"] <= 100
    ].copy()

    df = df.dropna(
        subset=[
            "collected_at",
            "vehicle_id",
            "route_id",
            "progress_m",
        ]
    )

    # Quitamos snapshots duplicados del mismo vehículo
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
    )

    group_cols = [
        "vehicle_id",
        "route_id",
    ]

    df["previous_time"] = (
        df.groupby(group_cols)["collected_at"]
        .shift(1)
    )

    df["previous_progress_m"] = (
        df.groupby(group_cols)["progress_m"]
        .shift(1)
    )

    df["delta_seconds"] = (
        df["collected_at"]
        - df["previous_time"]
    ).dt.total_seconds()

    df["delta_progress_m"] = (
        df["progress_m"]
        - df["previous_progress_m"]
    )

    # Solo observaciones consecutivas razonables
    valid = df[
        (df["delta_seconds"] > 0)
        & (df["delta_seconds"] <= 180)
    ].copy()

    # Ignoramos cambios pequeños porque pueden ser
    # ruido del GPS / snapping al mismo punto.
    moving = valid[
        valid["delta_progress_m"].abs() >= 30
    ].copy()

    # Quitamos saltos absurdamente grandes.
    moving = moving[
        moving["delta_progress_m"].abs() <= 3000
    ].copy()

    print(f"Observaciones válidas: {len(valid):,}")
    print(
        f"Movimientos útiles para diagnóstico: "
        f"{len(moving):,}"
    )

    moving["positive"] = (
        moving["delta_progress_m"] > 0
    ).astype(int)

    summary = (
        moving.groupby("route_id")
        .agg(
            movements=(
                "delta_progress_m",
                "size",
            ),
            positive_pct=(
                "positive",
                "mean",
            ),
            median_delta_m=(
                "delta_progress_m",
                "median",
            ),
        )
        .reset_index()
    )

    summary["positive_pct"] = (
        summary["positive_pct"] * 100
    ).round(1)

    # Clasificación del sentido observado
    def classify(row):
        if row["movements"] < 10:
            return "insufficient"

        if row["positive_pct"] >= 70:
            return "increasing"

        if row["positive_pct"] <= 30:
            return "decreasing"

        return "ambiguous"

    summary["observed_direction"] = summary.apply(
        classify,
        axis=1,
    )

    summary = summary.sort_values(
        [
            "observed_direction",
            "movements",
        ],
        ascending=[
            True,
            False,
        ],
    )

    output = DATA / "route_direction_diagnostic.csv"

    summary.to_csv(
        output,
        index=False,
    )

    print()
    print("Clasificación de rutas:")
    print(
        summary["observed_direction"]
        .value_counts()
        .to_string()
    )

    print()
    print("Detalle:")
    print(
        summary[
            [
                "route_id",
                "movements",
                "positive_pct",
                "median_delta_m",
                "observed_direction",
            ]
        ]
        .to_string(index=False)
    )

    print()
    print(f"Guardado en: {output}")


if __name__ == "__main__":
    main()