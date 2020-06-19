"""Monitor and control liquid coolers and other devices.

Copyright (C) 2018–2020  Jonas Malaco
Copyright (C) 2018–2020  each contribution's author

SPDX-License-Identifier: GPL-3.0-or-later
"""

from .asetek import Modern690Lc, Legacy690Lc, Corsair690Lc
from .corsair_hxi import CorsairHxi
from .hydro_platinum import HydroPlatinum
from .kraken_gen3 import KrakenX2
from .kraken_gen4 import KrakenX3, KrakenZ3
from .seasonic import SeasonicE
from .smart_device import SmartDevice, SmartDeviceV2
## from .smart_device_v2 import *

from .driver_tree import BaseBus as _BaseBus
from .util import find_all_subclasses as _find_all_subclasses


def find_liquidctl_devices(pick=None, **kwargs):
    """Find devices and instantiate corresponding liquidctl drivers.

    Probes all buses and drivers that have been loaded at the time of the call
    and yields driver instances.

    Filter conditions can be passed through to the buses and drivers via
    `**kwargs`.  A driver instance will be yielded for each compatible device
    that matches the supplied filter conditions.

    If `pick` is passed, only the driver instance for the `(pick + 1)`-th
    matched device will be yielded.
    """
    buses = sorted(_find_all_subclasses(_BaseBus), key=lambda x: x.__name__)
    num = 0
    for bus_cls in buses:
        for dev in  bus_cls().find_devices(**kwargs):
            if pick is not None:
                if num == pick:
                    yield dev
                    return
                num += 1
            else:
                yield dev
