r"""Turn pandoc's image + caption-paragraph pairs into real LaTeX floats.

Figures: each docx figure is an \includegraphics of a PNG pandoc
extracted, with a literal caption paragraph ("Figure 4.1.2: ...")
adjacent. This replaces every pair with a figure environment holding
the reconciled artwork (the vector PDF where one exists, the docx PNG
where none does), a generated \caption and a \label. The mapping below
is the outcome of the 2026-08-04 eyeball reconciliation of all 39
embedded images against Dissertation/figures_new/ and
evaluation/figures/; every "pdf" entry was confirmed visually against
its caption.

Tables: pandoc emits captionless longtables wrapped in a
{\def\LTcaptype{none} ...} group, with the docx caption as a separate
paragraph. This unwraps the group, moves the caption into the
longtable as a real \caption\label row (captions above tables), and
deletes the caption paragraph.

Appendix F: the docx carries a stale image render of the baselines
table (four rows, superseded) directly above the real five-row
longtable. The image is dropped and the Table F.1 caption attaches to
the real table.

Usage: python3 build_figures_tables.py latex_dir
"""

import re
import sys
from pathlib import Path

# (chapter file, caption marker, media image, asset in figures/, label, width)
FIGURES = [
    ("01-introduction.tex", "Figure 1.1:", "image1.png",
     "fig_2_3_closed_vs_open_world.pdf", "fig:assumption", 1.0),
    ("02-background-and-related-work.tex", "Figure 2.1: The Open Data",
     "image2.png", "odmi_overview.png", "fig:odmi-overview", 1.0),
    ("02-background-and-related-work.tex", "Figure 2.1: Why the objective",
     "image3.png", "fig_2_1_hallucination_objective.pdf",
     "fig:hallucination", 1.0),
    ("02-background-and-related-work.tex", "Figure 2.2:", "image4.png",
     "fig_2_2_prior_steered_retrieval.pdf", "fig:prior-steered", 1.0),
    ("02-background-and-related-work.tex", "Figure 2.3:", "image5.png",
     "fig_2_4_verification_lineage.pdf", "fig:lineage", 0.8),
    ("03-approach-and-methodology.tex", "Figure 3.1:", "image6.png",
     "fig_3_1_subtrio.pdf", "fig:subtrio", 1.0),
    ("03-approach-and-methodology.tex", "Figure 3.2:", "image7.png",
     "fig_3_2_leakage_controls.pdf", "fig:leakage-points", 1.0),
    ("03-approach-and-methodology.tex", "Figure 3.3:", "image8.png",
     "fig_3_3_evaluation_set.pdf", "fig:evaluation-set-fig", 1.0),
    ("04-results.tex", "Figure 4.1.1:", "image9.png",
     "outcome_makeup_per_country.png", "fig:outcome-makeup", 1.0),
    ("04-results.tex", "Figure 4.1.2:", "image10.png",
     "fig_4_1_yes_no.pdf", "fig:accuracy-by-class", 1.0),
    ("04-results.tex", "Figure 4.1.3:", "image11.png",
     "recompute_vs_band.png", "fig:recompute-band", 1.0),
    ("04-results.tex", "Figure 4.2.1:", "image12.png",
     "per_class_accuracy_full_range.pdf", "fig:per-class-confidence", 1.0),
    ("04-results.tex", "Figure 4.2.2:", "image13.png",
     "reliability_by_class.pdf", "fig:reliability", 1.0),
    ("04-results.tex", "Figure 4.4.2:", "image14.png",
     "fig_4_5_maturity.pdf", "fig:against-maturity", 0.72),
    ("04-results.tex", "Figure 4.5.1:", "image15.png",
     "fig_4_5_dimension.pdf", "fig:by-dimension", 1.0),
    ("04-results.tex", "Figure 4.5.2:", "image16.png",
     "coverage_accuracy_by_answer_shape.png", "fig:by-answer-shape", 1.0),
    ("04-results.tex", "Figure 4.6.2:", "image17.png",
     "fig_4_7_1_runtorun.pdf", "fig:replicates-fig", 1.0),
    ("04-results.tex", "Figure 4.9.1:", "image18.png",
     "reconstructed_band.png", "fig:reconstruction-fig", 1.0),
    ("05-discussion.tex", "Figure 5.1:", "image19.png",
     "fig_5_2_error_vs_maturity.pdf", "fig:error-vs-maturity", 1.0),
    ("05-discussion.tex", "Figure 5.2:", "image20.png",
     "fig_5_3_two_failure_modes.pdf", "fig:two-failure-modes", 1.0),
    ("05-discussion.tex", "Figure 5.3:", "image21.png",
     "fig_5_5_dimension_oversight.pdf", "fig:dimension-oversight", 1.0),
    ("08-appendix.tex", "Figure B.1:", "image22.png",
     "abstained_by_country.png", "fig:abstained-by-country", 1.0),
    ("08-appendix.tex", "Figure J.1:", "image24.png",
     "fig_4_1_funnel.pdf", "fig:j-funnel", 0.9),
    ("08-appendix.tex", "Figure J.2:", "image25.png",
     "fig_4_1_coverage_accuracy.pdf", "fig:j-shares", 1.0),
    ("08-appendix.tex", "Figure J.3:", "image26.png",
     "j3_four_ways.png", "fig:j-four-ways", 1.0),
    ("08-appendix.tex", "Figure J.4:", "image27.png",
     "fig_4_2_forced_vs_abstaining.pdf", "fig:j-forced", 0.8),
    ("08-appendix.tex", "Figure J.5:", "image28.png",
     "fig_4_3_3_confidence_by_label.pdf", "fig:j-confidence-at-commit", 0.9),
    ("08-appendix.tex", "Figure J.6:", "image29.png",
     "fig_4_6_subthreshold_recovery.pdf", "fig:j-subthreshold", 0.9),
    ("08-appendix.tex", "Figure J.7:", "image30.png",
     "j7_abstention_codes.png", "fig:j-abstention-codes", 1.0),
    ("08-appendix.tex", "Figure J.8:", "image31.png",
     "j8_code_gold_mix.png", "fig:j-code-gold-mix", 0.9),
    ("08-appendix.tex", "Figure J.9:", "image32.png",
     "j9_abstention_vs_accuracy.png", "fig:j-abstention-accuracy", 0.7),
    ("08-appendix.tex", "Figure J.10:", "image33.png",
     "j10_yes_share_dropped.png", "fig:j-yes-share-dropped", 0.65),
    ("08-appendix.tex", "Figure J.11:", "image34.png",
     "j11_yes_share_no.png", "fig:j-yes-share-no", 0.65),
    ("08-appendix.tex", "Figure J.12:", "image35.png",
     "j12_yes_share_oracle.png", "fig:j-yes-share-oracle", 0.65),
    ("08-appendix.tex", "Figure J.13:", "image36.png",
     "fig_exp36_score_bands.pdf", "fig:j-score-bands", 1.0),
    ("08-appendix.tex", "Figure J.14:", "image37.png",
     "fig_exp36_coverage_vs_published.pdf", "fig:j-coverage-published", 0.7),
    ("08-appendix.tex", "Figure J.16:", "image38.png",
     "fig_5_1_two_populations.pdf", "fig:j-two-populations", 0.9),
    ("08-appendix.tex", "Figure J.17:", "image39.png",
     "fig_5_4_evidence_asymmetry.pdf", "fig:j-asymmetry", 0.9),
]

