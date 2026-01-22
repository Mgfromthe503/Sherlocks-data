import os
import re
import json
import shutil
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import yaml
from tqdm import tqdm
from rich.console import Console
from rich.table import Table
from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

# GitPython requires the git executable; make it optional.
try:
    from git import Repo, InvalidGitRepositoryError

    GIT_AVAILABLE = True
except Exception:
    Repo = None  # type: ignore
    InvalidGitRepositoryError = Exception  # type: ignore
    GIT_AVAILABLE = False

from pygments.lexers import guess_lexer_for_filename
from pygments.util import ClassNotFound

console = Console()


# -----------------------
# Core data structures
# -----------------------
@dataclass
class FileDecision:
    src: Path
    project: str
    bucket: str  # src/docs/configs/data/tests/build/scripts/assets/misc
    language: str  # python/javascript/etc
    dest: Path
    confidence: float
    reasons: List[str]
    tags: Dict


# -----------------------
# Utility helpers
# -----------------------
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(cfg_path: Path) -> Dict:
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_ignore_spec(patterns: List[str]) -> PathSpec:
    compiled = [GitWildMatchPattern(p) for p in patterns]
    return PathSpec(compiled)


def safe_read_text(p: Path, max_bytes: int = 700_000) -> str:
    try:
        data = p.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def keyword_score(text: str, keywords: List[str]) -> float:
    if not text:
        return 0.0
    t = text.lower()
    hits = 0
    for k in keywords:
        if k.lower() in t:
            hits += 1
    return hits / max(1, len(keywords))


def find_mm_markers(text: str, mm_cfg: Dict) -> Dict:
    emojis = mm_cfg.get("emoji_markers", [])
    ops = mm_cfg.get("operator_markers", [])
    hermetic = mm_cfg.get("hermetic_tags", [])

    found_emojis = sorted(set([e for e in emojis if e in text]))
    found_ops = sorted(set([o for o in ops if o.lower() in text.lower()]))
    found_hermetic = sorted(set([h for h in hermetic if h.lower() in text.lower()]))

    operator_like = sorted(set(re.findall(r"[A-Za-z_]{3,64}Operator", text)))

    return {
        "mm_emojis": found_emojis,
        "mm_ops": found_ops,
        "hermetic_tags": found_hermetic,
        "operator_like": operator_like,
        "mm_strength": len(found_emojis) + len(found_ops) + len(found_hermetic),
    }


# -----------------------
# Language detection (ANY language)
# -----------------------
LANG_ALIASES = {
    "Python": "python",
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "JSON": "json",
    "YAML": "yaml",
    "Markdown": "markdown",
    "HTML": "html",
    "CSS": "css",
    "Rust": "rust",
    "Go": "go",
    "Bash": "shell",
    "Shell": "shell",
    "PowerShell": "powershell",
    "C": "c",
    "C++": "cpp",
    "Java": "java",
    "Kotlin": "kotlin",
    "Swift": "swift",
    "Ruby": "ruby",
    "PHP": "php",
}


def detect_language(src: Path, text: str) -> Tuple[str, List[str]]:
    reasons = []
    # Shebang fast path
    if text.startswith("#!"):
        if "python" in text.splitlines()[0]:
            return "python", ["shebang: python"]
        if "node" in text.splitlines()[0]:
            return "javascript", ["shebang: node"]
        if "bash" in text.splitlines()[0] or "sh" in text.splitlines()[0]:
            return "shell", ["shebang: shell"]

    # Pygments guess (content+filename)
    try:
        lexer = guess_lexer_for_filename(src.name, text[:4000])
        name = lexer.name
        lang = LANG_ALIASES.get(name, name.lower())
        reasons.append(f"pygments: {name}")
        return lang, reasons
    except ClassNotFound:
        # fallback by extension
        ext = src.suffix.lower()
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".md": "markdown",
            ".ps1": "powershell",
            ".sh": "shell",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        if ext in ext_map:
            return ext_map[ext], [f"extension: {ext}"]
        return "unknown", ["language unknown"]


# -----------------------
# Bucket detection (intent)
# src/docs/configs/data/tests/build/scripts/assets/misc
# -----------------------


