import matplotlib.pyplot as plt
import numpy as np


def golden_ratio_rectangles(fibonacci_numbers, colors):
    width, height = 1, 1
    for i, fib in enumerate(fibonacci_numbers):
        plt.gca().add_patch(
            plt.Rectangle((0, 0), width, height, color=colors[i], fill=True)
        )
        if i % 2 == 0:
            width += fib
        else:
            height += fib
        plt.xlim(0, width)
        plt.ylim(0, height)
        plt.gca().set_aspect("equal", adjustable="box")


# Generate Fibonacci numbers
fibonacci_numbers = [1, 1]
for i in range(2, 10):  # Adjust the range for more or fewer rectangles
    fibonacci_numbers.append(fibonacci_numbers[-1] + fibonacci_numbers[-2])

# Define colors
colors = [
    "red",
    "green",
    "blue",
    "yellow",
    "orange",
    "purple",
    "pink",
    "brown",
    "gray",
    "black",
][: len(fibonacci_numbers)]

# Plot the rectangles
golden_ratio_rectangles(fibonacci_numbers, colors)
plt.show()


def simulate_rainbow_gravity(wavelength, gravity_strength):
    """
    Simulate the effect of gravity on different wavelengths of light.
    This is a speculative simulation based on the concept of rainbow gravity.
    """
    # Placeholder for the effect of gravity on different wavelengths
    # In reality, this would require complex physics calculations
    effect = gravity_strength / wavelength
    return effect


def visualize_rainbow_gravity(wavelengths, gravity_strength):
    effects = [simulate_rainbow_gravity(wl, gravity_strength) for wl in wavelengths]

    plt.figure()
    plt.scatter(wavelengths, effects, c=effects, cmap="rainbow")
    plt.colorbar(label="Gravity Effect")
    plt.xlabel("Wavelength")
    plt.ylabel("Gravity Effect")
    plt.title("Rainbow Gravity Simulation")
    plt.show()


# Example wavelengths in nanometers (visible light spectrum)
wavelengths = np.linspace(380, 750, 100)  # 380nm (violet) to 750nm (red)
gravity_strength = 1  # Placeholder value for gravity strength

visualize_rainbow_gravity(wavelengths, gravity_strength)
