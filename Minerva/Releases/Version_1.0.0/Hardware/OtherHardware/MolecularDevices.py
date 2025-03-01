#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import datetime
import json
import os.path
import queue
import struct
import threading
import time

import logging
from dataclasses import dataclass
from enum import Enum

from typing import Union, Iterable, TYPE_CHECKING, List, Tuple, cast, Any, Optional

# import HelperClassDefinitions
from Minerva.API.HelperClassDefinitions import Hardware, HardwareTypeDefinitions, PathNames
from Minerva.Hardware.ControllerHardware import LocalPCServer, LocalPCClient

# Load the dlls for Controlling the reader
import clr

clr.AddReference("C:/Program Files/Molecular Devices/SoftMax Pro 7.2 Automation SDK/SoftMaxPro.AutomationInterface.dll")
clr.AddReference("C:/Program Files/Molecular Devices/SoftMax Pro 7.2 Automation SDK/SoftMaxPro.AutomationExtensions.dll")
clr.AddReference("C:/Program Files/Molecular Devices/SoftMax Pro 7.2 Automation SDK/SoftMaxPro.AutomationClient.dll")

import SoftMaxPro.AutomationInterface
import SoftMaxPro.AutomationExtensions
import SoftMaxPro.AutomationClient

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


@dataclass
class CallbackObject:
    """
    Dataclass holding items that are required used by asynchronous callback functions to relay the result to the caller:
    queue_id: int
    is_finished: threading.Event
    result: Optional[Union[str, int, float]]
    error: Optional[str]
    status: Optional[str]
    """
    queue_id: int
    is_finished: threading.Event
    result: Optional[Union[str, int, float]] = None
    error: Optional[str] = None
    status: Optional[str] = None


class ExportAsFormat(Enum):
    """
    Enum class with the different export formats.
    TIME exports data in a single column of text for each well.
    COLUMNS exports data in a single column of text for each well.
    PLATE exports data in a text matrix corresponding to a microplate grid.
    XML exports data in an XML file format.
    """
    TIME: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.TIME
    COLUMNS: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.COLUMNS
    PLATE: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.PLATE
    XML: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.XML


