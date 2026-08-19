.PHONY: test run package clean

test:
	PYTHONPATH=. python3 -m unittest discover -s tests -v

run:
	PYTHONPATH=. DOTLET_DATABASE=./dotlet-dev.db DOTLET_APPLY_COMMAND=/bin/true python3 -m dotlet.app serve --listen 127.0.0.1:8080

package:
	./packaging/build-deb.sh

clean:
	rm -rf build dist dotlet-dev.db
