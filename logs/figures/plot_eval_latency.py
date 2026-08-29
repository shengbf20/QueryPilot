"""Box + scatter of per-case wall time (DeepSeek-chat).

Official columns use the 2026-08-29 noshort reports (exact few-shot off),
so Q3/Q6/Q7 include model generate time. Extra36/Extra2 stay on 2026-08-21.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.transforms import blended_transform_factory
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "logs" / "eval_reports"
OUT_DIR = Path(__file__).resolve().parent

# Extra3 is intent-fence only (sub-ms); it would collapse the scale.
PATHS = ("快捷路径", "Agent 路径")
SETS = ("官方", "补充评测一", "补充评测二")
FILES = {
    ("快捷路径", "官方"): "gold_fast_noshort.json",
    ("快捷路径", "补充评测一"): "extra36_fast.json",
    ("快捷路径", "补充评测二"): "extra2_fast.json",
    ("Agent 路径", "官方"): "gold_agent_noshort.json",
    ("Agent 路径", "补充评测一"): "extra36_agent.json",
    ("Agent 路径", "补充评测二"): "extra2_agent.json",
}

# Fast group: deeper green; Agent group: lighter sage.
BOX = {
    "快捷路径": ("#1B4332", "#D8F3DC"),
    "Agent 路径": ("#2D6A4F", "#B7E4C7"),
}
DOT = {
    "官方": "#1B4332",
    "补充评测一": "#2D6A4F",
    "补充评测二": "#52B788",
}


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


def load_columns() -> list[tuple[str, str, np.ndarray]]:
    columns: list[tuple[str, str, np.ndarray]] = []
    for path in PATHS:
        for subset in SETS:
            payload = json.loads((REPORT_DIR / FILES[(path, subset)]).read_text(encoding="utf-8"))
            vals = [
                float((row.get("timing") or {}).get("total_ms") or 0.0) / 1000.0
                for row in payload["results"]
            ]
            columns.append((path, subset, np.asarray(vals, dtype=float)))
    return columns


def _jitter(n: int, center: float, width: float, rng: np.random.Generator) -> np.ndarray:
    return center + rng.uniform(-width, width, size=n)


def draw() -> Path:
    _configure_fonts()
    columns = load_columns()
    rng = np.random.default_rng(20260821)

    # Tight columns; small gap only between the two path groups.
    positions = np.array([1.00, 1.49, 1.98, 2.72, 3.21, 3.70])

    fig, ax = plt.subplots(figsize=(6.6, 4.7), dpi=300)
    fig.patch.set_facecolor("white")

    for pos, (path, subset, vals) in zip(positions, columns, strict=True):
        edge, face = BOX[path]
        ax.boxplot(
            [vals],
            positions=[pos],
            widths=0.26,
            whis=(5, 95),
            showfliers=False,
            patch_artist=True,
            boxprops=dict(facecolor=face, edgecolor=edge, linewidth=1.15, alpha=0.95),
            medianprops=dict(color=edge, linewidth=1.7),
            whiskerprops=dict(color=edge, linewidth=1.0),
            capprops=dict(color=edge, linewidth=1.0),
            zorder=2,
        )
        ax.scatter(
            _jitter(len(vals), pos, 0.055, rng),
            vals,
            s=24 if subset == "官方" else 16,
            c=DOT[subset],
            edgecolors="white",
            linewidths=0.35,
            alpha=0.8,
            zorder=3,
        )
        median = float(np.median(vals))
        q3 = float(np.percentile(vals, 75))
        ax.text(
            pos,
            max(median + 0.22, q3 + 0.18),
            f"{median:.1f}",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=edge,
            zorder=4,
        )

    ax.set_xticks(positions)
    ax.set_xticklabels(list(SETS) * 2, fontsize=9.5)
    ax.tick_params(axis="x", length=0, pad=4)
    ax.set_ylabel("单题总耗时（秒）", fontsize=12, labelpad=7)
    ax.set_xlim(0.70, 4.00)
    ax.set_ylim(0, 15.2)
    ax.set_title("评测单题总耗时", fontsize=15, pad=11, fontweight="medium")

    ax.yaxis.set_major_locator(mticker.MultipleLocator(2))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(1))
    ax.yaxis.set_tick_params(labelsize=10)
    ax.grid(axis="y", which="major", color="#95D5B2", linestyle="--", linewidth=0.55, alpha=0.55)
    ax.grid(axis="y", which="minor", color="#D8F3DC", linestyle=":", linewidth=0.45, alpha=0.75)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    trans = blended_transform_factory(ax.transData, ax.transAxes)
    for left, right, label in (
        (positions[0], positions[2], "快捷路径"),
        (positions[3], positions[5], "Agent 路径"),
    ):
        ax.plot(
            [left, right],
            [-0.078, -0.078],
            transform=trans,
            color="#2D6A4F",
            lw=0.9,
            clip_on=False,
            solid_capstyle="butt",
        )
        ax.text(
            (left + right) / 2,
            -0.128,
            label,
            transform=trans,
            ha="center",
            va="top",
            fontsize=11.5,
            color="#1B4332",
            clip_on=False,
        )

    fig.subplots_adjust(left=0.10, right=0.985, top=0.90, bottom=0.20)

    png, pdf = _save_pdf_and_png(fig, OUT_DIR / "eval_latency_boxplot")
    plt.close(fig)
    return png, pdf


def _save_pdf_and_png(fig, stem: Path) -> tuple[Path, Path]:
    png = stem.with_suffix(".png")
    pdf = stem.with_suffix(".pdf")
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    return png, pdf


if __name__ == "__main__":
    png, pdf = draw()
    print(png)
    print(pdf)
