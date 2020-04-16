"""Export monitoring data from liquidctl devices to other software.

Copyright (C) 2020–2020  Jonas Malaco
Copyright (C) 2020–2020  each contribution's author

This file is part of liquidctl.

liquidctl is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

liquidctl is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import logging
import sys
import time
from collections import namedtuple

import usb
import psutil

import liquidctl.elevate


LOGGER = logging.getLogger(__name__)


_export_modes = {}
_export_infos = namedtuple('_export_infos', ['dev', 'devinfos'])


def _restart_hwinfo():
    import psutil

    def find_hwinfo_process():
        for p in psutil.process_iter(['name']):
            if p.info['name'].lower().startswith('hwinfo'):
                return p
        return None

    cmdline = r'C:\Program Files\HWiNFO64\HWiNFO64.exe'
    curr = find_hwinfo_process()
    if curr:
        LOGGER.info('HWiNFO already open, restarting')
        cmdline = curr.cmdline()
        curr.terminate()
        curr.wait()
    LOGGER.debug('cmdline: %s', cmdline)
    psutil.Popen(cmdline)


if sys.platform == 'win32':
    import winreg

    _hwinfo_sensor_type = namedtuple('_hwinfo_sensor_type', ['prefix', 'format'])
    _HWINFO_FLOAT = (winreg.REG_SZ, str)
    _HWINFO_INT = (winreg.REG_DWORD, round)
    _HWINFO_SENSOR_TYPES = {
        '°C': _hwinfo_sensor_type('Temp', _HWINFO_FLOAT),
        'rpm': _hwinfo_sensor_type('Fan', _HWINFO_INT),
        'V': _hwinfo_sensor_type('Volt', _HWINFO_FLOAT),
        'A': _hwinfo_sensor_type('Current', _HWINFO_FLOAT),
        'W': _hwinfo_sensor_type('Power', _HWINFO_FLOAT),
        '%': _hwinfo_sensor_type('Usage', _HWINFO_INT),
        'dB': _hwinfo_sensor_type('Other', _HWINFO_INT),
    }

    _hwinfo_sensor = namedtuple('_hwinfo_sensor', ['key', 'format'])
    _hwinfo_devinfos = namedtuple('_hwinfo_devinfos', ['key', 'sensors'])

    def _hwinfo_restart_hwinfo():
        LOGGER.info('Starting HWiNFO')
        liquidctl.elevate.call(_restart_hwinfo, [])

    def _hwinfo_update_value(sensor, value):
        regtype, regwrite = sensor.format
        winreg.SetValueEx(sensor.key, 'Value', None, regtype, regwrite(value))

    def _hwinfo_init_device(dev, **opts):
        _HWINFO_BASE_KEY = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\HWiNFO64\Sensors\Custom')
        dev_key = winreg.CreateKey(_HWINFO_BASE_KEY, f'{dev.description} ({dev.bus}:{dev.address.__hash__()})')
        sensors = {}
        counts = {unit: 0 for unit in _HWINFO_SENSOR_TYPES.keys()}
        for k, v, u in dev.get_status(**opts):
            sensor_type = _HWINFO_SENSOR_TYPES.get(u, None)
            if not sensor_type:
                continue
            type_count = counts[u]
            counts[u] += 1
            sensor_key = winreg.CreateKey(dev_key, f'{sensor_type.prefix}{type_count}')
            winreg.SetValueEx(sensor_key, 'Name', None, winreg.REG_SZ, k)
            winreg.SetValueEx(sensor_key, 'Unit', None, winreg.REG_SZ, u)
            sensor = _hwinfo_sensor(sensor_key, sensor_type.format)
            _hwinfo_update_value(sensor, v)
            sensors[k] = sensor
        return _hwinfo_devinfos(dev_key, sensors)

    def _hwinfo_update(dev, devinfos, status):
        for k, v, u in status:
            sensor = devinfos.sensors.get(k)
            if not sensor:
                continue
            _hwinfo_update_value(sensor, v)

    def _hwinfo_deinit(dev, devinfos):
        for sensor in devinfos.sensors.values():
            winreg.DeleteKey(sensor.key, '')
        winreg.DeleteKey(devinfos.key, '')

    _export_modes['hwinfo'] = {
        'init': _hwinfo_init_device,
        'post_init': _hwinfo_restart_hwinfo,
        'update':  _hwinfo_update,
        'deinit':  _hwinfo_deinit
    }


def _run_export_loop(devices, init, post_init, update, deinit, update_interval=None, opts=None):
    infos = []
    for dev in devices:
        LOGGER.info('Preparing %s', dev.description)
        dev.connect(**opts)
        devinfos = init(dev, **opts)
        infos.append(_export_infos(dev, devinfos))
    post_init()
    try:
        while True:
            for dev, devinfos in infos:
                try:
                    status = dev.get_status(**opts)
                except usb.core.USBError as err:
                    LOGGER.warning('Failed to read from %s, continuing with stale data',
                                   dev.description)
                    LOGGER.debug(err, exc_info=True)
                update(dev, devinfos, status)
            time.sleep(update_interval)
    except KeyboardInterrupt:
        LOGGER.info('Canceled by user')
    except:
        LOGGER.exception('Unexpected error')
        sys.exit(1)
    finally:
        for dev, devinfos in infos:
            try:
                dev.disconnect(**opts)
                deinit(dev, devinfos)
            except:
                LOGGER.exception('Unexpected error when cleaning up %s', dev.description)


def run(devices, target, update_interval, opts):
    if not devices:
        return
    mode = _export_modes.get(target.lower())
    if not mode:
        raise ValueError(f'Exporting to {target} not supported on this platform')
    _run_export_loop(devices, update_interval=update_interval, opts=opts, **mode)