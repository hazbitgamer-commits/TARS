"""Skill loader: each skills/<name>/ folder holds skill.py (code) + skill.md (docs).

skill.py must define:
    DESCRIPTION - one line, shown to the intent router
    ARGS        - dict of arg name -> plain-English meaning
    run(args)   - does the thing, returns a short sentence for TARS to speak

Skills are re-scanned on every command, so new ones (including self-taught
ones, Phase 6) work without restarting TARS.
"""
import importlib.util
from pathlib import Path


class SkillBox:
    def __init__(self, base: Path):
        self.dir = base / "skills"
        self._cache: dict[str, tuple[float, object]] = {}  # name -> (mtime, module)

    def load(self) -> dict:
        """Modules are cached; a skill only re-imports when its file changes —
        hot-loading still works, but routing stops paying a 37-import tax
        on every single command."""
        skills = {}
        if not self.dir.exists():
            return skills
        for py in sorted(self.dir.glob("*/skill.py")):
            name = py.parent.name
            try:
                mtime = py.stat().st_mtime
                cached = self._cache.get(name)
                if cached and cached[0] == mtime:
                    skills[name] = cached[1]
                    continue
                spec = importlib.util.spec_from_file_location(f"skill_{name}", py)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._cache[name] = (mtime, mod)
                skills[name] = mod
            except Exception as e:
                print(f"(skill '{name}' failed to load: {e})")
        return skills

    def catalog(self) -> list[dict]:
        return [
            {"skill": name, "description": mod.DESCRIPTION, "args": mod.ARGS}
            for name, mod in self.load().items()
        ]

    def run(self, name: str, args: dict | None) -> str | None:
        mod = self.load().get(name)
        if mod is None:
            return None
        return mod.run(args or {})
