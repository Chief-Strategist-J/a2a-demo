"""Tests for shared/prompts.py — prompt loading and rendering."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared import prompts as prompt_lib

ROOT = Path(__file__).parent.parent.parent
PROMPTS_FILE = ROOT / "prompts.yaml"


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Clear and reload the prompt registry for each test."""
    prompt_lib._REGISTRY.clear()
    yield
    prompt_lib._REGISTRY.clear()


class TestLoad:
    def test_loads_real_prompts_file(self):
        prompt_lib.load(PROMPTS_FILE)
        assert prompt_lib.is_loaded()

    def test_known_prompt_ids_present(self):
        prompt_lib.load(PROMPTS_FILE)
        ids = prompt_lib.list_prompts()
        assert "worker_default" in ids
        assert "worker_with_tools" in ids

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            prompt_lib.load("/nonexistent/prompts.yaml")

    def test_load_from_temp_file(self, tmp_path):
        data = {
            "version": "1.0",
            "prompts": {
                "test_prompt": {
                    "version": "1.0",
                    "description": "test",
                    "template": "Hello {{name}}",
                    "variables": ["name"],
                }
            },
        }
        f = tmp_path / "prompts.yaml"
        f.write_text(yaml.dump(data))
        prompt_lib.load(f)
        assert "test_prompt" in prompt_lib.list_prompts()


class TestRender:
    def setup_method(self):
        prompt_lib.load(PROMPTS_FILE)

    def test_renders_worker_default(self):
        text = prompt_lib.render(
            "worker_default",
            {"agent_name": "TestAgent", "current_date": "2026-06-25"},
        )
        assert "TestAgent" in text
        assert "2026-06-25" in text

    def test_render_with_standard_vars(self):
        vars_ = prompt_lib.standard_vars("MyAgent")
        assert vars_["agent_name"] == "MyAgent"
        assert vars_["current_date"]  # non-empty date string

    def test_unknown_prompt_id_raises(self):
        with pytest.raises(KeyError, match="Unknown prompt id"):
            prompt_lib.render("nonexistent_prompt_id_xyz", {})

    def test_missing_variable_raises(self):
        with pytest.raises(KeyError, match="requires variables"):
            prompt_lib.render("worker_default", {"agent_name": "X"})  # missing current_date

    def test_extra_variables_are_ignored(self):
        # Extra vars beyond what template needs should not raise
        text = prompt_lib.render(
            "worker_default",
            {"agent_name": "A", "current_date": "2026-01-01", "extra": "ignored"},
        )
        assert "A" in text

    def test_rendered_text_has_no_placeholders(self):
        text = prompt_lib.render(
            "worker_default",
            {"agent_name": "Bot", "current_date": "2026-06-25"},
        )
        assert "{{" not in text
        assert "}}" not in text
