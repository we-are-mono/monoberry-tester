.PHONY: docs lint run

lint:
	uv tool run pylint --extension-pkg-whitelist=openhtf main --exit-zero

run:
	uv run main.py

deploy:
	rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
	  . mono@monoberry:~/Apps/monoberry-tester
