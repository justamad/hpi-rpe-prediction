from src.dataset import SubjectDataIterator, zero_pad_data_frames, impute_dataframe, mask_repetitions
from argparse import ArgumentParser
from typing import List, Tuple
from os.path import join, exists, isfile
from tsfresh.feature_extraction import extract_features, ComprehensiveFCParameters, feature_calculators
from tsfresh.utilities.dataframe_functions import impute
from tqdm import tqdm

from src.processing import (
    segment_kinect_signal,
    apply_butterworth_filter,
    calculate_acceleration,
    calculate_cross_correlation_with_datetime,
)

import numpy as np
import json
import os
import pandas as pd
import logging
import matplotlib

matplotlib.use("WebAgg")
import matplotlib.pyplot as plt

from cycler import cycler

default_cycler = (cycler(color=['r', 'g', 'b']) + cycler(linestyle=['-', '-', '-']))
plt.rc('axes', prop_cycle=default_cycler)


class CustomFeatures(ComprehensiveFCParameters):

    def __init__(self):
        ComprehensiveFCParameters.__init__(self)

        for f_name, f in feature_calculators.__dict__.items():
            is_minimal = (hasattr(f, "minimal") and getattr(f, "minimal"))
            is_curtosis_or_skew = f_name == "kurtosis" or f_name == "skewness"
            if f_name in self and not is_minimal and not is_curtosis_or_skew:
                del self[f_name]

        del self["sum_values"]
        del self["variance"]
        del self["mean"]


def match_flywheel_data(flywheel_df: pd.DataFrame, pos_df: pd.DataFrame) -> Tuple[List[bool], List[bool]]:
    if len(flywheel_df) == len(pos_df):
        return [True for _ in range(len(flywheel_df))], [True for _ in range(len(pos_df))]

    flywheel_duration = flywheel_df["duration"]
    pos_duration = pos_df["PELVIS (x)__length"] / 30

    flywheel_mean = flywheel_duration / flywheel_duration.max()
    pos_mean = pos_duration / pos_duration.max()

    max_length = min(len(flywheel_mean), len(pos_mean))
    if len(flywheel_mean) > len(pos_mean):
        shift = calculate_cross_correlation_arrays(flywheel_mean.to_numpy(), pos_mean.to_numpy())
        flywheel_mask = [False for _ in range(len(flywheel_mean))]
        flywheel_mask[shift:shift + max_length] = [True for _ in range(max_length)]
        return flywheel_mask, [True for _ in range(len(pos_mean))]
    else:
        shift = calculate_cross_correlation_arrays(pos_mean.to_numpy(), flywheel_mean.to_numpy())
        pos_mask = [False for _ in range(len(pos_mean))]
        pos_mask[shift:shift + max_length] = [True for _ in range(max_length)]
        return [True for _ in range(len(flywheel_mean))], pos_mask


def calculate_cross_correlation_arrays(reference: np.ndarray, target: np.ndarray) -> int:
    reference = (reference - np.mean(reference)) / np.std(reference)
    target = (target - np.mean(target)) / np.std(target)

    diffs = []
    for shift in range(0, len(reference) - len(target) + 1):
        diffs.append(np.sum(np.abs(reference[shift:shift + len(target)] - target)))

    shift = np.argmin(diffs)
    return shift


