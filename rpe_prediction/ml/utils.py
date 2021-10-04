import numpy as np
import pandas as pd
import math


def split_data_based_on_pseudonyms(X: pd.DataFrame, y: pd.DataFrame, train_p: float = 0.8, random_seed: int = None):
    subject_names = sorted(y['name'].unique())
    nr_subjects = math.ceil(len(subject_names) * train_p)

    if random_seed is not None:
        np.random.seed(random_seed)

    train_subjects = np.random.choice(subject_names, nr_subjects, replace=False)
    train_idx = y['name'].isin(train_subjects)

    return X.loc[train_idx].copy(), y.loc[train_idx].copy(), X.loc[~train_idx].copy(), y.loc[~train_idx].copy()


def normalize_rpe_values_min_max(df: pd.DataFrame):
    subjects = df['name'].unique()
    for subject_name in subjects:
        mask = df['name'] == subject_name
        df_subject = df[mask]
        min_rpe, max_rpe = df_subject['rpe'].min(), df_subject['rpe'].max()
        df.loc[mask, 'rpe'] = (df_subject['rpe'] - min_rpe) / (max_rpe - min_rpe)

    return df


def normalize_features_z_score(df: pd.DataFrame):
    mean = df.mean()
    std_dev = df.std()
    df = (df - mean) / (3 * std_dev)
    df = df.clip(-1.0, 1.0)
    return df
