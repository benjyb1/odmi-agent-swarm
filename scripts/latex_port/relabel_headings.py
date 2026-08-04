r"""Normalise headings and labels across the chapter files.

- Removes the two empty \section{} paragraphs, which are stray Word
  formatting; left in place they would renumber every later section.
- Replaces pandoc's slug labels (which carry cc/cl residue from the
  colour sentinels, e.g. ccdata-leakage-controlscc) with a systematic
  scheme: ch: for chapters, sec: for sections, app: for appendices.
- Restructures the appendix: the docx renders appendices as sections
  "8.5 E. Prior Work ...", doubling the label. Here each lettered
  section becomes an appendix \chapter with the manual letter dropped,
  after an unnumbered Appendices page holding the chapter's preamble.

The docx-section-number -> label mapping this file encodes is the
ground truth check_refs.py verifies against.

Usage: python3 relabel_headings.py latex_dir
"""

import re
import sys
from pathlib import Path

CHAPTER_LABELS = {
    "Introduction": "ch:introduction",
    "Background and Related Work": "ch:background",
    "Approach and Methodology": "ch:methodology",
    "Results": "ch:results",
    "Discussion": "ch:discussion",
    "Conclusion": "ch:conclusion",
    "References": "ch:references",
}

# docx §number -> (title, label). The order within each file must match
# the docx TOC; relabel asserts it.
SECTION_LABELS = {
    "1.1": ("Domain", "sec:domain"),
    "1.2": ("Motivation", "sec:motivation"),
    "1.3": ("The Open-World Problem", "sec:open-world"),
    "1.4": ("Approach", "sec:approach"),
    "1.5": ("Research Questions", "sec:research-questions"),
    "1.6": ("Contributions", "sec:contributions"),
    "1.7": ("Report Structure", "sec:report-structure"),
    "2.1": ("The ODMI as an Assessment", "sec:odmi-assessment"),
    "2.2": ("Criteria for an Automated System", "sec:criteria"),
    "2.3": ("Limitations of LLMs in Truth-Seeking", "sec:llm-limitations"),
    "2.4": ("Methods towards Verification", "sec:verification-methods"),
    "2.5": ("Multi-Agent Debate for Verification", "sec:debate"),
    "2.6": ("Allowing for Abstention", "sec:abstention"),
    "2.7": ("Multilingual Evidence Retrieval", "sec:multilingual"),
    "2.8": ("Research Gap", "sec:research-gap"),
    "3.1": ("System Architecture", "sec:architecture"),
    "3.2": ("The Agent Loop", "sec:agent-loop"),
    "3.3": ("Retrieval", "sec:retrieval"),
    "3.4": ("Ground Truth and Its Limits", "sec:ground-truth"),
    "3.5": ("Deterministic Tool for Catalogue Questions", "sec:catalogue-tool"),
    "3.6": ("Data-Leakage Controls", "sec:leakage-controls"),
    "3.7": ("Evaluation Set", "sec:evaluation-set"),
    "3.8": ("Experiments", "sec:experiments"),
    "3.9": ("Metrics", "sec:metrics"),
    "4.1": ("Convergent Validity", "sec:convergent-validity"),
    "4.2": ("Selectivity", "sec:selectivity"),
    "4.3": ("Attributability", "sec:attributability"),
    "4.4": ("Subgroup Equity", "sec:subgroup-equity"),
    "4.5": ("Generalisability", "sec:generalisability"),
    "4.6": ("Reproducibility", "sec:reproducibility"),
    "4.7": ("Ablation", "sec:ablation"),
    "4.8": ("Operational Cost and Runtime", "sec:cost-runtime"),
    "4.9": ("Reconstructing the Index", "sec:reconstruction"),
    "5.1": ("The Scorecard", "sec:scorecard"),
    "5.2": ("Debate in an ODMI Environment", "sec:debate-odmi"),
    "5.3": ("Reformulating the ODMI", "sec:reformulation"),
    "5.4": ("Threats to Validity", "sec:threats"),
    "5.5": ("Legal, Social, Ethical and Professional Issues", "sec:lsep"),
}

