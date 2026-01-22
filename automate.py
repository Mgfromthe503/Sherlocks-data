"""
Automation script for the project.

This script can be used to run tests, format code, and execute the main demo.
"""

import subprocess
import sys


def run_command(command: str) -> None:
    """Run a shell command."""
    try:
        result = subprocess.run(
            command, shell=True, check=True, capture_output=True, text=True
        )
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        print(e.stderr)


def format_code() -> None:
    """Format Python code using Black."""
    print("Formatting code with Black...")
    run_command(f"{sys.executable} -m black *.py")


def run_main() -> None:
    """Run the main demonstration script."""
    print("Running main demo...")
    run_command(f"{sys.executable} main.py")


def run_tests() -> None:
    """Run any tests (placeholder)."""
    print("Running tests...")
    # Placeholder for test commands
    print("No tests defined yet.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "format":
            format_code()
        elif action == "run":
            run_main()
        elif action == "test":
            run_tests()
        else:
            print("Usage: python automate.py [format|run|test]")
    else:
        # Default: format and run
        format_code()
        run_main()
