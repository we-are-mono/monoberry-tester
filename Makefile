lint:
	python3 -m pylint --extension-pkg-whitelist=PyQt5 monoberrytester.py

docs:
	lazydocs monoberrytester.py
