import os
import re
import json
import shutil
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import yaml
import numpy as np
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

# Optional ML
try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity

    SEMANTIC_AVAILABLE = True
except Exception:
    SentenceTransformer = None  # type: ignore
    cosine_similarity = None  # type: ignore
    SEMANTIC_AVAILABLE = False

# Optional math extraction
try:
    import sympy as sp
    from latex2sympy2 import latex2sympy

    LATEX_AVAILABLE = True
except Exception:
    sp = None  # type: ignore
    latex2sympy = None  # type: ignore
    LATEX_AVAILABLE = False


console = Console()


@dataclass
class FileDecision:
    src: Path
    project: str
    category: str
    dest: Path
    confidence: float
    reasons: List[str]
    tags: Dict


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


def safe_read_text(p: Path, max_bytes: int = 500_000) -> str:
    try:
        data = p.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def detect_category(ext: str, ext_map: Dict) -> str:
    for cat, exts in ext_map.items():
        if ext.lower() in [e.lower() for e in exts]:
            return cat
    return "misc"


def keyword_score(text: str, keywords: List[str]) -> float:
    if not text:
        return 0.0
    t = text.lower()
    hits = 0
    for k in keywords:
        if k.lower() in t:
            hits += 1
    # normalized-ish score
    return hits / max(1, len(keywords))


def find_mm_markers(text: str, mm_cfg: Dict) -> Dict:
    emojis = mm_cfg.get("emoji_markers", [])
    ops = mm_cfg.get("operator_markers", [])
    hermetic = mm_cfg.get("hermetic_tags", [])

    found_emojis = sorted(set([e for e in emojis if e in text]))
    found_ops = sorted(set([o for o in ops if o.lower() in text.lower()]))
    found_hermetic = sorted(set([h for h in hermetic if h.lower() in text.lower()]))

    # Simple "operator-like" detection: symbols that look like custom operators
    operator_like = sorted(set(re.findall(r"[A-Za-z_]{3,32}Operator", text)))

    return {
        "mm_emojis": found_emojis,
        "mm_ops": found_ops,
        "hermetic_tags": found_hermetic,
        "operator_like": operator_like,
    }


def extract_latex_blocks(text: str) -> List[str]:
    # $$...$$, \\[...]\\, \\( ... \\), $...$
    blocks = []
    blocks += re.findall(r"\$\$(.*?)\$\$", text, flags=re.DOTALL)
    blocks += re.findall(r"\\\[(.*?)\\\]", text, flags=re.DOTALL)
    blocks += re.findall(r"\\\((.*?)\\\)", text, flags=re.DOTALL)
    # cautious: single $...$ can be noisy; still useful
    blocks += re.findall(r"\$(.*?)\$", text, flags=re.DOTALL)
    # clean empties
    blocks = [b.strip() for b in blocks if b.strip()]
    # de-dup
    uniq = []
    seen = set()
    for b in blocks:
        key = b[:200]
        if key not in seen:
            seen.add(key)
            uniq.append(b)
    return uniq[:20]


def safe_math_parse(latex_expr: str) -> Dict:
    """
    Tries to parse LaTeX -> SymPy. If it fails, store raw.
    """
    out = {"latex": latex_expr, "sympy": None, "ok": False, "error": None}
    if not LATEX_AVAILABLE or latex2sympy is None:
        out["error"] = "latex2sympy2 not available"
        return out
    try:
        sym = latex2sympy(latex_expr)
        out["sympy"] = str(sym)
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)[:300]
    return out


def compute_embedding(model: SentenceTransformer, text: str) -> np.ndarray:
    if not text.strip():
        return np.zeros((384,), dtype=np.float32)
    emb = model.encode([text], normalize_embeddings=True)
    return emb[0]


