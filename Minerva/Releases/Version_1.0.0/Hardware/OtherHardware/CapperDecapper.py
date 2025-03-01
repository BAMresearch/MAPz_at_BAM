#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import time

import logging
import os.path

from typing import Union, Iterable, TYPE_CHECKING, List, Tuple, cast

from Minerva.API import MinervaAPI
from Minerva.API.HelperClassDefinitions import Hardware, PathsToHardwareCollection, TaskScheduler, TaskGroupSynchronizationObject, HardwareTypeDefinitions, PathNames
from Minerva.Hardware.RobotArms import UFactory
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


class CapperDecapper(Hardware):
    """
    Class for communication with an Arduino controlling the capper/decapper.

    Parameters
    ----------
    arduino_controller: ArduinoController
        The Arduino controller hardware.
    timeout : float, default=600
        The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
    """
    EMERGENCY_STOP_REQUEST = False
    BRACKET_WIDTH = 23  

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, timeout: float = 600):
        """
        Constructor for the CapperDecapper Class for communication with the Arduino controlling the capper/decapper.

        Parameters
        ----------
        arduino_controller: ArduinoController.ArduinoController
            The Arduino controller hardware.
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.CapperDecapperHardware)
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self.read_queue = self.arduino_controller.get_read_queue(f'CAPPER')
        self.approach_speed = 10
        self.clamp_height = 25
        self._logger_dict = {'instance_name': str(self)}

    def read_pressure_sensor(self, averages: int = 64, log_results: bool = True) -> int:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write('capper pressure\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r[-1] == 'OK':
            logger.info(f'Pressure Signal: {r[0]}', extra=self._logger_dict)
            return int(r[0])
        else:
            logger.error(r[-1], extra=self._logger_dict)
            return -1

    def read_current_sensor_dc_motor(self, averages: int = 8, log_results: bool = True, log_all: bool = False) -> Union[float, List[str], None]:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        if log_all:
            self.arduino_controller.write(f'capper motor_current all\n')
            r = self.read_queue.get(timeout=self.timeout)
            if r[-1] == 'OK':
                logger.info('\n'.join(r[:-1]), extra=self._logger_dict)
                return float(r[0].split(' ')[-1])
            else:
                logger.error(r[-1], extra=self._logger_dict)
                return []
        else:
            self.arduino_controller.write('capper motor_current\n')
            r = self.read_queue.get(timeout=self.timeout)
            if r[-1] == 'OK':
                if log_results:
                    logger.info(f'DC Motor Current [mA]: {r[0]}', extra=self._logger_dict)
                return float(r[0])
            else:
                logger.error(r[-1], extra=self._logger_dict)
                return None

    def read_current_sensor_servo_motor(self, averages: int = 8, log_results: bool = True, log_all: bool = False) -> Union[float, List[str], None]:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        if log_all:
            self.arduino_controller.write(f'capper servo_current all\n')
            r = self.read_queue.get(timeout=self.timeout)
            if r[-1] == 'OK':
                logger.info('\n'.join(r[:-1]), extra=self._logger_dict)
                return float(r[0].split(' ')[-1])
            else:
                logger.error(r[-1], extra=self._logger_dict)
                return []
        else:
            self.arduino_controller.write('capper servo_current\n')
            r = self.read_queue.get(timeout=self.timeout)
            if r[-1] == 'OK':
                logger.info(f'Servo Motor Current [mA]: {r[0]}', extra=self._logger_dict)
                return float(r[0])
            else:
                logger.error(r[-1], extra=self._logger_dict)
                return None

    def turn_wrist_clockwise(self) -> bool:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write('capper turn_cw\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Wrist turning clockwise', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def turn_wrist_counterclockwise(self) -> bool:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write('capper turn_ccw\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Wrist turning counterclockwise', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def wrist_stop(self) -> bool:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write('capper turn_stop\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Stopped turning wrist', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def set_clamp_position(self, position_in_mm: int) -> bool:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'capper clamp_set_position {position_in_mm}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp position set to {position_in_mm} mm.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def get_clamp_position(self) -> int:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write('capper clamp_get_position\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r[-1] == 'OK':
            logger.info(f'Clamp position is {r[0]} mm', extra=self._logger_dict)
            return int(r[0])
        else:
            logger.error(r[-1], extra=self._logger_dict)
            return -1

    def open_clamp(self, current_threshold_in_ma: float = 1200.0) -> bool:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'capper clamp_open {current_threshold_in_ma}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp opened.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def close_clamp(self, current_threshold_in_ma: float = 350.0) -> bool:
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'capper clamp_close {current_threshold_in_ma}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Clamp closed.', extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    @TaskScheduler.scheduled_task
    def open_container(self, robot_arm: UFactory.XArm6, current_threshold_in_ma: float = 400.0, z_offset: int = 0, opening_time: float = 2.0, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Method for unscrewing the lid of a container.

        Parameters
        ----------
        robot_arm: UFactory.XArm6
            The robot arm that is holding the container for uncapping
        current_threshold_in_ma: float = 400
            The current threshold in milliamps that determines the grip strength of the clamp. Default is 400.
        z_offset: int = 20
            Additional z_offset to be applied. Default is 0.
        opening_time: float = 2.0
            Time in seconds during which the wrist will be turned to open the container. Default is 2.
        block: bool = TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_blocking_behavior
        priority: int = TaskScheduler.default_priority
            Priority of this task (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_priority
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
            True if successful, false otherwise
        """

        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        logger.info(f'Opening Container...', extra=self._logger_dict)

        if not self.open_clamp():
            return False

        start_pos = robot_arm.arm.position
        start_zpos = start_pos[2]
        z_pos = start_zpos + CapperDecapper.BRACKET_WIDTH + z_offset
        robot_arm.arm.set_position(*[start_pos[i] if i != 2 else z_pos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument

        if not self.close_clamp(current_threshold_in_ma):
            self.open_clamp()
            robot_arm.arm.set_position(*[start_pos[i] if i != 2 else start_zpos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            return False
        if not self.turn_wrist_counterclockwise():
            self.open_clamp()
            time.sleep(5)
            robot_arm.arm.set_position(*[start_pos[i] if i != 2 else start_zpos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            return False
        time.sleep(opening_time)

        if not self.wrist_stop():
            self.open_clamp()
            time.sleep(5)
            robot_arm.arm.set_position(*[start_pos[i] if i != 2 else start_zpos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            return False

        err_warn_code = robot_arm.arm.get_err_warn_code()
        if err_warn_code != (0, [0, 0]):
            if err_warn_code == (0, [31, 0]):  # (0, [31, 0]) means abnormal current, probably due to collision:
                logger.critical('Collision detected. Emergency stop requested.', extra=self._logger_dict)
                MinervaAPI.Configuration.request_emergency_stop()
            return False

        return True

    @TaskScheduler.scheduled_task
    def close_container(self, robot_arm: UFactory.XArm6, current_threshold_in_ma: float = 300.0, z_offset: int = 6, block: bool = TaskScheduler.default_blocking_behavior, priority: int = TaskScheduler.default_priority, is_sequential_task: bool = True, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Method for closing the lid of a container.

        Parameters
        ----------
        robot_arm: UFactory.XArm6
            The robot arm that is holding the container for uncapping
        current_threshold_in_ma: float = 300
            The current threshold in milliamps that determines the torque of the wrist when closing the lid. Default is 300.
        z_offset: int = 6
            Additional z_offset to be applied to ensure there is some pressure on the lid. Default is 6.
        block: bool = TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_blocking_behavior
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = TaskScheduler.default_priority
            Priority of this task (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_priority
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
            True if successful, false otherwise
        """
        if CapperDecapper.EMERGENCY_STOP_REQUEST:
            return False

        logger.info(f'Closing Container...', extra=self._logger_dict)

        start_pos = robot_arm.arm.position
        start_zpos = start_pos[2]
        z_pos = start_zpos + CapperDecapper.BRACKET_WIDTH + z_offset
        if not self.turn_wrist_clockwise():
            return False
        robot_arm.arm.set_position(*[start_pos[i] if i != 2 else z_pos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument

        time.sleep(0.5)
        current_dc_motor_current = cast(float, self.read_current_sensor_dc_motor())
        start_time = time.time()
        timeout = 2.5

        while abs(current_dc_motor_current) < abs(current_threshold_in_ma) and time.time() - start_time < timeout:
            current_dc_motor_current = cast(float, self.read_current_sensor_dc_motor())
            if current_dc_motor_current is None:
                self.wrist_stop()
                self.open_clamp()
                time.sleep(5)
                robot_arm.arm.set_position(*[start_pos[i] if i != 2 else start_zpos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
                return False

        if not self.wrist_stop():
            self.open_clamp()
            time.sleep(5)
            robot_arm.arm.set_position(*[start_pos[i] if i != 2 else start_zpos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            return False

        if not self.open_clamp():
            robot_arm.arm.set_position(*[start_pos[i] if i != 2 else start_zpos for i in range(0, len(start_pos))], speed=self.approach_speed, wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            return False

        err_warn_code = robot_arm.arm.get_err_warn_code()
        if err_warn_code != (0, [0, 0]):
            if err_warn_code == (0, [31, 0]):  # (0, [31, 0]) means abnormal current, probably due to collision:
                logger.critical('Collision detected. Emergency stop requested.', extra=self._logger_dict)
                MinervaAPI.Configuration.request_emergency_stop()
            return False
        return True

    # def open_container_pressure_threshold(self, robot_arm: UFactory.XArm6, current_threshold_in_ma: float = 400.0, pressure_threshold: int = 400) -> bool:   #pressure threshold500
    #     if CapperDecapper.EMERGENCY_STOP_REQUEST:
    #         return False
    #
    #     logger.info(f'Opening Container...', extra=self._logger_dict)
    #     z_inc = 3
    #
    #     if not self.open_clamp():
    #         return False
    #
    #     current_pressure = self.read_pressure_sensor()
    #     if current_pressure == -1:
    #         return False
    #     start_zpos = robot_arm.arm.position[2]
    #     z_pos = start_zpos  # + self.clamp_height
    #     # robot_arm.arm.set_position(z=z_pos, speed=self.approach_speed, wait=True)
    #
    #     start_time = time.time()
    #     timeout = 10
    #
    #     while current_pressure < pressure_threshold and time.time() - start_time < timeout and z_pos < start_zpos + PathsToHardwareCollection.CAPPER_MAX_HEIGHT - PathsToHardwareCollection.CAPPER_BASE_HEIGHT:
    #         z_pos += z_inc
    #         robot_arm.arm.set_position(z=z_pos, speed=self.approach_speed, wait=True)
    #         current_pressure = self.read_pressure_sensor()
    #         if current_pressure == -1:
    #             robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #             return False
    #
    #     if not self.close_clamp(current_threshold_in_ma):
    #         self.open_clamp()
    #         robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #         return False
    #     if not self.turn_wrist_counterclockwise():
    #         self.open_clamp()
    #         time.sleep(5)
    #         robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #         return False
    #     time.sleep(0.5)
    #     current_pressure = self.read_pressure_sensor()
    #     pressure_threshold = current_pressure
    #     timeout = 3
    #     start_time = time.time()
    #
    #     while current_pressure > 0.97 * pressure_threshold and time.time() - start_time < timeout:
    #         current_pressure = self.read_pressure_sensor()
    #         if current_pressure == -1:
    #             self.wrist_stop()
    #             self.open_clamp()
    #             time.sleep(5)
    #             robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #             return False
    #
    #     robot_arm.arm.set_position(z=start_zpos-25, speed=self.approach_speed, wait=True)
    #
    #     if not self.wrist_stop():
    #         self.open_clamp()
    #         time.sleep(5)
    #         robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #         return False
    #
    #     return True

    # def close_container_pressure_threshold(self, robot_arm: UFactory.XArm6, current_threshold_in_ma: float = 300.0, pressure_threshold: int = 450) -> bool:  #pressure 900, current 150.0
    #     if CapperDecapper.EMERGENCY_STOP_REQUEST:
    #         return False
    #
    #     logger.info(f'Closing Container...', extra=self._logger_dict)
    #     z_inc = 3
    #
    #     current_pressure = self.read_pressure_sensor()
    #     start_zpos = robot_arm.arm.position[2]
    #     z_pos = start_zpos  # + self.clamp_height
    #     # robot_arm.arm.set_position(z=z_pos, speed=self.approach_speed, wait=True)
    #
    #     start_time = time.time()
    #     timeout = 10
    #
    #     while current_pressure < pressure_threshold and time.time() - start_time < timeout and z_pos < start_zpos + PathsToHardwareCollection.CAPPER_MAX_HEIGHT - PathsToHardwareCollection.CAPPER_BASE_HEIGHT:
    #         z_pos += z_inc
    #         robot_arm.arm.set_position(z=z_pos, speed=self.approach_speed, wait=True)
    #         current_pressure = self.read_pressure_sensor()
    #         if current_pressure == -1:
    #             robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #             return False
    #
    #     if not self.turn_wrist_clockwise():
    #         robot_arm.arm.set_position(z=start_zpos, wait=True)
    #         return False
    #     time.sleep(0.5)
    #     current_dc_motor_current = cast(float, self.read_current_sensor_dc_motor())
    #     start_time = time.time()
    #     timeout = 2.5
    #
    #     while abs(current_dc_motor_current) < abs(current_threshold_in_ma) and time.time() - start_time < timeout:
    #         current_dc_motor_current = cast(float, self.read_current_sensor_dc_motor())
    #         if current_dc_motor_current is None:
    #             self.wrist_stop()
    #             self.open_clamp()
    #             time.sleep(5)
    #             robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #             return False
    #
    #     if not self.wrist_stop():
    #         self.open_clamp()
    #         time.sleep(5)
    #         robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #         return False
    #
    #     if not self.open_clamp():
    #         robot_arm.arm.set_position(z=start_zpos, speed=self.approach_speed, wait=True)
    #         return False
    #
    #     robot_arm.arm.set_position(z=start_zpos-25, speed=self.approach_speed, wait=True)
    #     return True
    #


"""
  void CapperDecapper::logSensorSignals(unsigned long timeout=5000, bool logResults=true);
  bool CapperDecapper::openContainer(int pos=31, int pThreshold=100, int timeout=10000);
  bool CapperDecapper::closeContainer(int pThreshold=1000, float iThreshold=200.0, int timeout=10000);
"""

"""
Communication: 9600 8 N 1

Send commands values in [] are optional:
<COMMAND>[ ][VALUE][CHR(13)]<CHR(10)>
Answer:
OK<CHR(13)><CHR(10)>                          - If command was executed successfully
UNK<CHR(13)><CHR(10)>                         - Unknown Command
ERR <byte>: <errormessage><CHR(13)><CHR(10)>  - If an error occured while executing the command
<String><CHR(13)><CHR(10)>                    - String containing the answer to a query

"""
