import tempfile
import time
import os

import code_server

import openhtf as htf
from openhtf import plugs
from openhtf.util import configuration
from openhtf.output.servers import station_server
from openhtf.plugs import user_input
from openhtf.plugs.generic import serial_collection

CONF = configuration.CONF


@htf.PhaseOptions(timeout_s=None)
@plugs.plug(prompts=user_input.UserInput)
@plugs.plug(server=code_server.CodeServer)
@htf.measures(htf.Measurement("num_macs").equals(5))
def serial_from_server(
        test: openhtf.TestApi,
        prompts: user_input.UserInput,
        server: code_server.CodeServer):
    qr1 = prompts.prompt("Scan the first QR/datamatrix", text_input=True)
    qr2 = prompts.prompt("Scan the second QR/datamatrix", text_input=True)
    serial, macs = server.get_serial_number_and_macs(qr1, qr2)
    test.measurements.num_macs = len(macs)
    test.test_record.dut_id = serial
    test.attach('macs', '\n'.join(macs))


@plugs.plug(serial=serial_collection.SerialCollectionPlug)
def start_serial_port(test: openhtf.TestApi, serial: serial_collection.SerialCollection):
    output = test.state['serial_output'] = tempfile.NamedTemporaryFile(delete=False)
    output.close()
    serial.start_collection(output.name)


@plugs.plug(serial=serial_collection.SerialCollectionPlug)
def stop_serial_port(test: openhtf.TestApi, serial: serial_collection.SerialCollection):
    output = test.state['serial_output']
    test.attach_from_file(output.name)
    os.unlink(output.name)


@plugs.plug(serial=serial_collection.SerialCollectionPlug)
def wait_for_serial_text(
        test: openhtf.TestApi,
        serial: serial_collection.SerialCollection,
        text: str,
        response: str):
    output = test.state['serial_output']
    with open(output.name) as f:
        while text not in f.read():
            time.sleep(1)
    serial._serial.write(response)

def main():
    CONF.load(station_server_port="4444")
    with station_server.StationServer() as server:
        test = htf.Test(
            start_serial_port,
            wait_for_serial_text.with_args(
                text="stop autoboot",
                response="STOP\r\n"),
            stop_serial_port,
        )
        test.add_output_callbacks(server.publish_final_state)
        test.execute(test_start=serial_from_server)


if __name__ == "__main__":
    main()
