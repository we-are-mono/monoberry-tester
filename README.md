#MonoBerryTester desktop app

This package provides the initial tool to test Mono router dev kit boards

## Running for development
- Make fake UART devices:
    `socat -d -d pty,raw,echo=0,link=/tmp/ttyMBT01 pty,raw,echo=0,link=/tmp/ttyMBT0`
- Make fake server:
    `ncat -lk 8000 -c 'sleep 1; echo "HTTP/1.1 200 OK\r\n\r\nS3R14LNUM83R\n02:00:00:00:00:01\n02:00:00:00:00:02\n02:00:00:00:00:03\n02:00:00:00:00:04\n02:00:00:00:00:05"`
- Run `make run`

## Running in production
- Run: `make run server_url=http://actualserver.com uart_dev=/dev/ttyActualDevice`

## Docs
For more read the `docs.md` (generated documentation from code comments).