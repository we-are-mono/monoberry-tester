<a id="..monoberrytester.texts"></a>

# ..monoberrytester.texts

Messages displayed in UI or in the logs.

<a id="..monoberrytester.styles"></a>

# ..monoberrytester.styles

Styles used on some widgets.

<a id="..monoberrytester.main"></a>

# ..monoberrytester.main

MonoBerryTester

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

**Attributes**:

- `TEST_CASES_DATA` _dict_ - A dictionary of test cases to make widgets from and
  display in the right panel so they can be marked as successful/failed.
  
- `State(Enum)` - States that the application goes through. UI updates and other
  things happen based on state transitions.
  

**Todo**:

  * Implement and test a real Scanner class when we get the USB barcode scanner

