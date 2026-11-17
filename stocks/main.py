import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import __version__  # noqa: E402
from .window import StocksWindow  # noqa: E402

APP_ID = "io.github.gtkstocks.Stocks"


class StocksApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(__file__), "style.css"))
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # When running from a source checkout, find the icon in ./data/icons.
        icons = os.path.join(os.path.dirname(__file__), os.pardir, "data", "icons")
        if os.path.isdir(icons):
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.abspath(icons))
        Gtk.Window.set_default_icon_name(APP_ID)
        for name, cb, accels in (
            ("quit", lambda *_: self.quit(), ["<Control>q"]),
            ("about", self._on_about, []),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def do_activate(self):
        win = self.get_active_window() or StocksWindow(application=self)
        win.present()

    def _on_about(self, *_):
        Adw.AboutDialog(
            application_name="Stocks",
            application_icon=APP_ID,
            version=__version__,
            comments="Track your watchlist with live quotes, charts and news.\n"
            "Market data from Yahoo Finance; may be delayed.",
            license_type=Gtk.License.MIT_X11,
        ).present(self.get_active_window())


def main():
    return StocksApp().run(sys.argv)
