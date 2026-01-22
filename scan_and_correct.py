import os
import sys
import subprocess
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

TOOL_TIMEOUT = int(os.environ.get("TOOL_TIMEOUT", "60"))
SKIP_PYLINT = os.environ.get("SKIP_PYLINT", "0") == "1"


@dataclass
class ToolRun:
    tool: str
    path: Path
    ok: bool
    output: str


def module_exists(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def run_module(mod: str, args: List[str]) -> Tuple[bool, str]:
    cmd = [sys.executable, "-m", mod, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
        )
        out = (proc.stdout + "\n" + proc.stderr).strip()
        return proc.returncode == 0, out[:8000]
    except subprocess.TimeoutExpired as e:
        return False, f"timeout after {TOOL_TIMEOUT}s"
    except Exception as e:
        return False, str(e)


def scan_and_correct(directory: Path) -> List[ToolRun]:
    results: List[ToolRun] = []
    py_files = [p for p in directory.rglob("*.py") if p.is_file()]

    for path in py_files:
        print(f"\nProcessing {path}")

        if module_exists("black"):
            print("-> black")
            ok, out = run_module("black", [str(path)])
            results.append(ToolRun("black", path, ok, out))
        else:
            print("-> black not installed, skipping")

        if module_exists("autopep8"):
            print("-> autopep8")
            ok, out = run_module(
                "autopep8",
                ["--in-place", "--aggressive", "--aggressive", str(path)],
            )
            results.append(ToolRun("autopep8", path, ok, out))
        else:
            print("-> autopep8 not installed, skipping")

        if not SKIP_PYLINT and module_exists("pylint"):
            print("-> pylint")
            ok, out = run_module("pylint", [str(path)])
            results.append(ToolRun("pylint", path, ok, out))
        elif not SKIP_PYLINT:
            print("-> pylint not installed, skipping")
        else:
            print("-> pylint skipped by env")

    return results


def summarize(results: List[ToolRun]):
    total_files = len({r.path for r in results})
    failed = [r for r in results if not r.ok]
    print("\n=== Summary ===")
    print(f"Files touched: {total_files}")
    print(f"Tool runs: {len(results)}")
    print(f"Failures: {len(failed)}")
    if failed:
        print("\nFailures (first 5):")
        for r in failed[:5]:
            print(f"- {r.tool} on {r.path}")
            if r.output:
                first_lines = " | ".join(r.output.splitlines()[:2])
                print(f"  output: {first_lines}")


def main():
    default_path = Path(os.environ.get("PROJECT_FOLDER", "c:\\empty"))
    try:
        folder = input(
            "Enter the path to your project folder (blank for default): "
        ).strip()
    except EOFError:
        folder = ""
    directory = Path(folder) if folder else default_path
    if not directory.is_dir():
        print(f"Invalid folder path: {directory}")
        return
    results = scan_and_correct(directory)
    summarize(results)


if __name__ == "__main__":
    main()
