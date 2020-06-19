"""Compatibility shim that replaces deprecated liquidctl.driver package.

This should not be used in new code.  Instead, prefer the new module names.

liquidctl.driver.asetek       -> liquidctl.asetek
liquidctl.driver.kraken_two   -> liquidctl.kraken_gen3 [1]
liquidctl.driver.seasonic     -> liquidctl.seasonic
liquidctl.driver.smart_device -> liquidctl.smart_device,
                                 liquidctl.smart_device_v2 [2]

The drivers have also been renamed and now match the "device" abstraction
provided to the caller.  They can be imported from their respective modules
(which group drivers by protocol) or directly from the base package.

[1] The new kraken_gen3 module name reflects that the protocol is grouped by
generation number.  On the other hand the new driver name is KrakenX2, matching
the common suffix in the marketed devices names.

[2] The Smart Device V2 protocol has extracted into a new module, but aliases
have been added to the other module to ensure backwards compatibility.

Copyright (C) 2020–2020  Jonas Malaco
Copyright (C) 2020–2020  each contribution's author

SPDX-License-Identifier: GPL-3.0-or-later
"""

import logging
import sys

# deprecated aliases
from . import find_liquidctl_devices
from . import asetek
from . import corsair_hxi as corsair_hid_psu
from . import kraken_gen3 as kraken_two
from . import seasonic
from . import smart_device

# allow old protocol/driver imports to continue to work by manually placing
# these into the module cache, so import liquidctl.driver.foo does not need to
# check the filesystem for foo
sys.modules['liquidctl.driver.asetek'] = asetek
sys.modules['liquidctl.driver.corsair_hid_psu'] = corsair_hid_psu
sys.modules['liquidctl.driver.kraken_two'] = kraken_two
sys.modules['liquidctl.driver.seasonic'] = seasonic
sys.modules['liquidctl.driver.smart_device'] = smart_device

logger = logging.getLogger(__name__)
logger.debug('using deprecated liquidctl.driver names')
