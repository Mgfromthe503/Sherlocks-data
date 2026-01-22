import matplotlib.pyplot as plt
import numpy as np
import matplotlib.animation as animation
import itertools


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


def tesseract_wireframe_animation(
    frames=180,
    interval=50,
    d=3.0,
    figsize=(6, 6),
    color="blue",
    linewidth=1,
    elev=30,
    azim_speed=2,
):
    """
    Create a true 4D tesseract wireframe animation projected into 3D.
    Returns a matplotlib.animation.FuncAnimation.
    """
    verts4d = np.array(list(itertools.product([-1, 1], repeat=4)))
    edges = [
        (i, j)
        for i in range(16)
        for j in range(i + 1, 16)
        if np.sum(np.abs(verts4d[i] - verts4d[j])) == 2
    ]

    def project(v):
        x, y, z, w = v
        denom = d - w
        if abs(denom) < 1e-6:
            denom = 1e-6
        f = d / denom
        return np.array([x * f, y * f, z * f])

    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_axis_off()

    def rotation_matrix(theta):
        c = np.cos(theta)
        s = np.sin(theta)
        r_xw = np.array(
            [
                [c, 0, 0, -s],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [s, 0, 0, c],
            ]
        )
        r_yz = np.array(
            [
                [1, 0, 0, 0],
                [0, c, -s, 0],
                [0, s, c, 0],
                [0, 0, 0, 1],
            ]
        )
        return r_xw @ r_yz

    def update(frame):
        ax.cla()
        ax.set_axis_off()
        theta = 0.02 * frame
        r = rotation_matrix(theta)
        v4 = (r @ verts4d.T).T
        v3 = np.array([project(v) for v in v4])
        for i, j in edges:
            x1, y1, z1 = v3[i]
            x2, y2, z2 = v3[j]
            ax.plot([x1, x2], [y1, y2], [z1, z2], color=color, linewidth=linewidth)
        ax.set_xlim(-2, 2)
        ax.set_ylim(-2, 2)
        ax.set_zlim(-2, 2)
        ax.view_init(elev, frame * azim_speed)
        return []

    return animation.FuncAnimation(fig, update, frames=frames, interval=interval)
