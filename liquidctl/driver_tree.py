"""Base USB bus, driver and device APIs.

This modules provides abstractions over several platform and implementation
differences.  As such, there is a lot of boilerplate here, but callers should
be able to disregard almost everything and simply work on the UsbDriver/
UsbHidDriver level.

BaseDriver
└── BaseUsbDriver
    ├── UsbHidDriver
    │   └── device: HidapiDevice
    │               ├── wraps hidapi
    │               └── backed by
    │                   ├── hid.dll on Windows
    │                   ├── hidraw on Linux if it was enabled during the build of hidapi
    │                   ├── IOHidManager on MacOS
    │                   └── libusb-1.0 on all other cases
    └── UsbDriver
        └── device: PyUsbDevice
                    ├── wraps PyUSB
                    └── backed by (in order of priority)
                        ├── libusb-1.0
                        ├── libusb-0.1
                        └── OpenUSB

BaseBus
├── HidapiBus
│   └── drivers: all (recursive) subclasses of UsbHidDriver
└── PyUsbBus
    └── drivers: all (recursive) subclasses of UsbDriver

UsbDriver and UsbHidDriver are meant to be used as base classes to the actual
device drivers.  The users of those drivers generally do not care about read,
write or other low level operations; thus, these low level operations are
placed in <driver>.device.

However, there still are legitimate reasons as to why someone would want to
directly access the lower layers (device wrapper level, device implementation
level, or lower).  We do not hide or mark those references as private, but good
judgement should be exercised when calling anything within <driver>.device.

The USB drivers are organized into two buses.  The recommended way to
initialize and bind drivers is through their respective buses, though
<driver>.find_supported_devices can also be useful in certain scenarios.


The subclass constructor can generally be kept unaware of the implementation
details of the device parameter, and find_supported_devices already accepts
keyword arguments and forwards them to the driver constructor.

Copyright (C) 2019–2020  Jonas Malaco
Copyright (C) 2019–2020  each contribution's author

SPDX-License-Identifier: GPL-3.0-or-later
"""

import logging
import sys

import usb
try:
    import hidraw as hid
except ModuleNotFoundError:
    import hid

from .util import find_all_subclasses

LOGGER = logging.getLogger(__name__)


class BaseDriver:
    """Base driver API.

    All drivers are expected to implement this API for compatibility with the
    liquidctl CLI or other thirdy party tools.

    Example usage:

        for dev in <Driver>.find_supported_devices():
            dev.connect()
            try:
                print(dev.get_status())
                if dev.serial_number == '49385027ZP':
                    dev.set_fixed_speed("fan3", 42)
            finally:
                dev.disconnect()

    """

    @classmethod
    def find_supported_devices(cls, **kwargs):
        """Find and bind to compatible devices.

        Returns a list of bound driver instances.
        """
        raise NotImplementedError()

    def connect(self, **kwargs):
        """Connect to the device.

        Procedure before any read or write operation can be performed.
        Typically a handshake between driver and device.
        """
        raise NotImplementedError()

    def initialize(self, **kwargs):
        """Initialize the device.

        Apart from `connect()`, some devices might require a onetime
        initialization procedure after powering on, or to detect hardware
        changes.  This should be called *after* connecting to the device.

        This function can optionally return a list of `(property, value, unit)`
        tuples, similarly to `get_status`.
        """
        raise NotImplementedError()

    def disconnect(self, **kwargs):
        """Disconnect from the device.

        Procedure before the driver can safely unbind from the device.
        Typically just cleanup.
        """
        raise NotImplementedError()

    def get_status(self, **kwargs):
        """Get a status report.

        Returns a list of `(property, value, unit)` tuples.
        """
        raise NotImplementedError()

    def set_color(self, channel, mode, colors, **kwargs):
        """Set the color mode for a specific channel."""
        raise NotImplementedError()

    def set_speed_profile(self, channel, profile, **kwargs):
        """Set channel to follow a speed duty profile."""
        raise NotImplementedError()

    def set_fixed_speed(self, channel, duty, **kwargs):
        """Set channel to a fixed speed duty."""
        raise NotImplementedError()

    @property
    def description(self):
        """Human readable description of the corresponding device."""
        raise NotImplementedError()

    @property
    def vendor_id(self):
        """Numeric vendor identifier."""
        raise NotImplementedError()

    @property
    def product_id(self):
        """Numeric product identifier."""
        raise NotImplementedError()

    @property
    def release_number(self):
        """Device versioning number, or None if N/A.

        In USB devices this is bcdDevice.
        """
        raise NotImplementedError()

    @property
    def serial_number(self):
        """Serial number reported by the device, or None if N/A."""
        raise NotImplementedError()

    @property
    def bus(self):
        """Bus the device is connected to, or None if N/A."""
        raise NotImplementedError()

    @property
    def address(self):
        """Address of the device on the corresponding bus, or None if N/A.

        This typically depends on the bus enumeration order.
        """
        raise NotImplementedError()

    @property
    def port(self):
        """Physical location of the device, or None if N/A.

        This typically refers to a USB port, which is *not* dependent on bus
        enumeration order.  However, a USB port is hub-specific, and hubs can
        be chained.  Thus, for USB devices, this returns a tuple of port
        numbers, from the root hub to the parent of the connected device.
        """
        raise NotImplementedError()


