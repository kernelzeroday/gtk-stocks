"""Cairo-drawn price chart and sparkline widgets."""

import bisect
import math

import cairo
from gi.repository import Gtk, Pango, PangoCairo

from . import fmt


def nice_ticks(lo, hi, count=4):
    span = hi - lo
    if span <= 0:
        return [lo], 1.0
    raw = span / count
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if span / step <= count:
            break
    ticks = []
    v = math.ceil(lo / step) * step
    while v <= hi + step * 1e-6:
        ticks.append(v)
        v += step
    return ticks, step


def _value_bounds(series):
    vals = list(series.values)
    if series.baseline is not None:
        vals.append(series.baseline)
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or abs(hi) * 0.01 or 1.0
    return lo - pad, hi + pad


def _x_positions(series, left, width):
    n = len(series.values)
    if series.time_based and series.end > series.start:
        span = series.end - series.start
        return [left + (t - series.start) / span * width for t in series.times]
    return [left + i / max(1, n - 1) * width for i in range(n)]


def _dash_line(cr, x0, x1, y):
    cr.save()
    cr.set_dash([3, 4])
    cr.move_to(x0, y)
    cr.line_to(x1, y)
    cr.stroke()
    cr.restore()


class StockChart(Gtk.DrawingArea):
    """Interactive line chart. `on_hover(index | None)` is called as the pointer moves."""

    LEFT, RIGHT, TOP, BOTTOM = 4, 64, 34, 26

    def __init__(self):
        super().__init__()
        self.series = None
        self.hover_index = None
        self.on_hover = None
        self._xs = []
        self.set_content_height(320)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_cursor_from_name("crosshair")

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_series(self, series):
        self.series = series
        self.hover_index = None
        self.queue_draw()

    # -- interaction -----------------------------------------------------
    def _on_motion(self, _ctl, x, _y):
        if not self._xs:
            return
        i = bisect.bisect_left(self._xs, x)
        if i >= len(self._xs):
            i = len(self._xs) - 1
        elif i > 0 and (x - self._xs[i - 1]) < (self._xs[i] - x):
            i -= 1
        if i != self.hover_index:
            self.hover_index = i
            self.queue_draw()
            if self.on_hover:
                self.on_hover(i)

    def _on_leave(self, _ctl):
        if self.hover_index is not None:
            self.hover_index = None
            self.queue_draw()
            if self.on_hover:
                self.on_hover(None)

    # -- drawing ---------------------------------------------------------
    def _layout(self, cr, text, size=9, bold=False):
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
        layout.set_font_description(desc)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_font_features_new("tnum"))
        layout.set_attributes(attrs)
        layout.set_text(text, -1)
        return layout

    def _draw(self, _area, cr, w, h):
        s = self.series
        self._xs = []
        if not s or len(s.values) < 2:
            return
        fg = self.get_color()
        L, R, T, B = self.LEFT, self.RIGHT, self.TOP, self.BOTTOM
        pw, ph = w - L - R, h - T - B
        if pw < 20 or ph < 20:
            return

        lo, hi = _value_bounds(s)

        def y_of(v):
            return T + (hi - v) / (hi - lo) * ph

        xs = _x_positions(s, L, pw)
        self._xs = xs
        ys = [y_of(v) for v in s.values]

        # Horizontal grid + price labels.
        ticks, step = nice_ticks(lo, hi)
        decimals = max(0, min(4, math.ceil(-math.log10(step)))) if step < 1 else 0
        cr.set_line_width(1)
        for v in ticks:
            y = round(y_of(v)) + 0.5
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.10)
            cr.move_to(L, y)
            cr.line_to(L + pw, y)
            cr.stroke()
            layout = self._layout(cr, fmt.price(v, decimals))
            _, lh = layout.get_pixel_size()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
            cr.move_to(L + pw + 8, y - lh / 2)
            PangoCairo.show_layout(cr, layout)

        # Time labels + vertical grid.
        for x, label in self._time_ticks(s, xs, L, pw):
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
            cr.move_to(round(x) + 0.5, T)
            cr.line_to(round(x) + 0.5, T + ph)
            cr.stroke()
            layout = self._layout(cr, label)
            lw, _ = layout.get_pixel_size()
            lx = min(max(x - lw / 2, L), L + pw - lw)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
            cr.move_to(lx, T + ph + 6)
            PangoCairo.show_layout(cr, layout)

        color = fmt.color_for(s.change)

        # Previous-close baseline.
        if s.baseline is not None:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.4)
            _dash_line(cr, L, L + pw, round(y_of(s.baseline)) + 0.5)

        # Gradient fill under the line.
        cr.move_to(xs[0], T + ph)
        for x, y in zip(xs, ys):
            cr.line_to(x, y)
        cr.line_to(xs[-1], T + ph)
        cr.close_path()
        grad = cairo.LinearGradient(0, T, 0, T + ph)
        grad.add_color_stop_rgba(0, *color, 0.28)
        grad.add_color_stop_rgba(1, *color, 0.0)
        cr.set_source(grad)
        cr.fill()

        # Price line.
        cr.set_line_width(2)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgb(*color)
        cr.move_to(xs[0], ys[0])
        for x, y in zip(xs[1:], ys[1:]):
            cr.line_to(x, y)
        cr.stroke()

        if self.hover_index is not None and self.hover_index < len(xs):
            self._draw_hover(cr, s, xs, ys, fg, color, L, T, pw, ph)

    def _time_ticks(self, s, xs, L, pw):
        if s.time_based:
            # One tick per hour (or every few hours for 24h markets).
            span_h = (s.end - s.start) / 3600
            every = 1 if span_h <= 9 else 3 if span_h <= 24 else 6
            first = (s.start // 3600 + 1) * 3600
            out = []
            t = first
            while t < s.end:
                dt = fmt.exchange_time(t, s.gmtoffset)
                if dt.hour % every == 0:
                    x = L + (t - s.start) / (s.end - s.start) * pw
                    out.append((x, fmt.hour_label(dt)))
                t += 3600
            return out
        n = len(xs)
        count = 5 if pw > 420 else 3
        out, seen = [], set()
        for k in range(count):
            i = round((k + 0.5) / count * (n - 1))
            label = fmt.axis_label(s.times[i], s.gmtoffset, s.range_key)
            if label not in seen:
                seen.add(label)
                out.append((xs[i], label))
        return out

    def _draw_hover(self, cr, s, xs, ys, fg, color, L, T, pw, ph):
        i = self.hover_index
        x, y = xs[i], ys[i]
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
        cr.set_line_width(1)
        cr.move_to(round(x) + 0.5, T - 4)
        cr.line_to(round(x) + 0.5, T + ph)
        cr.stroke()

        cr.arc(x, y, 5.5, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.set_source_rgb(*color)
        cr.set_line_width(2.5)
        cr.stroke()

        label = fmt.hover_label(s.times[i], s.gmtoffset, s.range_key)
        layout = self._layout(cr, label, size=9, bold=True)
        lw, lh = layout.get_pixel_size()
        lx = min(max(x - lw / 2, L), L + pw - lw)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.75)
        cr.move_to(lx, (T - lh) / 2 - 2)
        PangoCairo.show_layout(cr, layout)


class Sparkline(Gtk.DrawingArea):
    def __init__(self, width=64, height=30):
        super().__init__()
        self.series = None
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def set_series(self, series):
        self.series = series
        self.queue_draw()

    def _draw(self, _area, cr, w, h):
        s = self.series
        if not s or len(s.values) < 2:
            return
        lo, hi = _value_bounds(s)
        pad = 2
        ph = h - 2 * pad

        def y_of(v):
            return pad + (hi - v) / (hi - lo) * ph

        xs = _x_positions(s, 1, w - 2)
        color = fmt.color_for(s.change)

        if s.baseline is not None:
            fg = self.get_color()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
            cr.set_line_width(1)
            cr.save()
            cr.set_dash([1.5, 2.5])
            yb = round(y_of(s.baseline)) + 0.5
            cr.move_to(0, yb)
            cr.line_to(w, yb)
            cr.stroke()
            cr.restore()

        cr.set_source_rgb(*color)
        cr.set_line_width(1.5)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(xs[0], y_of(s.values[0]))
        for x, v in zip(xs[1:], s.values[1:]):
            cr.line_to(x, y_of(v))
        cr.stroke()
