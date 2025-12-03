.PHONY: docs lint run sync

sync:
	uv sync

lint:
	uv run pylint --extension-pkg-whitelist=PyQt5 monoberrytester --exit-zero

run:
	sudo uv run python monoberrytester/main.py $(server_url) $(api_key) $(uart_dev) $(ftx_prog_path) $(ccs_tools_path)
