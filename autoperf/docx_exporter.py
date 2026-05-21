from __future__ import annotations

import csv
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .utils import AutoPerfError


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}
ET.register_namespace("w", WORD_NS)

SECTION_TITLES = {
    "baseline": "基准测试",
    "single_concurrency": "单交易并发",
    "multi_process": "多进程并发",
    "stability": "稳定性测试",
}

SECTION_MARKERS = {
    "{{AUTOPERF_BASELINE_TABLE}}": "baseline",
    "{{AUTOPERF_SINGLE_TABLE}}": "single_concurrency",
    "{{AUTOPERF_MULTI_TABLE}}": "multi_process",
    "{{AUTOPERF_STABILITY_TABLE}}": "stability",
    "{{AUTOPERF_RESOURCE_SUMMARY}}": "resource_summary",
}

TABLE_HEADERS = [
    "任务",
    "进程数",
    "内部线程数",
    "并发用户数",
    "运行时长(s)",
    "事务数",
    "平均值(ms)",
    "90%百分位(ms)",
    "最小值(ms)",
    "最大值(ms)",
    "异常%",
    "吞吐量(/min)",
    "NPU峰值(%)",
    "显存峰值(MiB)",
    "内存峰值(GB)",
]


@dataclass
class RunResult:
    path: Path
    test_name: str
    service_workers: int
    service_threads: int
    threads: int
    duration: int
    label: str
    samples: int
    average_ms: float
    p90_ms: float
    min_ms: float
    max_ms: float
    error_pct: float
    throughput_per_sec: float
    cpu_peak: float
    mem_peak: float
    npu_usage_peak: float
    npu_mem_peak: float


def collect_run_results(results_root: Path) -> list[RunResult]:
    root = Path(results_root)
    if not root.is_dir():
        raise AutoPerfError(f"results directory not found: {root}")

    results = []
    for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        config_file = run_dir / "config.json"
        aggregate_file = run_dir / "jmeter_aggregate_report.csv"
        monitor_file = run_dir / "monitor" / "monitor.csv"
        if not config_file.exists() and not aggregate_file.exists() and not monitor_file.exists():
            continue
        if not config_file.is_file() or not aggregate_file.is_file() or not monitor_file.is_file():
            raise AutoPerfError(f"incomplete AutoPerf result directory: {run_dir}")
        results.append(_read_run_result(run_dir, config_file, aggregate_file, monitor_file))

    if not results:
        raise AutoPerfError(f"no AutoPerf result directories found in: {root}")
    return sorted(results, key=lambda item: (classify_result(item), item.label, item.service_workers, item.service_threads, item.threads, item.duration))


def classify_result(result: RunResult) -> str:
    if result.duration >= 3600:
        return "stability"
    if result.service_workers > 1:
        return "multi_process"
    if result.service_threads > 1 or result.threads > 1:
        return "single_concurrency"
    return "baseline"


def export_docx_report(results_root: Path, template: Path, output: Path) -> Path:
    results = collect_run_results(results_root)
    template = Path(template)
    output = Path(output)
    if not template.is_file():
        raise AutoPerfError(f"DOCX template not found: {template}")
    if output.resolve() == template.resolve():
        raise AutoPerfError("output DOCX must not be the template path")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(template, "r") as zf:
            zf.extractall(tmp_path)

        document_file = tmp_path / "word" / "document.xml"
        if not document_file.is_file():
            raise AutoPerfError(f"template missing word/document.xml: {template}")
        _update_document_xml(document_file, results)

        if output.exists():
            output.unlink()
        _zip_dir(tmp_path, output)
    return output


def _read_run_result(run_dir: Path, config_file: Path, aggregate_file: Path, monitor_file: Path) -> RunResult:
    with config_file.open("r", encoding="utf-8") as fp:
        config = json.load(fp)
    aggregate = _read_aggregate_row(aggregate_file)
    monitor = _read_monitor_peaks(monitor_file)
    return RunResult(
        path=run_dir,
        test_name=str(config.get("test_name") or aggregate["label"]),
        service_workers=int(config.get("service_workers", 1)),
        service_threads=int(config.get("service_threads", 1)),
        threads=int(config.get("threads", 1)),
        duration=int(config.get("duration", 0)),
        label=str(aggregate["label"]),
        samples=int(float(aggregate["samples"])),
        average_ms=float(aggregate["average_ms"]),
        p90_ms=float(aggregate["p90_ms"]),
        min_ms=float(aggregate["min_ms"]),
        max_ms=float(aggregate["max_ms"]),
        error_pct=float(str(aggregate["error_pct"]).rstrip("%")),
        throughput_per_sec=float(aggregate["throughput_per_sec"]),
        cpu_peak=monitor["cpu_usage"],
        mem_peak=monitor["mem_usage"],
        npu_usage_peak=monitor["npu_usage"],
        npu_mem_peak=monitor["npu_mem"],
    )


