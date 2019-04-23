from collections import namedtuple
from time import sleep
from datetime import datetime

from bluepy import btle
from loguru import logger

from .data_struct import ScheduleMode, SettingsStruct, TemperatureStruct, TimeStruct, BatteryStruct, ScheduleStruct
from .schedule import Schedule
from .utils import etrv_read, etrv_write


Settings = namedtuple('Settings',
    ['frost_protection_temperature', 'schedule_mode', 'vacation_temperature', 'vacation_from', 'vacation_to']
)


class eTRVDevice(object):
    BATTERY_LEVEL_R = 0x0010

    PIN_W = 0x0024

    SETTINGS_RW = 0x002a

    TEMPERATURE_RW = 0x002d

    DEVICE_NAME_RW = 0x0030

    TIME_RW = 0x0036

    SECRET_R = 0x003f

    SCHEDULE_RW = []  # "1002000D-2749-0001-0000-00805F9B042F", "1002000E-2749-0001-0000-00805F9B042F", "1002000F-2749-0001-0000-00805F9B042F"

    def __init__(self, address, secret=None, pin=None):
        """
        Constructor for eTRVDevice
        """
        self.address = address
        self.secret = secret
        self.pin = b'0000' if pin is None else pin
        self.ble_device = None 
    
    @staticmethod
    def scan(timeout=10.0):
        devices = btle.Scanner().scan(timeout)

        for dev in devices:
            scan_data = dev.getScanData()
            for (adtype, desc, value) in scan_data:
                if adtype == 9 and value.endswith(';eTRV'):
                    yield dev

    def is_connected(self):
        return self.ble_device is not None

    def connect(self, send_pin: bool = True):
        """
        This method allow you to connect to eTRV device and if it is required it will
        also send pin. You can select is it necessery
        """
        logger.debug("Trying connect to {}", self.address)
        if self.is_connected():
            logger.debug("Device already connected {}", self.address)
            return

        while True:
            try:
                self.ble_device = btle.Peripheral(self.address)
                if send_pin:
                    self.send_pin()
                break
            except btle.BTLEDisconnectError:
                logger.error("Unable connect to {}. Retrying in 100ms", self.address)
                sleep(0.1)

    def disconnect(self):
        logger.debug("Disconnecting")
        if self.ble_device is not None:
            self.ble_device.disconnect()
            self.ble_device = None

    def send_pin(self):
        logger.debug("Write PIN to {}", self.address)
        self.ble_device.writeCharacteristic(eTRVDevice.PIN_W, self.pin, True)

    @etrv_read(SECRET_R, True)
    def retrieve_secret_key(self, data):
        return data.hex()

    @etrv_read(SETTINGS_RW, True, SettingsStruct)
    def settings(self, data: SettingsStruct):
        ret = Settings()
        ret.frost_protection_temperature = data.frost_protection_temperature * .5
        ret.schedule_mode = data.schedule_mode
        ret.vacation_temperature = data.vacation_temperature * .5
        ret.vacation_from = datetime.utcfromtimestamp(data.vacation_from)
        ret.vacation_to = datetime.utcfromtimestamp(data.vacation_to)
        return ret

    @property
    @etrv_read(TEMPERATURE_RW, True, TemperatureStruct)
    def temperature(self, data: TemperatureStruct):
        """
        This property will return both current and set point temperature
        """
        room_temp = data.room_temperature * .5
        set_temp = data.set_point_temperature * .5
        return room_temp, set_temp

    @property
    def room_temperature(self):
        """
        This property will return current temperature measured on device with precision up to 0.5 degrees
        """
        room_temp, _ = self.temperature
        return room_temp

    @property
    def set_point_temperature(self):
        """
        This property is responsible for set point temperature. It will allow you to not only retrieve
        current value, but also set new. Temperature will be always rounded to 0.5 degree
        """
        _, set_temp = self.temperature
        return set_temp

    @set_point_temperature.setter
    @etrv_write(TEMPERATURE_RW, True)
    def set_point_temperature(self, value: float) -> TemperatureStruct:
        temp = TemperatureStruct()
        temp.set_point_temperature = int(value*2)
        return temp

    @property
    @etrv_read(BATTERY_LEVEL_R, True, BatteryStruct)
    def battery(self, data: BatteryStruct):
        """
        This property will return current battery level in integer
        """
        return data.battery

    @property
    @etrv_read(DEVICE_NAME_RW, True)
    def device_name(self, data: bytes) -> str:
        # TODO This function do not work properly, need to fix later
        data = data.strip(b'\0')
        return data.decode('ascii')

    @property
    @etrv_read(TIME_RW, True, TimeStruct)
    def time(self, data: TimeStruct):
        return datetime.utcfromtimestamp(data.time_local-data.time_offset)

    @property
    @etrv_read(SCHEDULE_RW, True, ScheduleStruct)
    def schedule(self, data: ScheduleStruct) -> Schedule:
        s = Schedule()
        s.parse_struct(data)
        return s