def process_all_raw_data(src_path: str, dst_path: str, plot_path: str):
    iterator = SubjectDataIterator(
        base_path=src_path,
        dst_path=dst_path,
        data_loader=[
            SubjectDataIterator.FLYWHEEL,
            SubjectDataIterator.AZURE,
            SubjectDataIterator.IMU,
            SubjectDataIterator.HRV,
        ]
    )

    for set_id, trial in enumerate(iterator.iterate_over_all_subjects()):
        pos_df, ori_df = trial[SubjectDataIterator.AZURE]
        flywheel_df = trial[SubjectDataIterator.FLYWHEEL]
        hrv_df = trial[SubjectDataIterator.HRV]
        imu_df = trial[SubjectDataIterator.IMU]

        imu_df = apply_butterworth_filter(df=imu_df, cutoff=20, order=4, sampling_rate=128)
        azure_acc_df = calculate_acceleration(pos_df)
        shift_dt = calculate_cross_correlation_with_datetime(
            reference_df=imu_df,
            ref_sync_axis="CHEST_ACCELERATION_Z",
            target_df=azure_acc_df,
            target_sync_axis="SPINE_CHEST (y)",
            show=False,
        )
        azure_acc_df.index += shift_dt
        pos_df.index += shift_dt
        ori_df.index += shift_dt

        fig, axs = plt.subplots(4, 1, sharex=True, figsize=(15, 12))
        fig.suptitle(f"Subject: {trial['subject']}, Set: {trial['nr_set']}")
        axs[0].plot(pos_df[['SPINE_CHEST (x)', 'SPINE_CHEST (y)', 'SPINE_CHEST (z)']])
        axs[0].set_title("Kinect Position")
        axs[1].plot(azure_acc_df[['SPINE_CHEST (x)', 'SPINE_CHEST (y)', 'SPINE_CHEST (z)']])
        axs[1].set_title("Kinect Acceleration")
        axs[2].plot(imu_df[['CHEST_ACCELERATION_X', 'CHEST_ACCELERATION_Y', 'CHEST_ACCELERATION_Z']])
        axs[2].set_title("Gaitup Acceleration")
        axs[3].plot(hrv_df[["Intensity (TRIMP/min)"]])
        axs[3].set_title("HRV")

        plt.savefig(join(plot_path, f"{trial['subject']}_{trial['nr_set']}.png"))
        # plt.show(block=True)
        plt.close()
        plt.cla()
        plt.clf()

        for df, name in zip([pos_df, ori_df, imu_df, hrv_df, flywheel_df], ["pos", "ori", "imu", "hrv", "flywheel"]):
            df.to_csv(join(trial["dst_path"], f"{name}.csv"))


