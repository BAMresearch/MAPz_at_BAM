#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import threading

import serial
import logging
import os.path

from typing import Union

from Minerva.API import MinervaAPI
from Minerva.API.HelperClassDefinitions import Hardware, PathNames

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


class EmergencyStopButton(Hardware):
    """
    Class for connecting to an Emergency Stop Button

    Parameters
    ----------
    com_port : str
        The COM Port the Button is connected to.
    baud_rate : int, default=9600
        The baud Rate for communication with the Button (default is 9600).
    parity : str, default=serial.PARITY_NONE
        The parity for communication with the Button (default is 9600).
    byte_size : int, default=8
        The byte size for communication with the Button (default is 9600).
    stop_bit : int, default=1
        The stop bit for communication with the Button (default is 1).
    msg: str, default='ESR'
        The message that the controller sends to itself to determine whether the switch is open or closed. Default is 'ESR'
    interval: float, default = 100
        The interval (in Milliseconds) for polling the switch state. Default is 100 Milliseconds.
    """

    def __init__(self, com_port: Union[str, int], baud_rate: int = 9600, parity: str = serial.PARITY_NONE, byte_size: int = 8, stop_bit: int = 1, msg: str = 'ESR', interval: int = 1000):
        """
        Class for connecting to an Emergency Stop Button

        Parameters
        ----------
        com_port : str
            The COM Port the Button is connected to.
        baud_rate : int, default=9600
            The baud Rate for communication with the Button (default is 9600).
        parity : str, default=serial.PARITY_NONE
            The parity for communication with the Button (default is 9600).
        byte_size : int, default=8
            The byte size for communication with the Button (default is 9600).
        stop_bit : int, default=1
            The stop bit for communication with the Button (default is 1).
        msg: str, default='ESR'
            The message that the controller sends to itself to determine whether the switch is open or closed. Default is 'ESR'
        interval: float, default = 100
            The interval (in Milliseconds) for polling the switch state. Default is 100 Milliseconds.
        """
        super().__init__()
        self.com_port = str(com_port).upper()
        self.baud_rate = baud_rate
        self.parity = parity
        self.byte_size = byte_size
        self.stop_bit = stop_bit
        self.msg = msg
        self.interval = interval
        self.eol = b'\n'
        self._shutdown = False
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.port_number = 'COM' + self.com_port

        try:
            self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.interval/1000.0)
            logger.info(f'Emergency Stop Button connected on port {self.com_port}.', extra=self._logger_dict)
        except serial.SerialException:
            logger.critical('Emergency Stop Button disconnected.', extra=self._logger_dict)

        self._polling_thread = threading.Thread(target=self._poll, daemon=True)
        self._polling_thread.start()

    def _poll(self) -> None:
        """
        Writes a message to the serial port and checks if it comes back to determine whether the switch is open or closed.

        Returns
        -------
            None
        """
        while not self._shutdown:
            self.ser.write(f'{self.msg}\n'.encode())
            if self.ser.read_until(self.eol).decode().rstrip(self.eol.decode()) == self.msg:
                break

        if not self._shutdown:
            MinervaAPI.Configuration.request_emergency_stop()
