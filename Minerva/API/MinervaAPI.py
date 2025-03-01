#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

# mypy: disable-error-code="name-defined"
# See mypy issue 8497: [Bug report] Name '...' is not defined when wildcard importing local module

from __future__ import annotations

import inspect
import json
import logging
import atexit
import os
import threading
import queue
import math
import time

import pubchempy as pcp
import re
import requests
import numpy as np
from typing import Union, cast, SupportsFloat, Dict, Any

from Minerva.Hardware import *

from Minerva.API.HelperClassDefinitions import *
from Minerva.API.HelperClassDefinitions import _is_json_serializable, _get_instance_name_from_object

# Create a custom logger and set it to the lowest level
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Add a custom logging level (used for logging synthesis information)
logging.addLevelName(logging.INFO + 5, "SYNTHESIS_STEP")
setattr(logging, "SYNTHESIS_STEP", logging.INFO + 5)

def synthesis_step_log(message: str, *args: Any, **kwargs: Any) -> None:
    if logger.isEnabledFor(logging.SYNTHESIS_STEP):
        logger.log(logging.SYNTHESIS_STEP, message, *args, **kwargs)

setattr(logger, 'synthesis_step', synthesis_step_log)

# Create handlers
c_handler = logging.StreamHandler()
f_handler = logging.FileHandler(filename=os.path.join(PathNames.LOG_DIR.value, 'log.txt'), mode='a')

# Configure the handlers
c_format = logging.Formatter('%(asctime)s<%(thread)d>:%(name)s:%(levelname)s - %(message)s')
f_format = logging.Formatter('%(asctime)s<%(thread)d>:%(name)s:%(levelname)s - %(message)s')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Set the logging levels for the individual handlers
c_handler.setLevel(logging.DEBUG)
f_handler.setLevel(logging.INFO)

# Add handlers to the logger
logger.addHandler(c_handler)
logger.addHandler(f_handler)

logger.info('\n============== Started new Session ==============')


