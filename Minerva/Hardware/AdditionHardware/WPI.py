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
from typing import Union, List, Tuple, TYPE_CHECKING, Iterable, Optional, SupportsFloat

import serial
import logging

from Minerva.API.HelperClassDefinitions import AdditionHardware, SyringePumpType, Syringes, SyringeParameters, PumpUnitsVolume, PumpUnitsRate, Volume, FlowRate, TaskScheduler, TaskGroupSynchronizationObject, PathNames

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


class Aladdin(AdditionHardware):
    """
    Class for communication with the WPI Aladdin Syringe Pumps.

    Parameters
    ----------
    com_port : str
        The COM Port the syringe pump is connected to.
    baud_rate : int, default=9600
        The baud Rate for communication with the syringe pump (default is 9600).
    pump_type : SyringePumpType | None, default=SyringePumpType.AL_1050
        The type of the pump, specifying the minimum and maximum flow rates (default is SyringePumpType.AL_1050).

    Raises
    ------
    TimeoutError
        If the Syringe Pump is not responding to a query of its Version Number within 1 s.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, com_port: str, baud_rate: int = 9600, pump_type: SyringePumpType | None = SyringePumpType.AL_1050):
        """
        Constructor for the Aladdin Class for communication with the WPI Aladdin Syringe Pumps.

        Parameters
        ----------
        com_port : str
            The COM Port the syringe pump is connected to.
        baud_rate : int, default=9600
            The baud Rate for communication with the syringe pump (default is 9600).
        pump_type : SyringePumpType | None, default=SyringePumpType.AL_1050
            The type of the pump, specifying the minimum and maximum flow rates (default is SyringePumpType.AL_1050).

        Raises
        ------
        TimeoutError
            If the Syringe Pump is not responding to a query of its Version Number within 1 s.
        """
        super().__init__()
        self.sol = b'\x02'
        self.eol = b'\x03'
        self.com_port = str(com_port).upper()
        self.baud_rate = baud_rate
        self.parity = serial.PARITY_NONE
        self.byte_size = 8
        self.stop_bit = 1
        self.timeout = 1
        self.pump_type = pump_type
        self.default_addition_rate = FlowRate(0, 'ml/min')  # Calculated from syringe diameter when syringe is set
        self._default_addition_rate_percentage = 0.5  # Use half of the maximum rate when calculating the default addition rate from the syringe diameter
        self.retries = 3
        self.current_syringe_parameters: Union[SyringeParameters, None] = None
        self._com_port_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        if not self.com_port.startswith('COM'):
            self.com_port = 'COM' + self.com_port

        self.ser = serial.Serial(self.com_port, baudrate=self.baud_rate, parity=self.parity, bytesize=self.byte_size, stopbits=self.stop_bit, timeout=self.timeout)

        i = 0
        for i in range(0, self.retries):
            try:
                with self._com_port_lock:
                    self.ser.write('VER\r'.encode())
                    self.ser.flush()
                    r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
                if 'SNE' in r:
                    logger.info('Connected to Pump on {}.'.format(self.com_port), extra=self._logger_dict)
                    break
            except TimeoutError:
                continue  # Due to a probable transmission error, please attempt again (up to a maximum of self.retries times)

        if i == self.retries-1:
            logger.critical('Pump not responding on port {}.'.format(self.com_port), extra=self._logger_dict)
            self.ser.close()
            raise TimeoutError('Pump not responding on port {}.'.format(self.com_port))

    def add(self, chemical: Union[Chemical, List[Chemical], Tuple[Chemical, ...]], target_container: Container, withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Adds the specified chemical(s) to the specified container.

        Parameters
        ----------
        chemical : Union[Chemical, List[Chemical], Tuple[Chemical, ...]]
            A list of the chemical(s) to be added.
        target_container : Container
            The container to which the chemical(s) should be added.
        withdraw_rate: Union[FlowRate, float, str, List[FlowRate], List[float], List[str], List[None], None] = None
            Rate at which the chemical(s) are withdrawn. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, List[FlowRate], List[float], List[str], List[None], None] = None
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
            If the hardware configuration is not specified
        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return False

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
            if not self.infuse(volume=c.volume, rate=addition_rate[i], block=block, is_sequential_task=is_sequential_task, priority=priority, task_group_synchronization_object=task_group_synchronization_object):
                return False
            logger.info(f'Finished adding {c} ({c.container.name} -> {target_container.name})', extra=self._logger_dict)
            target_container.current_volume = Volume(target_container.current_volume + c.volume, target_container.current_volume.unit)
        return True

    @staticmethod
    def __float_to_string(f: float) -> str:
        """
        Formats a floating point number to match the format expected by the syringe pump for transmission over RS232. Maximum of 4 digits plus 1 decimal point. Maximum of 3 digits to the right of the decimal point.

        Parameters
        ----------
        f : float
            The floating point number to be formatted.

        Returns
        -------
        str
            A string with the correctly formatted number if successful, '' otherwise.
        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return ''

        if f == 0:
            return '0.000'
        elif f < 0 or f > 9999:
            logger.warning('Number {} out of range. Please use numbers between 0 and 9999.'.format(f))
            return ''

        f_str = str(f)[:4 + int('.' in str(f))].rstrip('.')

        if '.' not in f_str:
            f_str += '.'

        return f_str

    def _set_volume_and_rate(self, volume: Union[Volume, str, float], rate: Union[FlowRate, str, float, None] = None) -> Union[tuple[Volume, FlowRate], None]:
        """
        Sets the volume and rate for infusion/withdrawing.

        Parameters
        ----------
        volume: Union[Volume, str, float]
            The volume that should be infused/withdrawn. If a float is provided, it is assumed to be in mL.
        rate: Union[FlowRate, str, float, None] = None
            Tha rate at which the specified volume is infused/withdrawn. If a float is provided, it is assumed to be in mL/min. If set to None, the default addition rate is used. Default is None.

        Returns
        -------
        tuple[Volume, FlowRate] | tuple
            A tuple of (Volume, FlowRate) if successful, None otherwise
        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return None

        if isinstance(volume, str):
            volume = Volume.from_string(volume)
        elif isinstance(volume, SupportsFloat):
            volume = Volume(volume, 'mL')
        if isinstance(rate, str):
            rate = FlowRate.from_string(rate)
        elif isinstance(rate, SupportsFloat):  # Use SupportsFloat in case the user provided an integer
            rate = FlowRate(rate, 'mL/min')
        elif rate is None:
            rate = self.default_addition_rate

        unit_id = -1
        for u in Volume.units:
            if volume.unit.lower() in map(str.lower, u.string_representations):
                unit_id = u.id
                break
        if unit_id == -1:
            raise NotImplementedError(f'Invalid volume unit: {volume.unit}')
        if unit_id == 2:  # mL
            volume_unit = PumpUnitsVolume.MILLILITERS.value[0]
        elif unit_id == 3:  # uL
            volume_unit = PumpUnitsVolume.MICROLITERS.value[0]
        else:
            volume = volume.convert_to('mL')
            volume_unit = PumpUnitsVolume.MILLILITERS.value[0]

        if isinstance(rate, FlowRate):
            unit_id = -1
            for u in FlowRate.units:
                if rate.unit.lower() in map(str.lower, u.string_representations):
                    unit_id = u.id
                    break
            if unit_id == -1:
                raise NotImplementedError(f'Invalid rate unit: {rate.unit}')
            if unit_id == 6:  # mL/min
                rate_unit = PumpUnitsRate.MILLILITERS_PER_MINUTE.value[0]
            elif unit_id == 7:  # uL/min
                rate_unit = PumpUnitsRate.MICROLITERS_PER_MINUTE.value[0]
            elif unit_id == 11:  # mL/h
                rate_unit = PumpUnitsRate.MICROLITERS_PER_MINUTE.value[0]
            elif unit_id == 12:  # uL/h
                rate_unit = PumpUnitsRate.MICROLITERS_PER_MINUTE.value[0]
            else:
                if rate.in_unit('mL/min') < 16 and rate.in_unit('mL/min') >= 1:
                    rate = rate.convert_to('mL/h')
                    rate_unit = PumpUnitsRate.MILLILITERS_PER_HOUR.value[0]
                elif rate.in_unit('mL/min') < 1 and rate.in_unit('mL/min') >= 0.16:
                    rate = rate.convert_to('uL/min')
                    rate_unit = PumpUnitsRate.MICROLITERS_PER_MINUTE.value[0]
                elif rate.in_unit('mL/min') < 0.16:
                    rate = rate.convert_to('uL/h')
                    rate_unit = PumpUnitsRate.MICROLITERS_PER_HOUR.value[0]
                else:
                    rate = rate.convert_to('mL/min')
                    rate_unit = PumpUnitsRate.MILLILITERS_PER_MINUTE.value[0]

        with self._com_port_lock:
            self.ser.write('VOL{}\r'.format(volume_unit).encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r != '00S':
            logger.error('Error changing volume unit.', extra=self._logger_dict)
            return None

        with self._com_port_lock:
            self.ser.write('VOL{}\r'.format(Aladdin.__float_to_string(volume.value)).encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r != '00S':
            logger.error('Error changing volume.', extra=self._logger_dict)
            return None

        rate = min(rate, FlowRate((math.pi * (0.5 * self.current_syringe_parameters.inner_diameter / 10.0) ** 2) * self.pump_type.value.max_speed, 'mL/min').convert_to(rate_unit))

        with self._com_port_lock:
            self.ser.write('RAT{}{}\r'.format(Aladdin.__float_to_string(rate.value), rate_unit).encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r != '00S':
            logger.error('Error changing rate.', extra=self._logger_dict)
            return None

        logger.info(f'Infusion/withdrawing volume set to {float(Aladdin.__float_to_string(volume.value))} {volume.unit} at a rate of {float(Aladdin.__float_to_string(rate.value))} {rate.unit}', extra=self._logger_dict)
        return volume, rate

    def set_syringe(self, syringe: Syringes, default_addition_rate: Union[FlowRate, str, float, None] = None) -> bool:
        """
        Sets the inner diameter of the syringe (in mm).

        Parameters
        ----------
        syringe : Syringes
            The syringe that is installed.
        default_addition_rate : Union[FlowRate, str, float, None] = None
            The default addition rate that should be used with this syringe. If a float is provided, it is assumed to be in mL/min. If this number is larger than the maximum possible addition rate (calculated based on the chosen syringe), the latter will be used instead. If set to None, a default addition rate will be calculated automatically. Default is None.

        Returns
        -------
        bool
            True if the inner diameter was set successfully, False otherwise
        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return False

        return self.set_syringe_manual(inner_diameter=syringe.value.inner_diameter, volume=syringe.value.volume, default_addition_rate=default_addition_rate)

    def set_syringe_manual(self, inner_diameter: float, volume: float = 0.0, default_addition_rate: Union[FlowRate, str, float, None] = None) -> bool:
        """
        Sets the inner diameter of the syringe (in mm) and optionally its volume (in mL).

        Parameters
        ----------
        inner_diameter : float
            The inner diameter of the syringe (in mm).
        volume : Optional[float] = 0.0
            The volume of the syringe (in mL). Default is 0.0. This value is only necessary for some high-level functions of the syringe pump.
        default_addition_rate : Union[FlowRate, str, float, None] = None
            The default addition rate that should be used with this syringe. If a float is provided, it is assumed to be in mL/min. If this number is larger than the maximum possible addition rate (calculated based on the chosen syringe), the latter will be used instead. If set to None, a default addition rate will be calculated automatically. Default is None.

        Returns
        -------
        bool
            True if the inner diameter was set successfully, False otherwise
        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return False
        d = Aladdin.__float_to_string(inner_diameter)
        if d == '':
            logger.warning('Invalid number.', extra=self._logger_dict)
            return False

        with self._com_port_lock:
            self.ser.write('DIA{}\r'.format(d).encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r != '00S':
            logger.error('Diameter not set', extra=self._logger_dict)
            return False
        else:
            logger.info('Diameter set to {} mm'.format(d), extra=self._logger_dict)
            if self.pump_type is not None:
                if isinstance(default_addition_rate, str):
                    default_addition_rate = FlowRate.from_string(default_addition_rate)
                elif isinstance(default_addition_rate, SupportsFloat):
                    default_addition_rate = FlowRate(default_addition_rate, 'mL/min')

                if default_addition_rate is None:
                    self.default_addition_rate = FlowRate(self._default_addition_rate_percentage * (math.pi * (0.5 * inner_diameter / 10.0) ** 2) * self.pump_type.value.max_speed, 'mL/min')
                else:
                    self.default_addition_rate = FlowRate(min(default_addition_rate.in_unit('mL/min'), (math.pi * (0.5 * inner_diameter / 10.0) ** 2) * self.pump_type.value.max_speed), 'mL/min').convert_to(default_addition_rate.unit)
                self.default_addition_rate.value = float(Aladdin.__float_to_string(self.default_addition_rate.value))
                logger.info(f'Default addition rate set to {self.default_addition_rate}', extra=self._logger_dict)

            syringe_parameters = SyringeParameters(inner_diameter=inner_diameter, volume=volume)
            self.current_syringe_parameters = syringe_parameters
            return True

    @TaskScheduler.scheduled_task
    def infuse(self, volume: Union[Volume, str, float], rate: Union[FlowRate, str, float, None] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Infuses the specified volume at the specified rate.

        Parameters
        ----------
        volume: Union[Volume, str, float]
            The volume that should be infused/withdrawn. If a float is provided, it is assumed to be in mL.
        rate: Union[FlowRate, str, float, None] = None
            Tha rate at which the specified volume is infused/withdrawn. If a float is provided, it is assumed to be in mL/min. If set to None, the default addition rate is used. Default is None.
        block: bool = TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if all parameters were set successfully, False otherwise

        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return False

        if (isinstance(volume, Volume) and volume.value == 0) or (isinstance(volume, str) and Volume.from_string(volume).value == 0) or (isinstance(volume, float) and volume == 0):
            return True

        r = self._set_volume_and_rate(volume=volume, rate=rate)

        if r is None:
            return False
        else:
            volume, rate = r

        with self._com_port_lock:
            self.ser.write('DIR INF\r'.encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r != '00S':
            logger.error('Cannot set mode to Infuse.', extra=self._logger_dict)
            return False

        with self._com_port_lock:
            self.ser.write('RUN\r'.encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r == '':  # timeout
            logger.error('Error while infusing.', extra=self._logger_dict)
            return False

        # Check for completion of infusion step
        with self._com_port_lock:
            self.ser.write('FUN\r'.encode())  # Query current phase function
            fun = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        while 'S' not in fun:  
            time.sleep(0.2)
            with self._com_port_lock:
                self.ser.write('FUN\r'.encode())
                fun = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())

        logger.info(f'Finished infusing {float(Aladdin.__float_to_string(volume.value))} {volume.unit} at a rate of {float(Aladdin.__float_to_string(rate.value))} {rate.unit}', extra=self._logger_dict)
        return True

    @TaskScheduler.scheduled_task
    def withdraw(self, volume: Union[Volume, str, float], rate: Union[FlowRate, str, float, None] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Withdraw the specified volume at the specified rate.

        Parameters
        ----------
        volume: Union[Volume, str, float]
            The volume that should be infused/withdrawn. If a float is provided, it is assumed to be in mL.
        rate: Union[FlowRate, str, float, None] = None
            Tha rate at which the specified volume is infused/withdrawn. If a float is provided, it is assumed to be in mL/min. If set to None, the default addition rate is used. Default is None.
        block: bool = TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if all parameters were set successfully, False otherwise
        """
        if Aladdin.EMERGENCY_STOP_REQUEST:
            return False

        if (isinstance(volume, Volume) and volume.value == 0) or (isinstance(volume, str) and Volume.from_string(volume).value == 0) or (isinstance(volume, float) and volume == 0):
            return True

        r = self._set_volume_and_rate(volume=volume, rate=rate)
        if r is None:
            return False
        else:
            volume, rate = r

        with self._com_port_lock:
            self.ser.write('DIR WDR\r'.encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r != '00S':
            logger.error('Cannot set mode to Withdraw.', extra=self._logger_dict)
            return False

        with self._com_port_lock:
            self.ser.write('RUN\r'.encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if r == '':  # timeout
            logger.error('Error while withdrawing.', extra=self._logger_dict)
            return False

        # Check for completion of withdrawing step
        with self._com_port_lock:
            self.ser.write('FUN\r'.encode())  # Query current phase function
            fun = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        while 'S' not in fun: 
            time.sleep(0.2)
            with self._com_port_lock:
                self.ser.write('FUN\r'.encode())
                fun = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())

        logger.info(f'Finished withdrawing {float(Aladdin.__float_to_string(volume.value))} {volume.unit} at a rate of {float(Aladdin.__float_to_string(rate.value))} {rate.unit}', extra=self._logger_dict)
        return True

    def post_load_from_config(self, kwargs_dict: Dict[str, Any], loaded_configuration_dict: Dict[str, Any]) -> bool:
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
        pump_type = kwargs_dict.pop('pump_type', None)
        for i in SyringePumpType:
            if pump_type in str(i):
                self.pump_type = i
                break
        syringe_type = kwargs_dict.pop('syringe', None)
        for i in Syringes:
            if syringe_type in str(i):
                self.current_syringe_parameters = i.value
                break
        self.default_addition_rate = kwargs_dict.pop('default_addition_rate', None)
        self.set_syringe_manual(inner_diameter=self.current_syringe_parameters[0], volume=self.current_syringe_parameters[1], default_addition_rate=self.default_addition_rate)
        return True

    def emergency_stop(self) -> bool:
        """
        Stops the pump.

        Returns
        -------
        bool
            True if the emergency stop was executed successfully.
        """
        Aladdin.EMERGENCY_STOP_REQUEST = True

        with self._com_port_lock:
            self.ser.write('STP\r'.encode())
            r = self.ser.read_until(self.eol).decode().lstrip(self.sol.decode()).rstrip(self.eol.decode())
        if "S" not in r:
            logger.critical(f"Error in emergency stop protocol", extra=self._logger_dict)
            return False
        else:
            logger.critical(f"Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
            return True


# APPENDIX B: RS-232 COMMAND SUMMARY
# ==================================
# <command> =>
# DIA [ < float > ]  Syringe inside diameter
# PHN [ < phase data > ]  Program Phase number
# FUN [ < phase function > ]  Program Phase function
#     < phase function > =>RAT Pumping rate. “RATE’
#     FIL Fill syringe to volume dispensed. ‘FILL’
#     INC Increment rate. “INCR’
#     DEC Decrement rate. “DECR’
#     STP Stop pump. “STOP’
#     JMP <phase data>  Jump to Program Phase. “
#     JP:nn’PRI Program Selection Input. ‘Pr:In’
#     PRL <count data>  Program Selection Label definition. ‘Pr:nn’
#     LPS Loop starting Phase. “LP:ST’
#     LOP <count data>  Loop to previous loop start_centrifugation “nn” times. “LP:nn’
#     LPE Loop end Phase. “LP:EN’
#     PAS <number data>  Pauses pumping for “nn” seconds. “PS:nn’
#     PAS [n.n] Pauses pumping for ‘n.n’ seconds. ‘PS:n.n’
#     IF   <phase data>  If Program input low, jump to Program Phase. “IF:nn’
#     EVN <phase data>  Set event trigger. “EV:nn’
#     EVS <phase data>  Set event square wave trigger. ‘ES:nn’
#     EVR Event trigger reset. “EV:RS’
#     CLD Clear total dispense volume. ‘CLR.D’
#     TRG <nn>  Override default operational trigger configuration ‘tr:aa’
#     BEP Sound short beep. “BEEP’
#     OUT { 0 | 1 }  Set programmable output pin. “OUT.n’
# RAT [C | I ] [ <float> [ UM | MM | UH | MH ] ]  Pumping rate
# VOL [ <float>|<volume units> ]  Volume to be Dispensed. Do not send the volume units when setting the volume.
# DIR [ INF | WDR | REV ]  Pumping direction
# RUN [ <phase data> ]  Starts the Pumping Program
# [E [<phase data>] ]  Pumping Program event trigger
# PUR Start purge
# STP Stop/pauses the Pumping Program
# DIS Query volume dispensed
# CLD { INF | WDR }  Clear volume dispensed
# SAF [ <n> [ <n> [ <n> ] ] ]  Safe communications mode
# LN  [ 0 | 1]  Low motor noise mode
# AL  [ <on-off> ]  Alarm mode
# PF  [ <on-off> ]  Power failure mode
# TRG [ FT | LE | ST ]  Operational trigger mode
# DIN [ 0 | 1]  Directional input control mode
# ROM [0 | 1]  Pump Motor Operating TTL output mode
# LOC [ <on-off> ]  Keypad lockout mode
# BP  [ <on-off> ]  Key beep mode
# OUT 5 { 0 | 1 }  Set TTL output level
# IN   { 2 | 3 | 4 | 6 }  Query TTL input level
# BUZ [ 0 | { 1 [ < n > ] } ]  Buzzer control
# VER  Query firmware version
#
# System Commands: Valid regardless of current network address
# *ADR [ <n> [<n>] ]  Network address (system command, valid regardless of current address)
# *ADR [ DUAL | RECP | ALTR ]  Set Reciprocating, Dual, or Alternating pumping mode
# *RESET Resets pump.  Clears program memory and resets setup.
#
# Pump Responses:
# ===============
# <response data> => <address> <status> [ <data> ]    From pump
# <status> => { <prompt> | <alarm> }       Operational state of pump
# <prompt> =>
# I  Infusing
# W  Withdrawing
# S  Pumping Program Stopped
# P  Pumping Program Paused
# T  Timed Pause Phase
# U  Operational trigger wait (user wait)
#
# <alarm> => A ? <alarm type>  Alarm
# <alarm type> =>
# R  Pump was reset (power was interrupted)
# S  Pump motor stalled
# T  Safe mode communications time out
# E  Pumping Program error
# O  Pumping Program Phase is out of range