def detect_bucket(src: Path, text: str) -> Tuple[str, float, List[str]]:
    reasons = []
    name = src.name.lower()
    path = str(src).lower()

    # Tests
    if "test" in name or "/tests/" in path or "\\tests\\" in path:
        reasons.append("path/name indicates tests")
        return "tests", 0.90, reasons

    # Docs
    if name.endswith((".md", ".rst", ".txt")) or "/docs/" in path or "\\docs\\" in path:
        reasons.append("docs extension/path")
        return "docs", 0.85, reasons

    # Configs
    if name in (
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "cargo.toml",
        "go.mod",
    ) or name.endswith((".env", ".ini", ".toml", ".yaml", ".yml")):
        reasons.append("config file signature")
        return "configs", 0.90, reasons

    # Data
    if (
        name.endswith((".csv", ".parquet", ".sqlite", ".db", ".json"))
        and "package.json" not in name
    ):
        reasons.append("data file extension")
        return "data", 0.80, reasons

    # Build/system
    if (
        name in ("makefile", "dockerfile")
        or "cmake" in name
        or "/build/" in path
        or "\\build\\" in path
    ):
        reasons.append("build signature")
        return "build", 0.80, reasons

    # Scripts
    if name.endswith((".sh", ".ps1", ".bat", ".cmd")):
        reasons.append("script extension")
        return "scripts", 0.85, reasons

    # Assets
    if name.endswith(
        (
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".wav",
            ".mp3",
            ".mp4",
            ".mov",
            ".pdf",
        )
    ):
        reasons.append("asset extension")
        return "assets", 0.80, reasons

    # Default
    reasons.append("default -> src")
    return "src", 0.60, reasons


# -----------------------
# Project routing (keyword + MM overrides)
# -----------------------


def pick_project(
    text: str, projects_cfg: Dict, mm_markers: Dict
) -> Tuple[str, float, List[str]]:
    reasons = []
    mm_strength = mm_markers.get("mm_strength", 0)

    if mm_strength >= 2 and "MM_Language" in projects_cfg:
        reasons.append(f"MM markers strong (strength={mm_strength}) -> MM_Language")
        return "MM_Language", 0.92, reasons

    best_proj = "Unsorted"
    best_score = 0.0

    for proj, info in projects_cfg.items():
        if isinstance(info, dict):
            keywords = info.get("keywords", [])
        else:
            keywords = info
        s = keyword_score(text, keywords)
        if s > best_score:
            best_score = s
            best_proj = proj

    if best_score < 0.12:
        reasons.append(f"low keyword match ({best_score:.2f}) -> Unsorted")
        return "Unsorted", best_score, reasons

    reasons.append(f"best keyword match -> {best_proj} score={best_score:.2f}")
    return best_proj, best_score, reasons


# -----------------------
# Destination path building
# -----------------------


def build_destination(
    output_root: Path, project: str, bucket: str, language: str, layout: Dict, src: Path
) -> Path:
    bucket_dir = layout.get(bucket, layout.get("misc", "99_misc"))
    # language-aware subfolder (prevents spaghetti)
    lang_dir = language if language else "unknown"

    dest_dir = output_root / project / bucket_dir / lang_dir

    # preserve some context: hash original parent
    parent_hash = hashlib.md5(
        str(src.parent).encode("utf-8", errors="ignore")
    ).hexdigest()[:8]
    dest_dir = dest_dir / parent_hash

    ensure_dir(dest_dir)
    return dest_dir / src.name


def write_manifest(dest_file: Path, decision: FileDecision):
    meta_dir = dest_file.parent / ".mm_meta"
    ensure_dir(meta_dir)
    meta_path = meta_dir / f"{dest_file.name}.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "source": str(decision.src),
                "dest": str(decision.dest),
                "project": decision.project,
                "bucket": decision.bucket,
                "language": decision.language,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
                "tags": decision.tags,
            },
            f,
            indent=2,
        )


# -----------------------
# Git automation
# -----------------------


def init_git_repo(path: Path, default_branch: str = "main") -> Repo:
    try:
        return Repo(path)
    except InvalidGitRepositoryError:
        repo = Repo.init(path)
        try:
            repo.git.checkout("-b", default_branch)
        except Exception:
            pass
        return repo


def git_commit_all(repo: Repo, message: str):
    repo.git.add(all=True)
    if repo.is_dirty(untracked_files=True):
        repo.index.commit(message)


# -----------------------
# Safe "fixers" (format-only / safe autofix)
# No semantic rewriting. No hallucinated changes.
# -----------------------


def tool_exists(cmd: str) -> bool:
    # checks executable exists in PATH (windows-compatible)
    exe = cmd.split()[0]
    return shutil.which(exe) is not None


def run_cmd(cmd: str, cwd: Path) -> Tuple[bool, str]:
    try:
        completed = subprocess.run(
            cmd, cwd=str(cwd), shell=True, capture_output=True, text=True
        )
        ok = completed.returncode == 0
        out = (completed.stdout + "\n" + completed.stderr).strip()
        return ok, out[:5000]
    except Exception as e:
        return False, str(e)[:5000]


def run_fixers_for_project(project_path: Path, cfg: Dict, report_lines: List[str]):
    fixers_cfg = cfg.get("fixers", {})
    if not fixers_cfg.get("enabled", False):
        return

    formatters = fixers_cfg.get("formatters", {})
    if not formatters:
        return

    report_lines.append(f"## Fixers run for: {project_path}")
    for lang, cmds in formatters.items():
        if not cmds:
            continue

        # Only run if tool exists
        for cmd in cmds:
            exe = cmd.split()[0]
            if not tool_exists(exe):
                report_lines.append(f"- SKIP [{lang}] `{cmd}` (tool not installed)")
                continue
            ok, out = run_cmd(cmd, project_path)
            status = "OK" if ok else "FAIL"
            report_lines.append(f"- {status} [{lang}] `{cmd}`")
            if out:
                report_lines.append(f"  - output: `{out.replace('`','')[:220]}`")


