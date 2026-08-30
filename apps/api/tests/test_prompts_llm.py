import json

import pytest
from pydantic import ValidationError

from app.llm.json_utils import extract_json_object
from app.llm.prompt_registry import PromptNotFoundError, PromptRegistry
from app.schemas.possibility import RealityExtractionOutput


def test_extract_json_plain():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = "Here you go:\n```json\n{\"a\": {\"b\": 2}}\n```\nthanks"
    assert extract_json_object(text) == {"a": {"b": 2}}


def test_extract_json_with_prose():
    text = 'Sure! {"domain": "career", "n": [1,2]} hope that helps'
    assert extract_json_object(text)["domain"] == "career"


def test_extract_json_failure():
    with pytest.raises(ValueError):
        extract_json_object("no json here at all")


def test_prompt_registry_renders_variables(tmp_path):
    (tmp_path / "demo.v1.md").write_text("Hello {{name}} with {literal} braces")
    registry = PromptRegistry(prompts_dir=tmp_path)
    rendered, name, version = registry.render("demo", name="WHAT IF")
    assert rendered == "Hello WHAT IF with {literal} braces"
    assert name == "demo" and version == "v1"


def test_prompt_registry_missing_template():
    with pytest.raises(PromptNotFoundError):
        PromptRegistry(prompts_dir=__import__("pathlib").Path("/nonexistent")).render("nope")


def test_all_production_prompts_exist_and_render():
    from app.llm.prompt_registry import get_prompt_registry

    registry = get_prompt_registry()
    rendered, _, _ = registry.render("reality_extraction", input="test scenario input here")
    assert "JSON" in rendered and "test scenario" in rendered


def test_extraction_schema_rejects_invented_required_fields():
    with pytest.raises(ValidationError):
        RealityExtractionOutput.model_validate({})


def test_extraction_output_roundtrip():
    raw = {
        "title": "Test decision",
        "summary": "A sufficiently long summary for validation purposes.",
        "domain": "career",
        "events": [{"description": "Got offer", "evidence_type": "grounded"}],
    }
    model = RealityExtractionOutput.model_validate(raw)
    assert json.loads(model.model_dump_json())["domain"] == "career"


class TestPromptVariableContract:
    """Every variable a stage passes must appear in its template.

    `dimensions` was passed to consequence_generation and never interpolated,
    so the domain registry's dimension list was dead config and each branch
    invented its own names - which silently broke branch comparison, because
    "financial_safety" and "financial_security" never line up.
    """

    # stage -> the variables app/services/pipeline.py passes to render()
    STAGE_VARIABLES = {
        "reality_extraction": {"input", "domain_hint"},
        "fork_detection": {"reality"},
        "candidate_generation": {
            "reality", "fork_json", "allowed_variables", "hard_rules", "domain_guidance",
        },
        "consequence_generation": {
            "reality", "fork_json", "candidate_json", "dimensions",
            "hard_rules", "max_causal_depth", "domain_guidance",
        },
        "critic_review": {"reality", "branches_json"},
        "candidate_revision": {
            "reality", "fork_json", "allowed_variables", "hard_rules",
            "failing_json", "passing_labels",
        },
    }

    @pytest.mark.parametrize("stage,variables", STAGE_VARIABLES.items())
    def test_template_uses_every_variable_it_is_given(self, stage, variables):
        from app.llm.prompt_registry import get_prompt_registry

        raw = get_prompt_registry()._load(stage, "v1")
        unused = {v for v in variables if "{{" + v + "}}" not in raw}
        assert not unused, f"{stage}.v1 never interpolates: {sorted(unused)}"

    @pytest.mark.parametrize("stage,variables", STAGE_VARIABLES.items())
    def test_template_has_no_placeholder_left_unfilled(self, stage, variables):
        """A placeholder with no matching variable ships literal '{{x}}' text."""
        import re

        from app.llm.prompt_registry import get_prompt_registry

        raw = get_prompt_registry()._load(stage, "v1")
        placeholders = set(re.findall(r"\{\{([a-z_]+)\}\}", raw))
        assert not (placeholders - variables), (
            f"{stage}.v1 has placeholders nothing fills: {sorted(placeholders - variables)}"
        )