class BaseBus:
    """Base bus API."""

    def find_devices(self, **kwargs):
        """Find compatible devices and yield corresponding driver instances."""
        raise NotImplementedError()


class BaseUsbDriver(BaseDriver):
    """Base driver class for generic USB devices.

    Each driver should provide its own list of SUPPORTED_DEVICES, as well as
    implementations for all methods applicable to the devices is supports.

    SUPPORTED_DEVICES should consist of a list of (vendor id, product
    id, None (reserved), description, and extra kwargs) tuples.

    find_supported_devices will pass these extra kwargs, as well as any it
    receives, to the constructor.
    """

    SUPPORTED_DEVICES = []

    @classmethod
    def probe(cls, handle, vendor=None, product=None, release=None,
              serial=None, match=None, **kwargs):
        """Probe `handle` and yield corresponding driver instances."""
        for vid, pid, _, description, devargs in cls.SUPPORTED_DEVICES:
            if (vendor and vendor != vid) or handle.vendor_id != vid:
                continue
            if (product and product != pid) or handle.product_id != pid:
                continue
            if release and handle.release_number != release:
                continue
            if serial and handle.serial_number != serial:
                continue
            if match and match.lower() not in description.lower():
                continue
            consargs = devargs.copy()
            consargs.update(kwargs)
            dev = cls(handle, description, **consargs)
            LOGGER.debug('instanced driver for %s', description)
            yield dev

    def __init__(self, device, description, **kwargs):
        self.device = device
        self._description = description

    def connect(self, **kwargs):
        """Connect to the device."""
        self.device.open()

    def disconnect(self, **kwargs):
        """Disconnect from the device."""
        self.device.close()

    @property
    def description(self):
        """Human readable description of the corresponding device."""
        return self._description

    @property
    def vendor_id(self):
        """16-bit numeric vendor identifier."""
        return self.device.vendor_id

    @property
    def product_id(self):
        """16-bit umeric product identifier."""
        return self.device.product_id

    @property
    def release_number(self):
        """16-bit BCD device versioning number."""
        return self.device.release_number

    @property
    def serial_number(self):
        """Serial number reported by the device, or None if N/A."""
        return self.device.serial_number

    @property
    def bus(self):
        """Bus the device is connected to, or None if N/A."""
        return self.device.bus

    @property
    def address(self):
        """Address of the device on the corresponding bus, or None if N/A.

        Dependendent on bus enumeration order.
        """
        return self.device.address

    @property
    def port(self):
        """Physical location of the device, or None if N/A.

        Tuple of USB port numbers, from the root hub to this device.  Not
        dependendent on bus enumeration order.
        """
        return self.device.port


class UsbHidDriver(BaseUsbDriver):
    """Base driver class for USB Human Interface Devices (HIDs)."""

    @classmethod
    def find_supported_devices(cls, **kwargs):
        """Find devices specifically compatible with this driver."""
        devs = []
        for vid, pid, _, _, _ in cls.SUPPORTED_DEVICES:
            for dev in HidapiBus().find_devices(vendor=vid, product=pid, **kwargs):
                if type(dev) == cls:
                    devs.append(dev)
        return devs

    def __init__(self, device, description, **kwargs):
        # compatibility with v1.1.0 drivers, which could be directly
        # instantiated with a usb.core.Device
        if isinstance(device, usb.core.Device):
            LOGGER.warning('deprecated: device must be HidapiDevice, not PyUSB handle')
            LOGGER.warning('deprecated: PyUSB no longer supported for HID devices')
            LOGGER.warning('deprecated: switch to find_supported_devices or pass HidapiDevice')
            usbdev = device
            hidinfo = next(info for info in hid.enumerate(usbdev.idVendor, usbdev.idProduct)
                           if info['serial_number'] == usbdev.serial_number)
            assert hidinfo, 'Could not find device in HID bus'
            device = HidapiDevice(hid, hidinfo)
        super().__init__(device, description, **kwargs)


