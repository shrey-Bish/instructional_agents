"""Textbook-grounded decks keep several frames per outline slide, while the
frontend export needs exactly one speaker note per rendered frame. These tests
pin the note mapping and the routing between the grounded and standard
frame writers."""

from __future__ import annotations

from src.html_slides import parse_speaker_notes
from src.slides import SlideUtils, SlidesDeliberation


def _frame(title: str, body: str = "Body text.") -> str:
    return f"\\begin{{frame}}[fragile]\n\\frametitle{{{title}}}\n{body}\n\\end{{frame}}"


def _deck(*frames: str) -> str:
    return ("\\documentclass{beamer}\n\\title{Clustering}\n\\begin{document}\n"
            "\\frame{\\titlepage}\n" + "\n\n".join(frames) + "\n\\end{document}")


def _delib(retriever=object()):
    d = SlidesDeliberation.__new__(SlidesDeliberation)
    d.name = "Clustering"
    d.retriever = retriever
    d.slides_outline = [{"title": "K-Means"}, {"title": "DBSCAN"}]
    d.latex_dict = {
        0: {"frames": [{"full_frame": _frame("K-Means Algorithm")},
                       {"full_frame": _frame("K-Means Complexity")}]},
        1: {"frames": [{"full_frame": _frame("DBSCAN Density")}]},
    }
    d.slides_script = {0: {"script": "Note for K-Means."}, 1: {"script": "Note for DBSCAN."}}
    return d


def _notes(d, source):
    return {n.title: n.text for n in parse_speaker_notes(d._compile_slides_script(source))}


class TestGroundedNotes:
    def test_one_note_per_frame_with_inserted_frames(self):
        d = _delib()
        src = _deck(_frame("Learning Objectives", "\\begin{itemize}\\item K-Means\\end{itemize}"),
                    _frame("K-Means Algorithm"), _frame("K-Means Complexity"),
                    _frame("DBSCAN Density"), _frame("Key Takeaways", "Recap."))
        notes = _notes(d, src)
        assert len(notes) == 6  # title page + five content frames
        assert notes["K-Means Algorithm"] == "Note for K-Means."
        assert notes["DBSCAN Density"] == "Note for DBSCAN."
        assert notes["K-Means Complexity"].startswith("Present K-Means Complexity.")
        assert notes["Learning Objectives"].startswith("Present Learning Objectives.")
        assert notes["Key Takeaways"].startswith("Present Key Takeaways.")

    def test_script_moves_to_first_surviving_frame(self):
        d = _delib()
        notes = _notes(d, _deck(_frame("K-Means Complexity"), _frame("DBSCAN Density")))
        assert notes["K-Means Complexity"] == "Note for K-Means."

    def test_empty_script_falls_back_to_frame_note(self):
        d = _delib()
        d.slides_script[1] = {"script": "   "}
        notes = _notes(d, _deck(_frame("K-Means Algorithm"), _frame("DBSCAN Density")))
        assert notes["DBSCAN Density"].startswith("Present DBSCAN Density.")

    def test_standard_runs_keep_one_note_per_outline_slide(self):
        d = _delib(retriever=None)
        d.latex_dict = {0: {"frames": [{"full_frame": _frame("K-Means")}]},
                        1: {"frames": [{"full_frame": _frame("DBSCAN")}]}}
        notes = _notes(d, _deck(_frame("K-Means"), _frame("DBSCAN")))
        assert notes == {"Clustering": notes["Clustering"],
                         "K-Means": "Note for K-Means.", "DBSCAN": "Note for DBSCAN."}


class _Agent:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def reset_history(self):
        pass

    def generate_response(self, prompt, stream=False, save_to_history=False):
        self.prompts.append(prompt)
        return self.reply, 0.0, 0


def _writer(retriever, reply):
    d = SlidesDeliberation.__new__(SlidesDeliberation)
    d.retriever = retriever
    d.agents = {"teaching_assistant": _Agent(reply)}
    d.latex_dict, d.slides_outline = {}, [{"title": "K-Means", "description": "d"}]
    d.user_feedback = {"slides": "", "overall": "", "script": ""}
    d.slide_style_guidance = ""
    d.time_slides = d.token_slides = 0
    d._build_per_slide_evidence = lambda *a, **k: ("", "")
    return d


class TestFrameWriterRouting:
    TWO = _frame("K-Means Algorithm") + "\n\n" + _frame("K-Means Complexity")

    def test_grounded_run_keeps_several_frames(self):
        d = _writer(object(), self.TWO)
        d._generate_slide_latex(0, d.slides_outline[0], "draft")
        assert "maximum 3 frames" in d.agents["teaching_assistant"].prompts[0]
        assert [f["title"] for f in d.latex_dict[0]["frames"]] == ["K-Means Algorithm", "K-Means Complexity"]

    def test_standard_run_uses_the_one_frame_writer(self):
        d = _writer(None, self.TWO)
        d._generate_slide_latex(0, d.slides_outline[0], "draft")
        assert "Return exactly one Beamer frame" in d.agents["teaching_assistant"].prompts[0]
        assert len(d.latex_dict[0]["frames"]) == 1

    def test_grounded_prompt_carries_style_and_latex_rules(self):
        p = SlideUtils.generate_grounded_latex_frames_prompt(
            "K-Means", "content", style_guidance="Warm palette.")
        assert "Selected Course Slide Style Guidance:\nWarm palette." in p
        assert "Never nest display-math environments" in p
        assert "maximum 3 frames" in p
