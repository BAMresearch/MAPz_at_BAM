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
from typing import Union, Tuple, List, Dict, Any

from Minerva.Hardware.ControllerHardware import ArduinoController
from Minerva.Hardware.SampleHolder.SampleHolder import SampleHolder
from Minerva.API.HelperClassDefinitions import PathNames

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

class TwoPositionStirrerDCMotors(SampleHolder):
    """
    Class for communication with an Arduino controlling a stir plate for two flasks (based on DVD spindle motors).

    Parameters
    ----------
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
        Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
    parent_hardware : Union[Hardware, None] = None
        Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
    deck_position : int, default = 0
        The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
    leave_even_rows_empty : bool, default = True
        If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, hardware_definition: Union[SampleHolderDefinitions, str, Dict[str, Any]], parent_hardware: Union[Hardware, None] = None, deck_position: int = 0, leave_even_rows_empty: bool = True, timeout: float = 600):
        """
        Constructor for the SixPisitionStirrerDCMotors Class for communication with an Arduino controlling a stir plate for two flasks (based on DVD spindle motors).

        Parameters
        ----------
        arduino_controller : ArduinoController
            The Arduino controller hardware.
        hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
            Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
        parent_hardware : Union[Hardware, None] = None
            Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
        deck_position : int, default = 0
            The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
        leave_even_rows_empty : bool, default = True
            If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.ClampHardware)
        self._stirrer_number = 1
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self._parent_hardware = parent_hardware
        self.read_queue = self.arduino_controller.get_read_queue(f'STIRRER{self._stirrer_number}')
        self._logger_dict = {'instance_name': str(self)}

    def set_stirring_speed_setpoint(self, value: float, position: int, log: bool = True) -> bool:
        """
        Set the stirring speed setpoint (in percent).

        Parameters
        ----------
        value: float
            The stirring speed setpoint (in percent).
        position: int
            The position of the stirrer (1-2).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if self.EMERGENCY_STOP_REQUEST:
            return False

        value = min(max(value, 0), 100)
        self.arduino_controller.write(f's{self._stirrer_number}p{position} setsp {value}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r.endswith('OK'):
            if log:
                logger.info(f'Stirring speed setpoint of stirrer position {position} changed to: {value} percent', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def read_stirring_speed_setpoint(self, position: int, log: bool = True) -> float:
        """
        Get the stirring speed setpoint (in percent).

        Parameters
        ----------
        position: int
            The position of the stirrer (1-2).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The stirring speed setpoint (in percent).
        """
        if self.EMERGENCY_STOP_REQUEST:
            return -1

        self.arduino_controller.write(f's{self._stirrer_number}p{position} getsp\n')
        r = self.read_queue.get(timeout=self.timeout)
        if ' SETPOINT: ' in r:
            value = float(r.replace('\r', '').replace('\n', '').split(" SETPOINT: ")[-1])
            if log:
                logger.info(f'Stirring speed setpoint of stirrer position {position} is: {value} percent', extra=self._logger_dict)
            return value
        else:
            logger.error(r, extra=self._logger_dict)
            return -1

    def read_stirring_speed_in_rpm(self, position: int, log: bool = True) -> float:
        """
        Get the current stirring speed of the stirrer in rpm.

        Parameters
        ----------
        position: int
            The position of the stirrer (1-2).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The current stirring speed of the stirrer in rpm.
        """
        if self.EMERGENCY_STOP_REQUEST:
            return -1

        self.arduino_controller.write(f's{self._stirrer_number}p{position} getcurrentspeed\n')
        r = self.read_queue.get(timeout=self.timeout)
        if ' CURRENT SPEED (RPM): ' in r:
            value = float(r.replace('\r', '').replace('\n', '').split(" CURRENT SPEED (RPM): ")[-1])
            if log:
                logger.info(f'Current stirring speed of stirrer position {position} is: {value} rpm', extra=self._logger_dict)
            return value
        else:
            logger.error(r, extra=self._logger_dict)
            return -1

    def read_hall_sensor_parameters(self, position: int, log: bool = True) -> tuple[float, float]:
        """
        Get the hall sensor parameters of the stirrer.

        Parameters
        ----------
        position: int
            The position of the stirrer (1-2).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        tuple[float, float]
            The offset and threshold values of the hall sensor.
        """
        if self.EMERGENCY_STOP_REQUEST:
            return (-1, -1)

        self.arduino_controller.write(f's{self._stirrer_number}p{position} gethallparams\n')
        r = self.read_queue.get(timeout=self.timeout)
        if f'POSITION {position} HALL SENSOR PARAMETERS: OFFSET - ' in r:
            r = r.replace('\r', '').replace('\n', '').replace(' THRESHOLD - ', '').split(f"POSITION {position} HALL SENSOR PARAMETERS: OFFSET - ")
            if log:
                logger.info(f'Hall sensor parameters of stirrer position {position} are: Offset - {float(r[0])}; Threshold - {float(r[1])}', extra=self._logger_dict)
            return (float(r[0]), float(r[1]))
        else:
            logger.error(r, extra=self._logger_dict)
            return (-1, -1)

    def initialize_hall_sensor(self, position: int, log: bool = True) -> tuple[float, float]:
        """
        Re-initialize the hall sensor of the stirrer.

        Parameters
        ----------
        position: int
            The position of the stirrer (1-2).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        tuple[float, float]
            The offset and threshold values of the hall sensor.
        """
        if self.EMERGENCY_STOP_REQUEST:
            return (-1, -1)

        self.arduino_controller.write(f's{self._stirrer_number}p{position} ini\n')
        r = self.read_queue.get(timeout=self.timeout)
        if f'POSITION {position} HALL SENSOR PARAMETERS: OFFSET - ' in r:
            r = r.replace('\r', '').replace('\n', '').replace(' THRESHOLD - ', '').split(f"POSITION {position} HALL SENSOR PARAMETERS: OFFSET - ")
            if log:
                logger.info(f'Hall sensor initialized. Parameters of stirrer position {position} are: Offset - {float(r[0])}; Threshold - {float(r[1])}', extra=self._logger_dict)
            return (float(r[0]), float(r[1]))
        else:
            logger.error(r, extra=self._logger_dict)
            return (-1, -1)



class SixPositionStirrerFans(SampleHolder):
    """
    Class for communication with an Arduino controlling a stir plate for six flasks (based on CPU fans as DC motors).

    Parameters
    ----------
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
        Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
    parent_hardware : Union[Hardware, None] = None
        Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
    deck_position : int, default = 0
        The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
    leave_even_rows_empty : bool, default = True
        If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, hardware_definition: Union[SampleHolderDefinitions, str, Dict[str, Any]], parent_hardware: Union[Hardware, None] = None, deck_position: int = 0, leave_even_rows_empty: bool = True, timeout: float = 600):
        """
        Constructor for the SixPisitionStirrerFans Class for communication with an Arduino controlling a stir plate for six flasks (based on CPU fans as DC motors).

        Parameters
        ----------
        arduino_controller : ArduinoController
            The Arduino controller hardware.
        hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
            Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
        parent_hardware : Union[Hardware, None] = None
            Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
        deck_position : int, default = 0
            The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
        leave_even_rows_empty : bool, default = True
            If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.ClampHardware)
        self._stirrer_number = 2
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self._parent_hardware = parent_hardware
        self.read_queue = self.arduino_controller.get_read_queue(f'STIRRER{self._stirrer_number}')
        self._logger_dict = {'instance_name': str(self)}

    def set_stirring_speed_setpoint(self, value: float, position: int, log: bool = True) -> bool:
        """
        Set the stirring speed setpoint (in percent).

        Parameters
        ----------
        value: float
            The stirring speed setpoint (in percent).
        position: int
            The position of the stirrer (1-6).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if self.EMERGENCY_STOP_REQUEST:
            return False

        value = min(max(value, 0), 100)
        self.arduino_controller.write(f's{self._stirrer_number}p{position} setsp {value}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r.endswith('OK'):
            if log:
                logger.info(f'Stirring speed setpoint of stirrer position {position} changed to: {value} percent', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def read_stirring_speed_setpoint(self, position: int, log: bool = True) -> float:
        """
        Get the stirring speed setpoint (in percent).

        Parameters
        ----------
        position: int
            The position of the stirrer (1-6).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The stirring speed setpoint (in percent).
        """
        if self.EMERGENCY_STOP_REQUEST:
            return -1

        self.arduino_controller.write(f's{self._stirrer_number}p{position} getsp\n')
        r = self.read_queue.get(timeout=self.timeout)
        if ' SETPOINT: ' in r:
            value = float(r.replace('\r', '').replace('\n', '').split(" SETPOINT: ")[-1])
            if log:
                logger.info(f'Stirring speed setpoint of stirrer position {position} is: {value} percent', extra=self._logger_dict)
            return value
        else:
            logger.error(r, extra=self._logger_dict)
            return -1

    def read_stirring_speed_in_rpm(self, log: bool = True) -> float:
        """
        Get the current stirring speed of the stirrer in position 1 in rpm (currently, only position 1 has a hall sensor).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The current stirring speed of the stirrer in position 1 in rpm.
        """
        if self.EMERGENCY_STOP_REQUEST:
            return -1

        self.arduino_controller.write(f's{self._stirrer_number}p1 getcurrentspeed\n')
        r = self.read_queue.get(timeout=self.timeout)
        if ' CURRENT SPEED (RPM): ' in r:
            value = float(r.replace('\r', '').replace('\n', '').split(" CURRENT SPEED (RPM): ")[-1])
            if log:
                logger.info(f'Current stirring speed of stirrer position 1 is: {value} rpm', extra=self._logger_dict)
            return value
        else:
            logger.error(r, extra=self._logger_dict)
            return -1

    def read_hall_sensor_parameters(self, log: bool = True) -> tuple[float, float]:
        """
        Get the hall sensor parameters of the stirrer in position 1 (currently, only position 1 has a hall sensor).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        tuple[float, float]
            The offset and threshold values of the hall sensor.
        """
        if self.EMERGENCY_STOP_REQUEST:
            return (-1, -1)

        self.arduino_controller.write(f's{self._stirrer_number}p1 gethallparams\n')
        r = r.replace('\r', '').replace('\n', '').replace(' THRESHOLD - ', '').split(f"POSITION 1 HALL SENSOR PARAMETERS: OFFSET - ")
        if 'POSITION 1 HALL SENSOR PARAMETERS: OFFSET - ' in r:
            value = r.split("POSITION 1 HALL SENSOR PARAMETERS: OFFSET - ")[-1].replace('\r', '').replace('\n', '').replace(' THRESHOLD - ', '')
            if log:
                logger.info(f'Hall sensor parameters of stirrer position 1 are: Offset - {float(r[0])}; Threshold - {float(r[1])}', extra=self._logger_dict)
            return (float(r[0]), float(r[1]))
        else:
            logger.error(r, extra=self._logger_dict)
            return (-1, -1)

    def initialize_hall_sensor(self, log: bool = True) -> tuple[float, float]:
        """
        Re-initialize the hall sensor of the stirrer in position 1 (currently, only position 1 has a hall sensor).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        tuple[float, float]
            The offset and threshold values of the hall sensor.
        """
        if self.EMERGENCY_STOP_REQUEST:
            return (-1, -1)
        self.arduino_controller.write(f's{self._stirrer_number}p1 ini\n')
        r = self.read_queue.get(timeout=self.timeout)
        if 'POSITION 1 HALL SENSOR PARAMETERS: OFFSET - ' in r:
            r = r.replace('\r', '').replace('\n', '').replace(' THRESHOLD - ', '').split(f"POSITION 1 HALL SENSOR PARAMETERS: OFFSET - ")
            if log:
                logger.info(f'Hall sensor initialized. Parameters of stirrer position 1 are: Offset - {float(r[0])}; Threshold - {float(r[1])}', extra=self._logger_dict)
            return (float(r[0]), float(r[1]))
        else:
            logger.error(r, extra=self._logger_dict)
            return (-1, -1)


class SixPositionStirrerCoils(SampleHolder):
    """
    Class for communication with an Arduino controlling a stir plate for six flasks (based on magnetic coils).

    Parameters
    ----------
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
        Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
    parent_hardware : Union[Hardware, None] = None
        Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
    deck_position : int, default = 0
        The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
    leave_even_rows_empty : bool, default = True
        If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, hardware_definition: Union[SampleHolderDefinitions, str, Dict[str, Any]], parent_hardware: Union[Hardware, None] = None, deck_position: int = 0, leave_even_rows_empty: bool = True, timeout: float = 600):
        """
        Constructor for the SixPisitionStirrerCoils Class for communication with an Arduino controlling a stir plate for six flasks (based on magnetic coils).

        Parameters
        ----------
        arduino_controller : ArduinoController
            The Arduino controller hardware.
        hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
            Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
        parent_hardware : Union[Hardware, None] = None
            Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
        deck_position : int, default = 0
            The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
        leave_even_rows_empty : bool, default = True
            If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.ClampHardware)
        self._stirrer_number = 3
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self._parent_hardware = parent_hardware
        self.read_queue = self.arduino_controller.get_read_queue(f'STIRRER{self._stirrer_number}')
        self._logger_dict = {'instance_name': str(self)}

    def set_stirring_speed_setpoint(self, value: float, log: bool = True) -> bool:
        """
        Set the stirring speed setpoint for all six positions (in rpm).

        Parameters
        ----------
        value: float
            The stirring speed setpoint (in rpm).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if self.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f's{self._stirrer_number}p1 setsp {value}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r.endswith('OK'):
            if log:
                logger.info(f'Stirring speed setpoint changed to: {value} rpm', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def read_stirring_speed_setpoint(self, log: bool = True) -> float:
        """
        Get the stirring speed setpoint for all six positions (in rpm).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The stirring speed setpoint (in rpm).
        """
        if self.EMERGENCY_STOP_REQUEST:
            return -1

        self.arduino_controller.write(f's{self._stirrer_number}p1 getsp\n')
        r = self.read_queue.get(timeout=self.timeout)
        if ' SETPOINT: ' in r:
            value = float(r.replace('\r', '').replace('\n', '').split(" SETPOINT: ")[-1])
            if log:
                logger.info(f'Stirring speed setpoint is: {value} rpm', extra=self._logger_dict)
            return value
        else:
            logger.error(r, extra=self._logger_dict)
            return -1
