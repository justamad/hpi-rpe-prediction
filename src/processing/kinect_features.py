import pandas as pd
import numpy as np


def calculate_positions_std(df: pd.DataFrame):
    """
    Calculate the mean position value for all given joints
    @param df: data frame that contains positional (x,y,z) data for all joints
    @return: data frame that contains the mean velocity value for each axis and joint
    """
    positions = df.to_numpy()
    samples, features = positions.shape
    positions_std = positions.std(axis=0).reshape(-1, features)
    return pd.DataFrame(data=positions_std, columns=df.columns)


def calculate_velocity_std(df: pd.DataFrame):
    """
    Calculate the mean value of velocity for all given joints
    @param df: data frame that contains positional (x,y,z) data for all joints
    @return: data frame that contains the mean velocity value for each axis and joint
    """
    positional_data = df.to_numpy()
    samples, features = positional_data.shape
    velocity = np.gradient(positional_data, axis=0)
    velocity_std = velocity.std(axis=0).reshape(-1, features)
    return pd.DataFrame(data=velocity_std, columns=df.columns)


def calculate_acceleration_std(df: pd.DataFrame):
    """
    Calculate the mean value of acceleration for all given joints
    @param df: data frame that contains positional (x,y,z) data for all joints
    @return: data frame that contains the mean velocity value for each axis and joint
    """
    positional_data = df.to_numpy()
    samples, features = positional_data.shape
    velocity = np.gradient(positional_data, axis=0)
    acceleration = np.gradient(velocity, axis=0)
    acceleration_std = acceleration.std(axis=0).reshape(-1, features)
    return pd.DataFrame(data=acceleration_std, columns=df.columns)
