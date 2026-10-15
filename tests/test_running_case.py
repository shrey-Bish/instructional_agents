"""Opt-in running-case injection for case-based courses.

A catalog may carry a top-level ``running_case`` narrative; when present, the
slide writer builds the outline and each slide around that case. When absent
(every standard catalog), the prompts are byte-identical to the vanilla
release — pinned here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.slides import SlidesDeliberation


def _delib(running_case: str | None) -> SlidesDeliberation:
    d = SlidesDeliberation.__new__(SlidesDeliberation)
    d.catalog_dict = {"slides_length": 30}
    if running_case is not None:
        d.catalog_dict["running_case"] = running_case
    d.retriever = None
    d.section_ids = []
    d.user_feedback = {"slides": "", "overall": ""}
    d.time_slides = 0
    d.token_slides = 0
    return d


def _outline_prompt(d: SlidesDeliberation) -> str:
    agent = MagicMock()
    agent.generate_response.return_value = ("[]", 0.0, 0)
    d.agents = {"instructional_designer": agent}
    d.slides_outline = []
    d._generate_slides_outline({"title": "T", "description": "D"})
    return agent.generate_response.call_args.kwargs["prompt"]


class TestOutlineGate:
    def test_absent_case_prompt_has_no_case_block(self):
        prompt = _outline_prompt(_delib(None))
        assert "CASE-BASED OUTLINE" not in prompt
        assert "running case" not in prompt.lower()

    def test_empty_case_is_treated_as_absent(self):
        assert "CASE-BASED OUTLINE" not in _outline_prompt(_delib("  "))

    def test_present_case_injects_block_with_narrative(self):
        prompt = _outline_prompt(_delib("Maria the nurse notices an omission."))
        assert "CASE-BASED OUTLINE" in prompt
        assert "Maria the nurse notices an omission." in prompt

    def test_absent_vs_empty_prompts_byte_identical(self):
        assert _outline_prompt(_delib(None)) == _outline_prompt(_delib(""))


class TestSessionStructureGate:
    """Opt-in catalog ``session_structure`` — organizes the outline into
    labeled session segments. Same gating contract as running_case."""

    def _prompt(self, note):
        d = _delib(None)
        if note is not None:
            d.catalog_dict["session_structure"] = note
        return _outline_prompt(d)

    def test_absent_no_block_and_byte_identical(self):
        assert "SESSION STRUCTURE" not in self._prompt(None)
        assert self._prompt(None) == self._prompt("")

    def test_present_injects_plan(self):
        p = self._prompt("Split into 5 sessions: pros, cons, safety, roles, synthesis.")
        assert "SESSION STRUCTURE" in p
        assert "Session N:" in p
        assert "Split into 5 sessions" in p


class TestEngagementStyleGate:
    """Opt-in catalog ``engagement_style`` — hooks, vignettes, discussion
    cases, on-slide URLs. Same gating contract as session_structure."""

    def _prompt(self, note):
        d = _delib(None)
        if note is not None:
            d.catalog_dict["engagement_style"] = note
        return _outline_prompt(d)

    def test_absent_no_block_and_byte_identical(self):
        assert "ENGAGEMENT STYLE" not in self._prompt(None)
        assert self._prompt(None) == self._prompt("")

    def test_present_injects_directives(self):
        p = self._prompt("Open with a real hook; vignettes; URLs on slides.")
        assert "ENGAGEMENT STYLE" in p
        assert "Open with a real hook" in p


class TestDensityRuleGate:
    """The grounded outline's dense-slide rule yields to an opt-in
    ``engagement_style`` (which owns density: lean, one idea per slide)."""

    def test_default_is_dense(self):
        rule = _delib(None)._density_rule()
        assert "DENSE" in rule and "4–6 teaching bullets" in rule

    def test_engagement_style_takes_over(self):
        d = _delib(None)
        d.catalog_dict["engagement_style"] = "lean slides"
        rule = d._density_rule()
        assert "ENGAGEMENT STYLE" in rule and "4–6 teaching bullets" not in rule

    def test_blank_engagement_style_is_absent(self):
        d = _delib(None)
        d.catalog_dict["engagement_style"] = "  "
        assert "DENSE" in d._density_rule()

    def test_engagement_mode_flag(self):
        d = _delib(None)
        assert d._engagement_mode() is False
        d.catalog_dict["engagement_style"] = "lean"
        assert d._engagement_mode() is True


class TestSlideDraftGate:
    def _draft_prompt(self, case: str | None) -> str:
        d = _delib(case)
        agent = MagicMock()
        agent.generate_response.return_value = ("draft", 0.0, 0)
        d.agents = {"teaching_faculty": agent}
        d._build_per_slide_evidence = lambda q, artifact="slide": ("", [])
        d._generate_slide_draft(
            {"title": "S", "description": "d"}, [], {"title": "T"})
        return agent.generate_response.call_args.kwargs["prompt"]

    def test_absent_case_no_directive(self):
        assert "Running case:" not in self._draft_prompt(None)

    def test_present_case_directive_carries_narrative(self):
        p = self._draft_prompt("Maria hesitates to flag the note.")
        assert "Running case:" in p
        assert "Maria hesitates to flag the note." in p
