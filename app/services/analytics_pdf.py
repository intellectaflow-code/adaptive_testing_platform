import os
import math
import tempfile
from fastapi.responses import FileResponse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors


PAGE_WIDTH, PAGE_HEIGHT = A4  # 595.27 x 841.89

# ── COLORS ──────────────────────────────────────────────
GOLD       = HexColor("#F5A623")
GOLD_DARK  = HexColor("#E09000")
WHITE      = white
BLACK      = black
DARK       = HexColor("#1A1A2E")
GRAY_TEXT  = HexColor("#555555")
LIGHT_GRAY = HexColor("#F5F5F5")
BORDER_CLR = HexColor("#E0E0E0")
GREEN_CLR  = HexColor("#4CAF50")
RED_CLR    = HexColor("#F44336")
AMBER_CLR  = HexColor("#FF9800")
BLUE_CLR   = HexColor("#2196F3")
SUMMARY_BG = HexColor("#AEFF5E")


# ══════════════════════════════════════════════════════════
# CHART GENERATORS
# ══════════════════════════════════════════════════════════

def make_test_line_chart(trend_data, out_path):
    """Generate line chart for test average scores"""
    labels = [x["title"] for x in trend_data]
    scores = [float(x["avg_score"] or 0) for x in trend_data]
    overall_avg = sum(scores) / len(scores) if scores else 0

    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    ax.plot(labels, scores, color="#F5A623", marker="o",
            linewidth=2.5, markersize=5, label="Test Average", zorder=3)
    ax.axhline(overall_avg, color="#AAAAAA", linestyle="--",
               linewidth=1.5, label="Overall Average")

    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.tick_params(axis="both", labelsize=7)
    ax.set_xlabel("Tests Taken", fontsize=7, color="#555")
    ax.set_ylabel("Avg Score", fontsize=7, color="#555")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=6.5, loc="lower right", framealpha=0.8, edgecolor="#ccc")
    plt.tight_layout(pad=0.4)
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


def make_pass_rate_bar_chart(trend_data, out_path):
    """Generate pass/fail bar chart using pass_rate field"""
    labels = [x["title"] for x in trend_data]
    passes = []
    fails = []
    
    for x in trend_data:
        # Try to get pass_rate, fallback to calculating from 100 - pass_rate
        pass_rate = float(x.get("pass_rate", 50) or 50)
        fail_rate = 100 - pass_rate
        passes.append(pass_rate)
        fails.append(fail_rate)

    x = np.arange(len(labels))
    width = 0.34

    fig, ax = plt.subplots(figsize=(5.8, 3.2))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    ax.bar(x - width/2, passes, width, color="#F5A623", label="Pass", zorder=3)
    ax.bar(x + width/2, fails,  width, color="#F44336", label="Fail",  zorder=3)

    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.5, rotation=0)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlabel("Tests Taken", fontsize=7, color="#555")
    ax.set_ylabel("Students %", fontsize=7, color="#555")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=6.5, loc="upper right", framealpha=0.8, edgecolor="#ccc")
    plt.tight_layout(pad=0.5)
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


def make_donut_chart(distribution, out_path):
    """Generate donut chart for student at-risk distribution"""
    on_track  = distribution.get("on_track", 0)
    needs_imp = distribution.get("needs_improvement", 0)
    at_risk   = distribution.get("at_risk", 0)
    sizes = [on_track, needs_imp, at_risk]
    clrs  = ["#F5A623", "#4CAF50", "#F44336"]
    if sum(sizes) == 0:
        sizes = [1, 1, 1]

    fig, ax = plt.subplots(figsize=(2.4, 2.4))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.pie(sizes, colors=clrs, startangle=90,
           wedgeprops=dict(width=0.5, edgecolor="white", linewidth=2))
    plt.tight_layout(pad=0.1)
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


