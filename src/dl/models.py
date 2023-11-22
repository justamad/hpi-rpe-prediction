from tensorflow import keras
from tensorflow_addons.metrics import RSquare
from keras.regularizers import l2
from keras.layers import (
    Input,
    BatchNormalization,
    GRU,
    Dropout,
    Dense,
    Conv1D,
    MaxPooling1D,
)


def build_cnn_lstm_model(hp):
    # _, n_samples, n_features, n_channel = (None, win_size, 51, 1)
    model = keras.Sequential()
    model.add(Input(shape=(150, 51)))

    for i in range(hp.Choice('n_layers', values=[2, 3, 4])):
        model.add(Conv1D(
            filters=hp.Choice('filters_1', values=[32, 64]) * (2 ** i),
            kernel_size=hp.Choice('kernel_size_1', values=[3, 5, 7]),
            padding="valid",
            activation="relu",
            kernel_regularizer=l2(0.01),
        ))
        model.add(BatchNormalization())
        model.add(MaxPooling1D(pool_size=2))

    # model.add(Reshape((model.output_shape[1], model.output_shape[2]))) #  * model.output_shape[3])))
    model.add(GRU(hp.Choice("gru_units", values=[8, 16, 32, 64, 128]), activation="tanh", return_sequences=False))
    model.add(Dropout(0.5))
    model.add(Dense(1, activation="linear"))

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=hp.Float("learning_rate", min_value=1e-4, max_value=1e-2)),
        loss="mse", metrics=["mse", "mae", "mape", RSquare()]
    )
    # model.summary()
    return model
