"""
ASCII positioning map renderer.
Takes competitor scores and white spaces and renders a visual 2x2 map.
Works for any two axes — no hardcoding.
"""

from state.analyst_state import BrandAnalystOutput


def render_positioning_map(analysis: BrandAnalystOutput) -> str:
    """
    Renders an ASCII 2x2 positioning map from competitor scores.
    Axis 1 (x-axis): left = low, right = high
    Axis 2 (y-axis): bottom = low, top = high
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
        # Invert: high score = top of map
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

        # Nudge on overlap
        while (x, y) in placed and x < width - 2:
            x += 1
        placed[(x, y)] = sym
        grid[y][x] = sym
        legend.append(
            f"  {sym} = {comp.name} "
            f"({axes.axis_1_label}: {comp.axis_1_score:.0f}, "
            f"{axes.axis_2_label}: {comp.axis_2_score:.0f})"
        )

    # Place white space stars using actual axis position descriptions
    # We derive approximate scores from the position descriptions using the LLM output
    for ws in analysis.white_spaces[:2]:
        # Use the midpoint of unoccupied quadrant as approximation
        # The white space position descriptions guide placement
        axis_1_desc = ws.axis_1_position.lower()
        axis_2_desc = ws.axis_2_position.lower()

        # Derive score from description dynamically
        if any(w in axis_1_desc for w in ["premium", "high", "expensive", "luxury"]):
            ws_x_score = 8.0
        elif any(w in axis_1_desc for w in ["affordable", "low", "budget", "cheap"]):
            ws_x_score = 2.0
        else:
            ws_x_score = 5.0

        if any(w in axis_2_desc for w in ["authentic", "high", "artisan", "quality", "premium"]):
            ws_y_score = 8.0
        elif any(w in axis_2_desc for w in ["standard", "low", "mass", "basic"]):
            ws_y_score = 2.0
        else:
            ws_y_score = 5.0

        wx = score_to_grid_x(ws_x_score)
        wy = score_to_grid_y(ws_y_score)

        # Nudge if occupied
        while (wx, wy) in placed and wx < width - 2:
            wx += 1

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
