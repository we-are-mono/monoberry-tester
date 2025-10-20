.PHONY: docs lint run

lint:
	python3 -m pylint --extension-pkg-whitelist=PyQt5 monoberrytester --exit-zero

docs:
	@echo "Generating API documentation with pdoc..."
	pydoc-markdown -p . > docs.md

run:
	python3 -m monoberrytester.main