class SpectraMaxM3(Hardware):
    """
    SpectraMaxM3 class for automating the plate reader via the .NET dlls providing an API.

    Parameters
    ----------
    local_controller: Union[LocalPCServer, LocalPCClient, None] = None
        A local controller for network communication if the device is not directly connected to this machine. If set to None, it is assumed that the device is directly connected. Default is None.
    network_id: str = ''
        A unique identifier of the instrument on the server and client PC. Only has an effect if a local_controller is used. Default is '', which will result in an automatically chosen ID (however, it is up to the user to ensure that the IDs are unique and the same on the server and client PC).
    """

    class ExportAsFormat(Enum):
        """
        Enum class with the different export formats.
        TIME exports data in a single column of text for each well.
        COLUMNS exports data in a single column of text for each well.
        PLATE exports data in a text matrix corresponding to a microplate grid.
        XML exports data in an XML file format.
        """
        TIME: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.TIME
        COLUMNS: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.COLUMNS
        TEXT: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.TEXT
        XML: SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.XML

    """
    Class for controlling the SpectraMaxM3 via the .NET dlls providing an API.
    """
    EMERGENCY_STOP_REQUEST = False
    PROTOCOL_PATH = 'P:\\Exchange\\Bastian\\Spectramax_M3_Protocols'

    def __init__(self, local_controller: Union[LocalPCServer, LocalPCClient, None] = None, network_id: str = '') -> None:
        """
        Constructor for the SpectraMaxM3 class for automating the plate reader via the .NET dlls providing an API.

        Parameters
        ----------
        local_controller: Union[LocalPCServer, LocalPCClient, None] = None
            A local controller for network communication if the device is not directly connected to this machine. If set to None, it is assumed that the device is directly connected. Default is None.
        network_id: str = ''
            A unique identifier of the instrument on the server and client PC. Only has an effect if a local_controller is used. Default is '', which will result in an automatically chosen ID (however, it is up to the user to ensure that the IDs are unique and the same on the server and client PC).
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.CharacterizationInstrumentHardware)
        self.client: Union[None, Any] = None
        self.local_controller = local_controller
        self._logger_dict = {'instance_name': str(self)}

        if self.local_controller is not None:
            if network_id == '':
                self.network_id = 'SpectraMaxM3'
            else:
                self.network_id = network_id
            self.read_queue = self.local_controller.get_read_queue(self.network_id)

        if not isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.connected = self.connect()
            self.callback_object_list: list[CallbackObject] = []
            self.callback_object_list_lock = threading.Lock()

        if isinstance(self.local_controller, LocalPCClient.LocalPCClient):
            self.command_listener_thread = threading.Thread(target=self._command_listener, daemon=True)
            self.command_listener_thread.start()

    def _command_listener(self) -> None:
        """Method that waits for incoming commands on the client side and dispatches them to the measurement hardware"""
        while not SpectraMaxM3.EMERGENCY_STOP_REQUEST:
            item = self.read_queue.get().split(';')
            cmd = item[0]
            args = json.loads(item[1])

            if cmd == 'disconnect':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.disconnect()) + '\r\n')
            elif cmd == 'close_document':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.close_document()) + '\r\n')
            elif cmd == 'close_all_documents':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.close_all_documents()) + '\r\n')
            elif cmd == 'close_drawer':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.close_drawer()) + '\r\n')
            elif cmd == 'export_as':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.export_as(**args)) + '\r\n')
            elif cmd == 'get_data_copy':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.get_data_copy()) + '\r\n')
            elif cmd == 'get_drawer_status':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.get_drawer_status()) + '\r\n')
            elif cmd == 'get_temperature':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.get_temperature()) + '\r\n')
            elif cmd == 'get_version':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.get_version()) + '\r\n')
            elif cmd == 'new_document':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.new_document()) + '\r\n')
            elif cmd == 'new_experiment':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.new_experiment()) + '\r\n')
            elif cmd == 'new_notes':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.new_notes()) + '\r\n')
            elif cmd == 'new_plate':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.new_plate()) + '\r\n')
            elif cmd == 'open_drawer':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.open_drawer()) + '\r\n')
            elif cmd == 'open_file':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.open_file(**args)) + '\r\n')
            elif cmd == 'quit':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.quit()) + '\r\n')
            elif cmd == 'save_as':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.save_as(**args)) + '\r\n')
            elif cmd == 'shake':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.shake(**args)) + '\r\n')
            elif cmd == 'shake_on':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.shake_on()) + '\r\n')
            elif cmd == 'shake_off':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.shake_off()) + '\r\n')
            elif cmd == 'set_temperature':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.set_temperature(**args)) + '\r\n')
            elif cmd == 'start_read':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.start_read()) + '\r\n')
            elif cmd == 'stop_read':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.stop_read()) + '\r\n')
            elif cmd == 'start_measurement':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.start_measurement(**args)) + '\r\n')
            else:
                logger.warning(f'Invalid command: {cmd} called with args {args}', extra=self._logger_dict)

    def connect(self) -> bool:
        """
        Connect to the Automation Service

        Returns
        -------
        bool
            True if successful, False otherwise

        Raises
        ------
        TimeoutError
            If connecting to the SoftMax Pro Automation Sevice fails.
        """
        self.client = SoftMaxPro.AutomationClient.SMPAutomationClient()
        if self.client.Initialize():
            self.client.ErrorReport += self.spectramax_error
            self.client.CommandCompleted += self.spectramax_command_completed
            self.client.InstrumentStatusChanged += self.spectramax_instrument_status_changed
            logger.info(f'Connected to SpectraMax M3.', extra=self._logger_dict)
            return True
        else:
            logger.critical(f'Could not connect to SpectraMax M3. Make sure the device is switched on and the SoftMax Pro Software is running.', extra=self._logger_dict)
            raise TimeoutError(f'Could not connect to SpectraMax M3.')

    def disconnect(self) -> bool:
        """
        Disconnect from the Automation Service

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>disconnect;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return True

        if self.connected:
            self.client.ErrorReport -= self.spectramax_error
            self.client.CommandCompleted -= self.spectramax_command_completed
            self.client.InstrumentStatusChanged -= self.spectramax_instrument_status_changed
            self.client.Dispose()
        return True

    def spectramax_error(self, sender: object, e: SoftMaxPro.AutomationClient.SMPAutomationClient.ErrorEventArgs)->None:
        """
        Receives errors from the Automation Service and puts them into self.error_queue

        Parameters
        ----------
        sender: object
            The sender of the error message
        e: SoftMaxPro.AutomationClient.SMPAutomationClient.ErrorEventArgs
            The error object
        """
        logger.error(f'Error: Command ID = {e.QueueID} - {e.Error}', extra=self._logger_dict)
        with self.callback_object_list_lock:
            for i in self.callback_object_list:
                if i.queue_id == e.QueueID:
                    i.error = e.Error
                    i.is_finished.set()
                    break

    def spectramax_command_completed(self, sender: object, e: SoftMaxPro.AutomationClient.SMPAutomationClient.CommandStatusEventArg)->None:
        """
        Receives information for completed events from the Automation Service and puts them into self.command_completed_queue

        Parameters
        ----------
        sender: object
            The sender of the error message
        e: SoftMaxPro.AutomationClient.SMPAutomationClient.CommandStatusEventArg
            The command status event arguments
        """
        logger.debug(f'Command complete: Command ID = {e.QueueID} - {e.StringResult}', extra=self._logger_dict)

        with self.callback_object_list_lock:
            for i in self.callback_object_list:
                if i.queue_id == e.QueueID:
                    i.result = [i for i in [e.StringResult, e.IntResult, e.DoubleResult] if i is not None][0]  # TODO: Check if e always has all 3 properties
                    i.is_finished.set()
                    break

    def spectramax_instrument_status_changed(self, sender: object, e: SoftMaxPro.AutomationClient.SMPAutomationClient.InstrumentStatusEventArgs)->None:
        """
        Receives information about the instrument status from the Automation Service and puts them into self.instrument_status_changed_queue

        Parameters
        ----------
        sender: object
            The sender of the error message
        e: SoftMaxPro.AutomationClient.SMPAutomationClient.InstrumentStatusEventArgs
            The instrument status event arguments
        """
        logger.debug(f'Instrument status changed: {e.Status}', extra=self._logger_dict)

    def close_document(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The CloseDocument command closes the current document.
        Note: For the SoftMax Pro Software - GxP edition, the document must be unlocked, the document status must be In Work, and all statements must be unsigned.
        If the data is not saved, the document closes with no warning and data is not saved.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>close_document;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.CloseDocument(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def close_all_documents(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The CloseAllDocument command closes all open documents.
        Note: For the SoftMax Pro Software - GxP edition, the document must be unlocked, the document status must be In Work, and all statements must be unsigned.
        If the data is not saved, the document closes with no warning and data is not saved.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>close_all_documents;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.CloseAllDocuments(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def close_drawer(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The CloseDrawer command closes the drawer you specify on the instrument. This command closes the plate drawer for most instruments.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>close_drawer;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.CloseDrawer(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def export_as(self, path: str, export_as_format: str = 'PLATE') -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The ExportAs command exports data in the Columns, Plate, or .xml format. The ExportAs command overwrites any existing file without warning.

        Parameters
        ----------
        path: str
            The file name and path. If the file already exists, it will be overwritten
        export_as_format: str = "PLATE"
            The export format. Default is "PLATE". Can be any of the following:
                TIME exports data in a single column of text for each well.
                COLUMNS exports data in a single column of text for each well.
                PLATE exports data in a text matrix corresponding to a microplate grid.
                XML exports data in an XML file format.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>export_as;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        export_as_format = export_as_format.upper()

        if export_as_format == 'TIME':
            export_format = SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.TIME
        elif export_as_format == 'COLUMNS':
            export_format = SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.COLUMNS
        elif export_as_format == 'PLATE':
            export_format = SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.PLATE
        elif export_as_format == 'XML':
            export_format = SoftMaxPro.AutomationClient.SMPAutomationClient.ExportAsFormat.XML
        else:
            raise NotImplementedError(f'export_as_format needs to be either "TIME", "COLUMNS", "TEXT", or "XML", not {export_as_format}')

        cbo = CallbackObject(queue_id=self.client.ExportAs(path, export_format), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def get_data_copy(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The GetCopyData command copies data to the client by way of an event. The format of the copied data
        depends on the display settings for the plate section (normally Raw Data), the read mode, the read type, and
        the number of wavelengths.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>get_data_copy;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.GetDataCopy(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def get_drawer_status(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The GetDrawerStatus command returns the state of the drawer on the instrument. This command returns the state of the plate drawer for most instruments.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>get_drawer_status;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.GetDrawerStatus(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def get_temperature(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The GetTemperature command returns the instrument incubator temperature.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>get_temperature;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.GetTemperature(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def get_version(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The GetVersion command returns the version number of the SoftMax Pro Software automation Interface.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>get_version;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.GetVersion(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def new_document(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The NewDocument command creates a new document that uses the Default Protocol.spr protocol settings. Note: Not available for SoftMax Pro Software - GxP edition.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>new_document;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.NewDocument(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def new_experiment(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The NewExperiment command creates a new experiment in a document. Note: For the SoftMax Pro Software - GxP edition, the document must be unlocked, the document status must be In Work, and all statements must be unsigned.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>new_experiment;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.NewExperiment(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def new_notes(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The NewNotes command creates a new Note section in an experiment. Note: For the SoftMax Pro Software - GxP edition, the document must be unlocked, the document status must be In Work, and all statements must be unsigned.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>new_notes;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.NewNotes(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def new_plate(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The NewPlate command creates a new Plate section in an experiment. Note: For the SoftMax Pro Software - GxP edition, the user must have the Generate Compliance Data permission. Note: For the SoftMax Pro Software - GxP edition, the document must be unlocked, the document status must be In Work, and all statements must be unsigned.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>new_plate;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.NewPlate(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def open_drawer(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The OpenDrawer commands open a drawer on the instrument. This command opens the plate drawer for most instruments. Note: For instruments with temperature control, the plate drawer cannot open when the incubator is on.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>open_drawer;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.OpenDrawer(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def open_file(self, path: str) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The OpenFile command opens a protocol or data document. If the file is not found, the SoftMax Pro application does nothing.

        Parameters
        ----------
        path: str
            The path to the protocol or data file that is opened.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>open_file;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.OpenFile(path), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def quit(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The Quit command exits the SoftMax Pro Software.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>quit;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.Quit(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def save_as(self, path: str) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The SaveAs command saves the current document as a data document or a protocol. Define the document
        type by the file extension in the path statement. For the SoftMax Pro Software - Standard edition, use the
        *.sda file extension for data documents and *.spr file extension for protocols. For the SoftMax Pro Software -
        GxP edition, do not enter a file extension.
        If a document with the same name already exists, the SoftMax Pro Software - Standard edition automatically
        overwrites the document with no warning.
        Note: The SoftMax Pro Software - GxP edition does not allow you to save the document as a Protocol
        and prevents you from overwriting an existing document.

        Parameters
        ----------
        path: str
            The path to the protocol or data file that is opened.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>save_as;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.SaveAs(path), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def shake(self, shake_state: bool) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The SetShake command shakes the plate. When this command is set to true, starts shaking the plate tray until the Shake(false) command is sent. By default, the shake stops after 30 seconds in most instruments.

        Parameters
        ----------
        shake_state: bool
            True turns Shake on, False turns Shake off.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>shake;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.SetShake(shake_state), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def shake_on(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        Turns shaking on.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>shake_on;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        return self.shake(shake_state=True)

    def shake_off(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        Turns shaking on.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>shake_off;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        return self.shake(shake_state=False)

    def set_temperature(self, temperature: float) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The SetTemperature command sets the instrument incubator temperature. Set the temperature to zero to turn off the incubator.

        Parameters
        ----------
        temperature: float
            The temperature in degrees Celsius.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>set_temperature;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.SetTemperature(temperature), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def start_read(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The StartRead command reads a Plate section or CuvetteSet section. If the current section is neither a Plate section nor CuvetteSet section, the command reads the next Plate section or CuvetteSet section. The SoftMax Pro Software - Standard edition confirms that Auto Export is enabled and the SoftMax Pro Software - GxP edition confirms that Auto Save is enabled.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Depending on the nature of the callback, some fields are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>start_read;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        cbo = CallbackObject(queue_id=self.client.StartRead(), is_finished=threading.Event())
        with self.callback_object_list_lock:
            self.callback_object_list.append(cbo)
        cbo.is_finished.wait()
        with self.callback_object_list_lock:
            self.callback_object_list.remove(cbo)
        return cbo.error, cbo.result, cbo.status

    def stop_read(self) -> tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
        """
        The StopRead command stops the read of a Plate section or Cuvette Set section. This command is not queued.

        Returns
        -------
        tuple[Optional[str], Optional[Union[str, int, float]], Optional[str]]:
            A tuple with the error string, result value, and status string. Since this method is not queued, all values are None.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>stop_read;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        self.client.StopRead()
        return None, None, None

    def start_measurement(self, measured_wavelength: Union[float, list[float], tuple[float, float, float]], mode: str = 'ABS', start_well_index: Union[list[int], tuple[int, int]] = (0, 0), end_well_index: Union[list[int], tuple[int, int]] = (7, 11), fixed_wavelength: Optional[float] = None, read_from_bottom: bool = False) -> Union[str, int, float, None]:
        """
        Starts a measurement with the specified parameters.

        Parameters
        ----------
        measured_wavelength: Union[float, list[float], tuple[float, float, float]]
            The wavelength for the measurement. If only a single float is supplied, a single-point measurement will be performed. If three values are given, a spectral scan will be carried out from the first value to the second value, using a step width corresponding to the third value.
        mode: str = 'ABS'
            The measurement mode. Needs to be either 'ABS', 'EM', or 'EX'. Default is 'ABS'.
        start_well_index: Union[list[int], tuple[int, int]] = (0, 0)
            The zero-based row and column indices of the first well that is scanned. Default is (0, 0), corresponding to well A1.
        end_well_index: Union[list[int], tuple[int, int]] = (8, 12)
            The zero-based row and column indices of the last well that is scanned. Default is (7, 11), corresponding to well H12.
        fixed_wavelength: Optional[float] = None
            If mode = 'EM', the (fixed) excitation wavelength in nm. If mode = 'EX', the (fixed) emission wavelength in nm. If mode = 'ABS', this value has no effect. Default is None.
        read_from_bottom: bool = False
            Whether to read from the bottom in excitation or emission measurements. Default is False, i.e., it will be read from the top.

        Returns
        -------
        Union[str, int, float, None]
            A value with the results from the measurement.
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>start_measurement;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        tmp_file = self.write_spr_file(measured_wavelength=measured_wavelength, mode=mode, start_well_index=start_well_index, end_well_index=end_well_index, fixed_wavelength=fixed_wavelength, read_from_bottom=read_from_bottom)
        self.close_all_documents()
        self.open_file(tmp_file)
        self.start_read()
        res = self.get_data_copy()
        self.export_as(path=os.path.join(PathNames.CHARACTERIZATION_DIR.value, 'Platereader', os.path.basename(tmp_file).replace('.spr', '.csv')))
        return res[1]

    def write_spr_file(self, measured_wavelength: Union[float, list[float], tuple[float, float, float]], mode: str = 'ABS', start_well_index: Union[list[int], tuple[int, int]] = (0, 0), end_well_index: Union[list[int], tuple[int, int]] = (7, 11), fixed_wavelength: Optional[float] = None, read_from_bottom: bool = False) -> str:
        """
        Writes an .spr file with the specified acquisition parameters and returns the file path.

        Parameters
        ----------
        measured_wavelength: Union[float, list[float], tuple[float, float, float]]
            The wavelength for the measurement. If only a single float is supplied, a single-point measurement will be performed. If three values are given, a spectral scan will be carried out from the first value to the second value, using a step width corresponding to the third value.
        mode: str = 'ABS'
            The measurement mode. Needs to be either 'ABS', 'EM', or 'EX'. Default is 'ABS'.
        start_well_index: Union[list[int], tuple[int, int]] = (0, 0)
            The zero-based row and column indices of the first well that is scanned. Default is (0, 0), corresponding to well A1.
        end_well_index: Union[list[int], tuple[int, int]] = (8, 12)
            The zero-based row and column indices of the last well that is scanned. Default is (7, 11), corresponding to well H12.
        fixed_wavelength: Optional[float] = None
            If mode = 'EM', the (fixed) excitation wavelength in nm. If mode = 'EX', the (fixed) emission wavelength in nm. If mode = 'ABS', this value has no effect. Default is None.
        read_from_bottom: bool = False
            Whether to read from the bottom in excitation or emission measurements. Default is False, i.e., it will be read from the top.

        Returns
        -------
        str
            The file path of the created spr file
        """
        if isinstance(measured_wavelength, tuple) or isinstance(measured_wavelength, list):
            assert len(measured_wavelength) == 3, 'For spectral scans, two wavelength and the step value need to be provided.'
            is_spectral_scan = True
        else:
            is_spectral_scan = False

        if mode.lower() not in ['abs', 'ex', 'em']:
            logger.error(f'Unsupported measurement mode: {mode}. Currently, only "ABS", "EX", or "EM" are supported.', extra=self._logger_dict)
            raise NotImplementedError

        if (mode.lower() == 'ex' or mode.lower() == 'em') and fixed_wavelength is None:
            logger.error('For excitation and emission scans, a fixed wavelength needs to be specified.', extra=self._logger_dict)
            return ''

        if mode.lower() == 'abs':
            if is_spectral_scan:
                fc = open(os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, 'Templates', '_Abs_Spectrum_A1.spr'), 'rb').read()
            else:
                fc = open(os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, 'Templates', '_Abs_Singlepoint_A1.spr'), 'rb').read()
        elif mode.lower() == 'ex':
            if is_spectral_scan:
                fc = open(os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, 'Templates', '_Ex_Spectrum_A1.spr'), 'rb').read()
            else:
                fc = open(os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, 'Templates', '_Fl_Singlepoint_A1.spr'), 'rb').read()
        elif mode.lower() == 'em':
            if is_spectral_scan:
                fc = open(os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, 'Templates', '_Em_Spectrum_A1.spr'), 'rb').read()
            else:
                fc = open(os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, 'Templates', '_Fl_Singlepoint_A1.spr'), 'rb').read()
        else:
            raise NotImplementedError

        val: Union[bytes, int] = b''
        # Write Scan Area Section
        scan_area = b'ReadAreaSettings' + b'\x38\x12\x01\x00\x00\x0C\x00\x00\x0A' + b'TotalWells' + b'\x60\x00\x00\x00\x00\x14\x00\x00\x6C\x00\x00\x00\x00\x00\x00\x00\x12' + b'SelectedRowColumns' + b'\x01\x00\x00\x00\x00\x14\x00\x00\x49\x00\x00\x00\x00\x00\x00\x00\x13'
        well_counter = 0
        MAGIC_BYTES_SELECTED_ROW_COLUMNS = b'\x01\x00\x00\x00\x00\x0C\x00\x00\x08'
        MAGIC_BYTES_ROW_INDEX = b'\x00\x00\x00\x00\x0C\x00\x00\x0B'
        MAGIC_BYTES_COL_INDEX1 = b'\x00\x00\x00\x00\x14\x00\x00'
        MAGIC_BYTES_COL_INDEX2 = b'\x00\x00\x00\x00\x00\x00\x00'
        MAGIC_BYTES_LAST_COL_INDEX = b'\x00\x00\x00\x00\x20\x00\x00\x00\x00\x00\x14\x00\x00\x5D\x00\x00\x00\x00\x00\x00\x00\x0F'

        # Build scan area string
        for row_index in range(start_well_index[0], end_well_index[0] + 1):
            for col_index in range(start_well_index[1], end_well_index[1] + 1):
                scan_area += ('SelectedRowColumns' + str(well_counter)).encode()
                scan_area += MAGIC_BYTES_SELECTED_ROW_COLUMNS
                scan_area += ('RowIndex' + chr(row_index)).encode()
                scan_area += MAGIC_BYTES_ROW_INDEX
                scan_area += ('ColumnIndex' + chr(col_index)).encode()
                well_counter += 1
                if well_counter < abs(end_well_index[0] - start_well_index[0] + 1) * abs(end_well_index[1] - start_well_index[1] + 1):
                    if well_counter < 10:
                        scan_area += MAGIC_BYTES_COL_INDEX1 + b'\x49' + MAGIC_BYTES_COL_INDEX2 + b'\x13'
                    else:
                        scan_area += MAGIC_BYTES_COL_INDEX1 + b'\x4A' + MAGIC_BYTES_COL_INDEX2 + b'\x14'
                else:
                    scan_area += MAGIC_BYTES_LAST_COL_INDEX

        val = struct.pack('h', scan_area.rfind(b'\x20\x00\x00') - scan_area.find(b'\x14\x00\x00'))  # length read area block in bytes
        offset = scan_area.find(b'\x14\x00\x00') + len(b'\x14\x00\x00')
        scan_area = scan_area[: offset] + val + scan_area[offset + len(val):]
        fc_new = fc[:fc.find(b'ReadAreaSettings')] + scan_area + fc[fc.find(b'AutomixSettings8'):]

        # Set wavelengths
        if is_spectral_scan:
            offset = fc_new.find(b'WavelengthSettings') + len(b'WavelengthSettings')
            assert isinstance(measured_wavelength, tuple) or isinstance(measured_wavelength, list)
            if mode.lower() == 'abs':
                # Set Start Wavelength
                val = struct.pack('d', measured_wavelength[0])
                offset1 = fc_new.find(b'StartWavelength', offset) + len(b'StartWavelength')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                # Set Stop Wavelength
                val = struct.pack('d', measured_wavelength[1])
                offset1 = fc_new.find(b'StopWavelength', offset) + len(b'StopWavelength')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                # Set Step
                val = struct.pack('d', measured_wavelength[2])
                offset1 = fc_new.find(b'Step', offset)
                old_step_value = fc_new[offset1: offset1 + len(b'Step') + len(val)]
                fc_new = fc_new.replace(old_step_value, b'Step' + val, 3)
            elif mode.lower() == 'ex':
                # Set Start Wavelength
                val = struct.pack('d', measured_wavelength[0])
                offset1 = fc_new.find(b'ExcitationStart', offset) + len(b'ExcitationStart')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                # Set Stop Wavelength
                val = struct.pack('d', measured_wavelength[1])
                offset1 = fc_new.find(b'ExcitationStop', offset) + len(b'ExcitationStop')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                # Set Step
                val = struct.pack('d', measured_wavelength[2])
                offset1 = fc_new.find(b'Step', offset)
                old_step_value = fc_new[offset1: offset1 + len(b'Step') + len(val)]
                fc_new = fc_new.replace(old_step_value, b'Step' + val, 3)
                # Set Emission Wavelength
                val = struct.pack('d', fixed_wavelength)
                offset1 = fc_new.find(b'EmissionValue', offset) + len(b'EmissionValue')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
            elif mode.lower() == 'em':
                # Set Start Wavelength
                val = struct.pack('d', measured_wavelength[0])
                offset1 = fc_new.find(b'StartWavelength', offset) + len(b'StartWavelength')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                # Set Stop Wavelength
                val = struct.pack('d', measured_wavelength[1])
                offset1 = fc_new.find(b'StopWavelength', offset) + len(b'StopWavelength')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                # Set Step
                val = struct.pack('d', measured_wavelength[2])
                offset1 = fc_new.find(b'Step', offset)
                old_step_value = fc_new[offset1: offset1 + len(b'Step') + len(val)]
                fc_new = fc_new.replace(old_step_value, b'Step' + val, 3)
                # Set Emission Wavelength
                val = struct.pack('d', fixed_wavelength)
                offset1 = fc_new.find(b'ExcitationValue', offset) + len(b'ExcitationValue')
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
        else:
            offset = fc_new.find(b'Wavelength0') + len(b'Wavelength0')
            if mode.lower() == 'abs':
                offset1 = fc_new.find(b'Wavelength', offset) + len(b'Wavelength')
                val = struct.pack('d', measured_wavelength)
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
            elif mode.lower() == 'ex':
                offset1 = fc_new.find(b'ExcitationWavelength', offset) + len(b'ExcitationWavelength')
                val = struct.pack('d', measured_wavelength)
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                offset1 = fc_new.find(b'EmissionWavelength', offset) + len(b'EmissionWavelength')
                val = struct.pack('d', fixed_wavelength)
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
            elif mode.lower() == 'em':
                offset1 = fc_new.find(b'ExcitationWavelength', offset) + len(b'ExcitationWavelength')
                val = struct.pack('d', fixed_wavelength)
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]
                offset1 = fc_new.find(b'EmissionWavelength', offset) + len(b'EmissionWavelength')
                val = struct.pack('d', measured_wavelength)
                fc_new = fc_new[:offset1] + val + fc_new[offset1 + len(val):]

        # Set bottom/top read
        if mode.lower() != 'abs':
            offset = fc_new.find(b'IsReadFromBottom') + len(b'IsReadFromBottom')
            if read_from_bottom:
                val = b'\x01'
            else:
                val = b'\x00'
            fc_new = fc_new[:offset] + val + fc_new[offset + 1:]

        MAGIC_DELIMITER1 = b'\x00\x14'
        MAGIC_DELIMITER2 = b'\x0BBinary File'
        MAGIC_OFFSET2 = 0x29
        MAGIC_DELIMITER3 = b'\x04\x00\x00\x00\x08'
        MAGIC_OFFSET3 = 0x75
        MAGIC_DELIMITER4 = b'\x14\x00\x00\xA3\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x14'
        MAGIC_OFFSET4 = 0x1C1
        MAGIC_DELIMITER5 = b'\x00\x14\x00\x00\x47'
        MAGIC_OFFSET5 = 0x30C
        MAGIC_DELIMITER6 = b'UserInformation\x00\x00'
        MAGIC_DELIMITER7 = b'\x14\x00\x00\x5D'

        offset = 0
        spr_output_path = os.path.join(PathNames.SPECTRAMAX_TEMP_DIR.value, f'tmp_{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")}.spr')
        with open(spr_output_path, 'wb') as f:
            f.write(fc_new)

            offset = fc_new.find(MAGIC_DELIMITER1, offset + 1)
            f.seek(offset + 4, 0)
            val = len(fc_new) - offset
            f.write(struct.pack('h', val))

            offset = fc_new.find(MAGIC_DELIMITER2, offset + 1)
            f.seek(MAGIC_OFFSET2, 0)
            val = len(fc_new) - offset
            f.write(struct.pack('h', val))

            offset = fc_new.find(MAGIC_DELIMITER1, offset + 1)
            f.seek(offset + 4, 0)
            val = len(fc_new) - offset
            f.write(struct.pack('h', val))

            offset = fc_new.find(MAGIC_DELIMITER3, MAGIC_OFFSET3)
            f.seek(MAGIC_OFFSET3, 0)
            val = offset
            f.write(struct.pack('h', val))

            f.seek(MAGIC_OFFSET3 + 0x11, 0)
            val -= 0x11
            f.write(struct.pack('h', val))

            offset = fc_new.find(MAGIC_DELIMITER4, MAGIC_OFFSET4)
            f.seek(MAGIC_OFFSET4 + 0x03, 0)
            val = offset - MAGIC_OFFSET4
            f.write(struct.pack('h', val))

            offset = fc_new.rfind(MAGIC_DELIMITER5)
            f.seek(MAGIC_OFFSET5, 0)
            val = offset - fc_new.find(MAGIC_DELIMITER2, MAGIC_OFFSET5)
            f.write(struct.pack('h', val))

            f.seek(MAGIC_OFFSET5 + 0x1C, 0)
            val -= 0x10
            f.write(struct.pack('h', val))

            offset = fc_new.find(MAGIC_DELIMITER6, MAGIC_OFFSET5 + 0x3C) + len(MAGIC_DELIMITER6)
            f.seek(offset + 0x03, 0)
            val = fc_new.find(MAGIC_DELIMITER7, offset) - offset
            f.write(struct.pack('h', val))

        logger.info(f'Automatically created protocol file for plate reader measurement: {spr_output_path}', extra=self._logger_dict)
        return spr_output_path
