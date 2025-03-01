#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import logging
import threading
import time
from typing import Union, Optional

import serial
import os.path

from Minerva.API.HelperClassDefinitions import HotplateHardware, TaskScheduler, TaskGroupSynchronizationObject, PathNames

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


class RCTDigital5(HotplateHardware):
    """
    Class for using the IKA RCT Digital 5 hotplates. Based on hein lab ika.magnetic_stirrer package.

    Parameters
    ----------
    com_port : str
        The COM Port of the hotplate.
    """
    EMERGENCY_STOP_REQUEST = False

    # constant names are the functions, and the values are the corresponding NAMUR commands
    READ_DEVICE_NAME = "IN_NAME"
    READ_CURRENT_EXTERNAL_SENSOR_VALUE = "IN_PV_1"
    READ_CURRENT_HOTPLATE_SENSOR_VALUE = "IN_PV_2"
    READ_CURRENT_STIRRING_SPEED_VALUE = "IN_PV_4"
    READ_CURRENT_VISCOSITY_TREND_VALUE = "IN_PV_5"
    READ_TEMPERATURE_SETPOINT = "IN_SP_1"
    READ_SAFETY_TEMPERATURE_VALUE = "IN_SP_3"  # find the set safe temperature of the plate, the target/set temperature the plate can go to is 50 degrees beneath this
    READ_STIRRING_SPEED_SETPOINT = "IN_SP_4"
    SET_TEMPERATURE_SETPOINT = "OUT_SP_1 "  # requires a value to be appended to the end of the command
    SET_STIRRING_SPEED_SETPOINT = "OUT_SP_4 "  # requires a value to be appended to the end of the command
    START_HEATING = "START_1"
    STOP_HEATING = "STOP_1"
    START_STIRRING = "START_4"
    STOP_STIRRING = "STOP_4"
    SWITCH_TO_NORMAL_OPERATING_MODE = "RESET"
    SET_OPERATING_MODE_A = "SET_MODE_A"
    SET_OPERATING_MODE_B = "SET_MODE_B"
    SET_OPERATING_MODE_D = "SET_MODE_D"
    SET_WD_SAFETY_LIMIT_TEMPERATURE_WITH_SET_VALUE_ECHO = "OUT_SP_12@"  # requires a value to be appended to the end of the command
    SET_WD_SAFETY_LIMIT_SPEED_WITH_SET_VALUE_ECHO = "OUT_SP_42@"  # requires a value to be appended to the end of the command
    WATCHDOG_MODE_1 = "OUT_WD1@"   # requires a value (bw 20-1500) to be appended to the end of the command - this is the watchdog time in seconds. this command launches the watchdog function and must be transmitted within the set watchdog time. in watchdog mode 1, if event WD1 occurs, the heating and stirring functions are switched off and ER 2 is displayed
    WATCHDOG_MODE_2 = "OUT_WD2@"   # requires a value (bw 20-1500) to be appended to the end of the command - this is the watchdog time in seconds. this command launches the watchdog function and must be transmitted within the function.  in watchdog mode 2, if event WD2 occurs, the speed target value is changed to the WD safety speed limit and the temperature target value is change to the WD safety temperature limit value

    # hex command characters for data transmission
    SP_HEX = "\x20"  # space or blank
    CR_HEX = "\x0d"  # carriage return
    LF_HEX = "\x0a"  # line feed or new line
    DOT_HEX = "\x2E"  # dot
    LINE_ENDING = CR_HEX + LF_HEX  # each individual command and each response are terminated CR LF
    LINE_ENDING_ENCODED = LINE_ENDING.encode()

    def __init__(self, com_port: str) -> None:
        """
        Class for using the IKA RCT Digital 5 hotplates. Based on hein lab ika.magnetic_stirrer package.

        Parameters
        ----------
        com_port : str
            The COM Port of the hotplate.
        """
        super().__init__()
        self.com_port = str(com_port).upper()
        self.baud_rate = 9600
        self.parity = serial.PARITY_EVEN
        self.byte_size = 7
        self.stop_bit = 1
        self.timeout = 1
        self.retries = 3
        self.retries_connect = 3
        self._com_port_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.com_port = 'COM' + self.com_port

        self.temperature_stabilization_query_time = 30  # seconds
        self.stable_temperature_reached = threading.Event()
        self.heating_completed_event = threading.Event()

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)

        i = 0
        for i in range(0, self.retries_connect):
            try:
                if self.read_device_name(log=False).startswith('RCT digital'):
                    logger.info(f'Connected to RCTDigital5 on {self.com_port}.', extra=self._logger_dict)
                    break
            except TimeoutError:
                continue  # Due to a probable transmission error, please attempt again (up to a maximum of self.retries times)

        if i == self.retries - 1:
            logger.critical(f'RCTDigital5 not responding on port {self.com_port}.', extra=self._logger_dict)
            raise TimeoutError(f'RCTDigital5 not responding on port {self.com_port}.')

    def _send_and_receive(self, command: str, is_polling: bool = False) -> Union[str, float]:
        """
        Send a command to the hotplate, get a response back, and return the response

        Parameters
        ----------
        command: str
            A command that will give back a response - these will be:
            READ_DEVICE_NAME
            READ_CURRENT_EXTERNAL_SENSOR_VALUE
            READ_CURRENT_HOTPLATE_SENSOR_VALUE
            READ_CURRENT_STIRRING_SPEED_VALUE
            READ_CURRENT_VISCOSITY_TREND_VALUE
            READ_TEMPERATURE_SETPOINT
            READ_SAFETY_TEMPERATURE_VALUE
            READ_STIRRING_SPEED_SETPOINT
        is_polling: bool = False
            If set to True, the request is made by a polling thread (in that case, give it a low priority). Default is False.

        Returns
        -------
        Union[str, float]
            The answer from the device
        """
        if RCTDigital5.EMERGENCY_STOP_REQUEST:
            return 'Emergency Stop Active'

        if is_polling and self._com_port_lock.locked():
            return -1
        else:
            with self._com_port_lock:
                # format the command to send so that it terminates with the line ending (CR LF)
                formatted_command: str = command + self.LINE_ENDING
                formatted_command_encoded = formatted_command.encode()
                for i in range(self.retries):
                    self.ser.write(formatted_command_encoded)
                    # this is the response, and is returned
                    return_string = self.ser.read_until(self.LINE_ENDING_ENCODED).decode().rstrip(self.LINE_ENDING)
                    if return_string != '':
                        break
        # all the functions that would use this function, except when requesting the device name, return a number.
        # however the return string type for all the other functions is a string of the type '#.# #', so we want to
        # change that into a float instead, to facilitate easier usage
        if return_string == 'C-MAG HS7':
            return 'C-MAG HS7'
        elif return_string == 'RCT digital':
            return 'RCT digital'
        else:
            formatted_return_float = float(return_string.split()[0])  # return just the information we want as a float
        return formatted_return_float

    def _send(self, command: str) -> None:
        """
        Send a command to the hotplate

        Parameters
        ----------
        command: str
            A command with optional parameters included if required (such as for setting temperature or stirring rate)

        Returns
        -------
        None
        """
        if RCTDigital5.EMERGENCY_STOP_REQUEST:
            return
        with self._com_port_lock:
            # format the command to send so that it terminates with the line ending (CR LF)
            formatted_command: str = command + self.LINE_ENDING
            formatted_command_encoded = formatted_command.encode()
            self.ser.write(data=formatted_command_encoded)  # commands need to be encoded when sent

    def disconnect(self) -> None:
        """
        Stop heating and stirring and close the serial port
        """
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    with self._com_port_lock:
                        self.stop_heating()
                        self.stop_stirring()
                        self.ser.close()
            except serial.SerialException:
                logger.error("Could not disconnect from hotplate.", extra=self._logger_dict)

    def read_device_name(self, log: bool = True) -> str:
        """
        Read and return the device name.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
            The device name.
        """
        return_value = str(self._send_and_receive(command=self.READ_DEVICE_NAME))
        if log:
            logger.info(f'Device Name: {return_value}', extra=self._logger_dict)
        return return_value

    def read_current_external_sensor_value(self, log: bool = True, is_polling: bool = False) -> float:
        """
        Read and return the temperature read from the thermocouple (in degrees Celsius).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            If set to True, the request is made by a polling thread (in that case, give it a low priority). Default is False.

        Returns
        -------
        float
            The temperature read from the thermocouple (in degrees Celsius).
        """
        return_value = float(self._send_and_receive(command=self.READ_CURRENT_EXTERNAL_SENSOR_VALUE, is_polling=is_polling))
        if log:
            logger.info(f'Temperature (Thermocouple): {return_value} degrees Celsius', extra=self._logger_dict)
        return return_value

    def read_current_hotplate_sensor_value(self, log: bool = True, is_polling: bool = False) -> float:
        """
        Read and return the temperature read from the hotplate directly (in degrees Celsius).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            If set to True, the request is made by a polling thread (in that case, give it a low priority). Default is False.

        Returns
        -------
        float
            The temperature read from the hotplate directly (in degrees Celsius).
        """
        return_value = float(self._send_and_receive(command=self.READ_CURRENT_HOTPLATE_SENSOR_VALUE, is_polling=is_polling))
        if log:
            logger.info(f'Temperature (Hotplate): {return_value} degrees Celsius', extra=self._logger_dict)
        return return_value

    def read_current_stirring_speed_value(self, log: bool = True, is_polling: bool = False) -> float:
        """
        Read and return the current stirring speed (in rpm).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            If set to True, the request is made by a polling thread (in that case, give it a low priority). Default is False.

        Returns
        -------
        float
            The current stirring speed (in rpm).
        """
        return_value = float(self._send_and_receive(command=self.READ_CURRENT_STIRRING_SPEED_VALUE, is_polling=is_polling))
        if log:
            logger.info(f'Stirring Speed: {return_value} rpm', extra=self._logger_dict)
        return return_value

    def read_current_viscosity_trend_value(self, log: bool = True, is_polling: bool = False) -> float:
        """
        Read and return the viscosity trend value.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            If set to True, the request is made by a polling thread (in that case, give it a low priority). Default is False.

        Returns
        -------
        float
            The current viscosity trend value.
        """
        return_value = float(self._send_and_receive(command=self.READ_CURRENT_VISCOSITY_TREND_VALUE, is_polling=is_polling))
        if log:
            logger.info(f'Viscosity Trend: {return_value}', extra=self._logger_dict)
        return return_value

    def read_temperature_setpoint(self, log: bool = True) -> float:
        """
        Read and return the temperature setpoint (in degrees Celsius).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The temperature setpoint (in degrees Celsius).
        """
        return_value = float(self._send_and_receive(command=self.READ_TEMPERATURE_SETPOINT))
        if log:
            logger.info(f'Temperature Setpoint: {return_value} degrees Celsius', extra=self._logger_dict)
        return return_value

    def read_safety_temperature_value(self, log: bool = True) -> float:
        """
        Read and return the safety temperature value (in degrees Celsius).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The safety temperature value (in degrees Celsius).
        """
        return_value = float(self._send_and_receive(command=self.READ_SAFETY_TEMPERATURE_VALUE))
        if log:
            logger.info(f'Rated Safety Temperature Value: {return_value} degrees Celsius', extra=self._logger_dict)
        return return_value

    def read_stirring_speed_setpoint(self, log: bool = True) -> float:
        """
        Read and return the stirring speed setpoint (in rpm).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The stirring speed setpoint (in rpm).
        """
        return_value = float(self._send_and_receive(command=self.READ_STIRRING_SPEED_SETPOINT))
        if log:
            logger.info(f'Stirring Speed Setpoint: {return_value} rpm', extra=self._logger_dict)
        return return_value

    def set_temperature_setpoint(self, value: float, log: bool = True) -> None:
        """
        Set the temperature setpoint (in degrees Celsius).

        Parameters
        ----------
        value: float
            The temperature setpoint (in degrees Celsius).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        command = self.SET_TEMPERATURE_SETPOINT + str(value) + ' '
        self._send(command=command)
        if log:
            logger.info(f'Temperature setpoint changed to: {value} degrees Celsius', extra=self._logger_dict)

    def set_stirring_speed_setpoint(self, value: float, log: bool = True) -> None:
        """
        Set the stirring speed setpoint (in rpm).

        Parameters
        ----------
        value: float
            The stirring speed setpoint (in rpm).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        command = self.SET_STIRRING_SPEED_SETPOINT + str(value) + ' '
        self._send(command=command)
        if log:
            logger.info(f'Stirring Speed setpoint changed to: {value} rpm', extra=self._logger_dict)

    def start_heating(self, value: Optional[float] = None, log: bool = True) -> None:
        """
        Start heating to the provided temperature or the currently set setpoint.

        Parameters
        ----------
        value: Optional[float] = None
            If provided, the temperature setpoint will be changed to this value (in degrees Celsius). If set to None, the current setpoint will be used. Default is None.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        if value is not None:
            self.set_temperature_setpoint(value=value, log=log)
        self._send(command=self.START_HEATING)
        if log:
            logger.info(f'Started heating...', extra=self._logger_dict)

    def stop_heating(self, reset_setpoint: bool = True, log: bool = True) -> None:
        """
        Stop heating.

        Parameters
        ----------
        reset_setpoint: bool = True
            If set to tTrue, the setpoint will be set to 0 degrees Celsius and the heating will be switched off (otherwise, only the heating is switched off but the setpoint is not changed). Default is True.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        self._send(command=self.STOP_HEATING)
        if log:
            logger.info(f'Stopped heating.', extra=self._logger_dict)
        if reset_setpoint:
            self.set_temperature_setpoint(value=0, log=log)

    def start_stirring(self, value: Optional[float] = None, log: bool = True) -> None:
        """
        Start stirring with the provided speed or the currently set setpoint.

        Parameters
        ----------
        value: Optional[float] = None
            If provided, the stirring speed setpoint will be changed to this value (in rpm). If set to None, the current setpoint will be used. Default is None.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        if value is not None:
            self.set_stirring_speed_setpoint(value=value, log=log)
        self._send(command=self.START_STIRRING)
        if log:
            logger.info(f'Started stirring...', extra=self._logger_dict)

    def stop_stirring(self, reset_setpoint: bool = True, log: bool = True) -> None:
        """
        Stop stirring.

        Parameters
        ----------
        reset_setpoint: bool = True
            If set to True, the setpoint will be set to 0 rpm and the stirring will be switched off (otherwise, only the stirring is switched off but the setpoint is not changed). Default is True.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        self._send(command=self.STOP_STIRRING)
        if log:
            logger.info(f'Stopped stirring.', extra=self._logger_dict)
        if reset_setpoint:
            self.set_stirring_speed_setpoint(value=0, log=log)

    def switch_to_normal_operating_mode(self, log: bool = True) -> None:
        """
        Switch to normal operating mode.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        self._send(command=self.SWITCH_TO_NORMAL_OPERATING_MODE)
        if log:
            logger.info(f'Switched to Normal Operating Mode.', extra=self._logger_dict)

    def set_operating_mode_a(self, log: bool = True) -> None:
        """
        Switch to operating mode a.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        self._send(command=self.SET_OPERATING_MODE_A)
        if log:
            logger.info(f'Switched to Operating Mode A.', extra=self._logger_dict)

    def set_operating_mode_b(self, log: bool = True) -> None:
        """
        Switch to operating mode b.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        self._send(command=self.SET_OPERATING_MODE_B)
        if log:
            logger.info(f'Switched to Operating Mode B.', extra=self._logger_dict)

    def set_operating_mode_d(self, log: bool = True) -> None:
        """
        Switch to operating mode d.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        self._send(command=self.SET_OPERATING_MODE_D)
        if log:
            logger.info(f'Switched to Operating Mode D.', extra=self._logger_dict)

    def set_wd_safety_limit_temperature(self, value: str, log: bool = True) -> float:
        """
        Set the watchdog safety temperature limit (in degrees Celsius).

        Parameters
        ----------
        value: float
            The watchdog safety temperature limit (in degrees Celsius).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The watchdog safety temperature limit (in degrees Celsius).
        """
        command = self.SET_WD_SAFETY_LIMIT_TEMPERATURE_WITH_SET_VALUE_ECHO + value + ' '
        return_value = float(self._send_and_receive(command=command))
        if log:
            logger.info(f'Set Watchdog Safety Temperature Limit: {return_value} degrees Celsius', extra=self._logger_dict)
        return return_value

    def set_wd_safety_limit_speed(self, value: float, log: bool = True) -> float:
        """
        Set the watchdog safety stirring speed limit (in rpm).

        Parameters
        ----------
        value: float
            The watchdog safety stirring speed limit (in rpm).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The watchdog safety stirring speed limit (in rpm).
        """
        command = self.SET_WD_SAFETY_LIMIT_SPEED_WITH_SET_VALUE_ECHO + str(value) + ' '
        return_value = float(self._send_and_receive(command=command))
        if log:
            logger.info(f'Set Watchdog Safety Stirring Speed Limit: {return_value} rpm', extra=self._logger_dict)
        return return_value

    def watchdog_mode_1(self, value: float, log: bool = True) -> None:
        """
        Launch the watchdog function (must be transmitted within the set watchdog time). In watchdog mode 1, if event WD1 occurs, the heating and stirring functions are switched off and ER 2 is displayed.

        Parameters
        ----------
        value: float
            The watchdog time in seconds (should be between 20 and 1500)
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        command = self.WATCHDOG_MODE_1 + str(value) + ' '
        self._send(command=command)
        if log:
            logger.info(f'Watchdog Mode 1 started. Watchdog Time: {value} sec', extra=self._logger_dict)

    def watchdog_mode_2(self, value: float, log: bool = True) -> None:
        """
        Launch the watchdog function (must be transmitted within the set watchdog time). The WD2 event can be reset with the command "OUT_WD2@0", and this also stops the watchdog function. In watchdog mode 2, if event WD2 occurs, the speed target value is changed to the WD safety speed limit and the temperature target value is change to the WD safety temperature limit value.

        Parameters
        ----------
        value: float
            The watchdog time in seconds (should be between 20 and 1500)
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        None
        """
        command = self.WATCHDOG_MODE_2 + str(value) + ' '
        self._send(command=command)
        if log:
            logger.info(f'Watchdog Mode 2 started. Watchdog Time: {value} sec', extra=self._logger_dict)

    @TaskScheduler.scheduled_task
    def heat(self, heating_temperature: float, heating_time: float, stirring_speed: Optional[float] = 0, temperature_stabilization_time: Optional[float] = None, maximum_temperature_deviation: Optional[float] = None, cooldown_temperature: Optional[float] = None, temperature_sensor: Optional[str] = 'EXTERNAL', block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Method for heating and/or stirring

        Parameters
        ----------
        heating_temperature: float
            The temperature to which this container is heated (in degrees Celsius)
        heating_time: float
            The amount of time for which the container is heated/stirred (in seconds)
        stirring_speed: float
            The stirring speed during heating (in rpm)
        temperature_stabilization_time: Optional[float] = None
            Time (in seconds) for how long the temperature has to stay within maximum_temperature_deviation degrees from the target temperature to be considered stable. If set to None, the hotplate will not wait to reach a stable target temperature and the heating_time will start immediately. Default is None.
        maximum_temperature_deviation: Optional[float] = None
            Maximum deviation from the target temperature that is still considered as "stable" during the stabilization time. Only has an effect when a temperature_stabilization_time is provided. If set to None, the value 0 will be used. Default is None.
        cooldown_temperature: Optional[float] = None
            After the heating_time elapsed, wait until the temperature falls below this setpoint (in degrees Celsius) for two consecutive readings. If set to None, do not wait for cool down. Default is None.
        temperature_sensor: Optional[str] = 'EXTERNAL'
            The temperature sensor to use. needs to be either "EXTERNAL" (for thermocouple) or "INTERNAL"/None (for internal hotplate sensor). Default is EXTERNAL.
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
        if RCTDigital5.EMERGENCY_STOP_REQUEST:
            return False

        assert temperature_sensor == 'INTERNAL' or temperature_sensor == 'EXTERNAL' or temperature_sensor is None, f'Invalid value for temperature sensor: {temperature_sensor}. Needs to be EXTERNAL, INTERNAL, or None.'

        if self.heating_completed_event.is_set():
            self.heating_completed_event.clear()
        if self.stable_temperature_reached.is_set():
            self.stable_temperature_reached.clear()

        self.start_stirring(stirring_speed)
        self.start_heating(heating_temperature)

        if temperature_stabilization_time is not None:
            temperature_stabilization_time = max(temperature_stabilization_time, 0)
            temperature_stabilization_time = max(self.temperature_stabilization_query_time + 1.0, temperature_stabilization_time)
            if maximum_temperature_deviation is None:
                maximum_temperature_deviation = 0
            maximum_temperature_deviation = max(maximum_temperature_deviation, 0)

            start_time = time.time()
            while time.time() - start_time < temperature_stabilization_time:
                if temperature_sensor == 'EXTERNAL':
                    current_temp = self.read_current_external_sensor_value(log=False)
                else:
                    current_temp = self.read_current_hotplate_sensor_value(log=False)
                if abs(current_temp - heating_temperature) > maximum_temperature_deviation:
                    start_time = time.time()
                    logger.info(f'Waiting for temperature to stabilize: {current_temp} C / {heating_temperature} C', extra=self._logger_dict)
                else:
                    logger.info(f'Waiting for temperature to stabilize: {current_temp} C / {heating_temperature} C, stable within specification since {int(time.time() - start_time)} seconds.', extra=self._logger_dict)
                time.sleep(self.temperature_stabilization_query_time)

            logger.info(f'Temperature stable at {heating_temperature} +/- {maximum_temperature_deviation} degrees Celsius', extra=self._logger_dict)

        self.stable_temperature_reached.set()

        time.sleep(heating_time)

        self.stop_heating()

        self.heating_completed_event.set()

        if cooldown_temperature is not None:
            temperature_stabilization_time = 2 * self.temperature_stabilization_query_time  # max(temperature_stabilization_time, 0)
            start_time = time.time()
            while time.time() - start_time < temperature_stabilization_time:
                if temperature_sensor == 'EXTERNAL':
                    current_temp = self.read_current_external_sensor_value(log=False)
                else:
                    current_temp = self.read_current_hotplate_sensor_value(log=False)
                if current_temp > cooldown_temperature:
                    start_time = time.time()
                    logger.info(f'Waiting for hotplate to cool down: {current_temp} C / {cooldown_temperature} C', extra=self._logger_dict)
                else:
                    logger.info(f'Waiting for hotplate to cool down: {current_temp} C / {cooldown_temperature} C, below setpoint since {int(time.time() - start_time)} seconds.', extra=self._logger_dict)
                time.sleep(self.temperature_stabilization_query_time)

            logger.info(f'Temperature is now below {cooldown_temperature} degrees Celsius.', extra=self._logger_dict)

        self.stop_stirring()

        return True

    def emergency_stop(self) -> bool:
        """
        Switches the device off.

        Returns
        -------
        bool
            True if the emergency stop was executed successfully.
        """
        RCTDigital5.EMERGENCY_STOP_REQUEST = True

        self.stop_heating()
        self.stop_stirring()
        logger.critical("Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
        return True