def make_assignment_line_chart(assignment_data, out_path):
    """Generate line chart for assignment average scores"""
    labels = [x["title"] for x in assignment_data]
    scores = [float(x["avg_score"] or 0) for x in assignment_data]
    overall_avg = sum(scores) / len(scores) if scores else 0

    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    ax.plot(labels, scores, color="#F5A623", marker="o",
            linewidth=2.5, markersize=5, label="Assignment Average", zorder=3)
    ax.axhline(overall_avg, color="#AAAAAA", linestyle="--",
               linewidth=1.5, label="Overall Average")

    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.tick_params(axis="both", labelsize=7)
    ax.set_xlabel("Assignments Given", fontsize=7, color="#555")
    ax.set_ylabel("Avg Score", fontsize=7, color="#555")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=6.5, loc="lower right", framealpha=0.8, edgecolor="#ccc")
    plt.tight_layout(pad=0.4)
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


def make_submissions_bar_chart(assignment_data, out_path):
    """Generate bar chart for assignment submission rates"""
    labels    = [x["title"] for x in assignment_data]
    submitted = [float(x.get("submitted", 85)) for x in assignment_data]
    missing   = [100 - s for s in submitted]
    x = np.arange(len(labels))
    w = 0.35

    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    ax.bar(x - w/2, submitted, w, color="#F5A623", label="Submitted", zorder=3)
    ax.bar(x + w/2, missing,   w, color="#F44336", label="Missing",   zorder=3)

    ax.set_ylim(0, 110)
    ax.set_yticks(range(0, 101, 10))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlabel("Assignments Given", fontsize=7, color="#555")
    ax.set_ylabel("Students %", fontsize=7, color="#555")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=6.5, loc="upper right", framealpha=0.8, edgecolor="#ccc")
    plt.tight_layout(pad=0.4)
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


def make_comparison_line_chart(test_data, assignment_data, out_path):
    """Generate comparison line chart between test and assignment scores"""
    test_scores = [float(x["avg_score"] or 0) for x in test_data]
    asgn_scores = [float(x["avg_score"] or 0) for x in assignment_data]
    n  = max(len(test_scores), len(asgn_scores))
    xs = list(range(1, n + 1))

    t_avg = sum(test_scores) / len(test_scores) if test_scores else 0
    a_avg = sum(asgn_scores) / len(asgn_scores) if asgn_scores else 0

    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    ax.plot(xs[:len(asgn_scores)], asgn_scores, color="#F44336", marker="o",
            linewidth=2.5, markersize=5, label="Assignment Average")
    ax.axhline(a_avg, color="#F44336", linestyle="--", linewidth=1.2)

    ax.plot(xs[:len(test_scores)], test_scores, color="#F5A623", marker="o",
            linewidth=2.5, markersize=5, label="Test Average")
    ax.axhline(t_avg, color="#F5A623", linestyle="--", linewidth=1.2)

    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))
    ax.set_xticks(xs)
    ax.tick_params(axis="both", labelsize=7)
    ax.set_xlabel("Tests and Assignment Number", fontsize=7, color="#555")
    ax.set_ylabel("Avg Score", fontsize=7, color="#555")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=6.5, loc="lower right", framealpha=0.8, edgecolor="#ccc")
    plt.tight_layout(pad=0.4)
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()


# ══════════════════════════════════════════════════════════
# PDF HELPERS
# ══════════════════════════════════════════════════════════

