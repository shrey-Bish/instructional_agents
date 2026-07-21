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
    illustrate       bool — generate grayscale line-art for every \\illus
                     placeholder (image model) and embed it in the book
    illustration_style  optional style override for the generated art
"""
from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

ILLUSTRATION_STYLE = (
    "Black-and-white pen-and-ink line art illustration for a children's "
    "storybook, in the style of classic chapter-book illustrations. Clean "
    "confident outlines, simple cross-hatching for shadow, white background. "
    "Must print clearly in grayscale. No text, no captions, no speech "
    "bubbles, no borders."
)

# The only structures the writer may emit; the template defines them.
LATEX_RULES = r"""
OUTPUT FORMAT — LaTeX chapter body ONLY (no preamble, no \documentclass, no
\usepackage, no \begin{document}). Use EXACTLY this skeleton, in this order:

\storychapter{<Chapter title>}

<the story, as plain LaTeX paragraphs; you may use \emph{} for emphasis and
dialogue with normal quotes ``like this''. Keep paragraphs SHORT (1-3
sentences) so young readers get frequent breaks. Insert 2 illustration
placeholders as \illus{<one-line description of the scene>} — each placed
IMMEDIATELY after the paragraph whose scene it shows (one early, one later;
never bunched at the chapter's end)>

\begin{newwords}
\word{<term>}{<reader-friendly definition>}
... (3-5 words)
\end{newwords}

\begin{thinkaboutit}
\item <question>
... (3-4 items; at least one "What would YOU do?" question)
\end{thinkaboutit}

\begin{tryit}
<one-line setup sentence, then the activity's numbered steps as \item lines
inside \begin{enumerate} ... \end{enumerate}; fully paper-based, no devices>
\end{tryit}

HARD RULES: no other commands or environments than the ones above; escape any
literal % as \% and & as \&; no markdown syntax; no real product or brand
names; nothing color-dependent.
"""

# oneside: the default two-sided book class inserts blank verso pages before
# the TOC and chapters -- unwanted in a print-at-school A5 booklet.
BOOK_TEMPLATE = r"""\documentclass[@PTSIZE@,oneside]{book}
\usepackage[a5paper,margin=16mm,bottom=19mm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{mathpazo}
\usepackage{parskip}
\usepackage{graphicx}
\usepackage{xcolor}
% Accent colors chosen to stay readable when printed in grayscale
% (dark green ~ 45%% gray, warm amber ~ 60%% gray; tints stay light).
\definecolor{storygreen}{RGB}{27,94,54}
\definecolor{storyamber}{RGB}{196,101,25}
\pagestyle{plain}
\setlength{\emergencystretch}{2em}
\linespread{1.14}
\setlength{\parskip}{0.62em}
\newcommand{\storychapter}[1]{\chapter*{\color{storygreen}#1}%
\vspace{-1.2em}\noindent{\color{storyamber}\rule{\linewidth}{1.4pt}}\\[-0.8em]
\noindent{\color{storyamber}\rule{0.55\linewidth}{0.5pt}}\vspace{0.9em}%
\addcontentsline{toc}{chapter}{#1}}
\newcommand{\storyimg}[2]{\par\medskip\begin{center}%
\includegraphics[width=0.92\linewidth]{#1}\end{center}\medskip\par}
\newcommand{\illus}[1]{\par\medskip\begin{center}\fbox{\parbox{0.82\linewidth}{\centering
\vspace{4mm}\emph{\small [Illustration: #1]}\vspace{4mm}}}\end{center}\medskip\par}
\newcommand{\activityhead}[1]{\par\vspace{1.05em}\noindent%
\colorbox{storygreen!12}{\parbox{\dimexpr\linewidth-2\fboxsep}{%
\vspace{1pt}{\large\scshape\color{storygreen}#1}\vspace{1pt}}}\par\vspace{0.4em}}
\newcommand{\word}[2]{\item[\textcolor{storygreen}{\textbf{#1}}] #2}
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


def illustrate_book(output_dir, spec: Dict[str, str], image_client=None) -> int:
    """Generate line-art for every ``\\illus`` placeholder across the book's
    chapters and rewrite them to ``\\storyimg`` embeds.

    Idempotent: already-rewritten macros are untouched and existing image
    files are never regenerated. Returns the number of embedded images.
    """
    out = Path(output_dir)
    imgdir = out / "book" / "images"
    style = spec.get("illustration_style") or ILLUSTRATION_STYLE
    context = spec.get("story_bible", "")
    if image_client is None:
        from openai import OpenAI
        image_client = OpenAI()
    count = 0
    for tex in sorted(out.glob("chapter_*/story.tex")):
        chap = int(re.match(r"chapter_(\d+)$", tex.parent.name).group(1))
        text = tex.read_text(encoding="utf-8")
        idx = 0

        def repl(m: re.Match) -> str:
            nonlocal idx, count
            idx += 1
            name = f"ch{chap}_{idx}.png"
            png = imgdir / name
            if not png.exists():
                imgdir.mkdir(parents=True, exist_ok=True)
                print(f"[storybook] illustrating {name}: {m.group(1)[:60]}...")
                resp = image_client.images.generate(
                    model="gpt-image-1",
                    prompt=(f"{style}\nCharacters and setting (keep "
                            f"consistent): {context}\nScene to draw: "
                            f"{m.group(1)}"),
                    size="1536x1024", quality="medium", n=1)
                png.write_bytes(base64.b64decode(resp.data[0].b64_json))
            count += 1
            return f"\\storyimg{{images/{name}}}{{{m.group(1)}}}"

        new = re.sub(r"\\illus\{([^}]*)\}", repl, text)
        if new != text:
            tex.write_text(new, encoding="utf-8")
    return count


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
        # Storybook chapters carry story titles, not course scheduling — strip
        # any "Week N:" prefix the syllabus phase leaked into the title.
        tex = re.sub(r"(\\storychapter\{)\s*Week\s+\d+\s*:\s*", r"\1", tex)
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
