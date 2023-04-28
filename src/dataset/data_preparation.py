from typing import Tuple, Union, List
from scipy import stats

import numpy as np
import pandas as pd
import logging

META_DATA = ["subject", "set_id", "rpe"]


def extract_dataset_input_output(
        df: pd.DataFrame,
        labels: Union[List[str], str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if isinstance(labels, str):
        columns = [labels] + META_DATA
    elif isinstance(labels, list):
        columns = labels + META_DATA
    else:
        raise ValueError(f"Unknown ground truth column type: {type(labels)}.")

    for col in columns:
        if col not in df.columns:
            logging.warning(f"Column {col} not in dataframe. Proceeding anyways...")

    inputs = df.drop(columns, axis=1, inplace=False, errors="ignore")
    outputs = df.loc[:, df.columns.intersection(columns)]
    return inputs, outputs


def discretize_subject_rpe(df: pd.DataFrame) -> pd.DataFrame:
    labels = df["rpe"]
    labels[labels <= 15] = 0
    labels[(labels > 15) & (labels <= 18)] = 1
    labels[labels > 18] = 2
    df["rpe"] = labels
    return df


def normalize_labels_min_max(df: pd.DataFrame, label_col: str) -> pd.DataFrame:
    if label_col not in df.columns:
        raise ValueError(f"Label column {label_col} not in dataframe.")

    if "subject" not in df.columns:
        raise ValueError("Subject column not in dataframe.")

    subjects = df["subject"].unique()
    for subject_name in subjects:
        mask = df["subject"] == subject_name
        values = df.loc[mask, label_col].values
        rpe_norm = (values - values.min()) / (values.max() - values.min())
        df.loc[mask, label_col] = rpe_norm

    return df


def calculate_trend_labels(y: pd.DataFrame, label_col: str) -> pd.DataFrame:
    if label_col not in y.columns:
        raise ValueError(f"Label column {label_col} not in dataframe.")

    if "subject" not in y.columns:
        raise ValueError("Subject column not in dataframe.")

    subjects = y["subject"].unique()
    for subject in subjects:
        mask = y["subject"] == subject
        values = y.loc[mask, label_col].values
        y.loc[mask, label_col] = np.diff(values, prepend=values[0])

    return y


def normalize_data_by_subject(X: pd.DataFrame, y: pd.DataFrame, method: str = "standard") -> pd.DataFrame:
    if method not in ["standard", "min_max"]:
        raise ValueError(f"Unknown normalization method: {method}.")

    for subject in y["subject"].unique():
        mask = (y["subject"] == subject) & (~X.eq(0).all(axis=1))
        if method == "standard":
            X.loc[mask] = (X.loc[mask] - X.loc[mask].mean()) / X.loc[mask].std()
        else:
            X.loc[mask] = (X.loc[mask] - X.loc[mask].min()) / (X.loc[mask].max() - X.loc[mask].min())

    return X


def normalize_data_global(X: pd.DataFrame, method: str = "standard") -> pd.DataFrame:
    mask = ~X.eq(0).all(axis=1)
    if method == "standard":
        X.loc[mask] = (X.loc[mask] - X.loc[mask].mean()) / X.loc[mask].std()
    else:
        X.loc[mask] = (X.loc[mask] - X.loc[mask].min()) / (X.loc[mask].max() - X.loc[mask].min())

    return X


def filter_outliers_z_scores(df: pd.DataFrame, sigma: float = 3.0):
    df[df > sigma] = sigma
    df[df < -sigma] = -sigma
    return df


def filter_labels_outliers(
        X: Union[np.ndarray, pd.DataFrame],
        y: pd.DataFrame,
        gt: Union[str, List[str]],
        threshold: float = 3.1,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    abs_z_scores = np.abs(stats.zscore(y[gt]))

    if isinstance(abs_z_scores, pd.Series):
        filtered_entries = abs_z_scores < threshold
    else:
        filtered_entries = (abs_z_scores < threshold).all(axis=1)

    X = X[filtered_entries]
    y = y[filtered_entries]
    return X, y


def drop_highly_correlated_features(X: pd.DataFrame, threshold: float = 0.95) -> pd.DataFrame:
    corr_matrix = X.corr().abs()
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(np.bool))
    to_drop = [column for column in upper.columns if any(upper[column] > threshold)]
    X.drop(to_drop, axis=1, inplace=True)
    return X
