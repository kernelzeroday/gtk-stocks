NAME    := gtk-stocks
VERSION := $(shell sed -n 's/^Version: *//p' packaging/$(NAME).spec)
TOPDIR  := $(CURDIR)/build/rpmbuild
SOURCES := stocks data packaging io.github.gtkstocks.Stocks.desktop README.md LICENSE run.sh

.PHONY: rpm srpm tarball clean

tarball:
	mkdir -p $(TOPDIR)/SOURCES
	tar --exclude=__pycache__ --transform 's,^,$(NAME)-$(VERSION)/,' \
	    -czf $(TOPDIR)/SOURCES/$(NAME)-$(VERSION).tar.gz $(SOURCES)

rpm: tarball
	rpmbuild --define "_topdir $(TOPDIR)" -ba packaging/$(NAME).spec
	mkdir -p dist
	cp $(TOPDIR)/RPMS/noarch/*.rpm $(TOPDIR)/SRPMS/*.rpm dist/
	@ls -1 dist/

clean:
	rm -rf build dist
