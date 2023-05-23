import numpy as np
import pandas as pd
import tensorflow as tf
import logging
import yaml
import os
import matplotlib
import matplotlib.pyplot as plt

from typing import List, Union
from datetime import datetime
from argparse import ArgumentParser
from os.path import join
from tqdm import tqdm
from os import makedirs
from tensorflow import keras
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
from src.dl import build_cnn_lstm_model, WinDataGen, build_conv2d_model, ConvModelConfig, DLOptimization
from src.dataset import dl_split_data, filter_labels_outliers_per_subject, zero_pad_array


def train_time_series_model(
        X: np.ndarray,
        y: pd.DataFrame,
        epochs: int,
        ground_truth: Union[List[str], str],
        win_size: int,
        batch_size: int,
):
    input_shape = (None, win_size, *X[0].shape[-2:])
    meta = {"X_shape_": input_shape, "n_outputs_": (None, 1)}
    model = build_cnn_lstm_model(meta=meta, kernel_size=11, n_filters=32, n_layers=3, dropout=0.5, lstm_units=32)
    model.summary()

    X_train, y_train, X_test, y_test = dl_split_data(X, y, ground_truth, 0.8)

    train_dataset = WinDataGen(X_train, y_train, win_size, 0.9, batch_size=batch_size, shuffle=True, balance=True)
    test_dataset = WinDataGen(X_test, y_test, win_size, 0.9, batch_size=1, shuffle=False, balance=False)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = "logs/fit/" + timestamp
    tb_callback = tf.keras.callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)
    # es_callback = tf.keras.callbacks.EarlyStopping(monitor='loss', patience=3)
    model.fit(train_dataset, epochs=epochs, validation_data=test_dataset, callbacks=[tb_callback], verbose=1)
    model.save(f"models/{timestamp}/model")


def train_grid_search(X, y, labels):
    opt = DLOptimization(X, y, balance=False, task="regression", mode="grid", n_splits=16, ground_truth=labels)
    opt.perform_grid_search_with_cv(ConvModelConfig(), "results_dl/power")


def train_model_own_routine(
        X: np.ndarray,
        y: pd.DataFrame,
        labels: str,
        epochs: int,
        batch_size: int,
        learning_rate: float,
):
    X_train, y_train, X_test, y_test = dl_split_data(X, y, label_col=labels, p_train=0.8)
    meta = {"X_shape_": X_train.shape, "n_outputs_": y_train.shape}
    model = build_conv2d_model(meta=meta, kernel_size=(3, 3), n_filters=128, n_layers=3, dropout=0.5, n_units=128)
    model.summary()

    train_dataset = tf.data.Dataset.from_tensor_slices((X_train, y_train))
    train_dataset = train_dataset.shuffle(buffer_size=1024).batch(batch_size)

    train_loss_results = []
    optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate)

    folder = datetime.now().strftime("%Y%m%d-%H%M%S")
    makedirs(folder, exist_ok=True)

    r2_train_array = []
    r2_test_array = []
    mae_train_array = []
    mae_test_array = []

    for epoch in range(epochs):
        logging.info(f"Epoch {epoch}")
        epoch_loss_avg = tf.keras.metrics.Mean()

        for x, y in tqdm(train_dataset):
            loss_value, grads = grad(model, x, y)
            optimizer.apply_gradients(zip(grads, model.trainable_variables))
            epoch_loss_avg.update_state(loss_value)

        train_loss_results.append(epoch_loss_avg.result())

        fig, axs = plt.subplots(2, 1)
        y_pred = model(X_train[:600], training=False)
        y_true = y_train[:600]
        r2_train = r2_score(y_pred, y_true)
        mae_train = mean_absolute_error(y_pred, y_true)
        axs[0].plot(y_true, label="True")
        axs[0].plot(y_pred, label="Predicted")
        axs[0].legend()
        axs[0].set_title(f"Train Loss: {mean_squared_error(y_pred, y_true):.3f}, MAE: {mae_train:.3f}, r2: {r2_train:.3f}")

        y_pred = model(X_test, training=False)
        y_true = y_test
        r2_test = r2_score(y_pred, y_true)
        mae_test = mean_absolute_error(y_pred, y_true)
        axs[1].plot(y_true, label="True")
        axs[1].plot(y_pred, label="Predicted")
        axs[1].legend()
        axs[1].set_title(f"Test Loss: {mean_squared_error(y_pred, y_true):.3f}, MAE: {mae_test:.3f}, r2: {r2_test:.3f}")

        plt.tight_layout()
        plt.savefig(join(folder, f"{epoch:03d}.png"))
        plt.close()
        r2_train_array.append(r2_train)
        r2_test_array.append(r2_test)
        mae_train_array.append(mae_train)
        mae_test_array.append(mae_test)

    plt.plot(r2_train_array, label="Train")
    plt.plot(r2_test_array, label="Test")
    plt.legend()
    plt.tight_layout()
    plt.savefig(join(folder, "r2.png"))


