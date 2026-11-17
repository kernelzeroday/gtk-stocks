# Stocks

A GTK4 / libadwaita stock tracker in the spirit of Apple Stocks.

- Watchlist sidebar with sparklines and green/red change pills (click a pill to toggle % / $)
- Interactive chart: 1D–ALL ranges, previous-close baseline, hover to scrub (header price follows)
- Key stats (open, high/low, volume, prev close, 52-week range) and recent news with thumbnails
- Search any symbol: stocks, ETFs, indices, crypto, futures, currencies
- Auto-refresh every 60s; adaptive layout collapses to a single pane on narrow windows

Data comes from Yahoo Finance's public endpoints (no API key; quotes may be delayed).

## Install (Fedora)

Download the RPM from the [latest release](https://github.com/kernelzeroday/gtk-stocks/releases/latest), then:

    sudo dnf install ./gtk-stocks-*.noarch.rpm

Launch **Stocks** from your app grid, or run `gtk-stocks`.

## Run from source

    ./run.sh            # or: /usr/bin/python3 -m stocks

Requires the system PyGObject with GTK ≥ 4.10 and libadwaita ≥ 1.7
(Fedora: `python3-gobject python3-cairo gtk4 libadwaita`).

## Build the RPM

    make rpm            # outputs to dist/

## Shortcuts

| Key | Action |
| --- | --- |
| Ctrl+F | Search |
| Ctrl+R / F5 | Refresh |
| Delete | Remove selected symbol |
| Alt+↑ / Alt+↓ | Reorder selected symbol (drag and drop works too) |
| Right-click row | Remove from watchlist |
| Ctrl+Q | Quit |

The watchlist is saved to `~/.config/gtk-stocks/watchlist.json`.
