from src.devices.processing import normalize_signal, find_closest_timestamp, fill_missing_data
from ..sensor_base import SensorBase
from os.path import join

import pandas as pd
import numpy as np
import os
import json


class AzureKinect(SensorBase):

    def __init__(self, data_path, sampling_frequency=30):
        if isinstance(data_path, pd.DataFrame):
            data = data_path
        elif isinstance(data_path, str):
            position_file = join(data_path, "positions_3d.csv")
            orientation_file = join(data_path, "orientations_3d.csv")

            if not os.path.exists(position_file) or not os.path.exists(orientation_file):
                raise FileNotFoundError(f"Given files in {data_path} do not exist.")

            pos_data = pd.read_csv(position_file, delimiter=';')
            pos_data = pos_data[[c for c in pos_data.columns if "(c)" not in c and "body_idx" not in c]].copy()
            new_names = [(i, 'pos_' + i.lower()) for i in pos_data.iloc[:, 1:].columns.values]
            pos_data.rename(columns=dict(new_names), inplace=True)

            ori_data = pd.read_csv(orientation_file, delimiter=';')
            ori_data = ori_data[[c for c in ori_data.columns if "body_idx" not in c and "timestamp" not in c]].copy()
            new_names = [(i, 'ori_' + i.lower()) for i in ori_data.columns.values]
            ori_data.rename(columns=dict(new_names), inplace=True)
            data = pd.concat([pos_data, ori_data], axis=1)

        else:
            raise Exception(f"Unknown argument {data_path} for Azure Kinect class.")

        super().__init__(data, sampling_frequency)

    def process_raw_data(self):
        """
        Processing the raw data
        """
        self.data.loc[:, self.data.columns == 'timestamp'] *= 1e-6
        self.data = fill_missing_data(self.data, self.sampling_frequency)

    def multiply_matrix(self, matrix, translation=np.array([0, 0, 0])):
        """
        TODO: Change this method to work with position and orientation data
        Multiply all data points with a matrix and add a translation vector
        @param matrix: the rotation matrix
        @param translation: a translation vector
        """
        data = self.get_data(with_timestamps=False)
        samples, features = data.shape
        result = matrix * data.reshape(-1, 3).T + translation.reshape(3, 1)
        final_result = result.T.reshape(samples, features)

        # check if timestamps in data are present
        if 'timestamp' in self.data:
            timestamps = self.data['timestamp'].to_numpy()
            final_result = np.insert(final_result, 0, timestamps, axis=1)

        self.update_data_body(final_result)

    def update_data_body(self, data):
        # TODO: Replace this method with pandas update method
        samples, features = data.shape  # the new data format
        current_columns = self.data.columns  # current columns in data frame
        assert features == len(current_columns), f"Tries to assign data with wrong shape to {self}"
        self.data = pd.DataFrame(data=data, columns=current_columns)

    def __getitem__(self, item):
        """
        Get columns that contains the sub-string provided in item
        @param item: given joint name as string
        @return: pandas data frame most likely as nx3 (x,y,z) data frame
        """
        if type(item) is not str:
            raise ValueError(f"Wrong Type for Index. Expected: str, Given: {type(item)}")

        columns = [col for col in self.data.columns if item.lower() in col.lower()]
        if not columns:
            raise Exception(f"Cannot find joint: {item} in {self}")

        return self.data[columns]

    def get_data(self, with_timestamps=False):
        if with_timestamps:
            if 'timestamp' not in self.data:
                raise Exception(f"Data for {self} does not contain any timestamps.")
            return self.data.to_numpy()

        if 'timestamp' not in self.data:
            return self.data.to_numpy()
        return self.data.to_numpy()[:, 1:]

    def get_joints_as_list(self):
        """
        Return all joints in a list by removing the duplicate (x,y,z) axes
        @return: list of joint names
        """
        columns = list(self.data.columns)
        if 'timestamp' in self.data:
            columns = columns[1:]

        joints = []
        excluded_chars = ['(x)', '(y)', '(z)', ':x', ':y', ':z']
        for joint in map(lambda x: x.lower(), columns[::3]):
            for ex_char in excluded_chars:
                joint = joint.replace(ex_char, '')
            joints.append(joint.strip().lower())

        return joints

    def get_skeleton_connections(self, json_file):
        joints = self.get_joints_as_list()
        with open(json_file) as f:
            connections = json.load(f)

        return [(joints.index(j1.lower()), joints.index(j2.lower())) for j1, j2 in connections]

    def get_synchronization_signal(self) -> np.ndarray:
        return self.data['pos_spine_navel (y)'].to_numpy()
        # spine_navel = self['spine_navel'].to_numpy()
        # return spine_navel[:, 1]  # Only return y-axis

    def get_synchronization_data(self):
        """
        Get the synchronization data
        @return: tuple with (timestamps, raw_data, acc_data, peaks)
        """
        raw_data = normalize_signal(self.get_synchronization_signal())
        acc_data = normalize_signal(np.gradient(np.gradient(raw_data)))  # Calculate 2nd derivative
        return self.timestamps, raw_data, acc_data

    def cut_data_based_on_time(self, start_time, end_time):
        """
        Cut the data based on given start and end time
        @param start_time: start time in seconds
        @param end_time: end time in seconds
        """
        start_idx = find_closest_timestamp(self.timestamps, start_time)
        end_idx = find_closest_timestamp(self.timestamps, end_time)
        self.data = self.data.iloc[start_idx:end_idx]

    def __repr__(self):
        """
        String representation of Azure Kinect camera class
        @return: camera name
        """
        return "Azure Kinect"
