# MonoBerryTester desktop app

This package provides the initial tool to test Mono router dev kit boards

## Setup

This project uses [uv](https://docs.astral.sh/uv/) as the package manager.

Install dependencies:
```bash
uv sync
```

To install development dependencies:
```bash
uv sync --extra dev
```

## Running in production
- Run: `make run server_url=http://actualserver.com api_key=APIKEY uart_dev=/dev/ttyUSB0 ftx_prog_path=~/path/to/ftx_prog ccs_tools_path=/path/to/ccs/tools`

## Docs
All the files should have inline documentation.