def draw_gold_header(c, title):
    bar_h = 56
    c.setFillColor(GOLD)
    c.rect(0, PAGE_HEIGHT - bar_h, PAGE_WIDTH, bar_h, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.circle(28, PAGE_HEIGHT - bar_h / 2, 15, fill=1, stroke=0)
    c.setFillColor(GOLD_DARK)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(28, PAGE_HEIGHT - bar_h / 2 - 4, "IF")

    c.setStrokeColor(WHITE)
    c.setLineWidth(1.5)
    c.line(52, PAGE_HEIGHT - 14, 52, PAGE_HEIGHT - bar_h + 14)

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(62, PAGE_HEIGHT - bar_h / 2 + 5, "IntellectaFlow")
    c.setFont("Helvetica", 14)
    c.drawString(62 + 118, PAGE_HEIGHT - bar_h / 2 + 5, "  |  " + title)


def draw_divider(c, y):
    c.setStrokeColor(BORDER_CLR)
    c.setLineWidth(0.5)
    c.line(30, y, PAGE_WIDTH - 30, y)


def draw_section_title(c, x, y, text, color=GOLD):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, text)
    w = c.stringWidth(text, "Helvetica-Bold", 13)
    c.setStrokeColor(color)
    c.setLineWidth(1.5)
    c.line(x, y - 3, x + w, y - 3)


def draw_kv(c, x, y, label, value, val_color=DARK):
    c.setFillColor(GRAY_TEXT)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, label)
    lw = c.stringWidth(label, "Helvetica-Bold", 10)
    c.setFillColor(val_color)
    c.setFont("Helvetica", 10)
    c.drawString(x + lw + 4, y, str(value))


def draw_green_callout(c, x, y, w, h, lines):
    c.setFillColor(HexColor("#E8F5E9"))
    c.roundRect(x, y, w, h, 8, fill=1, stroke=0)
    c.setFillColor(HexColor("#2E7D32"))
    c.setFont("Helvetica-Bold", 8)
    ty = y + h - 14
    for line in lines:
        c.drawString(x + 8, ty, line)
        ty -= 13


def draw_bordered_box(c, x, y, w, h, title=None, title_bg=DARK):
    c.setFillColor(WHITE)
    c.setStrokeColor(BORDER_CLR)
    c.setLineWidth(0.6)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=1)
    if title:
        bar_h = 20
        c.setFillColor(title_bg)
        c.roundRect(x, y + h - bar_h, w, bar_h, 6, fill=1, stroke=0)
        c.rect(x, y + h - bar_h, w, bar_h / 2, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + 8, y + h - 14, title)


def place_image(c, path, x, y, w, h):
    if path and os.path.exists(path):
        c.drawImage(ImageReader(path), x, y,
                    width=w, height=h,
                    preserveAspectRatio=True, anchor="c")


def draw_student_table(
    c,
    data,
    x,
    y,
    col_widths,
    header_color,
    card_width,
    title,
):
    row_count = len(data)

    row_h = 24
    header_h = 26
    padding = 10

    table_h = row_count * row_h

    total_h = table_h + header_h + padding

    # ── CARD ─────────────────────────────
    c.setFillColor(WHITE)
    c.setStrokeColor(BORDER_CLR)
    c.setLineWidth(0.8)

    c.roundRect(
        x,
        y - total_h,
        card_width,
        total_h,
        10,
        fill=1,
        stroke=1,
    )

    # ── TOP HEADER BAR ───────────────────
    c.setFillColor(header_color)

    c.roundRect(
        x,
        y - header_h,
        card_width,
        header_h,
        10,
        fill=1,
        stroke=0,
    )

    # fix rounded bottom bleed
    c.rect(
        x,
        y - header_h,
        card_width,
        header_h / 2,
        fill=1,
        stroke=0,
    )

    # ── TITLE ────────────────────────────
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 12, y - 17, title)

    # ── TABLE ────────────────────────────
    tbl = Table(
        data,
        colWidths=col_widths,
        rowHeights=[row_h] * row_count,
    )

    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),

        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),

        ("FONTSIZE", (0, 0), (-1, -1), 8.5),

        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),

        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DDDDDD")),

        ("ROWBACKGROUNDS",
         (0, 1),
         (-1, -1),
         [colors.white, colors.HexColor("#FAFAFA")]),

        ("ALIGN", (1, 0), (1, -1), "CENTER"),

        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),

        ("TEXTCOLOR", (0, 1), (-1, -1), DARK),
    ]))

    table_y = y - header_h - table_h + 2

    tbl.wrapOn(c, 0, 0)
    tbl.drawOn(c, x + 4, table_y)


