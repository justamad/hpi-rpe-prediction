from src.ml import MLOptimization, eliminate_features_with_rfe, regression_models, instantiate_best_model
from src.plot import evaluate_sample_predictions, evaluate_aggregated_predictions
from typing import List, Dict, Tuple
from datetime import datetime
from argparse import ArgumentParser
from imblearn.over_sampling import RandomOverSampler
from imblearn.pipeline import Pipeline
from os.path import join, exists
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_percentage_error
from scipy.stats import pearsonr
from src.dataset import (
    normalize_gt_per_subject_mean,
    extract_dataset_input_output,
    normalize_data_by_subject,
)

import pandas as pd
import numpy as np
import itertools
import logging
import os
import yaml
import matplotlib
matplotlib.use("WebAgg")
import matplotlib.pyplot as plt


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
        log_path: str,
        task: str,
        normalization_input: str,
        normalization_labels: Tuple[str, bool],
        search: str,
        n_features: int,
        ground_truth: str,
        balancing: bool = False,
        temporal_features: bool = False,
        drop_columns: List = None,
        drop_prefixes: List = None,
) -> str:
    if drop_prefixes is None:
        drop_prefixes = []
    if drop_columns is None:
        drop_columns = []

    X, y = extract_dataset_input_output(df=df, ground_truth_column=ground_truth)
    for prefix in drop_prefixes:
        drop_columns += [col for col in df.columns if col.startswith(prefix)]

    X.drop(columns=drop_columns, inplace=True, errors="ignore")

    if temporal_features:
        X = calculate_temporal_features(X, y, folds=2)

    # Normalization
    input_mean, input_std = float('inf'), float('inf')
    label_mean, label_std = float('inf'), float('inf')

    if normalization_input:
        if normalization_input == "subject":
            X = normalize_data_by_subject(X, y)
        elif normalization_input == "global":
            input_mean, input_std = X.mean(), X.std()
            X = (X - input_mean) / input_std
        else:
            raise ValueError(f"Unknown normalization_input: {normalization_input}")

    if normalization_labels:
        if normalization_labels == "subject":
            y = normalize_gt_per_subject_mean(y, ground_truth, "mean")
        elif normalization_labels == "global":
            values = y.loc[:, ground_truth].values
            label_mean, label_std = values.mean(), values.std()
            y.loc[:, ground_truth] = (values - label_mean) / label_std
        else:
            raise ValueError(f"Unknown normalization_labels: {normalization_labels}")

    X.fillna(0, inplace=True)
    X, _report_df = eliminate_features_with_rfe(
        X_train=X,
        y_train=y[ground_truth],
        step=100,
        n_features=n_features,
    )
    _report_df.to_csv(join(log_path, "rfe_report.csv"))
    X.to_csv(join(log_path, "X.csv"))
    y.to_csv(join(log_path, "y.csv"))

    with open(join(log_path, "config.yml"), "w") as f:
        yaml.dump(
            {
                "task": task,
                "search": search,
                "n_features": n_features,
                "drop_columns": drop_columns,
                "ground_truth": ground_truth,
                "drop_prefixes": drop_prefixes,
                "normalization_input": normalization_input,
                "temporal_features": temporal_features,
                "balancing": balancing,
                "normalization_labels": normalization_labels,
                "input_mean": float(input_mean),
                "input_std": float(input_std),
                "label_mean": float(label_mean),
                "label_std": float(label_std),
            },
            f,
        )

    ml_optimization = MLOptimization(X=X, y=y, task=task, mode=search, balance=balancing, ground_truth=ground_truth)
    ml_optimization.perform_grid_search_with_cv(models=regression_models, log_path=log_path)
    return log_path


