"""liquidctl driver for Corsair HID PSUs.

Supported devices
-----------------

 - Corsair HXi (HX750i, HX850i, HX1000i and HX1200i)
 - Corsair RMi (RM650i, RM750i, RM850i and RM1000i)

Supported features
------------------

 - general device monitoring
 - electrical input monitoring
 - electrical output monitoring
 - fan control
 - +12V single or multi rail OCP

Copyright (C) 2019–2020  Jonas Malaco
Copyright (C) 2019–2020  each contribution's author

Port of corsaiRMi by notaz and realies.
Copyright (c) notaz, 2016

Incorporates or uses as reference work by Sean Nelson.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import logging

from datetime import timedelta
from enum import Enum

from .driver_tree import UsbHidDriver
from .pmbus import CommandCode as CMD
from .pmbus import WriteBit, linear_to_float
from .util import clamp

LOGGER = logging.getLogger(__name__)

_READ_LENGTH = 64
_WRITE_LENGTH = 64
_SLAVE_ADDRESS = 0x02
_CORSAIR_READ_TOTAL_UPTIME = CMD.MFR_SPECIFIC_D1
_CORSAIR_READ_UPTIME = CMD.MFR_SPECIFIC_D2
_CORSAIR_12V_OCP_MODE = CMD.MFR_SPECIFIC_D8
_CORSAIR_READ_INPUT_POWER = CMD.MFR_SPECIFIC_EE
_CORSAIR_FAN_CONTROL_MODE = CMD.MFR_SPECIFIC_F0

_RAIL_12V = 0x0
_RAIL_5V = 0x1
_RAIL_3P3V = 0x2
_RAIL_NAMES = {_RAIL_12V : '+12V', _RAIL_5V : '+5V', _RAIL_3P3V : '+3.3V'}
_MIN_FAN_DUTY = 0


class OCPMode(Enum):
    """Overcurrent protection mode."""

    SINGLE_RAIL = 0x1
    MULTI_RAIL = 0x2

    def __str__(self):
        return self.name.capitalize().replace('_', ' ')

class FanControlMode(Enum):
    """Fan control mode."""

    HARDWARE = 0x0
    SOFTWARE = 0x1

    def __str__(self):
        return self.name.capitalize()


class CorsairHxi(UsbHidDriver):
    """liquidctl driver for Corsair HID PSUs."""

    SUPPORTED_DEVICES = [
        (0x1b1c, 0x1c05, None, 'Corsair HX750i (experimental)', {}),
        (0x1b1c, 0x1c06, None, 'Corsair HX850i (experimental)', {}),
        (0x1b1c, 0x1c07, None, 'Corsair HX1000i (experimental)', {}),
        (0x1b1c, 0x1c08, None, 'Corsair HX1200i (experimental)', {}),
        (0x1b1c, 0x1c0a, None, 'Corsair RM650i (experimental)', {}),
        (0x1b1c, 0x1c0b, None, 'Corsair RM750i (experimental)', {}),
        (0x1b1c, 0x1c0c, None, 'Corsair RM850i (experimental)', {}),
        (0x1b1c, 0x1c0d, None, 'Corsair RM1000i (experimental)', {}),
    ]

    def initialize(self, single_12v_ocp=False, **kwargs):
        """Initialize the device.

        Necessary to receive non-zero value responses from the device.

        Note: replies before calling this function appear to follow the
        pattern <address> <cte 0xfe> <zero> <zero> <padding...>.
        """
        self.device.clear_enqueued_reports()
        self._write([0xfe, 0x03])  # not well understood
        self._read()
        mode = OCPMode.SINGLE_RAIL if single_12v_ocp else OCPMode.MULTI_RAIL
        if mode != self._get_12v_ocp_mode():
            # TODO replace log level with info once this has been confimed to work
            LOGGER.warning('(experimental feature) changing +12V OCP mode to %s', mode)
            self._exec(WriteBit.WRITE, _CORSAIR_12V_OCP_MODE, [mode.value])
        if self._get_fan_control_mode() != FanControlMode.HARDWARE:
            LOGGER.info('resetting fan control to hardware mode')
            self._set_fan_control_mode(FanControlMode.HARDWARE)
        self.device.release()

    def get_status(self, **kwargs):
        """Get a status report.

        Returns a list of `(property, value, unit)` tuples.
        """
        self.device.clear_enqueued_reports()
        ret = self._exec(WriteBit.WRITE, CMD.PAGE, [0])
        if ret[1] == 0xfe:
            LOGGER.warning('possibly uninitialized device')
        status = [
            ('Current uptime', self._get_timedelta(_CORSAIR_READ_UPTIME), ''),
            ('Total uptime', self._get_timedelta(_CORSAIR_READ_TOTAL_UPTIME), ''),
            ('Temperature 1', self._get_float(CMD.READ_TEMPERATURE_1), '°C'),
            ('Temperature 2', self._get_float(CMD.READ_TEMPERATURE_2), '°C'),
            ('Fan control mode', self._get_fan_control_mode(), ''),
            ('Fan speed', self._get_float(CMD.READ_FAN_SPEED_1), 'rpm'),
            ('Input voltage', self._get_float(CMD.READ_VIN), 'V'),
            ('Total power', self._get_float(_CORSAIR_READ_INPUT_POWER), 'W'),
            ('+12V OCP mode', self._get_12v_ocp_mode(), ''),
        ]
        for rail in [_RAIL_12V, _RAIL_5V, _RAIL_3P3V]:
            name = _RAIL_NAMES[rail]
            self._exec(WriteBit.WRITE, CMD.PAGE, [rail])
            status.append((f'{name} output voltage', self._get_float(CMD.READ_VOUT), 'V'))
            status.append((f'{name} output current', self._get_float(CMD.READ_IOUT), 'A'))
            status.append((f'{name} output power', self._get_float(CMD.READ_POUT), 'W'))
        self._exec(WriteBit.WRITE, CMD.PAGE, [0])
        self.device.release()
        LOGGER.warning('reading the +12V OCP mode is an experimental feature')
        return status

    def set_fixed_speed(self, channel, duty, **kwargs):
        """Set channel to a fixed speed duty."""
        duty = clamp(duty, _MIN_FAN_DUTY, 100)
        LOGGER.info('ensuring fan control is in software mode')
        self._set_fan_control_mode(FanControlMode.SOFTWARE)
        LOGGER.info('setting fan PWM duty to %i%%', duty)
        self._exec(WriteBit.WRITE, CMD.FAN_COMMAND_1, [duty])
        self.device.release()

    def _write(self, data):
        padding = [0x0]*(_WRITE_LENGTH - len(data))
        LOGGER.debug('write %s (and %i padding bytes)',
                     ' '.join(format(i, '02x') for i in data), len(padding))
        self.device.write(data + padding)

    def _read(self):
        msg = self.device.read(_READ_LENGTH)
        LOGGER.debug('received %s', ' '.join(format(i, '02x') for i in msg))
        return msg

    def _exec(self, writebit, command, data=None):
        self._write([_SLAVE_ADDRESS | WriteBit(writebit), CMD(command)] + (data or []))
        return self._read()

    def _get_12v_ocp_mode(self):
        """Get +12V single/multi-rail OCP mode."""
        return OCPMode(self._exec(WriteBit.READ, _CORSAIR_12V_OCP_MODE)[2])

    def _get_fan_control_mode(self):
        """Get hardware/software fan control mode."""
        return FanControlMode(self._exec(WriteBit.READ, _CORSAIR_FAN_CONTROL_MODE)[2])

    def _set_fan_control_mode(self, mode):
        """Set hardware/software fan control mode."""
        return self._exec(WriteBit.WRITE, _CORSAIR_FAN_CONTROL_MODE, [mode.value])

    def _get_float(self, command):
        """Get float value with `command`."""
        return linear_to_float(self._exec(WriteBit.READ, command)[2:])

    def _get_timedelta(self, command):
        """Get timedelta with `command`."""
        secs = int.from_bytes(self._exec(WriteBit.READ, command)[2:], byteorder='little')
        return timedelta(seconds=secs)


# deprecated aliases
CorsairHidPsuDriver = CorsairHxi
