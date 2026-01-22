# Integration with TensorFlow for Custom AI Models
import tensorflow as tf
import numpy as np


def build_custom_ai_model(training_data):
    # Custom AI model building using TensorFlow
    # Simple example: Linear regression model
    model = tf.keras.Sequential([tf.keras.layers.Dense(units=1, input_shape=[1])])
    model.compile(optimizer="sgd", loss="mean_squared_error")
    # Assuming training_data is a tuple (x_train, y_train)
    if isinstance(training_data, tuple) and len(training_data) == 2:
        x_train, y_train = training_data
        model.fit(x_train, y_train, epochs=10, verbose=0)
    return model


# Example usage
if __name__ == "__main__":
    # Generate some sample data
    x_train = np.array([[1], [2], [3], [4]])
    y_train = np.array([2, 4, 6, 8])  # y = 2x
    training_data = (x_train, y_train)

    model = build_custom_ai_model(training_data)
    print("Model built and trained.")

    # Test prediction
    test_input = np.array([[5]])
    prediction = model.predict(test_input)
    print(f"Prediction for input 5: {prediction[0][0]}")
