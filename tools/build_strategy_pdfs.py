"""Build the protocol-first Blueprint and release-evidence technical report PDFs."""

# ruff: noqa: E501, RUF001

from __future__ import annotations

import argparse
import html
from collections.abc import Callable
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#0B132B")
BLUE = colors.HexColor("#2364AA")
CYAN = colors.HexColor("#1B998B")
ORANGE = colors.HexColor("#E07825")
RED = colors.HexColor("#B42318")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#5A6675")
PALE = colors.HexColor("#EDF6F5")
PALE_BLUE = colors.HexColor("#EDF3FA")
LINE = colors.HexColor("#C7D2DE")
WHITE = colors.white


def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("M2RIV-TC", r"C:\Windows\Fonts\msjh.ttc"))
    pdfmetrics.registerFont(TTFont("M2RIV-TC-Bold", r"C:\Windows\Fonts\msjhbd.ttc"))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            parent=base["Normal"],
            fontName="M2RIV-TC-Bold",
            fontSize=8,
            leading=11,
            textColor=CYAN,
            spaceAfter=5,
            uppercase=True,
        ),
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="M2RIV-TC-Bold",
            fontSize=27,
            leading=33,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="M2RIV-TC",
            fontSize=12,
            leading=18,
            textColor=MUTED,
            spaceAfter=15,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="M2RIV-TC-Bold",
            fontSize=18,
            leading=24,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=9,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="M2RIV-TC-Bold",
            fontSize=11.5,
            leading=16,
            textColor=BLUE,
            spaceBefore=7,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="M2RIV-TC",
            fontSize=9.2,
            leading=14.2,
            textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="M2RIV-TC",
            fontSize=7.5,
            leading=10.5,
            textColor=MUTED,
            spaceAfter=3,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="M2RIV-TC-Bold",
            fontSize=12,
            leading=18,
            alignment=TA_CENTER,
            textColor=NAVY,
            borderColor=CYAN,
            borderWidth=1,
            borderPadding=11,
            backColor=PALE,
            spaceBefore=8,
            spaceAfter=12,
        ),
        "metric": ParagraphStyle(
            "Metric",
            parent=base["BodyText"],
            fontName="M2RIV-TC-Bold",
            fontSize=15,
            leading=18,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["BodyText"],
            fontName="M2RIV-TC",
            fontSize=7,
            leading=9,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _table(
    data: list[list[object]],
    widths: list[float],
    *,
    font_size: float = 7.2,
    header_color: colors.Color = NAVY,
) -> Table:
    header = ParagraphStyle(
        "TableHeader",
        fontName="M2RIV-TC-Bold",
        fontSize=font_size,
        leading=font_size + 2.3,
        textColor=WHITE,
    )
    cell = ParagraphStyle(
        "TableCell",
        fontName="M2RIV-TC",
        fontSize=font_size - 0.4,
        leading=font_size + 2.1,
        textColor=INK,
    )
    wrapped = [
        [
            Paragraph(html.escape(str(value)), header if row_index == 0 else cell)
            for value in row
        ]
        for row_index, row in enumerate(data)
    ]
    result = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#F6F8FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return result


def _metrics(items: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    columns = []
    for value, label in items:
        columns.append([_p(value, styles["metric"]), _p(label, styles["metric_label"])])
    result = Table([columns], colWidths=[41 * mm] * len(columns))
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return result


def _footer(label: str) -> Callable[[Canvas, SimpleDocTemplate], None]:
    def draw(pdf: Canvas, document: SimpleDocTemplate) -> None:
        pdf.saveState()
        width, _ = A4
        pdf.setStrokeColor(LINE)
        pdf.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        pdf.setFont("M2RIV-TC", 7)
        pdf.setFillColor(MUTED)
        pdf.drawString(18 * mm, 8 * mm, label)
        pdf.drawRightString(width - 18 * mm, 8 * mm, f"{document.page:02d}")
        pdf.restoreState()

    return draw


def _document(path: Path, *, title: str, author: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author=author,
    )


def _invariant_canvas(filename: str, **kwargs: object) -> Canvas:
    """Create byte-reproducible PDFs without wall-clock metadata."""
    kwargs["invariant"] = 1
    kwargs["pageCompression"] = 1
    return Canvas(filename, **kwargs)


def build_blueprint(path: Path) -> None:
    styles = _styles()
    story: list[object] = [
        Spacer(1, 10 * mm),
        _p("PROTOCOL-FIRST STRATEGY · 2026-08-29", styles["eyebrow"]),
        _p("M2RIV Blueprint v3.0", styles["title"]),
        _p("The vendor-neutral release-evidence layer for deployable AI models", styles["subtitle"]),
        _p(
            "模型 release 應有一份標準化、可驗證、可攜、可被 CI 消費的 change evidence。<br/><b>那份 evidence 是 MCR；M2RIV 是 reference implementation。</b>",
            styles["callout"],
        ),
        _p("要佔領的 abstraction", styles["h1"]),
        _p(
            "MCR 綁定 artifact identity、runtime provenance、paired evidence、uncertainty、policy、release authorization 與 build localization。成功不是所有人都執行 m2riv compare，而是其他 producer/consumer 不 import M2RIV Python 也能交換相同語意。",
            styles["body"],
        ),
        _table(
            [
                ["Producer / oracle", "MCR boundary", "Consumer"],
                ["ModelOpt / Polygraphy", "exact artifact + retained comparison + policy", "CI / promotion"],
                ["compiler CI / evaluator", "content identity + PASS/WARN/BLOCK/ERROR", "MLflow / registry"],
                ["M2RIV reference CLI", "conformance + strict verification", "KServe / internal control plane"],
            ],
            [48 * mm, 69 * mm, 47 * mm],
        ),
        Spacer(1, 4 * mm),
        _p("明確非目標", styles["h2"]),
        _p(
            "不做 evaluator zoo、training framework、registry、serving platform、dashboard 或 scheduler。Behavioral eval 是 external evidence source；Polygraphy 保持 backend oracle；MLflow 保持 experiment/lifecycle platform。",
            styles["body"],
        ),
        PageBreak(),
        _p("已完成的 kernel", styles["h1"]),
        _metrics(
            [("29", "public schemas"), ("4+4", "positive/negative profiles"), ("629", "GPU holdout cases"), ("4", "corpus entries")],
            styles,
        ),
        Spacer(1, 5 * mm),
        _table(
            [
                ["Layer", "What exists now", "Trust boundary"],
                ["Evidence kernel", "snapshots, manifests, stable/run identities, plans", "content integrity ≠ authorship"],
                ["MCR 0.4", "evidence/report/run IDs + target root", "self-consistency ≠ authorship"],
                ["Conformance", "PASS/WARN/BLOCK/ERROR + four negative vectors", "interoperability ≠ model safety"],
                ["Cross-language", "Python/Node/Rust vectors + Python<->Rust MCR", "repository-owned evidence"],
                ["Integrations", "Polygraphy producer + MLflow consumer", "reference, not vendor endorsement"],
                ["Security", "bounded parsing, HMAC cache, traversal/secret defenses", "isolated CI still required"],
            ],
            [36 * mm, 78 * mm, 50 * mm],
        ),
        _p("Live target milestone", styles["h2"]),
        _p(
            "RTX 4060 Laptop GPU / driver 555.97 / TensorRT 10.4.0 / Polygraphy 0.53.4：四個 build 各 629/629 backend matches；quality gate 為 PASS, PASS, BLOCK, BLOCK；first bad = build-02。此里程碑完成 repository-owned vertical，但不算 independent reproduction。",
            styles["callout"],
        ),
        PageBreak(),
        _p("六個月只押三件事", styles["h1"]),
        _table(
            [
                ["Priority", "Deliverable", "Exit signal"],
                ["1 · MCR", "language-neutral spec, compatibility, conformance, governance", "independent producer + consumer"],
                ["2 · NVIDIA/compiler", "exact GPU bundles, tactics/runtime/precision corpus", "one independently rerun target bundle"],
                ["3 · Adoption", "LLM inference, CV/edge, compiler/runtime design partners", "three retained real CI gates"],
            ],
            [35 * mm, 75 * mm, 54 * mm],
        ),
        _p("開宗立派指標", styles["h2"]),
        _p(
            "第一個非作者維護的 tool 輸出 MCR；第二個系統只 consume MCR 而不 import Python；相鄰工具 issue/PR 討論輸出 MCR；陌生作者維護 m2riv-* integration。這些都比 stars 更接近 abstraction ownership。",
            styles["body"],
        ),
        _p("Month 0 → Month 6", styles["h2"]),
        _table(
            [
                ["Metric", "Now", "M3", "M6"],
                ["External MCR producers", "0", "1", "3"],
                ["External MCR consumers", "0", "1", "3"],
                ["Active orgs with retained gates", "0", "2", "5"],
                ["Independently reproduced corpus cases", "0", "3", "10"],
                ["Unknown-to-founder integration maintainers", "0", "0", "1"],
            ],
            [92 * mm, 24 * mm, 24 * mm, 24 * mm],
        ),
        _p(
            "Repository-owned integrations and first-party GPU runs are tracked, but never counted as external adoption.",
            styles["small"],
        ),
        PageBreak(),
        _p("定位與決策護欄", styles["h1"]),
        _table(
            [
                ["Question", "Start with", "M2RIV relationship"],
                ["Prompt / RAG / agent quality", "Promptfoo / DeepEval / Inspect / Braintrust", "consume their retained evidence"],
                ["Experiment baseline validation", "MLflow", "log or promote verified MCR"],
                ["TensorRT vs ORT output debug", "Polygraphy", "preserve raw result, add release semantics"],
                ["Quantized artifact creation", "ModelOpt", "gate the produced build"],
                ["Cross-tool release handoff", "MCR", "reference producer/verifier/conformance"],
            ],
            [48 * mm, 51 * mm, 65 * mm],
        ),
        _p("Falsification", styles["h2"]),
        _p(
            "若 design partners 明確偏好 vendor-native reports、拒絕 portable promotion semantics，或相鄰標準形成廣泛採用的等價 contract，MCR moat hypothesis 便被削弱。應公開負訊號，不用擴 scope 掩蓋。",
            styles["body"],
        ),
        _p("品牌 gate", styles["h2"]),
        _p(
            "M2RIV 仍是 pre-alpha working name。公開 v0.1 前完成 10–20 人 unaided spoken recall/spelling test、近似名稱與商標檢查。RFC 0015 已把 wire namespace 解耦為 mcr:sha256；品牌不應拖延驗證，但也不能由 CI 自動清除。",
            styles["body"],
        ),
        _p(
            "Canonical pitch<br/><b>M2RIV turns model builds into reviewable release evidence.</b><br/>Polygraphy tells you whether outputs differ. MCR tells the organization whether this exact build is releasable, why, with what evidence, and where the regression began.",
            styles["callout"],
        ),
    ]
    document = _document(path, title="M2RIV Blueprint v3.0", author="M2RIV contributors")
    footer = _footer("M2RIV Blueprint v3.0 · Protocol-first strategy")
    document.build(
        story,
        onFirstPage=footer,
        onLaterPages=footer,
        canvasmaker=_invariant_canvas,
    )


def build_report(path: Path) -> None:
    styles = _styles()
    story: list[object] = [
        Spacer(1, 9 * mm),
        _p("TECHNICAL REPORT · REVISION 2026-08-29", styles["eyebrow"]),
        _p("Release Evidence for Deployable AI Models", styles["title"]),
        _p("A contract-based approach to artifact regression, statistical gating, and build localization", styles["subtitle"]),
        _p(
            "MCR is a vendor-neutral, content-addressed evidence envelope. M2RIV is its reference implementation and conformance suite—not a replacement for native model, compiler, or backend oracles.",
            styles["callout"],
        ),
        _p("Abstract", styles["h1"]),
        _p(
            "Deployable model releases cross optimizer, compiler, runtime, hardware, registry, and CI boundaries. Native tools can answer local questions while organizations still lack a portable object binding exact artifacts, evidence cohort, statistical interpretation, release policy, and first bad build. This report specifies MCR 0.4 and evaluates it with CPU ONNX cases, cross-language conformance, reference Polygraphy/MLflow integrations, and a live ModelOpt→TensorRT target execution.",
            styles["body"],
        ),
        _metrics(
            [("29", "public contracts"), ("629×4", "GPU comparisons"), ("100%", "declared backend matches"), ("build-02", "first bad")],
            styles,
        ),
        _p("Claim discipline", styles["h2"]),
        _p(
            "The GPU result is exact first-party evidence for one RTX 4060/driver/TensorRT/Polygraphy cohort. It is not an independent reproduction, a safety claim, or a cross-hardware performance ranking.",
            styles["body"],
        ),
        PageBreak(),
        _p("1 · Protocol boundary", styles["h1"]),
        _table(
            [
                ["Existing system", "Native strength", "Portable MCR role"],
                ["MLflow", "baseline-aware evaluation and validation", "consume verified decision/provenance"],
                ["Polygraphy", "runner output comparison and debug", "retain comparator result as evidence"],
                ["ModelOpt", "optimized artifact generation", "identify and gate resulting build"],
                ["TensorRT-Model-Connect", "revision/target/perf/quality validation layers", "cross-tool handoff semantics"],
            ],
            [38 * mm, 62 * mm, 64 * mm],
        ),
        _p("MCR contract", styles["h2"]),
        _p(
            "The envelope binds baseline/candidate snapshot IDs, executor/runtime provenance, paired metrics with direction and uncertainty, release policy, explicit authorization, evidence-set and supplemental references, a stable evidence ID, a decision-bound report ID, a volatile run ID, and optional ordered-build localization.",
            styles["body"],
        ),
        _p("Integrity is not authenticity", styles["h2"]),
        _p(
            "Strict verification rehashes recognized local components and rejects missing, traversing, symlinked, or inconsistent evidence. A valid bundle is internally complete; it does not identify the producer. The verifier therefore reports self-consistency-only trust unless a separate signing/attestation policy is applied.",
            styles["callout"],
        ),
        _p("Conformance", styles["h2"]),
        _p(
            "Producer fixtures cover fixed PASS, WARN, BLOCK, and ERROR vectors plus four mandatory negative cases. Consumer receipts preserve evidence/report IDs and statuses and may authorize only PASS. Python/Node/Rust identity vectors and Python<->Rust MCR interop test language neutrality. Repository ownership is disclosed and does not count as adoption.",
            styles["body"],
        ),
        PageBreak(),
        _p("2 · Experimental design", styles["h1"]),
        _table(
            [
                ["Element", "Declared method"],
                ["Dataset", "UCI handwritten digits via scikit-learn; 1,797 observations"],
                ["Holdout", "seed 23, stratified, 629 cases, unchanged between builds"],
                ["Weights", "reviewed fixed fixture with pinned SHA-256"],
                ["Critical slice", "input-declared digit 1 with normalized ink sum >= 18"],
                ["Regression", "calibration inputs ×1.0 / ×0.65 / ×0.60; weights fixed"],
                ["Policy", "overall margin 3%; critical slice margin 1.5%; paired evidence"],
            ],
            [43 * mm, 121 * mm],
        ),
        _p("CPU ONNX case", styles["h2"]),
        _p(
            "The CPU path creates FP16 and QDQ INT8 artifacts with ONNX Runtime. Linux and Windows retain separate numerical/timing evidence while preserving PASS, PASS, BLOCK, BLOCK and build-02 localization. An opset 17→18 control changes graph structure while all declared shared tensors remain equal and emits PASS.",
            styles["body"],
        ),
        _p("Why the slice matters", styles["h2"]),
        _p(
            "The slice is selected from input semantics before candidate outcomes are observed. This avoids post-hoc selection on the dependent variable. In the target run, overall accuracy drops by only 1.59 percentage points at build-02 while the slice drops by 12.77 points.",
            styles["callout"],
        ),
        PageBreak(),
        _p("3 · Live NVIDIA target execution", styles["h1"]),
        _table(
            [
                ["Cohort", "Exact value"],
                ["GPU", "NVIDIA GeForce RTX 4060 Laptop GPU · 8,188 MiB"],
                ["Software", "driver 555.97 · TensorRT 10.4.0 · Polygraphy 0.53.4"],
                ["Host", "Windows build 26200 · AMD64 · Python 3.11.15"],
                ["Comparison", "629 cases · 3 warmups · atol 0.05 · rtol 0.01"],
            ],
            [42 * mm, 122 * mm],
        ),
        _p("Execution chain", styles["h2"]),
        _p(
            "Reviewed weights → equivalent PyTorch Conv1d graph → ModelOpt 0.46 INT8 artifacts → TensorRT engines → Polygraphy sequential ONNX Runtime/TensorRT runners → retained native output and exit code → Comparator-native per-output evidence → MCR quality gate → target evidence root → monotonic bisect.",
            styles["body"],
        ),
        _table(
            [
                ["Build", "Overall", "Critical", "Parity", "Gate"],
                ["PyTorch FP16", "94.75%", "91.49%", "629/629", "PASS"],
                ["ModelOpt INT8 balanced", "94.91%", "91.49%", "629/629", "PASS"],
                ["ModelOpt INT8 scale .65", "93.32%", "78.72%", "629/629", "BLOCK"],
                ["ModelOpt INT8 scale .60", "92.85%", "74.47%", "629/629", "BLOCK"],
            ],
            [61 * mm, 25 * mm, 27 * mm, 25 * mm, 26 * mm],
            header_color=BLUE,
        ),
        _p("Verification result", styles["h2"]),
        _p(
            "First bad = build-02. Four strict MCR bundles and all backend-comparison IDs verified; unknown local references = 0. Target root mcr:sha256:b2c99b90…c125dbd covers 4,514 files. Archive SHA-256: 06a06000…21a05.",
            styles["callout"],
        ),
        _p(
            "Latency remains run-scoped and is not used here to rank builds. Windows/WDDM did not expose per-process memory through NVML, so VRAM is null with measurement state unavailable—not zero.",
            styles["small"],
        ),
        PageBreak(),
        _p("4 · Security and failure semantics", styles["h1"]),
        _table(
            [
                ["Threat", "Control", "Residual boundary"],
                ["Poisoned persistent cache", "HMAC envelope + key-domain separation", "key holders remain trusted"],
                ["Traversal / symlink evidence", "bounded local-root resolution and refusal", "host isolation still required"],
                ["Hostile ONNX", "budgets; no custom ops; external data refused", "native parser is not a sandbox"],
                ["Secret exfiltration", "metadata blocking + recursive secret canary", "operator-defined private endpoints allowed"],
                ["Incomplete evidence", "WARN/ERROR fail closed; strict coverage", "authorship needs attestation"],
            ],
            [40 * mm, 72 * mm, 52 * mm],
        ),
        _p("Target compatibility is separate", styles["h2"]),
        _p(
            "A development observation found an ONNX Runtime QDQ artifact with non-zero zero points rejected by TensorRT 10.4's symmetric-quantization requirement. Parser success, target compatibility, task quality, and performance are distinct claims; one cannot stand in for another.",
            styles["body"],
        ),
        _p("Corpus state", styles["h2"]),
        _table(
            [
                ["Case", "Status", "Expected"],
                ["ONNX calibration rare-slice regression", "verified in CI", "BLOCK / build-02"],
                ["ModelOpt→TensorRT calibration regression", "verified on one target", "BLOCK / build-02"],
                ["Recorded rare-slice regression", "verified in CI", "BLOCK"],
                ["ONNX opset structural control", "verified in CI", "PASS"],
            ],
            [78 * mm, 46 * mm, 40 * mm],
        ),
        PageBreak(),
        _p("5 · Falsifiability and adoption", styles["h1"]),
        _p(
            "The protocol hypothesis is weakened if design partners reject portable promotion semantics or an adjacent standard becomes the accepted equivalent contract. The project must publish these signals instead of hiding them through scope expansion.",
            styles["body"],
        ),
        _table(
            [
                ["Next proof", "Why it matters"],
                ["Independent GPU rerun", "separates reproducibility from first-party execution"],
                ["External producer + consumer", "tests whether MCR is a protocol rather than output format"],
                ["Three retained design-partner gates", "tests organizational promotion semantics"],
                ["Ten independent corpus cases", "tests generality across artifact axes"],
            ],
            [60 * mm, 104 * mm],
        ),
        _p("References", styles["h2"]),
        _p(
            "MCR specification · docs/mcr-specification.md<br/>MCR conformance · docs/mcr-conformance.md<br/>MLflow evaluation · mlflow.org/docs/latest/ml/evaluation<br/>NVIDIA Polygraphy, Model Optimizer, and TensorRT-Model-Connect · NVIDIA documentation",
            styles["small"],
        ),
        Spacer(1, 4 * mm),
        _p(
            "Conclusion<br/><b>MCR's claim is narrow and testable:</b> deployable model changes should carry portable, reviewable release evidence across tool boundaries. The reference implementation now demonstrates the complete path from artifact and retained native backend oracle to strict bundle/target-root verification and first-bad localization.",
            styles["callout"],
        ),
    ]
    document = _document(
        path,
        title="Release Evidence for Deployable AI Models",
        author="M2RIV contributors",
    )
    footer = _footer("M2RIV Technical Report · Release Evidence for Deployable AI Models")
    document.build(
        story,
        onFirstPage=footer,
        onLaterPages=footer,
        canvasmaker=_invariant_canvas,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/pdf"))
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    _register_fonts()
    blueprint = arguments.output / "M2RIV_Blueprint_v3.0.pdf"
    report = arguments.output / "M2RIV_Release_Evidence_Technical_Report.pdf"
    build_blueprint(blueprint)
    build_report(report)
    print(blueprint)
    print(report)


if __name__ == "__main__":
    main()
