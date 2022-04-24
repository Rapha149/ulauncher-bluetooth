import re
import shlex
import subprocess
import time
from enum import Enum
from functools import cmp_to_key
from pathlib import Path

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.SetUserQueryAction import SetUserQueryAction
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from wrapt_timeout_decorator import timeout

from bt_tools import BtTools

images_path = Path(__file__).parent / 'images'


def wait(condition, check_condition, wait_timeout):
    max_count, count = wait_timeout / check_condition, 0
    while condition():
        time.sleep(check_condition)
        count += 1
        if count >= max_count:
            return False
    return True


def set_input(extension, keyword, last_input, arg=''):
    same_as_before = arg == last_input or (not arg and not last_input)
    return extension.on_input(keyword, arg) if same_as_before else SetUserQueryAction(f'{keyword} {arg}')


def go_back_item(keyword, name='Go back', new_input=''):
    return ExtensionResultItem(icon='images/back.png',
                               name=name,
                               highlightable=False,
                               on_enter=SetUserQueryAction(f'{keyword} {new_input}'))


def parse_time(time_str):
    seconds = 0
    r = re.compile('(\\d+)([dhms])')
    for arg in time_str.split(' '):
        m = r.match(arg)
        if not m:
            return None
        number, unit = int(m.group(1)), m.group(2)
        if unit == 'd':
            seconds += number * 24 * 60 * 60
        elif unit == 'h':
            seconds += number * 60 * 60
        elif unit == 'm':
            seconds += number * 60
        else:
            seconds += number
    return seconds


def time_to_str(seconds):
    minutes = int(seconds / 60)
    hours = int(minutes / 60)
    days = int(hours / 24)
    seconds %= 60
    minutes %= 60
    hours %= 24

    arr = []
    if days > 0:
        arr.append(f'{days}d')
    if hours > 0:
        arr.append(f'{hours}h')
    if minutes > 0:
        arr.append(f'{minutes}m')
    if seconds > 0 or not arr:
        arr.append(f'{seconds}s')
    return ' '.join(arr)


def get_icon(device):
    is_dict = isinstance(device, dict)
    if is_dict and 'Icon' not in device:
        return f'images/default_0.png'

    icon_str = device['Icon'] if is_dict else device.Icon
    paired = device['Paired'] if is_dict else device.Paired
    connected = device['Connected'] if is_dict else device.Connected

    icon = icon_str.split('-', 2)[0]
    icon_type = '2' if connected else '1' if paired else '0'
    file_name = f'{icon}_{icon_type}.png'
    if (images_path / file_name).is_file():
        return f'images/{file_name}'
    else:
        return f'images/default_{icon_type}.png'