# Appendix letter -> (docx section title, new chapter title, label)
APPENDIX_CHAPTERS = [
    ("A", "A. Full Failure-Mode Register (FM-01 to FM-34)",
     "Full Failure-Mode Register (FM-01 to FM-34)", "app:failure-register"),
    ("B", "B. Pipeline Detail: Abstention Reasons, Evidence Gates and the "
     "False-Positive Audit",
     "Pipeline Detail: Abstention Reasons, Evidence Gates and the "
     "False-Positive Audit", "app:pipeline-detail"),
    ("C", "C. Experiments", "Experiments", "app:experiments"),
    ("D", "D. Out-of-Reach Questions", "Out-of-Reach Questions",
     "app:out-of-reach"),
    ("E", "E. Prior Work Scored Against the Six Criteria, with "
     "Justifications",
     "Prior Work Scored Against the Six Criteria, with Justifications",
     "app:prior-work-scored"),
    ("F", "F. Baselines", "Baselines", "app:baselines"),
    ("G", "G. The Full Question Bank", "The Full Question Bank",
     "app:question-bank"),
    ("H", "H. The Catalogue Recompute in Full",
     "The Catalogue Recompute in Full", "app:catalogue-recompute"),
    ("I", "I. Development-Set Results", "Development-Set Results",
     "app:dev-results"),
    ("J", "J. Figures Not Used in the Body", "Figures Not Used in the Body",
     "app:unused-figures"),
]

FILE_SECTIONS = {
    "01-introduction.tex": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"],
    "02-background-and-related-work.tex":
        ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8"],
    "03-approach-and-methodology.tex":
        ["3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9"],
    "04-results.tex":
        ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"],
    "05-discussion.tex": ["5.1", "5.2", "5.3", "5.4", "5.5"],
}


def relabel_file(path: Path, numbers: list) -> None:
    text = path.read_text(encoding="utf-8")

    n_empty = len(re.findall(r"\\section\{\}(\\label\{[^}]*\})?", text))
    text = re.sub(r"\\section\{\}(\\label\{[^}]*\})?\s*\n", "", text)

    m = re.match(r"\\chapter\{([^}]+)\}", text)
    title = m.group(1)
    text = re.sub(r"^\\chapter\{([^}]+)\}(\\label\{[^}]*\})?",
                  lambda mm: f"\\chapter{{{mm.group(1)}}}"
                  f"\\label{{{CHAPTER_LABELS[title]}}}", text)

    found = re.findall(r"\\section\{([^}]*)\}", text)
    expected = [SECTION_LABELS[n][0] for n in numbers]
    assert found == expected, (path.name, found, expected)

    for num in numbers:
        sec_title, label = SECTION_LABELS[num]
        pat = (r"\\section\{" + re.escape(sec_title) + r"\}"
               r"(\\label\{[^}]*\})?")
        text = re.sub(pat,
                      f"\\\\section{{{sec_title}}}\\\\label{{{label}}}",
                      text, count=1)

    path.write_text(text, encoding="utf-8")
    print(f"{path.name}: {len(numbers)} sections labelled, "
          f"{n_empty} empty sections removed")


def restructure_appendix(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^\\chapter\{Appendix\}(\\label\{[^}]*\})?",
        "\\\\chapter*{Appendices}\n"
        "\\\\addcontentsline{toc}{chapter}{Appendices}"
        "\\\\label{app:appendices}",
        text)
    for _letter, old_title, new_title, label in APPENDIX_CHAPTERS:
        pat = (r"\\section\{" + re.escape(old_title) + r"\}"
               r"(\\label\{[^}]*\})?")
        new = f"\\\\chapter{{{new_title}}}\\\\label{{{label}}}"
        text, n = re.subn(pat, new, text, count=1)
        assert n == 1, f"appendix heading not found: {old_title}"
    path.write_text(text, encoding="utf-8")
    print(f"{path.name}: 10 appendix chapters labelled")


def main() -> None:
    base = Path(sys.argv[1], "chapters")
    for name, numbers in FILE_SECTIONS.items():
        relabel_file(base / name, numbers)
    for name in ("06-conclusion.tex", "07-references.tex"):
        path = base / name
        text = path.read_text(encoding="utf-8")
        m = re.match(r"\\chapter\{([^}]+)\}", text)
        text = re.sub(r"^\\chapter\{([^}]+)\}(\\label\{[^}]*\})?",
                      lambda mm: f"\\chapter{{{mm.group(1)}}}"
                      f"\\label{{{CHAPTER_LABELS[m.group(1)]}}}", text)
        path.write_text(text, encoding="utf-8")
        print(f"{name}: chapter labelled")
    restructure_appendix(base / "08-appendix.tex")


if __name__ == "__main__":
    main()