def evaluate_for_specific_ml_model(result_path: str):
    config = yaml.load(open(join(result_path, "config.yml"), "r"), Loader=yaml.FullLoader)
    X = pd.read_csv(join(result_path, "X.csv"), index_col=0)
    y = pd.read_csv(join(result_path, "y.csv"), index_col=0)

    if config["task"] == "classification":
        score_metric = "mean_test_f1_score"
    else:
        score_metric = "mean_test_r2"

    for model_file in list(filter(lambda x: x.startswith("model__"), os.listdir(result_path))):
        model_name = model_file.replace("model__", "").replace(".csv", "")
        logging.info(f"Evaluating model: {model_name}")
        result_df = pd.read_csv(join(result_path, model_file))
        model = instantiate_best_model(result_df, model_name, score_metric)

        gt_column = config["ground_truth"]
        subjects = y["subject"].unique()
        result_dict = {}
        for idx, cur_subject in enumerate(subjects):

            if config["balancing"]:
                model = Pipeline(steps=[
                    ("balance_sampling", RandomOverSampler()),
                    ("learner", model),
                ])

            X_train = X.loc[y["subject"] != cur_subject, :]
            y_train = y.loc[y["subject"] != cur_subject, :]
            X_test = X.loc[y["subject"] == cur_subject, :]
            y_test = y.loc[y["subject"] == cur_subject, :].copy()

            y_test.loc[:, "predictions"] = model.fit(X_train, y_train[gt_column]).predict(X_test)

            if config["normalization_labels"]:
                # raise NotImplementedError("Label normalization not implemented yet...")
                y_test.loc[:, config["ground_truth"]] = y_test.loc[:, config["ground_truth"]] * config["label_std"] + config["label_mean"]
                y_test.loc[:, "predictions"] = y_test.loc[:, "predictions"] * config["label_std"] + config["label_mean"]

            result_dict[cur_subject] = y_test

        evaluate_sample_predictions(
            result_dict=result_dict,
            gt_column=gt_column,
            file_name=join(result_path, f"{model_name}_sample_prediction.png"),
        )

        evaluate_aggregated_predictions(
            result_dict=result_dict,
            gt_column=gt_column,
            file_name=join(result_path, f"{model_name}_aggregated_prediction.png"),
        )


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
    parser.add_argument("--eval_exp", type=str, dest="eval_exp", default="results/rpe/2023-03-23-16-28-27")
    parser.add_argument("--run_experiments", type=str, dest="run_experiments", default="experiments_ml")
    args = parser.parse_args()

    df = pd.read_csv(join(args.src_path, "statistical_features.csv"), index_col=0)

    # if args.eval_exp:
        # evaluate_for_specific_ml_model(args.eval_exp)

    if args.run_experiments:
        experiments = os.listdir(args.run_experiments)
        experiments = list(filter(lambda x: os.path.isdir(join(args.run_experiments, x)), experiments))
        for experiment_folder in experiments:
            exp_files = filter(lambda f: not f.startswith("_"), os.listdir(join(args.run_experiments, experiment_folder)))

            for exp_name in exp_files:
                exp_config = yaml.load(open(join(args.run_experiments, experiment_folder, exp_name), "r"), Loader=yaml.FullLoader)

                # Construct Search space with defined experiments
                elements = {key.replace("opt_", ""): value for key, value in exp_config.items() if key.startswith("opt_")}
                for name in elements.keys():
                    del exp_config[f"opt_{name}"]

                for combination in itertools.product(*elements.values()):
                    combination = dict(zip(elements.keys(), combination))
                    exp_config.update(combination)
                    cur_name = exp_name.replace(".yaml", "_") + "_".join([f"{key}_{value}" for key, value in combination.items()])

                    logging.info(f"Start to process experiment: {cur_name}")
                    log_path = f"{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}_{cur_name}"
                    log_path = join(args.result_path, experiment_folder, log_path)
                    if not exists(log_path):
                        os.makedirs(log_path)

                    eval_path = train_model(df, log_path, **exp_config)
                    evaluate_for_specific_ml_model(eval_path)