class BluetoothExtension(Extension):

    def __init__(self):
        super().__init__()
        self.bt_tools = BtTools()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

    def on_input(self, keyword, arg):
        adapter = self.bt_tools.get_adapter()
        if adapter is None:
            return RenderResultListAction([
                ExtensionResultItem(icon='images/icon.png',
                                    name='Turn Bluetooth on',
                                    highlightable=False,
                                    on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                    'last_input': arg,
                                                                    'action': Action.TURN_ON}, keep_app_open=True))
            ])

        if not arg:
            items = []

            for address, device in self.bt_tools.get_connected_devices().items():
                items.append(ExtensionResultItem(
                    icon=get_icon(device),
                    name=f'Connected: {device["Alias"]}',
                    description='Enter to manage'
                                '\nAlt+Enter to disconnect',
                    highlightable=False,
                    on_enter=SetUserQueryAction(f'{keyword} device {device["Address"]}'),
                    on_alt_enter=ExtensionCustomAction({'keyword': keyword,
                                                        'last_input': arg,
                                                        'action': Action.DISCONNECT,
                                                        'device': address,
                                                        'from_paired': False}, keep_app_open=True)
                ))

            items.extend([
                ExtensionResultItem(icon='images/icon.png',
                                    name='Change adapter settings',
                                    description='Edit alias and manage discovery and pairing mode',
                                    highlightable=False,
                                    on_enter=SetUserQueryAction(f'{keyword} settings')),
                ExtensionResultItem(icon='images/icon.png',
                                    name='Paired devices',
                                    description=f'There are {len(self.bt_tools.get_paired_devices())} paired devices',
                                    highlightable=False,
                                    on_enter=SetUserQueryAction(f'{keyword} paired'))
            ])

            if adapter.Discovering:
                items.append(ExtensionResultItem(
                    icon='images/icon.png',
                    name=f'Devices found while scanning: {len(self.bt_tools.get_nearby_devices())}',
                    description='Enter to list devices'
                                '\nAlt+Enter to stop scanning',
                    highlightable=False,
                    on_enter=SetUserQueryAction(f'{keyword} scanned'),
                    on_alt_enter=ExtensionCustomAction({'keyword': keyword,
                                                        'last_input': arg,
                                                        'action': Action.STOP_SCAN}, keep_app_open=True)
                ))
            else:
                items.append(ExtensionResultItem(
                    icon='images/icon.png',
                    name='Start scanning for devices',
                    highlightable=False,
                    on_enter=ExtensionCustomAction({'keyword': keyword,
                                                    'last_input': arg,
                                                    'action': Action.START_SCAN}, keep_app_open=True)
                ))

            items.append(ExtensionResultItem(
                icon='images/icon.png',
                name='Turn Bluetooth off',
                highlightable=False,
                on_enter=ExtensionCustomAction({'keyword': keyword,
                                                'last_input': arg,
                                                'action': Action.TURN_OFF}, keep_app_open=True)
            ))
            return RenderResultListAction(items)

        args = arg.split(' ')
        if args[0] == 'settings':
            if len(args) == 1:
                items = [
                    go_back_item(keyword),
                    ExtensionResultItem(icon='images/icon.png',
                                        name='Reload settings',
                                        highlightable=False,
                                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                        'last_input': arg,
                                                                        'action': Action.RELOAD}, keep_app_open=True)),
                    ExtensionResultItem(icon='images/icon.png',
                                        name=f'Alias: "{adapter.Alias}"',
                                        description='Enter to change',
                                        highlightable=False,
                                        on_enter=SetUserQueryAction(f'{keyword} settings alias '))
                ]

                if adapter.Discoverable:
                    if adapter.DiscoverableTimeout == 0:
                        items.append(ExtensionResultItem(
                            icon='images/icon.png',
                            name='Adapter is discoverable',
                            description='Enter to make it invisible'
                                        '\nAlt+Enter to make it temporarily discoverable',
                            highlightable=False,
                            on_enter=ExtensionCustomAction({'keyword': keyword,
                                                            'last_input': arg,
                                                            'action': Action.CHANGE_DISCOVERABLE,
                                                            'discoverable': False}, keep_app_open=True),
                            on_alt_enter=SetUserQueryAction(f'{keyword} settings discoverable ')
                        ))
                    else:
                        items.append(ExtensionResultItem(
                            icon='images/icon.png',
                            name='Adapter is temporarily discoverable',
                            description='Enter to make it invisible'
                                        '\nAlt+Enter to make it permanentely discoverable',
                            highlightable=False,
                            on_enter=ExtensionCustomAction({'keyword': keyword,
                                                            'last_input': arg,
                                                            'action': Action.CHANGE_DISCOVERABLE,
                                                            'discoverable': False}, keep_app_open=True),
                            on_alt_enter=ExtensionCustomAction({'keyword': keyword,
                                                                'last_input': arg,
                                                                'action': Action.CHANGE_DISCOVERABLE,
                                                                'discoverable': True}, keep_app_open=True)
                        ))
                else:
                    items.append(ExtensionResultItem(
                        icon='images/icon.png',
                        name='Adapter is invisible',
                        description='Enter to make it discoverable'
                                    '\nAlt+Enter to make it temporarily discoverable',
                        highlightable=False,
                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                        'last_input': arg,
                                                        'action': Action.CHANGE_DISCOVERABLE,
                                                        'discoverable': True}, keep_app_open=True),
                        on_alt_enter=SetUserQueryAction(f'{keyword} settings discoverable ')
                    ))

                if adapter.Pairable:
                    if adapter.PairableTimeout == 0:
                        items.append(ExtensionResultItem(
                            icon='images/icon.png',
                            name='Adapter is pairable',
                            description='Enter to make it not pairable'
                                        '\nAlt+Enter to make it temporarily pairable',
                            highlightable=False,
                            on_enter=ExtensionCustomAction({'keyword': keyword,
                                                            'last_input': arg,
                                                            'action': Action.CHANGE_PAIRABLE,
                                                            'pairable': False}, keep_app_open=True),
                            on_alt_enter=SetUserQueryAction(f'{keyword} settings pairable ')
                        ))
                    else:
                        items.append(ExtensionResultItem(
                            icon='images/icon.png',
                            name='Adapter is temporarily pairable',
                            description='Enter to make it not pairable'
                                        '\nAlt+Enter to make it permanentely pairable',
                            highlightable=False,
                            on_enter=ExtensionCustomAction({'keyword': keyword,
                                                            'last_input': arg,
                                                            'action': Action.CHANGE_PAIRABLE,
                                                            'pairable': False}, keep_app_open=True),
                            on_alt_enter=ExtensionCustomAction({'keyword': keyword,
                                                                'last_input': arg,
                                                                'action': Action.CHANGE_PAIRABLE,
                                                                'pairable': True}, keep_app_open=True)
                        ))
                else:
                    items.append(ExtensionResultItem(
                        icon='images/icon.png',
                        name='Adapter is not pairable',
                        description='Enter to make it pairable'
                                    '\nAlt+Enter to make it temporarily pairable',
                        highlightable=False,
                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                        'last_input': arg,
                                                        'action': Action.CHANGE_PAIRABLE,
                                                        'pairable': True}, keep_app_open=True),
                        on_alt_enter=SetUserQueryAction(f'{keyword} settings pairable ')
                    ))

                return RenderResultListAction(items)

            if args[1] == 'alias':
                items = []
                if len(args) == 2:
                    items.append(ExtensionResultItem(icon='images/icon.png',
                                                     name='Enter new alias...',
                                                     highlightable=False,
                                                     on_enter=DoNothingAction()))
                else:
                    alias = ' '.join(args[2:])
                    items.append(ExtensionResultItem(
                        icon='images/icon.png',
                        name=f'Set the new alias: {alias}',
                        highlightable=False,
                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                        'last_input': arg,
                                                        'action': Action.CHANGE_ADAPTER_ALIAS,
                                                        'alias': alias}, keep_app_open=True)
                    ))

                items.append(go_back_item(keyword, name='Cancel', new_input='settings'))
                return RenderResultListAction(items)

            if args[1] == 'discoverable':
                items = []
                if len(args) == 2:
                    items.append(ExtensionResultItem(icon='images/icon.png',
                                                     name='Enter the new discoverable timeout',
                                                     description='You can use "s", "m", "h" and "d"'
                                                                 '\nFor example: "1h 30m"',
                                                     highlightable=False,
                                                     on_enter=DoNothingAction()))
                else:
                    seconds = parse_time(' '.join(args[2:]))
                    if seconds is None:
                        items.append(ExtensionResultItem(icon='images/icon.png',
                                                         name='Invalid time format',
                                                         description='You can use "s", "m", "h" and "d"'
                                                                     '\nFor example: "1h 30m"',
                                                         highlightable=False,
                                                         on_enter=DoNothingAction()))
                    elif seconds <= 0:
                        items.append(ExtensionResultItem(icon='images/icon.png',
                                                         name='Invalid time (has to be at least 1 second)',
                                                         description='You can use "s", "m", "h" and "d"'
                                                                     '\nFor example: "1h 30m"',
                                                         highlightable=False,
                                                         on_enter=DoNothingAction()))
                    else:
                        items.append(ExtensionResultItem(
                            icon='images/icon.png',
                            name=f'Set the new discoverable timeout: {time_to_str(seconds)}',
                            description='You can use "s", "m", "h" and "d"'
                                        '\nFor example: "1h 30m"',
                            highlightable=False,
                            on_enter=ExtensionCustomAction({'keyword': keyword,
                                                            'last_input': arg,
                                                            'action': Action.CHANGE_DISCOVERABLE,
                                                            'discoverable': True,
                                                            'timeout': seconds}, keep_app_open=True)
                        ))

                items.append(go_back_item(keyword, name='Cancel', new_input='settings'))
                return RenderResultListAction(items)

            if args[1] == 'pairable':
                items = []
                if len(args) == 2:
                    items.append(ExtensionResultItem(icon='images/icon.png',
                                                     name='Enter the new pairable timeout',
                                                     description='You can use "s", "m", "h" and "d"'
                                                                 '\nFor example: "1h 30m"',
                                                     highlightable=False,
                                                     on_enter=DoNothingAction()))
                else:
                    seconds = parse_time(' '.join(args[2:]))
                    if seconds is None:
                        items.append(ExtensionResultItem(icon='images/icon.png',
                                                         name='Invalid time format',
                                                         description='You can use "s", "m", "h" and "d"'
                                                                     '\nFor example: "1h 30m"',
                                                         highlightable=False,
                                                         on_enter=DoNothingAction()))
                    elif seconds <= 0:
                        items.append(ExtensionResultItem(icon='images/icon.png',
                                                         name='Invalid time (has to be at least 1 second)',
                                                         description='You can use "s", "m", "h" and "d"'
                                                                     '\nFor example: "1h 30m"',
                                                         highlightable=False,
                                                         on_enter=DoNothingAction()))
                    else:
                        items.append(ExtensionResultItem(
                            icon='images/icon.png',
                            name=f'Set the new pairable timeout: {time_to_str(seconds)}',
                            description='You can use "s", "m", "h" and "d"'
                                        '\nFor example: "1h 30m"',
                            highlightable=False,
                            on_enter=ExtensionCustomAction({'keyword': keyword,
                                                            'last_input': arg,
                                                            'action': Action.CHANGE_PAIRABLE,
                                                            'pairable': True,
                                                            'timeout': seconds}, keep_app_open=True)
                        ))

                items.append(go_back_item(keyword, name='Cancel', new_input='settings'))
                return RenderResultListAction(items)

        if args[0] == 'paired':
            items = [go_back_item(keyword)]
            for address, device in self.bt_tools.get_paired_devices().items():
                connected = device['Connected']
                manage = SetUserQueryAction(f'{keyword} device_p {device["Address"]}')
                items.append(ExtensionResultItem(
                    icon=get_icon(device),
                    name=device['Alias'],
                    description='Connected\nEnter to manage' if connected else 'Enter to connect\nAlt+Enter to manage',
                    highlightable=False,
                    on_enter=manage if connected else ExtensionCustomAction({'keyword': keyword,
                                                                             'last_input': arg,
                                                                             'action': Action.CONNECT,
                                                                             'device': address,
                                                                             'from_paired': True}, keep_app_open=True),
                    on_alt_enter=manage
                ))

            return RenderResultListAction(items)

        if args[0] == 'scanned':
            items = [
                go_back_item(keyword),
                ExtensionResultItem(icon='images/icon.png',
                                    name='Reload scanned devices',
                                    highlightable=False,
                                    on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                    'last_input': arg,
                                                                    'action': Action.RELOAD}, keep_app_open=True))
            ]

            def compare(tuple1, tuple2):
                _, device1 = tuple1
                _, device2 = tuple2
                name1, name2 = 'Name' in device1, 'Name' in device2
                if name1 and not name2:
                    return -1
                if not name1 and name2:
                    return 1
                return 0

            for address, device in sorted(list(self.bt_tools.get_nearby_devices().items()), key=cmp_to_key(compare)):
                paired = device['Paired']
                items.append(ExtensionResultItem(
                    icon=get_icon(device),
                    name=device['Alias'] + (' (Paired)' if paired else ''),
                    description='Enter to connect'
                                '\nAlt+Enter to manage' if paired else 'Enter to pair',
                    highlightable=False,
                    on_enter=ExtensionCustomAction({'keyword': keyword,
                                                    'last_input': arg,
                                                    'action': Action.CONNECT if paired else Action.PAIR,
                                                    'device': address,
                                                    'from_paired': False}, keep_app_open=True),
                    on_alt_enter=SetUserQueryAction(f'{keyword} device {device["Address"]}')
                    if paired else DoNothingAction()
                ))

            return RenderResultListAction(items)

        if args[0].startswith('device'):
            if len(args) == 1:
                return

            address = args[1].replace('_', ':')
            device = self.bt_tools.get_device(address)
            if not device:
                return

            from_paired = args[0].endswith('_p')
            icon = get_icon(device)

            if len(args) == 2:
                return RenderResultListAction([
                    go_back_item(keyword, new_input='paired' if from_paired else ''),
                    ExtensionResultItem(icon='images/icon.png',
                                        name='Reload information',
                                        highlightable=False,
                                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                        'last_input': arg,
                                                                        'action': Action.RELOAD}, keep_app_open=True)),
                    ExtensionResultItem(icon=icon,
                                        name=f'Device: {device.Name}',
                                        description=f'Address: {address}'
                                                    f'\nEnter to unpair',
                                        highlightable=False,
                                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                        'last_input': arg,
                                                                        'action': Action.UNPAIR,
                                                                        'device': address,
                                                                        'from_paired': from_paired},
                                                                       keep_app_open=True)),
                    ExtensionResultItem(icon=icon,
                                        name=f'Connected: {"yes" if device.Connected else "no"}',
                                        description=f'Enter to {"dis" if device.Connected else ""}connect',
                                        highlightable=False,
                                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                        'last_input': arg,
                                                                        'action': Action.DISCONNECT if
                                                                        device.Connected else Action.CONNECT,
                                                                        'device': address,
                                                                        'from_paired': from_paired},
                                                                       keep_app_open=True)),
                    ExtensionResultItem(icon=icon,
                                        name=f'Alias: {device.Alias}',
                                        description='Enter to change',
                                        highlightable=False,
                                        on_enter=SetUserQueryAction(f'{keyword} {args[0]} {address} alias ')),
                    ExtensionResultItem(icon=icon,
                                        name=f'Trusted: {"yes" if device.Trusted else "no"}',
                                        description=f'Enter to {"un" if device.Trusted else ""}trust',
                                        highlightable=False,
                                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                        'last_input': arg,
                                                                        'action': Action.CHANGE_DEVICE_TRUSTED,
                                                                        'device': address,
                                                                        'from_paired': from_paired,
                                                                        'trusted': not device.Trusted},
                                                                       keep_app_open=True)),
                    ExtensionResultItem(icon=icon,
                                        name=f'Blocked: {"yes" if device.Blocked else "no"}',
                                        description=f'Enter to {"un" if device.Blocked else ""}block',
                                        highlightable=False,
                                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                                        'last_input': arg,
                                                                        'action': Action.CHANGE_DEVICE_BLOCKED,
                                                                        'device': address,
                                                                        'from_paired': from_paired,
                                                                        'blocked': not device.Blocked},
                                                                       keep_app_open=True))
                ])

            if args[2] == 'alias':
                items = []
                if len(args) == 3:
                    items.append(ExtensionResultItem(icon=icon,
                                                     name='Enter new alias...',
                                                     description=f'Device: {device.Name}',
                                                     highlightable=False,
                                                     on_enter=DoNothingAction()))
                else:
                    alias = ' '.join(args[3:])
                    items.append(ExtensionResultItem(
                        icon=icon,
                        name=f'Set the new alias: {alias}',
                        description=f'Device: {device.Name}',
                        highlightable=False,
                        on_enter=ExtensionCustomAction({'keyword': keyword,
                                                        'last_input': arg,
                                                        'action': Action.CHANGE_DEVICE_ALIAS,
                                                        'device': address,
                                                        'from_paired': from_paired,
                                                        'alias': alias}, keep_app_open=True)
                    ))

                items.append(go_back_item(keyword, name='Cancel', new_input='settings'))
                return RenderResultListAction(items)