def pick_project_deterministic(
    text: str, projects_cfg: Dict, mm_markers: Dict
) -> Tuple[str, float, List[str]]:
    reasons = []

    # If MM markers exist, boost MM_Language
    mm_strength = (
        len(mm_markers.get("mm_emojis", []))
        + len(mm_markers.get("mm_ops", []))
        + len(mm_markers.get("hermetic_tags", []))
    )
    if mm_strength >= 2 and "MM_Language" in projects_cfg:
        reasons.append(
            f"MM markers detected (strength={mm_strength}) -> MM_Language boost"
        )
        return "MM_Language", 0.85, reasons

    best_proj = None
    best_score = 0.0

    for proj, info in projects_cfg.items():
        kws = info.get("keywords", [])
        s = keyword_score(text, kws)
        if s > best_score:
            best_score = s
            best_proj = proj

    if best_proj is None or best_score < 0.10:
        return "Unsorted", best_score, ["Low keyword match -> Unsorted"]

    reasons.append(f"Best keyword match -> {best_proj} score={best_score:.2f}")
    return best_proj, best_score, reasons


def pick_project_semantic(
    model: SentenceTransformer, text: str, projects_cfg: Dict
) -> Tuple[Optional[str], float, List[str]]:
    """
    Semantic routing using project keyword descriptions.
    Deterministic (same model, same text => same routing).
    """
    reasons = []
    if not text.strip():
        return None, 0.0, ["No text to embed"]

    proj_names = list(projects_cfg.keys())
    proj_descs = []
    for p in proj_names:
        kws = projects_cfg[p].get("keywords", [])
        proj_descs.append(f"{p}: " + ", ".join(kws))

    text_emb = compute_embedding(model, text[:5000])
    proj_embs = model.encode(proj_descs, normalize_embeddings=True)

    sims = cosine_similarity([text_emb], proj_embs)[0]
    idx = int(np.argmax(sims))
    best_proj = proj_names[idx]
    best_sim = float(sims[idx])

    reasons.append(f"Semantic best -> {best_proj} sim={best_sim:.3f}")
    return best_proj, best_sim, reasons


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def init_git_repo(path: Path, default_branch: str = "main") -> Repo:
    try:
        repo = Repo(path)
        return repo
    except InvalidGitRepositoryError:
        repo = Repo.init(path)
        # Create an initial branch if needed
        if repo.active_branch.name != default_branch:
            try:
                repo.git.checkout("-b", default_branch)
            except Exception:
                pass
        return repo


def git_commit_all(repo: Repo, message: str):
    repo.git.add(all=True)
    # Only commit if there are changes
    if repo.is_dirty(untracked_files=True):
        repo.index.commit(message)


def build_destination(
    output_root: Path, project: str, category: str, layout: Dict, src: Path
) -> Path:
    cat_folder = layout.get(category, layout.get("misc", "99_misc"))
    dest_dir = output_root / project / cat_folder

    # preserve relative-like structure by hashing original parent path
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
                "category": decision.category,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
                "tags": decision.tags,
            },
            f,
            indent=2,
        )


