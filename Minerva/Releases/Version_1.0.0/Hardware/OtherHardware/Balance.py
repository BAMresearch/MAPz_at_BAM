#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2022, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "0.9.1"
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

from Minerva.API.HelperClassDefinitions import TaskGroupSynchronizationObject, PathNames, Hardware

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


class KernADJ(Hardware):
    """
    Class for communication with the Kern ADJ Balance.

    Parameters
    ----------
    com_port : str
        The COM Port the balance is connected to.

    Raises
    ------
    TimeoutError
        If the Balance is not responding to a query of the current weight within 1 s.
    """
    EMERGENCY_STOP_REQUEST: bool = False

    def __init__(self, com_port: str):
        """
        Constructor for the KernADJ Class for communication with the Kern ADJ balance.

        Parameters
        ----------
        com_port : str
            The COM Port the balance is connected to.

        Raises
        ------
        TimeoutError
            If the balance is not responding to a query of the current weight within the timeout.
        """
        super().__init__()
        self.com_port = str(com_port).upper()
        self.baud_rate = 9600
        self.parity = serial.PARITY_NONE
        self.byte_size = 8
        self.stop_bit = 1
        self.timeout = 1
        self.retries = 3
        self.eol = b'\r\n'
        self._com_port_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.com_port = 'COM' + self.com_port

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)

        i = 0
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('W\r\n'.encode())
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r != '':
                    logger.info(f'Connected to Kern Balance on {self.com_port}.', extra=self._logger_dict)
                    break
            except TimeoutError:
                logging.warning(f'Timed out while connecting to balance. Retrying... ({i}/{self.retries_connect})')
                continue  # try again (maximum self.retries times)

        if i == self.retries-1:
            logger.critical(f'Kern ADJ not responding on port {self.com_port}.', extra=self._logger_dict)
            self.ser.close()
            raise TimeoutError(f'Kern ADJ not responding on port {self.com_port}.')

    def get_weight(self, log: bool = True) -> str:
        """
        Returns the current weight (same as pressing the "Print" Button).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        str
            The current weght in the form <S S/S D> <+/-> <weight> <unit> (S S: Stable; S D: Unstable)
        """
        if KernADJ.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.write('W\r\n'.encode())
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
        if r != '':
            if log:
                logger.info(f'Weight: {r}', extra=self._logger_dict)
            return r
        return ''

    def tare(self) -> bool:
        """
        Tares the Balance (same as pressing the "Tare" Button).

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if KernADJ.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.write('T\r\n'.encode())
            return True
        return False

    def calibrate(self) -> bool:
        """
        Triggers the internal calibration of the Balance (same as pressing the "Cal" Button).

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if KernADJ.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.write('C\r\n'.encode())
            return True
        return False

    def toggle_on_off(self) -> bool:
        """
        Turns the balance on/off (same as pressing the "On/Off" Button).

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if KernADJ.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.write('O\r\n'.encode())
            return True
        return False

    def change_mode(self) -> bool:
        """
        Changes the Modes (same as pressing the "Mode" Button).

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if KernADJ.EMERGENCY_STOP_REQUEST:
            return ''

        with self._com_port_lock:
            self.ser.write('M\r\n'.encode())
            return True
        return False
