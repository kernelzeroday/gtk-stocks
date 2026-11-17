Name:           gtk-stocks
Version:        0.1.1
Release:        1%{?dist}
Summary:        Stock tracker for GNOME in the spirit of Apple Stocks
License:        MIT
URL:            https://github.com/kernelzeroday/gtk-stocks
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils
Requires:       python3
Requires:       python3-gobject >= 3.50
Requires:       python3-cairo
Requires:       gtk4 >= 4.10
Requires:       libadwaita >= 1.7
Requires:       pango

%description
A GTK4 / libadwaita stock tracker: watchlist with sparklines, interactive
charts from 1D to ALL, key stats and news. Market data from Yahoo Finance.

%prep
%autosetup

%build

%install
install -Dm0755 packaging/gtk-stocks %{buildroot}%{_bindir}/gtk-stocks
mkdir -p %{buildroot}%{_datadir}/%{name}/stocks
install -m0644 stocks/*.py stocks/style.css %{buildroot}%{_datadir}/%{name}/stocks/
install -Dm0644 data/icons/hicolor/scalable/apps/io.github.gtkstocks.Stocks.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.gtkstocks.Stocks.svg
install -Dm0644 io.github.gtkstocks.Stocks.desktop \
    %{buildroot}%{_datadir}/applications/io.github.gtkstocks.Stocks.desktop

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.gtkstocks.Stocks.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/gtk-stocks
%{_datadir}/%{name}/
%{_datadir}/applications/io.github.gtkstocks.Stocks.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.gtkstocks.Stocks.svg

%changelog
* Tue Nov 17 2026 kernelzeroday - 0.1.1-1
- New app icon

* Tue Nov 17 2026 kernelzeroday - 0.1.0-1
- Initial release
