# Monitor Peak Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mark the peak point in both HTML monitor charts and optional PNG monitor charts.

**Architecture:** Keep all behavior in `autoperf/report_generator.py`, where monitor reports are already generated. Compute the first maximum point per metric from existing `labels` and `series` data, include it in the HTML payload for canvas drawing, and reuse the same first-peak rule for matplotlib PNG annotations.

**Tech Stack:** Python standard library, HTML canvas JavaScript, optional matplotlib, unittest.

---

### Task 1: HTML peak annotation data and drawing

**Files:**
- Modify: `tests/test_report_generator.py`
- Modify: `autoperf/report_generator.py`

- [ ] **Step 1: Write the failing test**

Add a test that generates a monitor report with a clear CPU peak and asserts the HTML payload contains the peak value/index/time and the canvas script contains peak label drawing.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_report_generator.MonitorReportTimeAxisTests.test_html_report_includes_peak_annotations`
Expected: FAIL because `peaks` is not yet in the payload.

- [ ] **Step 3: Write minimal implementation**

Add a helper that returns the first peak for each metric, include it in the HTML payload, and draw a red point plus `peak: value` label on each canvas chart.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_report_generator.MonitorReportTimeAxisTests.test_html_report_includes_peak_annotations`
Expected: PASS.

### Task 2: PNG peak annotation

**Files:**
- Modify: `autoperf/report_generator.py`

- [ ] **Step 1: Reuse the peak helper**

In `generate_png_reports`, find the first peak for each metric and annotate it with a red marker and `peak: value` text.

- [ ] **Step 2: Run focused tests**

Run: `python -m unittest tests.test_report_generator`
Expected: PASS. PNG generation remains optional when matplotlib is absent.
