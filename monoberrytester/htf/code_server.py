from openhtf.core import base_plugs
import requests


class CodeServer(base_plugs.BasePlug):
    @configuration.inject_positional_args
    def __init__(self, code_server_endpoint: str):
        self._endpoint = code_server_endpoint

    def get_serial_number_and_macs(self, qr1, qr2):
        response = requests.get(
            f"{self._endpoint}/serial-macs", params={"qr1": qr1, "qr2": qr2})
        serial, *macs = response.text.split()
        return serial, macs
