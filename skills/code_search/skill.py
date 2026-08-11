"""'Where did I write the eufy login?' — searches every project the owner owns
and reads back the file, the line and the snippet.

He runs nine projects at once; the answer is always somewhere, and hunting
for it by hand is the tax on having many ideas. Pure-python search (no
ripgrep dependency), skipping the places that waste time: node_modules,
.git, virtualenvs, TARS's own bundled runtime.
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
ROOTS = (Path.home() / "Projects", Path.home() / "Desktop")
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "runtime", ".venv",
             "venv", "dist", "build", "vault", "vault_quarantine",
             "backups", "models", "wakeword", "eufy_lib", "site-packages",
             "logs", ".next", "target", "Screenshots", "Videos"}
CODE_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
            ".md", ".sh", ".bat", ".ps1", ".yml", ".yaml", ".toml", ".txt",
            ".java", ".cs", ".cpp", ".c", ".h", ".rs", ".go", ".scad"}
MAX_FILES = 4000
MAX_HITS = 8

DESCRIPTION = ("SEARCH THE OWNER'S OWN CODE across all his projects — 'where "
               "did I write the eufy login', 'find the function that reads "
               "the solar data', 'which project uses supabase', 'show me "
               "where I handle quiet hours'. Reads back file, line and the "
               "snippet. NOT for searching the internet (web_search), NOT "
               "for open-source projects (find_tool), and NOT for finding "
               "documents/photos (search_files).")
ARGS = {"query": "what to look for — a phrase, function name or idea",
        "project": "optional: limit to one project"}


def _files(project: str = "") -> list[Path]:
    out = []
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.iterdir():
            if not path.is_dir() or path.name.startswith("."):
                continue
            if project and project.lower().replace(" ", "") not in \
                    path.name.lower().replace("_", "").replace(" ", ""):
                continue
            for f in path.rglob("*"):
                if len(out) >= MAX_FILES:
                    return out
                if f.is_file() and f.suffix.lower() in CODE_EXT \
                        and not (SKIP_DIRS & set(f.parts)) \
                        and f.stat().st_size < 400_000:
                    out.append(f)
    return out


def run(args: dict) -> str:
    query = str(args.get("query") or "").strip()
    if len(query) < 3:
        return "What should I search your code for?"
    project = str(args.get("project") or "").strip()

    words = [w for w in re.findall(r"[\w']{3,}", query.lower())
             if w not in {"the", "and", "for", "where", "did", "write",
                          "find", "code", "function", "that", "with", "how",
                          "does", "which", "project", "uses", "show"}]
    if not words:
        words = [query.lower()]
    hits = []
    for f in _files(project):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        low = text.lower()
        score = sum(low.count(w) for w in words)
        if not score or not all(w in low for w in words[:2]):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if all(w in line.lower() for w in words[:2]):
                hits.append((score, f, i, line.strip()[:120]))
                break
        else:
            first = next((i for i, line in enumerate(text.splitlines(), 1)
                          if words[0] in line.lower()), 1)
            hits.append((score // 2, f, first,
                         text.splitlines()[first - 1].strip()[:120]))
    if not hits:
        return (f"I couldn't find {query} anywhere in your projects."
                + (f" (searched {project} only)" if project else ""))

    hits.sort(key=lambda h: -h[0])
    best = hits[:MAX_HITS]
    top = best[0]
    others = {h[1].parts[len(Path.home().parts) + 1] for h in best[1:]}
    where = f"{top[1].parent.name}/{top[1].name}, line {top[2]}"
    return (f"Found it in {where}: {top[3]}"
            + (f". Also in {len(best) - 1} other place"
               f"{'s' if len(best) > 2 else ''}"
               + (f" — {', '.join(sorted(others)[:3])}" if others else "")
               if len(best) > 1 else "") + ".")
