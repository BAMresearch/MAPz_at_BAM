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


class HotplateFan(Hardware):
    """
    Class for communication with an Arduino controlling the hotplate fan.

    Parameters
    ----------
    parent_hardware : HotplateHardware
        Field specifying the hotplate hardware where this clamp is located.
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    fan_number : int, default=1
        The number of the hotplate fan. Default is 1.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, parent_hardware: HotplateHardware, arduino_controller: ArduinoController.ArduinoController, timeout: float = 600, fan_number: int = 1):
        """
        Constructor for the HotplateFan Class for communication with the Arduino controlling the hotplate fan.

        Parameters
        ----------
        parent_hardware : HotplateHardware
            Field specifying the hotplate hardware where this clamp is located.
        arduino_controller : ArduinoController.ArduinoController
            The Arduino controller hardware.
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        fan_number : int, default=1
            The number of the hotplate fan. Default is 1.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.FanHardware)
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self.fan_number = fan_number
        self._parent_hardware = parent_hardware
        self.read_queue = self.arduino_controller.get_read_queue(f'FAN{self.fan_number}')
        self._logger_dict = {'instance_name': str(self)}

    def turn_on(self) -> bool:
        """
        Method for turning the fan on.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateFan.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'Fan{self.fan_number} on\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Fan{self.fan_number} turned on.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def turn_off(self) -> bool:
        """
        Method for turning the fan off.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateFan.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'Fan{self.fan_number} off\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Fan{self.fan_number} turned off.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False