class UsbDriver(BaseUsbDriver):
    """Base driver class for regular USB devices.

    Specifically, regular USB devices are *not* Human Interface Devices (HIDs).
    """

    @classmethod
    def find_supported_devices(cls, **kwargs):
        """Find devices specifically compatible with this driver."""
        devs = []
        for vid, pid, _, _, _ in cls.SUPPORTED_DEVICES:
            for dev in PyUsbBus().find_devices(vendor=vid, product=pid, **kwargs):
                if type(dev) == cls:
                    devs.append(dev)
        return devs


class PyUsbDevice:
    """"A PyUSB backed device.

    PyUSB will automatically pick the first available backend (at runtime).
    The supported backends are:

     - libusb-1.0
     - libusb-0.1
     - OpenUSB
    """

    def __init__(self, usbdev, bInterfaceNumber=None):
        self.api = usb
        self.usbdev = usbdev
        self.bInterfaceNumber = bInterfaceNumber
        self._attached = False

    def _select_interface(self, cfg):
        return self.bInterfaceNumber or 0

    def open(self, bInterfaceNumber=0):
        """Connect to the device.

        Ensure the device is configured and replace the kernel kernel on the
        selected interface, if necessary.
        """
        try:
            cfg = self.usbdev.get_active_configuration()
        except usb.core.USBError:
            LOGGER.debug('setting the (first) configuration')
            self.usbdev.set_configuration()  # assume the first configuration
            # FIXME device or handle might not be ready for use after set_configuration()
            cfg = self.usbdev.get_active_configuration()
        self.bInterfaceNumber = self._select_interface(cfg)
        LOGGER.debug('selected interface: %d', self.bInterfaceNumber)
        if (sys.platform.startswith('linux') and
                self.usbdev.is_kernel_driver_active(self.bInterfaceNumber)):
            LOGGER.debug('replacing stock kernel driver with libusb')
            self.usbdev.detach_kernel_driver(self.bInterfaceNumber)
            self._attached = True

    def claim(self):
        """Explicitly claim the device from other programs."""
        LOGGER.debug('explicitly claim interface')
        usb.util.claim_interface(self.usbdev, self.bInterfaceNumber)

    def release(self):
        """Release the device to other programs."""
        LOGGER.debug('ensure interface is released')
        usb.util.release_interface(self.usbdev, self.bInterfaceNumber)

    def close(self):
        """Disconnect from the device.

        Clean up and (Linux only) reattach the kernel driver.
        """
        self.release()
        if self._attached:
            LOGGER.debug('restoring stock kernel driver')
            self.usbdev.attach_kernel_driver(self.bInterfaceNumber)
            self._attached = False

    def read(self, endpoint, length, timeout=None):
        """Read from endpoint."""
        return self.usbdev.read(endpoint, length, timeout=timeout)

    def write(self, endpoint, data, timeout=None):
        """Write to endpoint."""
        return self.usbdev.write(endpoint, data, timeout=timeout)

    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0,
                      data_or_wLength=None, timeout=None):
        """Submit a contrl transfer."""
        return self.usbdev.ctrl_transfer(bmRequestType, bRequest,
                                         wValue=wValue, wIndex=wIndex,
                                         data_or_wLength=data_or_wLength,
                                         timeout=timeout)

    @classmethod
    def enumerate(cls, vid=None, pid=None):
        args = {}
        if vid:
            args['idVendor'] = vid
        if pid:
            args['idProduct'] = pid
        for handle in usb.core.find(find_all=True, **args):
            yield cls(handle)

    @property
    def vendor_id(self):
        return self.usbdev.idVendor

    @property
    def product_id(self):
        return self.usbdev.idProduct

    @property
    def release_number(self):
        return self.usbdev.bcdDevice

    @property
    def serial_number(self):
        return self.usbdev.serial_number

    @property
    def bus(self):
        return 'usb{}'.format(self.usbdev.bus)  # follow Linux model

    @property
    def address(self):
        return self.usbdev.address

    @property
    def port(self):
        return self.usbdev.port_numbers

    def __eq__(self, other):
        return type(self) == type(other) and self.bus == other.bus and self.address == other.address


