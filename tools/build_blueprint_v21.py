"""Build the v2.1 correction front-matter and stamp superseded v2.0 pages."""

# ruff: noqa: E501, RUF001

from __future__ import annotations

import argparse
import html
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#0B132B")
BLUE = colors.HexColor("#276FBF")
CYAN = colors.HexColor("#18A0AE")
PALE = colors.HexColor("#EAF4F7")
RED = colors.HexColor("#B42318")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#526071")
WHITE = colors.white


def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("M2RIV-TC", r"C:\Windows\Fonts\msjh.ttc"))
    pdfmetrics.registerFont(TTFont("M2RIV-TC-Bold", r"C:\Windows\Fonts\msjhbd.ttc"))


def _styles() -> dict[str, ParagraphStyle]:
    defaults = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=defaults["Title"],
            fontName="M2RIV-TC-Bold",
            fontSize=25,
            leading=32,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=defaults["Normal"],
            fontName="M2RIV-TC",
            fontSize=12,
            leading=18,
            textColor=MUTED,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=defaults["Heading1"],
            fontName="M2RIV-TC-Bold",
            fontSize=18,
            leading=24,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=defaults["Heading2"],
            fontName="M2RIV-TC-Bold",
            fontSize=12,
            leading=17,
            textColor=BLUE,
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=defaults["BodyText"],
            fontName="M2RIV-TC",
            fontSize=9.5,
            leading=15,
            textColor=INK,
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=defaults["BodyText"],
            fontName="M2RIV-TC",
            fontSize=7.7,
            leading=11.5,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=defaults["BodyText"],
            fontName="M2RIV-TC-Bold",
            fontSize=13,
            leading=20,
            alignment=TA_CENTER,
            textColor=NAVY,
            borderColor=CYAN,
            borderWidth=1,
            borderPadding=12,
            backColor=PALE,
            spaceBefore=8,
            spaceAfter=14,
        ),
    }


def _footer(pdf: canvas.Canvas, document: SimpleDocTemplate) -> None:
    pdf.saveState()
    width, _ = A4
    pdf.setStrokeColor(colors.HexColor("#CAD5DF"))
    pdf.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    pdf.setFont("M2RIV-TC", 7.5)
    pdf.setFillColor(MUTED)
    pdf.drawString(18 * mm, 8 * mm, "M2RIV Blueprint v2.1 - Technical Correction")
    pdf.drawRightString(width - 18 * mm, 8 * mm, f"Correction page {document.page}")
    pdf.restoreState()


