from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


class PromptNotFoundError(KeyError):
    pass


class PromptRegistry:
    """Loads versioned prompt templates from disk and renders variables.

    Templates use {{variable}} placeholders (double braces) so literal JSON
    braces inside prompts never conflict with formatting.
    """

    def __init__(self, prompts_dir: Path | None = None):
        self._dir = prompts_dir or PROMPTS_DIR
        self._cache: dict[str, str] = {}

    def _load(self, name: str, version: str) -> str:
        key = f"{name}.{version}"
        if key not in self._cache:
            path = self._dir / f"{key}.md"
            if not path.exists():
                raise PromptNotFoundError(path.name)
            self._cache[key] = path.read_text(encoding="utf-8")
        return self._cache[key]

    def render(self, template: str, template_version: str = "v1", **variables: str) -> tuple[str, str, str]:
        """Returns (rendered_text, prompt_name, prompt_version)."""
        raw = self._load(template, template_version)
        rendered = raw
        for var, value in variables.items():
            rendered = rendered.replace("{{" + var + "}}", value)
        return rendered, template, template_version


@lru_cache
def get_prompt_registry() -> PromptRegistry:
    return PromptRegistry()