# ══════════════════════════════════════════════════════════
# PAGE 1  —  Test Performance Analysis
# ══════════════════════════════════════════════════════════

def build_page1(c, analytics, chart_paths):
    stats = analytics["stats"]
    dist  = analytics["distribution"]

    # ── HEADER ───────────────────────────────────────────
    draw_gold_header(c, "Class Analytics Report")
    TOP = PAGE_HEIGHT - 56

    # ── INFO ROW ─────────────────────────────────────────
    c.setFillColor(WHITE)
    c.rect(0, TOP - 32, PAGE_WIDTH, 32, fill=1, stroke=0)
    draw_divider(c, TOP - 1)
    draw_divider(c, TOP - 32)

    info_items = [
        ("Subject:",           stats.get("code", analytics["course"].get("code", ""))),
        ("Total Students:",    str(stats["total_students"])),
        ("Total Tests:",       str(stats["total_tests"])),
        ("Total Assignments:", str(stats["total_assignments"])),
    ]
    ix = 32
    for label, val in info_items:
        c.setFillColor(DARK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(ix, TOP - 21, label)
        lw = c.stringWidth(label, "Helvetica-Bold", 9)
        c.setFont("Helvetica", 9)
        c.drawString(ix + lw + 3, TOP - 21, val)
        ix += 130

    # ── SECTION TITLE: Test Metrics ───────────────────────
    sec_y = TOP - 56
    draw_section_title(c, 32, sec_y, "Test Metrics")
    draw_divider(c, sec_y - 10)

    # ── KV METRICS (left column) ──────────────────────────
    left_x = 32
    kv_top = sec_y - 34
    KV_GAP = 24
    draw_kv(c, left_x, kv_top,              "Overall Average Score:", f" {stats['overall_average_score']}%", GOLD)
    draw_kv(c, left_x, kv_top - KV_GAP,     "Improvement Rate:",      f" +{stats['improvement_rate']}%",    GREEN_CLR)
    draw_kv(c, left_x, kv_top - KV_GAP*2,   "Consistency Score:",     f" {stats['consistency_score']}")
    draw_kv(c, left_x, kv_top - KV_GAP*3,   "Engagement:",            f" {stats['engagement']}")

    # ── GREEN CALLOUT (middle) ─────────────────────────────
    callout_lines = [
        f"A +{stats['improvement_rate']}% improvement",
        "rate shows positive",
        "learning progress, but",
        "the growth is gradual",
        "and can be accelerated",
        "with focused practice.",
    ]
    callout_h = 96
    callout_y = kv_top - callout_h + 14
    draw_green_callout(c, 194, callout_y, 132, callout_h, callout_lines)

    # ── DONUT (right column) ──────────────────────────────
    donut_label_x = 342
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(donut_label_x, kv_top + 6, "Students At-Risk Distribution:")

    donut_sz  = 92
    donut_x   = donut_label_x
    donut_y   = kv_top - donut_sz + 4
    place_image(c, chart_paths["donut"], donut_x, donut_y, donut_sz, donut_sz)

    leg_bul_x = donut_x + donut_sz + 8
    legend_items = [
        ("#F5A623", f"{dist['on_track']}% On Track"),
        ("#4CAF50", f"{dist['needs_improvement']}% Needs Improvement"),
        ("#F44336", f"{dist['at_risk']}% At Risk"),
    ]
    bly = donut_y + donut_sz - 8
    for hex_clr, label in legend_items:
        c.setFillColor(HexColor(hex_clr))
        c.circle(leg_bul_x + 5, bly + 3, 5, fill=1, stroke=0)
        c.setFillColor(DARK)
        c.setFont("Helvetica", 8)
        c.drawString(leg_bul_x + 13, bly, label)
        bly -= 22

    # ── DIVIDER ───────────────────────────────────────────
    metrics_bottom = kv_top - KV_GAP * 3 - 16
    divider_y = min(metrics_bottom, donut_y - 10)
    draw_divider(c, divider_y)

    # ── TEST PERFORMANCE TREND TITLE ─────────────────────
    trend_title_y = divider_y - 22
    draw_section_title(c, 32, trend_title_y, "Test Performance Trend")

    # ── CHART PAIR ────────────────────────────────────────
    chart_h = 148
    chart_y = trend_title_y - 18 - chart_h
    chart_w = 258

    # Left chart box
    c.setFillColor(WHITE)
    c.setStrokeColor(BORDER_CLR)
    c.setLineWidth(0.6)
    c.roundRect(28, chart_y, chart_w, chart_h + 8, 6, fill=1, stroke=1)
    place_image(c, chart_paths["test_line"], 32, chart_y + 4, chart_w - 8, chart_h)

    # Right chart box
    rx = 32 + chart_w + 8
    rw = PAGE_WIDTH - rx - 26
    c.setFillColor(WHITE)
    c.setStrokeColor(BORDER_CLR)
    c.setLineWidth(0.6)
    c.roundRect(rx - 4, chart_y, rw, chart_h + 8, 6, fill=1, stroke=1)
    place_image(c, chart_paths["pass_bar"], rx, chart_y + 4, rw - 8, chart_h)

    # Legends below charts
    leg_y = chart_y - 16
    # Left legend
    c.setStrokeColor(HexColor("#AAAAAA"))
    c.setLineWidth(1)
    c.setDash(3, 2)
    c.line(36, leg_y + 4, 56, leg_y + 4)
    c.setDash()
    c.setFillColor(GRAY_TEXT)
    c.setFont("Helvetica", 7)
    c.drawString(58, leg_y + 1, "Overall Average")
    c.setStrokeColor(GOLD)
    c.setLineWidth(2)
    c.line(130, leg_y + 4, 150, leg_y + 4)
    c.setFillColor(GRAY_TEXT)
    c.drawString(152, leg_y + 1, "Test Average")
    # Right legend
    c.setFillColor(GOLD)
    c.rect(rx + 2, leg_y, 10, 8, fill=1, stroke=0)
    c.setFillColor(GRAY_TEXT)
    c.setFont("Helvetica", 7)
    c.drawString(rx + 14, leg_y + 1, "Pass")
    c.setFillColor(RED_CLR)
    c.rect(rx + 46, leg_y, 10, 8, fill=1, stroke=0)
    c.setFillColor(GRAY_TEXT)
    c.drawString(rx + 58, leg_y + 1, "Fail")

    # ── INSIGHT BOX ───────────────────────────────────────
    insight_y = leg_y - 22
    insight_text = (
        "Recent test shows a sharp overall improvement, with both average score "
        "and pass rate rising together, indicating broad class recovery."
    )
    c.setFillColor(HexColor("#FFFDE7"))
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.6)
    c.roundRect(28, insight_y, PAGE_WIDTH - 56, 30, 5, fill=1, stroke=1)
    c.setFillColor(DARK)
    c.setFont("Helvetica", 8.5)
    words = insight_text.split()
    line, lines_out = "", []
    for word in words:
        test = (line + " " + word).strip()
        if c.stringWidth(test, "Helvetica", 8.5) < PAGE_WIDTH - 84:
            line = test
        else:
            lines_out.append(line)
            line = word
    lines_out.append(line)
    for i, l in enumerate(lines_out):
        c.drawString(36, insight_y + 19 - i * 12, l)

    # ── DIVIDER + TABLES ──────────────────────────────────
    div_y = insight_y - 18
    draw_divider(c, div_y)

    table_y = div_y - 18

    top_data = [["Name", "Avg. Score"]]
    for i, s in enumerate(analytics["top_students"]):
        avg = float(s.get("avg_score") or 0)
        top_data.append([f"{i+1}. {s['full_name']}", f"{avg:.2f}%"])

    weak_data = [["Name", "Avg. Score"]]
    for i, s in enumerate(analytics["weak_students"]):
        avg = float(s.get("avg_score") or 0)
        weak_data.append([f"{i+1}. {s['full_name']}", f"{avg:.2f}%"])

    table_top_y = div_y - 24

    left_x = 28
    right_x = 298

    draw_student_table(
        c,
        top_data,
        left_x,
        table_top_y,
        [188, 55],
        colors.HexColor("#1A1A2E"),
        255,
        "Top 5 Students",
    )

    draw_student_table(
        c,
        weak_data,
        right_x,
        table_top_y,
        [198, 55],
        colors.HexColor("#D32F2F"),
        265,
        "Weak Students",
    )