# (chapter file, caption marker, label); tables are matched to
# longtables by order within each file, asserted below.
TABLES = {
    "02-background-and-related-work.tex": [
        ("Table 2.1:", "tab:criteria"),
        ("Table 2.2:", "tab:prior-work"),
    ],
    "03-approach-and-methodology.tex": [
        ("Table 3.1:", "tab:answer-shapes"),
        ("Table 3.2:", "tab:harvests"),
        ("Table 3.3:", "tab:metrics"),
    ],
    "04-results.tex": [
        ("Table 4.1.1:", "tab:four-ways"),
        ("Table 4.2.1:", "tab:abstention-reasons"),
        ("Table 4.3.1:", "tab:attributability"),
        ("Table 4.4.1:", "tab:strata"),
        ("Table 4.6.1:", "tab:replicates"),
        ("Table 4.7.1:", "tab:ablation"),
        ("Table 4.8.1:", "tab:cost"),
    ],
    "05-discussion.tex": [
        ("Table 5.1:", "tab:scorecard"),
        ("Table 5.2:", "tab:reformulation"),
    ],
    "08-appendix.tex": [
        ("Table A.1:", "tab:failure-register"),
        ("Table B.1:", "tab:abstention-codes"),
        ("Table B.2:", "tab:fp-audit"),
        ("Table C.1:", "tab:experiments"),
        ("Table D.1:", "tab:out-of-reach"),
        ("Table E.1:", "tab:prior-work-full"),
        ("Table F.1:", "tab:baselines"),
        ("Table G.1:", "tab:question-bank"),
        ("Table H.1:", "tab:harvest-register"),
        ("Table H.2:", "tab:catalogue-metrics"),
        ("Table I.1:", "tab:dev-by-country"),
        ("Table I.2:", "tab:dev-by-dimension"),
    ],
}