def _read_aggregate_row(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    if not rows:
        raise AutoPerfError(f"JMeter aggregate CSV is empty: {path}")
    for row in rows:
        if (row.get("label") or "").upper() != "TOTAL":
            return row
    return rows[0]


def _read_monitor_peaks(path: Path) -> dict[str, float]:
    peaks = {"cpu_usage": 0.0, "mem_usage": 0.0, "npu_usage": 0.0, "npu_mem": 0.0}
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            for key in peaks:
                try:
                    peaks[key] = max(peaks[key], float(row.get(key, 0) or 0))
                except ValueError:
                    pass
    return peaks


def _update_document_xml(document_file: Path, results: list[RunResult]) -> None:
    tree = ET.parse(document_file)
    root = tree.getroot()
    body = root.find("w:body", NS)
    if body is None:
        raise AutoPerfError("template document.xml missing w:body")

    grouped = _group_results(results)
    children = list(body)
    replaced = False
    new_children = []
    for child in children:
        marker = SECTION_MARKERS.get(_paragraph_text(child))
        if marker is None:
            new_children.append(child)
            continue
        replaced = True
        if marker == "resource_summary":
            new_children.extend(_resource_summary_elements(results))
        else:
            new_children.extend(_section_elements(marker, grouped[marker]))

    if replaced:
        body[:] = new_children
    else:
        insert_at = len(body)
        if insert_at and _local_name(body[insert_at - 1].tag) == "sectPr":
            insert_at -= 1
        for element in reversed(_fallback_elements(grouped, results)):
            body.insert(insert_at, element)

    tree.write(document_file, encoding="utf-8", xml_declaration=True)


def _group_results(results: list[RunResult]) -> dict[str, list[RunResult]]:
    grouped = {key: [] for key in SECTION_TITLES}
    for result in results:
        grouped[classify_result(result)].append(result)
    for values in grouped.values():
        values.sort(key=lambda item: (item.label, item.service_workers, item.service_threads, item.threads, item.duration))
    return grouped


def _fallback_elements(grouped: dict[str, list[RunResult]], results: list[RunResult]) -> list[ET.Element]:
    elements = [_paragraph("AutoPerf 自动汇总结果", bold=True)]
    for section, rows in grouped.items():
        if rows:
            elements.extend(_section_elements(section, rows))
    elements.extend(_resource_summary_elements(results))
    return elements


def _section_elements(section: str, rows: list[RunResult]) -> list[ET.Element]:
    elements = [_paragraph(SECTION_TITLES[section], bold=True)]
    if rows:
        elements.append(_table([TABLE_HEADERS] + [_row_values(row) for row in rows]))
    else:
        elements.append(_paragraph("未发现该场景的测试结果。"))
    return elements


def _resource_summary_elements(results: list[RunResult]) -> list[ET.Element]:
    elements = [_paragraph("资源占用峰值说明", bold=True)]
    for result in results:
        elements.append(
            _paragraph(
                (
                    f"{result.label}：CPU峰值{result.cpu_peak:.2f}%，"
                    f"NPU峰值{result.npu_usage_peak:.2f}%，"
                    f"显存峰值{result.npu_mem_peak:.0f}MiB，"
                    f"内存峰值{result.mem_peak:.2f}GB。"
                )
            )
        )
    return elements


def _row_values(result: RunResult) -> list[str]:
    return [
        result.label,
        str(result.service_workers),
        str(result.service_threads),
        str(result.threads),
        str(result.duration),
        str(result.samples),
        f"{result.average_ms:.2f}",
        f"{result.p90_ms:.2f}",
        f"{result.min_ms:.2f}",
        f"{result.max_ms:.2f}",
        f"{result.error_pct:.2f}%",
        f"{result.throughput_per_sec * 60:.2f}",
        f"{result.npu_usage_peak:.2f}",
        f"{result.npu_mem_peak:.0f}",
        f"{result.mem_peak:.2f}",
    ]


def _paragraph(text: str, *, bold: bool = False) -> ET.Element:
    p = ET.Element(_w("p"))
    r = ET.SubElement(p, _w("r"))
    if bold:
        rpr = ET.SubElement(r, _w("rPr"))
        ET.SubElement(rpr, _w("b"))
    t = ET.SubElement(r, _w("t"))
    t.text = text
    return p


def _table(rows: list[list[str]]) -> ET.Element:
    tbl = ET.Element(_w("tbl"))
    tbl_pr = ET.SubElement(tbl, _w("tblPr"))
    borders = ET.SubElement(tbl_pr, _w("tblBorders"))
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        ET.SubElement(borders, _w(name), {_w("val"): "single", _w("sz"): "4", _w("space"): "0", _w("color"): "auto"})
    for row in rows:
        tr = ET.SubElement(tbl, _w("tr"))
        for value in row:
            tc = ET.SubElement(tr, _w("tc"))
            ET.SubElement(tc, _w("tcPr"))
            tc.append(_paragraph(value))
    return tbl


def _paragraph_text(element: ET.Element) -> str:
    if _local_name(element.tag) != "p":
        return ""
    return "".join(text.text or "" for text in element.findall(".//w:t", NS)).strip()


def _zip_dir(src: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())


def _w(name: str) -> str:
    return f"{{{WORD_NS}}}{name}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
