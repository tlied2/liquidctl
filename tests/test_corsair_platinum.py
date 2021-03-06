from _testutils import *

import unittest

from liquidctl.driver.coolit_platinum import CoolitPlatinumDriver
from liquidctl.pmbus import compute_pec


class _MockPlatinumHid(MockHidapiDevice):
    def __init__(self, vendor_id=0xffff, product_id=0x0c17, address=r'/generic\#123!&'):
        super().__init__(vendor_id=vendor_id, product_id=product_id, address=address)
        self.fw_version = (1, 1, 15)
        self.temperature = 30.9
        self.fan1_speed = 1499
        self.fan2_speed = 1512
        self.pump_speed = 2702

    def read(self, length):
        pre = super().read(length)
        if pre:
            return pre
        buf = bytearray(64)
        buf[2] = self.fw_version[0] << 4 | self.fw_version[1]
        buf[3] = self.fw_version[2]
        buf[7] = int((self.temperature - int(self.temperature)) * 255)
        buf[8] = int(self.temperature)
        buf[15:17] = self.fan1_speed.to_bytes(length=2, byteorder='little')
        buf[22:24] = self.fan2_speed.to_bytes(length=2, byteorder='little')
        buf[29:31] = self.pump_speed.to_bytes(length=2, byteorder='little')
        buf[-1] = compute_pec(buf[1:-1])
        return buf[:length]