def caption_text(line: str, marker: str) -> str:
    text = line.split(marker, 1)[1].strip()
    text = re.sub(r"\\textbf\{\s*\}\s*$", "", text).strip()
    if text.endswith("}") and line.lstrip().startswith("\\textbf{"):
        text = text[:-1].strip()
    return text


def do_figures(base: Path) -> None:
    for fname, marker, image, asset, label, width in FIGURES:
        path = base / "chapters" / fname
        text = path.read_text(encoding="utf-8")

        # remove the docx image wherever it sits (inline or on its own line)
        img_re = re.compile(
            r"\\includegraphics\[[^\]]*\]\{media/media/" + image + r"\}")
        text, n_img = img_re.subn("", text)
        assert n_img == 1, (fname, image, n_img)

        # replace the caption paragraph with the figure environment
        lines = text.split("\n")
        hits = [i for i, ln in enumerate(lines)
                if ln.lstrip().lstrip("~").lstrip().startswith(("\\textbf{" + marker, marker))
                or ln.lstrip("~ ").startswith(marker)]
        assert len(hits) == 1, (fname, marker, hits)
        i = hits[0]
        cap = caption_text(lines[i], marker)
        w = "\\linewidth" if width == 1.0 else f"{width}\\linewidth"
        lines[i] = (
            "\\begin{figure}[htbp]\n"
            "\\centering\n"
            f"\\includegraphics[width={w}]{{figures/{asset}}}\n"
            f"\\caption{{{cap}}}\n"
            f"\\label{{{label}}}\n"
            "\\end{figure}"
        )
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"figure {label}: {image} -> {asset}")


def do_tables(base: Path) -> None:
    for fname, caps in TABLES.items():
        path = base / "chapters" / fname
        text = path.read_text(encoding="utf-8")

        # unwrap pandoc's caption-suppression groups
        text, n_open = re.subn(r"\{\\def\\LTcaptype\{none\}[^\n]*\n", "", text)
        text, n_close = re.subn(r"^\}$\n(?=\s*$)", "", text, flags=re.M)

        n_tables = len(re.findall(r"\\begin\{longtable\}", text))
        assert n_tables == len(caps), (fname, n_tables, len(caps))

        lines = text.split("\n")
        # collect caption paragraphs first
        cap_bodies = {}
        for marker, label in caps:
            hits = [i for i, ln in enumerate(lines)
                    if ln is not None
                    and (ln.lstrip().lstrip("~").lstrip()
                         .startswith(("\\textbf{" + marker, marker))
                         or ln.lstrip("~ ").startswith(marker))]
            assert len(hits) == 1, (fname, marker, hits)
            cap_bodies[label] = caption_text(lines[hits[0]], marker)
            lines[hits[0]] = None  # delete the paragraph
        lines = [ln for ln in lines if ln is not None]
        text = "\n".join(lines)

        # insert \caption rows into the longtables, in file order
        pieces = text.split("\\begin{longtable}")
        out = [pieces[0]]
        for (marker, label), piece in zip(caps, pieces[1:]):
            # the column spec ends at the first line ending in "@{}}"
            m = re.search(r"@\{\}\}\n", piece)
            insert_at = m.end()
            cap_row = f"\\caption{{{cap_bodies[label]}}}\\label{{{label}}}\\\\\n"
            out.append(piece[:insert_at] + cap_row + piece[insert_at:])
        text = "\\begin{longtable}".join(out)

        path.write_text(text, encoding="utf-8")
        print(f"tables in {fname}: {len(caps)} captioned "
              f"({n_open} wrappers unwrapped)")


def drop_stale_baselines_image(base: Path) -> None:
    path = base / "chapters" / "08-appendix.tex"
    text = path.read_text(encoding="utf-8")
    text, n = re.subn(
        r"\s*\\includegraphics\[[^\]]*\]\{media/media/image23\.png\}", "",
        text)
    assert n == 1, n
    path.write_text(text, encoding="utf-8")
    print("appendix F: stale baselines image dropped")


def main() -> None:
    base = Path(sys.argv[1])
    stage = sys.argv[2] if len(sys.argv) > 2 else "all"
    if stage in ("all", "figures"):
        drop_stale_baselines_image(base)
        do_figures(base)
    if stage in ("all", "tables"):
        do_tables(base)


if __name__ == "__main__":
    main()