# -----------------------
# Main organizer
# -----------------------


def organize_once(cfg: Dict):
    input_roots = [Path(p) for p in cfg["input_roots"]]
    output_root = Path(cfg["output_root"])
    ensure_dir(output_root)

    ignore_spec = build_ignore_spec(cfg.get("ignore", []))
    layout = cfg.get("layout", {})
    mm_cfg = cfg.get("mm_language", {})
    projects_cfg = cfg.get("projects", {})

    mode = cfg.get("mode", "copy").lower()

    git_cfg = cfg.get("git", {})
    use_git = bool(git_cfg.get("enabled", False))
    repo_per_project = bool(git_cfg.get("create_repo_per_project", True))
    auto_commit = bool(git_cfg.get("auto_commit", True))
    commit_message = git_cfg.get(
        "commit_message", "MM Organizer Pro: organized + formatted"
    )
    default_branch = git_cfg.get("default_branch", "main")

    all_files: List[Path] = []
    for root in input_roots:
        if not root.exists():
            console.print(f"[yellow]Input root not found:[/yellow] {root}")
            continue
        for p in root.rglob("*"):
            if p.is_dir():
                continue
            rel = p.relative_to(root)
            if ignore_spec.match_file(str(rel)):
                continue
            all_files.append(p)

    decisions: List[FileDecision] = []
    for src in tqdm(all_files, desc="Scanning + classifying"):
        text = safe_read_text(src)

        mm_markers = find_mm_markers(text, mm_cfg)
        project, pscore, preasons = pick_project(text, projects_cfg, mm_markers)

        bucket, bscore, breasons = detect_bucket(src, text)

        language, lreasons = detect_language(src, text)

        confidence = max(pscore, bscore)
        reasons = preasons + breasons + lreasons

        tags = {
            "sha256": sha256_file(src),
            "size_bytes": src.stat().st_size,
            "mm_markers": mm_markers,
            "language_guess": language,
        }

        dest = build_destination(output_root, project, bucket, language, layout, src)
        decisions.append(
            FileDecision(
                src=src,
                project=project,
                bucket=bucket,
                language=language,
                dest=dest,
                confidence=float(confidence),
                reasons=reasons,
                tags=tags,
            )
        )

    # file operations
    for d in tqdm(decisions, desc="Organizing files"):
        ensure_dir(d.dest.parent)
        if mode == "move":
            shutil.move(str(d.src), str(d.dest))
        else:
            shutil.copy2(str(d.src), str(d.dest))
        write_manifest(d.dest, d)

    # Git + Fixers per project folder
    report_lines: List[str] = []
    report_lines.append("# MM Organizer Pro Repair Report")
    report_lines.append("")
    report_lines.append(f"Output root: `{output_root}`")
    report_lines.append("")

    if use_git and repo_per_project:
        if not GIT_AVAILABLE:
            console.print(
                "[yellow]Git executable not found; skipping git init/commit.[/yellow]"
            )
        else:
            projects = sorted(set([d.project for d in decisions]))
            for proj in projects:
                proj_path = output_root / proj
                # run safe fixers in-place (format only)
                run_fixers_for_project(proj_path, cfg, report_lines)

                # init repo and commit
                repo = init_git_repo(proj_path, default_branch=default_branch)
                if auto_commit:
                    git_commit_all(repo, commit_message)

    # Write report
    report_path = output_root / "MM_ORGANIZER_REPAIR_REPORT.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    # summary
    tbl = Table(title="MM Organizer Pro Summary")
    tbl.add_column("Project")
    tbl.add_column("Files")
    tbl.add_column("Top Languages")

    by_proj: Dict[str, List[FileDecision]] = {}
    for d in decisions:
        by_proj.setdefault(d.project, []).append(d)

    for proj, items in sorted(by_proj.items(), key=lambda x: (-len(x[1]), x[0])):
        langs = {}
        for it in items:
            langs[it.language] = langs.get(it.language, 0) + 1
        top_langs = ", ".join(
            [k for k, _ in sorted(langs.items(), key=lambda kv: -kv[1])[:3]]
        )
        tbl.add_row(proj, str(len(items)), top_langs or "unknown")

    console.print(tbl)
    console.print(f"[bold green]Done.[/bold green] Output: {output_root}")
    console.print(f"Repair report: {report_path}")


if __name__ == "__main__":
    cfg_path = Path(__file__).parent / "config.yaml"
    cfg = load_config(cfg_path)
    organize_once(cfg)