loss_object = tf.keras.losses.MeanSquaredError()


def grad(model, inputs, targets):
    with tf.GradientTape() as tape:
        loss_value = loss(model, inputs, targets, training=True)
    return loss_value, tape.gradient(loss_value, model.trainable_variables)


def loss(model, x, y, training):
    y_ = model(x, training=training)
    return loss_object(y_true=y, y_pred=y_)


def evaluate_single_model(X, y, src_path: str):
    X_train, y_train, X_test, y_test = dl_split_data(X, y, label_col="FLYWHEEL_powerAvg", p_train=0.8)

    model = keras.models.load_model(src_path)
    pred_train = model.predict(X_train).reshape(-1)
    pred_test = model.predict(X_test).reshape(-1)

    fig, axs = plt.subplots(2, 1)  # , figsize=(15, 10))
    matplotlib.rcParams.update(matplotlib.rcParamsDefault)

    # Plot Train
    axs[0].set_title("Train")
    axs[0].plot(pred_train, label="Prediction")
    axs[0].plot(y_train, label="Ground Truth")
    axs[0].legend()

    # Plot Test
    axs[1].set_title("Test")
    axs[1].plot(pred_test, label="Prediction")
    axs[1].plot(y_test, label="Ground Truth")
    axs[1].legend()

    plt.show()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--src_path", type=str, dest="src_path", default="data/training")
    parser.add_argument("--log_path", type=str, dest="log_path", default="results_dl")
    parser.add_argument("--exp_path", type=str, dest="exp_path", default="experiments_dl")
    parser.add_argument("--dst_path", type=str, dest="dst_path", default="evaluation_dl")
    parser.add_argument("--exp_file", type=str, dest="exp_file", default="experiments_dl/kinect.yaml")
    parser.add_argument("--train", type=bool, dest="train", default=True)
    parser.add_argument("--eval", type=bool, dest="eval", default=False)
    parser.add_argument("--single", type=bool, dest="single", default=True)
    parser.add_argument("--use_gpu", type=bool, dest="use_gpu", default=True)
    args = parser.parse_args()
    matplotlib.use("WebAgg")

    print(f"Available GPU devices: {tf.config.list_physical_devices('GPU')}")

    if args.train:
        if not args.use_gpu:
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

        cfg = yaml.load(open(args.exp_file, "r"), Loader=yaml.FullLoader)

        if cfg["lstm"]:
            X = np.load(join(args.src_path, cfg["X_file"]), allow_pickle=True)["X"]
            y = pd.read_csv(join(args.src_path, cfg["y_file"]), index_col=0)
            train_time_series_model(X, y, cfg["epochs"], cfg["labels"], win_size=30, batch_size=cfg["batch_size"])
        else:
            X = list(np.load(join(args.src_path, cfg["X_file"]), allow_pickle=True)["X"])
            y = pd.read_csv(join(args.src_path, cfg["y_file"]))

            arr = np.vstack(X)
            mean = np.mean(arr, axis=0)
            std = np.std(arr, axis=0)

            for skeleton in range(len(X)):
                skel = (X[skeleton] - mean) / std
                X[skeleton] = zero_pad_array(skel, 170)

            X = np.array(X)
            X = np.nan_to_num(X)
            X, y = filter_labels_outliers_per_subject(X, y, cfg["labels"], sigma=3.0)

            train_grid_search(X, y, labels=cfg["labels"])
            # train_model_own_routine(X, y, labels=cfg["labels"], epochs=cfg["epochs"], batch_size=cfg["batch_size"], learning_rate=cfg["learning_rate"])
            # evaluate_single_model(X, y, src_path="models/20230519-115702/model")
