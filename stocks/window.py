"""Main window: watchlist sidebar + stock detail view."""

import json
import os
import time
from datetime import datetime

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import api, fmt
from .chart import Sparkline, StockChart

DEFAULT_WATCHLIST = ["^GSPC", "^DJI", "^IXIC", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA"]
REFRESH_SECONDS = 60


def _set_trend_class(widget, change):
    for cls in ("up", "down"):
        widget.remove_css_class(cls)
    widget.add_css_class("down" if change < 0 else "up")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
class Watchlist:
    def __init__(self):
        self.path = os.path.join(GLib.get_user_config_dir(), "gtk-stocks", "watchlist.json")
        self.symbols = list(DEFAULT_WATCHLIST)
        try:
            with open(self.path) as f:
                data = json.load(f)
            if isinstance(data, list):
                self.symbols = [str(s) for s in data]
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.symbols, f, indent=2)
        os.replace(tmp, self.path)

    def __contains__(self, symbol):
        return symbol in self.symbols


# ---------------------------------------------------------------------------
# Sidebar row
# ---------------------------------------------------------------------------
class WatchRow(Gtk.ListBoxRow):
    def __init__(self, symbol, window):
        super().__init__()
        self.symbol = symbol
        self.window = window

        box = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=6, margin_end=6)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.symbol_label = Gtk.Label(label=symbol, xalign=0, css_classes=["heading"])
        self.name_label = Gtk.Label(
            xalign=0, ellipsize=3, max_width_chars=16, css_classes=["caption", "dim-label"]
        )
        left.append(self.symbol_label)
        left.append(self.name_label)

        self.spark = Sparkline()

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.CENTER)
        self.price_label = Gtk.Label(label="—", xalign=1, css_classes=["numeric", "row-price"])
        self.pill = Gtk.Button(label="—", css_classes=["pill-badge", "numeric"], halign=Gtk.Align.END)
        self.pill.set_tooltip_text("Toggle change / percent")
        self.pill.connect("clicked", lambda *_: window.cycle_pill_mode())
        right.append(self.price_label)
        right.append(self.pill)

        box.append(left)
        box.append(self.spark)
        box.append(right)
        self.set_child(box)

        # Right-click menu.
        menu = Gio.Menu()
        menu.append("Remove from Watchlist", f"win.remove-symbol::{symbol}")
        self.popover = Gtk.PopoverMenu.new_from_model(menu)
        self.popover.set_parent(self)
        self.popover.set_has_arrow(False)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_context)
        self.add_controller(click)

        # Drag to reorder.
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(self.symbol))
        drag.connect("drag-begin", self._on_drag_begin)
        self.add_controller(drag)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", lambda _t, value, *_: window.move_symbol(value, self.symbol))
        self.add_controller(drop)

    def _on_context(self, _gesture, _n, x, y):
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.popover.set_pointing_to(rect)
        self.popover.popup()

    def _on_drag_begin(self, source, _drag):
        source.set_icon(Gtk.WidgetPaintable.new(self), 20, 20)

    def update(self, quote, series, mode):
        self.name_label.set_label(quote.name)
        self.price_label.set_label(fmt.price(quote.price, quote.decimals))
        text = fmt.percent(quote.change_pct) if mode == 0 else fmt.change(quote.change, quote.decimals)
        self.pill.set_label(text)
        _set_trend_class(self.pill, quote.change)
        self.spark.set_series(series)

    def do_unroot(self):
        self.popover.unparent()
        Gtk.ListBoxRow.do_unroot(self)


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------
class DetailView(Adw.Bin):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.symbol = None
        self.quote = None
        self.series = None
        self.range_key = "1D"
        self._request = 0

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle()
        header.set_title_widget(self.title)
        self.watch_button = Gtk.Button()
        self.watch_button.connect("clicked", self._on_watch_clicked)
        header.pack_end(self.watch_button)
        toolbar.add_top_bar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(
            Adw.StatusPage(
                icon_name="io.github.gtkstocks.Stocks",
                title="No Stock Selected",
                description="Choose a symbol from your watchlist or search for one.",
            ),
            "empty",
        )
        self.stack.add_named(self._build_content(), "detail")
        toolbar.set_content(self.stack)
        self.set_child(toolbar)
        self._update_watch_button()

    def _build_content(self):
        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=18,
            margin_bottom=24,
            margin_start=18,
            margin_end=18,
        )

        # Price header.
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.name_label = Gtk.Label(xalign=0, wrap=True, css_classes=["title-3"])
        self.exchange_label = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"])
        price_row = Gtk.Box(spacing=12, margin_top=6)
        self.price_label = Gtk.Label(xalign=0, css_classes=["big-price", "numeric"])
        self.change_label = Gtk.Label(
            xalign=0, valign=Gtk.Align.BASELINE_CENTER, css_classes=["change", "numeric"]
        )
        self.price_label.set_valign(Gtk.Align.BASELINE_CENTER)
        price_row.append(self.price_label)
        price_row.append(self.change_label)
        self.status_label = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"])
        head.append(self.name_label)
        head.append(self.exchange_label)
        head.append(price_row)
        head.append(self.status_label)
        page.append(head)

        # Range selector.
        self.ranges = Adw.ToggleGroup(halign=Gtk.Align.FILL, hexpand=True, homogeneous=True)
        self.ranges.add_css_class("flat")
        for key in api.RANGES:
            self.ranges.add(Adw.Toggle(label=key, name=key))
        self.ranges.set_active_name(self.range_key)
        self.ranges.connect("notify::active-name", self._on_range_changed)
        page.append(self.ranges)

        # Chart (with loading / error states).
        self.chart = StockChart()
        self.chart.on_hover = self._on_chart_hover
        self.chart_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.chart_stack.add_named(self.chart, "chart")
        self.chart_stack.add_named(
            Adw.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width_request=32, height_request=32),
            "loading",
        )
        self.chart_error = Gtk.Label(css_classes=["dim-label"], wrap=True)
        self.chart_stack.add_named(self.chart_error, "error")
        self.chart_stack.set_size_request(-1, 320)
        page.append(self.chart_stack)

        # Stats.
        self.stats = {}
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            min_children_per_line=2,
            max_children_per_line=4,
            column_spacing=12,
            row_spacing=12,
            css_classes=["card", "stats-card"],
        )
        for key in ("Open", "High", "Low", "Volume", "Prev Close", "52W High", "52W Low", "Currency"):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cell.append(Gtk.Label(label=key, xalign=0, css_classes=["caption", "dim-label"]))
            value = Gtk.Label(label="—", xalign=0, css_classes=["numeric", "stat-value"])
            cell.append(value)
            flow.append(cell)
            self.stats[key] = value
        page.append(flow)

        # News.
        news_title = Gtk.Label(label="News", xalign=0, css_classes=["title-4"], margin_top=6)
        page.append(news_title)
        self.news_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.news_list.connect("row-activated", self._on_news_activated)
        page.append(self.news_list)

        clamp = Adw.Clamp(maximum_size=960, child=page)
        return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER)

    # -- public ----------------------------------------------------------
    def show_symbol(self, symbol):
        changed = symbol != self.symbol
        self.symbol = symbol
        self.stack.set_visible_child_name("detail")
        self._update_watch_button()
        if changed:
            self.quote = None
            self.series = None
            self.title.set_title(symbol)
            self.title.set_subtitle("")
            self.name_label.set_label("")
            self.exchange_label.set_label("")
            self.price_label.set_label("—")
            self.change_label.set_label("")
            self.status_label.set_label("")
            for v in self.stats.values():
                v.set_label("—")
            cached = self.window.quotes.get(symbol)
            if cached:
                self._apply_quote(cached[0])
                if self.range_key == "1D":
                    self._apply_series(cached[1])
            self._load_news()
        self.reload()

    def clear(self):
        self.symbol = None
        self.stack.set_visible_child_name("empty")
        self.title.set_title("")
        self.title.set_subtitle("")
        self._update_watch_button()

    def reload(self, quiet=False):
        if not self.symbol:
            return
        self._request += 1
        req, symbol, range_key = self._request, self.symbol, self.range_key
        if not quiet and (self.series is None or self.series.range_key != range_key):
            self.chart_stack.set_visible_child_name("loading")

        def show_error(error):
            if not quiet:
                self.chart_error.set_label(f"Couldn’t load chart\n{error}")
                self.chart_stack.set_visible_child_name("error")

        def on_quote(result, error):
            if req != self._request:
                return
            if error:
                if range_key == "1D":
                    show_error(error)
                return
            quote, series = result
            self.window.store_quote(symbol, quote, series)
            self._apply_quote(quote)
            if range_key == "1D":
                self._apply_series(series)

        def on_series(result, error):
            if req != self._request:
                return
            if error:
                show_error(error)
            else:
                self._apply_series(result[1])

        api.run_async(on_quote, api.fetch_chart, symbol, "1D")
        if range_key != "1D":
            api.run_async(on_series, api.fetch_chart, symbol, range_key)

    # -- internals -------------------------------------------------------
    def _apply_quote(self, q):
        self.quote = q
        self.title.set_title(q.symbol)
        self.title.set_subtitle(q.name)
        self.name_label.set_label(q.name)
        self.exchange_label.set_label(" · ".join(x for x in (q.exchange, q.currency) if x))
        self._show_price(q.price, q.change, q.change_pct, q.decimals)

        now = time.time()
        if q.regular_start <= now < q.regular_end:
            status = "Market Open"
        else:
            dt = fmt.exchange_time(q.market_time, q.gmtoffset)
            status = f"At Close · {dt:%b} {dt.day}, {fmt.full_time(dt)} {q.timezone}"
        self.status_label.set_label(status)

        d = q.decimals
        self.stats["Open"].set_label(fmt.price(q.open, d))
        self.stats["High"].set_label(fmt.price(q.high, d))
        self.stats["Low"].set_label(fmt.price(q.low, d))
        self.stats["Volume"].set_label(fmt.compact(q.volume))
        self.stats["Prev Close"].set_label(fmt.price(q.prev_close, d))
        self.stats["52W High"].set_label(fmt.price(q.high52, d))
        self.stats["52W Low"].set_label(fmt.price(q.low52, d))
        self.stats["Currency"].set_label(q.currency or "—")

    def _apply_series(self, series):
        self.series = series
        if len(series.values) < 2:
            self.chart_error.set_label("Not enough data for this range")
            self.chart_stack.set_visible_child_name("error")
            return
        self.chart.set_series(series)
        self.chart_stack.set_visible_child_name("chart")

    def _show_price(self, price, change, pct, decimals):
        self.price_label.set_label(fmt.price(price, decimals))
        self.change_label.set_label(f"{fmt.change(change, decimals)} ({fmt.percent(pct)})")
        _set_trend_class(self.change_label, change)

    def _on_chart_hover(self, index):
        s = self.series
        if index is None or not s:
            if self.quote:
                q = self.quote
                self._show_price(q.price, q.change, q.change_pct, q.decimals)
            return
        value = s.values[index]
        ref = s.reference
        change = value - ref
        self._show_price(value, change, change / ref * 100 if ref else 0, s.decimals)

    def _on_range_changed(self, group, _pspec):
        key = group.get_active_name()
        if key and key != self.range_key:
            self.range_key = key
            if key == "1D" and self.symbol in self.window.quotes:
                self._apply_series(self.window.quotes[self.symbol][1])
            self.reload()

    def _update_watch_button(self):
        watched = self.symbol is not None and self.symbol in self.window.watchlist
        self.watch_button.set_visible(self.symbol is not None)
        if watched:
            self.watch_button.set_icon_name("user-trash-symbolic")
            self.watch_button.set_tooltip_text("Remove from Watchlist")
        else:
            self.watch_button.set_icon_name("list-add-symbolic")
            self.watch_button.set_tooltip_text("Add to Watchlist")

    def _on_watch_clicked(self, _button):
        if self.symbol in self.window.watchlist:
            self.window.remove_symbol(self.symbol)
        else:
            self.window.add_symbol(self.symbol)
        self._update_watch_button()

    # -- news ------------------------------------------------------------
    def _load_news(self):
        self.news_list.remove_all()
        symbol = self.symbol
        placeholder = Adw.ActionRow(title="Loading news…", css_classes=["dim-label"])
        self.news_list.append(placeholder)

        def done(items, error):
            if symbol != self.symbol:
                return
            self.news_list.remove_all()
            if error or not items:
                self.news_list.append(Adw.ActionRow(title="No recent news", css_classes=["dim-label"]))
                return
            for item in items:
                self.news_list.append(self._news_row(item))

        api.run_async(done, api.fetch_news, symbol)

    def _news_row(self, item):
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(item["title"]),
            subtitle=GLib.markup_escape_text(f"{item['publisher']} · {fmt.relative(item['time'])}"),
            activatable=True,
            title_lines=3,
        )
        row.link = item["link"]
        row.add_suffix(Gtk.Image(icon_name="adw-external-link-symbolic"))
        if item["thumb"]:
            pic = Gtk.Picture(
                content_fit=Gtk.ContentFit.COVER,
                width_request=64,
                height_request=64,
                valign=Gtk.Align.CENTER,
                margin_top=6,
                margin_bottom=6,
                css_classes=["news-thumb"],
                overflow=Gtk.Overflow.HIDDEN,
            )
            row.add_prefix(pic)

            def loaded(data, error):
                if error or not data:
                    pic.set_visible(False)
                    return
                try:
                    pic.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
                except GLib.Error:
                    pic.set_visible(False)

            api.run_async(loaded, api.fetch_bytes, item["thumb"])
        return row

    def _on_news_activated(self, _list, row):
        link = getattr(row, "link", None)
        if link:
            Gtk.UriLauncher(uri=link).launch(self.get_root(), None, None, None)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
class StocksWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(1120, 760)
        self.set_title("Stocks")

        self.watchlist = Watchlist()
        self.quotes = {}  # symbol -> (Quote, 1D Series)
        self.rows = {}
        self.pill_mode = 0
        self._search_timeout = 0
        self._search_seq = 0

        self._install_actions()

        self.detail = DetailView(self)
        self.split = Adw.NavigationSplitView(
            min_sidebar_width=300, max_sidebar_width=380, sidebar_width_fraction=0.32
        )
        self.split.set_sidebar(Adw.NavigationPage(title="Stocks", child=self._build_sidebar()))
        self.split.set_content(Adw.NavigationPage(title="Stock", child=self.detail))

        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        for symbol in self.watchlist.symbols:
            self._append_row(symbol)
        self._sync_sidebar_state()
        self.refresh_all()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._on_tick)

        first = self.watchlist_box.get_row_at_index(0)
        if first:
            self.watchlist_box.select_row(first)

    # -- UI construction -------------------------------------------------
    def _build_sidebar(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        today = datetime.now()
        header.set_title_widget(Adw.WindowTitle(title="Stocks", subtitle=f"{today:%B} {today.day}"))

        menu = Gio.Menu()
        menu.append("Refresh", "win.refresh")
        menu.append("About Stocks", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True))
        toolbar.add_top_bar(header)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search symbols or companies")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", lambda e: e.set_text(""))
        self.search_entry.connect("activate", self._on_search_activate)
        search_box = Gtk.Box(margin_start=12, margin_end=12, margin_bottom=6)
        search_box.append(self.search_entry)
        self.search_entry.set_hexpand(True)
        toolbar.add_top_bar(search_box)

        self.watchlist_box = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.watchlist_box.connect("row-selected", self._on_row_selected)
        self.watchlist_box.connect("row-activated", lambda *_: self.split.set_show_content(True))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_list_key)
        self.watchlist_box.add_controller(keys)

        self.results_box = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.results_box.connect("row-activated", self._on_result_activated)

        self.side_stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.side_stack.add_named(Gtk.ScrolledWindow(child=self.watchlist_box), "watchlist")
        self.side_stack.add_named(Gtk.ScrolledWindow(child=self.results_box), "results")
        self.side_stack.add_named(
            Adw.StatusPage(
                icon_name="system-search-symbolic",
                title="Empty Watchlist",
                description="Search above to add stocks.",
                css_classes=["compact"],
            ),
            "empty",
        )
        self.search_status = Adw.StatusPage(icon_name="system-search-symbolic", css_classes=["compact"])
        self.side_stack.add_named(self.search_status, "search-status")
        toolbar.set_content(self.side_stack)
        return toolbar

    def _install_actions(self):
        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *_: self.refresh_all(user=True))
        self.add_action(refresh)

        search = Gio.SimpleAction.new("search", None)
        search.connect("activate", lambda *_: self._focus_search())
        self.add_action(search)

        remove = Gio.SimpleAction.new("remove-symbol", GLib.VariantType.new("s"))
        remove.connect("activate", lambda _a, v: self.remove_symbol(v.get_string()))
        self.add_action(remove)

        app = self.get_application()
        if app:
            app.set_accels_for_action("win.refresh", ["<Control>r", "F5"])
            app.set_accels_for_action("win.search", ["<Control>f"])

    def _focus_search(self):
        self.split.set_show_content(False)
        self.search_entry.grab_focus()

    # -- watchlist management -------------------------------------------
    def _append_row(self, symbol):
        row = WatchRow(symbol, self)
        self.rows[symbol] = row
        self.watchlist_box.append(row)
        if symbol in self.quotes:
            row.update(*self.quotes[symbol], self.pill_mode)
        return row

    def _sync_sidebar_state(self):
        if self.search_entry.get_text().strip():
            return
        self.side_stack.set_visible_child_name("watchlist" if self.watchlist.symbols else "empty")

    def add_symbol(self, symbol):
        if symbol in self.watchlist:
            return
        self.watchlist.symbols.append(symbol)
        self.watchlist.save()
        row = self._append_row(symbol)
        self._refresh_symbol(symbol)
        self._sync_sidebar_state()
        self._refresh_results_icons()
        if self.detail.symbol == symbol:
            self.watchlist_box.select_row(row)
        self.toasts.add_toast(Adw.Toast(title=f"Added {symbol} to Watchlist", timeout=2))

    def remove_symbol(self, symbol):
        if symbol not in self.watchlist:
            return
        index = self.watchlist.symbols.index(symbol)
        self.watchlist.symbols.remove(symbol)
        self.watchlist.save()
        row = self.rows.pop(symbol, None)
        was_selected = row is not None and row.is_selected()
        if row:
            self.watchlist_box.remove(row)
        self._sync_sidebar_state()
        self._refresh_results_icons()
        self.detail._update_watch_button()

        if was_selected:
            nxt = self.watchlist_box.get_row_at_index(min(index, len(self.watchlist.symbols) - 1))
            if nxt:
                self.watchlist_box.select_row(nxt)

        toast = Adw.Toast(title=f"Removed {symbol}", button_label="Undo", timeout=4)
        toast.connect("button-clicked", lambda *_: self._undo_remove(symbol, index))
        self.toasts.add_toast(toast)

    def _undo_remove(self, symbol, index):
        if symbol in self.watchlist:
            return
        self.add_symbol(symbol)
        self.move_symbol(symbol, self.watchlist.symbols[min(index, len(self.watchlist.symbols) - 1)])

    def move_symbol(self, src, dst):
        syms = self.watchlist.symbols
        if src == dst or src not in syms or dst not in syms:
            return False
        target = syms.index(dst)
        syms.remove(src)
        syms.insert(target, src)
        self.watchlist.save()
        selected = self.watchlist_box.get_selected_row()
        for row in self.rows.values():
            self.watchlist_box.remove(row)
        for s in syms:
            self.watchlist_box.append(self.rows[s])
        if selected:
            self.watchlist_box.select_row(selected)
        return True

    def cycle_pill_mode(self):
        self.pill_mode = (self.pill_mode + 1) % 2
        for symbol, row in self.rows.items():
            if symbol in self.quotes:
                row.update(*self.quotes[symbol], self.pill_mode)

    # -- data ------------------------------------------------------------
    def store_quote(self, symbol, quote, series):
        self.quotes[symbol] = (quote, series)
        row = self.rows.get(symbol)
        if row:
            row.update(quote, series, self.pill_mode)

    def _refresh_symbol(self, symbol, report=None):
        def done(result, error):
            if error:
                if report is not None:
                    report.append(symbol)
                return
            self.store_quote(symbol, *result)

        api.run_async(done, api.fetch_chart, symbol, "1D")

    def refresh_all(self, user=False):
        symbols = [s for s in self.watchlist.symbols if s != self.detail.symbol]
        failures = []
        pending = {"n": len(symbols)}

        def done(symbol):
            def cb(result, error):
                if error:
                    failures.append(symbol)
                else:
                    self.store_quote(symbol, *result)
                pending["n"] -= 1
                if pending["n"] == 0 and failures and user:
                    self.toasts.add_toast(
                        Adw.Toast(title=f"Couldn’t update {', '.join(failures[:3])}", timeout=3)
                    )

            return cb

        for symbol in symbols:
            api.run_async(done(symbol), api.fetch_chart, symbol, "1D")
        self.detail.reload(quiet=not user)

    def _on_tick(self):
        self.refresh_all()
        return GLib.SOURCE_CONTINUE

    # -- sidebar events ---------------------------------------------------
    def _on_row_selected(self, _box, row):
        if row is None:
            return
        self.results_box.unselect_all()
        self.detail.show_symbol(row.symbol)
        self.split.get_content().set_title(row.symbol)

    def _on_list_key(self, _ctl, keyval, _code, state):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            row = self.watchlist_box.get_selected_row()
            if row:
                self.remove_symbol(row.symbol)
                return True
        if state & Gdk.ModifierType.ALT_MASK and keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            row = self.watchlist_box.get_selected_row()
            if row:
                syms = self.watchlist.symbols
                i = syms.index(row.symbol) + (-1 if keyval == Gdk.KEY_Up else 1)
                if 0 <= i < len(syms):
                    self.move_symbol(row.symbol, syms[i])
                return True
        return False

    def _on_search_changed(self, entry):
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
            self._search_timeout = 0
        text = entry.get_text().strip()
        if not text:
            self._search_seq += 1
            self._sync_sidebar_state()
            return
        self._search_timeout = GLib.timeout_add(250, self._run_search, text)

    def _run_search(self, text):
        self._search_timeout = 0
        self._search_seq += 1
        seq = self._search_seq
        if self.side_stack.get_visible_child_name() != "results":
            self.search_status.set_title("Searching…")
            self.search_status.set_description(None)
            self.side_stack.set_visible_child_name("search-status")

        def done(results, error):
            if seq != self._search_seq:
                return
            self.results_box.remove_all()
            if error or not results:
                self.search_status.set_title("No Results" if not error else "Search Failed")
                self.search_status.set_description(str(error) if error else f"Nothing matches “{text}”")
                self.side_stack.set_visible_child_name("search-status")
                return
            for item in results:
                self.results_box.append(self._result_row(item))
            self.side_stack.set_visible_child_name("results")

        api.run_async(done, api.search, text)
        return GLib.SOURCE_REMOVE

    def _result_row(self, item):
        sub = " · ".join(x for x in (item["exchange"], item["type"]) if x)
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(item["symbol"]),
            subtitle=GLib.markup_escape_text(f"{item['name']}\n{sub}" if sub else item["name"]),
            activatable=True,
            subtitle_lines=2,
        )
        row.symbol = item["symbol"]
        button = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["flat", "circular"])
        button.connect("clicked", lambda *_: self.add_symbol(row.symbol))
        row.add_suffix(button)
        row.add_button = button
        self._update_result_button(row)
        return row

    def _update_result_button(self, row):
        watched = row.symbol in self.watchlist
        row.add_button.set_icon_name("object-select-symbolic" if watched else "list-add-symbolic")
        row.add_button.set_sensitive(not watched)
        row.add_button.set_tooltip_text("In Watchlist" if watched else "Add to Watchlist")

    def _refresh_results_icons(self):
        child = self.results_box.get_first_child()
        while child:
            if hasattr(child, "add_button"):
                self._update_result_button(child)
            child = child.get_next_sibling()

    def _on_result_activated(self, _box, row):
        symbol = row.symbol
        if symbol in self.rows:
            self.watchlist_box.select_row(self.rows[symbol])
        else:
            self.watchlist_box.unselect_all()
            self.detail.show_symbol(symbol)
            self.split.get_content().set_title(symbol)
        self.split.set_show_content(True)

    def _on_search_activate(self, _entry):
        row = self.results_box.get_row_at_index(0)
        if row and self.side_stack.get_visible_child_name() == "results":
            self._on_result_activated(self.results_box, row)
