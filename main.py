#!/usr/bin/env python3
"""Forecast a big game launch's Twitch viewers, hour by hour, as quantiles.

Reads one case file per run (makefun/twitch-ccu-case/v1): the first hour's
print of the release day plus every comparable past launch's hourly curve.
Writes /output/<id>.out with five quantiles (5/25/50/75/95%) for hours 2..24.

Method, in one paragraph: every comparable launch is reduced to its launch-day
shape, the log of each hour's viewers over that launch's hour-1 viewers. The
forecast median for an hour is the weighted median of those log shapes, where
a comparable's weight is a Gaussian kernel on how close its own hour-1 size
is to this case's hour-1 print (launches that opened at a similar scale grew
the most like this one), restricted to console-only launches when enough of
them carry weight, with the kernel widened automatically until the effective
sample is at least six launches so a huge opening never rests on one or two
comparables. The spread for an hour comes from the weighted interquartile
range of the same log shapes. A small share of the median then comes from a
ridge fit of the log shape on (distance in log hour-1 size, console flag),
which pulls small openings up and big openings down along the slope the
comparables actually show. Everything is a pure function of the case file:
no clock, no randomness, no network, so two runs agree byte for byte.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
ZSCORE = (-1.645, -0.674, 0.0, 0.674, 1.645)

# Kernel widths tried, narrow first, until the console set is big enough.
BANDS = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
MIN_EFFECTIVE = 6.0
# Ridge fit that supplies the small corrective share of the median.
RIDGE_BAND = 2.0
RIDGE = 10.0
RIDGE_SHARE = 0.25
RIDGE_SPREAD = 0.9
# Multiplier on the kernel spread.
SPREAD_MULT = 1.0
# Last-resort spread when no comparable covers an hour at all.
FALLBACK_SPREAD = 0.15


def parse_instant(text):
    """ISO 8601 instant -> aware datetime, tolerating a trailing Z."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def day_viewers(comp):
    """Hour number (1..24) -> viewers on the comparable's release day."""
    start = parse_instant(comp["day_start"])
    out = {}
    for row in comp.get("hourly") or []:
        try:
            at = parse_instant(row["from"])
            viewers = row["viewers"]
        except (KeyError, TypeError, ValueError):
            continue
        if viewers is None:
            continue
        slot = int((at - start).total_seconds() // 3600) + 1
        if 1 <= slot <= 24:
            out[slot] = float(viewers)
    return out


def is_console(comp):
    """True when the launch had no PC release listed."""
    platforms = comp.get("platforms") or ""
    return "PC" not in platforms


def log_shapes(comp):
    """(hour-1 viewers, hour -> log(viewers / hour-1)) for one comparable.

    Returns None when the launch has no usable opening hour or too few
    points to say anything about its shape.
    """
    day = day_viewers(comp)
    first = day.get(1)
    if not first or first <= 0:
        return None
    shape = {}
    for hour, viewers in day.items():
        if viewers and viewers > 0:
            shape[hour] = math.log(max(viewers, 1.0) / first)
    if len(shape) < 2:
        return None
    return first, shape


def kernel_weight(log_first, log_print, band):
    gap = (log_first - log_print) / band
    return math.exp(-0.5 * gap * gap)


def weighted_median(pairs):
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    seen = 0.0
    for value, weight in ordered:
        seen += weight
        if seen >= total / 2.0:
            return value
    return ordered[-1][0]


def weighted_quantile(pairs, level):
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    seen = 0.0
    for value, weight in ordered:
        seen += weight
        if seen >= total * level:
            return value
    return ordered[-1][0]


def effective_n(weights):
    total = sum(weights)
    if total <= 0:
        return 0.0
    return total * total / sum(w * w for w in weights)


def pick_band(shapes, log_print, console_only):
    """Narrowest kernel width whose effective sample reaches the floor."""
    for band in BANDS:
        weights = [
            kernel_weight(math.log(first), log_print, band)
            for first, _shape, console in shapes
            if (console or not console_only)
        ]
        if effective_n(weights) >= MIN_EFFECTIVE:
            return band
    return BANDS[-1]


def kernel_stats(shapes, log_print, band, console_only):
    """Per hour (median log shape, spread) from kernel-weighted comparables."""
    stats = {}
    for hour in range(2, 25):
        pairs = []
        for first, shape, console in shapes:
            if console_only and not console:
                continue
            if hour in shape:
                pairs.append(
                    (shape[hour], kernel_weight(math.log(first), log_print, band))
                )
        if not pairs:
            continue
        middle = weighted_median(pairs)
        low = weighted_quantile(pairs, 0.25)
        high = weighted_quantile(pairs, 0.75)
        spread = max((high - low) / 1.349, 0.05) * SPREAD_MULT
        stats[hour] = (middle, spread)
    return stats


def solve3(matrix, vector):
    """Gaussian elimination with partial pivoting for a 3x3 system."""
    rows = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        rows[col] = [v / scale for v in rows[col]]
        for r in range(3):
            if r != col and rows[r][col] != 0.0:
                factor = rows[r][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col])]
    return [rows[i][3] for i in range(3)]


