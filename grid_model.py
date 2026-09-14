"""Building grid geometry.

Extracted from grid_gui so the takeoff workflow no longer depends on the
tkinter desktop application. Spans are bay dimensions in feet; lines are
their cumulative stations from the origin.
"""
from __future__ import annotations

MIN_SPACING_FT = 0.5


class GridModel:
    def __init__(self, x_spans=None, y_spans=None):
        self.x_spans = x_spans if x_spans is not None else []
        self.y_spans = y_spans if y_spans is not None else []

    @property
    def x_lines(self):
        pos = [0.0]
        running = 0.0
        for span in self.x_spans:
            running += span
            pos.append(running)
        return pos

    @property
    def y_lines(self):
        pos = [0.0]
        running = 0.0
        for span in self.y_spans:
            running += span
            pos.append(running)
        return pos

    def move_vertical_line(self, index: int, new_x: float):
        x_lines = self.x_lines
        if index <= 0 or index >= len(x_lines) - 1:
            return
        left = x_lines[index - 1]
        right = x_lines[index + 1]
        new_x = max(left + MIN_SPACING_FT, min(right - MIN_SPACING_FT, new_x))
        self.x_spans[index - 1] = round(new_x - left, 3)
        self.x_spans[index] = round(right - new_x, 3)

    def move_horizontal_line(self, index: int, new_y: float):
        y_lines = self.y_lines
        if index <= 0 or index >= len(y_lines) - 1:
            return
        top = y_lines[index - 1]
        bottom = y_lines[index + 1]
        new_y = max(top + MIN_SPACING_FT, min(bottom - MIN_SPACING_FT, new_y))
        self.y_spans[index - 1] = round(new_y - top, 3)
        self.y_spans[index] = round(bottom - new_y, 3)

    def as_dict(self):
        return {"x_spans_ft": self.x_spans, "y_spans_ft": self.y_spans}
