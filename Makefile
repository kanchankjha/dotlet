.PHONY: test run package clean version release-patch release-minor release-major

test:
	PYTHONPATH=. python3 -m unittest discover -s tests -v

run:
	PYTHONPATH=. DOTLET_DATABASE=./dotlet-dev.db DOTLET_APPLY_COMMAND=/bin/true python3 -m dotlet.app serve --listen 127.0.0.1:8080

package:
	./packaging/build-deb.sh

clean:
	rm -rf build dist dotlet-dev.db

# Display current version
version:
	@sed -n 's/^__version__ = "\([^"]*\)"/\1/p' dotlet/__init__.py

# Release targets - bump version, commit, and create tag
release-patch:
	./scripts/bump-version.sh --tag patch

release-minor:
	./scripts/bump-version.sh --tag minor

release-major:
	./scripts/bump-version.sh --tag major