def draw_chart_card(c, img_path, x, y, w, h):

    c.setFillColor(WHITE)
    c.setStrokeColor(BORDER_CLR)

    c.roundRect(
        x,
        y,
        w,
        h,
        12,
        fill=1,
        stroke=1,
    )

    c.drawImage(
        img_path,
        x + 10,
        y + 10,
        width=w - 20,
        height=h - 20,
        preserveAspectRatio=True,
        mask='auto'
    )



def build_page2(c, analytics, chart_paths):

    stats = analytics["stats"]

    # ─────────────────────────────────────
    # HEADER
    # ─────────────────────────────────────
    draw_gold_header(c, "Class Analytics Report")

    content_x = 32
    content_w = PAGE_WIDTH - 64

    current_y = PAGE_HEIGHT - 90

    # =====================================================
    # ASSIGNMENT METRICS
    # =====================================================

    draw_section_title(c, content_x, current_y, "Assignment Metrics")

    current_y -= 34

    metric_card_w = (content_w - 16) / 2
    metric_card_h = 72

    metrics = [
        ("Overall Average Score", f"{stats['assignment_average']}%", GOLD),
        ("Consistency Score", stats["consistency_score"], DARK),
        ("Improvement Rate", f"+{stats['improvement_rate']}%", GREEN_CLR),
        ("Submissions", stats["engagement"], RED_CLR),
    ]

    positions = [
        (content_x, current_y),
        (content_x + metric_card_w + 16, current_y),
        (content_x, current_y - 84),
        (content_x + metric_card_w + 16, current_y - 84),
    ]

    for (title, value, color), (mx, my) in zip(metrics, positions):

        c.setFillColor(WHITE)
        c.setStrokeColor(BORDER_CLR)
        c.setLineWidth(0.7)

        c.roundRect(
            mx,
            my - metric_card_h,
            metric_card_w,
            metric_card_h,
            12,
            fill=1,
            stroke=1,
        )

        c.setFillColor(GRAY_TEXT)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(mx + 14, my - 24, title)

        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(mx + 14, my - 52, str(value))

    # =====================================================
    # CHARTS ROW
    # =====================================================

    current_y -= 200

    chart_gap = 16
    chart_w = (content_w - chart_gap) / 2
    chart_h = 210

    # LEFT CHART
    draw_section_title(
        c,
        content_x,
        current_y,
        "Assignment Score Trend"
    )

    chart_y = current_y - 228

    draw_chart_card(
        c,
        chart_paths["asgn_line"],
        content_x,
        chart_y,
        chart_w,
        chart_h,
    )

    # RIGHT CHART
    draw_section_title(
        c,
        content_x + chart_w + chart_gap,
        current_y,
        "Submission Analysis"
    )

    draw_chart_card(
        c,
        chart_paths["submissions_bar"],
        content_x + chart_w + chart_gap,
        chart_y,
        chart_w,
        chart_h,
    )

    # =====================================================
    # FULL WIDTH COMPARISON CHART
    # =====================================================

    current_y = chart_y - 34

    draw_section_title(
        c,
        content_x,
        current_y,
        "Assignment vs Test Score Comparison"
    )

    comparison_h = 230
    comparison_y = current_y - 248

    draw_chart_card(
        c,
        chart_paths["comparison"],
        content_x,
        comparison_y,
        content_w,
        comparison_h,
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    summary_y = comparison_y - 125

    c.setFillColor(HexColor("#E8F8D8"))
    c.setStrokeColor(HexColor("#CFE8A9"))

    c.roundRect(
        content_x,
        summary_y,
        content_w,
        100,
        12,
        fill=1,
        stroke=1,
    )

    c.setFillColor(DARK)

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        summary_y + 72,
        "Summary"
    )

    summary_text = (
        "Overall assignment performance shows measurable improvement "
        "with stronger outcomes in recent submissions. Students perform "
        "better in guided assignments than in tests, suggesting that "
        "exam readiness and conceptual reinforcement still require "
        "additional attention and practice."
    )

    c.setFont("Helvetica", 9)

    words = summary_text.split()

    lines = []
    line = ""

    for word in words:

        test = (line + " " + word).strip()

        if c.stringWidth(test, "Helvetica", 9) < content_w - 60:
            line = test
        else:
            lines.append(line)
            line = word

    lines.append(line)

    ty = summary_y + 50

    for ln in lines:
        c.drawCentredString(PAGE_WIDTH / 2, ty, ln)
        ty -= 14

