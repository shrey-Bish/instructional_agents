"""Storybook output mode (--storybook + catalog 'storybook' section).

The mode must be inert by default: without the flag the chapter phase runs
the slide path exactly as before, and standard catalogs (no 'storybook'
section) yield an empty spec.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ADDIE import ADDIE, ADDIERunner
from src.storybook import StorybookWriter, chapter_prompt, sanitize


def _runner(storybook: bool, tmp_path):
    r = ADDIERunner.__new__(ADDIERunner)
    r.addie = MagicMock()
    r.addie.storybook = storybook
    r.addie.catalog_dict = {"storybook": {"title": "T"}}
    r.resume = False
    r.output_dir = str(tmp_path)
    r.chapters = [{"title": "W1", "description": "d"}]
    return r


class TestGate:
    def test_default_path_unchanged(self, tmp_path):
        r = _runner(False, tmp_path)
        called = []
        r._run_slides_generation_with_retry = lambda ch, i, d: called.append(i)
        r._cleanup_checkpoints = lambda: None
        with patch("src.ADDIE.LaTeXCompiler") as C:
            C.return_value.compile_all = lambda: None
            r.run_chapter_deliberations()
        assert called == [0]

    def test_storybook_path_skips_slides(self, tmp_path):
        r = _runner(True, tmp_path)
        r._run_slides_generation_with_retry = lambda *a: (_ for _ in ()).throw(
            AssertionError("slide path must not run in storybook mode"))
        with patch.object(ADDIERunner, "_run_storybook_chapters") as sb:
            r.run_chapter_deliberations()
        sb.assert_called_once()

    def test_addie_defaults_off(self):
        with patch("src.ADDIE.LLM"):
            a = ADDIE("T")
        assert a.storybook is False
        assert a.catalog_dict.get("storybook", {}) == {}

    def test_catalog_without_section_yields_empty_spec(self):
        with patch("src.ADDIE.LLM"):
            a = ADDIE.__new__(ADDIE)
            a.catalog = True
            a.set_catalog({
                "course_structure": {}, "institutional_requirements": {},
                "teaching_constraints": {"max_slide_count": "30"},
                "student_profile": {}, "prior_feedback": {},
                "assessment_design": {}, "instructor_preferences": {},
            })
        assert a.catalog_dict["storybook"] == {}


class TestWriter:
    def test_prompt_carries_spec_and_chapter(self):
        p = chapter_prompt(
            {"title": "B", "age_range": "ages 8-11", "story_bible": "A village.",
             "chapter_words": "600-900"},
            2, 8, {"title": "W2: Data", "description": "Reading tables."})
        assert "chapter 2 of 8" in p
        assert "A village." in p
        assert "W2: Data" in p
        assert "600-900" in p
        assert "\\storychapter" in p          # output contract present

    def test_write_chapter_strips_fences_and_sanitizes(self, tmp_path):
        llm = MagicMock()
        llm.generate_response.return_value = (
            "```latex\n\\storychapter{Hi}\nIt’s fine.\n```", 0.1, 5)
        w = StorybookWriter(llm, {}, str(tmp_path))
        tex = w.write_chapter(1, 8, {"title": "t", "description": "d"})
        assert tex.startswith("\\storychapter{Hi}")
        assert "’" not in tex and "It's fine." in tex
        # llm called with a chat message list, not a bare string
        arg = llm.generate_response.call_args[0][0]
        assert isinstance(arg, list) and arg[0]["role"] == "user"

    def test_bind_book_assembles_all_chapters(self, tmp_path):
        w = StorybookWriter(MagicMock(), {"title": "My Book"}, str(tmp_path))
        w.save_chapter(1, "\\storychapter{One}")
        w.save_chapter(2, "\\storychapter{Two}")
        tex = w.bind_book(compile_pdf=False)
        content = tex.read_text(encoding="utf-8")
        assert "../chapter_1/story.tex" in content
        assert "../chapter_2/story.tex" in content
        assert "My Book" in content

    def test_sanitize(self):
        assert sanitize("a—b’c") == "a---b'c"
