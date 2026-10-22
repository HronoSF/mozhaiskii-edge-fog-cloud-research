#!/usr/bin/env python3
"""Generate one SVG plot of all 12 measured scenario medians from the public CSV.

This does not collect or alter experimental results. No third-party packages.
"""
import csv
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data/scenario-results.csv").open(newline="")))
assert len(rows) == 12
categories = [
    ("steady", "unshaped", "Steady, Normal"),
    ("steady", "delay20", "Steady, +20 ms"),
    ("burst", "unshaped", "Burst, Normal"),
    ("burst", "delay20", "Burst, +20 ms"),
]
algorithms = [
    ("rr", "Round Robin", "#466A9A"),
    ("compute_ect", "Compute-ECT", "#C28A37"),
    ("network_ect", "Network-ECT", "#258579"),
]
left, width, chart_width, top, step, height = 335, 1300, 860, 122, 43, 755
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
    f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>',
]
for tick in (0, 50, 100, 150, 200, 250, 300):
    x = left + round(tick / 300 * chart_width)
    parts.append(f'<line x1="{x}" y1="102" x2="{x}" y2="650" stroke="#d7dade" stroke-width="1.1"/>')
    parts.append(f'<text x="{x}" y="676" font-family="Georgia,serif" font-size="18" text-anchor="middle" fill="#333">{tick}</text>')
for i, (_, label, color) in enumerate(algorithms):
    x = 350 + i * 280
    parts.append(f'<rect x="{x}" y="35" width="27" height="14" fill="{color}"/>')
    parts.append(f'<text x="{x+37}" y="48" font-family="Georgia,serif" font-size="18" fill="#252525">{label}</text>')
for g, (arrival, network, group_label) in enumerate(categories):
    for j, (policy, algorithm, color) in enumerate(algorithms):
        candidates = [r for r in rows if r["arrival_pattern"] == arrival and r["network_condition"] == network and r["scheduler"] == policy]
        assert len(candidates) == 1, (arrival, network, policy)
        row = candidates[0]
        latency = float(row["median_latency_ms"])
        y = top + (g * 3 + j) * step + g * 9
        w = latency / 300 * chart_width
        parts.append(f'<text x="{left-12}" y="{y+22}" font-family="Georgia,serif" font-size="17" text-anchor="end" fill="#222">{escape(group_label+" - "+algorithm)}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{w:.2f}" height="30" fill="{color}" opacity=".92"/>')
        parts.append(f'<text x="{left+w+10:.2f}" y="{y+22}" font-family="Georgia,serif" font-size="18" fill="#222">{latency:.1f}</text>')
        if row["on_time"] == "11":
            parts.append(f'<text x="{width-20}" y="{y+22}" font-family="Georgia,serif" font-size="17" text-anchor="end" fill="#983f37">11/12 on time</text>')
    if g < 3:
        y = top + (g+1) * 3 * step + g * 9 - 5
        parts.append(f'<line x1="{left}" y1="{y}" x2="{width-20}" y2="{y}" stroke="#a4a9b0" stroke-width="1"/>')
parts.append(f'<text x="{left+chart_width/2}" y="718" font-family="Georgia,serif" font-size="21" text-anchor="middle" fill="#222">Median end-to-end latency from planned release (ms)</text>')
parts.append("</svg>")
(ROOT / "figures/median-latency.svg").write_text("\n".join(parts)+"\n")
print("Rendered 12 measured rows - no new experiment")
