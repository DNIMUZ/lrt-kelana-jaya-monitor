from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def weekday_seasonality(panel: pd.DataFrame, column: str = "ridership") -> pd.DataFrame:
    """Average ridership per weekday (Mon..Sun) across the panel."""
    stats = (
        panel.dropna(subset=[column])
        .groupby("weekday")[column]
        .agg(average="mean", median="median", min="min", max="max", days="count")
        .reindex(WEEKDAY_ORDER)
        .reset_index()
    )
    return stats


def monthly_seasonality(panel: pd.DataFrame, column: str = "ridership") -> pd.DataFrame:
    stats = (
        panel.dropna(subset=[column])
        .groupby(["year", "month"])[column]
        .agg(average="mean", days="count")
        .reset_index()
    )
    stats["month_name"] = pd.to_datetime(stats["month"], format="%m").dt.strftime("%b")
    return stats


def detect_ridership_anomalies(
    panel: pd.DataFrame,
    column: str = "ridership",
    window: int = 28,
    z_threshold: float = -2.0,
) -> pd.DataFrame:
    """Flag unusually-low ridership days vs a centered rolling baseline."""
    base = panel.copy()
    if column not in base or base[column].isna().all():
        return pd.DataFrame(columns=["date", "ridership", "baseline", "z_score", "disruption_signals", "anomalous"])
    base["baseline"] = base[column].rolling(window, center=True, min_periods=14).median()
    base["residual"] = base[column] - base["baseline"]
    base["z_score"] = (base["residual"] / base[column].rolling(window, center=True, min_periods=14).std()).replace(
        [np.inf, -np.inf], np.nan
    )
    base["anomalous"] = base["z_score"].lt(z_threshold).fillna(False)
    return base[["date", "ridership", "baseline", "z_score", "disruption", "anomalous"]].dropna(
        subset=["ridership", "baseline"]
    )


def signal_ridership_lag_correlation(
    panel: pd.DataFrame,
    signal_column: str = "disruption",
    ridership_column: str = "ridership",
    max_lag: int = 5,
) -> pd.DataFrame:
    """Pearson correlation between daily signals and ridership at various lags.

    Positive lag N means signals are correlated with ridership N days LATER.
    """
    rows: list[dict[str, float]] = []
    window = panel.dropna(subset=[signal_column, ridership_column]).copy()
    if window.empty:
        return pd.DataFrame(columns=["lag_days", "correlation", "samples"])
    for lag in range(-max_lag, max_lag + 1):
        if lag == 0:
            left = window[ridership_column]
            right = window[signal_column]
        elif lag > 0:
            left = window[ridership_column].shift(-lag)
            right = window[signal_column]
        else:
            left = window[ridership_column]
            right = window[signal_column].shift(-lag)
        paired = pd.concat([left, right], axis=1).dropna()
        if len(paired) >= 5:
            rows.append({"lag_days": lag, "correlation": float(paired[ridership_column].corr(paired[signal_column]))})
    return pd.DataFrame(rows)


