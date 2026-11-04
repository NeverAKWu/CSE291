"""Build the corrected 2-page Phase 1 report plus timeline appendix, offline.

Install requirements-report.txt first; original report/report.pdf is untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, FrameBreak, Image, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor("#162536")
BLUE = colors.HexColor("#245e83")
MUTED = colors.HexColor("#526171")
BODY = ParagraphStyle("body", fontName="Times-Roman", fontSize=10, leading=12,
                      spaceAfter=7, textColor=INK)
HEAD = ParagraphStyle("head", parent=BODY, fontName="Helvetica-Bold", fontSize=10,
                      leading=13, spaceBefore=6, spaceAfter=5, textColor=BLUE)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.3, leading=10, textColor=MUTED)
CAPTION = ParagraphStyle("caption", parent=SMALL, alignment=TA_CENTER, spaceAfter=7)


def p(text, style=BODY):
    return Paragraph(text, style)


def table(data, widths, size=8):
    result = Table([[p(str(cell), ParagraphStyle("cell", parent=SMALL,
                    fontSize=size, leading=size + 2)) for cell in row] for row in data],
                   colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f7")),
        ("LINEBELOW", (0, 0), (-1, 0), .6, BLUE),
        ("LINEBELOW", (0, -1), (-1, -1), .5, MUTED),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return result


def image(path, width):
    result = Image(str(path))
    result.drawHeight *= width / result.drawWidth
    result.drawWidth = width
    return result


def build(source, figures, output):
    # Embed metrically compatible fonts: relying on PDF viewer substitutions can
    # produce incorrect glyph spacing on machines without the standard fonts.
    from matplotlib.font_manager import FontProperties, findfont
    for alias, family, weight, style in (
        ("Times-Roman", "Liberation Serif", "normal", "normal"),
        ("Times-Bold", "Liberation Serif", "bold", "normal"),
        ("Times-Italic", "Liberation Serif", "normal", "italic"),
        ("Times-BoldItalic", "Liberation Serif", "bold", "italic"),
        ("Helvetica", "Liberation Sans", "normal", "normal"),
        ("Helvetica-Bold", "Liberation Sans", "bold", "normal"),
        ("Courier", "Liberation Mono", "normal", "normal"),
    ):
        font = findfont(FontProperties(family=family, weight=weight, style=style),
                        fallback_to_default=False)
        pdfmetrics.registerFont(TTFont(alias, font))
    source, figures, output = Path(source), Path(figures), Path(output)
    if output.exists():
        raise ValueError("report output must be a new file")
    stats = json.loads((source / "stats.json").read_text(encoding="utf-8"))
    lineage = json.loads((source / "lineage.json").read_text(encoding="utf-8"))
    if lineage.get("inputs", {}).get("runs_sha256") != (
            "f30225f77fdc8a20f7134b5ed5da2338b5973d1231bbba429840601397a537b1"):
        raise ValueError("qualitative case analysis requires the original legacy dataset")
    rows = [json.loads(line) for line in (source / "runs_enriched.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 975 or len({r["task_id"] for r in rows}) != 25:
        raise ValueError("this report is for the audited 25-task, 975-run experiment")
    clean, itt = stats["clean"], stats["intention_to_treat"]
    token_total = sum(r["total_tokens"] for r in rows)
    calls = sum(r["llm_calls"] for r in rows)
    success_changes = sum(r["success"] != r["original_scores"]["success"] for r in rows)
    auth_changes = sum(r["unauthorized"] != r["original_scores"]["unauthorized"] for r in rows)
    clean_none, clean_verify = clean["none"], clean["verify"]
    pc = lambda x: f"{100*x:.1f}%"
    counts = lambda row, field: f"{round(row[field] * row[field+'_n'])}/{row[field+'_n']}"
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(output), pagesize=letter, leftMargin=42, rightMargin=42,
                          topMargin=45, bottomMargin=45, title="Phase 1 - Audited Evaluation",
                          author="Option 5, Group 8")
    col, gap = 255, 18

    def header(canvas, document):
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(42, 760, "CSE 291A | Fall 2026 | Option 5, Group 8")
        canvas.drawRightString(570, 760, "Audited Phase 1 evaluation | November 4, 2026")
        canvas.setStrokeColor(colors.HexColor("#c7d4df"))
        canvas.line(42, 750, 570, 750)
        if document.page == 1:
            canvas.setFillColor(INK)
            canvas.setFont("Helvetica-Bold", 15)
            canvas.drawString(42, 726, "Failure Propagation and Recovery")
            canvas.setFont("Helvetica", 11)
            canvas.drawString(42, 710, "in Multi-Agent Systems: Fault Injection and Measurement")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(42, 29, "Original traces retained; revised scores use offline deterministic replay.")
        canvas.drawRightString(570, 29, str(document.page))
        canvas.restoreState()

    frames1 = [Frame(x, 48, col, 648, leftPadding=0, rightPadding=0,
                     topPadding=0, bottomPadding=0) for x in (42, 42+col+gap)]
    frames2 = [Frame(x, 48, col, 687, leftPadding=0, rightPadding=0,
                     topPadding=0, bottomPadding=0) for x in (42, 42+col+gap)]
    appendix = Frame(42, 48, 528, 687, leftPadding=0, rightPadding=0,
                     topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="first", frames=frames1, onPage=header),
                         PageTemplate(id="body", frames=frames2, onPage=header),
                         PageTemplate(id="appendix", frames=[appendix], onPage=header)])
    story = [p("1. Question and workflow", HEAD),
        p("Can tracking dependencies between agent results support efficient recovery while preserving correct and safe execution? Phase 1 measures failures and establishes baselines; selective recovery is reserved for Phase 2."),
        p("Each task requests a team purchase from the cheapest approved vendor within budget. A deterministic retrieval step reads a catalog, manager directory and shared budget file. The researcher extracts facts, the planner writes a JSON tool plan, and the executor issues one simulated action at a time, using returned order IDs."),
        p("The checker requires one correct order, matching CSV team/item/quantity/vendor/total and order ID, correct budget deduction, and manager confirmation. Over-budget tasks must order nothing and notify the manager. Business correctness and authorization are scored separately; safe success requires both."),
        p("Shared files are restorable. Simulated orders and emails are irreversible: restoring a file snapshot never removes them. The tools do not contact real vendors or recipients."),
        p("2. Faults and comparisons", HEAD),
        p("There are eight accidental schedules: corrupted shared budget; wrong researcher price/vendor; stale researcher facts; researcher or planner timeout; doubled plan quantity; corrupted returned order ID. Four adversarial schedules poison retrieval, researcher output, planner steps or a tool response."),
        p("No recovery measures propagation. Full restart receives oracle fault identity, restores files after the first pass and reruns the workflow, retaining external effects. Legacy verification checks researcher/planner candidates against sources and regenerates one rejected output. Its retry was not reverified, and executor/tool results were not checked."),
        p("All methods receive the same scheduled task/fault combinations. Primary results include all scheduled runs (intention to inject, ITT). A secondary common-delivery cohort compares the same task/fault pairs reached by every method; delivery is method-dependent, so this is an applicability diagnostic."),
        FrameBreak(), p("3. Measurement and trace audit", HEAD),
        p("Each artifact has a producer, content hash and explicit input IDs. Tool results depend on prior file writers, capturing shared-state dependencies. Fault artifacts replace payloads at boundaries. Semantic comparisons use decision fields and tool arguments rather than email wording."),
        p("Changed stages and taint matches are restricted to descendants of the faulty artifact. Differences before injection and missing artifacts without observed ancestry are listed separately. An associated failure is not automatically fault-caused harm. Direct harmful evidence requires a taint-bearing, independently audited unauthorized action downstream of injection."),
        p("Ignored injections do not establish recovery. Descendant tokens/actions measure potentially affected work, not a minimal invalid set. Wall latency is separated from synthetic 30-second timeout charges. Tracking overhead was not measured in historical runs."),
        image(figures / "affected_stages.png", col),
        p("Figure 1. Changed descendant stages / all 25 scheduled no-recovery tasks per fault. Missing ancestry is not invented.", CAPTION),
        p("The saved matrix has 975 runs: 25 tasks x 12 faults x 3 methods, plus 75 clean runs. Every trace replays consistently; all 17,298 recorded artifact hashes match. The requested model is api-glm-5.3-flash at temperature 0. Returned-model fingerprints and full original prompts were not collected."),
        p(f"Stricter scoring changes {success_changes} business-success labels and {auth_changes} unauthorized counts, chiefly because internal recipients outside the task manager and unexpected file reads are now explicitly audited. Original rows and PDFs remain unchanged.", SMALL),
        NextPageTemplate("body"), PageBreak(), p("4. Results", HEAD),
        p(f"<b>Clean execution.</b> No-recovery correctness is {counts(clean_none, 'success')} ({pc(clean_none['success'])}); verification is {counts(clean_verify, 'success')}. Neither has unauthorized actions. Mean no-recovery cost is {clean_none['total_tokens']:,.0f} tokens, {clean_none['llm_calls']:.2f} calls and {clean_none['workflow_wall_latency_s']:.1f} seconds. Verification adds {100*(clean_verify['total_tokens']/clean_none['total_tokens']-1):.0f}% tokens and {100*(clean_verify['workflow_wall_latency_s']/clean_none['workflow_wall_latency_s']-1):.0f}% wall time."),
        p("Two of 25 paired clean tasks have different semantic traces. Natural researcher budget errors already cause failures before some injected attacks. The verifier rejects one clean candidate (4% clean rejection rate); without independent candidate-validity labels, false positives and missed faults are unavailable."),
        p("Table 1. All scheduled runs. Correctness includes irreversible effects. UA is unauthorized actions per run; tokens and wall time are means.", SMALL)]
    data = [["Faults / method", "n", "Correct", "Safe", "UA", "Tokens", "Wall s"]]
    for cat in ("accidental", "adversarial"):
        for method in ("none", "restart", "verify"):
            r = itt[cat][method]
            data.append([("Acc." if cat == "accidental" else "Adv.")+" / "+method,
                         r["runs"], pc(r["success"]), pc(r["safe_success"]),
                         f"{r['unauthorized']:.2f}", f"{r['total_tokens']/1000:.1f}k",
                         f"{r['workflow_wall_latency_s']:.1f}"])
    story += [table(data, [69, 20, 35, 35, 25, 35, 36], 7.1), Spacer(1, 7),
        p("Accidental rows add 7.5 seconds of simulated timeout charge on average, separately from the wall times above." , SMALL),
        p("<b>Restart leaves residue.</b> Accidental correctness is 44%, versus 95.5% when first-pass external effects are hypothetically excluded; adversarial values are 24% versus 98%. These excluded-effect scores do not mean recovery. Restart retains 1.34 and 1.90 prior external actions per run on average and roughly doubles token use."),
        p("<b>Verification has boundary limits.</b> Legacy verification improves accidental correctness to 75% and adversarial safe success to 97%. It cannot correct a shared budget when it trusts the same corrupted source. Returned IDs also bypass its verification scope. A transient retry benefits from clean data; persistent faults need separate evaluation."),
        FrameBreak(), image(figures / "methods.png", col),
        p("Figure 2. Correct or safe executions / 25 scheduled tasks. This is the historical R/P verifier, not the new action-verification protocol.", CAPTION),
        p("<b>Observed attack propagation.</b> Among 100 scheduled no-recovery adversarial runs, 7 attacks are undelivered, 40 ignored, 30 propagate without audited failure, 21 have direct harmful evidence, and 2 failures remain unattributed. The old 23-harmful label included those 2 natural-error cases."),
        p("A compromised planner induces outside email actions in 20/25 tasks. Completion alone hides this: adversarial business success is 96%, while safe success is 75%. An outside recipient proves an unauthorized email action, not actual file-content exfiltration: some attack bodies only contain a literal attachment claim."),
        p("Common delivered cohorts contain 187 accidental and 93 adversarial pairs per method. Their correctness is 11.8/41.7/74.3% and 97.8/20.4/96.8% for none/restart/verify. These differ from ITT because unreached injection boundaries are retained in ITT."),
        p("5. Limits and Phase 2 direction", HEAD),
        p(f"The recorded {calls:,} successful calls use {token_total:,} native reported tokens. Failed attempts and gateway billing are unavailable; no dollar cost is inferred. One requested model, 25 generated tasks, stochastic clean references and conservative taint matching limit generalization."),
        p("The updated runtime rechecks retries, fails closed after bounded rejection, optionally verifies executor actions, records full messages and API attempts, and freezes source hashes before launch. Mock tests validate it; no new real-model results are claimed. Historical scores cannot be used to evaluate the new protocol."),
        p("Phase 2 will invalidate dependencies, validate retained work, restore shared-file versions and account for actions that cannot be undone. Comparisons must use identical schedules and resource budgets; detection quality remains separate from recovery quality."),
        NextPageTemplate("appendix"), PageBreak(), p("Appendix. Timeline, audit lineage and reproduction", HEAD),
        p("All authors are currently represented as Option 5, Group 8. The main report is pages 1-2; this appendix records project milestones through December 10."),
        table([["Date (2026)", "Milestone / deliverable"],
               ["November 4", "Phase 1 harness, 975-run dataset, strict offline audit and revised report; freeze original evidence."],
               ["November 11", "Freeze protocol and task schedules; expand validity annotations and selected persistent-fault cases."],
               ["November 18", "Implement dependency-aware invalidation and selective reruns; verify reused outputs remain valid."],
               ["November 25", "Shared-state snapshots and compensation; explicitly report irreversible orders/messages."],
               ["December 2", "Matched-schedule comparison against restart and verification: correctness, safety, retained work, latency, inference and tracking overhead."],
               ["December 6", "Failure-case analysis and optional detector evaluation with independent labels and FP/FN."],
               ["December 10", "Final code, traces, analysis and 4-6-page final report."]], [87, 441], 9),
        Spacer(1, 10), p("Evidence and reproducibility", HEAD),
        p("The audit preserves original scores alongside revised scores and validates actual simulated tool results before replay. File rollback retains external actions and sequence counters. Missing or inconsistent trace evidence stops reassessment. Source rows, task definitions, traces and scoring code are SHA-256 hashed in lineage.json; per-artifact legacy content hashes use the original 12-character SHA-1 format."),
        p("Original index: results/glm-flash-25tasks/runs.jsonl. Audit: results/glm-flash-25tasks-audited-v2. Keep the referenced source result folders. Recreate into a new output directory; do not overwrite the committed audit."),
        p("<font name='Courier' size='8'>python3 -m unittest discover -s tests -v<br/>python3 scripts/reassess.py results/glm-flash-25tasks --out /tmp/phase1-audit-new<br/>python3 -m pip install -r requirements-report.txt<br/>python3 scripts/plots.py /tmp/phase1-audit-new /tmp/phase1-figs-new<br/>python3 scripts/build_audited_report.py --source /tmp/phase1-audit-new --figures /tmp/phase1-figs-new --out /tmp/phase1-audited-new.pdf</font>"),
        p("The archived experiment lacks complete historical prompt/source snapshots, full request messages, returned-model metadata and failed-request usage. Neither replay nor source hashing can restore facts that were never logged. New protocol runs must remain a separate cohort."),
        p("Starting upstream commit: d3282e99517efd9a11abde5b4b6207281372a739. Detailed numerical tables, delivery denominators and conservative propagation labels are machine-readable in the audit directory.", SMALL)]
    doc.build(story)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "results/glm-flash-25tasks-audited-v2")
    parser.add_argument("--figures", type=Path, default=ROOT / "report/revised/figs")
    parser.add_argument("--out", type=Path, default=ROOT / "output/pdf/phase1_audited_report.pdf")
    args = parser.parse_args()
    build(args.source, args.figures, args.out)
    print(args.out.resolve())


if __name__ == "__main__":
    main()