def ridge_stats(shapes, log_print):
    """Per hour (median, spread) from a ridge fit on log-size gap + console.

    Predicts at gap 0 for a console launch. Returns {} when the fit cannot
    be trusted (too few points or a singular system).
    """
    stats = {}
    for hour in range(2, 25):
        points = []
        for first, shape, console in shapes:
            if hour not in shape:
                continue
            gap = math.log(first) - log_print
            weight = kernel_weight(math.log(first), log_print, RIDGE_BAND)
            points.append((gap, 1.0 if console else 0.0, shape[hour], weight))
        if len(points) < 8:
            return {}
        normal = [[0.0] * 3 for _ in range(3)]
        rhs = [0.0] * 3
        for gap, flag, value, weight in points:
            feats = (1.0, gap, flag)
            for i in range(3):
                rhs[i] += weight * feats[i] * value
                for j in range(3):
                    normal[i][j] += weight * feats[i] * feats[j]
        for i in (1, 2):
            normal[i][i] += RIDGE
        coef = solve3(normal, rhs)
        if coef is None or not all(math.isfinite(c) for c in coef):
            return {}
        intercept, slope, console_bonus = coef
        centre = intercept + console_bonus
        residuals = [
            value - (intercept + slope * gap + console_bonus * flag)
            for gap, flag, value, _w in points
        ]
        mean_res = sum(residuals) / len(residuals)
        var = sum((r - mean_res) ** 2 for r in residuals) / len(residuals)
        spread = max(math.sqrt(var), 0.05) * RIDGE_SPREAD
        stats[hour] = (centre, spread)
    return stats


def nearest_stats(stats, hour):
    """Stats for the closest covered hour, else None."""
    if hour in stats:
        return stats[hour]
    for step in range(1, 24):
        for other in (hour - step, hour + step):
            if other in stats:
                return stats[other]
    return None


def forecast_case(case):
    known = (case.get("known") or [{}])[0]
    first_print = known.get("viewers")
    if not first_print or first_print <= 0:
        first_print = 1.0
    first_print = float(first_print)
    log_print = math.log(max(first_print, 1.0))

    shapes = []
    for comp in case.get("comparables") or []:
        parsed = log_shapes(comp)
        if parsed is None:
            continue
        first, shape = parsed
        shapes.append((first, shape, is_console(comp)))
    if not shapes:
        raise ValueError("case has no usable comparables")

    band = pick_band(shapes, log_print, console_only=True)
    main = kernel_stats(shapes, log_print, band, console_only=True)
    if len(main) < 12:
        main = kernel_stats(shapes, log_print, band, console_only=False)
    extra = ridge_stats(shapes, log_print)

    rows = []
    for hour in range(2, 25):
        got = nearest_stats(main, hour)
        if got is None:
            got = (0.0, FALLBACK_SPREAD * math.sqrt(hour - 1))
        middle, spread = got
        if hour in extra:
            ridge_middle, ridge_spread = extra[hour]
            middle = (1.0 - RIDGE_SHARE) * middle + RIDGE_SHARE * ridge_middle
            spread = math.sqrt(
                (1.0 - RIDGE_SHARE) * spread * spread
                + RIDGE_SHARE * ridge_spread * ridge_spread
            )
        quantiles = []
        for z in ZSCORE:
            value = first_print * math.exp(middle + z * spread)
            quantiles.append(value)
        quantiles.sort()
        quantiles = [max(q, 1.0) for q in quantiles]
        for i in range(1, len(quantiles)):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        rows.append(
            {"hour": hour, "q": [round(q, 2) for q in quantiles]}
        )
    return {"hours": rows}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(
        name for name in os.listdir(in_dir) if name.endswith(".in")
    )
    for name in names:
        with open(os.path.join(in_dir, name), "r", encoding="utf-8") as handle:
            case = json.load(handle)
        forecast = forecast_case(case)
        stem = name[: -len(".in")]
        with open(
            os.path.join(out_dir, stem + ".out"), "w", encoding="utf-8"
        ) as handle:
            json.dump(forecast, handle, separators=(",", ":"))
            handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