class CorsairPlatinumTestCase(unittest.TestCase):
    def setUp(self):
        description = 'Mock H115i Platinum'
        kwargs = {'fan_count': 2, 'rgb_fans': True}
        self.mock_hid = _MockPlatinumHid(product_id=0x0c15)
        self.device = CoolitPlatinumDriver(self.mock_hid, description, **kwargs)
        self.device.connect()

    def tearDown(self):
        self.device.disconnect()

    def test_command_format(self):
        self.device._data.store('sequence', None)
        self.device.initialize()
        self.device.get_status()
        self.device.set_fixed_speed(channel='fan', duty=100)
        self.device.set_speed_profile(channel='fan', profile=[])
        self.device.set_color(channel='sync', mode='off', colors=[])
        self.assertEqual(len(self.mock_hid.sent), 6)
        for i, (report, data) in enumerate(self.mock_hid.sent):
            self.assertEqual(report, 0)
            self.assertEqual(len(data), 64)
            self.assertEqual(data[0], 0x3f)
            self.assertEqual(data[1] >> 3, i + 1)
            self.assertEqual(data[-1], compute_pec(data[1:-1]))

    def test_get_status(self):
        temp, pump, fan1, fan2 = self.device.get_status()
        self.assertAlmostEqual(temp[1], self.mock_hid.temperature, delta=1 / 255)
        self.assertEqual(fan1[1], self.mock_hid.fan1_speed)
        self.assertEqual(fan2[1], self.mock_hid.fan2_speed)
        self.assertEqual(pump[1], self.mock_hid.pump_speed)
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0)
        self.assertEqual(self.mock_hid.sent[0].data[2], 0xff)

    def test_handle_real_statuses(self):
        samples = [
            (
                'ff08110f0001002c1e0000aee803aed10700aee803aece0701aa0000aa9c0900'
                '0000000000000000000000000000000000000000000000000000000000000010'
            ),
            (
                'ff40110f009e14011b0102ffe8037e6a0502ffe8037e6d0501aa0000aa350901'
                '0000000000000000000000000000000000000000000000000000000000000098'
            )
        ]
        for sample in samples:
            self.mock_hid.preload_read(Report(0, bytes.fromhex(sample)))
            status = self.device.get_status()
            self.assertEqual(len(status), 4)
            self.assertNotEqual(status[0][1], self.mock_hid.temperature,
                                msg='failed sanity check')

    def test_initialize_status(self):
        (fw_version, ) = self.device.initialize()
        self.assertEqual(fw_version[1], '%d.%d.%d' % self.mock_hid.fw_version)

    def test_common_cooling_prefix(self):
        self.device.initialize(pump_mode='extreme')
        self.device.set_fixed_speed(channel='fan', duty=42)
        self.device.set_speed_profile(channel='fan', profile=[(20, 0), (55, 100)])
        self.assertEqual(len(self.mock_hid.sent), 3)
        for _, data in self.mock_hid.sent:
            self.assertEqual(data[0x1] & 0b111, 0)
            self.assertEqual(data[0x2], 0x14)
            # opaque but apparently important prefix (see @makk50's comments in #82):
            self.assertEqual(data[0x3:0xb], [0x0, 0xff, 0x5] + 5 * [0xff])

    def test_set_pump_mode(self):
        self.device.initialize(pump_mode='extreme')
        self.assertEqual(self.mock_hid.sent[0].data[0x17], 0x2)
        self.assertRaises(Exception, self.device.initialize, pump_mode='invalid')

    def test_fixed_fan_speeds(self):
        self.device.set_fixed_speed(channel='fan', duty=42)
        self.device.set_fixed_speed(channel='fan1', duty=84)
        self.assertEqual(self.mock_hid.sent[-1].data[0x0b], 0x2)
        self.assertAlmostEqual(self.mock_hid.sent[-1].data[0x10] / 2.55, 84, delta=1 / 2.55)
        self.assertEqual(self.mock_hid.sent[-1].data[0x11], 0x2)
        self.assertAlmostEqual(self.mock_hid.sent[-1].data[0x16] / 2.55, 42, delta=1 / 2.55)
        self.assertRaises(Exception, self.device.set_fixed_speed, channel='invalid', duty=0)

    def test_custom_fan_profiles(self):
        self.device.set_speed_profile(channel='fan', profile=iter([(20, 0), (55, 100)]))
        self.device.set_speed_profile(channel='fan1', profile=iter([(30, 20), (50, 80)]))
        self.assertEqual(self.mock_hid.sent[-1].data[0x0b], 0x0)
        self.assertEqual(self.mock_hid.sent[-1].data[0x1d], 7)
        self.assertEqual(self.mock_hid.sent[-1].data[0x1e:0x2c],
                         [30, 51, 50, 204] + 5 * [60, 255])
        self.assertEqual(self.mock_hid.sent[-1].data[0x11], 0x0)
        self.assertEqual(self.mock_hid.sent[-1].data[0x2c:0x3a],
                         [20, 0, 55, 255] + 5 * [60, 255])
        self.assertRaises(Exception, self.device.set_speed_profile,
                          channel='invalid', profile=[])
        self.assertRaises(ValueError, self.device.set_speed_profile,
                          channel='fan', profile=zip(range(10), range(10)))

    def test_address_leds(self):
        colors = [[i + 3, i + 2, i + 1] for i in range(0, 24 * 3, 3)]
        encoded = list(range(1, 24 * 3 + 1))
        self.device.set_color(channel='led', mode='super-fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[0].data[2:62], encoded[:60])
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[1].data[2:14], encoded[60:])

    def test_address_components(self):
        colors = [[i + 3, i + 2, i + 1] for i in range(0, 3 * 3, 3)]
        encoded = [1, 2, 3] * 8 + [4, 5, 6] * 8 + [7, 8, 9] * 8
        self.device.set_color(channel='sync', mode='fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[0].data[2:62], encoded[:60])
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[1].data[2:14], encoded[60:])

    def test_address_component_leds(self):
        colors = [[i + 3, i + 2, i + 1] for i in range(0, 8 * 3, 3)]
        encoded = list(range(1, 25)) * 3
        self.device.set_color(channel='sync', mode='super-fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[0].data[2:62], encoded[:60])
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[1].data[2:14], encoded[60:])

    def test_leds_off(self):
        self.device.set_color(channel='led', mode='off', colors=iter([]))
        self.device.set_color(channel='sync', mode='off', colors=iter([]))
        self.assertEqual(len(self.mock_hid.sent), 4)
        for _, data in self.mock_hid.sent:
            self.assertEqual(data[2:62], [0] * 60)

    def test_invalid_color_modes(self):
        self.assertRaises(Exception, self.device.set_color, channel='led',
                          mode='invalid', colors=[])
        self.assertRaises(Exception, self.device.set_color, channel='led',
                          mode='fixed', colors=[])
        self.assertRaises(Exception, self.device.set_color, channel='sync',
                          mode='invalid', colors=[])
        self.assertRaises(Exception, self.device.set_color, channel='invalid',
                          mode='off', colors=[])

    def test_bad_stored_data(self):
        # TODO
        pass


