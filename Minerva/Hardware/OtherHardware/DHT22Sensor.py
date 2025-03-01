#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import logging
import os.path
import threading
import time
from typing import Optional

from Minerva.API.HelperClassDefinitions import Hardware, HotplateHardware, HardwareTypeDefinitions, PathNames
from Minerva.Hardware.ControllerHardware import ArduinoController

# Create a custom logger and set it to the lowest level
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create handlers
c_handler = logging.StreamHandler()
f_handler = logging.FileHandler(filename=os.path.join(PathNames.LOG_DIR.value, 'log.txt'), mode='a')

# Configure the handlers
c_format = logging.Formatter('%(asctime)s<%(thread)d>:%(instance_name)s:%(levelname)s - %(message)s')
f_format = logging.Formatter('%(asctime)s<%(thread)d>:%(instance_name)s:%(levelname)s - %(message)s')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Set the logging levels for the individual handlers
c_handler.setLevel(logging.DEBUG)
f_handler.setLevel(logging.INFO)

# Add handlers to the logger
logger.addHandler(c_handler)
logger.addHandler(f_handler)


class DHT22Sensor(Hardware):
    """
    Class for communication with an Arduino controlling the DHT22 Sensor.

    Parameters
    ----------
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    sensor_number : int, default=1
        The number of the DHT22 sensor. Default is 1.
    retries : int, default=10
        The number of retries if the sensor returns an error (the 1 wire protocol is a bit error-prone). Default is 10.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, timeout: float = 600, sensor_number: int = 1, retries: int = 10, interval: Optional[int] = 3600):
        """
        Constructor for the DHT22Sensor Class for communication with the Arduino controlling the DHT22 sensor.

        Parameters
        ----------
        arduino_controller : ArduinoController.ArduinoController
            The Arduino controller hardware.
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        sensor_number : int, default=1
            The number of the DHT22 sensor. Default is 1.
        retries : int, default=10
            The number of retries if the sensor returns an error (the 1 wire protocol is a bit error-prone). Default is 10.
        interval: int = 3600
            The interval for the readings in seconds. Default is 3600 s. Set to None to disable periodic reading
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.SensorHardware)
        self.timeout = timeout
        self.retries = retries
        self.arduino_controller = arduino_controller
        self.sensor_number = sensor_number
        self.read_queue = self.arduino_controller.get_read_queue(f'DHT22SENSOR{self.sensor_number}')
        self._shutdown = False
        self.interval = interval
        self._logger_dict = {'instance_name': str(self)}

        if self.interval is not None and self.interval > 0:
            self._polling_thread = threading.Thread(target=self._measure_continuous, daemon=True)
            self._polling_thread.start()

    def measure(self) -> bool:
        """
        Method for reading the sensor values once.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if DHT22Sensor.EMERGENCY_STOP_REQUEST:
            return False

        for _ in range(0, self.retries):
            self.arduino_controller.write(f'DHT22SENSOR{self.sensor_number} measure\n')
            r = self.read_queue.get(timeout=self.timeout)
            if r[-1] == 'OK':
                logger.info(f'Temperature: {r[0]} C, Humidity: {r[1]} %', extra=self._logger_dict)
                return True

        logger.error(r, extra=self._logger_dict)
        return False

    def _measure_continuous(self) -> None:
        """
        Method for continuously reading the sensor values in a certain interval.
        """
        while not self._shutdown and not DHT22Sensor.EMERGENCY_STOP_REQUEST:
            self.measure()
            time.sleep(self.interval)
