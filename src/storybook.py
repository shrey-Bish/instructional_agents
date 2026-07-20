"""Storybook output mode — generate a printed story-based book instead of
slide decks.

Opt-in end to end: activates only when ``--storybook`` is passed AND the
catalog carries a top-level ``storybook`` section. The foundation phase
(goals -> audience -> syllabus -> chapters) runs unchanged; each processed
chapter then becomes one narrative book chapter written around the catalog's
story bible, and the chapters are bound into a single print-ready PDF
(A5 book layout, grayscale-safe).

Catalog ``storybook`` section (all free-text unless noted):
    title            book title
    subtitle         optional subtitle
    age_range        e.g. "ages 8-11 (Grades 4-6)"
    reading_level    guidance for vocabulary / sentence length
    story_bible      setting, recurring characters, tone, values, and any
                     per-chapter beats the stories must follow
    chapter_words    target story length per chapter, e.g. "600-900"
    extras           optional extra per-chapter block instruction
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# The only structures the writer may emit; the template defines them.
LATEX_RULES = r"""
OUTPUT FORMAT — LaTeX chapter body ONLY (no preamble, no \documentclass, no
\usepackage, no \begin{document}). Use EXACTLY this skeleton, in this order:

\storychapter{<Chapter title>}

<the story, as plain LaTeX paragraphs; you may use \emph{} for emphasis and
dialogue with normal quotes ``like this''. Insert 1-2 illustration placeholders
at strong visual moments as: \illus{<one-line description of the scene>} >

\begin{newwords}
\word{<term>}{<reader-friendly definition>}
... (3-5 words)
\end{newwords}

\begin{thinkaboutit}
\item <question>
... (3-4 items; at least one "What would YOU do?" question)
\end{thinkaboutit}

\begin{tryit}
<one fully paper-based activity with numbered steps; no devices ever>
\end{tryit}

