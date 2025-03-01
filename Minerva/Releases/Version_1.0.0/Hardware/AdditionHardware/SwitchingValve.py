#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import logging
import math
import os.path
import queue
import threading
import time
from abc import ABC, abstractmethod

from typing import Union, Iterable, TYPE_CHECKING, List, Tuple, Dict, Optional, Any, SupportsFloat

import serial

from Minerva.API import MinervaAPI
from Minerva.Hardware.AdditionHardware import WPI
from Minerva.Hardware.ControllerHardware import ArduinoController
from Minerva.Hardware.RobotArms import UFactory
from Minerva.API.HelperClassDefinitions import AdditionHardware, Hardware, PumpUnitsVolume, Volume, FlowRate, TaskScheduler, TaskGroupSynchronizationObject, PathNames, _is_json_serializable, RobotArmHardware

if TYPE_CHECKING:
    from Minerva.API.MinervaAPI import Chemical, Container

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


class SwitchingValve(AdditionHardware, ABC):
    """Abstract Base class for SwitchingValves"""
    EMERGENCY_STOP_REQUEST = False

    def __init__(self) -> None:
        """Abstract Base class for SwitchingValves"""
        super().__init__()
        self.outlet_port: Union[int, None] = None
        self.syringe_pump: Union[WPI.Aladdin, None] = None
        self.configuration: Dict[int, Union[str, WPI.Aladdin, MinervaAPI.Container, Hardware, None]] = {}
        self.dead_volumes: Dict[int, Union[float, str, Volume, None]] = {}

        self._logger_dict = {'instance_name': str(self)}

    # @TaskScheduler.scheduled_task  # The actual withdrawing and infusing steps of the associated pumps are wrapped as a scheduled_task, so do not wrap this method here as well
    def add(self, chemical: Union[Chemical, List[Chemical], Tuple[Chemical, ...]], target_container: MinervaAPI.Container, withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Adds the specified chemical(s) to the specified container.

        Parameters
        ----------
        chemical : Union[Chemical, Iterable[Chemical]]
            A list of the chemical(s) to be added.
        target_container : MinervaAPI.Container
            The Container to which the chemicals are added
        withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are withdrawn. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are added. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
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
            True if the addition was successful.

        Raises
        ------
        AssertionError
            If the configuration is not specified
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return False

        assert self.configuration is not None, 'Valve configuration not found. Please use the set_configuration method to define the current configuration of the valve.'

        if not isinstance(chemical, Iterable):
            chemical = [chemical]
        if addition_rate is None:
            addition_rate = [None] * len(chemical)
        elif not isinstance(addition_rate, List):
            addition_rate = [addition_rate]
        if withdraw_rate is None:
            withdraw_rate = [None] * len(chemical)
        elif not isinstance(withdraw_rate, List):
            withdraw_rate = [withdraw_rate]

        assert len(chemical) == len(addition_rate) and len(chemical) == len(withdraw_rate), 'If a list of chemicals and addition/withdraw rates are provided, the lists must be of the same length.'

        for i, c in enumerate(chemical):
            for k, v in self.configuration.items():
                if c.container == v:
                    assert isinstance(v, MinervaAPI.Container)
                    logger.info(f'Performing addition step for chemical {c} ({c.container.name} -> {target_container.name})', extra=self._logger_dict)

                    if c.volume.in_unit('mL') > self.syringe_pump.current_syringe_parameters.volume:
                        no_of_steps = math.ceil(c.volume.in_unit('mL') / self.syringe_pump.current_syringe_parameters.volume)
                        volume_per_step = Volume(value=c.volume.in_unit('mL') / no_of_steps, unit='mL')
                    else:
                        no_of_steps = 1
                        volume_per_step = c.volume

                    for _ in range(0, no_of_steps):
                        ret = self.set_position(k)
                        if ret:
                            ret = self.syringe_pump.withdraw(volume=volume_per_step, rate=withdraw_rate[i], block=block, is_sequential_task=is_sequential_task, priority=priority, task_group_synchronization_object=task_group_synchronization_object)
                        if ret:
                            for key, val in self.configuration.items():
                                if target_container == val:
                                    port = key
                                    break
                            else:
                                port = self.outlet_port
                            ret = self.set_position(port)
                        if ret:
                            ret = self.syringe_pump.infuse(volume=volume_per_step, rate=addition_rate[i], block=block, is_sequential_task=is_sequential_task, priority=priority, task_group_synchronization_object=task_group_synchronization_object)
                        if not ret:
                            return False

                    logger.info(f'Finished adding {c} ({c.container.name} -> {target_container.name})', extra=self._logger_dict)
                    target_container.current_volume = Volume(target_container.current_volume + c.volume, target_container.current_volume.unit)
                    break

        time.sleep(1)  # Allow for a pause of 1 second for the last drops to be dispensed

        return True

    def _purge(self, target_container: MinervaAPI.Container, purging_volume: Union[Volume, str, float, None] = Volume(30, 'mL'), purging_addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, purging_port: Union[int, None] = None, robot_arm: RobotArmHardware = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Purges the valve and tubes with air.

        Parameters
        ----------
        target_container : MinervaAPI.Container
            The Container into which the chemicals are purged
        purging_volume: Union[Volume, str, float, None] = Volume(30, 'mL')
            Volume of air that is used for purging the tube/needle after dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve. If a float is supplied, it will be assumed to be in mL. Default is 30 mL.
        purging_addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate that is used when purging the tube/needle after dispensing the liquid into the new container. Only has an effect if a purging volume is not None. If a float is supplied, it will be assumed to be in milliliters per minute. Default is None, which means the default_addition_rate of the syringe pump will be used.
        purging_port: Union[int, None] = None:
            Port on a valve that is used to draw in air for purging. Only has an effect if the addition hardware is a valve and a purging volume is not None. Default is None, which means the outlet_port of the syringe pump will be used.
        robot_arm: RobotArmHardware = None
            The robot arm that was used for moving the container to the valve. Default is None
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
            True if the addition was successful.
        """
        if purging_volume is not None and ((isinstance(purging_volume, float) and purging_volume > 0) or (isinstance(purging_volume, Volume) and purging_volume.value > 0) or (isinstance(purging_volume, str) and Volume.from_string(purging_volume).value > 0)):
            logger.info(f'Performing purging step into container {target_container}...', extra=self._logger_dict)

            if isinstance(purging_volume, Volume):
                purging_volume = purging_volume.in_unit('mL')
            elif isinstance(purging_volume, str):
                purging_volume = Volume.from_string(purging_volume).in_unit('mL')

            if purging_volume > self.syringe_pump.current_syringe_parameters.volume:
                no_of_steps = math.ceil(purging_volume / self.syringe_pump.current_syringe_parameters.volume)
                volume_per_step = purging_volume / no_of_steps
            else:
                no_of_steps = 1
                volume_per_step = purging_volume

            for _ in range(0, no_of_steps):
                if robot_arm is not None:
                    assert isinstance(robot_arm, UFactory.XArm6)
                    current_z_pos = robot_arm.arm.position[2]
                    # Move container down to aspirate air through outlet needle
                    if target_container.container_type is not None:
                        robot_arm.arm.set_position(z=current_z_pos - target_container.container_type.container_height - 5, wait=True)
                # Change valve position to the port that is used for drawing in air
                if purging_port is None:
                    purging_port = self.outlet_port
                if not self.set_position(purging_port):
                    logger.error(f'Error while changing valve port to {purging_port} for aspirating air.', extra=self._logger_dict)
                    return False
                # Aspirate air through purging port
                if not self.syringe_pump.withdraw(volume=volume_per_step, block=block, is_sequential_task=is_sequential_task, priority=priority, task_group_synchronization_object=task_group_synchronization_object):
                    logger.error(f'Error while aspirating air through port {purging_port}.', extra=self._logger_dict)
                    return False
                # Move container back up
                if robot_arm is not None:
                    if target_container.container_type is not None:
                        robot_arm.arm.set_position(z=current_z_pos, wait=True)
                # Check if the outlet port needs to be changed (in case the container is connected directly to the valve or the purging port is different than the outlet port)
                for k, v in self.configuration.items():
                    if target_container == v:
                        if not self.set_position(k):
                            logger.error(f'Error while changing valve port.', extra=self._logger_dict)
                            return False
                        break
                else:
                    if purging_port != self.outlet_port:
                        if not self.set_position(self.outlet_port):
                            logger.error(f'Error while changing valve port.', extra=self._logger_dict)
                            return False
                # Dispense
                if not self.syringe_pump.infuse(volume=volume_per_step, rate=purging_addition_rate, block=block, is_sequential_task=is_sequential_task, priority=priority, task_group_synchronization_object=task_group_synchronization_object):
                    logger.error(f'Error while purging with air.', extra=self._logger_dict)
                    return False

        return True

    def set_configuration(self, configuration: dict[int, Union[MinervaAPI.Container, WPI.Aladdin, Hardware, str, None]]) -> bool:
        """
        Sets the configuration of the valve (i.e., what is connected to which outlet).

        configuration : dict[int, Union[MinervaAPI.Container, Aladdin.Aladdin, str, None]]
            A dict with the configuration of the valve in the form {int: Union[MinervaAPI.Container, Aladdin.Aladdin, str, None]}. A valid Syringe Pump connected to the valve has to be specified.

        Returns
        -------
        bool
            True if the hardware configuration was set successfully, False otherwise
        """

        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return False

        syringe_pump_is_declared = False
        for key, val in configuration.items():
            if isinstance(val, str) and val.lower() == 'outlet':
                # outlet_is_declared = True
                self.outlet_port = key
            elif isinstance(val, WPI.Aladdin):
                syringe_pump_is_declared = True
                self.syringe_pump = val
            # Initialize dead volume of the port as None (if not set yet)
            if key not in self.dead_volumes.keys():
                self.dead_volumes[key] = None
        if not syringe_pump_is_declared:
            return False
        else:
            self.configuration = configuration
            return True

    def set_dead_volumes(self, dead_volumes: dict[int, Union[float, str, Volume, None]]) -> bool:
        """
        Sets the dead volumes of the valve (i.e., the volumes of the tubes for each individual port).

        dead_volumes: dict[int, Union[float, str, Volume, None]
            A dict with the dead volumes for each port of the valve. If a float is provided, it is assumed to be in mL.

        Returns
        -------
        bool
            True if the hardware configuration was set successfully, False otherwise
        """

        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return False

        for k, v in dead_volumes.items():
            self.dead_volumes[k] = v

        return True

    @abstractmethod
    def set_position(self, position: int) -> bool:
        """
        Moves the valve to the indicated position.

        Parameters
        ----------
        position : int
            The position the valve should be moved to.

        Returns
        -------
        bool
            True if the command was issued successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_position(self) -> int:
        """
        Get the current position of the valve.

        Returns
        -------
        int
            The current position of the valve
        """
        pass

    def dump_configuration(self) -> Dict[str, Any]:
        """Dump all current instance vars in a json-serializable dict. Overriden to take care of configuration dict."""
        config_dict: Dict[str, Any] = {}
        for k, v in list(vars(self).items()):
            if _is_json_serializable(v):
                config_dict[k] = v
            elif isinstance(v, dict):
                config_dict[k] = dict([(key, val) if _is_json_serializable(val) else (key, f'{type(val)}-{id(val)}') for key, val in v.items()])
            else:
                config_dict[k] = f'{type(v)}-{id(v)}'
        return config_dict

    def post_load_from_config(self, kwargs_dict: Dict[str, Any], loaded_configuration_dict: Optional[Dict[str, Any]]) -> bool:
        """
        Function will be called after everything else is initialized when loading from a configuration file (can e.g. be used for setting configurations that depend on other objects being initialized first).

        Parameters
        ----------
        kwargs_dict: Dict[str, Any]
            Dictionary with any remaining kwargs that were not used in the __init__ method of the class
        loaded_configuration_dict: Dict[str, Any]
            Dictionary with all initialized objects

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        tmp_valve_configuration = kwargs_dict.pop('configuration', None)
        if tmp_valve_configuration is not None:
            for k, v in list(tmp_valve_configuration.items()):
                tmp_valve_configuration.pop(k)
                if v is not None and "<class 'MinervaAPI.Container'>" in v:
                    tmp_valve_configuration[int(k)] = loaded_configuration_dict['Containers'][v]
                elif v is not None and "<class 'Hardware.AdditionHardware.WPI.Aladdin'>" in v:
                    tmp_valve_configuration[int(k)] = loaded_configuration_dict['AdditionHardware'][v]
                else:
                    tmp_valve_configuration[int(k)] = v
            self.configuration = tmp_valve_configuration
        return True


class SwitchingValveArduino(SwitchingValve):
    """
    Class for communication with an Arduino controlling a switching valve.

    Parameters
    ----------
    arduino_controller: ArduinoController.ArduinoController
        The Arduino controller hardware.
    timeout: float = 5
        The timeout when waiting for a response in seconds. Default is 5.
    valve_number: int = 1
        The number of this valve. Default is 1.
    """

    def __init__(self, arduino_controller: ArduinoController.ArduinoController, timeout: float = 600, valve_number: int = 1):
        """
        Constructor for the SwitchingValve Class for communication with the Arduino controlling the valve.

        Parameters
        ----------
        arduino_controller: ArduinoController.ArduinoController
            The Arduino controller hardware.
        timeout : float, default=600
            The timeout when waiting for a response in seconds. Default is 600 seconds = 10 minutes.
        valve_number : int, default=1
            The number of this valve. Default is 1.
        """
        super().__init__()
        self.timeout = timeout
        self.arduino_controller = arduino_controller
        self.valve_number = valve_number
        self.read_queue = self.arduino_controller.get_read_queue(f'VALVE{self.valve_number}')

        self.outlet_port: Union[int, None] = None
        self.syringe_pump: Union[WPI.Aladdin, None] = None
        self.configuration: Dict[int, Union[str, WPI.Aladdin, MinervaAPI.Container, Hardware, None]] = {}

        self._logger_dict = {'instance_name': str(self)}

        i = 0
        self.retries = 3
        for i in range(0, self.retries):
            try:
                self.arduino_controller.write(f'VALVE{self.valve_number} INI\n')
                r = self.read_queue.get(block=True, timeout=self.timeout)
                if r == 'OK':
                    logger.info(f'Valve {self.valve_number} on {self.arduino_controller} sucessfully initialized.', extra=self._logger_dict)
                    break
            except queue.Empty:
                continue  # try again (maximum self.retries times)

        if i == self.retries - 1:
            logger.critical(f'Valve not responding on controller {self.arduino_controller}.', extra=self._logger_dict)
            raise TimeoutError

    def set_position(self, position: int) -> bool:
        """
        Moves the valve to the indicated position.

        Parameters
        ----------
        position : int
            The position the valve should be moved to.

        Returns
        -------
        bool
            True if the command was issued successfully, False otherwise
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'VALVE{self.valve_number} POS{position}\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == 'OK':
            logger.info(f'Moved valve {self.valve_number} to position {position} (connected to {self.configuration[position].name if isinstance(self.configuration[position], MinervaAPI.Container) else self.configuration[position]}).', extra=self._logger_dict)  # type: ignore #(mypy issues 622, 3487)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def get_position(self) -> int:
        """
        Get the current position of the valve.

        Returns
        -------
        int
            The current position of the valve
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return -1

        self.arduino_controller.write(f'VALVE{self.valve_number} POS\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r.startswith('ERROR') or r.startswith('EMERGENCY STOP ACTIVE'):
            logger.error(r, extra=self._logger_dict)
            return -1
        else:
            position = int(r.replace('POS ', ''))
            logger.info(f'Valve {self.valve_number} is currently in position {position} (connected to {self.configuration[position].name if isinstance(self.configuration[position], MinervaAPI.Container) else self.configuration[position]}).', extra=self._logger_dict)  # type: ignore #(mypy issues 622, 3487)
            return position

    def get_hall_sensor_parameters(self) -> str:
        """
        Get the current hall sensor parameters.

        Returns
        -------
        str
            The current hall sensor parameters.
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return ''

        self.arduino_controller.write('VALVE{self.valve_number} PAR\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r.startswith('ERROR') or r.startswith('EMERGENCY STOP ACTIVE'):
            logger.error(r, extra=self._logger_dict)
            return r
        else:
            logger.info(f'Hall Sensor Parameters for valve {self.valve_number}: {r}', extra=self._logger_dict)
            return r

    def re_initialize(self) -> bool:
        """
        Re-Initialize the valve and the hall sensor.

        Returns
        -------
        bool
            True if the initialization was successfully, false otherwise.
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return False

        self.arduino_controller.write(f'VALVE{self.valve_number} INI\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == "OK":
            logger.info(f"Valve {self.valve_number} re-initialized.", extra=self._logger_dict)
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    def emergency_stop(self) -> bool:
        """
        Sends an emergency stop request to the Arduino, causing it to ignore all further commands until cleared.

        Returns
        -------
        bool
            True if the request was sent successfully, false otherwise.
        """
        SwitchingValve.EMERGENCY_STOP_REQUEST = True

        self.arduino_controller.write('ESR\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == "OK":
            logger.critical(f"Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
            return True
        else:
            logger.critical(f"Error in emergency stop protocol.", extra=self._logger_dict)
            logger.error(r, extra=self._logger_dict)
            return False

    def clear_emergency_stop(self) -> bool:
        """
        Clears a previously sent emergency stop request, and continue processing commands.

        Returns
        -------
        bool
            True if the request was cleared successfully, false otherwise.
        """
        self.arduino_controller.write('CES\n')
        r = self.read_queue.get(timeout=self.timeout)
        if r == "OK":
            logger.info(f"Emergency stop cleared. Continuing to process commands.", extra=self._logger_dict)
            SwitchingValve.EMERGENCY_STOP_REQUEST = False
            return True
        else:
            logger.error(r, extra=self._logger_dict)
            return False

    """
    Communication: 9600 8 N 1
    
    Send commands values in [] are optional:
    <COMMAND>[ ][VALUE][CHR(13)]<CHR(10)>
    Answer:
    OK<CHR(13)><CHR(10)>                          - If command was executed successfully
    UNK<CHR(13)><CHR(10)>                         - Unknown Command
    ERR <byte>: <errormessage><CHR(13)><CHR(10)>  - If an error occured while executing the command
    <String><CHR(13)><CHR(10)>                    - String containing the answer to a query
    
    Query Commands:
    POS
    Current valve position (0-5)
    PAR
    Gives the Hall sensor idle and threshold values (Hall Sensor Idle Value:\t<int>\tHall Sensor Threshold Value:\t<int>)
    
    Action Commands:
    POS Value
    Move to the valve position indicated by Value (integer from 0-5)
    INI
    Re-initialize valve
    ESR
    Emergency Stop Request - Further commands will be ignored until cleared
    CES
    Clear Emergency Stop - Continue Processing commands 
    """


class SwitchingValveVici(SwitchingValve):
    """
    Class for communication with a Vici controller controlling a switching valve.

    Parameters
    ----------
    com_port : str
        The COM Port the valve controller is connected to.
    baud_rate : int, default=9600
        The baud rate for communication with the valve controller (default is 9600).
    positions : int, default = 10
        The number of selectable positions on this valve. Default is 10
    sleep_time : float = 1
        The time (in seconds) to wait for the valve to reach its requested position. Default is 1 second.
    """

    def __init__(self, com_port: str, baud_rate: int = 9600, positions: int = 10):
        """
        Constructor for the class for communication with a Vici controller controlling a switching valve.

        Parameters
        ----------
        com_port : str
            The COM Port the valve controller is connected to.
        baud_rate : int, default=9600
            The baud rate for communication with the valve controller (default is 9600).
        positions : int, default = 10
            The number of selectable positions on this valve. Default is 10
        """
        super().__init__()
        self.eol = b'\x0D'
        self.com_port = str(com_port).upper()
        self.baud_rate = baud_rate
        self.parity = serial.PARITY_NONE
        self.byte_size = 8
        self.stop_bit = 1
        self.timeout = 1

        self.retries = 3
        self._com_port_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        self.outlet_port: Union[int, None] = None
        self.syringe_pump: Union[WPI.Aladdin, None] = None
        self.configuration: Dict[int, Union[str, WPI.Aladdin, MinervaAPI.Container, Hardware, None]] = {}
        self.positions = positions

        if not self.com_port.startswith('COM'):
            self.com_port = 'COM' + self.com_port

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)

        i = 0
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('LG1\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                if r == 'LG = 1' or 'LG1':
                    with self._com_port_lock:
                        self.ser.write('IFM1\r'.encode())
                        self.ser.flush()
                        r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())
                    if r == 'IFM = 1' or 'IFM1':
                        logger.info('Connected to Valve on {}.'.format(self.com_port), extra=self._logger_dict)
                        break
            except TimeoutError:
                continue  # Due to a probable transmission error, please attempt again (up to a maximum of self.retries times)

        if i == self.retries-1:
            logger.critical('Valve not responding on port {}.'.format(self.com_port), extra=self._logger_dict)
            self.ser.close()
            raise TimeoutError('Valve not responding on port {}.'.format(self.com_port))

    def set_position(self, position: int) -> bool:
        """
        Moves the valve to the indicated position.

        Parameters
        ----------
        position : int
            The position the valve should be moved to.

        Returns
        -------
        bool
            True if the command was issued successfully, False otherwise
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return False

        position = position % self.positions
        if position == self.get_position():
            logger.info(f'Moved valve {self} to position {position} (connected to {self.configuration[position].name if isinstance(self.configuration[position], MinervaAPI.Container) else self.configuration[position]}).', extra=self._logger_dict)  # type: ignore #(mypy issues 622, 3487)
            return True

        with self._com_port_lock:
            if position == 0:
                position = self.positions
            self.ser.write(f'GO{position}\r'.encode())
            self.ser.flush()
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())

        if not r.startswith('Position is '):
            logger.error(r, extra=self._logger_dict)
            return False
        else:
            position = int(r.split(" ")[-1]) % self.positions
            logger.info(f'Moved valve {self} to position {position} (connected to {self.configuration[position].name if isinstance(self.configuration[position], MinervaAPI.Container) else self.configuration[position]}).', extra=self._logger_dict)  # type: ignore #(mypy issues 622, 3487)
            return True

    def get_position(self) -> int:
        """
        Get the current position of the valve.

        Returns
        -------
        int
            The current position of the valve
        """
        if SwitchingValve.EMERGENCY_STOP_REQUEST:
            return -1

        with self._com_port_lock:
            self.ser.write(f'CP\r'.encode())
            self.ser.flush()
            r = self.ser.read_until(self.eol).decode().rstrip(self.eol.decode())

        if not r.startswith('Position is '):
            logger.error(r, extra=self._logger_dict)
            return -1
        else:
            position = int(r.split(" ")[-1]) % self.positions
            logger.info(f'Valve {self} is currently in position {position} (connected to {self.configuration[position].name if isinstance(self.configuration[position], MinervaAPI.Container) else self.configuration[position]}).', extra=self._logger_dict)  # type: ignore #(mypy issues 622, 3487)
            return position

    """
    Communication: 9600 8 N 1
    
    COMMAND MODES* DESCRIPTION
    AL<enter> 2, 3 Moves the actuator drive shaft to the reference position prior to valve installation
    AM<enter> 1, 2, 3 Displays the current actuator mode
    AMn<enter> 1, 2, 3 Sets the actuator mode to [1] two position with stops, [2] two position without stops, or [3] multiposition
    CC<enter> 1, 2 Sends the actuator from Position A to Position B, 3 Decrements the actuator one position. (For example, from position 5 to position 4)
    CCnn<enter> 3 Sends the actuator in the “negative” or “down” direction to position nn (from NP to 1)
    CNT<enter> 1, 2, 3 Displays the current value in the actuation counter
    CNTnnnnn<enter> 1, 2, 3 Sets the actuation counter from 0 to 65535
    CP<enter> 1, 2, 3 Displays the current position
    CW<enter> 1, 2 Sends the actuator from Position B to Position A, 3 Increments the actuator one position. (For example, from position 4 to position 5)
    CWnn<enter> 3 Sends the actuator in the “positive” or “up” direction to position nn (from 1 to NP)
    DT<enter> 1, 2 Displays the current delay time in milliseconds
    DTnnnnn<enter> 1, 2 Sets the delay time from 0 to 65,000 milliseconds
    GOnn<enter> 1, 2 Sends the actuator to position n, where n is A or B, 3 Sends the actuator to position nn (from 1 to NP) via the shortest route
    HM<enter> 3 Moves the valve to position 1 (home)
    IDa/n<enter> 1, 2, 3 Sets the ID of the actuator to a/n (must be a number 0-9 or letter A-Z)
    IFM<enter> 1, 2, 3 Displays the current actuator response setting
    IFMn<enter> 1, 2, 3 Sets the actuator response where [0] = no response string to move commands; [1] = basic response string to end of move; [2] = extended response strings motor and error status
    LG<enter> 1, 2, 3 Displays the serial response string format
    LGn<enter> 1, 2, 3 Sets the serial response string format where [0] = limited serial response command set; [1] = extended serial response command set (default)
    LRN<enter> 1 Automated procedure to locate A & B mechanical stop positions
    MA<enter> 1, 2, 3 Displays the current motor setting
    MAaaa<enter> 1, 2, 3 Sets the controller to operate the type of motor assembly to be used: EMH, EMD or EMT
    NP<enter> 2, 3 Displays the number of positions the actuator is currently set to index
    NPnn<enter> 2 Sets the number of ports (nn) for the current valve. 3 Sets the number of positions (nn) for the current valve.
    SB<enter> 1, 2, 3 Displays the current baud rate
    SBnnnn<enter> 1, 2, 3 Sets the baud rate to 48(00), 96(00), 192(00), 384(00), 576(00), or 1152(00). The parity setting, number of data bits, and number of stop bits cannot be changed.
    SD<enter> 1, 2, 3 Displays the digital input type of 0 - 3
    SDn<enter> 1, 2, 3 Sets the digital input type to [0] BCD, [1] disabled, [2] parallel, or [3] binary. NOTE: Setting SD to [1] locks out digital inputs until it is changed, or a power cycle occurs. If set to [3], SD reverts to [0] at power up. See Note **
    SL<enter> 1, 2, 3 Displays current Data Latch signal status where 0 = required and 1 = unused
    SLn<enter> 1, 2, 3 This command displays or changes the requirement for a Data Latch signal to accompany BCD inputs. When set to [0] (factory default), the data latch is required for digital inputs. When set to [1], the data latch is NOT required. This feature can reduce the number of control lines required for a system with a dedicated digital output port and only one actuator connected. NOTE: In SL1 mode, be sure all the digital inputs are asserted within 20 milliseconds of each other, or the actuator may be misdirected.
    SM<enter> 3 Displays the current default rotational direction
    SM<enter> 3 In Two Position Mode (AM1,2) SM(n) sets the function of the Control Port inputs from 1 to 4 as follows: SM 1 (dual signal control mode), SM 2 (single signal toggle mode, SM 3 (state mode with enable), SM 4 (state mode with disable). In Multiposition Mode (AM3), SM(n) sets the direction of rotation for the actuator, where F: Forward (toward the next highest numeric position), R: Reverse (toward the next lowest numeric position), A: Auto (shortest route). (See Section 3.6.3 Figure 1)
    SO<enter> 3 Displays the current offset value
    SOnn<enter> 3 Sets the offset value of the first position to be any number from 1 to 96 minus the total number of positions. Example: for a 10 position valve, the offset can be set from 1 to 86.
    STAT<enter> 1, 2, 3 Displays the status of the actuator
    TM<enter> 1, 2, 3 Displays the amount of time required for the previous move, in milliseconds
    TO<enter> 1, 2 Toggles the actuator to the opposite position
    TT<enter> 1, 2 Toggles the actuator to the opposite position, waits a preset delay time, then rotates back to the original position.
    VRn<enter> 1, 2, 3 Displays the current firmware version for the main PCB where n is not used, or for firmware version for the optional interface PCB where n = [2].
    ?<enter> 1, 2, 3 Displays a list of valid commands
    """