def iterate_segmented_data(src_path: str, plot: bool = False, plot_path: str = None):
    if not exists(src_path):
        raise FileNotFoundError(f"Could not find source path {src_path}")

    for subject in os.listdir(src_path):
        rpe_file = join(src_path, subject, "rpe_ratings.json")
        if not isfile(rpe_file):
            raise FileNotFoundError(f"Could not find RPE file for subject {subject}")

        with open(rpe_file) as f:
            rpe_values = json.load(f)
        rpe_values = {k: v for k, v in enumerate(rpe_values["rpe_ratings"])}

        subject_plot_path = join(plot_path, "segmented", subject)
        if not exists(subject_plot_path):
            os.makedirs(subject_plot_path)

        subject_path = join(src_path, subject)
        set_folders = list(filter(lambda x: x != "rpe_ratings.json", os.listdir(subject_path)))
        set_folders = sorted(map(lambda x: (int(x.split("_")[0]), join(subject_path, x)), set_folders))
        for set_id, set_folder in set_folders:
            logging.info(f"Processing subject {subject}, set {set_id}")

            def read_and_process_dataframe(target: str):
                df = pd.read_csv(join(set_folder, f"{target}.csv"), index_col=0)
                df.index = pd.to_datetime(df.index)
                return df

            dataframes = [read_and_process_dataframe(target) for target in ["imu", "pos", "ori", "hrv", "flywheel"]]
            imu_df, pos_df, ori_df, hrv_df, flywheel_df = dataframes

            pos_df = apply_butterworth_filter(df=pos_df, cutoff=12, order=4, sampling_rate=30)
            ori_df = apply_butterworth_filter(df=ori_df, cutoff=12, order=4, sampling_rate=30)

            reps = segment_kinect_signal(
                pos_df["PELVIS (y)"],
                prominence=0.01,
                std_dev_p=0.4,
                min_dist_p=0.5,
                min_time=30,
                show=False,
            )
            pos_df = mask_repetitions(pos_df, reps, col_name="Repetition")
            ori_df = mask_repetitions(ori_df, reps, col_name="Repetition")
            imu_df = mask_repetitions(imu_df, reps, col_name="Repetition")
            hrv_df = mask_repetitions(hrv_df, reps, col_name="Repetition")

            if plot:
                fig, axs = plt.subplots(3, 1, sharex=True, figsize=(15, 12))
                axs[0].set_title(f"FlyWheel: {len(flywheel_df)} vs. Kinect: {len(reps)}")
                axs[0].plot(pos_df["PELVIS (y)"], color="gray")
                for p1, p2 in reps:
                    axs[0].plot(pos_df["PELVIS (y)"][p1:p2])
                    axs[0].plot(ori_df["KNEE_LEFT (x)"])

                axs[1].plot(imu_df["CHEST_ACCELERATION_Z"], color="gray")
                for p1, p2 in reps:
                    axs[1].plot(imu_df["CHEST_ACCELERATION_Z"][p1:p2])

                axs[2].plot(hrv_df["Load (TRIMP)"], color="gray")
                for p1, p2 in reps:
                    axs[2].plot(hrv_df["Load (TRIMP)"][p1:p2])

                # plt.show()
                plt.savefig(join(subject_plot_path, f"{subject}_{set_id}.png"))
                plt.clf()
                plt.cla()
                plt.close()

            pos_reps = pos_df["Repetition"].unique()
            imu_reps = imu_df["Repetition"].unique()
            # assert len(pos_reps) == len(imu_reps), f"Different number of reps: {subject}, set {set_id}: {len(pos_reps)} vs. {len(imu_reps)}"
            if len(pos_reps) != len(imu_reps):
                logging.warning(
                    f"Different number of reps: {subject}, set {set_id}: {len(pos_reps)} vs. {len(imu_reps)}")
                continue

            pos_df = pos_df[pos_df["Repetition"] != -1]
            ori_df = ori_df[ori_df["Repetition"] != -1]
            imu_df = imu_df[imu_df["Repetition"] != -1]
            hrv_df = hrv_df[hrv_df["Repetition"] != -1]

            cur_dict = {
                "rpe": rpe_values[set_id],
                "subject": subject,
                "set_id": set_id,
                "imu_df": imu_df,
                "pos_df": pos_df,
                "ori_df": ori_df,
                "hrv_df": hrv_df,
                "flywheel_df": flywheel_df,
            }
            yield cur_dict


def prepare_segmented_data_for_ml(src_path: str, dst_path: str, plot: bool = False, plot_path: str = None):
    final_df = pd.DataFrame()
    settings = CustomFeatures()

    for trial in iterate_segmented_data(src_path, plot=plot, plot_path=plot_path):
        rpe, subject, set_id, imu_df, pos_df, ori_df, hrv_df, flywheel_df = trial.values()

        try:
            imu_features_df = extract_features(imu_df, column_id="Repetition", default_fc_parameters=settings)
            imu_features_df = impute(imu_features_df)  # Replace Nan and inf by with extreme values (min, max)
            pos_features_df = extract_features(pos_df, column_id="Repetition", default_fc_parameters=settings)
            pos_features_df = impute(pos_features_df)
            ori_features_df = extract_features(ori_df, column_id="Repetition", default_fc_parameters=settings)
            ori_features_df = impute(ori_features_df)
            hrv_mean = hrv_df.groupby("Repetition").mean()

            # Match feature reps with Flywheel data
            flywheel_mask, pos_mask = match_flywheel_data(flywheel_df, pos_features_df)
            flywheel_df = flywheel_df[flywheel_mask]
            pos_features_df = pos_features_df[pos_mask]
            ori_features_df = ori_features_df[pos_mask]

            total_df = pd.concat(
                [
                    pos_features_df.reset_index(drop=True).add_prefix("KINECTPOS_"),
                    ori_features_df.reset_index(drop=True).add_prefix("KINECTORI_"),
                    flywheel_df.reset_index(drop=True).add_prefix("FLYWHEEL_"),
                    imu_features_df.reset_index(drop=True).add_prefix("PHYSILOG_"),
                    hrv_mean.reset_index(drop=True).add_prefix("HRV_"),
                ],
                axis=1,
            )

            total_df["rpe"] = rpe
            total_df["subject"] = subject
            total_df["set_id"] = set_id
            total_df["rep_id"] = total_df.index
            final_df = pd.concat([final_df, total_df], axis=0)

        except Exception as e:
            logging.error(f"Error while processing {subject} {set_id}: {e}")

    if not exists(dst_path):
        os.makedirs(dst_path)

    final_df = impute_dataframe(final_df)
    final_df.reset_index(drop=True, inplace=True)
    final_df.to_csv(join(dst_path, "feat.csv"))


