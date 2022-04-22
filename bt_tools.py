import re

import pydbus
from gi.repository import GLib


class BtTools:

    def __init__(self):
        self._bus = pydbus.SystemBus()
        self._manager = self._bus.get('org.bluez', '/')
        self._adapter = None
        self._pattern = re.compile('\\/org\\/bluez\\/hci\\d*\\/dev\\_(.*)')

    def get_devices(self):
        items = {}
        for key, value in self._manager.GetManagedObjects().items():
            if 'org.bluez.Device1' not in value:
                continue

            m = self._pattern.match(key)
            if m is not None:
                items[m.group(1)] = value['org.bluez.Device1']
        return items

    def get_nearby_devices(self):
        return {k: v for k, v in self.get_devices().items() if 'RSSI' in v}

    def get_connected_devices(self):
        return {k: v for k, v in self.get_devices().items() if v['Connected']}

    def get_paired_devices(self):
        return {k: v for k, v in self.get_devices().items() if v['Paired']}

    def get_device(self, dev: str):
        try:
            return self._bus.get('org.bluez', f'/org/bluez/hci0/dev_{dev.replace(":", "_")}')
        except KeyError:
            return None

    def get_adapter(self):
        if '/org/bluez/hci0' in self._manager.GetManagedObjects():
            if self._adapter is not None:
                return self._adapter
            else:
                self._adapter = self._bus.get('org.bluez', '/org/bluez/hci0')
                return self._adapter
        else:
            self._adapter = None
            return None


if __name__ == '__main__':
    BtTools()
