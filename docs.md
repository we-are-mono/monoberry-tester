<a id="monoberrytester.texts"></a>

# monoberrytester.texts

Messages displayed in UI or in the logs.

<a id="monoberrytester.styles"></a>

# monoberrytester.styles

Styles used on some widgets.

<a id="monoberrytester.main"></a>

# monoberrytester.main

This is an application that will be running on a Raspberry Pi that will act
as a testing device for our boards (to start with). It will the following
peripherals connected:
- Power supply (duh...)
- HDMI touch screen
- USB barcode scanner
- Ethernet cable if we can't use WiFi

If it is run without command line  arguments it uses testing ones that are
hardcoded (server endpoint, serial port). In production run it like this:
    $ python example_google.py

Section breaks are created by resuming unindented text. Section breaks
are also implicitly created anytime a new section starts.
-----

<a id="monoberrytester.main.TEST_CASES_DATA"></a>

#### TEST\_CASES\_DATA

A dictionary of test cases to make widgets from and
display in the right panel so they can be marked as successful/failed.

<a id="monoberrytester.main.State"></a>

## State Objects

```python
class State(Enum)
```

Class to define states of the application

<a id="monoberrytester.main.LoggingService"></a>

## LoggingService Objects

```python
class LoggingService(QObject)
```

Class for logging into a file and on screen to QTextEdit widget

**Arguments**:

- `text_widget` _QTextEdit_ - Text field to append log statements to

<a id="monoberrytester.main.LoggingService.info"></a>

#### info

```python
def info(text)
```

Logs text as info

<a id="monoberrytester.main.LoggingService.error"></a>

#### error

```python
def error(text)
```

Logs text as error

<a id="monoberrytester.main.ScannerService"></a>

## ScannerService Objects

```python
class ScannerService(QObject)
```

Class that handles communication with the USB barcode scanner
TODO: replace with actual code when I get the barcode scanner

**Attributes**:

- `code_received` _pyqtSignal_ - Signal for when a code is scanned

<a id="monoberrytester.main.ScannerService.handle_input"></a>

#### handle\_input

```python
def handle_input(key, text)
```

Reads key presses until a return key is pressed

<a id="monoberrytester.main.ServerClient"></a>

## ServerClient Objects

```python
class ServerClient(QThread)
```

HTTP Client to call our server

**Arguments**:

- `server_endpoint` _str_ - URL base for our server
- `logging_service` _LoggingService_ - Service for logging
  

**Example**:

  .. code-block:: console
  
  ncat -lk 8000 -c 'sleep 1; echo "HTTP/1.1 200 OK
  
  S3R14LNUM83R
  
  02:00:00:00:00:01
  02:00:00:00:00:02
  02:00:00:00:00:03
  
  02:00:00:00:00:04
  02:00:00:00:00:05"'

<a id="monoberrytester.main.ServerClient.set_codes"></a>

#### set\_codes

```python
def set_codes(codes)
```

Sets scanned QR data matrix codes (do this before calling `run` method)

<a id="monoberrytester.main.ServerClient.run"></a>

#### run

```python
def run()
```

Runs the thread and fetches serial and MACs from our server