class HidapiDevice:
    """A hidapi backed device.

    Depending on the platform, the selected `hidapi` and how it was built, this
    might use any of the following backends:

     - hid.dll on Windows
     - hidraw on Linux, if it was enabled during the build of hidapi
     - IOHidManager on MacOS
     - libusb-1.0 on all other cases

    The default hidapi API is the module 'hid'.  On standard Linux builds of
    the hidapi package, this might default to a libusb-1.0 backed
    implementation; at the same time an alternate 'hidraw' module may also be
    provided.  The latter is prefered, when available.

    Note: if a libusb-backed 'hid' is used on Linux (assuming default build
    options) it will detach the kernel driver, making hidraw and hwmon
    unavailable for that device.  To fix, rebind the device to usbhid with:

        echo '<bus>-<port>:1.0' | sudo tee /sys/bus/usb/drivers/usbhid/bind
    """
    def __init__(self, hidapi, hidapi_dev_info):
        self.api = hidapi
        self.hidinfo = hidapi_dev_info
        self.hiddev = self.api.device()

    def open(self):
        """Connect to the device."""
        self.hiddev.open_path(self.hidinfo['path'])

    def claim(self):
        """NOOP."""
        pass

    def release(self):
        """NOOP."""
        pass

    def close(self):
        """NOOP."""
        pass

    def clear_enqueued_reports(self):
        """Clear already enqueued incoming reports.

        The OS generally enqueues incomming reports for open HIDs, and hidapi
        emulates this when running on top of libusb.  On Linux, up to 64
        reports can be enqueued.

        This method quickly reads and discards any already enqueued reports,
        and is useful when later reads are not expected to return stale data.
        """
        self.hiddev.set_nonblocking(True)
        while self.hiddev.read(1):
            pass

    def read(self, length):
        """Read raw report from HID.

        The returned data follows the semantics of the Linux HIDRAW API.

        > On a device which uses numbered reports, the first byte of the
        > returned data will be the report number; the report data follows,
        > beginning in the second byte. For devices which do not use numbered
        > reports, the report data will begin at the first byte.
        """
        self.hiddev.set_nonblocking(False)
        return self.hiddev.read(length)

    def write(self, data):
        """Write raw report to HID.

        The buffer should follow the semantics of the Linux HIDRAW API.

        > The first byte of the buffer passed to write() should be set to the
        > report number.  If the device does not use numbered reports, the
        > first byte should be set to 0. The report data itself should begin
        > at the second byte.
        """
        return self.hiddev.write(data)

    @classmethod
    def enumerate(cls, api, vid=None, pid=None):
        infos = api.enumerate(vid or 0, pid or 0)
        if sys.platform == 'darwin':
            infos = sorted(infos, key=lambda info: info['path'])
        for info in infos:
            yield cls(api, info)

    @property
    def vendor_id(self):
        return self.hidinfo['vendor_id']

    @property
    def product_id(self):
        return self.hidinfo['product_id']

    @property
    def release_number(self):
        return self.hidinfo['release_number']

    @property
    def serial_number(self):
        return self.hidinfo['serial_number']

    @property
    def bus(self):
        return 'hid'  # follow Linux model

    @property
    def address(self):
        return self.hidinfo['path'].decode()

    @property
    def port(self):
        return None

    def __eq__(self, other):
        return type(self) == type(other) and self.bus == other.bus and self.address == other.address


class HidapiBus(BaseBus):
    def find_devices(self, vendor=None, product=None, bus=None, address=None, **kwargs):
        """Find compatible USB HID devices."""
        handles = HidapiDevice.enumerate(hid, vendor, product)
        drivers = sorted(find_all_subclasses(UsbHidDriver), key=lambda x: x.__name__)
        LOGGER.debug('searching %s (api=%s, drivers=[%s])', self.__class__.__name__, hid.__name__,
                     ', '.join(map(lambda x: x.__name__, drivers)))
        for handle in handles:
            if bus and handle.bus != bus:
                continue
            if address and handle.address != address:
                continue
            LOGGER.debug('probing drivers for device %04x:%04x', handle.vendor_id,
                         handle.product_id)
            for drv in drivers:
                yield from drv.probe(handle, vendor=vendor, product=product, **kwargs)


class PyUsbBus(BaseBus):
    def find_devices(self, vendor=None, product=None, bus=None, address=None,
                     usb_port=None, **kwargs):
        """ Find compatible regular USB devices."""
        drivers = sorted(find_all_subclasses(UsbDriver), key=lambda x: x.__name__)
        LOGGER.debug('searching %s (drivers=[%s])', self.__class__.__name__,
                     ', '.join(map(lambda x: x.__name__, drivers)))
        for handle in PyUsbDevice.enumerate(vendor, product):
            if bus and handle.bus != bus:
                continue
            if address and handle.address != address:
                continue
            if usb_port and handle.port != usb_port:
                continue
            LOGGER.debug('probing drivers for device %04x:%04x', handle.vendor_id,
                         handle.product_id)
            for drv in drivers:
                yield from drv.probe(handle, vendor=vendor, product=product, **kwargs)