class Configuration(ABC, metaclass=ConfigurationMeta):
    ControllerHardware: Dict[str, Any] = {}
    Hotplates: Dict[str, Any] = {}
    AdditionHardware: Dict[str, Any] = {}
    Centrifuges: Dict[str, Any] = {}
    RobotArms: Dict[str, Any] = {}
    SampleHolder: Dict[str, Any] = {}
    Sonicators: Dict[str, Any] = {}
    OtherHardware: Dict[str, Any] = {}
    Containers: Dict[str, Any] = {}
    Chemicals: Dict[str, Any] = {}

    @staticmethod
    def register_object(obj: Union[Hardware, Chemical, Container]) -> None:
        """
        Static method to register a new Object with this class. Called from the __post__init__ function of the Hardware superclass

        Parameters
        ----------
        obj: Union[Hardware, Chemical, Container]
            The Object to register in this class

        Returns
        -------
        None

        Raises
        ------
        NotImplementedError
            If it is attempted to register an unknown object type
        """
        if isinstance(obj, HotplateHardware) and obj not in Configuration.Hotplates:
            Configuration.Hotplates[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, ControllerHardware) and obj not in Configuration.ControllerHardware:
            Configuration.ControllerHardware[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, AdditionHardware) and obj not in Configuration.AdditionHardware:
            Configuration.AdditionHardware[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, CentrifugeHardware) and obj not in Configuration.Centrifuges:
            Configuration.Centrifuges[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, RobotArmHardware) and obj not in Configuration.RobotArms:
            Configuration.RobotArms[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, SampleHolderHardware) and obj not in Configuration.SampleHolder:
            Configuration.SampleHolder[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, SonicatorHardware) and obj not in Configuration.Sonicators:
            Configuration.Sonicators[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, Hardware) and obj not in Configuration.OtherHardware:
            Configuration.OtherHardware[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, Container) and obj not in Configuration.Containers:
            Configuration.Containers[f'{_get_instance_name_from_object(obj)}'] = obj
        elif isinstance(obj, Chemical) and obj not in Configuration.Chemicals:
            Configuration.Chemicals[f'{_get_instance_name_from_object(obj)}'] = obj
        else:
            raise NotImplementedError

    @staticmethod
    def unregister_object(obj: Union[Hardware, Chemical, Container]) -> None:
        """
        Static method to remove a registered object from the configuration

        Parameters
        ----------
        obj: Union[Hardware, Chemical, Container]
            The Object to register in this class

        Returns
        -------
        None
        """
        for i, j in Configuration:
            for key, val in j.items():
                if obj is val:
                    del j[key]

    @staticmethod
    def update_name_mappings(name_dict: Optional[Dict[str, str]] = None, rename_all: bool = False) -> None:
        """
        Method for updating the names of the objects in the configuration.

        Parameters
        ----------
        name_dict: Optional[Dict[str, str]] = None
            Mapping dictionary in the form {oldname: newname}. If None, current variable names will be used as new names.
        rename_all: bool = False
            If True, all names will be replaced with their variable names, if False, only "generic" names will be replaced. Only has an effect if name_dict is None.

        Returns
        -------
        None
        """
        for _, j in Configuration:
            for k, v in list(j.items()):
                if name_dict is None:
                    if rename_all or k == f'{type(v)}-{id(v)}':
                        j.update({f'{_get_instance_name_from_object(v)}': j.pop(k)})
                elif k in name_dict:
                    j.update({name_dict[k]: j.pop(k)})

    @staticmethod
    @atexit.register
    def save_configuration(configuration_file_path: str = os.path.join(PathNames.CONFIG_DIR.value, 'last_config.json'), update_name_mappings: bool = False) -> Dict[str, Any]:
        """
        Method for serializing the current configuration and saving it to a json file.

        Parameters
        ----------
        configuration_file_path: str = os.path.join(HelperClassDefinitions.PathNames.CONFIG_DIR.value, 'last_config.json')
            The file path to the json file to which the configuration is saved. Default is os.path.join(HelperClassDefinitions.PathNames.CONFIG_DIR.value, 'last_config.json')
        update_name_mappings: bool = False
            If set to True, the names of variables from the global scope will be used as names for the objects in the configuration. Should only be used when remapping variable names to objects.

        Returns
        -------
        Dict[str, Any]
            The json serialization of the current configuration.
        """
        if update_name_mappings:
            Configuration.update_name_mappings()

        config: Dict[str, Any] = {'NameMappings': {}}
        for k, v in Configuration:
            config[k] = {f'{type(i)}-{id(i)}': i.dump_configuration() for _, i in v.items()}
            config['NameMappings'].update({f'{type(j)}-{id(j)}': i for i, j in v.items()})

        with open(configuration_file_path, 'w') as f:
            json.dump(config, fp=f, indent=4)

        return config

    @staticmethod
    def load_configuration(configuration: Union[str, Dict[str, Any]] = os.path.join(PathNames.CONFIG_DIR.value, 'last_config.json')) -> Dict[str, Any]:
        """
        Method for loading a configuration from a json file and deserializing the objects.

        Parameters
        ----------
        configuration: Union[str, Dict[str, Any]] = os.path.join(HelperClassDefinitions.PathNames.CONFIG_DIR.value, 'last_config.json')
            A file path to the configuration file or the json dictionary for deserialization. Default is os.path.join(HelperClassDefinitions.PathNames.CONFIG_DIR.value, 'last_config.json')


        Returns
        -------
        Dict[str, Any]
            The loaded configuration
        """
        # Clear current configuration:
        for _, val in Configuration:
            val.clear()

        # Load new configuration:
        loaded_configuration: Dict[str, Any] = {k: {} for k, _ in Configuration}
        post_load_from_config: List[Tuple[Any, Dict[str, Any]]] = []

        if isinstance(configuration, str):
            with open(configuration, 'r') as f:
                configuration = json.load(f, )

        assert isinstance(configuration, dict)
        name_mappings = configuration.pop('NameMappings')

        error_counter = 0

        # The load order is important here since some components require instances of other components in their constructors. With newer Python versions the order in a dictionary is preserved, this may pose a problem with older python versions, though.
        for k, v in configuration.items():
            for i, j in v.items():
                try:
                    if repr(IkaHotplate.RCTDigital5) in i:
                        tmp_signature = inspect.signature(IkaHotplate.RCTDigital5.__init__).parameters.keys()  # remove any non-constructor entries
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = IkaHotplate.RCTDigital5(**kwargs)
                    elif repr(WPI.Aladdin) in i:
                        tmp_signature = inspect.signature(WPI.Aladdin.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items()}
                        init_kwargs = {key: kwargs.pop(key) for key in list(kwargs.keys()) if key.lstrip('_') in tmp_signature and key != 'pump_type'}  # Set pump_type in post_load
                        loaded_configuration[k][i] = WPI.Aladdin(**init_kwargs)
                        loaded_configuration[k][i].post_load_from_config(kwargs.copy(), None)  # Does not depend on late bindings and can be executed right away
                    elif repr(SwitchingValve.SwitchingValveArduino) in i:
                        tmp_signature = inspect.signature(SwitchingValve.SwitchingValveArduino.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items()}
                        init_kwargs = {key: kwargs.pop(key) for key in list(kwargs.keys()) if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if init_kwargs['arduino_controller'] in n:
                                    if init_kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Arduino_controller "{name_mappings[init_kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        init_kwargs['arduino_controller'] = loaded_configuration[key][init_kwargs['arduino_controller']]
                                        break
                            else:
                                continue
                            break
                        loaded_configuration[k][i] = SwitchingValve.SwitchingValveArduino(**init_kwargs)
                        post_load_from_config.append((loaded_configuration[k][i], kwargs.copy()))
                    elif repr(SwitchingValve.SwitchingValveVici) in i:
                        tmp_signature = inspect.signature(SwitchingValve.SwitchingValveVici.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items()}
                        init_kwargs = {key: kwargs.pop(key) for key in list(kwargs.keys()) if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = SwitchingValve.SwitchingValveVici(**init_kwargs)
                        post_load_from_config.append((loaded_configuration[k][i], kwargs.copy()))
                    elif repr(OpentronsOT2.OT2) in i:
                        tmp_signature = inspect.signature(OpentronsOT2.OT2.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items()}
                        init_kwargs = {key: kwargs.pop(key) for key in list(kwargs.keys()) if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = OpentronsOT2.OT2(**init_kwargs)
                        post_load_from_config.append((loaded_configuration[k][i], kwargs.copy()))
                    elif repr(Herolab.RobotCen) in i:
                        tmp_signature = inspect.signature(Herolab.RobotCen.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = Herolab.RobotCen(**kwargs)
                    elif repr(UFactory.XArm6) in i:
                        tmp_signature = inspect.signature(UFactory.XArm6.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items()}
                        init_kwargs = {key: kwargs.pop(key) for key in list(kwargs.keys()) if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = UFactory.XArm6(**init_kwargs)
                        loaded_configuration[k][i].post_load_from_config(kwargs.copy(), None)  # Does not depend on late bindings and can be executed right away
                    elif repr(Bandelin.SonorexDigitecHRC) in i:
                        tmp_signature = inspect.signature(Bandelin.SonorexDigitecHRC.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = Bandelin.SonorexDigitecHRC(**kwargs)
                    elif repr(Hielscher.UP200ST) in i:
                        tmp_signature = inspect.signature(Hielscher.UP200ST.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = Hielscher.UP200ST(**kwargs)
                    elif repr(ESP32Camera.Camera) in i:
                        tmp_signature = inspect.signature(ESP32Camera.Camera.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = ESP32Camera.Camera(**kwargs)
                    elif repr(ArduinoController.ArduinoController) in i:
                        tmp_signature = inspect.signature(ArduinoController.ArduinoController.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = ArduinoController.ArduinoController(**kwargs)
                    elif repr(EmergencyStopButton.EmergencyStopButton) in i:
                        tmp_signature = inspect.signature(EmergencyStopButton.EmergencyStopButton.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        loaded_configuration[k][i] = EmergencyStopButton.EmergencyStopButton(**kwargs)
                    elif repr(MalvernPanalytical.ZetaSizer) in i:
                        loaded_configuration[k][i] = MalvernPanalytical.ZetaSizer()  # Does not need any arguments for instancing
                    elif repr(HotplateClamp.HotplateClampDCMotor) in i:
                        tmp_signature = inspect.signature(HotplateClamp.HotplateClampDCMotor.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if isinstance(kwargs['parent_hardware'], str) and kwargs['parent_hardware'] in n:
                                    if kwargs['parent_hardware'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Parent hardware "{name_mappings[kwargs["parent_hardware"]]}" not found.')
                                    else:
                                        kwargs['parent_hardware'] = loaded_configuration[key][kwargs['parent_hardware']]
                                if isinstance(kwargs['arduino_controller'], str) and kwargs['arduino_controller'] in n:
                                    if kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Arduino_controller "{name_mappings[kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        kwargs['arduino_controller'] = loaded_configuration[key][kwargs['arduino_controller']]
                        loaded_configuration[k][i] = HotplateClamp.HotplateClampDCMotor(**kwargs)
                    elif repr(HotplateClamp.HotplateClampStepperMotor) in i:
                        tmp_signature = inspect.signature(HotplateClamp.HotplateClampStepperMotor.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if isinstance(kwargs['parent_hardware'], str) and kwargs['parent_hardware'] in n:
                                    if kwargs['parent_hardware'] not in loaded_configuration[key].keys():
                                        raise ValueError(
                                            f'Parent hardware "{name_mappings[kwargs["parent_hardware"]]}" not found.')
                                    else:
                                        kwargs['parent_hardware'] = loaded_configuration[key][kwargs['parent_hardware']]
                                if isinstance(kwargs['arduino_controller'], str) and kwargs['arduino_controller'] in n:
                                    if kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(
                                            f'Arduino_controller "{name_mappings[kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        kwargs['arduino_controller'] = loaded_configuration[key][kwargs['arduino_controller']]
                        loaded_configuration[k][i] = HotplateClamp.HotplateClampStepperMotor(**kwargs)
                    elif repr(HotplateFan.HotplateFan) in i:
                        tmp_signature = inspect.signature(HotplateFan.HotplateFan.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if isinstance(kwargs['parent_hardware'], str) and kwargs['parent_hardware'] in n:
                                    if kwargs['parent_hardware'] not in loaded_configuration[key].keys():
                                        raise ValueError(
                                            f'Parent hardware "{name_mappings[kwargs["parent_hardware"]]}" not found.')
                                    else:
                                        kwargs['parent_hardware'] = loaded_configuration[key][kwargs['parent_hardware']]
                                if isinstance(kwargs['arduino_controller'], str) and kwargs['arduino_controller'] in n:
                                    if kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(
                                            f'Arduino_controller "{name_mappings[kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        kwargs['arduino_controller'] = loaded_configuration[key][kwargs['arduino_controller']]
                        loaded_configuration[k][i] = HotplateFan.HotplateFan(**kwargs)
                    elif repr(DHT22Sensor.DHT22Sensor) in i:
                        tmp_signature = inspect.signature(DHT22Sensor.DHT22Sensor.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if isinstance(kwargs['arduino_controller'], str) and kwargs['arduino_controller'] in n:
                                    if kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Arduino_controller "{name_mappings[kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        kwargs['arduino_controller'] = loaded_configuration[key][kwargs['arduino_controller']]
                        loaded_configuration[k][i] = DHT22Sensor.DHT22Sensor(**kwargs)
                    elif repr(CapperDecapper.CapperDecapper) in i:
                        tmp_signature = inspect.signature(CapperDecapper.CapperDecapper.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if kwargs['arduino_controller'] in n:
                                    if kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Arduino_controller "{name_mappings[kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        kwargs['arduino_controller'] = loaded_configuration[key][kwargs['arduino_controller']]
                                        break
                            else:
                                continue
                            break
                        loaded_configuration[k][i] = CapperDecapper.CapperDecapper(**kwargs)
                    elif repr(Electromagnet.Electromagnet) in i:
                        tmp_signature = inspect.signature(Electromagnet.Electromagnet.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if kwargs['arduino_controller'] in n:
                                    if kwargs['arduino_controller'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Arduino_controller "{name_mappings[kwargs["arduino_controller"]]}" not found.')
                                    else:
                                        kwargs['arduino_controller'] = loaded_configuration[key][kwargs['arduino_controller']]
                                        break
                            else:
                                continue
                            break
                        loaded_configuration[k][i] = Electromagnet.Electromagnet(**kwargs)
                    elif repr(SampleHolder.SampleHolder) in i:
                        tmp_signature = inspect.signature(SampleHolder.SampleHolder.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        if kwargs['parent_hardware'] == i or kwargs['parent_hardware'] is None:
                            kwargs['parent_hardware'] = None
                        else:
                            for key in configuration.keys():
                                for n in configuration[key].keys():
                                    if kwargs['parent_hardware'] in n:
                                        if kwargs['parent_hardware'] not in loaded_configuration[key].keys():
                                            raise ValueError(f'Parent hardware "{name_mappings[kwargs["parent_hardware"]]}" not found.')
                                        else:
                                            kwargs['parent_hardware'] = loaded_configuration[key][kwargs['parent_hardware']]
                                            break
                                else:
                                    continue
                                break
                        loaded_configuration[k][i] = SampleHolder.SampleHolder(**kwargs)
                    elif repr(Container) in i:
                        tmp_signature = inspect.signature(Container.__init__).parameters.keys()
                        kwargs = {key.lstrip('_'): val for key, val in j.items() if key.lstrip('_') in tmp_signature}
                        for key in configuration.keys():
                            for n in configuration[key].keys():
                                if kwargs['current_hardware'] in n:
                                    if kwargs['current_hardware'] not in loaded_configuration[key].keys():
                                        raise ValueError(f'Current hardware "{name_mappings[kwargs["current_hardware"]]}" not found.')
                                    else:
                                        kwargs['current_hardware'] = loaded_configuration[key][kwargs['current_hardware']]
                                        break
                            else:
                                continue
                            break
                        if 'container_type' in kwargs.keys() and kwargs['container_type'] is not None:
                            kwargs['container_type'] = ContainerTypeCollection.ContainerDescription(*kwargs['container_type'])
                        loaded_configuration[k][i] = Container(**kwargs)
                    elif repr(Chemical) in i:
                        kwargs = {key.lstrip('_'): val for key, val in j.items()}
                        if kwargs['container'] not in loaded_configuration['Containers'].keys():
                            raise ValueError(f'Container "{name_mappings[kwargs["container"]]}" not found.')
                        else:
                            kwargs['container'] = loaded_configuration['Containers'][kwargs['container']]
                            loaded_configuration[k][i] = Chemical(**kwargs)
                    else:
                        pass  # Implement your custom loading routine for other hardware here
                except Exception as ex:
                    logger.error(f'Error while loading configuration. Could not restore object "{k}: {name_mappings[i]}". Error message: {ex}')
                    if i in loaded_configuration.keys():
                        loaded_configuration[k].pop(i)
                    error_counter += 1

        # Perform any remaining post_initialization
        for hw, d in post_load_from_config:
            hw.post_load_from_config(kwargs_dict=d, loaded_configuration_dict=loaded_configuration)

        # Restore original names:
        for i in loaded_configuration.values():
            for k, v in i.items():
                name_mappings[f'{type(v)}-{id(v)}'] = name_mappings.pop(k)
        Configuration.update_name_mappings(name_mappings)

        if error_counter == 0:
            logger.info(f'Configuration loaded successfully:\n{Configuration}')
        elif error_counter == 1:
            logger.info(f'Configuration loaded, but there was {error_counter} error:\n{Configuration}')
        else:
            logger.info(f'Configuration loaded, but there were {error_counter} errors:\n{Configuration}')

        return loaded_configuration

    @staticmethod
    def disable_autosave_on_exit() -> None:
        """Disable configuration autosaving on exit"""
        atexit.unregister(Configuration.save_configuration)

    @staticmethod
    def enable_autosave_on_exit() -> None:
        """Enable configuration autosaving on exit (enabled by default, so only needs to be enabled after disabling)"""
        atexit.register(Configuration.save_configuration)

    @staticmethod
    def request_emergency_stop() -> None:
        """Sends an emergency stop request to all registered hardware"""
        logger.critical('EMERGENCY STOP REQUEST RECEIVED.\nBroadcasting to all registered Hardware and Task Scheduler...')
        TaskScheduler.EMERGENCY_STOP_REQUEST = True
        for k, v in Configuration:
            if k == Configuration.Chemicals or k == Configuration.Containers or k == Configuration.SampleHolder:
                continue
            for i, j in v.items():
                try:
                    logger.critical(f'Emergency stop request sent to {str(j)}.')
                    j.EMERGENCY_STOP_REQUEST = True
                    j.emergency_stop()
                except Exception:
                    pass  # Ignore and send out emergency stop requests to next hardware


class ContainerMeta(ABCMeta):
    def __call__(cls: ABCMeta, *args: Any, **kwargs: Any) -> Container:
        # Unlike with Hardware that can throw an error when trying to instantiate twice (e.g. due to the port already being used), the container can be instantiated, checked, and then either returned or discarded
        obj = type.__call__(cls, *args, **kwargs)
        for i in MinervaAPI.Configuration:
            for k, v in i[1].items():
                if str(v) == str(obj):
                    return v
        MinervaAPI.Configuration.register_object(obj)
        return obj


class Container(metaclass=ContainerMeta):
    """
    Class specifying a container object that can hold a chemical (can be a flask, tube, etc.)

    Parameters
    ----------
    current_hardware : Hardware
        The hardware where the container is currently located.
    deck_position : int, default = 0
        The deck number of the holder (if the parent hardware has several positions for holders). If current_hardware is a SampleHolder, the deck number of the sample holder will be used. Default is 0.
    slot_number : int, default = 0
        Optional number of the slot of the holder (for holders with several slots) or the valve position (if the hardware is a syringe pump) that can be used to access the container, default is 0
    name : str, default = ''
        Optional name of the container, default = '' (a name will be generated automatically based on the container type or class).
    current_volume : Union[Volume, str, None] = None
        Optional value specifying the volume that is currently in the container and not already assigned to any queued commands, default is None. If None, it is assumed that the container is empty
    max_volume : Union[Volume, str, None] = None
        Optional value the maximum volume the container can hold. If not None, it will be checked if an addition exceeds the maximum volume, default is None. If None, no checks if additions will exceed max volume are performed.
    container_type : Union[ContainerTypeCollection.ContainerDescription, None], default = None
        The type and height of the container in mm. Needs to be specified if the container should be picked up and moved by the robotic arm, and if the OT2 should adjust the aspirating/dispensing height of the pipette depending on the fill level of the container.
    has_stirbar : bool, default = False
        Indicating whether there is currently a stirbar in the container (important for e.g. subsequent stirring operations or centrifugation steps), default is False
    is_capped : bool, default = False
        Indicating whether there is currently a cap on the container, default is False

    Raises
    ------
    AssertionError
        If an invalid value is entered for any of the fields.
    """
    def __init__(self, current_hardware: Hardware, deck_position: int = 0, slot_number: int = 0, name: str = '', current_volume: Union[Volume, str, None] = None, max_volume: Union[Volume, str, None] = None, container_type: Union[ContainerTypeCollection.ContainerDescription, None] = None, has_stirbar: bool = False, is_capped: bool = False):
        if isinstance(current_volume, str):
            current_volume = Volume.from_string(current_volume)
        if isinstance(max_volume, str):
            max_volume = Volume.from_string(max_volume)

        assert isinstance(current_hardware, Hardware), 'invalid hardware'
        assert isinstance(deck_position, int) and deck_position >= 0, 'deck_position must be an integer >= 0'
        assert isinstance(slot_number, int) and slot_number >= 0, 'slot_number must be an integer >= 0'
        assert current_volume is None or isinstance(current_volume, Volume), 'invalid value for current_volume'
        assert max_volume is None or isinstance(max_volume, Volume), 'invalid value for max_volume'

        if isinstance(current_hardware, SampleHolderHardware):
            deck_position = current_hardware.deck_position

        self.name = str(name)
        self._current_hardware = current_hardware
        self._deck_position = int(deck_position)
        self._slot_number = int(slot_number)
        self._current_volume = current_volume
        self._max_volume = max_volume
        self._container_type = container_type
        self._has_stirbar = bool(has_stirbar)
        self._is_capped = bool(is_capped)
        self._container_availability_lock = threading.Lock()

        if self.name == '':
            if self.container_type is None:
                self.name = f'{self.__class__.__name__}_{id(self)}'
            else:
                self.name = f'{self.container_type.container_name}_{id(self)}'

        if current_volume is None:
            self._current_volume = Volume(0, 'mL')

        if max_volume is not None:
            self._max_volume = max_volume
        elif isinstance(self._container_type, (ContainerTypeCollection, ContainerTypeCollection.ContainerDescription)):
            self._max_volume = Volume(self._container_type.container_max_volume, 'mL')

        if isinstance(self._current_hardware, SampleHolderHardware):
            self._current_hardware.available_slots[slot_number] = self.name

    def __str__(self) -> str:
        """Function returning a human-readable string description of the class with some information."""
        if self.container_type is None:
            tmp_name = self.__class__.__name__
            if self.name != f'{self.__class__.__name__}_{id(self)}':
                tmp_name += f'[{self.name}]'
        else:
            tmp_name = self.container_type.container_name
            if self.name != f'{self.container_type.container_name}_{id(self)}':
                tmp_name += f'[{self.name}]'

        if self.current_volume is None:
            tmp_vol = ''
        else:
            if self.current_volume.value >= 1e-3 and self.current_volume.value < 1e4:
                tmp_vol = f': {round(self.current_volume.value, 4)} {self.current_volume.unit}'
            else:
                tmp_vol = f': {self.current_volume.value:.3e} {self.current_volume.unit}'

        return f'{tmp_name}{tmp_vol} at {self.current_hardware}->slot {self.slot_number}'

    @property
    def current_hardware(self) -> Hardware:
        return self._current_hardware

    @property
    def deck_position(self) -> int:
        return self._deck_position

    @property
    def slot_number(self) -> int:
        return self._slot_number

    @property
    def current_volume(self) -> Union[Volume, None]:
        return self._current_volume

    @current_volume.setter
    def current_volume(self, value: Volume) -> None:
        self._current_volume = value

    @property
    def max_volume(self) -> Union[Volume, None]:
        return self._max_volume

    @property
    def container_type(self) -> Union[ContainerTypeCollection.ContainerDescription, None]:
        return self._container_type

    @property
    def has_stirbar(self) -> bool:
        return self._has_stirbar

    @property
    def is_capped(self) -> bool:
        return self._is_capped

    def dump_configuration(self) -> Dict[str, Any]:
        """Dump all current instance vars in a json-serializable dict."""
        return_dict = {}
        for k, v in vars(self).items():
            if _is_json_serializable(v):
                return_dict[k] = v
            elif isinstance(v, Quantity):
                return_dict[k] = str(v)
            else:
                return_dict[k] = f'{type(v)}-{id(v)}'
        return return_dict

    def add_chemical(self, chemical: Union[Chemical, List[Chemical], Tuple[Chemical]], withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, robot_arm: RobotArmHardware = None, capper_decapper: Hardware = None, return_container_after_addition: bool = False, return_chemicals_after_addition: bool = True, bottom_clearance: Optional[float] = None, purging_volume: Union[Volume, str, float, None] = '30 mL', purging_addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, purging_port: Union[int, None] = None, priming_volume: Union[Volume, str, float, None] = None, priming_waste_container: Optional[Container] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for adding a chemical to this container

        Parameters
        ----------
        chemical : Union[Chemical, List[Chemical], Tuple[Chemical, ...]]
            The chemical or list of chemicals that should be added to the container
        withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are withdrawn. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are added. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the appropriate hardware for addition. If set to None and the container and chemical to be added are not already at the same hardware (e.g., both in the OT2), the first registered robot arm will be used. Default is None
        capper_decapper: Hardware = None
            The capper/decapper hardware to be used for opening/closing the cap on the container(s). If set to None and a container is closed, the first registered capper/decapper will be used. Default is None.
        return_container_after_addition: bool = False
            Whether to try to return the container to its original sample holder after the addition is complete (the original slot will be tried first, if it is not available another slot in the same sample holder will be tried, if none are available the container will not be moved back). If set to False, the container will remain with the addition hardware (if the addition hardware has a sample holder). Default is False.
        return_chemicals_after_addition: bool = True
            Whether to return the chemicals to their original spot after the addition is complete (the original slot will be tried first, if it is not available another slot in the same sample holder will be tried, if none are available the chemical will not be moved back). If set to False, the chemicals will remain with the addition hardware. Default is True.
        bottom_clearance : Optional[float], default = None
            Optional parameter, only used when adding chemicals via a needle from a syringe pump or valve. Indicates the height in mm above the bottom of the vessel. Default is None, resulting in 45 mm for flasks and 20 mm for falcon tubes.
        purging_volume: Union[Volume, str, float, None] = '30 mL'
            Volume of air that is used for purging the tube/needle after dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve. If a float is supplied, it will be assumed to be in mL. Default is 30 mL.
        purging_addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate that is used when purging the tube/needle after dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve and a purging volume is not None. If a float is supplied, it will be assumed to be in milliliters per minute. Default is None, which means the default_addition_rate of the syringe pump will be used.
        purging_port: Union[int, None] = None:
            Port on a valve that is used to draw in air for purging. Only has an effect if the addition hardware is a valve and a purging volume is not None. Default is None, which means the outlet_port of the syringe pump will be used.
        priming_volume: Union[Volume, str, float, None] = None
            Volume of chemical(s) that is used for priming the tube before dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve. If specified, the parameter priming_waste_container also needs to be specified. If a float is supplied, it will be assumed to be in mL. Default is None.
        priming_waste_container: Optional[Container] = None
            Container for discarding the chemical that is used during priming. Only has an effect if the addition hardware is a valve and a priming volume is specified. Has to be connected to the same valve as the chemical(s) that are used for priming. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if the addition was successful, False otherwise

        Raises
        ------
        AssertionError
            If an invalid chemical is passed to the method or the addition exceeds the maximum volume of the container
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

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
        if purging_addition_rate is None:
            purging_addition_rate = [None] * len(chemical)
        elif not isinstance(purging_addition_rate, List):
            purging_addition_rate = [purging_addition_rate]

        try:
            target_hardware = None
            deck_position = 0
            slot_number = 0
            previous_hardware_container = self._current_hardware
            previous_slot_number_container = self._slot_number
            previous_hardware_chemicals = [c.container.current_hardware for c in chemical]
            previous_slot_number_chemicals = [c.container.slot_number for c in chemical]
            sample_holder_is_full: Dict[Hardware.SampleHolder.SampleHolder, bool] = {}

            if len(chemical) != len(addition_rate) or len(chemical) != len(withdraw_rate) or (len(chemical) != len(purging_addition_rate) and purging_volume is not None):
                raise CustomError('If a list of chemicals and addition/withdraw rates are provided, the lists must be of the same length.')

            if purging_volume is not None:
                if isinstance(purging_volume, str):
                    purging_volume = Volume.from_string(purging_volume)
                elif isinstance(purging_volume, SupportsFloat):
                    purging_volume = Volume(purging_volume, 'mL')

            if priming_volume is not None:
                if priming_waste_container is None:
                    raise CustomError('If a priming volume is specified, you also need to specify a priming waste container for discarding the liquid used in the priming step.')
                if isinstance(priming_volume, str):
                    priming_volume = Volume.from_string(priming_volume)
                elif isinstance(priming_volume, SupportsFloat):
                    priming_volume = Volume(priming_volume, 'mL')

            if bottom_clearance is None:
                if self.container_type is not None:
                    if 'FLASK' in self.container_type.container_name:
                        bottom_clearance = 45
                    else:
                        bottom_clearance = 20
                else:
                    bottom_clearance = 0

            if any([c.container.is_capped for c in chemical]) and self.is_capped:
                number_of_capper_decapper = 0
                for hw in Configuration.OtherHardware.values():
                    if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                        number_of_capper_decapper += 1
                if number_of_capper_decapper < 2:
                    raise CustomError(f'At least two capped containers are involved in the addition step, which exceeds to number of currently available capper/decappers.')
            original_container_was_capped = self.is_capped

            # Check for the availability of suitable additional hardware for the respective containers
            start_time = time.time()
            warning_is_logged = False
            while True:  # Loop until a slot in a suitable sample holder becomes available or a timeout occurs
                # First, check for the chemicals which can be added with the syringe/valve that do not require sample holders
                sample_holder_is_full = {}
                addition_hardware_check: List[Union[Hardware, None]] = [c.container.current_hardware if (isinstance(c.container.current_hardware, WPI.Aladdin) or isinstance(c.container.current_hardware, SwitchingValve.SwitchingValve)) else None for c in chemical]
                for i, c in enumerate(chemical):
                    if addition_hardware_check[i] is not None:  # If the chemical does not require a sample holder, skip to the next one:
                        continue
                    if not isinstance(c.container.current_hardware, SampleHolderHardware):  # If a sample holder is required and the chemical is "part of" the addition hardware and cannot be moved, make sure this addition hardware can also fit the current container
                        for h in Configuration.SampleHolder.values():
                            if (h.parent_hardware is c.container.current_hardware and self.container_type.container_name in h.hardware_definition['metadata']['tags']) or self.name in h.available_slots.values():
                                # Reserve a slot in the hardware if one is not already allocated, and if a slot is available
                                if self.name not in h.available_slots.values():
                                    if h.get_next_free_slot() is not None:
                                        h.available_slots[h.get_next_free_slot()] = self.name
                                    else:
                                        sample_holder_is_full[h] = True
                                # Mark the hardware as suitable for the addition
                                addition_hardware_check[i] = c.container.current_hardware
                                break
                        else:  # For loop ended without finding anything suitable
                            raise CustomError('No suitable addition hardware found that is compatible with the containers involved in this addition step.')
                    else:  # If the chemical can be moved, attempt to identify an addition hardware that can accommodate both the container itself and the chemical to be added
                        if isinstance(c.container.current_hardware.parent_hardware, AdditionHardware):  # If the chemical to be added is already present in an addition hardware, check for its compatibility for the container as well
                            for h in Configuration.SampleHolder.values():
                                if (h.parent_hardware is c.container.current_hardware.parent_hardware and self.container_type.container_name in h.hardware_definition['metadata']['tags']) or self.name in h.available_slots.values():
                                    # "Reserve" a slot in the hardware (if not already done)
                                    if self.name not in h.available_slots.values():
                                        if h.get_next_free_slot() is not None:
                                            h.available_slots[h.get_next_free_slot()] = self.name
                                        else:
                                            sample_holder_is_full[h] = True
                                    # Mark the hardware as suitable for the addition
                                    addition_hardware_check[i] = c.container.current_hardware
                                    break
                        # If no suitable addition hardware was found, or if the chemical to be added is not already in an addition hardware, attempt to identify the one that works with both the container and the chemical
                        if addition_hardware_check[i] is None:
                            for ah in Configuration.AdditionHardware.values():
                                match_chemical = False
                                match_container = False
                                addition_hardware_check[i] = None
                                for sh in Configuration.SampleHolder.values():
                                    if sh.parent_hardware is ah:
                                        if c.container.container_type.container_name in sh.hardware_definition['metadata']['tags'] or c.container.name in sh.available_slots.values():
                                            match_chemical = True
                                            # "Reserve" a slot in the hardware (if not already done)
                                            if self.name not in sh.available_slots.values():
                                                if sh.get_next_free_slot() is not None:
                                                    sh.available_slots[sh.get_next_free_slot()] = self.name
                                                else:
                                                    sample_holder_is_full[sh] = True
                                            # Mark the hardware as suitable for the addition (will later be reset to None if the container is not compatible)
                                            addition_hardware_check[i] = sh
                                        if self.container_type.container_name in sh.hardware_definition['metadata']['tags'] or self.name in sh.available_slots.values():
                                            match_container = True
                                            # "Reserve" a slot in the hardware (if not already done)
                                            if self.name not in sh.available_slots.values():
                                                if sh.get_next_free_slot() is not None:
                                                    sh.available_slots[sh.get_next_free_slot()] = self.name
                                                else:
                                                    sample_holder_is_full[sh] = True

                                        if match_chemical and match_container:
                                            break
                                if match_chemical and match_container:
                                    break
                            else:
                                addition_hardware_check[i] = None

                if any([v is None for v in addition_hardware_check]):
                    raise CustomError('No suitable addition hardware found that is compatible with the containers involved in this addition step.')

                # Remove unneeded slot reservations
                for c in chemical:
                    for h in Configuration.SampleHolder.values():
                        if h not in addition_hardware_check and h is not c.container.current_hardware and h is not self.current_hardware and self.container_type is not None and self.container_type.container_name not in h.hardware_definition['metadata']['tags'] and (c.container.name in h.available_slots.values() or self.name in h.available_slots.values()):
                            for k, v in h.available_slots.items():
                                if v == c.container.name or v == self.name:
                                    h.available_slots[k] = None

                if not any(sample_holder_is_full):
                    break
                elif not warning_is_logged:
                    logger.warning(f'Some required sample holders of the addition hardware are full: {", ".join([str(h) for h in sample_holder_is_full.keys()])}. Waiting for free slots to become available...')
                    warning_is_logged = True
                if time.time() - start_time > 1800:
                    raise CustomError(f'Timed out while waiting for free slots becoming available in sample holders {", ".join([str(h) for h in sample_holder_is_full.keys()])}')

                time.sleep(1)

            i = 0
            keep_container_slot = return_container_after_addition

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            while i < len(chemical):
                # Group sequential additions of chemicals that require the same addition hardware, respecting the order of additions
                chemicals: List[Chemical] = []
                addition_rates: List[Union[FlowRate, float, str, None]] = []
                withdraw_rates: List[Union[FlowRate, float, str, None]] = []
                purging_addition_rates: List[Union[FlowRate, float, str, None]] = []
                addition_hardware = addition_hardware_check[i].parent_hardware
                found_capped_container = False
                j = i
                while j < len(addition_hardware_check) and addition_hardware_check[j].parent_hardware is addition_hardware:
                    # Ensure only one container per group is capped
                    if chemical[j].container.is_capped and found_capped_container:
                        break
                    elif chemical[j].container.is_capped and not found_capped_container:
                        found_capped_container = True

                    chemicals.append(chemical[j])
                    addition_rates.append(addition_rate[j])
                    withdraw_rates.append(withdraw_rate[j])
                    purging_addition_rates.append(purging_addition_rate[j])
                    j += 1

                # Move chemicals to the addition hardware if necessary
                for n, k in enumerate(chemicals):
                    # wait until required container is available
                    if is_internal_tgso:
                        k.container._container_availability_lock.acquire()

                    chemical_container_was_capped = k.container.is_capped

                    if k.container.current_hardware.parent_hardware != addition_hardware:
                        if robot_arm is None:
                            assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to {addition_hardware}.'
                            robot_arm = list(Configuration.RobotArms.values())[0]
                        tmp_target_hardware = addition_hardware_check[i+n]
                        assert isinstance(tmp_target_hardware, SampleHolderHardware)
                        tmp_target_slot = 0
                        for key, val in tmp_target_hardware.available_slots.items():
                            if val == k.container.name:
                                tmp_target_slot = key
                                break

                        # Wait until required hardware is ready to process the current task group and then block the hardware during this step
                        required_hardware = [robot_arm]
                        if k.container.is_capped:
                            if capper_decapper is None:
                                for hw in Configuration.OtherHardware.values():
                                    if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                                        capper_decapper = hw
                                        break
                                else:
                                    raise CustomError(f'At least one container is capped, but no capper/decapper for opening the container was specified.')
                            required_hardware.append(capper_decapper)

                        TaskScheduler.wait_for_hardware(required_hardware, tgso)

                        if k.container.is_capped:
                            if not k.container.uncap(capper_decapper=capper_decapper, robot_arm=robot_arm):
                                raise CustomError(f'Error while uncapping Container {k}')
                        if not k.container.move(target_hardware=tmp_target_hardware, robot_arm=robot_arm, target_slot_number=tmp_target_slot, task_group_synchronization_object=tgso):  # tgso might not be needed here yet
                            raise CustomError(f'Error while moving Container {k} to {tmp_target_hardware}')
                    else:
                        if k.container.is_capped:
                            if capper_decapper is None:
                                for hw in Configuration.OtherHardware.values():
                                    if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                                        capper_decapper = hw
                                        break
                                else:
                                    raise CustomError(f'At least one container is capped, but no capper/decapper for opening the container was specified.')
                            required_hardware = [robot_arm, capper_decapper]
                            TaskScheduler.wait_for_hardware(required_hardware, tgso)
                            if not k.container.uncap(capper_decapper=capper_decapper, robot_arm=robot_arm):
                                raise CustomError(f'Error while uncapping Container {k}')

                required_hardware = [addition_hardware]

                # Move container to the addition hardware if necessary
                if self.current_hardware.parent_hardware != addition_hardware:
                    if robot_arm is None:
                        assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to {addition_hardware}.'
                        robot_arm = list(Configuration.RobotArms.values())[0]

                    # Wait until required hardware is ready to process the current task group and then block the hardware during this step
                    required_hardware.append(robot_arm)
                    if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                        required_hardware.append(addition_hardware.syringe_pump)
                    TaskScheduler.wait_for_hardware(required_hardware, tgso)

                    if isinstance(addition_hardware, OpentronsOT2.OT2):
                        for sh in Configuration.SampleHolder.values():
                            if sh.parent_hardware is addition_hardware and self.name in sh.available_slots.values():
                                target_slot = 0
                                for key, val in sh.available_slots.items():
                                    if val == self.name:
                                        target_slot = key
                                        break
                                if not self.move(target_hardware=sh, robot_arm=robot_arm, target_slot_number=target_slot, vacate_previous_slot=not keep_container_slot, task_group_synchronization_object=tgso):  # task grouping is only really necessary when a valve/syringe pump is used (i.e., for non pick&place operations), but if movement to a valve addition hardware ocurred before, these additions should still be part of the same task group
                                    raise CustomError(f'Error while moving container {self.name} to {addition_hardware}.')
                                keep_container_slot = False  # Only keep the first slot reserved for the container
                                break
                        else:
                            if is_internal_tgso:
                                self._container_availability_lock.release()
                            raise RuntimeError(f'Error while moving container {self.name} to {addition_hardware}.')
                    else:
                        if not self.move(target_hardware=addition_hardware, robot_arm=robot_arm, bottom_clearance=bottom_clearance, vacate_previous_slot=False, task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while moving container {self.name} to {addition_hardware}.')
                else:
                    # Wait until required hardware is ready to process the current task group and then block the hardware during this step
                    if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                        required_hardware.append(addition_hardware.syringe_pump)

                    TaskScheduler.wait_for_hardware(required_hardware, tgso)

                # Start the addition
                assert isinstance(addition_hardware, AdditionHardware), 'Invalid addition hardware'
                if isinstance(addition_hardware, OpentronsOT2.OT2):
                    # Release the robot arm from the task group while the OT2 is adding chemicals unless a valve or syringe pump is handling the addition. Always release it here, even for external tgso (OT2 addition is slow, and does not require the robot arm until it is finished)
                    TaskScheduler.release_hardware(robot_arm, tgso)

                    if not addition_hardware.add(chemical=chemicals, withdraw_rate=withdraw_rates, addition_rate=addition_rates, target_container=self, task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while adding chemical(s) {chemicals} with {addition_hardware}.')
                else:
                    if isinstance(addition_hardware, SwitchingValve.SwitchingValve) and priming_volume is not None and priming_waste_container not in addition_hardware.configuration.values():
                        raise CustomError(f'The priming waste container {priming_waste_container} needs to be connected to the same valve ({addition_hardware}) that is also used for adding the chemical(s) {chemicals}.')
                    for j, c in enumerate(chemicals):
                        if priming_volume is not None:
                            logger.info(f'Priming addition hardware {addition_hardware} with chemical {c}.')
                            if not addition_hardware.add(chemical=Chemical.from_stock_chemical(c, volume=priming_volume), withdraw_rate=None, addition_rate=None, target_container=priming_waste_container, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while priming addition hardware {addition_hardware} with chemical {c}.')
                            if isinstance(addition_hardware,SwitchingValve.SwitchingValve) and purging_volume is not None and purging_volume.value > 0:
                                if not addition_hardware._purge(target_container=priming_waste_container, purging_addition_rate=None, purging_volume=purging_volume, purging_port=purging_port, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error purging the tube connected to syringe pump after priming.')

                        if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                            dead_volume = addition_hardware.dead_volumes[addition_hardware.outlet_port]
                            if isinstance(dead_volume, str):
                               dead_volume = Volume.from_string(dead_volume).convert_to('mL')
                            elif isinstance(dead_volume, SupportsFloat):
                                dead_volume = Volume(dead_volume, 'mL')
                            elif isinstance(dead_volume, Volume):
                                dead_volume = dead_volume.convert_to('mL')
                            elif dead_volume is None:
                                dead_volume = Volume(0, 'mL')

                            # Addition of chemicals in more than one step (in terms of volume), such that the first step (dead_volume) is at the default rate before the actual addition of chemical starts
                            if c.volume <= dead_volume:
                                # fill the tube with the desired volume of the chemical
                                if not addition_hardware.add(chemical=c, withdraw_rate=withdraw_rates[j], addition_rate=None, target_container=self, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while filling tube with chemical {c}.')
                                # purge with air at a higher rate until the chemical has passed the dead volume
                                if not addition_hardware._purge(target_container=self, purging_addition_rate=None, purging_volume=(dead_volume - c.volume), purging_port=purging_port, robot_arm=None, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while purging dead volume from the tube.')
                                # continue purging with air to add the chemical at the desired addition rate
                                if not addition_hardware._purge(target_container=self, purging_addition_rate=addition_rates[j], purging_volume=c.volume, purging_port=purging_port, robot_arm=None, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while adding chemical {c}.')
                            else:  # addition in two volume steps, first covering the dead volume and second the actual desired volume of the chemical
                                if dead_volume > 0:
                                    chemical_dead_volume = Chemical.from_stock_chemical(c, volume=dead_volume)
                                    # fill the tube with the chemical and add the amount correspopnding to the dead volume at a higher rate
                                    if not addition_hardware.add(chemical=chemical_dead_volume, withdraw_rate=withdraw_rates[j], addition_rate=None, target_container=self, task_group_synchronization_object=tgso):
                                        raise CustomError(f'Error while filling tube with chemical {c}.')
                                chemical_main_volume = Chemical.from_stock_chemical(c, volume=Volume(c.volume.in_unit('mL') - dead_volume.value, 'mL'))
                                # after the chemical has passed the dead volume of the tube, add the rest at the desired rate
                                if not addition_hardware.add(chemical=chemical_main_volume, withdraw_rate=withdraw_rates[j], addition_rate=addition_rates[j], target_container=self, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while adding chemical {c}.')
                                # purge the remaining chemical in the tube with air at the desired rate
                                if not addition_hardware._purge(target_container=self, purging_addition_rate=addition_rates[j], purging_volume=dead_volume, purging_port=purging_port, robot_arm=None, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while adding chemical {c}.')
                        else:
                            if not addition_hardware.add(chemical=c, withdraw_rate=withdraw_rates[j], addition_rate=addition_rates[j], target_container=self, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while adding chemical {c} with {addition_hardware}.')

                        # Purging step
                        if isinstance(addition_hardware, SwitchingValve.SwitchingValve) and purging_volume is not None and purging_volume.value > 0:
                            if not addition_hardware._purge(target_container=self, purging_addition_rate=purging_addition_rates[j], purging_volume=purging_volume, purging_port=purging_port, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while performing purging step.')

                # If the chemical container was capped, recap it and release the capper/decapper
                if chemical_container_was_capped:
                    k.container.cap(capper_decapper=capper_decapper, robot_arm=robot_arm)
                    TaskScheduler.release_hardware(capper_decapper, tgso)

                # Return the chemicals to their original positions (if applicable)
                if return_chemicals_after_addition:
                    for n, k in enumerate(chemicals):
                        if k.container.current_hardware != previous_hardware_chemicals[n+i]:
                            tmp_target_hardware = previous_hardware_chemicals[n+i]
                            assert isinstance(tmp_target_hardware, SampleHolder.SampleHolder)
                            if tmp_target_hardware.available_slots[previous_slot_number_chemicals[i+n]] is None:
                                tmp_target_slot = previous_slot_number_chemicals[i+n]
                            else:
                                tmp_target_slot = tmp_target_hardware.get_next_free_slot()

                            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
                            required_hardware = [robot_arm]
                            TaskScheduler.wait_for_hardware(required_hardware, tgso)

                            if tmp_target_slot is not None and tmp_target_slot != 0:
                                if not k.container.move(target_hardware=tmp_target_hardware, robot_arm=robot_arm, target_slot_number=tmp_target_slot, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while moving container {k.container} to {tmp_target_hardware}.')
                            else:
                                logger.warning(f'Could not return Chemical {k} to its original position: {tmp_target_hardware}.')

                # Release the addition hardware
                if is_internal_tgso:
                    # Release the container locks
                    for k in chemicals:
                        if k.container._container_availability_lock.locked():
                            k.container._container_availability_lock.release()
                    # Release the addition hardware only if it is an internal tgso (otherwise it might still be needed for another step)
                    TaskScheduler.release_hardware(addition_hardware, tgso)
                    if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                        TaskScheduler.release_hardware(addition_hardware.syringe_pump, tgso)

                # Log the addition step (only for containers with a defined container_type - which typically excludes logging additions to waste containers etc. as SYNTHESIS-STEPS)
                if self.container_type is not None:
                    if isinstance(addition_hardware, OpentronsOT2.OT2):
                        ot2_addition_parameters = addition_hardware.last_used_addition_parameters
                        for n, k in enumerate(ot2_addition_parameters):
                            tmp_log_string = f'Add Chemical [{self.name}]: {self.container_type.container_name}; {k[0]}; {k[2]}; {k[1][1:].replace("_gen2", "").replace("_", " uL ").replace("single", "Single").replace("multi", "Multi")} Channel Pipette'
                            logger.synthesis_step(tmp_log_string)
                    else:
                        for n, k in enumerate(chemicals):
                            tmp_log_string = f'Add Chemical [{self.name}]: {self.container_type.container_name}; {k}'
                            if addition_rates[n] is not None:
                                if isinstance(addition_rate, str):
                                    tmp_log_string += f'; {addition_rate}'
                                else:
                                    tmp_log_string += f'; {addition_rate[0]}'
                            if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                                if addition_rates[n] is None:
                                    tmp_log_string += f'; {addition_hardware.syringe_pump.default_addition_rate}'
                                tmp_log_string += f'; {addition_hardware.syringe_pump.current_syringe_parameters.volume} mL Syringe'
                            elif isinstance(addition_hardware, WPI.Aladdin):
                                if addition_rates[n] is None:
                                    tmp_log_string += f'; {addition_hardware.default_addition_rate}'
                                tmp_log_string += f'; {addition_hardware.current_syringe_parameters.volume} mL Syringe'
                            logger.synthesis_step(tmp_log_string)

                # Continue with the next set of Chemicals
                i += len(chemicals)

            if (return_container_after_addition or (is_internal_tgso and not isinstance(self.current_hardware, SampleHolderHardware))) and self.current_hardware != previous_hardware_container and isinstance(previous_hardware_container, SampleHolderHardware):
                if original_container_was_capped:
                    if capper_decapper is None:
                        for hw in Configuration.OtherHardware.values():
                            if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                                capper_decapper = hw
                                break
                        else:
                            raise CustomError(f'At least one container is capped, but no capper/decapper for opening the container was specified.')
                        required_hardware = [robot_arm, capper_decapper]
                        TaskScheduler.wait_for_hardware(required_hardware, tgso)
                    self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso)
                    TaskScheduler.release_hardware(capper_decapper, tgso)
                if previous_hardware_container.available_slots[previous_slot_number_container] is None or previous_hardware_container.available_slots[previous_slot_number_container] == self.name:
                    tmp_target_slot = previous_slot_number_container
                else:
                    tmp_target_slot = previous_hardware_container.get_next_free_slot()
                if tmp_target_slot is not None and tmp_target_slot != 0:
                    TaskScheduler.wait_for_hardware(robot_arm, tgso)
                    if not self.move(target_hardware=previous_hardware_container, robot_arm=robot_arm, target_slot_number=tmp_target_slot, task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while returning container {self} to its original position: {previous_hardware_container}.')
                    TaskScheduler.release_hardware(robot_arm, tgso)
                else:
                    logger.warning(f'Could not return Container {self} to its original position: {previous_hardware_container}.')

            # Release the robot arm
            TaskScheduler.release_hardware(robot_arm, tgso)

            return True
        except CustomError as e:
            if is_internal_tgso:  # release locks
                for c in chemical:
                    if c.container._container_availability_lock.locked():
                        c.container._container_availability_lock.release()
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:  # release all hardware and locks
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def move(self, target_hardware: Hardware, robot_arm: Optional[RobotArmHardware] = None, target_deck_position: int = 0, target_slot_number: int = 0, vacate_previous_slot: bool = True, capper_decapper: Optional[Hardware] = None, bottom_clearance: float = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for moving the container to a different hardware.

        Parameters
        ----------
        target_hardware : Hardware
            The hardware to which the container should be moved.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        target_deck_position : int, default = 0
            Optional deck position of the holder (or the valve position when hardware is a syringe pump) to which the container should be moved. If the target_hardware is a SampleHolder, the deck position of the holder will be used. Default is 0.
        target_slot_number : int, default = 0
            Optional number of the slot of the holder (for holders with several slots). If the holder has several slots and the value is 0, the next free slot will be used. Default is 0
        capper_decapper: Hardware = None
            The capper/decapper hardware to be used for opening/closing the cap on the container. If set to None, the container is closed, and the target hardware requires an open container, an error will occur. Default is None.
        vacate_previous_slot: bool = True
            Optional value indicating whether the container that is being moved should give up its previous spot and make it available to other containers (default) or keep it reserved (in case it needs to return tp this slot later)
        bottom_clearance : float, default = None
            Optional parameter indicating the height in mm above the bottom of the vessel for the tip of the Probe Sonicator, stirbar retriever, or needle from a syringe pump or valve. Default is None, resulting in 30mm for UP200ST, 5/15/25mm for the stirbar retriever and flasks/50mL Falcon Tubes/15mL Falcon Tubes, and 5mm for the 6-way valve.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if the container was successfully moved, False otherwise

        Raises
        ------
        AssertionError
            If an invalid value is entered for any of the fields.
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        try:
            if self.current_hardware == target_hardware and (not isinstance(self.current_hardware, SampleHolderHardware) or (isinstance(self.current_hardware, SampleHolderHardware) and (self.slot_number is None or self.slot_number == target_slot_number))):
                return True

            assert isinstance(target_hardware, Hardware), 'invalid hardware'
            assert isinstance(target_deck_position, int) and target_deck_position >= 0, 'target_deck_position must be an integer >= 0'
            assert isinstance(target_slot_number, int) and target_slot_number >= 0, 'target_slot_number must be an integer >= 0'

            source_hotplate_clamp = None
            target_hotplate_clamp = None
            requires_uncapping = False
            requires_capping = False

            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to {target_hardware}.'
                robot_arm = list(Configuration.RobotArms.values())[0]

            if self.is_capped and (isinstance(target_hardware, AdditionHardware) or isinstance(target_hardware, Hielscher.UP200ST) or isinstance(target_hardware, Electromagnet.Electromagnet)):
                requires_uncapping = True
                if capper_decapper is None:
                    for h in Configuration.OtherHardware.values():
                        if h.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                            capper_decapper = h
                            break
                    else:
                        raise CustomError(f'The source container is capped, but no capper/decapper for opening the container was specified.')

            if not self.is_capped and isinstance(target_hardware, CentrifugeHardware):
                requires_capping = True
                if capper_decapper is None:
                    for h in Configuration.OtherHardware.values():
                        if h.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                            capper_decapper = h
                            break
                    else:
                        raise CustomError(f'The source container is uncapped, but no capper/decapper for closing the container was specified.')

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware: List[Hardware] = []
            if not isinstance(target_hardware.parent_hardware, SampleHolderHardware):
                required_hardware.append(target_hardware.parent_hardware)
            if isinstance(self.current_hardware, CentrifugeHardware):
                required_hardware.append(self.current_hardware.parent_hardware)
            if requires_capping or requires_uncapping:
                required_hardware.append(capper_decapper.parent_hardware)
            required_hardware.append(robot_arm)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if isinstance(self.current_hardware, CentrifugeHardware):
                if isinstance(self.current_hardware, Herolab.RobotCen):
                    if not self.current_hardware.open_lid():
                        raise CustomError('Error opening lid of Centrifuge')
                else:
                    raise NotImplementedError

            if isinstance(target_hardware, SampleHolderHardware):
                target_deck_position = target_hardware.deck_position
                if target_slot_number == 0:
                    for i, s in enumerate(target_hardware.available_slots.values()):
                        if s == self.name:
                            target_slot_number = i + 1
                            break
                    else:
                        next_free_slot = target_hardware.get_next_free_slot()
                        assert next_free_slot is not None, 'No empty slots available in target sample holder.'
                        target_slot_number = int(next_free_slot)
            elif isinstance(target_hardware, CentrifugeHardware):
                if isinstance(target_hardware, Herolab.RobotCen):
                    target_hardware.set_position_absolute(target_slot_number)
                    target_hardware.open_lid()
                else:
                    raise NotImplementedError

            if isinstance(self.current_hardware.parent_hardware, HotplateHardware):
                for h in Configuration.OtherHardware.values():
                    if h.hardware_type == HardwareTypeDefinitions.ClampHardware and h.parent_hardware == self.current_hardware.parent_hardware:
                        source_hotplate_clamp = h
                        if not source_hotplate_clamp.move_up():
                            raise CustomError(f'Error raising stage of hotplate clamp {h}')
                        if not source_hotplate_clamp.open_clamp():
                            raise CustomError(f'Error opening hotplate clamp {h}')
                        break
            if isinstance(target_hardware.parent_hardware, HotplateHardware):
                for h in Configuration.OtherHardware.values():
                    if h.hardware_type == HardwareTypeDefinitions.ClampHardware and h.parent_hardware == target_hardware.parent_hardware:
                        target_hotplate_clamp = h
                        if not target_hotplate_clamp.move_up():
                            raise CustomError(f'Error raising stage of hotplate clamp {h}')
                        if not target_hotplate_clamp.open_clamp():
                            raise CustomError(f'Error opening hotplate clamp {h}')
                        break

            if requires_uncapping:
                if not self.uncap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError('Error while uncapping container')

            if requires_capping:
                if not self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError('Error while uncapping container')

            if not isinstance(robot_arm, UFactory.XArm6):
                raise NotImplementedError('Currently move commands are only implemented for the UFactory xArm')

            if robot_arm.move(container=self, target_hardware=target_hardware, target_deck_position=target_deck_position, target_slot_number=target_slot_number, bottom_clearance=bottom_clearance, task_group_synchronization_object=tgso):
                if isinstance(self.current_hardware, SampleHolderHardware) and vacate_previous_slot:
                    self.current_hardware.available_slots[self.slot_number] = None
                if isinstance(target_hardware, SampleHolderHardware):
                    target_hardware.available_slots[target_slot_number] = self.name
                self._current_hardware = target_hardware
                self._deck_position = target_deck_position
                self._slot_number = target_slot_number

                if source_hotplate_clamp is not None:
                    if not source_hotplate_clamp.close_clamp():
                        raise CustomError(f'Error closing hotplate clamp {source_hotplate_clamp}')
                if target_hotplate_clamp is not None:
                    if not target_hotplate_clamp.close_clamp():
                        raise CustomError(f'Error closing hotplate clamp {target_hotplate_clamp}')

                if is_internal_tgso:
                    TaskScheduler.release_hardware(required_hardware, tgso)

                return True
            else:
                raise CustomError('Error while moving container.')
        except CustomError as e:
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:  # release all hardware and locks
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def centrifuge(self, containers: Union[Container, List[Container], Tuple[Container, ...]], centrifugation_speed: Union[RotationSpeed, str, float], centrifugation_time: Union[Time, str, float], centrifugation_temperature: Optional[Union[Temperature, str, float]] = '25 C', bottom_clearance_withdrawing: Optional[Union[int, float]] = 3, dropoff_location: Optional[Tuple[SampleHolderHardware, Optional[int]]] = None, robot_arm: Optional[RobotArmHardware] = None, centrifuge: Optional[CentrifugeHardware] = None, transfer_hardware: Optional[AdditionHardware] = None, capper_decapper: Optional[Hardware] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for centrifuging the contents of this container

        Parameters
        ----------
        containers: Union[Container, List[Container], Tuple[Container, ...]]
            A container to be used as a counterweight, or a list of all containers that should be centrifuged together (all should be of the same type). If the current container is a flask, at least two empty centrifuge tubes need to be specified here (the volume will be split evently between them). If the container is a centrifuge tube, at least one container of the same type has to be specified as the counterweight. If the volume of the liquid of the counterweight container is zero, the volume in this container will be split in two and half of it filled into the new container
        centrifugation_speed : Union[RotationSpeed, str, float]
            Speed for the centrigugation step. If a float is provided, it is assumed to be in rpm.
        centrifugation_time : Union[Time, str, float]
            Time for the centrigugation step. If a float is provided, it is assumed to be in seconds.
        centrifugation_temperature: Optional[Union[Temperature, str, float]] = 25
            Optional temperature for the centrifugation step.  If a float is provided, it is assumed to be in degrees Celsius. Default is 25 degrees Celsius.
        bottom_clearance_withdrawing: Optional[Union[int, float]] = 3
             Optional bottom clearance for withdrawing in mm for the centrifugation step. Default is 3 to facilitate withdrawal of the entire content of the container.
        dropoff_location: Optional[Tuple[SampleHolderHardware, Optional[int]]] = None
            Optional alternative dropoff location if the container on which the method is called is not a centrifugable container. If provided, needs to be a tuple of the form (SampleHolder, SlotNumber), with the slot number being optional. If set to None, the container will be returned to its original position. Default is None.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the centrifuge. If set to None, the first registered robot arm will be used. Default is None
        centrifuge: Optional[CentrifugeHardware] = None
            The centrifuge to be used for the centrifugation step. If set to None, the first registered centrifuge will be used. Default is None.
        transfer_hardware : Optional[AdditionHardware] = None
            The addition hardware that is used to move the liquid to the specified containers (if necessary). If set to None, the first registered addition hardware will be used. Default is None.
        capper_decapper: Optional[Hardware] = None
            The capper/decapper hardware to be used for opening/closing the cap on the containers. If set to None and the container is closed, the first registered capper/decapper will be used. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if the centrifugation was successful, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        requires_transfer_hardware = False

        if not isinstance(containers, Iterable):
            containers = [containers]

        try:
            if self.container_type == ContainerTypeCollection.FALCON_TUBE_15_ML or self.container_type == ContainerTypeCollection.FALCON_TUBE_50_ML:
                first_container = self
            else:
                first_container = containers[0]

            for container in containers:
                assert first_container.container_type == container.container_type, f'All container types need to be the same as this container type.'

            if (self.container_type == ContainerTypeCollection.FALCON_TUBE_15_ML or self.container_type == ContainerTypeCollection.FALCON_TUBE_50_ML) and len(containers) % 2 != 1 and containers[0].container_type != self.container_type:
                raise CustomError('Please give an odd number of containers of the same type as this container (either a single counterweight or a counterweight plus other containers and their counterweights).')
            elif self.container_type != ContainerTypeCollection.FALCON_TUBE_15_ML and self.container_type != ContainerTypeCollection.FALCON_TUBE_50_ML and len(containers) % 2 != 0:
                raise CustomError('Please give an even number of containers (containers and their counterweights).')

            if centrifuge is None:
                assert len(Configuration.Centrifuges) > 0, f'No centrifuge found.'
                centrifuge = list(Configuration.Centrifuges.values())[0]
            if isinstance(centrifuge, Herolab.RobotCen):
                available_slots = centrifuge.rotor_info.bottle_number
            else:
                raise NotImplementedError('Implement method for retrieving the number of available slots in the rotor.')

            if isinstance(centrifugation_speed, str):
                centrifugation_speed = RotationSpeed.from_string(centrifugation_speed)
            if isinstance(centrifugation_speed, RotationSpeed):
                if centrifugation_speed.unit == 'rpm':
                    centrifugation_speed = centrifugation_speed.value
                else:
                    centrifugation_speed = centrifuge.rcf_to_rpm(centrifugation_speed.value)
            if isinstance(centrifugation_time, str):
                centrifugation_time = Time.from_string(centrifugation_time).in_unit('s')
            elif isinstance(centrifugation_time, Time):
                centrifugation_time = centrifugation_time.in_unit('s')
            if isinstance(centrifugation_temperature, str):
                centrifugation_temperature = Temperature.from_string(centrifugation_temperature).in_unit('C')
            elif isinstance(centrifugation_temperature, Temperature):
                centrifugation_temperature = centrifugation_temperature.in_unit('C')

            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to the centrifuge {centrifuge}.'
                robot_arm = list(Configuration.RobotArms.values())[0]

            if self.container_type != ContainerTypeCollection.FALCON_TUBE_15_ML or self.container_type != ContainerTypeCollection.FALCON_TUBE_50_ML:
                requires_transfer_hardware = True
            elif containers[0].current_volume.value == 0:
                requires_transfer_hardware = True

            if requires_transfer_hardware and transfer_hardware is None:
                assert len(Configuration.AdditionHardware) > 0, f'No transfer hardware found.'
                transfer_hardware = list(Configuration.AdditionHardware.values())[0]

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware: List[Hardware] = []
            if requires_transfer_hardware:
                required_hardware.append(transfer_hardware)
            required_hardware.append(centrifuge)
            required_hardware.append(robot_arm)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if self.container_type != ContainerTypeCollection.FALCON_TUBE_15_ML and self.container_type != ContainerTypeCollection.FALCON_TUBE_50_ML:
                previous_hardware = [(containers[0], containers[0].current_hardware, containers[0].slot_number), (containers[1], containers[1].current_hardware, containers[1].slot_number)]
                # wait until required containers are available
                if is_internal_tgso:
                    containers[0]._container_availability_lock.acquire()
                    containers[1]._container_availability_lock.acquire()
                if not self.transfer_content_to_container(volume=((self._current_volume)-Volume(1, 'mL')), target_containers=containers[0:2], dropoff_locations=[dropoff_location, (centrifuge, 1), (centrifuge, 1 + available_slots // 2)], transfer_hardware=transfer_hardware, robot_arm=robot_arm, capper_decapper=capper_decapper, bottom_clearance_withdrawing=bottom_clearance_withdrawing, task_group_synchronization_object=tgso):
                    raise CustomError('Error while transferring content from source container to target container(s)')
                # release the transfer hardware
                TaskScheduler.release_hardware(transfer_hardware, tgso)
                other_containers = containers[2:]
            else:
                previous_hardware = [(self, self.current_hardware, self.slot_number), (containers[0], containers[0].current_hardware, containers[0].slot_number)]
                if containers[0].current_volume.value == 0:
                    # wait until required containers are available
                    if is_internal_tgso:
                        containers[0]._container_availability_lock.acquire()

                    if not self.transfer_content_to_container(target_containers=containers[0], volume=Volume(self.current_volume.value/2.0, self.current_volume.unit), dropoff_locations=[(centrifuge, 1), (centrifuge, 1 + available_slots // 2)], robot_arm=robot_arm, transfer_hardware=transfer_hardware, capper_decapper=capper_decapper, task_group_synchronization_object=tgso):
                        raise CustomError('Error while transferring content from source container to target container(s)')
                    if is_internal_tgso:  # release the transfer hardware
                        with tgso.sync_condition:
                            tgso.is_final_task[transfer_hardware].set()
                        with TaskScheduler.task_scheduler_global_event:
                            TaskScheduler.task_scheduler_global_event.notify_all()
                else:
                    if not self.move(target_hardware=centrifuge, robot_arm=robot_arm, target_slot_number=1, vacate_previous_slot=False, task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while moving container {self.name} to the centrifuge.')
                    if not containers[0].move(target_hardware=centrifuge, robot_arm=robot_arm, target_slot_number=1+available_slots // 2, vacate_previous_slot=False, task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while moving container {containers[0]} to the centrifuge.')
                other_containers = containers[1:]

            assert len(other_containers) + 2 <= available_slots, f"The number of containers to be centrifuged exceeds the maximum capacity of the rotor of {available_slots}"
            target_slot = 1
            inc = (available_slots // 2) / (len(other_containers) // 2 + 1)
            for i in range(0, len(other_containers), 2):
                target_slot += inc
                # wait until required container is available
                other_container = other_containers[i]
                if is_internal_tgso:
                    other_container._container_availability_lock.acquire()
                previous_hardware.append((other_container, other_container.current_hardware, other_container.slot_number))
                if not other_container.move(target_hardware=centrifuge, robot_arm=robot_arm, target_slot_number=round(target_slot), vacate_previous_slot=False, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while moving container {other_container.name} to the centrifuge.')

                # wait until required counter-weight container is available
                other_container = other_containers[i+1]
                if is_internal_tgso:
                    other_container._container_availability_lock.acquire()
                previous_hardware.append((other_container, other_container.current_hardware, other_container.slot_number))
                if not other_container.move(target_hardware=centrifuge, robot_arm=robot_arm, target_slot_number=round(target_slot) + available_slots // 2, vacate_previous_slot=False, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while moving container {other_container.name} to the centrifuge.')

            # release the robot arm
            TaskScheduler.release_hardware(robot_arm, tgso)

            centrifuge.start_centrifugation(int(centrifugation_time), int(centrifugation_speed), int(centrifugation_temperature), task_group_synchronization_object=tgso)

            TaskScheduler.wait_for_hardware(robot_arm, tgso)
            for h in previous_hardware:
                centrifuge.set_position_absolute(h[0].slot_number)
                h[0].move(target_hardware=h[1], robot_arm=robot_arm, target_slot_number=h[2], task_group_synchronization_object=tgso)

            if is_internal_tgso:
                for c in containers:
                    if c._container_availability_lock.locked():
                        c._container_availability_lock.release()

            TaskScheduler.release_hardware([robot_arm, centrifuge], tgso)

            logger.synthesis_step(f'Centrifuge [{self.name}]: {centrifugation_time} seconds; {centrifugation_speed} rpm; {centrifugation_temperature} degrees Celsius')

            return True
        except CustomError as e:
            if is_internal_tgso:  # release all hardware and locks
                for c in containers:
                    if c._container_availability_lock.locked():
                        c._container_availability_lock.release()
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:  # release all hardware and locks
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def remove_supernatant_and_redisperse(self, waste_container: Container, redispersion_chemical: Chemical, sonicator: SonicatorHardware = None, sonication_time: Union[Time, str, float] = '10 min', sonication_power: float = 50, sonication_amplitude: float = 50, sonication_temperature: Union[Temperature, str, float] = '20 C', container_for_cleaning: Optional[Container] = None, robot_arm: Optional[RobotArmHardware] = None, capper_decapper: Optional[Hardware] = None, purging_volume: Union[Volume, str, float, None] = '30 mL', bottom_clearance_withdrawing: Optional[Union[int, float]] = 5, bottom_clearance_dispensing: Optional[Union[int, float]] = None, bottom_clearance_sonication: Optional[Union[int, float]] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for removing a liquid (supernatant) from this container, adding a new liquid for redispersion, and redispersing the particles by sonication.

        Parameters
        ----------
        waste_container: Container
            The waste container to which the supernatant is moved.
        redispersion_chemical: Chemical
            The chemical that is used for redispersing the particles
        sonicator: SonicatorHardware = None
            The sonicator hardware that is used for redispersing the particles. If set to None, the first registered sonicator is used. Default is None.
        sonication_time : Union[Time, str, float], default = '10 min'
            Amount of time for which the container is sonicated. If a float is supplied, it is assumed to be in seconds. Default is 10 minutes.
        sonication_power: float, default = 50
            The sonication power in percent (between 0 and 100), default is 50. Not supported by all sonicators.
        sonication_amplitude: float, default = 50
            The sonication amplitude in percent (between 0 and 100), default is 50. Not supported by all sonicators.
        sonication_temperature: Union[Temperature, str, float], default = '20 C'
            The temperature during sonication. If a float is supplied, it is assumed to be in degrees Celsius. Default is 20 degrees Celsius. Not supported by all sonicators.
        container_for_cleaning : Optional[Container], default = None
            The container that is used for cleaning the probe of a probe sonicator (value is ignored if sonicator is a bath sonicator). Default is None.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        capper_decapper: Hardware = None
            The capper/decapper hardware to be used for opening/closing the cap on the source and target containers. If set to None and the container is closed, the first registered capper/decapper will be used. Default is None.
        purging_volume: Union[Volume, str, float, None] = '30 mL'
            Volume of air that is used for purging the tube/needle after dispensing the liquid into the new container. If a float is supplied, it will be assumed to be in mL. Default is 30 mL.
        bottom_clearance_withdrawing: Optional[Union[int, float]] = None
            Bottom clearance of the needle from the container bottom in mm. If set to None, the value specified in the XArm6.move() method will be used.
        bottom_clearance_dispensing: Optional[Union[int, float]] = None
            Bottom clearance of the needle from the container bottom in mm. If set to None, flask height - 20 will be used.
        bottom_clearance_sonication : Optional[float], default = None
            The bottom clearance of the probe sonicator tip. If set to None, a defualt of 30 mm will be used. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if successful, False otherwise
        """

        tgso = task_group_synchronization_object

        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        try:
            container_previous_hardware = self.current_hardware
            container_previous_slot_number = self.slot_number
            transfer_hardware_remove_step = waste_container.current_hardware
            assert isinstance(transfer_hardware_remove_step, AdditionHardware)

            if isinstance(transfer_hardware_remove_step, SwitchingValve.SwitchingValve):
                syringe_pump_remove_step = transfer_hardware_remove_step.syringe_pump
            elif isinstance(transfer_hardware_remove_step, WPI.Aladdin):
                syringe_pump_remove_step = transfer_hardware_remove_step
            else:
                raise NotImplementedError

            transfer_hardware_addition_step = redispersion_chemical.container.current_hardware.parent_hardware
            assert isinstance(transfer_hardware_addition_step, AdditionHardware)

            if isinstance(transfer_hardware_addition_step, SwitchingValve.SwitchingValve):
                syringe_pump_addition_step = transfer_hardware_addition_step.syringe_pump
            elif isinstance(transfer_hardware_addition_step, WPI.Aladdin):
                syringe_pump_addition_step = transfer_hardware_addition_step
            else:
                syringe_pump_addition_step = None

            was_capped = self.is_capped

            if sonicator is None:
                for h in Configuration.Sonicators.values():
                    sonicator = h
                    break
                else:
                    raise CustomError(f'No Sonicators found.')

            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to {transfer_hardware_remove_step}.'
                robot_arm = list(Configuration.RobotArms.values())[0]
            if not isinstance(robot_arm, UFactory.XArm6):
                raise NotImplementedError('Currently this command is only implemented for the UFactory xArm')

            if self.is_capped or waste_container.is_capped or (container_for_cleaning is not None and container_for_cleaning.is_capped):
                if capper_decapper is None:
                    for hw in Configuration.OtherHardware.values():
                        if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                            capper_decapper = hw
                            break
                    else:
                        raise CustomError(f'At least one container is capped, but no capper/decapper for opening the container was specified.')

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()
                waste_container._container_availability_lock.acquire()
                if container_for_cleaning is not None:
                    container_for_cleaning._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware: List[Hardware] = [transfer_hardware_remove_step]
            if syringe_pump_remove_step != transfer_hardware_remove_step:
                required_hardware.append(syringe_pump_remove_step)
            if transfer_hardware_addition_step != transfer_hardware_remove_step:
                required_hardware.append(transfer_hardware_addition_step)
                if syringe_pump_addition_step != transfer_hardware_addition_step and syringe_pump_addition_step is not None:
                    required_hardware.append(syringe_pump_addition_step)
            if self.is_capped:
                required_hardware.append(capper_decapper)
            required_hardware.append(sonicator)
            required_hardware.append(robot_arm)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if not self.transfer_content_to_container(target_containers=waste_container, transfer_hardware=transfer_hardware_remove_step, dropoff_locations=((transfer_hardware_remove_step, 0), (waste_container.current_hardware, waste_container.slot_number)), volume=None, robot_arm=robot_arm, capper_decapper=capper_decapper, purging_volume=purging_volume, bottom_clearance_withdrawing=bottom_clearance_withdrawing, bottom_clearance_dispensing=bottom_clearance_dispensing, recap_container=False, task_group_synchronization_object=tgso):
                raise CustomError('Error while removing supernatant')
            waste_container._container_availability_lock.release()

            # Release transfer hardware (if it is different from the addition hardware)
            if transfer_hardware_remove_step != transfer_hardware_addition_step:
                TaskScheduler.release_hardware([transfer_hardware_remove_step, syringe_pump_remove_step], tgso)

            if not self.add_chemical(redispersion_chemical, robot_arm=robot_arm, return_container_after_addition=False, bottom_clearance=bottom_clearance_dispensing, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while adding chemical {redispersion_chemical} for redispersing')

            # Release addition hardware
            TaskScheduler.release_hardware([transfer_hardware_addition_step, syringe_pump_addition_step], tgso)

            if isinstance(sonicator, Bandelin.SonorexDigitecHRC) and was_capped:
                if not self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while recapping container.')

            if not self.sonicate(sonicator=sonicator, sonication_time=sonication_time, sonication_power=sonication_power, sonication_amplitude=sonication_amplitude, sonication_temperature=sonication_temperature, bottom_clearance=bottom_clearance_sonication, container_for_cleaning=None, robot_arm=robot_arm, capper_decapper=capper_decapper, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while redispersing sample with sonicator {sonicator}.')

            if isinstance(sonicator, Hielscher.UP200ST) and was_capped:
                if not self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while recapping container.')

            if not self.move(target_hardware=container_previous_hardware, target_slot_number=container_previous_slot_number, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while moving container back to its original position.')

            if isinstance(sonicator, Hielscher.UP200ST) and container_for_cleaning is not None:  # Do this manually after (potentially) recapping the container (in case the cleaning container is also capped)
                if not container_for_cleaning.sonicate(sonicator=sonicator, sonication_time='10 s', robot_arm=robot_arm, capper_decapper=capper_decapper, bottom_clearance=15, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while performing cleaning step for probe sonicator {sonicator}.')

            if is_internal_tgso and container_for_cleaning is not None and container_for_cleaning._container_availability_lock.locked():
                container_for_cleaning._container_availability_lock.release()

            TaskScheduler.release_hardware([sonicator, robot_arm], tgso)

            logger.synthesis_step(f'Remove supernatant and redisperse [{self.name}]: {redispersion_chemical}')

            return True

        except CustomError as e:
            if is_internal_tgso:  # release locks on hardware that is still potentially locked because an exception might be thrown before the unlock (do not move this statement to 'finally' block, as it may cauase a race condition with one thread releasing it while another thread holds it, alternatively use an RLock which can only be released by the thread currently holding it)
                if waste_container._container_availability_lock.locked():
                    waste_container._container_availability_lock.release()
                if container_for_cleaning is not None and container_for_cleaning._container_availability_lock.locked():
                    container_for_cleaning._container_availability_lock.release()
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:  # release all hardware and locks
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def transfer_content_to_container(self, target_containers: Union[Container, List[Container], Tuple[Container, ...]], transfer_hardware: AdditionHardware, volume: Union[Volume, str, float, None] = None, dropoff_locations: Union[Tuple[Hardware, Optional[int]], List[Tuple[Hardware, Optional[int]]], Tuple[Tuple[Hardware, Optional[int]], ...], None] = None, robot_arm: Optional[RobotArmHardware] = None, capper_decapper: Optional[Hardware] = None, purging_volume: Union[Volume, str, float, None] = '30 mL', purging_port: Union[int, None] = None, bottom_clearance_withdrawing: Optional[Union[int, float]] = None, bottom_clearance_dispensing: Optional[Union[int, float]] = None, recap_container: bool = True, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for removing a liquid from this container and putting it into other container(s).

        Parameters
        ----------
        target_containers: Union[Container, List[Container], Tuple[Container, ...]]
            The container (or list of containers) to which the liquid should be moved. If a list is provided, the volume will be split equally.
        transfer_hardware: AdditionHardware
            The hardware that is used to move the liquid to the target container(s). Should be either a valve or a syringe pump.
        volume : Union[Volume, str, float, None] = None
            The volume of liquid to be removed from this container. If a float is supplied, it will be assumed to be in mL. If set to None, the entire Volume of the container will be used. Default is None.
        dropoff_locations : Union[Tuple[Hardware, Optional[int]], List[Tuple[Hardware, Optional[int]]], Tuple[Tuple[Hardware, Optional[int]], ...], None] = None
            An optional list of dropoff locations in the form (Hardware, SlotNumber) for the container itself and the target containers. If provided, the length and order must match the containers involved in the transfer. If set to None, all containers will be returned to their original locations. if no task group synchronization object is provided, only sample holders or centrifuges are valid dropoff locations. Default is None.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        capper_decapper: Hardware = None
            The capper/decapper hardware to be used for opening/closing the cap on the source and target containers. If set to None and the container is closed, the first registered capper/decapper will be used. Default is None.
        purging_volume: Union[Volume, str, float, None] = '30 mL'
            Volume of air that is used for purging the tube/needle after dispensing the liquid into the new container. If a float is supplied, it will be assumed to be in mL. Default is 30 mL.
        purging_port: Union[int, None] = None:
            Port on a valve that is used to draw in air for purging. Only has an effect if the addition hardware is a valve and a purging volume is not None. Default is None, which means the outlet_port of the syringe pump will be used.
        bottom_clearance_withdrawing: Optional[Union[int, float]] = None
            Bottom clearance of the needle from the container bottom in mm. If set to None, the value specified in the XArm6.move() method will be used.
        bottom_clearance_dispensing: Optional[Union[int, float]] = None
            Bottom clearance of the needle from the container bottom in mm. If set to None, flask height - 20 will be used.
        recap_container:bool = True
            Whether to recap the source container (if it was capped). If no task_group_synchronization_object is provided or any of the target containers is capped, the container will always be recapped (otherwise this could result in the capper/decapper holding a cap indefinitely, respectively the capper/decapper not being able to open a required container because it still holds a cap). Default is True.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        if not (isinstance(target_containers, list) or isinstance(target_containers, tuple)):
            target_containers = [target_containers]
        assert isinstance(target_containers, list) or isinstance(target_containers, tuple)

        try:
            requires_capper_decapper = False
            if isinstance(transfer_hardware, SwitchingValve.SwitchingValve):
                syringe_pump = transfer_hardware.syringe_pump
            elif isinstance(transfer_hardware, WPI.Aladdin):
                syringe_pump = transfer_hardware
            else:
                raise NotImplementedError

            if dropoff_locations is not None:
                if isinstance(dropoff_locations, tuple) and not any([isinstance(i, list) or isinstance(i, tuple) for i in dropoff_locations]):
                    dropoff_locations = cast(Tuple[Hardware, Optional[int]], dropoff_locations)
                    dropoff_locations = [dropoff_locations]
                dropoff_locations = cast(Union[List[Tuple[Hardware, Optional[int]]], Tuple[Tuple[Hardware, Optional[int]], ...]], dropoff_locations)
                if isinstance(dropoff_locations, tuple):
                    dropoff_locations = cast(Tuple[Tuple[Hardware, Optional[int]], ...], dropoff_locations)
                    dropoff_locations = list(dropoff_locations)
                for i, dropoff_location in enumerate(dropoff_locations):
                    if dropoff_location is None:
                        dropoff_locations[i] = (None, None)
                if len(dropoff_locations) != len(target_containers) + 1:
                    raise CustomError(f'If provided, the list of dropoff locations must match the number of containers involved in the operation.')
                for h in dropoff_locations:
                    assert isinstance(h, list) or isinstance(h, tuple)
                    if is_internal_tgso and h[0] is not None and (not (isinstance(h[0], SampleHolderHardware) or isinstance(h[0], CentrifugeHardware)) or not (isinstance(h[1], int))):
                        raise CustomError(f'Only Sample Holders or Centrifuges are permitted as dropoff locations for containers.')

            if isinstance(volume, str):
                volume = Volume.from_string(volume)
            elif isinstance(volume, SupportsFloat):
                volume = Volume(volume, 'mL')
            elif volume is None:
                volume = Volume(self.current_volume.value, self.current_volume.unit)  # make a new instance (or use copy.deepcopy instead)
            if isinstance(purging_volume, str):
                purging_volume = Volume.from_string(purging_volume).in_unit('mL')
            elif isinstance(purging_volume, SupportsFloat):
                purging_volume = Volume(purging_volume, 'mL')

            source_current_hardware = self.current_hardware
            source_current_deck_position = self.deck_position
            source_current_slot = self.slot_number
            source_was_capped = self.is_capped

            if is_internal_tgso:
                recap_container = True

            if transfer_hardware != self.current_hardware:
                requires_robot_arm = True
                if robot_arm is None:
                    assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to transfer hardware {transfer_hardware}.'
                    robot_arm = list(Configuration.RobotArms.values())[0]
                if not isinstance(robot_arm, UFactory.XArm6):
                    raise NotImplementedError('Currently this command is only implemented for the UFactory xArm')
            else:
                requires_robot_arm = False

            if self.is_capped or any([c.is_capped for c in target_containers]):
                if capper_decapper is None:
                    for hw in Configuration.OtherHardware.values():
                        if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                            capper_decapper = hw
                            break
                    else:
                        raise CustomError(f'At least one container is capped, but no capper/decapper for opening the container was specified.')
                requires_capper_decapper = True

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()
                for c in target_containers:
                    c._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware: List[Hardware] = []
            if requires_capper_decapper:
                required_hardware.append(capper_decapper)
            required_hardware.append(transfer_hardware)
            if syringe_pump != transfer_hardware:
                required_hardware.append(syringe_pump)
            if requires_robot_arm:
                required_hardware.append(robot_arm)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if self.is_capped:
                if not self.uncap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while uncapping source container.')

            if self.current_volume.in_unit('mL') - volume.in_unit('mL') < 0:
                logger.warning(f'Attempting to remove more liquid than is currently in the container')

            if isinstance(transfer_hardware, SwitchingValve.SwitchingValve) and self in transfer_hardware.configuration.values():
                current_outlet_port = transfer_hardware.outlet_port
                transfer_hardware.outlet_port = self._slot_number

            if volume.in_unit('mL') > syringe_pump.current_syringe_parameters.volume:
                no_of_steps = math.ceil(volume.in_unit('mL') / len(target_containers) / syringe_pump.current_syringe_parameters.volume)
                transfer_volume_per_step = Volume(value=volume.in_unit('mL') / len(target_containers) / no_of_steps, unit='mL')
                for i, target_container in enumerate(target_containers):
                    for transfer_step in range(0, no_of_steps):
                        if not self.move(target_hardware=transfer_hardware, robot_arm=robot_arm, bottom_clearance=bottom_clearance_withdrawing, task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while moving the source container to the transfer hardware.')

                        if isinstance(transfer_hardware, SwitchingValve.SwitchingValve) and not transfer_hardware.set_position(transfer_hardware.outlet_port):
                            raise CustomError(f'Error while changing valve port to outlet.')

                        if not syringe_pump.withdraw(volume=transfer_volume_per_step, task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while removing content from container.')

                        new_volume = self.current_volume - transfer_volume_per_step
                        if new_volume < 0:
                            self.current_volume.value = 0
                        else:
                            self.current_volume.value = Volume(new_volume, 'mL').in_unit(self.current_volume.unit)

                        if (i == len(target_containers) - 1 and transfer_step == no_of_steps - 1 and source_was_capped and recap_container) or (source_was_capped and any([c.is_capped for c in target_containers])):
                            if not self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while recapping source container.')

                        # Move back to original position or drop off at new location
                        if dropoff_locations is None or dropoff_locations[0][0] is None:
                            if not self.move(target_hardware=source_current_hardware, target_deck_position=source_current_deck_position, target_slot_number=source_current_slot, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while moving source container back to its original position.')
                        else:
                            if not self.move(target_hardware=dropoff_locations[0][0], robot_arm=robot_arm, target_slot_number=dropoff_locations[0][1], task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while moving source container to its dropoff location {dropoff_locations[0]}.')

                        target_current_hardware = target_container.current_hardware
                        target_current_deck_position = target_container.deck_position
                        target_current_slot = target_container.slot_number
                        target_was_capped = target_container.is_capped
                        if bottom_clearance_dispensing is None:
                            if target_container.container_type is None:
                                bottom_clearance_dispensing = 0
                            else:
                                bottom_clearance_dispensing = max(target_container.container_type.container_height - 20, 1)

                        if isinstance(transfer_hardware, SwitchingValve.SwitchingValve) and target_container.current_hardware is transfer_hardware:  # If the target is directly connected to the valve (e.g. waste, DLS Cell, ...), just dispense to that container
                            if not transfer_hardware.set_position(target_container.slot_number):
                                raise CustomError(f'Error while changing valve port to {target_container.slot_number}.')
                            if not syringe_pump.infuse(volume=Volume(transfer_volume_per_step.value / len(target_containers), volume.unit), task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while dispensing liquid into target container.')
                            target_container.current_volume.value = target_container.current_volume.value + transfer_volume_per_step.in_unit(target_container.current_volume.unit)
                            # Purging step (for last step only)
                            if purging_volume is not None and purging_volume > 0 and transfer_step == no_of_steps - 1:
                                if not transfer_hardware._purge(target_container=target_container, purging_addition_rate=None, purging_volume=purging_volume, purging_port=purging_port, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while performing purging step.')
                        else:
                            if target_container.is_capped:
                                if capper_decapper is None:
                                    for hw in Configuration.OtherHardware.values():
                                        if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                                            capper_decapper = hw
                                            break
                                    else:
                                        raise CustomError(f'The target container is capped, but no capper/decapper for opening the container was specified.')
                                if not target_container.uncap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError('Error while uncapping container')
                            if not target_container.move(target_hardware=transfer_hardware, robot_arm=robot_arm, bottom_clearance=bottom_clearance_dispensing, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while moving target container to the transfer hardware.')
                            if not syringe_pump.infuse(volume=transfer_volume_per_step, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while dispensing liquid into target container.')
                            target_container.current_volume.value = target_container.current_volume.value + transfer_volume_per_step.in_unit(target_container.current_volume.unit)
                            # Purging step (for last step only)
                            if purging_volume is not None and purging_volume > 0 and transfer_step == no_of_steps - 1 and isinstance(transfer_hardware, SwitchingValve.SwitchingValve):
                                if not transfer_hardware._purge(target_container=target_container, purging_addition_rate=None, purging_volume=purging_volume, purging_port=purging_port, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while performing purging step.')

                            if target_was_capped and (transfer_step == no_of_steps - 1 or self.is_capped):
                                if not target_container.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while recapping target container.')

                            if dropoff_locations is None or dropoff_locations[i + 1][0] is None:
                                if not target_container.move(target_hardware=target_current_hardware, target_deck_position=target_current_deck_position, target_slot_number=target_current_slot, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while moving target container back to its original location.')
                            else:
                                if not target_container.move(target_hardware=dropoff_locations[i + 1][0], target_slot_number=dropoff_locations[i + 1][1], robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                    raise CustomError(f'Error while moving target container to its dropoff location {dropoff_locations[i + 1][0]}, slot number {dropoff_locations[i + 1][1]}.')
            else:  # Withdraw the entire volume at once and "store" it in the syringe
                if not self.move(target_hardware=transfer_hardware, robot_arm=robot_arm, bottom_clearance=bottom_clearance_withdrawing, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while moving the source container to the transfer hardware.')

                if isinstance(transfer_hardware, SwitchingValve.SwitchingValve) and not transfer_hardware.set_position(transfer_hardware.outlet_port):
                    raise CustomError(f'Error while changing valve port to outlet.')

                if not syringe_pump.withdraw(volume=volume, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while removing content from container.')

                new_volume = self.current_volume - volume
                if new_volume < 0:
                    self.current_volume.value = 0
                else:
                    self.current_volume.value = new_volume

                if source_was_capped and (recap_container or any([c.is_capped for c in target_containers])):
                    if not self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while recapping source container.')

                # Move back to original position or drop off at new location
                if dropoff_locations is None or dropoff_locations[0][0] is None:
                    if not self.move(target_hardware=source_current_hardware, target_deck_position=source_current_deck_position, target_slot_number=source_current_slot, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while moving source container back to its original position.')
                else:
                    if not self.move(target_hardware=dropoff_locations[0][0], robot_arm=robot_arm, target_slot_number=dropoff_locations[0][1], task_group_synchronization_object=tgso):
                        raise CustomError(f'Error while moving source container to its dropoff location {dropoff_locations[0]}.')

                for i, target_container in enumerate(target_containers):
                    target_current_hardware = target_container.current_hardware
                    target_current_deck_position = target_container.deck_position
                    target_current_slot = target_container.slot_number
                    target_was_capped = target_container.is_capped
                    if bottom_clearance_dispensing is None:
                        if target_container.container_type is None:
                            bottom_clearance_dispensing = 0
                        else:
                            bottom_clearance_dispensing = max(target_container.container_type.container_height - 20, 1)

                    if isinstance(transfer_hardware, SwitchingValve.SwitchingValve) and target_container.current_hardware is transfer_hardware:  # If the target is directly connected to the valve (e.g. waste, DLS Cell, ...), just dispense to that container
                        if not transfer_hardware.set_position(target_container.slot_number):
                            raise CustomError(f'Error while changing valve port to {target_container.slot_number}.')
                        if not syringe_pump.infuse(volume=Volume(volume.value / len(target_containers), volume.unit), task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while dispensing liquid into target container.')
                        target_container.current_volume.value = target_container.current_volume.value + Volume(volume.value / len(target_containers), volume.unit).in_unit(target_container.current_volume.unit)
                        # Purging step (for last container only)
                        if purging_volume is not None and purging_volume > 0 and i == len(target_containers) - 1:
                            if not transfer_hardware._purge(target_container=target_container, purging_addition_rate=None, purging_volume=purging_volume, purging_port=purging_port, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while performing purging step.')
                    else:
                        if target_container.is_capped:
                            if capper_decapper is None:
                                for hw in Configuration.OtherHardware.values():
                                    if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                                        capper_decapper = hw
                                        break
                                else:
                                    raise CustomError(f'The target container is capped, but no capper/decapper for opening the container was specified.')
                            if not target_container.uncap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError('Error while uncapping container')
                        if not target_container.move(target_hardware=transfer_hardware, robot_arm=robot_arm, bottom_clearance=bottom_clearance_dispensing, task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while moving target container to the transfer hardware.')
                        if not syringe_pump.infuse(volume=Volume(volume.value / len(target_containers), volume.unit), task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while dispensing liquid into target container.')
                        target_container.current_volume.value = target_container.current_volume.value + Volume(volume.value / len(target_containers), volume.unit).in_unit(target_container.current_volume.unit)
                        # Purging step (for last container only)
                        if purging_volume is not None and purging_volume > 0 and i == len(target_containers) - 1 and isinstance(transfer_hardware, SwitchingValve.SwitchingValve):
                            if not transfer_hardware._purge(target_container=target_container, purging_addition_rate=None, purging_volume=purging_volume, purging_port=purging_port, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while performing purging step.')

                        if target_was_capped:
                            if not target_container.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while recapping target container.')

                        if dropoff_locations is None or dropoff_locations[i+1][0] is None:
                            if not target_container.move(target_hardware=target_current_hardware, target_deck_position=target_current_deck_position, target_slot_number=target_current_slot, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while moving target container back to its original location.')
                        else:
                            if not target_container.move(target_hardware=dropoff_locations[i+1][0], target_slot_number=dropoff_locations[i+1][1], robot_arm=robot_arm, task_group_synchronization_object=tgso):
                                raise CustomError(f'Error while moving target container to its dropoff location {dropoff_locations[i+1][0]}, slot number {dropoff_locations[i+1][1]}.')

            if isinstance(transfer_hardware, SwitchingValve.SwitchingValve) and self in transfer_hardware.configuration.values():
                transfer_hardware.outlet_port = current_outlet_port

            if is_internal_tgso:
                for c in target_containers:
                    if c._container_availability_lock.locked():
                        c._container_availability_lock.release()

                TaskScheduler.release_hardware(required_hardware, tgso)

            return True
        except CustomError as e:
            if is_internal_tgso:
                for c in target_containers:
                    if c._container_availability_lock.locked():
                        c._container_availability_lock.release()
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def heat(self, heating_temperature: Union[Temperature, str, float], stirring_speed: Union[RotationSpeed, str, float], heating_time: Union[Time, str, float], temperature_stabilization_time: Union[Time, str, float, None] = '5 min', maximum_temperature_deviation: Union[Temperature, str, float, None] = '2 C', cooldown_temperature: Union[Temperature, str, float, None] = '40 C', active_cooling: bool = True, temperature_sensor: Optional[str] = 'EXTERNAL', robot_arm: RobotArmHardware = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for heating this container on a hotplate

        Parameters
        ----------
        heating_temperature: Union[Temperature, str, float]
            The temperature to which this container is heated. If a float is supplied, it is assumed to be in degrees Celsius.
        stirring_speed: Union[RotationSpeed, str, float]
            The stirring speed during heating. If a float is supplied, it is assumed to be in rpm.
        heating_time: Union[Time, str, float]
            The amount of time for which the container is heated. If a float is supplied, it is assumed to be in seconds.
        temperature_stabilization_time: Union[Time, str, float, None] = '5 min'
            Time for how long the temperature has to stay within maximum_temperature_deviation degrees from the target temperature to be considered stable. If set to None, the hotplate will not wait to reach a stable target temperature and the heating_time will start immediately. Default is 5 minutes.
        maximum_temperature_deviation: Union[Temperature, str, float, None] = '2 C'
            Maximum deviation from the target temperature that is still considered as "stable" during the stabilization time. Only has an effect when a temperature_stabilization_time is provided. If set to None, the temperature will be considered stable as soon as the target temperature is reached or exceeded. Default is 2 degrees Celsius.
        cooldown_temperature: Union[Temperature, str, float, None] = '40 C'
            After the heating_time elapsed, wait until the temperature falls below this setpoint (in degrees Celsius) for two consecutive readings. If set to None, do not wait for cool down. Default is 40 degrees Celsius.
        active_cooling: bool = True
            If set to true and the hotplate is equipped with a fan, the fan will be switched on to accelerate cooling. Default is True.
        temperature_sensor: Optional[str] = 'EXTERNAL'
            The temperature sensor to use. needs to be either "EXTERNAL" (for thermocouple) or "INTERNAL"/None (for internal hotplate sensor). Not supported for all hardware. Default is EXTERNAL.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the appropriate hardware for heating. Not necessary if the container is already on the hotplate. If set to None, the first registered robot arm will be used. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if the heating finished successful, False otherwise
        """
        return self.infuse_while_heating(addition_hardware=None, chemical=None, addition_rate=None, heating_temperature=heating_temperature, stirring_speed=stirring_speed, heating_time=heating_time, temperature_stabilization_time=temperature_stabilization_time, maximum_temperature_deviation=maximum_temperature_deviation, cooldown_temperature=cooldown_temperature, active_cooling=active_cooling, temperature_sensor=temperature_sensor, robot_arm=robot_arm, task_group_synchronization_object=task_group_synchronization_object)

    def infuse_while_heating(self, heating_temperature: Union[Temperature, str, float], stirring_speed: Union[RotationSpeed, str, float], heating_time: Union[Time, str, float], addition_hardware: Optional[AdditionHardware] = None, chemical: Union[Chemical, List[Chemical], Tuple[Chemical], None] = None, withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, purging_volume: Union[Volume, str, float, None] = Volume(5, 'mL'), purging_addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, purging_port: Union[int, None] = None, priming_volume: Union[Volume, str, float, None] = None, priming_waste_container: Optional[Container] = None, chemical_for_cleaning: Optional[Chemical] = None, temperature_stabilization_time: Union[Time, str, float, None] = '5 min', maximum_temperature_deviation: Union[Temperature, str, float, None] = '2 C', cooldown_temperature: Union[Temperature, str, float, None] = '40 C', active_cooling: bool = True, temperature_sensor: Optional[str] = 'EXTERNAL', robot_arm: RobotArmHardware = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for heating this container on a hotplate

        Parameters
        ----------
        heating_temperature: Union[Temperature, str, float]
            The temperature to which this container is heated. If a float is supplied, it is assumed to be in degrees Celsius.
        stirring_speed: Union[RotationSpeed, str, float]
            The stirring speed during heating. If a float is supplied, it is assumed to be in rpm.
        heating_time: Union[Time, str, float]
            The amount of time for which the container is heated. If a float is supplied, it is assumed to be in seconds.
        addition_hardware: Optional[AdditionHardware] = None
            Hardware that is used for adding the chemical while heating. If set to None, nothing will be added and the container will only be heated. Default is None.
        chemical: Union[Chemical, List[Chemical], Tuple[Chemical], None] = None
            The chemical(s) that are added while heating. If set to None, nothing will be added and the container will only be heated. Default is None.
        withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are withdrawn. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are added. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        purging_volume: Union[Volume, str, float, None] = Volume(5, 'mL')
            Volume of air that is used for purging the tube/needle after dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve. If a float is supplied, it will be assumed to be in mL. Default is 30 mL.
        purging_addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate that is used when purging the tube/needle after dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve and a purging volume is not None. If a float is supplied, it will be assumed to be in milliliters per minute. Default is None, which means the same value as specified for the addition_rate will be used.
        purging_port: Union[int, None] = None:
            Port on a valve that is used to draw in air for purging. Only has an effect if the addition hardware is a valve and a purging volume is not None. Default is None, which means the outlet_port of the syringe pump will be used.
        priming_volume: Union[Volume, str, float, None] = None
            Volume of chemical(s) that is used for priming the tube before dispensing the liquid into the new container. Only has an effect if the addition hardware is a valve. If specified, the parameter priming_waste_container also needs to be specified. If a float is supplied, it will be assumed to be in mL. Default is None.
        priming_waste_container: Optional[Container] = None
            Container for discarding the chemical that is used during priming. Only has an effect if the addition hardware is a valve and a priming volume is specified. Has to be connected to the same valve as the chemical(s) that are used for priming. Default is None.
        chemical_for_cleaning: Optional[Chemical] = None
            Chemical to be used for flushing the valve after each addition. Only has an effect if the addition hardware is a valve. Default is None.
        temperature_stabilization_time: Union[Time, str, float, None] = '5 min'
            Time for how long the temperature has to stay within maximum_temperature_deviation degrees from the target temperature to be considered stable. If set to None, the hotplate will not wait to reach a stable target temperature and the heating_time and addition will start immediately. Default is 5 minutes.
        maximum_temperature_deviation: Union[Temperature, str, float, None] = '2 C'
            Maximum deviation from the target temperature that is still considered as "stable" during the stabilization time. Only has an effect when a temperature_stabilization_time is provided. If set to None, the temperature will be considered stable as soon as the target temperature is reached or exceeded. Default is 2 degrees Celsius.
        cooldown_temperature: Union[Temperature, str, float, None] = '40 C'
            After the heating_time elapsed, wait until the temperature falls below this setpoint (in degrees Celsius) for two consecutive readings. If set to None, do not wait for cool down. Default is 40 degrees Celsius.
        active_cooling: bool = True
            If set to true and the hotplate is equipped with a fan, the fan will be switched on to accelerate cooling. Default is True.
        temperature_sensor: Optional[str] = 'EXTERNAL'
            The temperature sensor to use. needs to be either "EXTERNAL" (for thermocouple) or "INTERNAL"/None (for internal hotplate sensor). Not supported for all hardware. Default is EXTERNAL.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the appropriate hardware for heating. Not necessary if the container is already on the hotplate. If set to None, the first registered robot arm will be used. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if the heating finished successful, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})
        hotplate_fan = None

        try:
            slot_number = 0
            target_hardware: Union[SampleHolderHardware, None] = None
            requires_robot_arm = False

            if addition_hardware is not None and not (isinstance(addition_hardware, SwitchingValve.SwitchingValve) or isinstance(addition_hardware, WPI.Aladdin)):
                raise NotImplementedError

            if not isinstance(self.current_hardware.parent_hardware, HotplateHardware):
                if robot_arm is None:
                    assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self.current_hardware} to {target_hardware}.'
                    robot_arm = list(Configuration.RobotArms.values())[0]
                requires_robot_arm = True

            if isinstance(self.current_hardware, SampleHolderHardware) and isinstance(self.current_hardware.parent_hardware, HotplateHardware):
                assert isinstance(self.current_hardware, SampleHolderHardware)
                target_hardware = self.current_hardware
            else:
                for sh in Configuration.SampleHolder.values():
                    if isinstance(sh.parent_hardware, HotplateHardware) and self.container_type.container_name in sh.hardware_definition['metadata']['tags']:
                        slot_number = sh.get_next_free_slot()
                        if slot_number is not None:
                            sh.available_slots[slot_number] = self.name
                            target_hardware = sh
                            break
                assert slot_number is not None, 'No available slot found on any heating block'
                assert slot_number != 0, 'No suitable heating blocks found on any hotplate for this container'
                assert target_hardware is not None, 'No suitable heating blocks or hotplates defined'

            hotplate = target_hardware.parent_hardware
            assert isinstance(hotplate, HotplateHardware)

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware: List[Hardware] = [hotplate]
            if requires_robot_arm:
                required_hardware.append(robot_arm)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if requires_robot_arm:
                if not self.move(target_hardware=target_hardware, robot_arm=robot_arm, target_deck_position=target_hardware.deck_position, target_slot_number=slot_number, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while moving container to target hardware {target_hardware}')

            # Release robot arm
            if requires_robot_arm:
                TaskScheduler.release_hardware(robot_arm, tgso)

            if isinstance(stirring_speed, RotationSpeed):
                stir_rate = stirring_speed.in_unit('rpm')
            elif isinstance(stirring_speed, str):
                stir_rate = RotationSpeed.from_string(stirring_speed).in_unit('rpm')
            else:
                stir_rate = stirring_speed
            if isinstance(heating_temperature, Temperature):
                temp = heating_temperature.in_unit('C')
            elif isinstance(heating_temperature, str):
                temp = Temperature.from_string(heating_temperature).in_unit('C')
            else:
                temp = heating_temperature
            if isinstance(heating_time, Time):
                wait_time = heating_time.in_unit('s')
            elif isinstance(heating_time, str):
                wait_time = Time.from_string(heating_time).in_unit('s')
            else:
                wait_time = heating_time
            if isinstance(temperature_stabilization_time, Time):
                stabilization_time = temperature_stabilization_time.in_unit('s')
            elif isinstance(temperature_stabilization_time, str):
                stabilization_time = Time.from_string(temperature_stabilization_time).in_unit('s')
            else:
                stabilization_time = temperature_stabilization_time
            if isinstance(maximum_temperature_deviation, Temperature):
                delta_temp = maximum_temperature_deviation.in_unit('C')
            elif isinstance(maximum_temperature_deviation, str):
                delta_temp = Temperature.from_string(maximum_temperature_deviation).in_unit('C')
            else:
                delta_temp = maximum_temperature_deviation
            if isinstance(cooldown_temperature, Temperature):
                cool_temp = cooldown_temperature.in_unit('C')
            elif isinstance(cooldown_temperature, str):
                cool_temp = Temperature.from_string(cooldown_temperature).in_unit('C')
            else:
                cool_temp = cooldown_temperature
            if purging_addition_rate is None:
                purging_addition_rate = addition_rate

            # if there is a hotplate clamp/stage associated with this hotplate, lower it
            for h in Configuration.OtherHardware.values():
                if h.hardware_type == HardwareTypeDefinitions.ClampHardware and h.parent_hardware == hotplate:
                    hotplate_clamp = h
                    if not hotplate_clamp.move_down():
                        raise CustomError(f'Error while lowering stage of hotplate clamp {h}.')
                    break

            assert isinstance(hotplate, IkaHotplate.RCTDigital5), 'Currently only implemented for Ika Hotplates'

            # Clear any events for the hotplate that might still be set before the asynchronous call to its heat method (where they get cleared as well, but asynchronously)
            hotplate.stable_temperature_reached.clear()
            hotplate.heating_completed_event.clear()

            heating_result = hotplate.heat(heating_temperature=temp, heating_time=wait_time, stirring_speed=stir_rate, temperature_stabilization_time=stabilization_time, maximum_temperature_deviation=delta_temp, cooldown_temperature=cool_temp, temperature_sensor=temperature_sensor, is_sequential_task=False, task_group_synchronization_object=tgso, block=False)
            hotplate.stable_temperature_reached.wait()

            logger.synthesis_step(f'Heat and Stir [{self.name}]: {temp} degrees Celsius; {stir_rate} rpm; {wait_time} seconds')

            if addition_hardware is not None:
                required_hardware = [addition_hardware]  # required chemical containers are not locked or released since currently only containers connected to the valve/pump are supported in this method, so locking the valve/pump suffices
                if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                    required_hardware.append(addition_hardware.syringe_pump)
                TaskScheduler.wait_for_hardware(required_hardware, tgso)

                # Temporarily set the current hardware to the addition hardware
                previous_outlet = addition_hardware.outlet_port
                previous_hardware = self._current_hardware
                self._current_hardware = addition_hardware
                if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                    for k, v in addition_hardware.configuration.items():
                        if v == hotplate:
                            addition_hardware.outlet_port = k
                            break
                    else:
                        raise CustomError(f'Hotplate {hotplate} not found in configuration of valve {addition_hardware}.')

                    # Explicitly call add_chemical with robot_arm=None to prevent robot_arm from moving up/down during purging step
                    if not self.add_chemical(chemical=chemical, withdraw_rate=withdraw_rate, addition_rate=addition_rate, robot_arm=None, purging_volume=purging_volume, purging_addition_rate=purging_addition_rate, purging_port=purging_port, priming_volume=priming_volume, priming_waste_container=priming_waste_container, task_group_synchronization_object=tgso):
                        self._current_hardware = previous_hardware
                        addition_hardware.outlet_port = previous_outlet
                        raise CustomError(f'Error while adding chemical.')

                    # Aspirating back in any chemical left in the addition tubes
                    self._current_volume.value = self._current_volume + Volume.from_string(purging_volume)  # adding volume that would be transferred back into waste container
                    if not self.transfer_content_to_container(target_containers=priming_waste_container, volume=purging_volume, robot_arm=None, transfer_hardware=addition_hardware, purging_volume=None, purging_port=purging_port, task_group_synchronization_object=tgso):
                        self._current_hardware = previous_hardware
                        raise CustomError(f'Error while transferring the leftover chemical from tube to waste container.')

                    # Flushing the valve with cleaning chemical
                    if chemical_for_cleaning is not None and isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                        if not priming_waste_container.add_chemical(chemical=chemical_for_cleaning, robot_arm=None, purging_volume=purging_volume, purging_addition_rate=None, purging_port=purging_port, priming_waste_container=priming_waste_container, task_group_synchronization_object=tgso):
                            raise CustomError(f'Error while flushing the valve with cleaning chemical.')

                    self._current_hardware = previous_hardware
                    addition_hardware.outlet_port = previous_outlet

                elif isinstance(addition_hardware, WPI.Aladdin):
                    if not self.add_chemical(chemical=chemical, withdraw_rate=withdraw_rate, addition_rate=addition_rate, robot_arm=None, purging_volume=purging_volume, purging_addition_rate=purging_addition_rate, purging_port=purging_port, priming_volume=priming_volume, priming_waste_container=priming_waste_container, task_group_synchronization_object=tgso):
                        self._current_hardware = previous_hardware
                        raise CustomError(f'Error while adding chemical.')

                # Release the addition hardware
                TaskScheduler.release_hardware(addition_hardware, tgso)
                if isinstance(addition_hardware, SwitchingValve.SwitchingValve):
                    TaskScheduler.release_hardware(addition_hardware.syringe_pump, tgso)

            hotplate.heating_completed_event.wait()

            if active_cooling:
                for h in Configuration.OtherHardware.values():
                    if h.hardware_type == HardwareTypeDefinitions.FanHardware and h.parent_hardware == self.current_hardware.parent_hardware:
                        hotplate_fan = h
                        if not hotplate_fan.turn_on():
                            raise CustomError(f'Error while turning on hotplate fan {hotplate_fan}.')

            if not heating_result.get():
                raise CustomError('Error while heating/stirring solution')

            logger.synthesis_step(f'Cool down [{self.name}]: {cool_temp} degrees Celsius; Active Cooling {active_cooling}')

            if active_cooling:
                if not hotplate_fan.turn_off():
                    raise CustomError(f'Error while turning off hotplate fan {hotplate_fan}.')

            TaskScheduler.release_hardware(hotplate, tgso)

            return True

        except CustomError as e:
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)
            if hotplate_fan is not None:
                hotplate_fan.turn_off()

    def uncap(self, capper_decapper: Hardware, robot_arm: Optional[RobotArmHardware] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for removing the lid from this container. It always needs a subsequent call to cap() to free the hardware again, since only one cap can be held at a time.

        Parameters
        ----------
        capper_decapper: Hardware
            The capper/decapper to be used for removing the lid from the container.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if lid was removed successfully, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        try:
            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to the capper/decapper {capper_decapper}.'
                robot_arm = list(Configuration.RobotArms.values())[0]
            if not isinstance(robot_arm, UFactory.XArm6):
                raise NotImplementedError('Currently move commands are only implemented for the UFactory xArm')

            if not self.is_capped:
                return True

            if not isinstance(capper_decapper, CapperDecapper.CapperDecapper):
                raise NotImplementedError('Currently this command is only implemented for the custom-built capper decapper hardware')

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware = [capper_decapper, robot_arm]
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if self.current_hardware is not capper_decapper:
                if not self.move(target_hardware=capper_decapper, robot_arm=robot_arm, target_deck_position=0, target_slot_number=0, vacate_previous_slot=False, task_group_synchronization_object=tgso):
                    raise CustomError('Error while moving container to capper/decapper')

            if capper_decapper.open_container(robot_arm=robot_arm, task_group_synchronization_object=tgso):
                self._is_capped = False

            if is_internal_tgso:
                TaskScheduler.release_hardware([robot_arm], tgso)  # only release the robot arm from the task group, since the capper still needs to close the cap again. It will be released at the end of the cap() method.

            return not self.is_capped
        except CustomError as e:
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()

    def cap(self, capper_decapper: Hardware, robot_arm: Optional[RobotArmHardware] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for putting the lid back on this container (assumes the capper/decapper is currently holding the right lid).

        Parameters
        ----------
        capper_decapper: Hardware
            The capper/decapper to be used for removing the lid from the container.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if lid was screwed on successfully, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        try:
            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to the capper/decapper {capper_decapper}.'
                robot_arm = list(Configuration.RobotArms.values())[0]
            if not isinstance(robot_arm, UFactory.XArm6):
                raise NotImplementedError('Currently move commands are only implemented for the UFactory xArm')

            if self.is_capped:
                return True

            if not isinstance(capper_decapper, CapperDecapper.CapperDecapper):
                raise NotImplementedError('Currently this command is only implemented for the custom-built capper decapper hardware')

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware = [capper_decapper, robot_arm]
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if self.current_hardware is not capper_decapper:
                if not self.move(target_hardware=capper_decapper, robot_arm=robot_arm, target_deck_position=0, target_slot_number=0, vacate_previous_slot=False, task_group_synchronization_object=tgso):
                    raise CustomError('Error while moving container to capper/decapper')

            if capper_decapper.close_container(robot_arm=robot_arm, task_group_synchronization_object=tgso):
                self._is_capped = True

            if is_internal_tgso:
                TaskScheduler.release_hardware([capper_decapper, robot_arm], tgso)

            return self.is_capped
        except CustomError as e:
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def measure_dls(self, dls_cell: Container, waste_container: Container, sop_path: str, sample_name: str = '', dls_device: Optional[Hardware] = None, dls_volume: Union[Volume, str, float] = '5 mL', dls_infusion_rate: Union[FlowRate, float, str, None] = '55 mL/min', chemical_for_cleaning: Optional[Chemical] = None, purging_volume: Union[Volume, str, float, None] = '30 mL', dead_volume_valve: Union[Volume, str, float] = '19 mL', dead_volume_dls: Union[Volume, str, float] = '3.8 mL', robot_arm: Optional[RobotArmHardware] = None, capper_decapper: Optional[Hardware] = None, bottom_clearance_sampling: Optional[int] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for performiong a DLS/Zeta Potential Measurement of the solution in the container.

        Parameters
        ----------
        dls_cell: Container
            The DLS cell to which the liquid should be moved.
        waste_container: Container
            The container into which excess solution can be flushed.
        sop_path : str
            File path to the SOP that is used for the measurement.
        sample_name : str, default = ''
            Sample name. When not specified, the name <Container_Name>_yyyy-mm-dd_hh-mm-ss is used.
        dls_device: Hardware = None
            The DLS device used for the measurement. If set to None, the first registered DLS will be used. Default is None.
        dls_volume : Union[Volume, str, float] = '5 mL'
            The volume of liquid to be removed from the container. If a float is supplied it is assumed to be in mL. Default is 5 mL.
        dls_infusion_rate : Optional[FlowRate, float, str, None] = '55 mL/min'
            The flowrate for adding liquid into the DLS cell. The rate should not be too high to avoid air bubbles in the DLS cell. Default is '55 mL/min'.
        chemical_for_cleaning : Optional[Chemical] = None
            The Chemical that is used for cleaning/flushing the cell. Default is None.
        purging_volume : Union[Volume, str, float, None] = '30 mL'
            Volume of air that is used for purging the DLS cell with air after Measurement. If a float is supplied it is assumed to be in mL. Default is 30 mL.
        dead_volume_valve : Union[Volume, str, float] = '19 mL'
            The "dead" volume of the tube connected to the valve. This volume of air will be withdrawn on top of the dls_volume for flushing all the liquid into the syringe. If a float is supplied it is assumed to be in mL. Default is 19 mL.
        dead_volume_dls : Union[Volume, str, float] = '3.8 mL'
            The "dead" volume of the tube connected to the dls. This volume will be injected into the cell on top of the dls_volume for flushing all the liquid into the cell. If a float is supplied it is assumed to be in mL. Default is 3.5 mL.
        robot_arm: RobotArmHardware = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        capper_decapper: Hardware = None
            The capper/decapper hardware to be used for opening/closing the cap on the source and target containers. If set to None and the container is closed, the first registered capper/decapper will be used. Default is None.
        bottom_clearance_sampling: Optional[int] = None
            The clearance of the needle from the bottom of the container when drawing the sample for DLS. If set to None, it will sample from the middle between the solvent level and the container bottom. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        try:
            valve = dls_cell.current_hardware
            if not isinstance(valve, SwitchingValve.SwitchingValve):
                raise CustomError('Invalid Addition Hardware or DLS cell.')

            assert isinstance(valve, SwitchingValve.SwitchingValve), 'Invalid Addition Hardware or DLS cell.'
            assert waste_container.current_hardware == valve, 'The waste container needs to be attached to the valve.'

            if dls_device is None:
                for h in Configuration.OtherHardware.values():
                    if h.hardware_type == HardwareTypeDefinitions.CharacterizationInstrumentHardware and isinstance(h, MalvernPanalytical.ZetaSizer):
                        dls_device = h
                        break
                else:
                    raise CustomError(f'No DLS Devices found.')

            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to the capper/decapper {capper_decapper}.'
                robot_arm = list(Configuration.RobotArms.values())[0]

            requires_capper_decapper = False
            if self.is_capped:
                if capper_decapper is None:
                    for hw in Configuration.OtherHardware.values():
                        if hw.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                            capper_decapper = hw
                            break
                    else:
                        raise CustomError(f'The container is capped, but no capper/decapper for opening the container was specified.')
                requires_capper_decapper = True

            syringe_pump = valve.syringe_pump

            if isinstance(dls_volume, str):
                dls_volume = Volume.from_string(dls_volume)
            elif isinstance(dls_volume, SupportsFloat):
                dls_volume = Volume(dls_volume, 'mL')
            if isinstance(dead_volume_valve, str):
                dead_volume_valve = Volume.from_string(dead_volume_valve)
            elif isinstance(dead_volume_valve, SupportsFloat):
                dead_volume_valve = Volume(dead_volume_valve, 'mL')
            if isinstance(dead_volume_dls, str):
                dead_volume_dls = Volume.from_string(dead_volume_dls)
            elif isinstance(dead_volume_dls, SupportsFloat):
                dead_volume_dls = Volume(dead_volume_dls, 'mL')
            if isinstance(purging_volume, str):
                purging_volume = Volume.from_string(purging_volume)
            elif isinstance(purging_volume, SupportsFloat):
                purging_volume = Volume(purging_volume, 'mL')
            assert isinstance(dls_volume, Volume)
            assert isinstance(dead_volume_valve, Volume)
            assert isinstance(dead_volume_dls, Volume)
            assert isinstance(purging_volume, Volume)

            if dls_volume.in_unit('mL') > syringe_pump.current_syringe_parameters.volume or dead_volume_valve.in_unit('mL') > syringe_pump.current_syringe_parameters.volume or (dls_volume.in_unit('mL') + dead_volume_dls.in_unit('mL')) > syringe_pump.current_syringe_parameters.volume or purging_volume.in_unit('mL') > syringe_pump.current_syringe_parameters.volume:
                raise CustomError(f'Error: Volume of Syringe too small.')

            if bottom_clearance_sampling is None:
                bottom_clearance_sampling = max(2, int(self.get_solvent_level_height() / 2))

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()
                dls_cell._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware = [dls_device, valve, syringe_pump, robot_arm]
            if requires_capper_decapper:
                required_hardware.append(capper_decapper)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if not self.transfer_content_to_container(target_containers=dls_cell, transfer_hardware=valve, volume=dls_volume, robot_arm=robot_arm, capper_decapper=capper_decapper, purging_volume=None, bottom_clearance_withdrawing=bottom_clearance_sampling, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while transferring sample to DLS.')

            # Release robot arm (if no longer needed), the capper/decapper, and container
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
            if chemical_for_cleaning is not None and chemical_for_cleaning.container.current_hardware == valve:
                TaskScheduler.release_hardware(robot_arm, tgso)
            if requires_capper_decapper:
                TaskScheduler.release_hardware(capper_decapper, tgso)

            if not valve.set_position(valve.outlet_port):
                raise CustomError(f'Error while setting valve position to outlet port for purging.')
            if not syringe_pump.withdraw(volume=dead_volume_valve, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while withdrawing air for purging.')
            if not valve.set_position(dls_cell.slot_number):
                raise CustomError(f'Error setting valve to DLS Cell Position.')
            if not syringe_pump.infuse(volume=dead_volume_dls + dls_volume, rate=dls_infusion_rate, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while injecting into DLS cell.')
            # wait until required container is available
            if is_internal_tgso:
                waste_container._container_availability_lock.acquire()

            # Empty the leftover solution in the syringe and tube
            if not valve.set_position(waste_container.slot_number):
                raise CustomError(f'Error setting valve to Waste Container Position.')
            if not syringe_pump.infuse(volume=Volume(max(0.0, dead_volume_valve - (dead_volume_dls + dls_volume)), dead_volume_valve.unit), task_group_synchronization_object=tgso):
                raise CustomError(f'Error while emptying tubes.')

            # Purge withdrawing tube and clean syringe
            if not valve._purge(target_container=waste_container, purging_volume=purging_volume, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while purging tube and syringe with air.')
            # Flush syringe with cleaning chemical
            if chemical_for_cleaning is not None:
                # wait until required container is available
                if is_internal_tgso:
                    chemical_for_cleaning.container._container_availability_lock.acquire()

                if not waste_container.add_chemical(chemical_for_cleaning, purging_volume=None, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error flushing syringe.')

                # Release the container (and the robot arm if it was used)
                if is_internal_tgso:
                    if chemical_for_cleaning.container._container_availability_lock.locked():
                        chemical_for_cleaning.container._container_availability_lock.release()
                if robot_arm in required_hardware:
                    TaskScheduler.release_hardware(robot_arm, tgso)

            # Release valve, pump and waste container
            if is_internal_tgso:
                waste_container._container_availability_lock.release()
            TaskScheduler.release_hardware([valve, syringe_pump], tgso)

            if sample_name == '':
                sample_name = f'{self.name}_DLS_{time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())}'

            if isinstance(dls_device, MalvernPanalytical.ZetaSizer):
                if not dls_device.perform_measurement_and_export_data(sop_path=sop_path, sample_name=sample_name):
                    raise CustomError('Error while performing DLS Measurement.')
            else:
                raise NotImplementedError('Currently DLS/Zeta measurements are only implemented for the Malvern Panalytical Zetasizer')

            # Flush cell with cleaning chemical
            if chemical_for_cleaning is not None:
                # wait until required container is available
                if is_internal_tgso:
                    chemical_for_cleaning.container._container_availability_lock.acquire()

                # Wait until required hardware is ready to process the current task group and then block the hardware during this step
                required_hardware = [valve, syringe_pump, robot_arm]
                TaskScheduler.wait_for_hardware(required_hardware, tgso)

                if not dls_cell.add_chemical(chemical_for_cleaning, purging_volume=None, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error flushing DLS cell.')

                # Release robot arm and container
                if is_internal_tgso:
                    if chemical_for_cleaning.container._container_availability_lock.locked():
                        chemical_for_cleaning.container._container_availability_lock.release()
                TaskScheduler.release_hardware(robot_arm, tgso)

            if is_internal_tgso:
                if chemical_for_cleaning is not None:
                    if chemical_for_cleaning.container._container_availability_lock.locked():
                        chemical_for_cleaning.container._container_availability_lock.release()

            # Purge cell with air
            if purging_volume is not None and purging_volume.value > 0:
                # Wait until required hardware is ready to process the current task group and then block the hardware during this step
                required_hardware = [valve, syringe_pump]
                TaskScheduler.wait_for_hardware(required_hardware, tgso)

                if not valve.set_position(valve.outlet_port):
                    raise CustomError(f'Error while changing valve position to outlet.')
                # Aspirate air through outlet port
                if not syringe_pump.withdraw(volume=purging_volume, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while aspirating air through outlet port.')

                if not valve.set_position(dls_cell.slot_number):
                    raise CustomError(f'Error setting valve to DLS Cell Position.')
                # Dispense
                if not syringe_pump.infuse(volume=purging_volume, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while purging with air.')

            if is_internal_tgso:
                if dls_cell._container_availability_lock.locked():
                    dls_cell._container_availability_lock.release()
            TaskScheduler.release_hardware([valve, syringe_pump, dls_device], tgso)

            return True
        except CustomError as e:
            if is_internal_tgso:
                if dls_cell._container_availability_lock.locked():
                    dls_cell._container_availability_lock.release()
                if chemical_for_cleaning is not None:
                    if chemical_for_cleaning.container._container_availability_lock.locked():
                        chemical_for_cleaning.container._container_availability_lock.release()
                if waste_container._container_availability_lock.locked():
                    waste_container._container_availability_lock.release()
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def sonicate(self, sonicator: Optional[SonicatorHardware] = None, sonication_time: Union[Time, str, float] = '10 min', sonication_power: float = 50, sonication_amplitude: float = 50, sonication_temperature: Union[Temperature, str, float] = '20 C',  bottom_clearance: Optional[float] = None, container_for_cleaning: Optional[Container] = None, robot_arm: Optional[RobotArmHardware] = None, capper_decapper: Optional[Hardware] = None, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Method used for sonicating the contents of the container.

        Parameters
        ----------
        sonicator : Optional[SonicatorHardware], default = None
            The Sonicator Hardware that is used. If not specified, the first registered Sonicator will be used. Default is None.
        sonication_time : Union[Time, str, float], default = '10 min'
            Amount of time for which the container is sonicated. If a float is supplied, it is assumed to be in seconds. Default is 10 minutes.
        sonication_power: float, default = 50
            The sonication power in percent (between 0 and 100), default is 50. Not supported by all sonicators.
        sonication_amplitude: float, default = 50
            The sonication amplitude in percent (between 0 and 100), default is 50. Not supported by all sonicators.
        sonication_temperature: Union[Temperature, str, float], default = '20 C'
            The temperature during sonication. If a float is supplied, it is assumed to be in degrees Celsius. Default is 20 degrees Celsius. Not supported by all sonicators.
        bottom_clearance : Optional[float], default = None
            The bottom clearance of the probe sonicator tip. If set to None, a defualt of 30 mm will be used. Default is None.
        container_for_cleaning : Optional[Container], default = None
            The container that is used for cleaning the probe of a probe sonicator (value is ignored if sonicator is a bath sonicator). Default is None.
        robot_arm: RobotArmHardware, default = None
            The robot arm to be used for moving the container to the target hardware. If set to None, the first registered robot arm will be used. Default is None
        capper_decapper: Hardware, default = None
            The capper/decapper hardware to be used for opening/closing the cap on the container. If set to None, the specified sonicator is a probe sonicator, and the container is closed, the first registered capper/decapper will be used. Default is None.
        task_group_synchronization_object: TaskGroupSynchronizationObject, default = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        tgso = task_group_synchronization_object
        is_internal_tgso = False
        if tgso is None:
            is_internal_tgso = True
            tgso = TaskGroupSynchronizationObject(threading.Condition(), {}, threading.Event(), {})

        try:
            if robot_arm is None:
                assert len(Configuration.RobotArms) > 0, f'No robot arm found for moving the container from {self._current_hardware} to the capper/decapper {capper_decapper}.'
                robot_arm = list(Configuration.RobotArms.values())[0]

            if sonicator is None:
                for h in Configuration.Sonicators.values():
                    sonicator = h
                    break
                else:
                    raise CustomError(f'No Sonicators found.')

            if self.is_capped and capper_decapper is None:
                for h in Configuration.OtherHardware.values():
                    if h.hardware_type == HardwareTypeDefinitions.CapperDecapperHardware:
                        capper_decapper = h
                        break
                else:
                    raise CustomError(f'The source container is capped, but no capper/decapper for opening the container was specified.')

            previous_hardware = self.current_hardware
            was_capped = self.is_capped

            if isinstance(sonication_time, str):
                sonication_time = Time.from_string(sonication_time).in_unit('s')
            elif isinstance(sonication_time, Time):
                sonication_time = sonication_time.in_unit('s')
            if isinstance(sonication_temperature, str):
                sonication_temperature = Temperature.from_string(sonication_temperature).in_unit('C')
            elif isinstance(sonication_temperature, Temperature):
                sonication_temperature = sonication_temperature.in_unit('C')

            # wait until required container is available
            if is_internal_tgso:
                self._container_availability_lock.acquire()

            # Wait until required hardware is ready to process the current task group and then block the hardware during this step
            required_hardware = [sonicator, robot_arm]
            if capper_decapper is not None:
                required_hardware.append(capper_decapper)
            TaskScheduler.wait_for_hardware(required_hardware, tgso)

            if not self.move(target_hardware=sonicator, robot_arm=robot_arm, capper_decapper=capper_decapper, bottom_clearance=bottom_clearance, task_group_synchronization_object=tgso):
                raise CustomError(f'Error moving container to sonicator {sonicator}.')

            if not isinstance(sonicator, Hielscher.UP200ST):  # release robot arm
                if is_internal_tgso:
                    TaskScheduler.release_hardware(robot_arm, tgso)

            if not sonicator.start_sonication(sonication_time=sonication_time, sonication_power=sonication_power, sonication_amplitude=sonication_amplitude, sonication_temperature=sonication_temperature, task_group_synchronization_object=tgso):
                raise CustomError(f'Error while performing the sonication step with hardware {sonicator}.')

            if not self.is_capped and was_capped:
                if not self.cap(capper_decapper=capper_decapper, robot_arm=robot_arm, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while recapping container.')

            if capper_decapper is not None:  # release capper/deacpper
                if is_internal_tgso:
                    TaskScheduler.release_hardware(capper_decapper, tgso)

            # if the previous hardware was a sample holder, return the flask there
            if isinstance(previous_hardware, SampleHolderHardware) or isinstance(previous_hardware, Herolab.RobotCen):
                if not self.move(target_hardware=previous_hardware, robot_arm=robot_arm, capper_decapper=capper_decapper, bottom_clearance=bottom_clearance, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error moving container back to its original hardware.')

            # Perform cleaning step
            if isinstance(sonicator, Hielscher.UP200ST) and container_for_cleaning is not None:
                # wait until required container is available
                if is_internal_tgso:
                    container_for_cleaning._container_availability_lock.acquire()

                if not container_for_cleaning.sonicate(sonicator=sonicator, sonication_time='10 s', robot_arm=robot_arm, capper_decapper=capper_decapper, bottom_clearance=15, task_group_synchronization_object=tgso):
                    raise CustomError(f'Error while performing cleaning step for probe sonicator {sonicator}.')

            # release robot arm
            if is_internal_tgso:
                TaskScheduler.release_hardware(robot_arm, tgso)

            if is_internal_tgso:
                if container_for_cleaning is not None:
                    if container_for_cleaning._container_availability_lock.locked():
                        container_for_cleaning._container_availability_lock.release()

            logger.synthesis_step(f'Sonicate [{self.name}]: {sonication_time} s; {sonication_amplitude} % Amplitude; {sonication_power} % Power')

            return True
        except CustomError as e:
            if is_internal_tgso:
                if container_for_cleaning is not None:
                    if container_for_cleaning._container_availability_lock.locked():
                        container_for_cleaning._container_availability_lock.release()
            logger.error(e)
            return False
        finally:
            if is_internal_tgso:
                if self._container_availability_lock.locked():
                    self._container_availability_lock.release()
                TaskScheduler.finish_task_group_and_release_all(tgso)

    def get_solvent_level_height(self) -> float:
        """
        Method used for calculating the height of the solvent level in mm above the bottom of the container.

        Returns
        -------
        float
            The height in mm if successful, or 0 if the height cannot be calculated
        """
        h = 0.0
        if self.current_volume is not None and self.current_volume.in_unit('uL') > 0 and self.container_type is not None:
            r = self.container_type.container_diameter / 2.0
            v = self.current_volume.in_unit('uL')
            if 'falcon_tube' in self.container_type.container_name.lower():
                # Calculate height of liquid in conical tube above bottom, assume conical part starts at 10 % of the max volume
                h = min(v, self.max_volume.in_unit('uL') * 0.1) / ((math.pi * r ** 2) / 3.0) + max(0.0, v - self.max_volume.in_unit('uL') * 0.1 / ((math.pi * r ** 2) / 3.0)) / (math.pi * r ** 2)
            elif 'flask' in self.container_type.container_name.lower():
                # Calculate height of liquid in spherical flask. The expression used is the solution of V = pi * h^2 * (R - h/3) for h with 0 < V < 4*3 pi R^3 and 0 < h < 2R
                h = r * (1 - 2 * math.sin(1 / 3 * math.asin(1 - (3 * v) / (2 * math.pi * r ** 3))))
        return h


class Chemical:
    """
    Class specifying a chemical/reagent that can be used in an addition step. It holds the information about the amount
    of the chemical that should be added and the container it can be taken from.
    Many parameters are optional and/or can be looked up, however, since currently only liquid handling is possible,
    a combination of parameters that allows to calculate the required volume is necessary when not creating stock
    solutions (as indicated by the is_stock_solution parameter).
    This can be one of the following:
    volume OR
    mass, density OR
    molar amount, molecular weight, density OR
    molar amount, concentration OR
    mass, mass concentration OR
    molar amount, mass concentration, molecular weight OR
    mass, molecular weight, concentration

    Parameters
    ----------
    container : Container
        The container the chemical is in
    lookup_missing_values: bool = True
        Whether to look up missing values on wikidata or pubchem, default is True
    name: str = ''
        Name of the chemical, default is ''. If lookup_missing_values is set to True, it will be attempted to look up the name from the CAS number or SMILES string.
    lot_number: str = ''
        Lot number of the chemical, default is ''
    supplier: str = ''
        Supplier of the chemical, default is ''
    cas: str = ''
        CAS number of the chemical, default is ''. If lookup_missing_values is set to True, it will be attempted to look up the CAS number from the SMILES string or name.
    smiles: str = ''
        SMILES of the chemical, default is ''. If lookup_missing_values is set to True, it will be attempted to look up the SMILES string from the CAS number or name.
    density: Union[Density, str, None] = None
        Density of the chemical to be used, default is None. If lookup_missing_values is set to True, it will be attempted to look this value up.
    molar_mass: Union[MolarMass, str, None] = None
        Molar mass of the chemical to be used, default is None. If lookup_missing_values is set to True, it will be attempted to look this value up.
    mass: Union[MolarMass, str, None] = None
        Mass of the chemical to be used, default is None. If lookup_missing_values is set to True, it will be attempted to look this value up.
    molar_amount: Union[MolarAmount, str, None] = None
        Molar amount of the chemical to be used, default is None. If lookup_missing_values is set to True, it will be attempted to look this value up.
    concentration: Union[Concentration, str, None] = None
        Concentration of the chemical to be used, default is None. If lookup_missing_values is set to True, it will be attempted to look this value up.
    mass_concentration: Union[MassConcentration, str, None] = None
        Mass concentration of the chemical to be used, default is 0. If lookup_missing_values is set to True, it will be attempted to look this value up.
    volume: Union[Volume, str, None] = None
        Volume of the chemical to be used, default is None. If lookup_missing_values is set to True, it will be attempted to look this value up.
    is_stock_solution: bool = False
        Indicates that the chemical is a stock solution rather than a reagent, default is False

    Raises
    ------
    AssertionError
        If an invalid value is entered for any of the fields.
    """
    def __init__(self,
                 container: Container,
                 lookup_missing_values: bool = True,
                 name: str = '',
                 lot_number: str = '',
                 supplier: str = '',
                 cas: str = '',
                 smiles: str = '',
                 density: Union[Density, str, None] = None,
                 molar_mass: Union[MolarMass, str, None] = None,
                 mass: Union[Mass, str, None] = None,
                 molar_amount: Union[MolarAmount, str, None] = None,
                 concentration: Union[Concentration, str, None] = None,
                 mass_concentration: Union[MassConcentration, str, None] = None,
                 volume: Union[Volume, str, None] = None,
                 is_stock_solution: bool = False):

        if isinstance(density, str):
            density = Density.from_string(density)
        if isinstance(molar_mass, str):
            molar_mass = MolarMass.from_string(molar_mass)
        if isinstance(mass, str):
            mass = Mass.from_string(mass)
        if isinstance(molar_amount, str):
            molar_amount = MolarAmount.from_string(molar_amount)
        if isinstance(concentration, str):
            concentration = Concentration.from_string(concentration)
        if isinstance(mass_concentration, str):
            mass_concentration = MassConcentration.from_string(mass_concentration)
        if isinstance(volume, str):
            volume = Volume.from_string(volume)

        assert isinstance(container, Container), 'Please specify a valid container for the chemical'
        assert density is None or isinstance(density, Density), 'Please specify a valid density for the chemical'
        assert molar_mass is None or isinstance(molar_mass, MolarMass), 'Please specify a valid molar mass for the chemical'
        assert mass is None or isinstance(mass, Mass), 'Please specify a valid mass for the chemical'
        assert molar_amount is None or isinstance(molar_amount, MolarAmount), 'Please specify a valid molar amount for the chemical'
        assert concentration is None or isinstance(concentration, Concentration), 'Please specify a valid concentration for the chemical'
        assert mass_concentration is None or isinstance(mass_concentration, MassConcentration), 'Please specify a valid mass concentration for the chemical'
        assert volume is None or isinstance(volume, Volume), 'Please specify a valid volume for the chemical'

        self.container = container
        self.lookup_missing_values = lookup_missing_values
        self.name = name
        self.lot_number = lot_number
        self.supplier = supplier
        self.cas = cas
        self.smiles = smiles
        self.density = density
        self.molar_mass = molar_mass
        self.mass = mass
        self.molar_amount = molar_amount
        self.concentration = concentration
        self.mass_concentration = mass_concentration
        self.volume = volume
        self.is_stock_solution = is_stock_solution

        # Look up some properties on wikidata
        if self.lookup_missing_values and (self.cas == '' or self.smiles == '' or self.molar_mass is None or self.density is None or self.molar_mass.value == 0 or self.density.value == 0):
            c: Any = {}
            if self.cas != '':  # If a CAS number is given, use that
                c = Chemical.search_wiki_by_cas(self.cas)
            elif self.smiles != '':  # Otherwise, try the smiles
                c = Chemical.search_wiki_by_smiles(self.smiles)
            elif self.name != '':  # Otherwise, try the name
                c = Chemical.search_wiki_by_name(self.name)
            if c is not None and 'results' in c and len(c['results']['bindings']) > 0:
                c = c['results']['bindings'][0]
                if self.cas == '' and 'cas' in c:
                    self.cas = c['cas']['value']
                if self.smiles == '' and 'smiles' in c:
                    self.smiles = c['smiles']['value']
                if self.name == '' and 'compoundLabel' in c:
                    self.name = c['compoundLabel']['value']
                if 'mass' in c and (self.molar_mass is None or self.molar_mass.value == 0):
                    tmp_unit = None
                    if self.molar_mass is not None:
                        tmp_unit = self.molar_mass.unit
                    if WikidataUnitEnum.DALTON.value in c['mass_unit']['value']:
                        self.molar_mass = MolarMass(value=float(c['mass']['value']), unit='dalton')
                    elif WikidataUnitEnum.KILODALTON.value in c['mass_unit']['value']:
                        self.molar_mass = MolarMass(value=float(c['mass']['value']), unit='kilodalton')
                    if tmp_unit is not None:
                        self.molar_mass.convert_to(tmp_unit)
                if 'density' in c and (self.density is None or self.density.value == 0):
                    is_liquid = True
                    if 'mp' in c and 'mp_unit' in c:
                        if ((c['mp_unit']['value'] == WikidataUnitEnum.CELSIUS.value and float(c['mp']['value']) > 28) or
                           (c['mp_unit']['value'] == WikidataUnitEnum.FAHRENHEIT.value and float(c['mp']['value']) > 80)):
                            is_liquid = False
                    if 'bp' in c and 'bp_unit' in c:
                        if ((c['bp_unit']['value'] == WikidataUnitEnum.CELSIUS.value and float(c['bp']['value']) < 18) or
                           (c['bp_unit']['value'] == WikidataUnitEnum.FAHRENHEIT.value and float(c['bp']['value']) < 62)):
                            is_liquid = False
                    if is_liquid:
                        tmp_unit = None
                        if self.density is not None:
                            tmp_unit = self.density.unit
                        if WikidataUnitEnum.GRAM_PER_CUBIC_CENTIMETER.value in c['density_unit']['value']:
                            self.density = Density(value=float(c['density']['value']), unit='g/ccm')
                        elif WikidataUnitEnum.KILOGRAM_PER_CUBIC_METER.value in c['density_unit']['value']:
                            self.density = Density(value=float(c['density']['value']), unit='kg/m3')
                        if tmp_unit is not None:
                            self.density.convert_to(tmp_unit)

        # If some properties could not be found on wikidata, try looking them up on pubchem (pubchem does not have densities, though)
        if self.lookup_missing_values and (self.cas == '' or self.smiles == '' or self.molar_mass is None or self.molar_mass.value == 0):
            c = None
            if self.cas != '':  # If a CAS number is given, use that
                c = pcp.get_compounds(self.cas, 'name')
            elif self.smiles != '':  # Otherwise, try the smiles
                c = pcp.get_compounds(self.smiles, 'smiles')
            elif self.name != '':  # Otherwise, try the name
                c = pcp.get_compounds(self.name, 'name')
            if c is not None and len(c) > 0:
                c = c[0]
                if self.cas == '':
                    for syn in c.synonyms:
                        match = re.match(r'(\d{2,7}-\d\d-\d)', syn)
                        if match:
                            self.cas = match.group(1)
                            break
                if self.smiles == '':
                    self.smiles = c.canonical_smiles
                if self.name == '':
                    self.name = c.name
                if self.molar_mass is None or self.molar_mass.value == 0:
                    tmp_unit = None
                    if self.molar_mass is not None:
                        tmp_unit = self.molar_mass.unit
                    self.molar_mass = MolarMass(value=float(c.molecular_weight), unit='dalton')
                    if tmp_unit is not None:
                        self.molar_mass.convert_to(tmp_unit)

        if not self.is_stock_solution:
            if self.volume is None:
                self.volume = Volume(value=0, unit='mL')
            tmp_unit = self.volume.unit  # Store current volume unit
            if self.volume.value == 0:
                self.volume.convert_to('m3')  # set temporarily to SI unit to simplify calculations

            if self.volume.value > 0:
                pass
            elif self.mass is not None and self.mass.value != 0 and self.density is not None and self.density.value != 0:  # Calculate volume from mass and density
                self.volume.value = self.mass.in_si() / self.density.in_si()
            elif self.molar_amount is not None and self.molar_amount.value != 0 and self.density is not None and self.density.value != 0 and self.molar_mass is not None and self.molar_mass.value != 0:  # Calculate volume from molar amount and density
                self.volume.value = self.molar_amount.in_si() * self.molar_mass.in_si() / self.density.in_si()
            elif self.concentration is not None and self.concentration.value != 0 and self.molar_amount is not None and self.molar_amount.value != 0:  # Calculate volume from molar amount and concentration
                self.volume.value = self.molar_amount.in_si() / self.concentration.in_si()
            elif self.mass_concentration is not None and self.mass_concentration.value != 0 and self.mass is not None and self.mass.value != 0:  # Calculate volume from mass and mass concentration
                self.volume.value = self.mass.in_si() / self.mass_concentration.in_si()
            elif self.mass_concentration is not None and self.mass_concentration.value != 0 and self.molar_amount is not None and self.molar_amount.value != 0 and self.molar_mass is not None and self.molar_mass.value != 0:  # Calculate volume from molar amount and mass concentration
                self.volume.value = self.molar_mass.in_si() * self.molar_amount.in_si() / self.mass_concentration.in_si()
            elif self.mass is not None and self.mass.value != 0 and self.concentration is not None and self.concentration.value != 0 and self.molar_mass is not None and self.molar_mass.value != 0:  # Calculate volume from mass and concentration
                self.volume.value = (self.mass.in_si() / self.molar_mass.in_si()) / self.concentration.in_si()

            self.volume.convert_to(tmp_unit)
            if self.volume.value <= 0:
                raise ValueError('Please specify at least one of the following for non stock-solutions: volume OR mass, density OR molar amount, molecular weight, density OR molar amount, concentration OR mass, mass concentration OR molar amount, mass concentration, molecular weight OR mass, molecular weight, concentration')

        # Calculate the molar amount (for information only) if the required quantities are known (volume is always known, the other quantities require either the mass or molar amount to be known -> sufficient to check for volume or mass
        if self.molar_amount is None or self.molar_amount.value == 0:
            if self.molar_amount is not None and self.molar_amount.unit is not None:
                tmp_unit = self.molar_amount.unit
            else:
                tmp_unit = 'mol'

            if self.density is not None and self.density.value != 0:
                tmp_val = self.density.in_si() * self.volume.in_si() / self.molar_mass.in_si()
                self.molar_amount = MolarAmount(value=tmp_val, unit='mol').convert_to(tmp_unit)
            elif self.mass is not None and self.mass.value != 0 and self.molar_mass is not None and self.molar_mass.value != 0:
                tmp_val = self.mass.in_si() / self.molar_mass.in_si()
                self.molar_amount = MolarAmount(value=tmp_val, unit='mol').convert_to(tmp_unit)

        Configuration.register_object(self)

    def __str__(self) -> str:
        """Function returning a human-readable string description of the class with some information."""
        if self.name is not None and self.name != '':
            tmp_name = f'Chemical {self.name}'
        else:
            tmp_name = 'Unknown chemical'

        if self.cas is not None and self.cas != '':
            tmp_cas = f' (CAS:{self.cas})'
        else:
            tmp_cas = ''

        if self.volume.value >= 1e-3 and self.volume.value < 1e4:
            tmp_vol = f': {round(self.volume.value, 4)} {self.volume.unit}'
        else:
            tmp_vol = f': {self.volume.value:.3e} {self.volume.unit}'

        if self.molar_amount is not None:
            if self.molar_amount.value >= 1e-3 and self.molar_amount.value < 1e4:
                tmp_mol = f'; {round(self.molar_amount.value, 4)} {self.molar_amount.unit}'
            else:
                tmp_mol = f'; {self.molar_amount.value:.3e} {self.molar_amount.unit}'
        else:
            tmp_mol = ''

        return f'{tmp_name}{tmp_cas}{tmp_vol}{tmp_mol}'

    def dump_configuration(self) -> Dict[str, Any]:
        """Dump all current instance vars in a json-serializable dict."""
        return_dict = {}
        for k, v in vars(self).items():
            if _is_json_serializable(v):
                return_dict[k] = v
            elif isinstance(v, Quantity):
                return_dict[k] = str(v)
            else:
                return_dict[k] = f'{type(v)}-{id(v)}'
        return return_dict

    @classmethod
    def from_stock_chemical(
            cls,
            stock_chemical: Chemical,
            mass: Union[Mass, None] = None,
            molar_amount: Union[MolarAmount, None] = None,
            volume: Union[Volume, None] = None) -> Chemical:
        """
        Alternative constructor of the class based on an already existing (stock) chemical. The general properties of the stock chemical are copied to the new instance. Useful for creating reagents to be used in addition steps from stock solutions.

        Parameters
        ----------
        stock_chemical: Chemical
            The chemical on which this instance is based
        mass: Union[Mass, None] = None
            Mass of the chemical to be used, default is None
        molar_amount: Union[MolarAmount, None] = None
            Molar amount of the chemical to be used, default is None
        volume: Union[Volume, None] = None
            Volume of the chemical to be used, default is 0

        Returns
        -------
        Chemical
            A new instance of the class with general properties copied from the chemical it was derived from
        """

        return cls(container=stock_chemical.container,
                   lookup_missing_values=stock_chemical.lookup_missing_values,
                   name=stock_chemical.name,
                   lot_number=stock_chemical.lot_number,
                   supplier=stock_chemical.supplier,
                   cas=stock_chemical.cas,
                   smiles=stock_chemical.smiles,
                   density=stock_chemical.density,
                   molar_mass=stock_chemical.molar_mass,
                   concentration=stock_chemical.concentration,
                   mass_concentration=stock_chemical.mass_concentration,
                   mass=mass,
                   molar_amount=molar_amount,
                   volume=volume,
                   is_stock_solution=False
                   )

    @staticmethod
    def search_wiki_by_cas(cas: str) -> Union[None, Any]:
        """
        Searches wikidata based on a CAS number using sparql

        Parameters
        ----------
        cas: str
            The cas number of the chemical to be looked up

        Returns
        -------
        dict
            A json dict with information about cas, smiles, name, and density of the chemical if found on wikidata, None otherwise
        """
        url = 'https://query.wikidata.org/sparql'
        query = f'''
        SELECT DISTINCT ?compound ?compoundLabel ?compoundAltLabel ?cas ?smiles ?density ?density_unit ?mass ?mass_unit ?mp ?mp_unit ?bp ?bp_unit
        WHERE {{
            BIND ("{cas}" AS ?cas).
            ?compound wdt:P31 wd:Q113145171.
            ?compound wdt:P231 ?cas.
            OPTIONAL {{
                ?compound wdt:P231 ?cas;
            }}
            OPTIONAL {{
                ?compound wdt:P233 ?smiles;
            }}
            OPTIONAL {{
                ?compound p:P2067 [
                    ps:P2067 ?mass ;
                    psv:P2067/wikibase:quantityUnit ?mass_unit
                ];
            }}
            OPTIONAL {{
                ?compound p:P2054 [
                    ps:P2054 ?density ;
                    psv:P2054/wikibase:quantityUnit ?density_unit ;
                ] .
            }}
            OPTIONAL {{
                ?compound p:P2101 [
                    ps:P2101 ?mp ;
                    psv:P2101/wikibase:quantityUnit ?mp_unit ;
                ] .
            }}
            OPTIONAL {{
                ?compound p:P2102 [
                    ps:P2102 ?bp ;
                    psv:P2102/wikibase:quantityUnit ?bp_unit ;
                ] .
            }}
            SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
        LIMIT 10
        '''
        r = requests.get(url, params={'format': 'json', 'query': query})
        if r.ok:
            return r.json()
        else:
            return None

    @staticmethod
    def search_wiki_by_smiles(smiles: str) -> Union[None, Any]:
        """
        Searches wikidata based on a SMILES string using sparql

        Parameters
        ----------
        smiles: str
            The canonical SMILES string of the chemical to be looked up

        Returns
        -------
        dict
            A json dict with information about cas, smiles, name, and density of the chemical if found on wikidata, None otherwise
        """
        url = 'https://query.wikidata.org/sparql'
        query = f'''
        SELECT DISTINCT ?compound ?compoundLabel ?compoundAltLabel ?cas ?smiles ?density ?density_unit ?mass ?mass_unit ?mp ?mp_unit ?bp ?bp_unit
        WHERE {{
            BIND ("{smiles}" AS ?smiles).
            ?compound wdt:P31 wd:Q113145171.
            ?compound wdt:P233 ?smiles.
            OPTIONAL {{
                ?compound wdt:P231 ?cas;
            }}
            OPTIONAL {{
                ?compound wdt:P233 ?smiles;
            }}
            OPTIONAL {{
                ?compound p:P2067 [
                    ps:P2067 ?mass ;
                    psv:P2067/wikibase:quantityUnit ?mass_unit
                ];
            }}
            OPTIONAL {{
                ?compound p:P2054 [
                    ps:P2054 ?density ;
                    psv:P2054/wikibase:quantityUnit ?density_unit ;
                ] .
            }}
            OPTIONAL {{
                ?compound p:P2101 [
                    ps:P2101 ?mp ;
                    psv:P2101/wikibase:quantityUnit ?mp_unit ;
                ] .
            }}
            OPTIONAL {{
                ?compound p:P2102 [
                    ps:P2102 ?bp ;
                    psv:P2102/wikibase:quantityUnit ?bp_unit ;
                ] .
            }}
            SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
        LIMIT 10
        '''
        r = requests.get(url, params={'format': 'json', 'query': query})
        if r.ok:
            return r.json()
        else:
            return None

    @staticmethod
    def search_wiki_by_name(name: str) -> Union[None, Any]:
        """
        Searches wikidata based on a chemical name using sparql

        Parameters
        ----------
        name: str
            The name of the chemical to be looked up

        Returns
        -------
        dict
            A json dict with information about cas, smiles, name, and density of the chemical if found on wikidata, None otherwise
        """
        url = 'https://query.wikidata.org/sparql'
        query = f'''
        SELECT DISTINCT ?compound ?compoundLabel ?compoundAltLabel ?cas ?smiles ?density ?density_unit ?mass ?mass_unit ?mp ?mp_unit ?bp ?bp_unit
        WHERE {{
            {{
                SELECT DISTINCT ?compound
                WHERE {{
                    SERVICE wikibase:mwapi {{
                        bd:serviceParam wikibase:api "Search";
                                        wikibase:endpoint "www.wikidata.org";
                                        mwapi:srsearch "{name} haswbstatement:P31=Q113145171". #;
                        ?compound wikibase:apiOutputItem mwapi:title .
                    }}
                }}
            }}
            BIND ("{name.lower()}" AS ?lbl).
            ?compound skos:altLabel ?altLabel.
            FILTER(STR(LCASE(?altLabel)) = ?lbl).
            OPTIONAL {{
                ?compound wdt:P231 ?cas;
            }}
            OPTIONAL {{
                ?compound wdt:P233 ?smiles;
            }}
            OPTIONAL {{
                ?compound p:P2067 [
                    ps:P2067 ?mass ;
                    psv:P2067/wikibase:quantityUnit ?mass_unit
                ];
            }}
            OPTIONAL {{
                ?compound p:P2054 [
                    ps:P2054 ?density ;
                    psv:P2054/wikibase:quantityUnit ?density_unit ;
                ] .
            }}
            OPTIONAL {{
                ?compound p:P2101 [
                    ps:P2101 ?mp ;
                    psv:P2101/wikibase:quantityUnit ?mp_unit ;
                ] .
            }}
            OPTIONAL {{
                ?compound p:P2102 [
                    ps:P2102 ?bp ;
                    psv:P2102/wikibase:quantityUnit ?bp_unit ;
                ] .
            }}
            SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
        LIMIT 10
        '''
        r = requests.get(url, params={'format': 'json', 'query': query})
        if r.ok:
            return r.json()
        else:
            return None
