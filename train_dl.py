import numpy as np
import pandas as pd
import tensorflow as tf
import yaml
import os
import matplotlib

from typing import Union
from datetime import datetime
from argparse import ArgumentParser
from os.path import join
from os import makedirs
from sklearn.metrics import mean_squared_error, mean_absolute_error, mean_absolute_percentage_error, r2_score
from scipy.stats import spearmanr
from src.dl import ConvModelConfig, DLOptimization, CNNLSTMModelConfig
from src.plot import (
    plot_sample_predictions,
    create_retrain_table,
    create_residual_plot,
    create_scatter_plot,
    create_bland_altman_plot,
)

from src.dataset import (
    filter_labels_outliers_per_subject,
    zero_pad_dataset,
    dl_normalize_data_3d_subject,
    aggregate_results,
    dl_normalize_data_3d_global,
)


def train_time_series_grid_search(
        X: Union[np.ndarray, pd.DataFrame],
        y: Union[np.ndarray, pd.DataFrame],
        label: str,
        log_path: str,
        balance: bool = True,
        task: str = "regression",
        search: str = "grid",
        lstm: bool = False,
):
    opt = DLOptimization(X, y, balance=balance, task=task, mode=search, ground_truth=label)
    if lstm:
        opt.perform_grid_search_with_cv(CNNLSTMModelConfig(), log_path, lstm=lstm)
    else:
        opt.perform_grid_search_with_cv(ConvModelConfig(), log_path, lstm=lstm)


def evaluate_result_grid_search(src_path: str, dst_path: str, exp_name: str, aggregate: bool = False):
    results_df = collect_trials(src_path)

    if not os.path.exists(dst_path):
        makedirs(dst_path)

    data_df = pd.read_csv(results_df.iloc[0]["file"], index_col=0)
    data_df["model"] = "CNN-LSTM"
    if aggregate:
        data_df = aggregate_results(data_df)

    plot_sample_predictions(data_df, exp_name, dst_path)
    create_bland_altman_plot(data_df, join(dst_path), "CNN", exp_name)
    create_scatter_plot(data_df, dst_path, "CNN", exp_name)
    create_residual_plot(data_df, dst_path, "CNN")
    train_df = create_retrain_table(data_df, dst_path)
    train_df.to_csv(join(dst_path, "retrain.csv"))


def collect_trials(dst_path: str) -> pd.DataFrame:
    data_dicts = []
    for folder in os.listdir(dst_path):
        result_file = join(dst_path, folder, "results.csv")
        if not os.path.exists(result_file):
            continue

        df = pd.read_csv(result_file, index_col=0)
        if "y_pred" in df.columns:
            df.rename(columns={"y_pred": "prediction", "y_true": "ground_truth"}, inplace=True)
        metrics = {
            "RMSE": lambda x, y: mean_squared_error(x, y, squared=False),
            "MAE": mean_absolute_error,
            "R2": r2_score,
            "MAPE": mean_absolute_percentage_error,
            "Spearman": lambda x, y: spearmanr(x, y)[0],
        }
        errors = {k: [] for k in metrics.keys()}
        for subject in df["subject"].unique():
            subject_df = df[df["subject"] == subject]

            for metric, func in metrics.items():
                errors[metric].append(func(subject_df["prediction"], subject_df["ground_truth"]))

        errors = {k: np.mean(v) for k, v in errors.items()}
        errors["file"] = result_file

        params_dict = yaml.load(open(join(dst_path, folder, "params.yaml")), Loader=yaml.FullLoader)
        data_dicts.append({**params_dict, **errors})

    result_df = pd.DataFrame(data_dicts)
    result_df.sort_values(by="RMSE", inplace=True)
    return result_df


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--src_path", type=str, dest="src_path", default="data/training")
    parser.add_argument("--log_path", type=str, dest="log_path", default="dl_results")
    parser.add_argument("--exp_path", type=str, dest="exp_path", default="experiments/dl")
    parser.add_argument("--dst_path", type=str, dest="dst_path", default="evaluation_dl")
    parser.add_argument("--exp_file", type=str, dest="exp_file", default="rpe.yaml")
    parser.add_argument("--train", type=bool, dest="train", default=True)
    parser.add_argument("--eval", type=bool, dest="eval", default=True)
    parser.add_argument("--use_gpu", type=bool, dest="use_gpu", default=True)
    args = parser.parse_args()

    matplotlib.use("WebAgg")
    print(f"Available GPU devices: {tf.config.list_physical_devices('GPU')}")

    if not args.use_gpu:
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    cfg = yaml.load(open(join(args.exp_path, args.exp_file), "r"), Loader=yaml.FullLoader)
    log_path = join(args.log_path, datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(log_path, exist_ok=True)

    if cfg["lstm"]:
        X = np.load(join(args.src_path, cfg["X_file"]), allow_pickle=True)["X"]
        y = pd.read_csv(join(args.src_path, cfg["y_file"]), index_col=0)
        X = dl_normalize_data_3d_subject(X, y, method="std")

        if args.train:
            train_time_series_grid_search(X, y, cfg["label"], log_path, cfg["balance"], cfg["task"], cfg["search"], cfg["lstm"])
        if args.eval:
            evaluate_result_grid_search(
                "data/dl_results/rpe/CNNLSTM", "data/dl_evaluation/rpe", exp_name="rpe", aggregate=True,
            )
    else:
        X = np.load(join(args.src_path, cfg["X_file"]), allow_pickle=True)["X"]
        y = pd.read_csv(join(args.src_path, cfg["y_file"]))

        X = dl_normalize_data_3d_global(X, method="min_max")
        X = zero_pad_dataset(X, 170)
        X, y = filter_labels_outliers_per_subject(X, y, cfg["label"], sigma=3.0)

        if args.train:
            train_time_series_grid_search(X, y, cfg["label"], lstm=False)
        if args.eval:
            evaluate_result_grid_search(
                "data/dl_results/power/CONV2D", "data/dl_evaluation/power", exp_name="poweravg",
                aggregate=False,
            )
