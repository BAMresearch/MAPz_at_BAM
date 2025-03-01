#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import math
import threading
import time
import serial
import logging
import os.path
from typing import Union

from Minerva.API.HelperClassDefinitions import CentrifugeHardware, RotorInfo, TaskScheduler, TaskGroupSynchronizationObject, PathNames

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


class RobotCen(CentrifugeHardware):
    """
    Class for communication with the Herolab RobotCen.

    Parameters
    ----------
    com_port : str
        The COM Port the centrifuge is connected to.

    Raises
    ------
    TimeoutError
        If the RobotCen is not responding to a query of its Version Number within 1 s.
    """
    EMERGENCY_STOP_REQUEST: bool = False
    STEPS_PER_REVOLUTION: int = 25600

    def __init__(self, com_port: str, initialize_rotor: bool = True, home_rotor: bool = True):
        """
        Constructor for the RobotCen Class for communication with the Herolab RobotCen.

        Parameters
        ----------
        com_port : str
            The COM Port the centrifuge is connected to.

        Raises
        ------
        TimeoutError
            If the RobotCen is not responding to a query of its Version Number within the timeout.
        AssertionError
            If the initialization produces unexpected results
        """
        super().__init__()
        self.rotor_info: RotorInfo
        self.initialize_rotor = initialize_rotor
        self.home_rotor = home_rotor
        self.eol = b'\r\n'
        self.eol2 = b'\r\n\r\n'
        self.com_port = str(com_port).upper()
        self.baud_rate = 9600
        self.parity = serial.PARITY_NONE
        self.byte_size = 8
        self.stop_bit = 1
        self.timeout = 15
        self.retries = 3
        self.retries_connect = 3
        self._com_port_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.com_port = 'COM' + self.com_port

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)

        i = 0
        for i in range(0, self.retries_connect):
            try:
                with self._com_port_lock:
                    self.ser.write('AEX P11\n'.encode())
                    r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
                if 'ER 0' in r:
                    logger.info(f'Connected to RobotCen on {self.com_port}.', extra=self._logger_dict)
                    break
            except TimeoutError:
                logging.warning(f'Timed out while connecting to centrifuge. Retrying... ({i}/{self.retries_connect})')
                continue  # try again (maximum self.retries times)

        if i == self.retries_connect-1:
            logger.critical(f'RobotCen not responding on port {self.com_port}.', extra=self._logger_dict)
            self.ser.close()
            raise TimeoutError(f'RobotCen not responding on port {self.com_port}.')

        if initialize_rotor:
            self.rotor_info = RotorInfo.from_string(self.enable_and_get_rotor_id(), RobotCen.STEPS_PER_REVOLUTION)
        else:
            self.rotor_info = RotorInfo('ROT', 7, 4, 2, 2, 1, 'AF 8.50.3', 8, 13500, 1100, True, 3200, 104)

        if home_rotor:
            assert self.rotor_homing(), 'Error homing rotor'
        else:
            assert self.set_position_absolute2(5) > -1, 'Error setting rotor position'
            self.current_slot = 5

        logger.info('Rotor successfully initialized.', extra=self._logger_dict)

    def rotor_homing(self, log: bool = True) -> bool:
        """
        Returns the rotor to its home position

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True when successful, False otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return False

        if log:
            logger.info('Homing to first rotor position...', extra=self._logger_dict)
        if not self._set_rotor_first_position(self.rotor_info.first_position):
            return False

        if log:
            logger.info('Setting next rotor position...', extra=self._logger_dict)
        if not self._set_rotor_next_position(self.rotor_info.bottle_number):
            return False

        self.current_slot = self.rotor_info.bottle_number // 2 + 1 + (-1) ** self.rotor_info.numbering_is_clockwise  # Home position is slot 1 at front, i.e., slot self.rotor_info.bottle_number // 2 at back; +1 due to 1-based counting (first position is 1, not 0); (-1)**self.rotor_info.numbering_is_clockwise due to call to _set_rotor_next_position (will always go counterclockwise to the next position)
        return True

    @TaskScheduler.scheduled_task
    def start_centrifugation(self, run_time: Union[int, None] = None, speed: Union[int, None] = None, temperature: Union[int, None] = None, log: bool = True, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Starts the run with the currently active or supplied time, speed, and temperature setpoints.

        Parameters
        ----------
        run_time: Union[int, None] = None
            The centrifugation time in seconds. If set to None, the current time setpoint is used. Default is None.
        speed: Union[int, None] = None
            The centrifugation speed in rpm. If set to None, the current speed setpoint is used. Default is None.
        temperature: Union[int, None] = None
            The centrifugation temperature in degrees Celsius. If set to None, the current temperature setpoint is used. Default is None.
        log: bool = True
            Set to False to disable logging for this query. Default is True.
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
        bool
            True when the run finished successfully, False otherwise

        Raises
        ------
        AssertionError
            If an invalid value is entered.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return False

        if run_time is not None:
            assert run_time >= 0, f'Run time needs to be >= 0.'
            if self.set_time(run_time) == -1:
                return False
        else:
            run_time = self.get_time_setpoint()

        if speed is not None:
            assert (speed >= 0 and speed <= self.rotor_info.max_rpm), f'Speed needs to be between 0 and {self.rotor_info.max_rpm} rpm'
            if self.set_speed(speed) == -1:
                return False
        else:
            speed = self.get_speed_setpoint()

        if temperature is not None:
            assert (temperature >= -20 and temperature <= 40), f'Temperature needs to be between -20 and 40 degrees Celsius.'
            if self.set_temperature(temperature) == -1:
                return False
        else:
            temperature = self.get_temperature_setpoint()

        if not self.close_lid():
            return False

        with self._com_port_lock:
            self.ser.write(f'ZEX P1\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'ZER 0' not in r:
            logger.error(f'Error starting centrifugation run: {r}', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info(f'Centrifugation run started. Time: {run_time} seconds; Speed: {speed} rpm; Temperature: {temperature} degrees Celsius', extra=self._logger_dict)

        while 'ZT1 0' not in r:  
            with self._com_port_lock:
                r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())

        if log:
            logger.info(f'Centrifugation speed setpoint reached.', extra=self._logger_dict)

        if run_time == 0:
            return True
        else:
            while 'ZS1 0' not in r: 
                with self._com_port_lock:
                    r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())

            if log:
                logger.info(f'Centrifugation run finished.', extra=self._logger_dict)
            time.sleep(2)  # Wait 2 seconds to reach complete standstill

        return self.rotor_homing()

    def stop(self, log: bool = True) -> bool:
        """
        Stops the centrifugation run.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the centrifugation run was stopped successfully, False otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return False

        with self._com_port_lock:
            self.ser.write(f'ZEX P2\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
        if 'ZER 0' not in r:
            logger.error(f'Error stopping centrifugation run: {r}', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info(f'Centrifugation run stopped.', extra=self._logger_dict)
            return True

    def get_current_speed(self, log: bool = True, is_polling: bool = False) -> int:
        """
        Gets the current centrifugation speed in rpm.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            Whether the request is part of a regular polling request. If so, do not wait on the communication lock if the hardware is busy and just return immediately. Default is False.

        Returns
        -------
        int
            The current centrifugation speed in rpm if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        if self._com_port_lock.acquire(blocking=not is_polling):
            return -1

        self.ser.write(f'ZPR IsSpeed\n'.encode())
        r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        self._com_port_lock.release()

        if 'ZIsSpeed' not in r:
            logger.error(f'Error getting speed: {r}', extra=self._logger_dict)
            return -1
        else:
            speed = int(r.replace('ZIsSpeed', '').replace(' ', '').replace('\r', '').replace('\n', ''))
            if log:
                logger.info(f'Speed is currently {speed} rpm.', extra=self._logger_dict)
            return speed

    def get_speed_setpoint(self, log: bool = True) -> int:
        """
        Gets the currently set centrifugation speed in rpm.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The currently set centrifugation speed in rpm if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        with self._com_port_lock:
            self.ser.write(f'ZPR Speed\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'Speed' not in r:
            logger.error(f'Error getting speed: {r}', extra=self._logger_dict)
            return -1
        else:
            speed = int(r.replace('ZSpeed', '').replace(' ', '').replace('\r', '').replace('\n', ''))
            if log:
                logger.info(f'Speed currently set to {speed} rpm.', extra=self._logger_dict)
            return speed

    def set_speed(self, speed: int, log: bool = True) -> int:
        """
        Sets the centrifugation speed in rpm.

        Parameters
        ----------
        speed: int
            The new centrifugation speed in rpm.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The new centrifugation speed in rpm if successful, -1 otherwise

        Raises
        ------
        AssertionError
            If an invalid value is entered.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        assert (speed >= 0 and speed <= self.rotor_info.max_rpm), f'Speed needs to be between 0 and {self.rotor_info.max_rpm} rpm'

        with self._com_port_lock:
            self.ser.write(f'ZSpeed={speed}\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'ZSpeed' not in r:
            logger.error(f'Error setting speed to {speed} rpm: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Speed set to {speed} rpm', extra=self._logger_dict)
            return speed

    def get_current_time(self, log: bool = True) -> int:
        """
        Gets the current centrifugation run time in seconds.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The current centrifugation run time in seconds if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        with self._com_port_lock:
            self.ser.write(f'ZPR IsTime\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'ZIsTime' not in r:
            logger.error(f'Error getting run time: {r}', extra=self._logger_dict)
            return -1
        else:
            run_time = int(r.replace('ZIsTime', '').replace(' ', '').replace('\r', '').replace('\n', ''))
            if log:
                logger.info(f'Time is currently {run_time} seconds.', extra=self._logger_dict)
            return run_time

    def get_time_setpoint(self, log: bool = True) -> int:
        """
        Gets the currently set centrifugation run time in seconds.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The currently set centrifugation run time in seconds if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        with self._com_port_lock:
            self.ser.write(f'ZPR Time\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'Time' not in r:
            logger.error(f'Error getting run time: {r}', extra=self._logger_dict)
            return -1
        else:
            run_time = int(r.replace('ZTime', '').replace(' ', '').replace('\r', '').replace('\n', ''))
            if log:
                logger.info(f'Time currently set to {run_time} seconds.', extra=self._logger_dict)
            return run_time

    def set_time(self, run_time: int, log: bool = True) -> int:
        """
        Sets the centrifugation run time in seconds. Set to 0 for maximum run time (hold).

        Parameters
        ----------
        run_time: int
            The new centrifugation run time in seconds.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The new centrifugation run time in seconds if successful, -1 otherwise

        Raises
        ------
        AssertionError
            If an invalid value is entered.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        assert run_time >= 0, f'Run time needs to be >= 0 seconds.'

        with self._com_port_lock:
            self.ser.write(f'ZTime={run_time}\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'ZTime' not in r:
            logger.error(f'Error setting run time to {run_time} seconds: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Time set to {run_time} seconds', extra=self._logger_dict)
            return run_time

    def get_current_temperature(self, log: bool = True, is_polling: bool = False) -> Union[int, None]:
        """
        Gets the current centrifuge temperature in degrees Celsius.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            Whether the request is part of a regular polling request. If so, do not wait on the communication lock if the hardware is busy and just return immediately. Default is False.

        Returns
        -------
        Union[int, None]
            The current centrifuge temperature in degrees Celsius if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        if not self._com_port_lock.acquire(blocking=not is_polling):
            return -1

        self.ser.write(f'ZPR IsTemp\n'.encode())
        r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        self._com_port_lock.release()

        if 'ZIsTemp' not in r:
            logger.error(f'Error getting temperature: {r}', extra=self._logger_dict)
            return -1
        else:
            temperature = int(r.replace('ZIsTemp', '').replace(' ', '').replace('\r', '').replace('\n', '')) // 10
            if log:
                logger.info(f'Temperature is currently {temperature} degrees Celsius.', extra=self._logger_dict)
            return temperature

    def get_temperature_setpoint(self, log: bool = True) -> Union[int, None]:
        """
        Gets the currently set centrifugation temperature in degrees Celsius.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        Union[int, None]
            The currently set centrifugation temperature in degrees Celsius if successful, None otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.write(f'ZPR Temp\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'Temp' not in r:
            logger.error(f'Error getting temperature: {r}', extra=self._logger_dict)
            return -1
        else:
            temperature = int(r.replace('ZTemp', '').replace(' ', '').replace('\r', '').replace('\n', '')) // 10
            if log:
                logger.info(f'Temperature currently set to {temperature} degrees Celsius.', extra=self._logger_dict)
            return temperature

    def set_temperature(self, temperature: int, log: bool = True) -> int:
        """
        Sets the centrifugation temperature in degrees Celsius.

        Parameters
        ----------
        temperature: int
            The new centrifugation temperature in degrees Celsius.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The new centrifugation temperature in degrees Celsius if successful, -1 otherwise

        Raises
        ------
        AssertionError
            If an invalid value is entered.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        assert (temperature >= -20 and temperature <= 40), f'Temperature needs to be between -20 and 40 degrees Celsius.'

        with self._com_port_lock:
            self.ser.write(f'ZTemp={temperature*10}\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if 'ZTemp' not in r:
            logger.error(f'Error setting temperature to {temperature} degrees Celsius: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Temperature set to {temperature} degrees Celsius', extra=self._logger_dict)
            return temperature

    def open_lid(self, log: bool = True) -> bool:
        """
        Opens the sliding lid of the centrifuge.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the lid was opened successfully, False otherwise.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return False

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the lid time to open
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('BEX P2\n'.encode())
                    r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
                if 'ER 0' not in r:
                    logger.error(f'Error Opening RobotCen Lid: {r}', extra=self._logger_dict)
                    with self._com_port_lock:
                        self.ser.timeout = self.timeout
                    return False
                else:
                    if log:
                        logger.info('Opened RobotCen Lid.', extra=self._logger_dict)
                    with self._com_port_lock:
                        self.ser.timeout = self.timeout
                    return True
            except TimeoutError:
                with self._com_port_lock:
                    self.ser.flush()
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                logging.warning(f'Timed out while opening lid. Retrying... ({i}/{self.retries})', extra=self._logger_dict)
                continue  # try again (maximum self.retries times)

        with self._com_port_lock:
            self.ser.timeout = self.timeout
        return False

    def close_lid(self, log: bool = True) -> bool:
        """
        Closes the sliding lid of the centrifuge.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the lid was closed successfully, False otherwise.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return False

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the lid time to close
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('BEX P1\n'.encode())
                    r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
                if 'BS2 0' not in r:  # The correct answer from the device to the "BEX P1" command is BEX P1\r\n>BS2 0\r\n\r\n and not BER 0\r\nBS2 0\r\n\r\n
                    logger.error(f'Error Closing RobotCen Lid: {r}', extra=self._logger_dict)
                    with self._com_port_lock:
                        self.ser.timeout = self.timeout
                    return False
                else:
                    if log:
                        logger.info('Closed RobotCen Lid.', extra=self._logger_dict)
                    with self._com_port_lock:
                        self.ser.timeout = self.timeout
                    return True
            except TimeoutError:
                with self._com_port_lock:
                    self.ser.flush()
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                logger.warning(f'Timed out while closing lid. Retrying... ({i}/{self.retries})', extra=self._logger_dict)
                continue  # try again (maximum self.retries times)

        with self._com_port_lock:
            self.ser.timeout = self.timeout
        return False

    def set_position_relative(self, slot_steps: int, log: bool = True) -> Union[int, None]:
        """
        Rotates the rotor slot_steps times.

        Parameters
        ----------
        slot_steps: int
            The number of slots by which the rotor should be moved. Positive numbers correspond clockwise rotation, negative numbers to counterclockwise rotation.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The number of slots the rotor moved by if successful, None otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the new position
            self.ser.write(f'AR3 {slot_steps} \nAEX P8\n'.encode())

            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout
        if 'ER 0' not in r:
            logger.error(f'Error moving rotor by {slot_steps} slots: {r}', extra=self._logger_dict)
            return None
        else:
            if slot_steps >= 0:
                direction = 'forward'
            else:
                direction = 'backward'
            if log:
                logger.info(f'Rotor moved {direction} by {abs(slot_steps)} slots.', extra=self._logger_dict)
            return slot_steps

    def set_position_absolute(self, slot: int, log: bool = True) -> int:
        """
        Sets the position of the rotor to the specified slot.

        Parameters
        ----------
        slot: int
            The slot number to which the rotor should be moved.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The slot number the rotor moved to if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        if (slot - self.current_slot) % self.rotor_info.bottle_number < (self.rotor_info.bottle_number // 2):
            relative = (-1)**self.rotor_info.numbering_is_clockwise * ((slot - self.current_slot) % self.rotor_info.bottle_number)
        else:
            relative = (-1)**self.rotor_info.numbering_is_clockwise * ((slot - self.current_slot) % self.rotor_info.bottle_number - self.rotor_info.bottle_number)

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the new position
            self.ser.write(f'AR3 {relative} \nAEX P8\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout
        if 'ER 0' not in r:
            logger.error(f'Error moving rotor to slot {slot}: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Rotor moved to slot {slot}.', extra=self._logger_dict)
            self.current_slot = slot
            return slot

    def set_position_relative2(self, slot_steps: int, log: bool = True) -> Union[int, None]:
        """
        Rotates the rotor slot_steps times (using stepper commands converted to slot numbers, i.e., the function _set_rotor_position_relative).

        Parameters
        ----------
        slot_steps: int
            The number of slots by which the rotor should be moved. Positive numbers correspond clockwise rotation, negative numbers to counterclockwise rotation.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The number of slots the rotor moved by if successful, None otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the new position
            self.ser.write(f'AR3 {int(slot_steps * self.rotor_info.steps_per_slot)} \nAEX P3\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout
        if 'ER 0' not in r:
            logger.error(f'Error moving rotor by {slot_steps} slots: {r}', extra=self._logger_dict)
            return None
        else:
            if slot_steps >= 0:
                direction = 'forward'
            else:
                direction = 'backward'
            if log:
                logger.info(f'Rotor moved {direction} by {abs(slot_steps)} slots.', extra=self._logger_dict)
            return slot_steps

    def set_position_absolute2(self, slot: int, log: bool = True) -> int:
        """
        Sets the position of the rotor to the specified slot (using stepper commands converted to slot numbers, i.e., the function _set_rotor_position_absolute).

        Parameters
        ----------
        slot: int
            The slot number to which the rotor should be moved.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The slot number the rotor moved to if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the new position
            self.ser.write(f'AR3 {int((self.rotor_info.bottle_number / 2 - (slot - 1)) * self.rotor_info.steps_per_slot) % RobotCen.STEPS_PER_REVOLUTION}\nAEX P4\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout
        if 'ER 0' not in r:
            logger.error(f'Error moving rotor to slot {slot}: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Rotor moved to slot {slot}.', extra=self._logger_dict)
            self.current_slot = slot
            return slot

    def get_rotor_position(self, log: bool = True) -> int:
        """
        Queries the current position of the rotor in slot numbers.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The current position of the rotor if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        pos = self._get_rotor_position()
        if pos == -1:
            return pos
        else:
            if log:
                logger.info(f'Rotor position is {int(pos / self.rotor_info.steps_per_slot) % self.rotor_info.bottle_number}', extra=self._logger_dict)
            return int(pos / self.rotor_info.steps_per_slot) % self.rotor_info.bottle_number

    def _get_rotor_position(self, log: bool = True) -> Union[int, None]:
        """
        Queries the current position of the rotor in absolute units (not slot number).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        Union[int, None]
            The current position of the rotor if successful, None otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.write('AEX P11\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
        if 'ER 0' not in r:
            logger.error(f'Error querying rotor position: {r}', extra=self._logger_dict)
            return -1
        else:
            r = r.split('\r\n')
            pos = -1
            for i in r:
                if 'Position = ' in i:
                    pos = int(i.replace('Position = ', '').replace('\r\n', ''))
                    break
            if log:
                logger.info(f'Current Rotor Position: {pos}', extra=self._logger_dict)
            return pos

    def _set_rotor_position_absolute(self, position: int, log: bool = True) -> Union[int, None]:
        """
        Sets the current position of the rotor in absolute units (not slot number).

        Parameters
        ----------
        position: int
            The new position of the rotor.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        Union[int, None]
            The new position of the rotor if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the new position
            self.ser.write(f'AR3 {position} \nAEX P4\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout

        if 'ER 0' not in r:
            logger.error(f'Error moving rotor to position {position}: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Rotor moved to position {position}', extra=self._logger_dict)
            return position

    def _set_rotor_position_relative(self, steps: int, log: bool = True) -> Union[int, None]:
        """
        Sets the position of the rotor relative to its current position in absolute units (not slot numbers).

        Parameters
        ----------
        steps: int
            The number of steps by which the rotor should be moved.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        Union[int, None]
            The number of steps the rotor was moved forward if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the new position
            self.ser.write(f'AR3 {steps} \nAEX P3\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout

        if 'ER 0' not in r:
            logger.error(f'Error moving rotor forward by {steps} steps: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Rotor moved forward by {steps} steps.', extra=self._logger_dict)
            return steps

    def _set_rotor_first_position(self, position: int, log: bool = True) -> Union[int, None]:
        """
        Sets the first position of the rotor

        Parameters
        ----------
        position: int
            The first position of the rotor.
        log: bool = True
            Set to False to disable logging for this query. Default is True.


        Returns
        -------
        int
            The first position of the rotor if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return None

        with self._com_port_lock:
            self.ser.timeout = 120  # Temporarily increase timeout to give the rotor time to reach the home position
            self.ser.write(f'AR1 {position}\n'.encode())
            time.sleep(1)
            self.ser.write('AEX P1\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout

        if 'ER 0' not in r:
            logger.error(f'Error setting rotor to first position {position}: {r}', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info(f'Rotor set to first position {position}', extra=self._logger_dict)
            return position

    def _set_rotor_next_position(self, bottle_number: int, log: bool = True) -> int:
        """
        Sets the bottle number of the rotor.

        Parameters
        ----------
        bottle_number: int
            The bottle number of the rotor.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The bottle number if successful, -1 otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time to reach the next position
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write(f'AR2 {bottle_number}\n'.encode())
                    time.sleep(1)
                    self.ser.write('AEX P2\n'.encode())
                    r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
                if 'ER 0' not in r:
                    logger.error(f'Error setting bottle number to {bottle_number}: {r}', extra=self._logger_dict)
                    with self._com_port_lock:
                        self.ser.timeout = self.timeout
                    return -1
                else:
                    if log:
                        logger.info(f'Bottle number set to {bottle_number}.', extra=self._logger_dict)
                    with self._com_port_lock:
                        self.ser.timeout = self.timeout
                    return bottle_number
            except TimeoutError:
                with self._com_port_lock:
                    self.ser.flush()
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                logging.warning(f'Timed out while setting bottle number. Retrying... ({i}/{self.retries})')
                continue  # try again (maximum self.retries times)

        with self._com_port_lock:
            self.ser.timeout = self.timeout
        return False

    def rotor_detection(self, log: bool = True) -> bool:
        """
        Does 3 turns to detect the rotor

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return False

        with self._com_port_lock:
            self.ser.timeout = 30  # Temporarily increase timeout to give the rotor time for 3 revolutions
            self.ser.write(f'AEX P5\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout

        if 'ER 0' not in r:
            logger.error(f'Error detecting rotor: {r}', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info(f'Rotor detected.', extra=self._logger_dict)
            return True

    def enable_and_get_rotor_id(self, log: bool = True) -> str:
        """
        Enable and get the rotor information. Also calls AEX P5 (rotor_detection) after the first reply with REN.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
             ROT, Mg count, 1st code, 2nd code, 3rd code, 4th code, Rotor type, Bottle number, Max rpm, First position if successful, '' otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.timeout = 20  # Temporarily increase timeout to give the rotor time for 3 revolutions
            self.ser.write(f'NRENm\r\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())

            if r != 'REN':
                return ''

            self.ser.write(f'AEX P5\r\n'.encode())
            r = self.ser.read_until(self.eol2).decode().rstrip(self.eol2.decode())
            self.ser.timeout = self.timeout

        if 'ER 0' not in r or 'ID1' not in r:
            return ''

        r = r.replace('\r', '').replace('\n', '').replace('AEX P5>AER 0ID1', '').replace('AS5 0', '')
        if log:
            logger.info(f'Rotor Information: {r}', extra=self._logger_dict)
        return r

    def get_rotor_id(self, log: bool = True) -> str:
        """
        Get the rotor information.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
             ROT, Mg count, 1st code, 2nd code, 3rd code, 4th code, Rotor type, Bottle number, Max rpm, First position if successful, '' otherwise
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.write(f'NRROTm\r\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())

        if log:
            logger.info(f'Rotor Information: {r}', extra=self._logger_dict)
        return r

    def rpm_to_rcf(self, rpm: float) -> float:
        """
        Calculate rcf from a given rpm value, based on the current rotor information.

        Parameters
        ----------
        rpm: float
            The rpm value that should be converted into rcf.

        Returns
        -------
        float
            The corresponding rcf value.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1
        g = 9.81
        r = self.rotor_info.radius_in_mm / 1000.0
        return r * (rpm * 2 * math.pi / 60)**2 / g

    def rcf_to_rpm(self, rcf: float) -> float:
        """
        Calculate rpm from a given rcf value, based on the current rotor information.

        Parameters
        ----------
        rcf: float
            The rcf value that should be converted into rpm.

        Returns
        -------
        float
            The corresponding rpm value.
        """
        if RobotCen.EMERGENCY_STOP_REQUEST:
            return -1
        g = 9.81
        r = self.rotor_info.radius_in_mm / 1000.0
        return math.sqrt(rcf / r * g) * 60 / (2 * math.pi)