class H150iProXtTestCase(CorsairPlatinumTestCase):
    def setUp(self):
        description = 'Mock H150i PRO XT'
        kwargs = {'fan_count': 1, 'rgb_fans': False}
        self.mock_hid = _MockPlatinumHid(product_id=0x0c22)
        self.mock_hid.fan2_speed = 0
        self.device = CoolitPlatinumDriver(self.mock_hid, description, **kwargs)
        self.device.connect()

    def test_get_status(self):
        temp, pump, fan = self.device.get_status()
        self.assertAlmostEqual(temp[1], self.mock_hid.temperature, delta=1 / 255)
        self.assertEqual(fan[1], self.mock_hid.fan1_speed)
        self.assertEqual(pump[1], self.mock_hid.pump_speed)
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0)
        self.assertEqual(self.mock_hid.sent[0].data[2], 0xff)

    def test_handle_real_statuses(self):
        samples = [
            (
                'ff10111f002100df23000266e80366df0302b2e803b20000008c00008cba0700'
                '00000000000000ffe803ff00000000000000000000000000000000000000001f'
            ),
        ]
        for sample in samples:
            self.mock_hid.preload_read(Report(0, bytes.fromhex(sample)))
            status = self.device.get_status()
            self.assertEqual(len(status), 3)
            self.assertNotEqual(status[0][1], self.mock_hid.temperature,
                                msg='failed sanity check')

    def test_fixed_fan_speeds(self):
        self.device.set_fixed_speed(channel='fan', duty=42)
        self.assertEqual(self.mock_hid.sent[-1].data[0x0b], 0x2)
        self.assertAlmostEqual(self.mock_hid.sent[-1].data[0x10] / 2.55, 42, delta=1 / 2.55)
        self.device.set_fixed_speed(channel='fan1', duty=84)
        self.assertAlmostEqual(self.mock_hid.sent[-1].data[0x10] / 2.55, 84, delta=1 / 2.55)
        self.assertRaises(Exception, self.device.set_fixed_speed, channel='fan2', duty=0)

    def test_custom_fan_profiles(self):
        self.device.set_speed_profile(channel='fan', profile=iter([(20, 0), (55, 100)]))
        self.assertEqual(self.mock_hid.sent[-1].data[0x0b], 0x0)
        self.assertEqual(self.mock_hid.sent[-1].data[0x1d], 7)
        self.assertEqual(self.mock_hid.sent[-1].data[0x1e:0x2c],
                         [20, 0, 55, 255] + 5 * [60, 255])
        self.device.set_speed_profile(channel='fan1', profile=iter([(30, 20), (50, 80)]))
        self.assertEqual(self.mock_hid.sent[-1].data[0x1e:0x2c],
                         [30, 51, 50, 204] + 5 * [60, 255])
        self.assertRaises(Exception, self.device.set_speed_profile,
                          channel='fan2', profile=[])
        self.assertRaises(ValueError, self.device.set_speed_profile,
                          channel='fan', profile=zip(range(10), range(10)))

    def test_address_leds(self):
        colors = [[i + 3, i + 2, i + 1] for i in range(0, 24 * 3, 3)]
        encoded = list(range(1, 8 * 3 + 1)) + [0] * 48
        self.device.set_color(channel='led', mode='super-fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[0].data[2:62], encoded[:60])
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[1].data[2:14], encoded[60:])

    def test_address_components(self):
        colors = [[i + 3, i + 2, i + 1] for i in range(0, 3 * 3, 3)]
        encoded = [1, 2, 3] * 8 + [0] * 48
        self.device.set_color(channel='sync', mode='fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[0].data[2:62], encoded[:60])
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[1].data[2:14], encoded[60:])

    def test_address_component_leds(self):
        colors = [[i + 3, i + 2, i + 1] for i in range(0, 8 * 3, 3)]
        encoded = list(range(1, 25)) + [0] * 48
        self.device.set_color(channel='sync', mode='super-fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[0].data[2:62], encoded[:60])
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[1].data[2:14], encoded[60:])
