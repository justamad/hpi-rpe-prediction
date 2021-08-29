import pandas as pd
import numpy as np

joints_with_reference = [("HIP_RIGHT", "KNEE_RIGHT"),
                         ("HIP_LEFT", "KNEE_LEFT"),
                         ("KNEE_RIGHT", "ANKLE_RIGHT"),
                         ("KNEE_LEFT", "ANKLE_LEFT"),
                         ("SHOULDER_RIGHT", "ELBOW_RIGHT"),
                         ("SHOULDER_LEFT", "ELBOW_LEFT"),
                         ("SHOULDER_LEFT", "SHOULDER_RIGHT"),
                         ("HIP_LEFT", "HIP_RIGHT"),
                         ("KNEE_LEFT", "KNEE_RIGHT"),
                         ("ELBOW_LEFT", "ELBOW_RIGHT")]

joints_with_first_joint_as_origin = [("SPINE_CHEST", "NECK", "SPINE_NAVEL"),
                                     ("SPINE_NAVEL", "SPINE_CHEST", "PELVIS"),
                                     ("HIP_LEFT", "PELVIS", "KNEE_LEFT"),
                                     ("HIP_RIGHT", "PELVIS", "KNEE_RIGHT"),
                                     ("KNEE_RIGHT", "HIP_RIGHT", "ANKLE_RIGHT"),
                                     ("KNEE_LEFT", "HIP_LEFT", "ANKLE_LEFT")]


def calculate_individual_axes_joint_velocities(df: pd.DataFrame):
    diff = df.diff(axis=0).dropna(axis='index')
    diff = diff.add_suffix('_velocity')
    return diff


def calculate_3d_joint_velocities(df: pd.DataFrame):
    diff = df.diff(axis=0).dropna(axis='index')
    euclidean_distances = np.sqrt(np.sum((diff.to_numpy() ** 2).reshape(-1, 3), axis=1))
    gradients = euclidean_distances.reshape(diff.shape[0], diff.shape[1] // 3)
    return pd.DataFrame(data=gradients,
                        columns=list(map(lambda x: x[:-4] + "_3D_VELOCITY", df.columns[::3])),
                        index=diff.index)


def calculate_joint_angles_with_reference_joint(df: pd.DataFrame, reference: str = "PELVIS"):
    r = df[[c for c in df.columns if reference in c]].to_numpy()
    result = []
    columns = []

    for j1, j2 in joints_with_reference:
        p1 = df[[c for c in df.columns if j1 in c]].to_numpy()
        p2 = df[[c for c in df.columns if j2 in c]].to_numpy()
        angles = calculate_angle_in_radians_between_vectors(r - p1, p2 - r)
        result.append(angles)
        columns.append(f"{j1}_{j2}")

    return pd.DataFrame(data=np.stack(result, axis=-1), columns=columns, index=df.index)


def calculate_angles_between_3_joints(df: pd.DataFrame):
    result = []
    columns = []
    for j1, j2, j3 in joints_with_first_joint_as_origin:
        p1 = df[[c for c in df.columns if j1 in c]].to_numpy()
        p2 = df[[c for c in df.columns if j2 in c]].to_numpy()
        p3 = df[[c for c in df.columns if j3 in c]].to_numpy()
        columns.append(f"{j1}->{j2}_{j1}->{j3}")
        angles = calculate_angle_in_radians_between_vectors(p2 - p1, p3 - p1)
        result.append(angles)

    return pd.DataFrame(data=np.stack(result, axis=-1), columns=columns, index=df.index)


def calculate_angle_in_radians_between_vectors(v1: np.ndarray, v2: np.ndarray):
    l_v1 = v1 / np.linalg.norm(v1, axis=1).reshape(-1, 1)
    l_v2 = v2 / np.linalg.norm(v2, axis=1).reshape(-1, 1)
    dot = np.sum(l_v1 * l_v2, axis=1)
    return np.arccos(dot)