def _lag_features(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    work = frame.copy().sort_values("date")
    work["previous_day"] = work[column].shift(1)
    work["l7avg"] = work[column].rolling(7, min_periods=1).mean().shift(1)
    work["disruption_lag1"] = work["disruption"].shift(1).fillna(0)
    return work


def ridge_forecast(
    panel: pd.DataFrame,
    column: str = "ridership",
    test_days: int = 90,
    horizon: int = 14,
) -> dict[str, object]:
    """Interpretable ridge model: day-of-week + month + trend + ridership lags.

    Trained on rolling slices with a trailing holdout; nails the weekday
    pattern that dominates rail ridership and exposes drift (social-signal effect
    is visible only in the recent window where Threads data exists).
    """
    cleaned = panel.dropna(subset=[column]).copy()
    if len(cleaned) < 30:
        return {"error": "not enough ridership history to train; need >= 30 daily rows"}
    features = _lag_features(cleaned, column)
    latest = cleaned["date"].max()
    split = latest - pd.Timedelta(days=test_days)
    train = features[features["date"] < split]
    test = features[features["date"] >= split]

    def design(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "weekday": frame["weekday_code"],
                "month": frame["month"],
                "is_weekend": frame["is_weekend"],
                "days_elapsed": (frame["date"] - cleaned["date"].min()).dt.days,
                "previous_day": frame["previous_day"].fillna(0),
                "l7avg": frame["l7avg"].fillna(frame["l7avg"].mean() if not frame["l7avg"].isna().all() else 0),
                "disruption_lag1": frame["disruption_lag1"],
            }
        )

    X_train, y_train = design(train), train[column]
    X_test, y_test = design(test), test[column]
    model = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=100.0))])
    model.fit(X_train, y_train)
    preds = pd.Series(model.predict(X_test), index=y_test.index)
    mae = float((preds - y_test).abs().mean())
    mape = float(((preds - y_test).abs() / y_test.replace(0, np.nan)).mean() * 100)
    ss_res = float(((y_test - preds) ** 2).sum())
    ss_tot = float(((y_test - y_test.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    future = _walk_forward(model, design, cleaned, column, horizon)
    test_dates = test["date"].reset_index(drop=True)
    actual_series = pd.Series(y_test.to_numpy(), index=test_dates.to_numpy(), name="ridership")
    pred_series = pd.Series(preds.to_numpy(), index=test_dates.to_numpy(), name="ridership")
    return {
        "model": model,
        "metrics": {"mae": round(mae, 0), "mape_pct": round(mape, 1), "r2": round(r2, 3)},
        "test_start": split.date().isoformat(),
        "test_end": latest.date().isoformat(),
        "test_days": len(test),
        "actual_test": actual_series,
        "predicted_test": pred_series,
        "forecast": future,
        "obs_since_2025": int((cleaned["date"] >= "2025-01-01").sum()),
        "signal_window_days": int(cleaned["disruption"].ne(0).sum()),
    }


def _walk_forward(model: Pipeline, design, cleaned: pd.DataFrame, column: str, horizon: int) -> pd.DataFrame:
    """Predict future days by carrying predictions back into the lag features."""
    lookback = cleaned[["date", "weekday_code", "month", "is_weekend", column, "disruption"]].copy()
    last = cleaned["date"].max()
    forecast_rows: list[dict[str, object]] = []
    for offset in range(1, horizon + 1):
        target_day = last + pd.Timedelta(days=offset)
        previous = lookback[column].iloc[-1]
        l7 = lookback[column].tail(7)
        l7avg = l7.mean()
        frame = pd.DataFrame(
            {
                "date": [target_day],
                "weekday": [target_day.dayofweek],
                "weekday_code": [target_day.dayofweek],
                "month": [target_day.month],
                "is_weekend": [int(target_day.dayofweek >= 5)],
                "days_elapsed": [(target_day - cleaned["date"].min()).days],
                "previous_day": [previous],
                "l7avg": [l7avg],
                "disruption_lag1": [lookback["disruption"].fillna(0).iloc[-1]],
                column: [np.nan],
            }
        )
        predicted = float(model.predict(design(frame))[0])
        lookback = pd.concat([lookback, pd.DataFrame({**frame.to_dict("records")[0], column: [predicted]})], ignore_index=True)
        forecast_rows.append({"date": target_day, "forecast": predicted})
    return pd.DataFrame(forecast_rows)


def station_mention_counts(signals: pd.DataFrame) -> pd.DataFrame:
    counts = signals[signals["station"].notna() & signals["station"].ne("")].groupby("station").size().sort_values(ascending=False)
    return counts.rename("posts").reset_index()


def author_activity(signals: pd.DataFrame) -> pd.DataFrame:
    counts = signals[signals["author_id"].notna()].groupby("author_id").size().sort_values(ascending=False)
    return counts.rename("posts").reset_index()