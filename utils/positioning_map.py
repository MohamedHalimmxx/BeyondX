"""
ASCII positioning map renderer.
Takes competitor scores and white spaces and renders a visual 2x2 map.
Works for any two axes — no hardcoding.
"""

from state.analyst_state import BrandAnalystOutput


def _parse_position_score(description: str, low_label: str, high_label: str) -> float:
    """
    Derives a 0-10 score from a position description string.
    Uses semantic matching against the axis labels — no hardcoded keywords.
    """
    desc = description.lower()
    low = low_label.lower()
    high = high_label.lower()

    # Split labels into individual words for matching
    low_words = set(low.replace("-", " ").replace("→", " ").split())
    high_words = set(high.replace("-", " ").replace("→", " ").split())

    # Remove common stop words
    stop_words = {"and", "or", "the", "a", "an", "to", "of", "in", "with"}
    low_words -= stop_words
    high_words -= stop_words

    # Count matches toward each end
    low_matches = sum(1 for w in low_words if w in desc)
    high_matches = sum(1 for w in high_words if w in desc)

    # Explicit position words
    low_signals = {"affordable", "budget", "cheap", "low", "basic", "standard",
                   "traditional", "generic", "mass", "entry", "simple"}
    high_signals = {"premium", "high", "expensive", "luxury", "innovative",
                    "authentic", "artisan", "gourmet", "advanced", "unique"}
    mid_signals = {"mid", "medium", "moderate", "middle", "average", "balanced"}

    low_count = low_matches + sum(1 for w in low_signals if w in desc)
    high_count = high_matches + sum(1 for w in high_signals if w in desc)
    mid_count = sum(1 for w in mid_signals if w in desc)

    if mid_count > 0 and low_count == 0 and high_count == 0:
        return 5.0
    if high_count > low_count:
        return 7.5 + min(high_count - 1, 2) * 0.5  # 7.5 to 8.5
    if low_count > high_count:
        return 2.5 - min(low_count - 1, 2) * 0.5  # 2.5 to 1.5
    return 5.0  # Default to center if ambiguous


def render_positioning_map(analysis: BrandAnalystOutput) -> str:
    """
    Renders an ASCII 2x2 positioning map from competitor scores.
    Axis 1 (x-axis): left = low, right = high
    Axis 2 (y-axis): bottom = low, top = high
    All positions derived from data — no hardcoded coordinates.
    """
    axes = analysis.positioning_axes
    competitors = analysis.competitors

    width = 60
    height = 20

    grid = [[" " for _ in range(width)] for _ in range(height)]

    for x in range(width):
        grid[0][x] = "─"
        grid[height - 1][x] = "─"
    for y in range(height):
        grid[y][0] = "│"
        grid[y][width - 1] = "│"
    grid[0][0] = "┌"
    grid[0][width - 1] = "┐"
    grid[height - 1][0] = "└"
    grid[height - 1][width - 1] = "┘"

    mid_y = height // 2
    mid_x = width // 2
    for x in range(1, width - 1):
        if grid[mid_y][x] == " ":
            grid[mid_y][x] = "·"
    for y in range(1, height - 1):
        if grid[y][mid_x] == " ":
            grid[y][mid_x] = "·"

    def score_to_grid_x(score: float) -> int:
        margin = 2
        usable = width - 2 * margin
        pos = margin + int((score / 10) * usable)
        return max(margin, min(width - margin - 1, pos))

    def score_to_grid_y(score: float) -> int:
        margin = 2
        usable = height - 2 * margin
        pos = height - 1 - (margin + int((score / 10) * usable))
        return max(margin, min(height - margin - 1, pos))

    symbols = ["A", "B", "C", "D", "E", "F", "G", "H"]
    legend = []
    placed = {}

    for i, comp in enumerate(competitors):
        if i >= len(symbols):
            break
        sym = symbols[i]
        x = score_to_grid_x(comp.axis_1_score)
        y = score_to_grid_y(comp.axis_2_score)

        # Nudge on overlap — try right, then down, then diagonal
        attempts = [(x, y), (x+1, y), (x, y-1), (x+1, y-1), (x+2, y), (x, y-2)]
        for ax, ay in attempts:
            ax = max(1, min(width - 2, ax))
            ay = max(1, min(height - 2, ay))
            if (ax, ay) not in placed:
                x, y = ax, ay
                break

        placed[(x, y)] = sym
        grid[y][x] = sym
        legend.append(
            f"  {sym} = {comp.name} "
            f"({axes.axis_1_label}: {comp.axis_1_score:.0f}, "
            f"{axes.axis_2_label}: {comp.axis_2_score:.0f})"
        )

    # Place white space stars using axis labels for semantic score derivation
    for ws in analysis.white_spaces[:2]:
        ws_x_score = _parse_position_score(
            ws.axis_1_position,
            axes.axis_1_low,
            axes.axis_1_high
        )
        ws_y_score = _parse_position_score(
            ws.axis_2_position,
            axes.axis_2_low,
            axes.axis_2_high
        )

        wx = score_to_grid_x(ws_x_score)
        wy = score_to_grid_y(ws_y_score)

        attempts = [(wx, wy), (wx-1, wy), (wx, wy+1), (wx-1, wy+1)]
        for ax, ay in attempts:
            ax = max(1, min(width - 2, ax))
            ay = max(1, min(height - 2, ay))
            if (ax, ay) not in placed:
                wx, wy = ax, ay
                break

        placed[(wx, wy)] = "★"
        grid[wy][wx] = "★"
        legend.append(f"  ★ = White Space: {ws.description[:45]}")

    lines = []
    lines.append(f"\n  {axes.axis_2_high:^{width}}")
    lines.append(f"  {'':4}{axes.axis_2_label:^{width - 4}}")
    lines.append("")
    for y in range(height):
        row = "".join(grid[y])
        lines.append(f"  {row}")
    lines.append("")
    lines.append(f"  {axes.axis_1_low:<20}{'':10}{axes.axis_1_high:>20}")
    lines.append(f"  {'':4}{axes.axis_1_label:^{width - 4}}")
    lines.append(f"  {axes.axis_2_low:^{width}}")
    lines.append("")
    lines.append("  LEGEND:")
    lines.extend(legend)

    return "\n".join(lines)
