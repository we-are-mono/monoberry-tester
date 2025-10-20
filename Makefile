.PHONY: docs lint run

lint:
	python3 -m pylint --extension-pkg-whitelist=PyQt5 monoberrytester --exit-zero

run:
	python3 monoberrytester/main.py