def _table(data: list[list[object]], widths: list[float]) -> Table:
    header_style = ParagraphStyle(
        "TableHeader",
        fontName="M2RIV-TC-Bold",
        fontSize=7.2,
        leading=9.2,
        textColor=WHITE,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        fontName="M2RIV-TC",
        fontSize=6.7,
        leading=9.2,
        textColor=INK,
    )
    wrapped = [
        [
            Paragraph(html.escape(str(cell)), header_style if row_index == 0 else cell_style)
            for cell in row
        ]
        for row_index, row in enumerate(data)
    ]
    result = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "M2RIV-TC-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "M2RIV-TC"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C5D0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#F5F8FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return result


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def build_correction(target: Path) -> None:
    styles = _styles()
    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="M2RIV Model Release Engineering Blueprint v2.1 Technical Correction",
        author="M2RIV contributors",
    )
    story: list[object] = []

    story.extend(
        [
            Spacer(1, 12 * mm),
            _p("M2RIV", styles["title"]),
            _p("MODEL RELEASE ENGINEERING BLUEPRINT", styles["h1"]),
            _p("v2.1 Technical Correction and Implementation Evidence", styles["subtitle"]),
            _p(
                "本修正前編取代 v2.0 的競爭地圖、第一個公開 demo、技術引用與命名確定性。"
                "原始 27 頁保留在後方作歷史記錄；已失效頁面加上 SUPERSEDED 標記。",
                styles["callout"],
            ),
            _p("修正後的一句話定位", styles["h2"]),
            _p(
                "M2RIV 是 deployable model artifact 的 release gate。它比較量化、編譯、轉換或 runtime-specific build 與 baseline，"
                "先做 artifact semantic diff，再以 paired confidence interval 判斷 regression，並在有序 build sequence 上定位第一個壞版本。",
                styles["body"],
            ),
            _p("不再主張的內容", styles["h2"]),
            _p(
                "不再主張 CI evaluation 或 deployment gate 是空白市場。Promptfoo、DeepEval / Confident AI、Braintrust、Inspect AI 已覆蓋"
                "應用、agent、安全與 LLM eval 的重要工作流。M2RIV 的 wedge 改為 quantization / compiler / runtime / hardware artifact regression。",
                styles["body"],
            ),
            _p("目前已實際跑通的 deployment demo", styles["h2"]),
            _table(
                [
                    ["Build", "Overall", "Critical rare slice", "Gate"],
                    ["build-00-fp16", "94.75%", "91.49%", "PASS"],
                    ["build-01-int8-balanced", "94.75–94.91%", "91.49–93.62%", "PASS"],
                    ["build-02-int8-calibration-scale-065", "92.85–93.16%", "74.47–78.72%", "BLOCK"],
                    [
                        "build-03-int8-calibration-scale-060",
                        "92.37–92.85%*",
                        "70.21–76.60%",
                        "BLOCK",
                    ],
                ],
                [76 * mm, 25 * mm, 38 * mm, 22 * mm],
            ),
            Spacer(1, 4 * mm),
            _p(
                "Bisect result: first bad build = build-02-int8-calibration-scale-065. Dataset 為 scikit-learn 內建的 UCI handwritten digits，"
                "1,797 個真實樣本；固定且有 SHA-256 的 sklearn MLP fixture；全程 CPUExecutionProvider。* 精確值以執行主機產生的 "
                "MCR 為準；CI 對 Linux/Windows 驗證有界差異、相同 gate 與 first-bad 結果。",
                styles["small"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            _p("1. 重新繪製競爭邊界", styles["h1"]),
            _p(
                "Application evaluation 已經成熟。差異不能寫成『別人只顯示 score』，而應寫成被測事件與證據物件不同。",
                styles["body"],
            ),
            _table(
                [
                    ["Project", "已驗證的核心", "M2RIV 的邊界"],
                    ["Promptfoo", "AI app eval、red teaming、static scan、CI；2026-03-09 宣布由 OpenAI 收購。", "部署 artifact、compiler/runtime build provenance、paired artifact regression、build bisect。"],
                    ["DeepEval / Confident AI", "Pytest-style LLM app metrics；governance policy 可在 CI block deployment。", "不建立 evaluator zoo；外部 metric 可作 evidence input。"],
                    ["Braintrust", "Immutable experiments、CI comparison、production feedback。", "local-first artifact identity、portable MCR、vendor-neutral executor。"],
                    ["Inspect AI", "LLM task / dataset / solver / scorer / agent / sandbox framework。", "Inspect suite 可輸入 evidence，但不是 M2RIV 的 benchmark surface。"],
                    ["NVIDIA ModelOpt", "Quantization、distillation、pruning、sparsity、deployment export。", "ModelOpt 產生 build；M2RIV 判斷 build 是否可取代 baseline。"],
                    ["ONNX Runtime", "Static / dynamic quantization、QDQ / QOperator、calibration、execution。", "ORT 產生並執行 graph；M2RIV 保存 semantic diff、gate、MCR、bisect。"],
                ],
                [31 * mm, 66 * mm, 66 * mm],
            ),
            Spacer(1, 5 * mm),
            _p(
                "Canonical positioning: Application-evaluation tools test prompts, agents, RAG systems, and model behavior. Optimization and compiler tools produce deployment artifacts. M2RIV connects the second event to release engineering.",
                styles["callout"],
            ),
            _p(
                "此定位是可被市場推翻的 boundary hypothesis，不是 priority 或 exclusivity claim。若相鄰工具加入完整 artifact provenance、paired statistical gate 與 ordered-build localization，本頁必須更新。",
                styles["small"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            _p("2. 已完成的 deployment-side implementation", styles["h1"]),
            _p("ArtifactProfile / ArtifactDiff", styles["h2"]),
            _p(
                "新增 inference-free ONNX inspection：artifact hash、opset、operator count、initializer dtype、initializer element count、graph I/O、"
                "QDQ / QOperator form、external tensor-data presence，以及 config / tokenizer sidecar hash。Diff 是 content-addressed public contract。",
                styles["body"],
            ),
            _p("OnnxRuntimeAdapter", styles["h2"]),
            _p(
                "新增 optional、CPU-only adapter。它拒絕 external tensor data，不註冊 custom-op library，將 runtime version、provider、I/O、"
                "thread 設定納入 snapshot / cache identity，並對 input/output element count 設上限。",
                styles["body"],
            ),
            _p("安全與誠實邊界", styles["h2"]),
            _table(
                [
                    ["Threat", "Control", "仍然不保證"],
                    ["Parser/resource bomb", "512 MiB default file limit；node、initializer、metadata、rank、I/O cardinality limits。", "Native ONNX parser 不是 sandbox。"],
                    ["External path traversal", "Inspection 不載入 external data；reference runtime 直接拒絕 external tensor data。", "未來 large-model external data 需隔離 worker contract。"],
                    ["Custom native code", "不載入 custom-op library；只指定 CPUExecutionProvider。", "ONNX Runtime 本身仍是 native dependency。"],
                    ["TOCTOU", "解析前後重算 artifact hash；改變即 fail closed。", "Hostile shared filesystem 仍需 OS isolation。"],
                ],
                [38 * mm, 72 * mm, 53 * mm],
            ),
            Spacer(1, 5 * mm),
            _p("Core dependency policy", styles["h2"]),
            _p(
                "核心依賴仍只有 httpx、pydantic、PyYAML、typer。numpy、onnx、onnxruntime、scikit-learn 全部是 optional extra。"
                "因此 recorded-output、schema、gate、stats、report 與 air-gapped core 不被重型 ML stack 綁住。",
                styles["callout"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            _p("3. 真實 demo 的證據鏈", styles["h1"]),
            _p("資料與模型", styles["h2"]),
            _p(
                "資料來自 sklearn.datasets.load_digits 對 UCI Optical Recognition of Handwritten Digits 的內建副本。固定 seed 23，"
                "stratified holdout 35%。訓練 split 只保留 digit 1 的 29 / 118 個樣本，使它成為有文件記錄的 rare training class。",
                styles["body"],
            ),
            _p("風險 slice", styles["h2"]),
            _p(
                "Critical slice 在 inference 前由輸入定義：digit = 1 且 normalized ink sum >= 18，共 47 cases。這個規則沒有使用 baseline 或 candidate outcome 選樣本。",
                styles["body"],
            ),
            _p("轉換序列", styles["h2"]),
            _p(
                "同一組學得的 MLP weights 先輸出 FP16 ONNX baseline；FP32 source 經 ONNX Runtime preprocessing 後產生 static INT8 QDQ。"
                "Build-01 使用正常 calibration；Build-02 / 03 故意把 calibration inputs scale 到 0.75 / 0.70，模擬 deployment calibration config regression。",
                styles["body"],
            ),
            _p("判定與定位", styles["h2"]),
            _p(
                "629 cases 逐一 paired，4,000 bootstrap resamples，95% CI。Overall non-inferiority margin = 3%；critical slice margin = 1.5%。"
                "Build-02 整體只下降 1.11%，critical slice 卻單向下降 10.64%，故 gate BLOCK。Monotonic bisect 以 4 次 evaluation 找到 PASS/BLOCK 相鄰邊界 1 -> 2。",
                styles["body"],
            ),
            _p("輸出", styles["h2"]),
            _p(
                "每個 build 產生 artifact-diff.json、release-plan.json、m2riv-report.json、summary.md、junit.xml、results.sarif；"
                "序列另產生 checkpoints.jsonl 與 bisect-result.json。所有 artifact 與 evidence identity 都可離線重算。",
                styles["body"],
            ),
            _p(
                "限制：這證明的是固定資料、固定模型與固定 calibration sequence 下的 paired release regression；不是所有手寫數字分布、所有量化方法或安全性的普遍證明。",
                styles["callout"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            _p("4. Reference 與品牌修正", styles["h1"]),
            _p("引用修正", styles["h2"]),
            _p(
                "v2.0 的 R8 / R9 並非不存在，但只寫『GitHub』而沒有 repository path，不符合可稽核標準。完整來源如下；"
                "R10 / R20 是內部命名敘述，不再列入外部 bibliography；R11-R19 的命名 collision 筆記移出技術論證。",
                styles["body"],
            ),
            _p(
                "R8a https://github.com/dcdeve/tracepact<br/>"
                "R8b https://github.com/hidai25/eval-view<br/>"
                "R9 https://github.com/sulthonzh/prompt-bisect",
                styles["small"],
            ),
            _p("新增必列來源", styles["h2"]),
            _p(
                "Promptfoo / OpenAI: https://www.promptfoo.dev/blog/promptfoo-joining-openai/<br/>"
                "DeepEval: https://deepeval.com/docs/introduction<br/>"
                "Confident AI gate: https://www.confident-ai.com/docs/ai-governance/policies/gate-deployments-in-ci-cd<br/>"
                "Braintrust: https://www.braintrust.dev/docs/evaluate/run-evaluations<br/>"
                "Inspect AI: https://inspect.aisi.org.uk/<br/>"
                "NVIDIA Model Optimizer: https://github.com/NVIDIA/Model-Optimizer<br/>"
                "ONNX Runtime quantization: https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html",
                styles["small"],
            ),
            _p("名稱決策", styles["h2"]),
            _p(
                "M2RIV 降級為 pre-alpha working name。撤回『第一次看到即可自然念對』的宣稱。公開 v0.1 前必須完成 10 人 unaided spoken-name test、"
                "GitHub / PyPI / package / domain near-match search、專業 trademark review、三個 cleared alternatives 比較，以及 m2riv:sha256 protocol namespace migration decision。",
                styles["body"],
            ),
            _p(
                "目前不立即換名的理由不是保護既有品牌，而是避免用另一個未 clearance 的即興名稱取代它。Brand gate 未通過前，不應累積公開 stars、integration 或 stable consumer。",
                styles["callout"],
            ),
            _p("Superseded original pages", styles["h2"]),
            _p(
                "原始 PDF 第 3-5 頁的 category / competition / brand certainty，以及第 24-26 頁的 references / naming conclusions，"
                "已由本修正前編取代，並在後方原頁加上紅色標記。其餘架構與工程原則仍可作歷史設計來源，但以 repository RFC 與測試結果為準。",
                styles["body"],
            ),
        ]
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _stamp_page(page: object, label: str) -> None:
    width = float(page.mediabox.width)  # type: ignore[attr-defined]
    height = float(page.mediabox.height)  # type: ignore[attr-defined]
    buffer = BytesIO()
    overlay = canvas.Canvas(buffer, pagesize=(width, height))
    overlay.setFillColor(colors.Color(0.70, 0.08, 0.06, alpha=0.92))
    overlay.rect(0, height - 27, width, 27, stroke=0, fill=1)
    overlay.setFillColor(WHITE)
    overlay.setFont("Helvetica-Bold", 9)
    overlay.drawCentredString(
        width / 2,
        height - 18,
        f"SUPERSEDED BY v2.1 TECHNICAL CORRECTION - {label}",
    )
    overlay.save()
    buffer.seek(0)
    page.merge_page(PdfReader(buffer).pages[0])  # type: ignore[attr-defined]


def build_final(source: Path, correction: Path, target: Path) -> None:
    original = PdfReader(source)
    correction_reader = PdfReader(correction)
    writer = PdfWriter()
    for page in correction_reader.pages:
        writer.add_page(page)
    superseded = {
        2: "CATEGORY MAP",
        3: "COMPETITION MAP",
        4: "BRAND CERTAINTY",
        23: "REFERENCES",
        24: "REFERENCES / NAMING",
        25: "NAMING CONCLUSION",
    }
    for index, page in enumerate(original.pages):
        if index in superseded:
            _stamp_page(page, superseded[index])
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": "M2RIV Model Release Engineering Blueprint v2.1",
            "/Subject": "Technical correction, implementation evidence, and v2.0 history",
            "/Author": "M2RIV contributors",
        }
    )
    with target.open("wb") as stream:
        writer.write(stream)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/M2RIV_Model_Release_Engineering_Blueprint_v2.1.pdf"),
    )
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path("tmp/pdfs/M2RIV_v2.1_correction.pdf")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    _register_fonts()
    build_correction(temporary)
    build_final(arguments.source, temporary, arguments.output)
    print(arguments.output)


if __name__ == "__main__":
    main()