def prepare_segmented_data_for_dl(src_path: str, normalization: str, mode: str, dst_path: str, plot_path: str):
    if normalization not in ["subject", "global"]:
        raise ValueError(f"Normalization {normalization} not supported.")

    if mode not in ["padding", "dtw"]:
        raise ValueError(f"Mode {mode} not supported.")

    repetition_data = []
    for trial in iterate_segmented_data(src_path, plot=False):
        rpe, subject, set_id, imu_df, pos_df, ori_df, hrv_df, flywheel_df = trial.values()

        l_df = [group for _, group in pos_df.groupby("reps")]
        # r_df = [group for _, group in ori_df.groupby("reps")]

        for a in l_df:
            repetition_data.append({
                "subject": subject,
                "set_id": set_id,
                "rpe": rpe,
                "pos_dfs": a,
                # "ori_dfs": r_df,
            })

        # total_df["rpe"] = rpe_values[set_id]
        # total_df["subject"] = subject
        # total_df["set_id"] = set_id
        # total_df["rep_id"] = total_df.index
        # final_df = pd.concat([final_df, total_df], axis=0)

    lengths = [len(df["pos_dfs"]) for df in repetition_data]
    arg_max = np.argmax(lengths)
    max_length = max(lengths)
    logging.info(
        f"Max Length of repetitions: {max_length} by subject {repetition_data[arg_max]['subject']}, set {repetition_data[arg_max]['set_id']}")

    final_df = pd.DataFrame()
    if mode == "padding":
        logging.info("Prepare files using Zero Padding")

        for data_obj in tqdm(repetition_data):
            df_temp = zero_pad_data_frames(data_obj["pos_dfs"], max_length)
            df_temp["rpe"] = data_obj["rpe"]
            df_temp["subject"] = data_obj["subject"]
            df_temp["set_id"] = data_obj["set_id"]

            final_df = pd.concat([final_df, df_temp], axis=0)

    if not exists(dst_path):
        os.makedirs(dst_path)

    final_df.to_csv(join(dst_path, f"{mode}.csv"))


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--src_path", type=str, dest="src_path", default="/media/ch/Data/RPE_Analysis")
    parser.add_argument("--plot_path", type=str, dest="plot_path", default="plots")
    parser.add_argument("--dst_path", type=str, dest="dst_path", default="data")
    parser.add_argument("--show", type=bool, dest="show", default=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)-8s %(levelname)-8s %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    if not exists(args.dst_path):
        os.makedirs(args.dst_path)

    if not exists(args.plot_path):
        os.makedirs(args.plot_path)

    # process_all_raw_data(args.src_path, join(args.dst_path, "processed"), args.plot_path)
    prepare_segmented_data_for_ml(join(args.dst_path, "processed"), join(args.dst_path, "training"), True, args.plot_path)
    # prepare_segmented_data_for_dl(join(args.dst_path, "processed"), "padding", join(args.dst_path, "training"), args.plot_path)