# ══════════════════════════════════════════════════════════
# MAIN ENTRY POINT  (FastAPI async)
# ══════════════════════════════════════════════════════════

async def generate_class_analytics_pdf(analytics: dict):
    """
    Generates a two-page A4 analytics PDF.

    Expected analytics dict structure:
    {
      "course": { "id", "name", "code", "semester", "branch" },
      "stats": { "overall_average_score", "improvement_rate", 
                 "consistency_score", "engagement", "assignment_average",
                 "assignment_submission_rate", ... },
      "distribution": { "on_track", "needs_improvement", "at_risk" },
      "top_students": [ { "full_name", "avg_score" }, ... ],
      "weak_students": [ { "full_name", "avg_score" }, ... ],
      "test_trend": [ { "title", "avg_score", "pass_rate" }, ... ],
      "assignment_trend": [ { "title", "avg_score", "submitted", "missing" }, ... ],
    }
    """

    tmp         = tempfile.mkdtemp()
    output_path = os.path.join(tmp, "analytics_report.pdf")

    chart_paths = {
        "test_line":       os.path.join(tmp, "test_line.png"),
        "pass_bar":        os.path.join(tmp, "pass_bar.png"),
        "donut":           os.path.join(tmp, "donut.png"),
        "asgn_line":       os.path.join(tmp, "asgn_line.png"),
        "submissions_bar": os.path.join(tmp, "submissions_bar.png"),
        "comparison":      os.path.join(tmp, "comparison.png"),
    }

    # Generate all charts
    make_test_line_chart(analytics["test_trend"],     chart_paths["test_line"])
    make_pass_rate_bar_chart(analytics["test_trend"],  chart_paths["pass_bar"])
    make_donut_chart(analytics["distribution"],        chart_paths["donut"])

    if analytics.get("assignment_trend"):
        make_assignment_line_chart(
            analytics["assignment_trend"], chart_paths["asgn_line"])
        make_submissions_bar_chart(
            analytics["assignment_trend"], chart_paths["submissions_bar"])
        make_comparison_line_chart(
            analytics["test_trend"],
            analytics["assignment_trend"],
            chart_paths["comparison"]
        )

    # Build PDF
    cv = canvas.Canvas(output_path, pagesize=A4)
    build_page1(cv, analytics, chart_paths)
    cv.showPage()
    build_page2(cv, analytics, chart_paths)
    cv.save()

    course_code = analytics["course"].get("code", "course")
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"{course_code}_analytics_report.pdf"
    )