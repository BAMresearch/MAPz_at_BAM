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
import os.path

import serial
import datetime
import logging
from typing import Tuple, Optional

from Minerva.API.HelperClassDefinitions import SonicatorHardware, BathSonicatorErrorFlags, BathSonicatorStatusFlags, TaskScheduler, TaskGroupSynchronizationObject, PathNames


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


class SonorexDigitecHRC(SonicatorHardware):
    """
    Class for communication with the Bandelin Sonorex Digitec H-RC Bath Sonicator via RS-232/infrared

    Parameters
    ----------
    com_port : str
        The COM Port the Bath Sonicator is connected to.

    Raises
    ------
    TimeoutError
        If the Sonicator is not responding on the specified COM Port within 1 sec to a query of its Programming Board Version.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, com_port: str):
        """
        Constructor of the SonorexDigitecHRC Class for communication with the Bandelin Sonorex Digitec H-RC Bath Sonicator via RS-232/infrared.

        Parameters
        ----------
        com_port : str
            The COM Port the Bath Sonicator is connected to.

        Raises
        ------
        TimeoutError
            If the Sonicator is not responding on the specified COM Port within 1 sec to a query of its Programming Board Version.
        """
        super().__init__()
        self.eol = b'\x0D\x0A'
        self.com_port = str(com_port).upper()
        self.baud_rate = 9600
        self.parity = serial.PARITY_EVEN
        self.byte_size = 7
        self.stop_bit = 1
        self.timeout = 0.5
        self.retries = 5
        self._com_port_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.com_port = 'COM' + self.com_port

        # For some reason (possibly the device going into standby mode) the connection often only works after the second attempt
        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)
        with self._com_port_lock:
            self.ser.write('#V\r'.encode())
            self.ser.readall()
            self.ser.close()

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)
        with self._com_port_lock:
            self.ser.reset_output_buffer()
            self.ser.reset_input_buffer()

        i = 0
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#V\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.lower().startswith('v'):
                    logger.info('Connected to Bath Sonicator on {}.'.format(self.com_port), extra=self._logger_dict)
                    break
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        if i == self.retries-1:
            logger.critical('Bath Sonicator not responding on port {}.'.format(self.com_port), extra=self._logger_dict)
            self.ser.close()
            raise TimeoutError('Bath Sonicator not responding on port {}.'.format(self.com_port))

    @TaskScheduler.scheduled_task
    def start_sonication(self, sonication_time: Optional[float] = None, sonication_power: Optional[float] = None, sonication_amplitude: Optional[float] = None, sonication_temperature: Optional[float] = 20, log: bool = True, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Starts the sonication with the supplied or previously set setpoints.

        Parameters
        ----------
        sonication_time: Optional[float] = None
            The amount of time for which the container is sonicated (in seconds)
        sonication_power: Optional[float] = None
            Not supported by this device
        sonication_amplitude: Optional[float] = None
            Not supported by this device
        sonication_temperature: Optional[float] = 20
            The temperature at which this container is sonicated (in degrees Celsius)
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
            True if successful, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        if sonication_time is not None:
            if self.set_time_setpoint(int(sonication_time)) != -1:
                return False
        if sonication_temperature is not None:
            if self.set_temperature_setpoint(sonication_temperature) == -1:
                return False
        if log:
            logger.info('Starting sonication...', extra=self._logger_dict)

        time.sleep(sonication_time)

        ret = self.ultrasound_off()

        if log:
            logger.info('Finished sonication.', extra=self._logger_dict)
        return ret

    def set_temperature_setpoint(self, setpoint: float, log: bool = True) -> float:
        """
        Set the temperature setpoint (in degrees Celsius).

        Parameters
        ----------
        setpoint : float
            The temperature to which the sonicator should heat (in degrees Celsius).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new temperature setpoint if the change was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Hn{}\r'.format(hex(int(setpoint * 256)).replace('0x', '').upper()).encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'hn{}'.format(hex(int(setpoint * 256)).replace('0x', '')):
                    if log:
                        logger.info('Temperature setpoint set to {} degrees Celsius'.format(setpoint), extra=self._logger_dict)
                    return setpoint
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Temperature setpoint not changed.', extra=self._logger_dict)
        return -1

    def get_temperature_setpoint(self, log: bool = True) -> float:
        """
        Get the temperature setpoint (in degrees Celsius).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The current temperature setpoint (in degrees Celsius) if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Hn\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('hn'):
                    setpoint = round(int(r.replace(' ', '').lower()[2:], 16) / 256, 1)
                    if log:
                        logger.info('Temperature setpoint is {} degrees Celsius'.format(setpoint), extra=self._logger_dict)
                    return setpoint
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying temperature setpoint.', extra=self._logger_dict)
        return -1

    def get_current_temperature(self, log: bool = True, is_polling: bool = False) -> float:
        """
        Get the current temperature (in degrees Celsius).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            Whether the request is part of a regular polling request. If so, do not wait on the communication lock if the hardware is busy and just return immediately. Default is False.

        Returns
        -------
        float
            The current temperature (in degrees Celsius) if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                if not self._com_port_lock.acquire(blocking=not is_polling):
                    return -1
                self.ser.write('#Hm\r'.encode())
                self.ser.flush()
                r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                self._com_port_lock.release()
                if r.replace(' ', '').lower().startswith('hm'):
                    temp = round(int(r.replace(' ', '').lower()[2:], 16) / 256, 1)
                    if log:
                        logger.info('Current temperature is {} degrees Celsius'.format(temp), extra=self._logger_dict)
                    return temp
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying current temperature.', extra=self._logger_dict)
        return -1

    def turn_heating_off(self, log: bool = True) -> bool:
        """
        Turn the heating off (setpoint 0000). Change the setpoint to switch it back on.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#H0\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'h0':
                    if log:
                        logger.info('Heating turned off.', extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error turning heating off.', extra=self._logger_dict)
        return False

    def set_time_setpoint(self, setpoint: int, log: bool = True) -> int:
        """
        Set the time setpoint (in seconds). Determines for how long the ultrasound will be running once powered on. 0000 means continuous operation. Maximum Value is 65535 s (ca. 18h)

        Parameters
        ----------
        setpoint : int
            How long the ultrasound will be running once powered on (in seconds). Value between 0 (continuous) and 65535.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The new time setpoint (in seconds) if the change was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        if setpoint > 0xFFFF:
            logger.warning('Maximum value is {} seconds. Time not changed.'. format(int(0xFFFF)), extra=self._logger_dict)
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Tn{}\r'.format(hex(int(setpoint)).replace('0x', '').upper()).encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'tn{}'.format(hex(int(setpoint)).replace('0x', '')):
                    if log:
                        logger.info('Time setpoint set to {} seconds (i.e., {})'.format(setpoint, str(datetime.timedelta(seconds=setpoint))), extra=self._logger_dict)
                    return setpoint
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Time setpoint not changed.', extra=self._logger_dict)
        return -1

    def get_time_setpoint(self, log: bool = True) -> int:
        """
        Get the time setpoint (in seconds). Determines for how long the ultrasound will be running once powered on. 0 means continuous operation. Maximum Value is 65535 s (ca. 18h)

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The time setpoint (in seconds) if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Tn\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('tn'):
                    setpoint = int(r.replace(' ', '').lower()[2:], 16)
                    if log:
                        logger.info('Time setpoint is {} seconds (i.e., {})'.format(setpoint, str(datetime.timedelta(seconds=setpoint))), extra=self._logger_dict)
                    return setpoint
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying time setpoint.', extra=self._logger_dict)
        return -1

    def get_elapsed_time(self, log: bool = True) -> int:
        """
        Get the elapsed time (in seconds) since the ultrasound was powered on.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The elapsed time (in seconds) since the ultrasound was powered on if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Tm\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('tm'):
                    elapsed_time = int(r.replace(' ', '').lower()[2:], 16)
                    if log:
                        logger.info('Elapsed time is {} seconds (i.e., {})'.format(elapsed_time, str(datetime.timedelta(seconds=elapsed_time))), extra=self._logger_dict)
                    return elapsed_time
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying elapsed time.', extra=self._logger_dict)
        return -1

    def ultrasound_on(self, degas: bool = False, log: bool = True) -> bool:
        """
        Turns the ultrasound on for the time specified in the time setpoint. It can be specified whether the ultrasound should run in "normal" mode (default), or "degas" mode.

        Parameters
        ----------
        degas : bool, default=False
            Whether the ultrasound should be set to degas mode (default is False).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the operation mode (normal or degas) was set correctly and the ultrasound was switched on, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        i = 0
        for i in range(0, self.retries):
            try:
                if degas:
                    with self._com_port_lock:
                        self.ser.write('#Tp1\r'.encode())
                        self.ser.flush()
                        r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                else:
                    with self._com_port_lock:
                        self.ser.write('#Tp0\r'.encode())
                        self.ser.flush()
                        r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('tp'):
                    break
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        if i == self.retries-1:
            logger.error('Error setting degassing to {}. Ultrasound not turned on.'.format(degas), extra=self._logger_dict)
            return False

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#P1\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'p1':
                    if log:
                        logger.info('Ultrasound turned on.', extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error turning ultrasound on.', extra=self._logger_dict)
        return False

    def ultrasound_off(self, log: bool = True) -> bool:
        """
        Turns the ultrasound off (to standby).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the ultrasound was switched off, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#P0\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'p0':
                    if log:
                        logger.info('Ultrasound off.', extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error turning ultrasound off.', extra=self._logger_dict)
        return False

    def ultrasound_standby(self, log: bool = True) -> bool:
        """
        Turns the ultrasound to standby. Can only be reactivated from button presses.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the ultrasound was switched to standby, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Pz\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'pz':
                    if log:
                        logger.info('Ultrasound switched to standby. Reactivate manually by pressing a button.', extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error switching ultrasound to standby.', extra=self._logger_dict)
        return False

    def reset_and_standby(self, log: bool = True) -> bool:
        """
        Resets the device and turns it to standby. Can only be reactivated from button presses.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the device was reset and set to standby, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#X\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if 'rst_sr:' in r.replace(' ', '').lower():
                    if log:
                        logger.info('Device reset and set to standby. Reactivate manually by pressing a button.', extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error resetting device.', extra=self._logger_dict)
        return False

    def turn_off(self, log: bool = True) -> bool:
        """
        Turns the device to standby. Can only be reactivated manually by pressing the power on button.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the device was powered off, False otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return False

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Zz\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'zz':
                    if log:
                        logger.info('Device turned off. Switch back on manually.', extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error turning device off.', extra=self._logger_dict)
        return False

    def set_remote_control_timeout(self, timeout: int, log: bool = True) -> int:
        """
        Sets the timeout (in seconds) for the remote control of the device. If no signal is received for the specified time via infrared, the device is switched OFF (STANDBY). Set to 0 to disable timeout. Maximum value is 255 s (ca. 4 min).

        Parameters
        ----------
        timeout : int
            Timeout (in seconds) for receiving an infrared signal. Value between 0 (diabled) and 255.
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The new timeout (in seconds) if the change was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        if timeout > 0xFF:
            logger.warning('Maximum value is {} seconds. Timeout not changed.'. format(int(0xFF)), extra=self._logger_dict)
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Tt{}\r'.format(hex(int(timeout)).replace('0x', '').upper()).encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'tt{}'.format(hex(int(timeout)).replace('0x', '')):
                    if log:
                        logger.info('Remote control timeout set to {} seconds (i.e., {})'.format(timeout, str(datetime.timedelta(seconds=timeout))), extra=self._logger_dict)
                    return timeout
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

            logger.error('Remote control timeout not changed.', extra=self._logger_dict)
            return -1

        return timeout

    def get_remote_control_timeout(self, log: bool = True) -> int:
        """
        Gets the timeout (in seconds) for the remote control of the device. If no signal is received for the specified time via infrared, the device is switched OFF (STANDBY).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The timeout (in seconds) if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Tt\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('tt'):
                    timeout = int(r.replace(' ', '').lower()[2:], 16)
                    if log:
                        logger.info('Remote control timeout is {} seconds (i.e., {})'.format(timeout, str(datetime.timedelta(seconds=timeout))), extra=self._logger_dict)
                    return timeout
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying remote control timeout.', extra=self._logger_dict)
        return -1

    def get_remaining_time_to_remote_control_timeout(self, log: bool = True) -> int:
        """
        Gets the remaining time (in seconds) until the remote control timeout is reached.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        int
            The remaining time (in seconds) until the remote control timeout is reached if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Ts\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('ts'):
                    remaining_time = int(r.replace(' ', '').lower()[2:], 16)
                    if log:
                        logger.info('Time to remote control timeout is {} seconds (i.e., {})'.format(remaining_time, str(datetime.timedelta(seconds=remaining_time))), extra=self._logger_dict)
                    return remaining_time
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying time to remote control timeout.', extra=self._logger_dict)
        return -1

    def get_current_operating_time(self, log: bool = True) -> Tuple[int, int]:
        """
        Gets the current operating time (in seconds), i.e. for how long the device and the ultrasound has been switched on.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        Tuple[int, int]
            The time (in seconds) for how long the device and ultrasound have currently been switched on if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1, -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Tl\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('tl'):
                    r = r[2:].strip().lower().split(' ')
                    power_on_time = int(r[0], 16)
                    us_on_time = int(r[1], 16)
                    if log:
                        logger.info('Current power on time is {} seconds (i.e., {}), current ultrasound time is {} seconds (i.e., {})'.format(power_on_time, str(datetime.timedelta(seconds=power_on_time)), us_on_time, str(datetime.timedelta(seconds=us_on_time))), extra=self._logger_dict)
                    return power_on_time, us_on_time
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying current operating time.', extra=self._logger_dict)
        return -1, -1

    def get_total_operating_time(self, log: bool = True) -> Tuple[int, int]:
        """
        Gets the total operating time (in seconds), i.e. for how long the device and the ultrasound has been switched on in total.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        Tuple[int, int]
            The time (in seconds) for how long the device and ultrasound have been switched on in total if the query was successful, -1 otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return -1, -1

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Th\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('th'):
                    r = r[2:].strip().lower().split(' ')
                    power_on_time = int(r[0], 16)
                    us_on_time = int(r[1], 16)
                    if log:
                        logger.info('Total power on time is {} seconds (i.e., {}), total ultrasound time is {} seconds (i.e., {})'.format(power_on_time, str(datetime.timedelta(seconds=power_on_time)), us_on_time, str(datetime.timedelta(seconds=us_on_time))), extra=self._logger_dict)
                    return power_on_time, us_on_time
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying total operating time.', extra=self._logger_dict)
        return -1, -1

    def get_serial_number(self, log: bool = True) -> str:
        """
        Gets the serial number of the device. Not available for all instruments.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
            The serial number of the device in the format [zz] [d]ddd.dddddddd.ddd (z: Alphanumeric character, d: Numeric character)
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return ''

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#I\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('i'):
                    if log:
                        logger.info('Serial Number: {}'.format(r[1:].lstrip()), extra=self._logger_dict)
                    return r[1:].lstrip()
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying serial number.', extra=self._logger_dict)
        return ''

    def get_board_version(self, log: bool = True) -> str:
        """
        Gets the version of the programming board of the device.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
            The version of the programming board of the device in the format <Version - Date>: dd.dd - MMM DD YYYY (d: Numeric character)
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return ''

        for _ in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#V\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('v'):
                    if log:
                        logger.info('Programming board version version: {}'.format(r[1:].lstrip()), extra=self._logger_dict)
                    return r[1:].lstrip()
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.error('Error querying programming board version.', extra=self._logger_dict)
        return ''

    def get_error_bits(self, log: bool = True) -> str:
        """
        Gets the error bits.

        Bit Meaning
        0   <Not Assigned>
        1   Error in Temperature Sensor
        2   <Not Assigned>
        3   Transmission Error
        4   <Not Assigned>
        5   <Not Assigned>
        6   <Not Assigned>
        7   <Not Assigned>

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
            A string with the binary representation of the error byte if the query was successful, '' otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return ''

        i = 0
        r = ''
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('#Je\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower().startswith('je'):
                    break
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        if i == self.retries-1:
            logger.error('Error querying error bits.', extra=self._logger_dict)
            return ''
        else:
            error_bits = int(r.replace(' ', '')[2:], 16)
            if error_bits == 0:
                if log:
                    logger.info('No Error Bits set')
            else:
                errors = ['Error bits are {}:'.format(bin(error_bits)).replace('0b', '')]
                for field in BathSonicatorErrorFlags:
                    flag, meaning = field.value
                    if flag & error_bits:
                        errors.append('Error bit <{}> for {} is set.'.format(int(math.log2(flag)), meaning))
                logger.warning(' '.join(errors), extra=self._logger_dict)
            return bin(error_bits).replace('0b', '')

    def get_status_bits(self, log: bool = True, is_polling: bool = False) -> str:
        """
        Gets the status bits.

        Bit Meaning
        0   <reserved> Remote Control
        1   <reserved> Service Mode
        2   Ultrasound or Degas started
        3   Degas on
        4   <reserved> Heating Regulation
        5   Interruption of Ultrasound output (pause)
        6   Standby
        7   <Not Assigned>

        8   Ultrasound Power Output (current output)
        9   Heating power output
        10  Calibration function: 20ms
        11  <Not Assigned>
        12  <Not Assigned>
        13  <Not Assigned>
        14  <Not Assigned>
        15  Service Function 'full access'

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            Whether the request is part of a regular polling request. If so, do not wait on the communication lock if the hardware is busy and just return immediately. Default is False.

        Returns
        -------
        str
            A string with the binary representation of the status bytes if the query was successful, '' otherwise.
        """
        if SonorexDigitecHRC.EMERGENCY_STOP_REQUEST:
            return ''

        i = 0
        r = ''
        for i in range(0, self.retries):
            try:
                if not self._com_port_lock.acquire(blocking=not is_polling):
                    return ''
                with self._com_port_lock:
                    self.ser.write('#Js\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                self._com_port_lock.release()
                if r.replace(' ', '').lower().startswith('js'):
                    break
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        if i == self.retries-1:
            logger.error('Error querying status bits.', extra=self._logger_dict)
            return ''
        else:
            status_bits = int(r.replace(' ', '')[2:], 16)
            if status_bits == 0:
                if log:
                    logger.info('No Status Bits set', extra=self._logger_dict)
            else:
                status = ['Status bits are {}:'.format(bin(status_bits).replace('0b', ''))]
                for field in BathSonicatorStatusFlags:
                    flag, meaning = field.value
                    if flag & status_bits:
                        status.append('Status bit <{}> for {} is set.'.format(int(math.log2(flag)), meaning))
                if log:
                    logger.info(' '.join(status), extra=self._logger_dict)
            return bin(status_bits).replace('0b', '')

    def emergency_stop(self) -> bool:
        """
        Switches the device off.

        Returns
        -------
        bool
            True if the emergency stop was executed successfully.
        """
        SonorexDigitecHRC.EMERGENCY_STOP_REQUEST = True

        for _ in range(0, 500):
            try:
                with self._com_port_lock:
                    self.ser.write('#Zz\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r.replace(' ', '').lower() == 'zz':
                    logger.critical("Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
                    return True
            except (UnicodeDecodeError, AttributeError):
                continue     # Due to a probable transmission error, attempt again (up to a maximum of self.retries times)

        logger.critical("Error while executing emergency stop protocol.", extra=self._logger_dict)
        return False


# Telegram structure:
# Send:
# =====
# #Instruction<CR>
#
# An instruction starts with a character for the instruction group (e.g. Q for frequency). For ease of distinction, upper case is used for the instruction group in this documentation.
# T Time
# P Power
# H Temperature (Heating)
#
# The character for the instruction is followed by a differentiation character. The meaning of the differentiation character is generally the same for each instruction group.
# n nominal is the value that is specified as a (temporary) target value for control in the current operation. Generally speaking, it reverts to the reset value after resetting and can then be (temporarily) changed in operation
# m actual value is the current measured value. It cannot be changed by the user and is thus read-only.
#
# Instead of the differentiation character, the functions OFF an ON may be realized by means of 0 and 1 (switch instructions)
# Examples:
#     P1 Power (ultrasound) ON
#     Tm query passed time
#     Hn set temperature
#
# All values are transferred in hexadecimal notation
#
# Receive (Echo):
# ===============
# Instruction(echo)[value]<CR><LF>
#
# Instruction set (h -> hexadecimal number, z -> Alphanumeric character, d -> Numeric character)
# Instruction         Meaning                             Comment
# Hn hhhh             Set temperature setpoint            Unit: °C/256. Example: #Hn1A80<CR> -> Set temperature to 6784/256 = 26.5°C. Can only be changed when the instrument is on (not in standby); 0000 means OFF
# Hn                  Query temperature setpoint          Reply: Hn hhhh; Unit: °C/256 (in hexadecimal)
# Hm                  Query actual temperature            Reply: Hm hhhh; Unit: °C/256 (in hexadecimal) -> Can also be queried in standby
# H0                  Switch Heating OFF (setpoint 0000)  Turn back on by setting as new setpoint
# I                   Identification (Serial Number)      Reply: I [zz] [d]ddd.dddddddd.ddd; not available for all instruments
# Je                  Query Error-Bytes                   Reply: Je hhhh
# Js                  Query Status-Bytes                  Reply: Js hhhh
# P0 | 1 | z          Turn Power OFF | ON | STANDBY       Turn Power OFF | ON | STANDBY
# Tn hhhh             Set ultrasound time setpoint        Unit: sec; Tn0[000] -> continuous; TnFFFF -> 18 h (Attention: the DIGITEC RC switches to STANDBY after 8 h without button presses)
# Tn                  Query ultrasound time setpoint      Unit: sec; Tn0[000] -> continuous; TnFFFF -> 18 h (Attention: the DIGITEC RC switches to STANDBY after 8 h without button presses)
# Tm                  Query elapsed ultrasound time       Reply: Tm hhhh; Unit: sec; Time remains after stop (P0) and is only reset after start_somication
# Tp 0 | 1            Degas OFF | ON                      Tp1 has to be sent together with P1, i.e., Tp1<CR>P1<CR> or P1<CR>Tp1<CR>
# Tt hh               Set timeout for remote control      Unit: sec; If no signal is received for the specified time via infrared, the device is switched OFF (STANDBY). Tt0 -> disable timeout
# Tt                  Query timeout for remote control    Reply: Tt hh; Unit: sec
# Tl                  Current operating time (Power+US)   Reply: Tl hhhh hhhh; Unit: sec
# Th                  Total operating time (Power+US)     Reply: Th hhhhhhhhh hhhhhhhhh; Unit: sec
# Ts                  Remaining time to Timeout           Reply: Ts hhhhhhhhh; Unit: sec
# V                   Query Version of board              Reply: V dd.dd - MMM DD YYYY -> Version - Date, e.g. 01.01 - Apr 22 2005
# X                   Reset                               Turn OFF (STANDBY). Can only be reactivated from button presses
# Zz                  Turn OFF (without Echo)             Turn OFF (STANDBY). Can only be reactivated from button presses. See also Pz
