"""Grouped accuracy bars from logs/13 (corrected scores, Extra3 included)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

OUT_DIR = Path(__file__).resolve().parent

# (label, fast_correct, agent_correct); denom = 7+36+40+24
DENOM = 207
ROWS = (
    ("DS-V4-Flash", 207, 207),
    ("GPT-5.6-Luna", 206, 207),
    ("MiniMax-M3", 205, 206),
    ("Kimi-K2.5", 205, 206),
    ("mimo-v2.5-pro", 206, 207),
    ("GLM-5.3", 206, 207),
    ("Qwen3.8-Max", 207, 207),
    ("Gemini-3.1-Pro", 207, 207),
)

FAST_FACE = "#1B4332"
AGENT_FACE = "#74C69D"
EDGE = "#1B4332"


def _configure_fonts() -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"],
            "font.family": "sans-serif",
            "axes.unicode_minus": False,
            "axes.linewidth": 0.8,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "figure.facecolor": "white",
            "axes.facecolor": "#F7FBF8",
            "axes.edgecolor": "#1B4332",
            "text.color": "#081C15",
            "axes.labelcolor": "#081C15",
            "xtick.color": "#1B4332",
            "ytick.color": "#1B4332",
        }
    )


def _save_pdf_and_png(fig, stem: Path) -> tuple[Path, Path]:
    png = stem.with_suffix(".png")
    pdf = stem.with_suffix(".pdf")
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    return png, pdf


def draw() -> tuple[Path, Path]:
    _configure_fonts()
    labels = [row[0] for row in ROWS]
    fast = np.array([100.0 * row[1] / DENOM for row in ROWS])
    agent = np.array([100.0 * row[2] / DENOM for row in ROWS])

    x = np.arange(len(labels), dtype=float)
    width = 0.36

    fig, ax = plt.subplots(figsize=(10.4, 4.8), dpi=300)
    fig.patch.set_facecolor("white")

    bars_fast = ax.bar(
        x - width / 2,
        fast,
        width,
        label="快捷路径",
        facecolor=FAST_FACE,
        edgecolor=EDGE,
        linewidth=0.8,
        zorder=3,
    )
    bars_agent = ax.bar(
        x + width / 2,
        agent,
        width,
        label="Agent 路径",
        facecolor=AGENT_FACE,
        edgecolor=EDGE,
        linewidth=0.8,
        zorder=3,
    )

    for bars, color in ((bars_fast, FAST_FACE), (bars_agent, "#2D6A4F")):
        for rect in bars:
            h = rect.get_height()
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                h + 0.12,
                f"{h:.1f}",
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=color,
                zorder=4,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5, rotation=18, ha="right")
    ax.tick_params(axis="x", length=0, pad=2)
    ax.set_ylabel("准确率（%）", fontsize=12, labelpad=7)
    ax.set_ylim(96.0, 101.0)
    ax.set_xlim(-0.62, len(labels) - 0.38)
    ax.set_title("各模型评测准确率", fontsize=15, pad=22, fontweight="medium")

    ax.yaxis.set_major_locator(mticker.MultipleLocator(1))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(0.5))
    ax.yaxis.set_tick_params(labelsize=10)
    ax.grid(axis="y", which="major", color="#95D5B2", linestyle="--", linewidth=0.55, alpha=0.55)
    ax.grid(axis="y", which="minor", color="#D8F3DC", linestyle=":", linewidth=0.45, alpha=0.75)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(
        frameon=False,
        fontsize=10,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.0),
        ncol=2,
        handlelength=1.1,
        borderaxespad=0.0,
    )

    fig.subplots_adjust(left=0.07, right=0.985, top=0.86, bottom=0.22)
    paths = _save_pdf_and_png(fig, OUT_DIR / "eval_accuracy_bar")
    plt.close(fig)
    return paths


if __name__ == "__main__":
    png, pdf = draw()
    print(png)
    print(pdf)
