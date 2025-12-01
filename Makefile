.PHONY: docs lint run

lint:
	python3 -m pylint --extension-pkg-whitelist=PyQt5 monoberrytester --exit-zero

run:
	sudo python3 monoberrytester/main.py $(server_url) $(api_key) $(uart_dev) $(ftx_prog_path) $(ccs_tools_path)