HARD RULES: no other commands or environments than the ones above; escape any
literal % as \% and & as \&; no markdown syntax; no real product or brand
names; nothing color-dependent.
"""

BOOK_TEMPLATE = r"""\documentclass[@PTSIZE@]{book}
\usepackage[a5paper,margin=16mm,bottom=19mm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{mathpazo}
\usepackage{parskip}
\usepackage{graphicx}
\usepackage{xcolor}
\pagestyle{plain}
\setlength{\emergencystretch}{2em}
\newcommand{\storychapter}[1]{\chapter*{#1}%
\vspace{-1.2em}\noindent\rule{\linewidth}{1.1pt}\\[-0.82em]
\noindent\rule{\linewidth}{0.4pt}\vspace{0.9em}%
\addcontentsline{toc}{chapter}{#1}}
\newcommand{\storyimg}[2]{\begin{center}%
\includegraphics[width=0.94\linewidth]{#1}\end{center}}
\newcommand{\illus}[1]{\begin{center}\fbox{\parbox{0.86\linewidth}{\centering
\vspace{9mm}\emph{[Illustration: #1]}\vspace{9mm}}}\end{center}}
\newcommand{\activityhead}[1]{\par\vspace{1.1em}%
{\color{black!60}\hrule height 0.7pt}\vspace{0.55em}%
{\large\scshape #1}\par\vspace{0.35em}}
\newcommand{\word}[2]{\item[\textbf{#1}] #2}
\newenvironment{newwords}{\activityhead{New Words}\begin{description}}{\end{description}}
\newenvironment{thinkaboutit}{\activityhead{Think About It}\begin{enumerate}}{\end{enumerate}}
\newenvironment{tryit}{\activityhead{Try It}}{}
\newenvironment{godeeper}{\activityhead{Go Deeper}}{}
\title{{\Huge @TITLE@}\\[0.6em]\large @SUBTITLE@}
\author{}
\date{}
\begin{document}
\maketitle
\tableofcontents
@CHAPTERS@
\end{document}
"""


def sanitize(tex: str) -> str:
    """Normalize Unicode punctuation the T1 font setup drops silently."""
    for a, b in (("’", "'"), ("‘", "`"), ("“", "``"),
                 ("”", "''"), ("—", "---"), ("–", "--"),
                 ("…", "\\dots{}")):
        tex = tex.replace(a, b)
    return tex


def chapter_prompt(spec: Dict[str, str], chapter_idx: int, total: int,
                   chapter: Dict[str, str], course_context: str = "") -> str:
    """Build the story-chapter prompt from the catalog spec + a processed
    chapter (title/description from the syllabus phase)."""
    context_block = (
        f"\nCOURSE CONTEXT (teaching goals this chapter must carry, woven "
        f"naturally into the narrative — never as a lecture):\n{course_context}\n"
        if course_context else ""
    )
    extras = spec.get("extras", "")
    return f"""You are writing chapter {chapter_idx} of {total} of the storybook
"{spec.get('title', 'Storybook')}" for {spec.get('age_range', 'young readers')}.
Reading level: {spec.get('reading_level', 'plain, age-appropriate language')}.

STORY BIBLE (follow the setting, recurring characters, and any chapter beats
exactly):
{spec.get('story_bible', '')}

THIS CHAPTER'S TOPIC (from the course syllabus):
Title: {chapter.get('title', '')}
Description: {chapter.get('description', '')}
{context_block}
Story length: {spec.get('chapter_words', '800-1200')} words. {extras}
{LATEX_RULES}"""


class StorybookWriter:
    """Writes one story chapter per processed chapter and binds the book."""

    def __init__(self, llm, spec: Dict[str, str], output_dir: str):
        self.llm = llm
        self.spec = spec
        self.output_dir = Path(output_dir)
        self.time_total = 0.0
        self.token_total = 0

    def write_chapter(self, chapter_idx: int, total: int,
                      chapter: Dict[str, str],
                      course_context: str = "") -> str:
        prompt = chapter_prompt(self.spec, chapter_idx, total, chapter,
                                course_context)
        response, elapsed, tokens = self.llm.generate_response(
            [{"role": "user", "content": prompt}])
        self.time_total += elapsed
        self.token_total += tokens
        body = response.strip()
        body = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", body)
        return sanitize(body)

    def save_chapter(self, chapter_idx: int, tex: str) -> Path:
        d = self.output_dir / f"chapter_{chapter_idx}"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "story.tex"
        p.write_text(tex, encoding="utf-8")
        return p

    def bind_book(self, compile_pdf: bool = True) -> Optional[Path]:
        """Assemble book.tex from every chapter_N/story.tex and compile."""
        chapters: List[int] = sorted(
            int(m.group(1))
            for p in self.output_dir.glob("chapter_*/story.tex")
            if (m := re.match(r"chapter_(\d+)$", p.parent.name))
        )
        if not chapters:
            return None
        bookdir = self.output_dir / "book"
        bookdir.mkdir(exist_ok=True)
        inputs = "\n".join(
            f"\\input{{../chapter_{c}/story.tex}}" for c in chapters)
        doc = (BOOK_TEMPLATE
               .replace("@PTSIZE@", self.spec.get("pt_size", "11pt"))
               .replace("@TITLE@", self.spec.get("title", "Storybook"))
               .replace("@SUBTITLE@", self.spec.get("subtitle", ""))
               .replace("@CHAPTERS@", inputs))
        tex_path = bookdir / "book.tex"
        tex_path.write_text(doc, encoding="utf-8")
        if not compile_pdf:
            return tex_path
        result = subprocess.run(
            ["tectonic", "book.tex"], cwd=bookdir,
            capture_output=True, text=True)
        if result.returncode != 0:
            print("[storybook] tectonic failed; book.tex kept for manual "
                  "compile.\n" + result.stdout[-1500:])
            return tex_path
        print(f"[storybook] book compiled -> {bookdir / 'book.pdf'}")
        return bookdir / "book.pdf"
