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

from Minerva.Hardware.ControllerHardware import ArduinoController
from Minerva.API.HelperClassDefinitions import Hardware, HardwareTypeDefinitions, PathNames

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


class Electromagnet(Hardware):
    """
    Class for communication with an Arduino controlling electromagnets.

    Parameters
    ----------
    arduino_controller : ArduinoController.ArduinoController
        The Arduino controller hardware.
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    magnet_number : int, default=0
        The number of the magnet. Default is 0
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, timeout: float = 600, magnet_number: int = 0):
        """
        Constructor for the Electromagnet Class for communication with the Arduino controlling the electromagnets.

        Parameters
        ----------
        arduino_controller : ArduinoController
            The Arduino controller hardware.
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        magnet_number : int, default=0
            The number of the magnet. Default is 0
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.ElectromagnetHardware)
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self.magnet_number = magnet_number
        self.read_queue = self.arduino_controller.get_read_queue(f'MAGNET{self.magnet_number}')
        self._logger_dict = {'instance_name': str(self)}

    def turn_on(self) -> bool:
        """
        Turns the electromagnet on.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if Electromagnet.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'MAGNET{self.magnet_number} ON\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Magnet {self.magnet_number} turned on.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def turn_off(self) -> bool:
        """
        Turns the electromagnet off.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if Electromagnet.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'MAGNET{self.magnet_number} OFF\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Magnet {self.magnet_number} turned off.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def release(self) -> bool:
        """
        Releases the piece currently held by the electromagnet briefly reversing the polarity and then turning the magnet off.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if Electromagnet.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'MAGNET{self.magnet_number} REL\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Magnet {self.magnet_number} released.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def reverse_polarity(self) -> bool:
        """
        Reverses the polarity of the electromagnet.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if Electromagnet.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'MAGNET{self.magnet_number} REV\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Polarity of magnet {self.magnet_number} reversed.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def emergency_stop(self) -> bool:
        """
        Sends an emergency stop request to the Arduino, causing it to ignore all further commands until cleared.

        Returns
        -------
        bool
            True if the request was sent successfully, false otherwise.
        """
        Electromagnet.EMERGENCY_STOP_REQUEST = True

        self.arduino_controller.write('ESR\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == "OK":
            logger.critical(f"Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
            return True
        else:
            logger.critical(f"Error in emergency stop protocol.", extra=self._logger_dict)
            logger.error(r, extra=self._logger_dict)
            return False

    def clear_emergency_stop(self) -> bool:
        """
        Clears a previously sent emergency stop request, and continue processing commands.

        Returns
        -------
        bool
            True if the request was cleared successfully, false otherwise.
        """
        self.arduino_controller.write('CES\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == "OK":
            logger.info(f"Emergency stop cleared. Continuing to process commands.", extra=self._logger_dict)
            Electromagnet.EMERGENCY_STOP_REQUEST = False
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False


"""
Communication: 9600 8 N 1

Send commands values in [] are optional:
<COMMAND>[ ][VALUE][CHR(13)]<CHR(10)>
Answer:
OK<CHR(13)><CHR(10)>                          - If command was executed successfully
UNK<CHR(13)><CHR(10)>                         - Unknown Command
ERR <byte>: <errormessage><CHR(13)><CHR(10)>  - If an error occured while executing the command
<String><CHR(13)><CHR(10)>                    - String containing the answer to a query

Action Commands:
ON
Turns the electromagnet on
OFF
Turns the electromagnet off
REL
Releases the piece currently held by the electromagnet briefly reversing the polarity and then turning the magnet off.
REV
Reverses the polarity of the electromagnet
"""
