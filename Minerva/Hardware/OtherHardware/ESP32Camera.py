#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

from PIL import Image
from io import BytesIO
import struct

import socket
import select
import logging
import os.path

from typing import Union, List

# Create a custom logger and set it to the lowest level
from Minerva.API.HelperClassDefinitions import Hardware, HardwareTypeDefinitions, PathNames

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


class Camera(Hardware):
    """
    Class for communication with an ESP32 Camera via Bluetooth.

    Parameters
    ----------
    mac_address : str
        The MAC address of the ESP32 Board.
    port : int, default=1
        The port number for communication (default is 1)
    buffer_size : int, default = 4096
        The buffer size used for Bluetooth communication (default is 4096)

    Raises
    ------
    TimeoutError
        If the Board is not responding via Bluetooth.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, mac_address: str, port: int = 1, buffer_size: int = 4096):
        """
        Constructor for the Camera Class for communication with an ESP32 Camera via Bluetooth.

        Parameters
        ----------
        mac_address : str
            The MAC address of the ESP32 Board.
        port : int, default=1
            The port number for communication (default is 1)
        buffer_size : int, default = 4096
            The buffer size used for Bluetooth communication (default is 4096)

        Raises
        ------
        TimeoutError
            If the Board is not responding via Bluetooth.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.CameraHardware)
        self.eoi = b'\xFF\xD9'  # End of image in a jpeg file
        self.eol = b'\n'  # Used at the end of outgoing messages
        self.delimiter = b'<DELIMITER>'  # Used at the beginning and end of incoming messages
        self.mac_address = mac_address.lower()
        self.port = port
        self.buffer_size = buffer_size
        self.timeout = 2  # Timeout when waiting for incoming Bluetooth packages in seconds
        self.retries = 3
        self._logger_dict = {'instance_name': str(self)}

        self.socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.socket.connect((self.mac_address, self.port))

        i = 0
        for i in range(0, self.retries):
            try:
                if self.get_camera_status():
                    logger.info(f'Connected to ESP32 Camera {self.mac_address} via Bluetooth.', extra=self._logger_dict)
                    break
            except TimeoutError:
                continue  # try again (maximum self.retries times)

        if i == self.retries-1:
            logger.info(f'Error: ESP32 Camera {self.mac_address} not responding via Bluetooth.', extra=self._logger_dict)
            self.socket.close()
            raise TimeoutError

    def get_camera_status(self) -> bool:
        """
        Method to query the status of the camera.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if Camera.EMERGENCY_STOP_REQUEST:
            return False

        self.send_message('GET STATUS')
        msg = self.read_message()
        if msg[0].startswith('CAMERA STATUS: '):
            logger.debug(msg[0], extra=self._logger_dict)
            return True
        else:
            logger.critical(f'Error getting camera status of camera {self.mac_address}.', extra=self._logger_dict)
            return False

    def take_picture(self, use_flash: bool = False) -> Union[Image.Image, None]:
        """
        Method to take a picture with the camera.

        Parameters
        ----------
        use_flash : bool (default = False)
            Whether to use the flashlight when taking the picture (default is False)

        Returns
        -------
        Union[Image, None]
            The taken image if successful, None otherwise
        """
        if Camera.EMERGENCY_STOP_REQUEST:
            return None

        if use_flash:
            if not self.turn_led_on():
                logger.warning(f'Failed to use flash for taking the picture.', extra=self._logger_dict)

        self.send_message('TAKE PICTURE')
        msg = self.read_message()
        if len(msg) < 2:  # Should return 2 elements, the image and a confirmation/error String. If only one is returned, check again for the remaining one
            msg.append(self.read_message()[0])
        if len(msg) < 2 or msg[0] == 'ERROR TAKING PICTURE' or msg[1] == 'ERROR TAKING PICTURE':
            logger.warning(f'Error taking picture on camera {self.mac_address}.', extra=self._logger_dict)
            if use_flash:
                if not self.turn_led_off():
                    logger.warning(f'Failed to use flash for taking the picture.')
            return None
        if msg[1] != 'PICTURE TAKEN' or not isinstance(msg[0], Image.Image):
            logger.warning(f'Unexpected return value after taking a picture.', extra=self._logger_dict)
            if use_flash:
                if not self.turn_led_off():
                    logger.warning(f'Failed to use flash for taking the picture.', extra=self._logger_dict)
            return None

        logger.debug(f'Picture taken on camera {self.mac_address}.', extra=self._logger_dict)
        if use_flash:
            if not self.turn_led_off():
                logger.warning(f'Failed to use flash for taking the picture.', extra=self._logger_dict)

        return msg[0]

    def turn_led_on(self) -> bool:
        """
        Method to turn the LED light on.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command='LED ON', expected_answer='LED TURNED ON')

    def turn_led_off(self) -> bool:
        """
        Method to turn the LED light off.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command='LED OFF', expected_answer='LED TURNED OFF')

    def set_framesize(self, framesize: int = 13) -> bool:
        """
        Method to set the frame size of the camera.

        Parameters
        ----------
        framesize : int, default = 13
            The new framesize (0 to 13 with larger numbers meaning higher resolution). Default is 13

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'FRAMESIZE {framesize}', expected_answer=f'FRAMESIZE CHANGED TO {framesize}')

    def set_exposure(self, exposure: int = 0) -> bool:
        """
        Method to set the exposure of the camera.

        Parameters
        ----------
        exposure : int, default = 0
            The new exposure (0-1200, 0 means auto exposure). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'EXPOSURE {exposure}', expected_answer=f'EXPOSURE CHANGED TO {exposure}')

    def set_gain(self, gain: int = 0) -> bool:
        """
        Method to set the gain of the camera.

        Parameters
        ----------
        gain : int, default = 0
            The new gain (0-30, 0 means auto gain). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'GAIN {gain}', expected_answer=f'GAIN CHANGED TO {gain}')

    def set_auto_white_balance(self, auto_white_balance: int = 1) -> bool:
        """
        Method to set the auto white balance of the camera.

        Parameters
        ----------
        auto_white_balance : int, default = 1
            The new auto_white_balance (0-1, 0 means off, 1 means on). Default is 1.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'AWB {auto_white_balance}', expected_answer=f'AWB CHANGED TO {auto_white_balance}')

    def set_white_balance_mode(self, white_balance_mode: int = 0) -> bool:
        """
        Method to set the white_balance_mode of the camera (if awb_gain enabled).

        Parameters
        ----------
        white_balance_mode : int, default = 0
            The new white_balance_mode (0-4, 0 - Auto, 1 - Sunny, 2 - Cloudy, 3 - Office, 4 - Home). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'WB_MODE {white_balance_mode}', expected_answer=f'WB_MODE CHANGED TO {white_balance_mode}')

    def set_brightness(self, brightness: int = 0) -> bool:
        """
        Method to set the brightness of the camera.

        Parameters
        ----------
        brightness : int, default = 0
            The new brightness (-2 to 2). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'BRIGHTNESS {brightness}', expected_answer=f'BRIGHTNESS CHANGED TO {brightness}')

    def set_saturation(self, saturation: int = 0) -> bool:
        """
        Method to set the saturation of the camera.

        Parameters
        ----------
        saturation : int, default = 0
            The new saturation (-2 to 2). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'SATURATION {saturation}', expected_answer=f'STURATION CHANGED TO {saturation}')

    def set_contrast(self, contrast: int = 0) -> bool:
        """
        Method to set the contrast of the camera.

        Parameters
        ----------
        contrast : int, default = 0
            The new contrast (-2 to 2). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'CONTRAST {contrast}', expected_answer=f'CONTRAST CHANGED TO {contrast}')

    def set_sharpness(self, sharpness: int = 0) -> bool:
        """
        Method to set the sharpness of the camera.

        Parameters
        ----------
        sharpness : int, default = 0
            The new sharpness (-2 to 2). Default is 0.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'SHARPNESS {sharpness}', expected_answer=f'SHARPNESS CHANGED TO {sharpness}')

    def set_vertical_flip(self, vertical_flip: int = 0) -> bool:
        """
        Method to set the vertical flip of the camera.

        Parameters
        ----------
        vertical_flip : int, default = 0
            The new vertical flip value (0-1, 0 means off, 1 means on). Default is 1.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'VFLIP {vertical_flip}', expected_answer=f'VFLIP CHANGED TO {vertical_flip}')

    def set_horizontal_flip(self, horizontal_flip: int = 0) -> bool:
        """
        Method to set the horizontal flip of the camera.

        Parameters
        ----------
        horizontal_flip : int, default = 0
            The new horizontal flip value (0-1, 0 means off, 1 means on). Default is 1.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        return self._execute_command(command=f'HFLIP {horizontal_flip}', expected_answer=f'HFLIP CHANGED TO {horizontal_flip}')

    def _execute_command(self, command: str, expected_answer: str) -> bool:
        """
        Convenience method for sending a command to the camera and checking the answer against an expected outcome.

        Parameters
        ----------
            command : str
                The command that is sent to the camera
            expected_answer : str
                The expected answer to this command from the camera

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if Camera.EMERGENCY_STOP_REQUEST:
            return False
        self.send_message(command)
        msg = self.read_message()[0]
        if msg != expected_answer:
            logger.warning(f'Unexpected answer for command {command}: {msg}', extra=self._logger_dict)
            return False
        else:
            logger.debug(f'{msg[0]}{msg[1:].lower()} on camera {self.mac_address}.', extra=self._logger_dict)
        return True

    def read_message(self) -> List[Union[str, Image.Image]]:
        """
        Method to read incoming messages from an ESP32 Camera via Bluetooth.

        Returns
        -------
        List[Union[str, Image.Image]]
            An array with String messages and/or PIL Images received via Bluetooth
        """
        if Camera.EMERGENCY_STOP_REQUEST:
            return []

        data = b''
        rec = b''
        ret = []
        read_sockets, _, _ = select.select([self.socket], [], [], self.timeout)
        while read_sockets:
            sock = read_sockets[0]
            if sock == self.socket:  # Incoming message from remote server to opened socket
                data = sock.recv(self.buffer_size)
                if not data:
                    logger.critical('ERROR: Disconnected from server.', extra=self._logger_dict)
                    raise TimeoutError
                else:
                    rec += data
                if data.endswith(self.delimiter) and len(rec) != len(self.delimiter):
                    for m in rec.split(self.delimiter):
                        if len(m) == 0:
                            continue
                        if self.eoi in m:  # Image data
                            ret.append(Image.open(BytesIO(m)))
                        else:  # Message
                            if b'CAMERA STATUS: ' in m:
                                fmt = "<L2?B4b7BbxH11B3x"
                                ret.append('CAMERA STATUS: ' + repr(struct.unpack(fmt, m.replace(b'CAMERA STATUS: ', b''))))
                            else:
                                ret.append(m.decode())
                    break
                else:
                    read_sockets, _, _ = select.select([self.socket], [], [], self.timeout)  # Check if there is more waiting...

        if not rec.startswith(self.delimiter):
            logger.warning('Invalid beginning of message delimiter. Expect previous and current message to be corrupted.', extra=self._logger_dict)
        if not data.endswith(self.delimiter):
            logger.warning('Timeout occurred while waiting for end of message delimiter. Expect last and following message to be corrupted.', extra=self._logger_dict)

        return ret

    def send_message(self, message: str) -> None:
        """
        Method to send messages to an ESP32 Camera via Bluetooth.

        Parameters
        ----------
        message : str
            The message to be sent.
        """
        if Camera.EMERGENCY_STOP_REQUEST:
            return

        self.socket.send(message.encode() + self.eol)