def organize_once(cfg: Dict):
    input_roots = [Path(p) for p in cfg["input_roots"]]
    output_root = Path(cfg["output_root"])
    ensure_dir(output_root)

    ignore_spec = build_ignore_spec(cfg.get("ignore", []))
    ext_map = cfg.get("extension_map", {})
    mm_cfg = cfg.get("mm_language", {})
    projects_cfg = cfg.get("projects", {})
    layout = cfg.get("layout", {})
    mode = cfg.get("mode", "copy").lower()

    use_git = cfg.get("git", {}).get("enabled", False)
    repo_per_project = cfg.get("git", {}).get("create_repo_per_project", True)
    auto_commit = cfg.get("git", {}).get("auto_commit", True)
    commit_message = cfg.get("git", {}).get(
        "commit_message", "Organized by mm-organizer"
    )
    default_branch = cfg.get("git", {}).get("default_branch", "main")

    # ML model for semantic routing (optional)
    model = None
    semantic_available = SEMANTIC_AVAILABLE
    if semantic_available:
        try:
            console.print(
                "[bold]Loading embedding model (sentence-transformers)...[/bold]"
            )
            model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            console.print(
                f"[yellow]Semantic model unavailable; falling back to deterministic routing. ({e})[/yellow]"
            )
            semantic_available = False

    decisions: List[FileDecision] = []
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

    for src in tqdm(all_files, desc="Classifying files"):
        ext = src.suffix.lower()
        category = detect_category(ext, ext_map)

        text = safe_read_text(src)
        mm_markers = find_mm_markers(text, mm_cfg)

        # Deterministic routing first
        proj_det, score_det, reasons_det = pick_project_deterministic(
            text, projects_cfg, mm_markers
        )

        # Semantic routing second (only if weak deterministic signal)
        proj_final = proj_det
        conf_final = float(score_det)
        reasons = list(reasons_det)

        if proj_det == "Unsorted" or score_det < 0.20:
            if semantic_available and model is not None:
                proj_sem, sim, reasons_sem = pick_project_semantic(
                    model, text[:6000], projects_cfg
                )
                if proj_sem and sim >= 0.35:
                    proj_final = proj_sem
                    conf_final = max(conf_final, sim)
                    reasons += reasons_sem
                else:
                    reasons += reasons_sem
            else:
                reasons.append("Semantic routing unavailable")

        # Math extraction
        latex_blocks = extract_latex_blocks(text)
        math_parsed = []
        for b in latex_blocks[:5]:
            math_parsed.append(safe_math_parse(b))

        tags = {
            "sha256": sha256_file(src),
            "size_bytes": src.stat().st_size,
            "extension": ext,
            "mm_markers": mm_markers,
            "latex_blocks_found": len(latex_blocks),
            "math_extract": math_parsed,
        }

        dest = build_destination(output_root, proj_final, category, layout, src)
        decisions.append(
            FileDecision(
                src=src,
                project=proj_final,
                category=category,
                dest=dest,
                confidence=float(conf_final),
                reasons=reasons,
                tags=tags,
            )
        )

    # Execute file operations + manifests
    for d in tqdm(decisions, desc="Writing organized files"):
        ensure_dir(d.dest.parent)

        if mode == "move":
            shutil.move(str(d.src), str(d.dest))
        else:
            shutil.copy2(str(d.src), str(d.dest))

        write_manifest(d.dest, d)

    # Git init + commit per project
    if use_git and repo_per_project:
        if not GIT_AVAILABLE:
            console.print(
                "[yellow]Git executable not found; skipping git init/commit.[/yellow]"
            )
        else:
            projects = sorted(set([d.project for d in decisions]))
            for proj in projects:
                proj_path = output_root / proj
                repo = init_git_repo(proj_path, default_branch=default_branch)
                if auto_commit:
                    git_commit_all(repo, commit_message)

    # Summary table
    tbl = Table(title="MM Organizer Summary")
    tbl.add_column("Project")
    tbl.add_column("Files")
    tbl.add_column("Avg Conf", justify="right")

    by_proj: Dict[str, List[FileDecision]] = {}
    for d in decisions:
        by_proj.setdefault(d.project, []).append(d)

    for proj, items in sorted(by_proj.items(), key=lambda x: (-len(x[1]), x[0])):
        avg_conf = sum(i.confidence for i in items) / max(1, len(items))
        tbl.add_row(proj, str(len(items)), f"{avg_conf:.2f}")

    console.print(tbl)
    console.print(f"[bold green]Done.[/bold green] Output: {output_root}")


def watch_mode(cfg: Dict, poll_seconds: float = 2.0):
    """
    Simple watch: re-run organizer when new/changed files appear.
    This is deterministic and safe, but heavy for huge trees.
    """
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    input_roots = [Path(p) for p in cfg["input_roots"]]
    ignore_spec = build_ignore_spec(cfg.get("ignore", []))

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            p = Path(event.src_path)
            # Ignore patterns check against each root
            for root in input_roots:
                try:
                    rel = p.relative_to(root)
                    if ignore_spec.match_file(str(rel)):
                        return
                except Exception:
                    continue
            console.print("[cyan]Change detected -> organizing...[/cyan]")
            try:
                organize_once(cfg)
            except Exception as e:
                console.print(f"[red]Organizer error:[/red] {e}")

    obs = Observer()
    handler = Handler()

    for r in input_roots:
        if r.exists():
            obs.schedule(handler, str(r), recursive=True)

    obs.start()
    console.print("[bold]Watch mode ON[/bold] (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()


if __name__ == "__main__":
    cfg_path = Path(__file__).parent / "config.yaml"
    cfg = load_config(cfg_path)

    import argparse

    parser = argparse.ArgumentParser(description="MM Intelligent Organizer")
    parser.add_argument(
        "--watch", action="store_true", help="Watch folders and auto-organize"
    )
    args = parser.parse_args()

    if args.watch:
        watch_mode(cfg)
    else:
        organize_once(cfg)
