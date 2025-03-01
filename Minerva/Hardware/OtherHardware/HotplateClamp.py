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

from typing import Optional, Union

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


class HotplateClampDCMotor(Hardware):
    """
    Class for communication with an Arduino controlling the hotplate clamp/stage, where the stage is connected to a DC Motor.

    Parameters
    ----------
    parent_hardware : HotplateHardware
        Field specifying the hotplate hardware where this clamp is located.
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    clamp_number : int, default=1
        The number of the hotplate clamp. Default is 1.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, parent_hardware: HotplateHardware, arduino_controller: ArduinoController.ArduinoController, timeout: float = 600, clamp_number: int = 1):
        """
        Constructor for the HotplateClamp Class for communication with the Arduino controlling the hotplate clamp/stage, where the stage is connected to a DC Motor.

        Parameters
        ----------
        parent_hardware : HotplateHardware
            Field specifying the hotplate hardware where this clamp is located.
        arduino_controller : ArduinoController.ArduinoController
        The Arduino controller hardware.
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        clamp_number : int, default=1
            The number of the hotplate clamp. Default is 1.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.ClampHardware)
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self.clamp_number = clamp_number
        self._parent_hardware = parent_hardware
        self.read_queue = self.arduino_controller.get_read_queue(f'CLAMP{self.clamp_number}')
        self._logger_dict = {'instance_name': str(self)}
        self.is_in_home_position = self.move_up()

    def move_up(self, current_threshold: Optional[Union[float, str]] = None) -> bool:
        """
        Method for moving the clamp up until it reaches the current threshold (if provided) or hits the limit switch (if no threshold is provided).

        Parameters:
        -----------
        current_threshold : Optional[float] = None
            Stop movement when the current draw of the motor exceeds this value (in milliampere). If set to None, the stage will go up until it reaches the limit switch. Default is None.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampDCMotor.EMERGENCY_STOP_REQUEST:
            return False

        if current_threshold is None:
            current_threshold = ''
        self.arduino_controller.write(f'Clamp{self.clamp_number} up {current_threshold}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp{self.clamp_number} moved up.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def move_down(self, current_threshold: Optional[Union[float, str]] = None) -> bool:
        """
        Method for moving the clamp down until it reaches the current threshold (if provided) or hits the limit switch (if no threshold is provided).

        Parameters:
        -----------
        current_threshold : Optional[float] = None
            Stop movement when the current draw of the motor exceeds this value (in milliampere). If set to None, the stage will go down until it reaches the limit switch. Default is None.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampDCMotor.EMERGENCY_STOP_REQUEST:
            return False

        if current_threshold is None:
            current_threshold = ''
        self.arduino_controller.write(f'Clamp{self.clamp_number} down {current_threshold}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp{self.clamp_number} moved down.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def open_clamp(self, angle: Optional[int] = None) -> bool:
        """
        Method for opening the clamp (up to the specified servo angle in degrees, or all the way if set to None).

        Parameters:
        -----------
        angle : Optional[int] = None
            Servo angle in degrees. If set to None, open the clamp all the way.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampDCMotor.EMERGENCY_STOP_REQUEST:
            return False

        if angle is None:
            self.arduino_controller.write(f'Clamp{self.clamp_number} open\n')
        else:
            self.arduino_controller.write(f'Clamp{self.clamp_number} open {angle}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            if angle is None:
                logger.info(f'Clamp{self.clamp_number} opened.', extra=self._logger_dict)
            else:
                logger.info(f'Clamp{self.clamp_number} servo set to {angle} degrees.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def close_clamp(self, angle: Optional[int] = None) -> bool:
        """
        Method for closing the clamp (up to the specified servo angle in degrees, or all the way if set to None).

        Parameters:
        -----------
        angle : Optional[int] = None
            Servo angle in degrees. If set to None, close the clamp all the way.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampDCMotor.EMERGENCY_STOP_REQUEST:
            return False

        if angle is None:
            self.arduino_controller.write(f'Clamp{self.clamp_number} close\n')
        else:
            self.arduino_controller.write(f'Clamp{self.clamp_number} close {angle}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            if angle is None:
                logger.info(f'Clamp{self.clamp_number} closed.', extra=self._logger_dict)
            else:
                logger.info(f'Clamp{self.clamp_number} servo set to {angle} degrees.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False


class HotplateClampStepperMotor(Hardware):
    """
    Class for communication with an Arduino controlling the hotplate clamp/stage, where the stage is connected to a Stepper Motor.

    parent_hardware : HotplateHardware
        Field specifying the hotplate hardware where this clamp is located.
    arduino_controller : ArduinoController
        The Arduino controller hardware.
    timeout : float, default=5
        The timeout when waiting for a response in seconds. Default is 5.
    clamp_number : int, default=1
        The number of the hotplate clamp. Default is 1.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, parent_hardware: HotplateHardware, arduino_controller: ArduinoController.ArduinoController, timeout: float = 5, clamp_number: int = 1):
        """
        Constructor for the HotplateClamp Class for communication with the Arduino controlling the hotplate clamp/stage, where the stage is connected to a Stepper Motor.

        Parameters
        ----------
        parent_hardware : HotplateHardware
            Field specifying the hotplate hardware where this clamp is located.
        arduino_controller : ArduinoController.ArduinoController
            The Arduino controller hardware.
        timeout : float, default=5
            The timeout when waiting for a response in seconds. Default is 5.
        clamp_number : int, default=1
            The number of the hotplate clamp. Default is 1.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.ClampHardware)
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self.clamp_number = clamp_number
        self._parent_hardware = parent_hardware
        self.read_queue = self.arduino_controller.get_read_queue(f'CLAMP{self.clamp_number}')
        self._logger_dict = {'instance_name': str(self)}

    def home_position(self) -> bool:
        """
        Method for homing the stepper motor of the hotplate stage (will return it to the bottom-most position).

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampStepperMotor.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'Clamp{self.clamp_number} homePosition\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r[-1] == 'OK':
            logger.info(f'Clamp{self.clamp_number} returned to home position. Current Position set to 0.', extra=self._logger_dict)
            self.current_position = 0
            return True
        else:
            logger.error(r[-1], extra=self._logger_dict)
            return False

    def get_position(self) -> int:
        """
        Method for querying the current height of the clamp in millimeters above the home position.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampStepperMotor.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'Clamp{self.clamp_number} pos\n')
        r = self.read_queue.get(timeout=self.timeout)
        pos = int(r.split(' '))
        if pos == self.current_position:
            logger.info(f'Clamp{self.clamp_number} is currently at {pos} mm above the home position.', extra=self._logger_dict)
            return pos
        else:
            logger.error(r, extra=self._logger_dict)
            logger.error('Inconsistent clamp position. Please home the motor and try again.', extra=self._logger_dict)
            return False

    def update_position(self, position: int) -> bool:
        """
        Method for setting the current height of the clamp in millimeters above the home position WITHOUT moving the clamp.

        Parameters:
        -----------
        position : int
            Current height of the clamp in millimeters above the home position

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampStepperMotor.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'Clamp{self.clamp_number} pos {self.current_position}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp{self.clamp_number} position set to {position} mm above the home position.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def goto_position(self, position: int) -> bool:
        """
        Method for moving the clamp to the specified position in millimeters above the home position.

        Parameters:
        -----------
        position : int
            Height of the clamp in millimeters above the home position

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampStepperMotor.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'Clamp{self.clamp_number} gotoPosition {position}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp{self.clamp_number} moved to {position} mm above the home position.', extra=self._logger_dict)
            self.current_position = position
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def open_clamp(self, angle: Optional[int] = None) -> bool:
        """
        Method for opening the clamp (up to the specified servo angle in degrees, or all the way if set to None).

        Parameters:
        -----------
        angle : Optional[int] = None
            Servo angle in degrees. If set to None, open the clamp all the way.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampStepperMotor.EMERGENCY_STOP_REQUEST:
            return False

        if angle is None:
            self.arduino_controller.write(f'Clamp{self.clamp_number} open\n')
        else:
            self.arduino_controller.write(f'Clamp{self.clamp_number} open {angle}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            if angle is None:
                logger.info(f'Clamp{self.clamp_number} opened.', extra=self._logger_dict)
            else:
                logger.info(f'Clamp{self.clamp_number} servo set to {angle} degrees.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def close_clamp(self, angle: Optional[int] = None) -> bool:
        """
        Method for closing the clamp (up to the specified servo angle in degrees, or all the way if set to None).

        Parameters:
        -----------
        angle : Optional[int] = None
            Servo angle in degrees. If set to None, close the clamp all the way.

        Returns
        ------
        bool
            True if successful, False otherwise
        """
        if HotplateClampStepperMotor.EMERGENCY_STOP_REQUEST:
            return False

        if angle is None:
            self.arduino_controller.write(f'Clamp{self.clamp_number} close\n')
        else:
            self.arduino_controller.write(f'Clamp{self.clamp_number} close {angle}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            if angle is None:
                logger.info(f'Clamp{self.clamp_number} closed.', extra=self._logger_dict)
            else:
                logger.info(f'Clamp{self.clamp_number} servo set to {angle} degrees.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False
