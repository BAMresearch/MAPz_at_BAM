#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import queue
import threading

import serial
import logging
import os.path

from typing import Union, Dict

from Minerva.API.HelperClassDefinitions import ControllerHardware, PathNames

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


class LocalPCClient(ControllerHardware):
    """
    Class for creating a local client interface through which a PC controlling different hardware can connect to a server via RS-232 null modem.

    Parameters
    ----------
    com_port : str
        The COM Port used for communication with the server.
    baud_rate : int, default=9600
        The baud Rate for communication with the Arduino (default is 9600).
    parity : str, default=serial.PARITY_NONE
        The parity for communication with the Arduino (default is None).
    byte_size : int, default=8
        The byte size for communication with the Arduino (default is 8).
    stop_bit : int, default=1
        The stop bit for communication with the Arduino (default is 1).
    """

    EMERGENCY_STOP_REQUEST = False

    def __init__(self, com_port: Union[str, int], baud_rate: int = 9600, parity: str = serial.PARITY_NONE, byte_size: int = 8, stop_bit: int = 1):
        """
        Class for creating a local client interface through which a PC controlling different hardware can connect to a server via RS-232 null modem.

        Parameters
        ----------
        com_port : Union[str, int]
            The COM Port used for communication with the server.
        baud_rate : int, default=9600
            The baud Rate for communication with the Arduino (default is 9600).
        parity : str, default=serial.PARITY_NONE
            The parity for communication with the Arduino (default is 9600).
        byte_size : int, default=8
            The byte size for communication with the Arduino (default is 9600).
        stop_bit : int, default=1
            The stop bit for communication with the Arduino (default is 1).
        """
        super().__init__()
        self.com_port = str(com_port).upper()
        self.baud_rate = baud_rate
        self.parity = parity
        self.byte_size = byte_size
        self.stop_bit = stop_bit
        self.eol = b'\r\n'
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.port_number = 'COM' + self.com_port

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit)

        self.ser.timeout = None

        self.read_queue_dict: Dict[str, queue.Queue] = {}
        self.write_queue: queue.Queue = queue.Queue()

        self.reading_thread = threading.Thread(target=self._read_from_comport, daemon=True)
        self.writing_thread = threading.Thread(target=self._write_to_comport, daemon=True)

        self.reading_thread.start()
        self.writing_thread.start()

    def write(self, message: str) -> bool:
        """
        Puts the specified message in the write queue, from where it will be written to the serial port.

        Parameters
        ----------
        message: str
            The message that will be written to the serial port

        Returns
        -------
            True if successful, False otherwise
        """

        self.write_queue.put(message)
        return True

    def get_read_queue(self, prefix: str) -> queue.Queue:
        """
        Creates a queue.Queue object for the specified prefix and returns it. Any messages read from the serial port addressing this prefix will be stored in the queue.

        Parameters
        ----------
        prefix
            The prefix that identifies the hardware to which the message sent by the Arduino controller is addressed (e.g., VALVE1, MAGNET0, CAPPER, ...)

        Returns
        -------
        queue.Queue
            A queue holding all messages read from the serial port that are addressed to the specified prefix.
        """

        if prefix not in self.read_queue_dict.keys():
            self.read_queue_dict[prefix] = queue.Queue()
        return self.read_queue_dict[prefix]

    def _read_from_comport(self) -> None:
        """
        Method for continuously reading from the serial port and putting the messages in the corresponding queue. Run in its own daemon thread.
        """

        while not LocalPCClient.EMERGENCY_STOP_REQUEST:
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
            if '>' in r:
                target = r[:r.find('>')]
                msg = r.replace(f'{target}>', '')
                self.read_queue_dict[target].put(msg)
            elif r.startswith('<'):
                r = r.lstrip('<')
                if r in self.read_queue_dict.keys():
                    self.write_queue.put(f'<{r}\r\n')
                    logger.info(f'Connected hardware {r} to server on {self.com_port}', extra=self._logger_dict)
                else:
                    logger.error(f'Hardware {r} requested by server on {self.com_port} not ready on this machine.', extra=self._logger_dict)
            else:
                logger.info(r, extra=self._logger_dict)

    def _write_to_comport(self) -> None:
        """
        Method for continuously checking the write queue and writing the messages to the serial port. Run in its own daemon thread.
        """
        while not LocalPCClient.EMERGENCY_STOP_REQUEST:
            self.ser.write(self.write_queue.get().encode())
