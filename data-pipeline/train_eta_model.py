from pathlib import Path
import json
import pickle

import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "api" / "models"

MODEL_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def metrics(y_true, y_pred):
    mae = mean_absolute_error(
        y_true,
        y_pred,
    )

    rmse = np.sqrt(
        mean_squared_error(
            y_true,
            y_pred,
        )
    )

    r2 = r2_score(
        y_true,
        y_pred,
    )

    return {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
    }


def main():

    print("Entrenamiento modelo ETA")
    print("------------------------")

    df = pd.read_csv(
        DATA / "eta_dataset.csv",
        dtype={
            "route_id": str,
            "next_stop_id": str,
        },
    )

    df["collected_at"] = pd.to_datetime(
        df["collected_at"],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "collected_at",
            "route_id",
            "next_stop_id",
            "distance_to_next_stop_m",
            "progress_pct",
            "hour_decimal",
            "eta_real_minutes",
        ]
    ).copy()

    df = df.sort_values(
        "collected_at"
    ).reset_index(drop=True)

    print(f"Muestras disponibles: {len(df):,}")

    # ---------------------------------------------
    # División temporal 80/20
    # ---------------------------------------------

    split_index = int(
        len(df) * 0.80
    )

    train = df.iloc[
        :split_index
    ].copy()

    test = df.iloc[
        split_index:
    ].copy()

    print(
        f"Train: {len(train):,}"
    )

    print(
        f"Test: {len(test):,}"
    )

    print(
        f"Train hasta: "
        f"{train['collected_at'].max()}"
    )

    print(
        f"Test desde: "
        f"{test['collected_at'].min()}"
    )

    # ---------------------------------------------
    # Baseline
    #
    # Estimamos minutos por metro utilizando
    # únicamente TRAIN para evitar leakage.
    # ---------------------------------------------

    valid_baseline = train[
        train["distance_to_next_stop_m"]
        > 50
    ].copy()

    valid_baseline[
        "minutes_per_meter"
    ] = (
        valid_baseline[
            "eta_real_minutes"
        ]
        / valid_baseline[
            "distance_to_next_stop_m"
        ]
    )

    global_minutes_per_meter = (
        valid_baseline[
            "minutes_per_meter"
        ].median()
    )

    baseline_prediction = (
        test[
            "distance_to_next_stop_m"
        ]
        * global_minutes_per_meter
    )

    baseline_prediction = np.clip(
        baseline_prediction,
        0.25,
        20,
    )

    baseline_metrics = metrics(
        test["eta_real_minutes"],
        baseline_prediction,
    )

    # ---------------------------------------------
    # Features ML
    # ---------------------------------------------

    numeric_features = [
        "distance_to_next_stop_m",
        "progress_pct",
        "hour_decimal",
    ]

    categorical_features = [
        "route_id",
        "next_stop_id",
    ]

    features = (
        numeric_features
        + categorical_features
    )

    X_train = train[features]
    y_train = train[
        "eta_real_minutes"
    ]

    X_test = test[features]
    y_test = test[
        "eta_real_minutes"
    ]

    # ---------------------------------------------
    # Preprocesamiento
    # ---------------------------------------------

    numeric_transformer = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                ),
            ),
        ]
    )

    categorical_transformer = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="most_frequent"
                ),
            ),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
            ),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                numeric_transformer,
                numeric_features,
            ),
            (
                "categorical",
                categorical_transformer,
                categorical_features,
            ),
        ]
    )

    model = HistGradientBoostingRegressor(
        learning_rate=0.08,
        max_iter=200,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        random_state=42,
    )

    pipeline = Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor,
            ),
            (
                "model",
                model,
            ),
        ]
    )

    print()
    print("Entrenando modelo...")

    pipeline.fit(
        X_train,
        y_train,
    )

    prediction = pipeline.predict(
        X_test
    )

    prediction = np.clip(
        prediction,
        0.25,
        20,
    )

    model_metrics = metrics(
        y_test,
        prediction,
    )

    # ---------------------------------------------
    # Resultados
    # ---------------------------------------------

    print()
    print("BASELINE")
    print(
        f"MAE:  "
        f"{baseline_metrics['mae']:.3f} min"
    )
    print(
        f"RMSE: "
        f"{baseline_metrics['rmse']:.3f} min"
    )
    print(
        f"R²:   "
        f"{baseline_metrics['r2']:.3f}"
    )

    print()
    print("MODELO ML")
    print(
        f"MAE:  "
        f"{model_metrics['mae']:.3f} min"
    )
    print(
        f"RMSE: "
        f"{model_metrics['rmse']:.3f} min"
    )
    print(
        f"R²:   "
        f"{model_metrics['r2']:.3f}"
    )

    improvement = (
        (
            baseline_metrics["mae"]
            - model_metrics["mae"]
        )
        / baseline_metrics["mae"]
        * 100
    )

    print()
    print(
        "Mejora MAE vs baseline: "
        f"{improvement:.1f}%"
    )

    # ---------------------------------------------
    # Ejemplos del test
    # ---------------------------------------------

    results = test[
        [
            "collected_at",
            "route_id",
            "next_stop_name",
            "distance_to_next_stop_m",
            "eta_real_minutes",
        ]
    ].copy()

    results[
        "eta_baseline_minutes"
    ] = baseline_prediction

    results[
        "eta_model_minutes"
    ] = prediction

    results[
        "absolute_error_model"
    ] = (
        results[
            "eta_real_minutes"
        ]
        - results[
            "eta_model_minutes"
        ]
    ).abs()

    print()
    print("Ejemplos TEST:")
    print(
        results.head(15)
        .round(2)
        .to_string(index=False)
    )

    # ---------------------------------------------
    # Guardar resultados
    # ---------------------------------------------

    results.to_csv(
        DATA / "eta_test_predictions.csv",
        index=False,
    )

    with open(
        MODEL_DIR / "eta_model.pkl",
        "wb",
    ) as f:
        pickle.dump(
            pipeline,
            f,
        )

    metadata = {
        "features": features,
        "train_samples": len(train),
        "test_samples": len(test),
        "train_end": str(
            train["collected_at"].max()
        ),
        "test_start": str(
            test["collected_at"].min()
        ),
        "baseline": baseline_metrics,
        "model": model_metrics,
        "mae_improvement_pct": float(
            improvement
        ),
        "global_minutes_per_meter": float(
            global_minutes_per_meter
        ),
    }

    with open(
        MODEL_DIR / "eta_model_metadata.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(
        "Modelo guardado en:"
    )
    print(
        MODEL_DIR / "eta_model.pkl"
    )

    print()
    print(
        "Predicciones guardadas en:"
    )
    print(
        DATA / "eta_test_predictions.csv"
    )


if __name__ == "__main__":
    main()