"""
Trains the burnout risk model and bundles it with calibration data.

v2 changes:
- Switched RandomForest -> XGBoost. The previous version's GridSearchCV
  (36 param combos x 5-fold = 180 full RandomForest fits, some with
  unbounded depth) is almost certainly what made training "get stuck" on
  a real-sized dataset. XGBoost trains one model with early stopping
  instead of grid-searching, which is both much faster and, done right,
  at least as accurate.

v3 changes:
- The v2 normalization (percentile of predictions across all real dataset
  rows) had a subtle bug: it doesn't guarantee the live app can actually
  reach that percentile. The agent clips each simulated feature
  independently to its own bound before predicting -- and if a protective
  feature (deep_work_hours: more is better) gets clipped toward its "high"
  bound the same way the risk-increasing features do, the model correctly
  reads that as good news and pulls the ceiling down. That's what caused
  the score to plateau under 100 (capping around 75). Calibration now
  predicts directly on the exact best-case/worst-case vectors the runtime
  clip can produce, with each feature's direction (does higher mean better
  or worse?) taken from the sign of its correlation with burnout_risk
  rather than assumed.

Note on feature scope: the live desktop agent can only observe activity
it can literally see from window focus/switching, i.e. daily_screen_time,
deep_work_hours, doomscrolling_duration and app_switch_frequency. The
dataset has many richer columns (sleep_hours, stress_level, notification_count,
etc.), but feeding the model placeholder/mean values for columns the agent
can't actually measure live would not add real signal -- it would just add
noise and make the calibration meaningless. So this script trains on the
four observable features, but prints feature-importance / correlation
context from the fuller dataset so you can see what else would help if you
ever add manual check-in inputs (a short onboarding form, for instance).
"""

import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import joblib

# Features the desktop agent can actually observe live via window tracking.
LIVE_FEATURES = [
    'daily_screen_time',
    'deep_work_hours',
    'doomscrolling_duration',
    'app_switch_frequency',
]

# Extra dataset columns we can't measure live, but which are useful to
# report on so you know what you're leaving on the table.
CONTEXT_ONLY_FEATURES = [
    'social_media_hours', 'notification_count', 'smartphone_unlocks',
    'late_night_device_usage', 'focus_sessions', 'distraction_frequency',
    'task_completion_rate', 'concentration_score', 'sleep_hours',
    'sleep_quality', 'caffeine_intake', 'physical_activity', 'stress_level',
    'workspace_quality', 'meeting_hours', 'internet_stability',
    'remote_work_days', 'motivation_level', 'mental_fatigue',
    'emotional_exhaustion', 'work_satisfaction',
]

TARGET = 'burnout_risk'
MODEL_PATH = "halt_model.pkl"

# Percentiles used to anchor the 0-100 score scale. 2/98 rather than 0/100
# so a handful of extreme outlier rows can't compress the whole scale.
CALIBRATION_LOW_PCT = 2
CALIBRATION_HIGH_PCT = 98


def compute_correlations(df):
    """Correlation of each live feature (and context-only ones, for the
    report) with burnout_risk."""
    numeric_cols = [c for c in CONTEXT_ONLY_FEATURES + LIVE_FEATURES if c in df.columns]
    numeric_cols = [c for c in numeric_cols if pd.api.types.is_numeric_dtype(df[c])]
    return df[numeric_cols + [TARGET]].corr()[TARGET].drop(TARGET)


def report_feature_importance(corrs):
    print("\nCorrelation with burnout_risk (all available dataset columns):")
    for col, val in corrs.sort_values(key=abs, ascending=False).items():
        tag = "  [LIVE]" if col in LIVE_FEATURES else "  [not tracked live]"
        print(f"  {col:<28} {val:+.3f}{tag}")


def train_and_export():
    print("Loading dataset...")
    df = pd.read_csv("burnout_dataset.csv")

    missing = [c for c in LIVE_FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    corrs = compute_correlations(df)
    report_feature_importance(corrs)

    X = df[LIVE_FEATURES]
    y = df[TARGET]

    # Three-way split: train / early-stopping validation / held-out test.
    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.3, random_state=42)
    X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42)

    print("\nTraining XGBoost with early stopping...")
    model = XGBRegressor(
        n_estimators=1000,          # upper bound -- early stopping picks the real count
        learning_rate=0.05,
        max_depth=4,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        reg_lambda=1.0,
        objective='reg:squarederror',
        eval_metric='mae',
        early_stopping_rounds=25,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    print(f"Stopped after {model.best_iteration + 1} trees (of 1000 max).")

    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    r2 = r2_score(y_test, predictions)
    print(f"Model trained! MAE: +/- {mae:.2f} points (0-100 scale), R^2: {r2:.3f}")

    # --- Calibration: anchor score_min/score_max to the EXACT vectors the
    # runtime clip can produce ---
    # The agent clips each simulated feature independently to feature_bounds
    # before predicting. For that clip to ever actually reach 0 or 100, the
    # calibration anchors must be the model's prediction on those same
    # clipped extremes -- not a percentile taken from the dataset's real
    # (correlated) rows, which may never contain the single worst
    # combination the live app can produce.
    #
    # The wrinkle: not every feature is "worse when higher". deep_work_hours
    # is protective (negative correlation) -- more of it is good, so its
    # worst-case value is its LOW bound, not its high bound, while the other
    # three features are the opposite. Getting this backwards for even one
    # feature (e.g. clipping deep_work_hours to its high bound like the
    # others) makes the model read it as good news and pull the ceiling
    # down -- which is exactly what caused the score to plateau well under
    # 100 previously. So the worst/best-case direction per feature is
    # derived from the sign of its real correlation with burnout_risk,
    # rather than assumed.
    feature_bounds = {
        f: (float(df[f].quantile(0.01)), float(df[f].quantile(0.99)))
        for f in LIVE_FEATURES
    }

    best_case, worst_case = {}, {}
    for f in LIVE_FEATURES:
        low, high = feature_bounds[f]
        if corrs.get(f, 0) >= 0:
            # higher = worse
            best_case[f], worst_case[f] = low, high
        else:
            # higher = better (protective, e.g. deep_work_hours)
            best_case[f], worst_case[f] = high, low

    best_case_df = pd.DataFrame([best_case])[LIVE_FEATURES]
    worst_case_df = pd.DataFrame([worst_case])[LIVE_FEATURES]

    score_min = float(model.predict(best_case_df)[0])
    score_max = float(model.predict(worst_case_df)[0])
    if score_max <= score_min:
        # Safety net in case correlations are all near zero on a given
        # dataset -- fall back to the observed prediction range.
        all_predictions = model.predict(X)
        score_min = float(np.percentile(all_predictions, CALIBRATION_LOW_PCT))
        score_max = float(np.percentile(all_predictions, CALIBRATION_HIGH_PCT))

    print(f"\nCalibration anchors -> score_min: {score_min:.2f}, score_max: {score_max:.2f}")
    print("(model predictions on the exact best-case / worst-case vectors "
          "the runtime clip can produce)")

    bundle = {
        'model': model,
        'features': LIVE_FEATURES,
        'score_min': score_min,
        'score_max': score_max,
        'feature_bounds': feature_bounds,
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"Exported model bundle to {MODEL_PATH}")


if __name__ == "__main__":
    train_and_export()
