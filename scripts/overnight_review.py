"""Unattended end-to-end review of the dissertation.

Runs the deterministic sweeps, then a headless Claude pass over every part of
the document, then a cross-chapter pass, then compiles one report.

Built for running overnight with nobody watching, so the failure handling
matters more than the happy path:

- The master is snapshotted first. Findings quote the snapshot, so an edit made
  at 3am cannot make the report quote text that no longer exists.
- Every unit is retried on crash, timeout, or empty output.
- State is written after each unit, so a supervisor that dies can be relaunched
  and will skip completed work rather than start again.
- A heartbeat file is refreshed on a timer. A stale heartbeat is how the caller
  tells "still thinking" from "dead", which a silent background process cannot
  express on its own.
- Review agents get read-only tools. Nothing in this pipeline can write to the
  master.

Usage:
    python3 scripts/overnight_review.py --out build/overnight
    python3 scripts/overnight_review.py --out build/overnight --resume
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = "/Users/benjyb/Desktop/MscProject/Dissertation/Dissertation.docx"

MODEL = "opus"
READ_TOOLS = ["Read", "Grep", "Glob"]
WEB_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]

UNIT_TIMEOUT = 1500          # seconds per review unit
MAX_ATTEMPTS = 3
CONCURRENCY = 3
TARGET_WORDS = 3500          # split chapters larger than this
HEARTBEAT_SECONDS = 20

HOUSE_STYLE = (
    "House style he must follow, so flag violations: UK English; NO em dashes; "
    "never the word 'genuinely'; no AI-tell vocabulary (delve, crucial, "
    "landscape, testament, underscore, tapestry, navigate); no hollow "
    "signposting; no rule-of-three lists written for rhythm; no "
    "moreover/furthermore as scaffolding between points."
)

OUTPUT_CONTRACT = (
    "OUTPUT FORMAT, strictly. For each finding:\n"
    "QUOTE: <exact verbatim text from the file, 8-25 words, so it can be found "
    "with Ctrl-F in Word>\n"
    "WRONG: <one line>\n"
    "FIX: <one line>\n"
    "SEVERITY: EXAMINER-VISIBLE | MARKS-AT-RISK | POLISH\n"
    "MINUTES: <integer>\n\n"
    "The quote MUST be verbatim, character for character. Paragraph numbers are "
    "useless to the reader, only searchable quotes work. If you cannot quote it "
    "exactly, do not report it.\n"
    "Do not praise anything. Do not summarise. Findings only. Your final "
    "message is the deliverable."
)

NUMBER_RULE = (
    "STANDING RULE ON NUMBERS, which overrides any instinct to be thorough: a "
    "number is a finding ONLY when it contradicts its source, or contradicts "
    "itself elsewhere in the document. NEVER report that a base or denominator "
    "should be stated or clarified. Simplifying '94 audited, 3 unscorable' to "
    "'91' is the author's editorial choice and is NOT an error. Do not raise it."
)

PROJECT = (
    "The project: an LLM agent swarm that answers EU Open Data Maturity Index "
    "(ODMI) questions across 36 countries, validated against ODMI's published "
    "2025 answer key. Three roles (Researcher, Verifier, Adjudicator) debate and "
    "may abstain. Held-out evaluation is 8 countries x 143 questions = 1,144 "
    "pairs. Canonical numbers live in evaluation/results/exp36_headline.json, "
    "computed from the SQLite store."
)


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Supervisor:
    def __init__(self, outdir, resume=False):
        self.out = os.path.abspath(outdir)
        self.findings = os.path.join(self.out, "findings")
        self.state_path = os.path.join(self.out, "state.json")
        self.heartbeat_path = os.path.join(self.out, "heartbeat.json")
        self.log_path = os.path.join(self.out, "supervisor.log")
        os.makedirs(self.findings, exist_ok=True)

        self.state = {"units": {}, "phase": "starting", "started": now()}
        if resume and os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    self.state = json.load(f)
                self.log("resuming from existing state")
            except (json.JSONDecodeError, OSError):
                self.log("state file unreadable, starting fresh")

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb.start()

    def log(self, msg):
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    def save_state(self):
        with self._lock:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=1)
            os.replace(tmp, self.state_path)

    def _heartbeat_loop(self):
        """Refreshed on a timer rather than after each unit, so a supervisor
        wedged inside a long call still proves it is alive."""
        while not self._stop.wait(HEARTBEAT_SECONDS):
            units = self.state.get("units", {})
            done = sum(1 for u in units.values() if u.get("status") == "done")
            failed = sum(1 for u in units.values() if u.get("status") == "failed")
            beat = {
                "ts": now(),
                "epoch": time.time(),
                "pid": os.getpid(),
                "phase": self.state.get("phase"),
                "units_total": len(units),
                "units_done": done,
                "units_failed": failed,
                "running": [k for k, v in units.items()
                            if v.get("status") == "running"],
            }
            tmp = self.heartbeat_path + ".tmp"
            try:
                with open(tmp, "w") as f:
                    json.dump(beat, f, indent=1)
                os.replace(tmp, self.heartbeat_path)
            except OSError:
                pass

    def stop(self):
        self._stop.set()

    # ----------------------------------------------------------------------

    def run_claude(self, prompt, tools, timeout=UNIT_TIMEOUT):
        """One headless call. Returns (ok, text)."""
        cmd = [
            "claude", "-p",
            "--model", MODEL,
            "--tools", ",".join(tools),
            "--allowedTools", " ".join(tools),
            "--output-format", "text",
            # No MCP servers. One of the configured servers needs interactive
            # auth, which would stall an unattended call, and none of them are
            # any use for reading local files.
            "--strict-mcp-config",
        ]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=timeout, cwd=HERE,
            )
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
        if proc.returncode != 0:
            return False, f"EXIT {proc.returncode}: {proc.stderr[-800:]}"
        text = (proc.stdout or "").strip()
        if len(text) < 40:
            return False, f"EMPTY OUTPUT: {text!r}"
        return True, text

    def run_unit(self, name, prompt, tools):
        rec = self.state["units"].setdefault(name, {"status": "pending",
                                                    "attempts": 0})
        if rec.get("status") == "done":
            self.log(f"skip {name} (already done)")
            return
        path = os.path.join(self.findings, f"{name}.md")

        for attempt in range(rec.get("attempts", 0), MAX_ATTEMPTS):
            rec["status"] = "running"
            rec["attempts"] = attempt + 1
            self.save_state()
            self.log(f"start {name} (attempt {attempt + 1}/{MAX_ATTEMPTS})")
            t0 = time.time()
            ok, text = self.run_claude(prompt, tools)
            secs = round(time.time() - t0)

            if ok:
                with open(path, "w") as f:
                    f.write(text)
                rec.update(status="done", seconds=secs, chars=len(text),
                           finished=now())
                self.save_state()
                self.log(f"done  {name} in {secs}s, {len(text)} chars")
                return

            rec.update(status="retrying", last_error=text[:300], seconds=secs)
            self.save_state()
            self.log(f"FAIL  {name} attempt {attempt + 1}: {text[:160]}")
            time.sleep(min(60, 10 * (attempt + 1)))

        rec["status"] = "failed"
        self.save_state()
        self.log(f"GIVE UP on {name} after {MAX_ATTEMPTS} attempts")

    def run_pool(self, units):
        """units: list of (name, prompt, tools)."""
        q = queue.Queue()
        for u in units:
            q.put(u)

        def worker():
            while True:
                try:
                    name, prompt, tools = q.get_nowait()
                except queue.Empty:
                    return
                try:
                    self.run_unit(name, prompt, tools)
                except Exception as exc:                      # keep the pool alive
                    self.log(f"worker error on {name}: {exc!r}")
                    rec = self.state["units"].setdefault(name, {})
                    rec.update(status="failed", last_error=repr(exc)[:300])
                    self.save_state()
                finally:
                    q.task_done()

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(min(CONCURRENCY, len(units)))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


# --------------------------------------------------------------------------
# document preparation
# --------------------------------------------------------------------------

def snapshot(sup, master):
    dest = os.path.join(sup.out, "snapshot.docx")
    shutil.copy2(master, dest)
    with open(dest, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:16]
    sup.state["snapshot"] = {"path": dest, "sha256_16": digest,
                             "taken": now(),
                             "source_mtime": os.path.getmtime(master)}
    sup.save_state()
    sup.log(f"snapshot taken, sha {digest}")
    return dest


def deterministic(sup, snap):
    qa_out = os.path.join(sup.out, "qa")
    steps = [
        ("qa_sweep", ["python3", "scripts/dissertation_qa.py", snap,
                      "--out", qa_out]),
        ("number_verify", ["python3", "scripts/verify_numbers.py",
                           "--qa", os.path.join(qa_out, "report.json"),
                           "--out", qa_out]),
        ("prose_scan", ["python3", "scripts/ai_prose_scan.py",
                        "--qa", os.path.join(qa_out, "report.json")]),
    ]
    for name, cmd in steps:
        sup.log(f"deterministic: {name}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=HERE, timeout=600)
            with open(os.path.join(sup.out, f"{name}.txt"), "w") as f:
                f.write(proc.stdout + ("\n[stderr]\n" + proc.stderr
                                       if proc.stderr else ""))
            if proc.returncode != 0:
                sup.log(f"  {name} exit {proc.returncode}: {proc.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            sup.log(f"  {name} TIMED OUT")
    return qa_out


def build_units(sup, qa_out):
    """Split chapters into review units of roughly TARGET_WORDS."""
    chdir = os.path.join(qa_out, "chapters")
    units = []
    for fn in sorted(os.listdir(chdir)):
        if not fn.endswith(".txt"):
            continue
        path = os.path.join(chdir, fn)
        with open(path) as f:
            text = f.read()
        stem = fn[:-4]
        words = len(text.split())
        if words <= TARGET_WORDS:
            units.append((stem, text))
            continue
        # Split on blank lines so a unit never starts mid-paragraph.
        paras, cur, count = text.split("\n\n"), [], 0
        part = 1
        for p in paras:
            cur.append(p)
            count += len(p.split())
            if count >= TARGET_WORDS:
                units.append((f"{stem}_part{part}", "\n\n".join(cur)))
                cur, count, part = [], 0, part + 1
        if cur:
            tail = "\n\n".join(cur)
            # A short tail is folded back rather than spending a whole call on
            # a few hundred words with no surrounding context.
            if len(tail.split()) < 800 and units and units[-1][0].startswith(stem):
                prev_name, prev_text = units[-1]
                units[-1] = (prev_name, prev_text + "\n\n" + tail)
            else:
                units.append((f"{stem}_part{part}", tail))
    for name, text in units:
        with open(os.path.join(sup.out, "units", f"{name}.txt"), "w") as f:
            f.write(text)
    return units


def chapter_prompt(name, unit_path, qa_out):
    return f"""You are doing a final pre-submission read of part of an MSc dissertation (King's College London, Advanced Computing). Submission is tomorrow. READ-ONLY: you have Read, Grep and Glob only. Do not attempt to edit anything.

{PROJECT}

YOUR TEXT: {unit_path}
Read that file in full. It is one part of the document, named "{name}".

Supporting material you may read if useful:
- {qa_out}/chapters/  (the other chapters, for cross-checking a claim)
- evaluation/results/exp36_headline.json  (canonical numbers)
- RESULTS.md

{NUMBER_RULE}

Find at most 10 problems, most damaging first. Look for:
- claims set up and never paid off, or paid off in a different chapter than promised
- a finding buried under a weaker adjacent point, or a stronger available argument not made
- a number here that contradicts the same number elsewhere in the document
- results stated without the comparison that makes them meaningful
- overclaiming beyond what the evidence supports, or a real finding hedged into invisibility
- sentences carrying two ideas, terms used before they are defined, vague attribution
- leftover editorial notes, placeholders, or debris that must not be submitted

{HOUSE_STYLE}

{OUTPUT_CONTRACT}
"""


def cross_prompt(sup, qa_out):
    return f"""You are checking an MSc dissertation for cross-chapter coherence, the night before submission. READ-ONLY.

{PROJECT}

Read every chapter in {qa_out}/chapters/ and the per-part findings already produced in {sup.findings}/ (they are markdown files of findings from agents that each read one part).

{NUMBER_RULE}

Your job is only what a single-chapter reader could not see:
1. Every research question stated in the Introduction, answered explicitly somewhere. Name where each is answered, or report it unanswered.
2. The Abstract and Introduction describing the results actually obtained in the Results chapter.
3. The Conclusion consistent with Results and Discussion, including every number it repeats.
4. The same statistic given two different values in two places. Check especially: negative-gold counts, false-positive rates, coverage, commit accuracy, closed-book figures, the false-positive audit outcome.
5. Terminology drift: the same concept named differently across chapters.
6. Contributions claimed in the Introduction that the body does not deliver.

{OUTPUT_CONTRACT}
"""


def citation_prompt(qa_out):
    return f"""You are verifying CITATIONS in an MSc dissertation, the night before submission. READ-ONLY apart from web access.

{PROJECT}

Read {qa_out}/chapters/01_background_and_related_work.txt and {qa_out}/chapters/06_references.txt.

For the 10 citations that carry the most weight (any citation a numeric claim is attributed to, plus any whose finding the argument depends on), verify against the PRIMARY source:
1. Find the primary source (arXiv, DOI, publisher page), not a summary.
2. Confirm the source actually makes the claim it is cited for. A paper being real does not mean it reports the number in the sentence.
3. Check the year and author list match the References entry.

Rules you must not break:
- If you cannot reach the primary text, or cannot confirm the specific claim, report it as UNVERIFIED. Never approximate, never infer a number from an abstract, never guess.
- Report a citation ONLY if it is wrong or unverifiable. Do not report correct ones.

ALREADY CHECKED, do not spend time on it: Fumega and Gao (2026), 'Beyond automation', Data & Policy 8, e20. The dissertation reproduces their 19%/2-of-12 and 69%/17-of-25 figures exactly as the source states them. The arithmetic defect is the source's own and the dissertation already says so. Not a finding.

{OUTPUT_CONTRACT}

Then a final section headed "UNVERIFIED" listing every citation you could not confirm either way, one line each.
"""


def notes_prompt(qa_out, sup):
    return f"""You are reconciling outstanding editorial notes in an MSc dissertation, the night before submission. READ-ONLY.

Read {sup.out}/qa/report.json and look at its "notes" array. Each entry is an outstanding note: a red [CC] marker, a bracketed author note, or a Word comment, with the surrounding context.

Also read the chapters in {qa_out}/chapters/ to check the current state of the text.

For EVERY note, return a verdict:
- ANSWERED: the text now does what the note asked. Quote the sentence that resolves it.
- NOT ANSWERED: still owed. Say in one line what is missing.
- STALE: the note describes a state that no longer exists (for example it warns about scaffolding that has since been deleted).

The author's own notes in black count exactly as much as red [CC] ones.

A verdict with no quoted evidence is a guess, so quote both the note and the text you are judging it against.

OUTPUT FORMAT, per note:
NOTE: <the note text, truncated to 30 words>
WHERE: <chapter>
VERDICT: ANSWERED | NOT ANSWERED | STALE
EVIDENCE: <exact quote from the current text, or "none">
ACTION: DELETE | KEEP AND RESOLVE
"""


def compile_prompt(sup, qa_out):
    return f"""You are compiling the final overnight review report for an MSc dissertation. Submission is today. READ-ONLY.

Read every markdown file in {sup.findings}/ . These are findings from agents that each read one part of the document, plus a cross-chapter pass, a citation pass and a notes reconciliation.

Also read the deterministic output:
- {sup.out}/qa_sweep.txt
- {sup.out}/number_verify.txt
- {sup.out}/prose_scan.txt

Produce ONE report. Requirements:

1. DEDUPLICATE. The same problem found by three agents is one finding. Merge them, keep the clearest quote.
2. RANK by marks at risk divided by minutes to fix. The reader has hours, not days.
3. GROUP by chapter, so the reader walks the document once.
4. Every finding keeps its exact QUOTE so it can be found with Ctrl-F. Drop any finding whose quote is missing or paraphrased.
5. Open with a section "FIX THESE FIRST" of at most 12 items: the highest-value, lowest-cost fixes, with a running total of minutes.
6. Add a section "TOO LATE TO FIX" for anything structural that cannot be done in the time. Say plainly it is noted and not actionable.
7. Add a section "UNVERIFIED" listing what could not be confirmed either way. Being unable to confirm is a valid result and must be stated, not hidden.
8. Add a section "CONTRADICTIONS TO SETTLE" for any place the document disagrees with itself and the correct value could not be determined from source. These need the author's decision.

Do not invent findings. Do not include a finding that appears in no input file. Do not state a number you have not seen in one of the input files.

Write in UK English. No em dashes. Never the word "genuinely". Plain and direct, no praise, no encouragement.
"""


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/overnight")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    sup = Supervisor(args.out, resume=args.resume)
    os.makedirs(os.path.join(sup.out, "units"), exist_ok=True)
    sup.log("=" * 60)
    sup.log(f"overnight review starting, pid {os.getpid()}")

    try:
        if not sup.state.get("snapshot") or not args.resume:
            snap = snapshot(sup, args.master)
        else:
            snap = sup.state["snapshot"]["path"]

        sup.state["phase"] = "deterministic"
        sup.save_state()
        qa_out = deterministic(sup, snap)

        sup.state["phase"] = "chapters"
        sup.save_state()
        units = build_units(sup, qa_out)
        sup.log(f"{len(units)} review units")
        jobs = []
        for name, _text in units:
            upath = os.path.join(sup.out, "units", f"{name}.txt")
            jobs.append((name, chapter_prompt(name, upath, qa_out), READ_TOOLS))
        sup.run_pool(jobs)

        sup.state["phase"] = "cross_and_citations"
        sup.save_state()
        sup.run_pool([
            ("_cross_chapter", cross_prompt(sup, qa_out), READ_TOOLS),
            ("_citations", citation_prompt(qa_out), WEB_TOOLS),
            ("_notes", notes_prompt(qa_out, sup), READ_TOOLS),
        ])

        sup.state["phase"] = "compile"
        sup.save_state()
        sup.run_unit("_FINAL_REPORT", compile_prompt(sup, qa_out), READ_TOOLS)

        sup.state["phase"] = "complete"
        sup.state["finished"] = now()
        sup.save_state()
        sup.log("COMPLETE")
    except Exception as exc:
        sup.state["phase"] = "crashed"
        sup.state["error"] = repr(exc)[:500]
        sup.save_state()
        sup.log(f"SUPERVISOR CRASHED: {exc!r}")
        raise
    finally:
        sup.stop()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
