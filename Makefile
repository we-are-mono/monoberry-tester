.PHONY: docs lint run

lint:
	python3 -m pylint --extension-pkg-whitelist=PyQt5 monoberrytester --exit-zero

run:
	python3 monoberrytester/main.py $(server_url) $(api_key) $(uart_dev)

deploy:
	rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
	  . mono@monoberry:~/Apps/monoberry-tester