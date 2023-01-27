from typing import List, Dict
from src.ml import MLOptimization, eliminate_features_with_rfe
from datetime import datetime
from sklearn.svm import SVR, SVC
from argparse import ArgumentParser
from imblearn.over_sampling import RandomOverSampler
from imblearn.pipeline import Pipeline
from os.path import join, exists
from sklearn.metrics import mean_squared_error, r2_score
from src.dataset import (
    extract_dataset_input_output,
    normalize_subject_rpe,
    split_data_based_on_pseudonyms,
    normalize_data_by_subject,
)

import pandas as pd
import numpy as np
import logging
import os
import yaml
import matplotlib
matplotlib.use("WebAgg")
import matplotlib.pyplot as plt


def parse_report_file_to_model_parameters(result_df: pd.DataFrame, metric: str, model: str) -> Dict:
    best_combination = result_df.sort_values(by=metric, ascending=True).iloc[0]
    best_combination = best_combination[best_combination.index.str.contains("param")]
    param = {k.replace(f"param_{model}__", ""): v for k, v in best_combination.to_dict().items()}
    return param


def calculate_temporal_features(X: pd.DataFrame, y: pd.DataFrame, folds: int = 2) -> pd.DataFrame:
    total_df = pd.DataFrame()
    for subject in y["subject"].unique():
        mask = y["subject"] == subject
        sub_df = X.loc[mask]

        data_frames = [sub_df.diff(periods=period).add_prefix(f"GRAD_{period:02d}") for period in range(1, folds + 1)]
        temp_df = pd.concat([sub_df] + data_frames, axis=1)
        temp_df.fillna(0, inplace=True)
        total_df = pd.concat([total_df, temp_df])

    total_df.reset_index(drop=True, inplace=True)
    return total_df


def train_model(
        df: pd.DataFrame,
        exp_name: str,
        log_path: str,
        task: str,
        normalization: str,
        search: str,
        n_features: int,
        ground_truth: str,
        temporal_features: bool = False,
        drop_columns=None,
        drop_prefixes=None,

):
    if drop_prefixes is None:
        drop_prefixes = []
    if drop_columns is None:
        drop_columns = []

    log_path = join(log_path, f"{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}_{exp_name}")
    if not exists(log_path):
        os.makedirs(log_path)

    with open(join(log_path, "config.yml"), "w") as f:
        yaml.dump(
            {
                "task": task,
                "search": search,
                "n_features": n_features,
                "drop_columns": drop_columns,
                "ground_truth": ground_truth,
                "drop_prefixes": drop_prefixes,
                "normalization": normalization,
                "temporal_features": temporal_features,
            },
            f,
        )

    X, y = extract_dataset_input_output(df=df, ground_truth_column=ground_truth)

    for prefix in drop_prefixes:
        drop_columns += [col for col in df.columns if col.startswith(prefix)]

    X.drop(columns=drop_columns, inplace=True, errors="ignore")

    if temporal_features:
        X = calculate_temporal_features(X, y, folds=3)

    if normalization == "subject":
        X = normalize_data_by_subject(X, y)
    elif normalization == "global":
        X = (X - X.mean()) / X.std()

    X.fillna(0, inplace=True)
    X, _report_df = eliminate_features_with_rfe(
        X_train=X,
        y_train=y[ground_truth],
        step=25,
        n_features=n_features,
    )
    _report_df.to_csv(join(log_path, "rfe_report.csv"))
    X.to_csv(join(log_path, "X.csv"))
    y.to_csv(join(log_path, "y.csv"))

    ml_optimization = MLOptimization(
        X=X,
        y=y,
        task=task,
        mode=search,
        ground_truth=ground_truth,
    )
    ml_optimization.perform_grid_search_with_cv(log_path=log_path)
    return log_path


def evaluate_for_specific_ml_model(result_path: str, model_name: str, score_metric: str = "mean_test_r2"):
    config = yaml.load(open(join(result_path, "config.yml"), "r"), Loader=yaml.FullLoader)
    X = pd.read_csv(join(result_path, "X.csv"), index_col=0)
    y = pd.read_csv(join(result_path, "y.csv"), index_col=0)
    result_df = pd.read_csv(join(result_path, f"{model_name}.csv"))
    params = parse_report_file_to_model_parameters(result_df, score_metric, model_name)

    gt_column = config["ground_truth"]
    subjects = y["subject"].unique()
    fig, axes = plt.subplots(len(subjects), sharey=True, figsize=(20, 40))
    rmse_all = []
    r2_all = []

    for idx, cur_subject in enumerate(subjects):
        model = SVR(**params)  # Instantiate a new model everytime with best parameters from grid search
        if config["task"] == "classification":
            model = Pipeline(steps=[
                ("balance_sampling", RandomOverSampler()),
                ("svm", model),
            ])

        X_train = X.loc[y["subject"] != cur_subject]
        y_train = y.loc[y["subject"] != cur_subject]
        X_test = X.loc[y["subject"] == cur_subject]
        y_test = y.loc[y["subject"] == cur_subject]
        model.fit(X_train, y_train[gt_column])
        predictions = model.predict(X_test)
        rmse = mean_squared_error(y_test[gt_column], predictions, squared=False)
        r2 = r2_score(y_test[gt_column], predictions)
        rmse_all.append(rmse)
        r2_all.append(r2)
        axes[idx].plot(y_test[gt_column].to_numpy(), label="Ground Truth")
        axes[idx].plot(predictions, label="Prediction")
        axes[idx].set_title(f"Subject: {cur_subject}, RMSE: {rmse:.2f}, R2: {r2:.2f}")

    fig.suptitle(f"RMSE: {np.mean(rmse_all):.2f} +- {np.std(rmse_all):.2f}, R2: {np.mean(r2_all):.2f} +- {np.std(r2_all):.2f}")
    plt.legend()
    plt.savefig(join(result_path, "eval.png"))
    # plt.show()
    plt.clf()
    plt.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)-8s %(levelname)-8s %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger("my_logger").addHandler(console)

    parser = ArgumentParser()
    parser.add_argument("--src_path", type=str, dest="src_path", default="data/training")
    parser.add_argument("--result_path", type=str, dest="result_path", default="results")
    parser.add_argument("--eval_path", type=str, dest="eval_path", default="results/2023-01-27-11-11-32_mocap_rpe_20")
    parser.add_argument("--from_scratch", type=bool, dest="from_scratch", default=True)
    parser.add_argument("--task", type=str, dest="task", default="classification")
    parser.add_argument("--search", type=str, dest="search", default="grid")
    parser.add_argument("--n_features", type=int, dest="n_features", default=100)
    args = parser.parse_args()

    exp_path = "experiments"
    df = pd.read_csv(join(args.src_path, "seg_hrv.csv"), index_col=0)

    for experiment in os.listdir(exp_path):
        exp_config = yaml.load(open(join(exp_path, experiment), "r"), Loader=yaml.FullLoader)
        eval_path = train_model(df, experiment.replace(".yaml", ""), args.result_path, **exp_config)
        evaluate_for_specific_ml_model(eval_path, "svm", "mean_test_f1_score")
    # evaluate_for_specific_ml_model(args.eval_path, "svm", "mean_test_r2")
    # evaluate_for_specific_ml_model(args.eval_path, "svm", "mean_test_f1_score")