class KeywordQueryEventListener(EventListener):

    def on_event(self, event: KeywordQueryEvent, extension: BluetoothExtension):
        return extension.on_input(event.get_keyword(), event.get_argument())


class ItemEnterEventListener(EventListener):

    def on_event(self, event: ItemEnterEvent, extension: BluetoothExtension):
        bt_tools = extension.bt_tools
        adapter = bt_tools.get_adapter()
        data = event.get_data()
        keyword, last_input, action = data['keyword'], data['last_input'], data['action']

        if action == Action.RELOAD:
            return set_input(extension, keyword, last_input, arg=last_input)

        if action == Action.TURN_ON:
            if adapter is not None:
                return
            subprocess.call(shlex.split(extension.preferences['command_on']), stdout=subprocess.DEVNULL)
            if wait(lambda: bt_tools.get_adapter() is None, 0.25, 5):
                return set_input(extension, keyword, last_input)
            else:
                return DoNothingAction()

        if adapter is None:
            return set_input(extension, keyword, last_input)

        if action == Action.TURN_OFF:
            subprocess.call(shlex.split(extension.preferences['command_off']), stdout=subprocess.DEVNULL)
            if wait(lambda: bt_tools.get_adapter() is not None, 0.25, 5):
                return set_input(extension, keyword, last_input)
            else:
                return DoNothingAction()

        if action == Action.CHANGE_ADAPTER_ALIAS:
            adapter.Alias = data['alias']
            return set_input(extension, keyword, last_input, arg='settings')

        if action == Action.CHANGE_DISCOVERABLE:
            adapter.DiscoverableTimeout = data['timeout'] if 'timeout' in data else 0
            adapter.Discoverable = data['discoverable']
            return set_input(extension, keyword, last_input, arg='settings')

        if action == Action.CHANGE_PAIRABLE:
            adapter.PairableTimeout = data['timeout'] if 'timeout' in data else 0
            adapter.Pairable = data['pairable']
            return set_input(extension, keyword, last_input, arg='settings')

        if action == Action.START_SCAN:
            if adapter.Discovering:
                return set_input(extension, keyword, last_input)
            adapter.StartDiscovery()
            time.sleep(2)
            return SetUserQueryAction(f'{keyword} scanned')

        if action == Action.STOP_SCAN:
            if adapter.Discovering:
                adapter.StopDiscovery()
            return set_input(extension, keyword, last_input)

        if action == Action.CONNECT:
            device = bt_tools.get_device(data['device'])
            redirect_failed = 'paired' if data['from_paired'] else ''
            if not device:
                return set_input(extension, keyword, last_input, arg=redirect_failed)
            redirect = f'device{"_p" if data["from_paired"] else ""} {device.Address}'
            if device.Connected:
                return set_input(extension, keyword, last_input, arg=redirect)

            @timeout(5, timeout_exception=Exception)
            def connect():
                device.Connect()

            # noinspection PyBroadException
            try:
                connect()
                return set_input(extension, keyword, last_input, arg=redirect)
            except Exception:
                return set_input(extension, keyword, last_input, arg=redirect_failed)

        if action == Action.DISCONNECT:
            device = bt_tools.get_device(data['device'])
            if not device:
                return set_input(extension, keyword, last_input)
            if device.Connected:
                device.Disconnect()
                if not wait(lambda: device.Connected, 0.25, 5):
                    return set_input(extension, keyword, last_input)
            return set_input(extension, keyword, last_input,
                             arg=f'device_p {device.Address}' if data['from_paired'] else '')

        if action == Action.PAIR:
            device = bt_tools.get_device(data['device'])
            if not device:
                return set_input(extension, keyword, last_input, arg='scanned')
            if device.Paired:
                return set_input(extension, keyword, last_input, arg=f'device {device.Address}')

            @timeout(5, timeout_exception=Exception)
            def pair():
                device.Pair()

            # noinspection PyBroadException
            try:
                pair()
                return set_input(extension, keyword, last_input, arg=f'device_p {device.Address}')
            except Exception:
                return set_input(extension, keyword, last_input, arg='paired')

        if action == Action.UNPAIR:
            device = bt_tools.get_device(data['device'])
            if not device:
                return set_input(extension, keyword, last_input, arg='paired' if data['from_paired'] else '')
            if not device.Paired:
                return set_input(extension, keyword, last_input)
            adapter.RemoveDevice(f'{device.Adapter}/dev_{device.Address.replace(":", "_")}')
            wait(lambda: bt_tools.get_device(data['device']) is not None and device.Paired, 0.25, 5)
            return set_input(extension, keyword, last_input, arg='paired' if data['from_paired'] else '')

        if action == Action.CHANGE_DEVICE_ALIAS:
            device = bt_tools.get_device(data['device'])
            if not device or not device.Paired:
                return set_input(extension, keyword, last_input, arg='paired' if data['from_paired'] else '')
            device.Alias = data['alias']
            return set_input(extension, keyword, last_input,
                             arg=f'device{"_p" if data["from_paired"] else ""} {data["device"]}')

        if action == Action.CHANGE_DEVICE_TRUSTED:
            device = bt_tools.get_device(data['device'])
            if not device or not device.Paired:
                return set_input(extension, keyword, last_input, arg='paired' if data['from_paired'] else '')
            device.Trusted = data['trusted']
            return set_input(extension, keyword, last_input,
                             arg=f'device{"_p" if data["from_paired"] else ""} {data["device"]}')

        if action == Action.CHANGE_DEVICE_BLOCKED:
            device = bt_tools.get_device(data['device'])
            if not device or not device.Paired:
                return set_input(extension, keyword, last_input, arg='paired' if data['from_paired'] else '')
            device.Blocked = data['blocked']
            return set_input(extension, keyword, last_input,
                             arg=f'device{"_p" if data["from_paired"] else ""} {data["device"]}')


class Action(Enum):
    RELOAD = 1
    TURN_ON = 2
    TURN_OFF = 3
    CHANGE_ADAPTER_ALIAS = 4
    CHANGE_DISCOVERABLE = 5
    CHANGE_PAIRABLE = 6
    START_SCAN = 7
    STOP_SCAN = 8
    CONNECT = 9
    DISCONNECT = 10
    PAIR = 11
    UNPAIR = 12
    CHANGE_DEVICE_ALIAS = 13
    CHANGE_DEVICE_TRUSTED = 14
    CHANGE_DEVICE_BLOCKED = 15


if __name__ == '__main__':
    BluetoothExtension().run()
