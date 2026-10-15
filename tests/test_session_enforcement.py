"""Session-deck enforcement for catalogs that opt in with ``engagement_style``.

The soft directives alone were not followed (decks came out at twice the slide
cap, ~100 visible words per frame, no worked examples, answers printed on the
question slide), so the outline is fixed and typed, and every written slide is
checked against hard caps with one revision request. Standard catalogs never
reach this code; their prompts are pinned byte-identical.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src import slides as S
from src.slides import SlidesDeliberation


def _delib(engagement: str | None) -> SlidesDeliberation:
    d = SlidesDeliberation.__new__(SlidesDeliberation)
    d.catalog_dict = {"slides_length": 30}
    if engagement is not None:
        d.catalog_dict["engagement_style"] = engagement
    d.retriever = None
    d.section_ids = []
    d.user_feedback = {"slides": "", "overall": ""}
    d.time_slides = 0
    d.token_slides = 0
    d.latex_dict = {}
    d.slides_outline = []
    return d


def _outline_prompt(d, response="[]"):
    agent = MagicMock()
    agent.generate_response.return_value = (response, 0.0, 0)
    d.agents = {"instructional_designer": agent}
    d._generate_slides_outline({"title": "T", "description": "D"})
    return agent


GOOD_OUTLINE = [
    {"slide_id": 1, "kind": "objective", "title": "Objective", "description": "d"},
    {"slide_id": 2, "kind": "moment", "title": "A record moment", "description": "d"},
    {"slide_id": 3, "kind": "worked_example", "title": "Example one", "description": "d"},
    {"slide_id": 4, "kind": "worked_example", "title": "Example two", "description": "d"},
    {"slide_id": 5, "kind": "concept", "title": "Concept", "description": "d"},
    {"slide_id": 6, "kind": "worked_example", "title": "Example three", "description": "d"},
    {"slide_id": 7, "kind": "table", "title": "One table", "description": "d"},
    {"slide_id": 8, "kind": "worked_example", "title": "Example four", "description": "d"},
    {"slide_id": 9, "kind": "concept", "title": "Another concept", "description": "d"},
    {"slide_id": 10, "kind": "discussion", "title": "Cases", "description": "d"},
    {"slide_id": 11, "kind": "check", "title": "Check", "description": "d"},
    {"slide_id": 12, "kind": "answers", "title": "Answers", "description": "d"},
]


class TestOutlineBlueprint:
    def test_standard_catalog_prompt_unchanged(self):
        a = _outline_prompt(_delib(None))
        p = a.generate_response.call_args.kwargs["prompt"]
        assert "SESSION BLUEPRINT" not in p
        assert "Generate about 10 slides" in p
        assert '"kind"' not in p
        b = _outline_prompt(_delib(""))
        assert p == b.generate_response.call_args.kwargs["prompt"]

    def test_session_prompt_is_fixed_and_typed(self):
        a = _outline_prompt(_delib("lean"))
        p = a.generate_response.call_args.kwargs["prompt"]
        assert "SESSION BLUEPRINT" in p
        assert "Output EXACTLY 12 items" in p
        assert "Generate about" not in p
        assert '"kind"' in p

    def test_bad_outline_gets_one_revision_then_kinds_normalised(self):
        import json
        bad = GOOD_OUTLINE[:5]
        agent = MagicMock()
        agent.generate_response.side_effect = [
            (json.dumps(bad), 0.0, 0), (json.dumps(GOOD_OUTLINE), 0.0, 0),
        ]
        d = _delib("lean")
        d.agents = {"instructional_designer": agent}
        d._generate_slides_outline({"title": "T", "description": "D"})
        assert agent.generate_response.call_count == 2
        assert "REVISION REQUIRED" in agent.generate_response.call_args.kwargs["prompt"]
        assert len(d.slides_outline) == 12
        assert [s["kind"] for s in d.slides_outline][-3:] == ["discussion", "check", "answers"]
        assert d._session_retries == 0

    def test_good_outline_no_revision(self):
        import json
        agent = _outline_prompt(_delib("lean"), json.dumps(GOOD_OUTLINE))
        assert agent.generate_response.call_count == 1


class TestOutlineValidator:
    def test_good(self):
        assert S._validate_session_outline(GOOD_OUTLINE) == []

    def test_problems_named(self):
        bad = [dict(x) for x in GOOD_OUTLINE]
        bad[2]["kind"] = "concept"
        bad[-1]["kind"] = "check"
        probs = S._validate_session_outline(bad)
        assert any("worked_example" in p for p in probs)
        assert any("last three" in p for p in probs)
        assert S._validate_session_outline([]) == ["the outline is empty"]


class TestFrameWords:
    def test_counts_body_only(self):
        f = (r"\begin{frame}[fragile]\frametitle{A long title that must not count}"
             r"\begin{itemize}\item one two three \item four five\end{itemize}"
             r"\url{https://example.org/very/long/path} % a comment with words"
             r"\end{frame}")
        assert S._frame_body_words(f) == 5

    def test_inline_title_form(self):
        f = r"\begin{frame}[fragile]{Inline title words} alpha beta \end{frame}"
        assert S._frame_body_words(f) == 2


def _frame(body, title="T", opts="fragile"):
    return "\\begin{frame}[%s]\n\\frametitle{%s}\n%s\n\\end{frame}" % (opts, title, body)


class TestFrameProblems:
    def test_lean_concept_passes(self):
        assert S._session_frame_problems([_frame("one idea in a few words")], "concept") == []

    def test_word_cap_and_shrink(self):
        heavy = _frame(" ".join(["word"] * 60), opts="fragile,shrink=12")
        probs = S._session_frame_problems([heavy], "concept")
        assert any("visible words" in p for p in probs)
        assert any("shrink" in p for p in probs)

    def test_frame_count_caps(self):
        fr = [_frame("a b"), _frame("c d"), _frame("e f")]
        assert any("maximum" in p for p in S._session_frame_problems(fr, "concept"))
        assert S._session_frame_problems(fr[:2], "concept") == []

    def test_check_needs_question_and_no_answer(self):
        fr = [_frame("Scenario text. Answer: it is the EHR.", title="Knowledge check 1"),
              _frame("Scenario. Which system stores it?", title="Knowledge check 2"),
              _frame("Scenario. Is it structured?", title="Knowledge check 3")]
        probs = S._session_frame_problems(fr, "check")
        assert any("asks no question" in p for p in probs)
        assert any("contains an answer" in p for p in probs)
        assert not any("must be titled" in p for p in probs)

    def test_scenario_frames_need_recognisable_titles(self):
        fr = [_frame("Case 1 setup. Which copy would you trust?", title="Which Copy Fits?"),
              _frame("Case 3 setup. What would you check?", title="Discussion cases 3-4")]
        probs = S._session_frame_problems(fr, "discussion")
        assert [p for p in probs if "must be titled 'Discussion cases" in p and "frame 1" in p]
        assert not [p for p in probs if "frame 2" in p]

    def test_worked_example_needs_verbatim_fragment(self):
        ev = "EXCERPT: The legal medical record is the primary documentation of direct patient care provided by the organization."
        good = _frame(r"\begin{block}{Record fragment} the primary documentation of direct patient care provided by the organization \end{block} One line.")
        bad = _frame(r"\begin{block}{Record fragment} something the excerpts never said at all here \end{block} One line.")
        none = _frame("No block at all, just prose about records.")
        assert S._session_frame_problems([good], "worked_example", ev) == []
        assert any("VERBATIM" in p for p in S._session_frame_problems([bad], "worked_example", ev))
        assert any("VERBATIM" in p for p in S._session_frame_problems([none], "worked_example", ev))

    def test_table_frame_gets_wider_cap(self):
        body = r"\begin{tabular}{ll}" + " ".join(["cell"] * 80) + r"\end{tabular}"
        assert S._session_frame_problems([_frame(body)], "concept") == []


class TestLatexWriterEnforcement:
    def _run(self, engagement, responses, kind="concept"):
        d = _delib(engagement)
        agent = MagicMock()
        agent.generate_response.side_effect = [(r, 0.0, 0) for r in responses]
        d.agents = {"teaching_assistant": agent}
        d._build_per_slide_evidence = lambda q, artifact="slide": ("", [])
        slide = {"title": "S", "description": "d", "kind": kind}
        d._generate_slide_latex(0, slide, "draft")
        return d, agent

    def test_standard_catalog_single_call_three_frames_allowed(self):
        d, agent = self._run(None, [_frame(" ".join(["w"] * 120))])
        assert agent.generate_response.call_count == 1
        assert "maximum 3 frames" in agent.generate_response.call_args.kwargs["prompt"]
        assert "SESSION SLIDE RULES" not in agent.generate_response.call_args.kwargs["prompt"]

    def test_heavy_frame_gets_one_revision_and_lean_version_kept(self):
        heavy = _frame(" ".join(["w"] * 120))
        lean = _frame("one idea only")
        d, agent = self._run("lean", [heavy, lean])
        assert agent.generate_response.call_count == 2
        second = agent.generate_response.call_args.kwargs["prompt"]
        assert "REVISION REQUIRED" in second and "visible words" in second
        assert d.latex_dict[0]["frames"][0]["full_frame"] == lean
        assert d._session_retries == 1

    def test_worse_revision_keeps_original(self):
        heavy = _frame(" ".join(["w"] * 120))
        worse = _frame(" ".join(["w"] * 120), opts="fragile,shrink=10")
        d, agent = self._run("lean", [heavy, worse])
        assert d.latex_dict[0]["frames"][0]["full_frame"] == heavy

    def test_retry_budget_bounds_cost(self):
        d = _delib("lean")
        d._session_retries = S._SESSION_MAX_RETRIES
        agent = MagicMock()
        agent.generate_response.return_value = (_frame(" ".join(["w"] * 120)), 0.0, 0)
        d.agents = {"teaching_assistant": agent}
        d._build_per_slide_evidence = lambda q, artifact="slide": ("", [])
        d._generate_slide_latex(0, {"title": "S", "kind": "concept"}, "draft")
        assert agent.generate_response.call_count == 1

    def test_kind_sets_max_frames(self):
        three = "\n\n".join([_frame("Scenario. Which system? one", title="Knowledge check 1"),
                             _frame("Scenario. Structured? two", title="Knowledge check 2"),
                             _frame("Scenario. Who permitted? three", title="Knowledge check 3")])
        d, agent = self._run("lean", [three], kind="check")
        assert "maximum 3 frames" in agent.generate_response.call_args.kwargs["prompt"]
        assert agent.generate_response.call_count == 1


class TestDraftDirective:
    def _prompt(self, engagement, kind="worked_example"):
        d = _delib(engagement)
        agent = MagicMock()
        agent.generate_response.return_value = ("draft", 0.0, 0)
        d.agents = {"teaching_faculty": agent}
        d._build_per_slide_evidence = lambda q, artifact="slide": ("", [])
        d._generate_slide_draft({"title": "S", "description": "d", "kind": kind}, [], {"title": "T"})
        return agent.generate_response.call_args.kwargs["prompt"]

    def test_absent_no_job_line(self):
        assert "THIS SLIDE'S JOB" not in self._prompt(None)

    def test_present_carries_kind_job(self):
        p = self._prompt("lean")
        assert "THIS SLIDE'S JOB (worked_example)" in p
        assert "Record fragment" in p
