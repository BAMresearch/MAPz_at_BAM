#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import datetime
import socket

import requests
import logging
import time
from typing import Union, Tuple, List, Iterable, Dict, TYPE_CHECKING, Any, Optional, SupportsFloat
import math
import os

from Minerva.API.HelperClassDefinitions import AdditionHardware, SampleHolderHardware, Volume, FlowRate, _is_json_serializable, TaskScheduler, TaskGroupSynchronizationObject, PathNames

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


class OT2(AdditionHardware):
    """
    Class for running protocols on the Opentrons OT-2 robot via HTTP requests.

    Parameters
    ----------
    ip_address : str
        The IP Address of the robot.
    """

    EMERGENCY_STOP_REQUEST = False

    X_LIMIT = 392.76  
    Y_LIMIT = 356.98  
    SEPARATOR_WIDTH = 4.55
    SEPARATOR_HEIGHT = 4.55
    DECK_SLOT_WIDTH = 127.95
    DECK_SLOT_HEIGHT = 85.95

    DECK_SLOTS_TOP_LEFT = {
        1: (X_LIMIT / 2 - SEPARATOR_WIDTH - 1.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 - 1.5 * SEPARATOR_HEIGHT - DECK_SLOT_HEIGHT, 2),
        2: (X_LIMIT / 2 - 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 - 1.5 * SEPARATOR_HEIGHT - DECK_SLOT_HEIGHT, 2),
        3: (X_LIMIT / 2 + SEPARATOR_WIDTH + 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 - 1.5 * SEPARATOR_HEIGHT - DECK_SLOT_HEIGHT, 2),
        4: (X_LIMIT / 2 - SEPARATOR_WIDTH - 1.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 - 0.5 * SEPARATOR_HEIGHT, 2),
        5: (X_LIMIT / 2 - 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 - 0.5 * SEPARATOR_HEIGHT, 2),
        6: (X_LIMIT / 2 + SEPARATOR_WIDTH + 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 - 0.5 * SEPARATOR_HEIGHT, 2),
        7: (X_LIMIT / 2 - SEPARATOR_WIDTH - 1.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 + 0.5 * SEPARATOR_HEIGHT + DECK_SLOT_HEIGHT, 2),
        8: (X_LIMIT / 2 - 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 + 0.5 * SEPARATOR_HEIGHT + DECK_SLOT_HEIGHT, 2),
        9: (X_LIMIT / 2 + SEPARATOR_WIDTH + 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 + 0.5 * SEPARATOR_HEIGHT + DECK_SLOT_HEIGHT, 2),
        10: (X_LIMIT / 2 - SEPARATOR_WIDTH - 1.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 + 1.5 * SEPARATOR_HEIGHT + 2 * DECK_SLOT_HEIGHT, 2),
        11: (X_LIMIT / 2 - 0.5 * DECK_SLOT_WIDTH, Y_LIMIT / 2 + 1.5 * SEPARATOR_HEIGHT + 2 * DECK_SLOT_HEIGHT, 2),
    }

    def __init__(self, ip_address: str):
        """
        Constructor for the OT2 Class for running protocols on the Opentrons OT-2 robot via HTTP POST requests.

        Parameters
        ----------
        ip_address : str
            The IP Address of the robot.
        """
        super().__init__()
        self._logger_dict = {'instance_name': str(self)}
        self.ip_address = ip_address
        try:
            ip_address_resolved: Union[str, Tuple[str, List[str], List[str]]]
            if '.local' in ip_address:
                ip_address_resolved = socket.gethostbyname(ip_address)
            else:
                ip_address_resolved = socket.gethostbyaddr(ip_address)[-1][0]
        except socket.herror:
            logger.critical(f'OT2 not responding on {ip_address}.', extra=self._logger_dict)
            raise TimeoutError(f'OT2 not responding on {ip_address}.')

        self.ip_address_resolved = ip_address_resolved
        self.session_id = None
        self.protocol_id = None

        self.configuration: Dict[int, Union[str, SampleHolderHardware, None]] = {}
        self.left_pipette: Union[str, None] = None
        self.left_pipette_volume = -1
        self.tip_racks_for_left_pipette: List[Tuple[str, Union[str, SampleHolderHardware]]] = []
        self.current_tip_index_for_left_pipette = -1
        self.current_tip_rack_for_left_pipette: Tuple[str, Union[str, SampleHolderHardware]] = ('', '')
        self.right_pipette: Union[str, None] = None
        self.right_pipette_volume = -1
        self.tip_racks_for_right_pipette: List[Tuple[str, Union[str, SampleHolderHardware]]] = []
        self.current_tip_index_for_right_pipette = -1
        self.current_tip_rack_for_right_pipette: Tuple[str, Union[str, SampleHolderHardware]] = ('', '')
        self.custom_labware_definition: List[str] = []
        self._last_used_addition_parameters: List[Tuple[Chemical, str, FlowRate]] = []

        self.MIN_PIPETTE_VOLUME_USE = 0.2  # Try to use at least 20% of the total volume of the pipette to avoid large pipetting errors
        self.HEIGHT_ABOVE_SOLVENT_LEVEL_WHEN_DISPENSING = 60  # The height above the solvent level when dispensing liquid in millimeters (offsets to keep it above 0 and below container height are applied automatically)
        self.HEIGHT_BELOW_SOLVENT_LEVEL_WHEN_ASPIRATING = 30  # The height below the solvent level when aspirating liquid in millimeters (offsets to keep it above 0 and below container height are applied automatically)
        self.HEIGHT_BELOW_CONTAINER_TOP_WHEN_DISPENSING_FLASKS = 32  # The minimum height below the top of the container when dispensing liquid into flasks in millimeters (this value is automatically applied for )
        self.HEIGHT_BELOW_CONTAINER_TOP_WHEN_DISPENSING_FALCON_TUBES = 15  # The minimum height below the top of the container when dispensing liquid into Falcon tubes in millimeters (this value is automatically applied for )


    @property
    def last_used_addition_parameters(self) -> list[tuple(Chemical, str, FlowRate)]:
        """Returns the addition parameters that were last used (a list of tuples of Chemical, Pipette and FlowRate)"""
        return self._last_used_addition_parameters

    def set_hardware_configuration(self, configuration: Dict[int, Union[SampleHolderHardware, str, None]], reset_tip_racks_and_tippositions: bool = True) -> bool:
        """
        Specifies the current hardware configuration of the OT2.

        Parameters
        ----------
        configuration : Dict[int, Union[SampleHolderHardware, str, None]]
            A dict with the hardware configuration of the OT2 in the form {int: Union[SampleHolderHardware, str, None]}. 1-11 correspond to deck positions 1-11 on the OT2, 12 corresponds to left pipette, 13 to right pipette.
        reset_tip_racks_and_tippositions : bool = True
            If set to true it will be assumed that all tip racks are newly filled, and the first tip of the first matching tip rack will be used.

        Returns
        -------
        bool
            True if the hardware configuration was set successfully.
        """
        if OT2.EMERGENCY_STOP_REQUEST:
            return False

        if self.configuration is None:
            self.configuration = configuration
        else:
            self.configuration.update(configuration)

        all_tipracks = []

        for key, val in self.configuration.items():
            if key > 0 and val is not None and ((isinstance(val, str) and 'tiprack' in val) or (isinstance(val, SampleHolderHardware) and 'tiprack' in val.hardware_definition['metadata']['tags'][0])):
                all_tipracks.append((f'labware_{key}', val))

        for i in self.tip_racks_for_left_pipette:
            if i not in all_tipracks:
                self.tip_racks_for_left_pipette.remove(i)
                if self.current_tip_rack_for_left_pipette == i:
                    self.current_tip_rack_for_left_pipette = ('', '')
                    self.current_tip_index_for_left_pipette = -1
        for i in self.tip_racks_for_right_pipette:
            if i not in all_tipracks:
                self.tip_racks_for_right_pipette.remove(i)
                if self.current_tip_rack_for_right_pipette == i:
                    self.current_tip_rack_for_right_pipette = ('', '')
                    self.current_tip_index_for_right_pipette = -1

        if isinstance(self.configuration[12], str):
            self.left_pipette = self.configuration[12]
            self.left_pipette_volume = int(self.left_pipette[1:self.left_pipette.find('_')])
            for i in all_tipracks:
                if (isinstance(i[1], str) and f'{self.left_pipette_volume}ul' in i[1]) or (isinstance(i[1], SampleHolderHardware) and f'{self.left_pipette_volume}ul' in i[1].hardware_definition['metadata']['tags'][0]):
                    self.tip_racks_for_left_pipette.append(i)
        if isinstance(self.configuration[13], str):
            self.right_pipette = self.configuration[13]
            self.right_pipette_volume = int(self.right_pipette[1:self.right_pipette.find('_')])
            for i in all_tipracks:
                if (isinstance(i[1], str) and f'{self.right_pipette_volume}ul' in i[1]) or (isinstance(i[1], SampleHolderHardware) and f'{self.right_pipette_volume}ul' in i[1].hardware_definition['metadata']['tags'][0]):
                    self.tip_racks_for_right_pipette.append(i)

        if (isinstance(self.left_pipette, str) and 'single' not in self.left_pipette) or (isinstance(self.right_pipette, str) and 'single' not in self.right_pipette):
            raise NotImplementedError

        if reset_tip_racks_and_tippositions:
            self.current_tip_rack_for_left_pipette = ('', '')
            self.current_tip_index_for_left_pipette = -1
            self.current_tip_rack_for_right_pipette = ('', '')
            self.current_tip_index_for_right_pipette = -1

        if self.current_tip_rack_for_left_pipette == ('', '') and len(self.tip_racks_for_left_pipette) > 0:
            self.current_tip_rack_for_left_pipette = self.tip_racks_for_left_pipette.pop()
        if self.current_tip_rack_for_right_pipette == ('', '') and len(self.tip_racks_for_right_pipette) > 0:
            self.current_tip_rack_for_right_pipette = self.tip_racks_for_right_pipette.pop()

        return True

    def reset_tipracks_and_tippositions(self) -> bool:
        """
        Resets the values for the current tip racks and next tip positions (can be called after manually refilling everything without changes to the configuration).

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        return self.set_hardware_configuration(configuration=self.configuration, reset_tip_racks_and_tippositions=True)

    def _get_next_pipette_tip_location(self, pipette: str) -> Union[Tuple[Tuple[str, Union[str, SampleHolderHardware]], int], None]:
        """
        Keeps track of the pipette tips and returns the position of the next tip for the specified pipette.

        Parameters
        ----------
        pipette : str
            The string identifying the pipette.

        Returns
        -------
        Union[Tuple[Tuple[str, Union[str, SampleHolderHardware]], int], None]
            The tip rack and index of the next available tip or None if no more tips are available.
        """
        # Currently implemented for single channel pipettes only

        if pipette == self.left_pipette:
            if self.current_tip_index_for_left_pipette < 95:
                self.current_tip_index_for_left_pipette += 1
            elif self.current_tip_index_for_left_pipette == 95 and len(self.tip_racks_for_left_pipette) > 0:
                self.current_tip_rack_for_left_pipette = self.tip_racks_for_left_pipette.pop()
                self.current_tip_index_for_left_pipette = 0
            elif self.current_tip_index_for_left_pipette > 95 and len(self.tip_racks_for_left_pipette) == 0:
                return None
            return self.current_tip_rack_for_left_pipette, self.current_tip_index_for_left_pipette
        elif pipette == self.right_pipette:
            if self.current_tip_index_for_right_pipette < 95:
                self.current_tip_index_for_right_pipette += 1
            elif self.current_tip_index_for_right_pipette == 95 and len(self.tip_racks_for_right_pipette) > 0:
                self.current_tip_rack_for_right_pipette = self.tip_racks_for_right_pipette.pop()
                self.current_tip_index_for_right_pipette = 0
            elif self.current_tip_index_for_right_pipette > 95 and len(self.tip_racks_for_right_pipette) == 0:
                return None
            return self.current_tip_rack_for_right_pipette, self.current_tip_index_for_right_pipette
        else:
            return None

    @TaskScheduler.scheduled_task
    def add(self, chemical: Union[Chemical, List[Chemical], Tuple[Chemical, ...]], target_container: Container, withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, air_gap: Union[float, None] = 0.01, blow_out: bool = True, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Adds the specified chemical(s) to the specified container.

        Parameters
        ----------
        chemical : Union[Chemical, List[Chemical], Tuple[Chemical, ...]]
            A list of the chemical(s) to be added.
        target_container : Container
            The container to which the chemical(s) should be added.
        withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are withdrawn. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are added. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        air_gap: Union[float, None] = 0.01
            Use an air gap after aspirating liquid to prevent it from seeping out of the tip while moving. The value is given as a fraction of the max volume of the pipette. If set to None or a value <= 0, no air gap is used. Default is 0.02 (i.e., 2 %)
        blow_out: bool = True
            Whether to perform a blow out step after dispensing. Default is True.
        block: bool = TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_blocking_behavior
        priority: int = TaskScheduler.default_priority
            Priority of this task (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_priority
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if the addition was successful.

        Raises
        ------
        RuntimeError
            If an error occurs when uploading the protocol to the robot.
        AssertionError
            If the hardware configuration is not specified
        """
        if OT2.EMERGENCY_STOP_REQUEST:
            return False

        assert self.configuration is not None, 'Hardware configuration not found. Please use the set_hardware_configuration method to define the current hardware configuration of the OT2.'

        labware = ""
        protocol = ""
        filecontent = ""
        self._last_used_addition_parameters = []

        for key, val in self.configuration.items():
            if 0 < key < 12 and val is not None:
                if isinstance(val, str) and 'opentrons' in val:
                    labware += f"\tlabware_{key} = protocol.load_labware('{val}', {key})\n"
                elif isinstance(val, str) and 'opentrons' not in val:
                    labware += f"\tlabware_{key} = protocol.load_labware_from_definition(json.load(open('{val}.json', 'rb')), {key})\n"  # .set_calibration(Point(-2.0, 2.6, 0.6))\n"
                    self.custom_labware_definition.append(os.path.join(PathNames.ROOT_DIR.value, 'OT2_Custom_Labware', f'{val}.json'))
                elif isinstance(val, SampleHolderHardware) and val.hardware_definition['brand']['brand'].lower().startswith('opentrons'):
                    labware += f"\tlabware_{key} = protocol.load_labware('{val.hardware_definition['metadata']['tags'][0]}', {key})\n"
         
        if self.left_pipette is not None:
            labware += f"\tleft_pipette = protocol.load_instrument(instrument_name='{self.left_pipette}', mount='left')\n"
        if self.right_pipette is not None:
            labware += f"\tright_pipette = protocol.load_instrument(instrument_name='{self.right_pipette}', mount='right')\n"

        assert self.left_pipette is not None or self.right_pipette is not None, 'At least one pipette required for addition step.'
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

        # Decide which pipette to use for which chemical
        for i, c in enumerate(chemical):
            assert c.volume is not None, 'Invalid Volume'
            vol = c.volume.in_unit('uL')
            source_container = c.container
            pipette = ''
            if self.left_pipette is not None and self.right_pipette is None:  # Use left pipette
                pipette = self.left_pipette
            elif self.right_pipette is not None and self.left_pipette is None:  # Use right pipette
                pipette = self.right_pipette
            elif vol > self.left_pipette_volume and vol > self.right_pipette_volume and (self.left_pipette_volume > 0 or self.right_pipette_volume > 0):  # Use the larger of the two
                if self.left_pipette_volume > self.right_pipette_volume:
                    pipette = self.left_pipette
                else:
                    pipette = self.right_pipette
            elif vol <= self.left_pipette_volume and vol <= self.right_pipette_volume:  # Use the smaller of the two
                if self.left_pipette_volume < self.right_pipette_volume and self.left_pipette_volume > 0:
                    pipette = self.left_pipette
                    if vol < self.MIN_PIPETTE_VOLUME_USE * self.left_pipette_volume:
                        logger.warning(f'Warning: Addition Volume below {self.MIN_PIPETTE_VOLUME_USE * 100} % of the pipette volume. Addition might not be accurate.', extra=self._logger_dict)
                else:
                    pipette = self.right_pipette
                    if vol < self.MIN_PIPETTE_VOLUME_USE * self.right_pipette_volume:
                        logger.warning(f'Warning: Addition Volume below {self.MIN_PIPETTE_VOLUME_USE * 100} % of the pipette volume. Addition might not be accurate.', extra=self._logger_dict)
            elif vol > self.right_pipette_volume and self.right_pipette_volume > 0 and vol < self.MIN_PIPETTE_VOLUME_USE * self.left_pipette_volume:  # Prefer right pipette despite multiple dispense steps
                pipette = self.right_pipette
            elif vol > self.left_pipette_volume and self.left_pipette_volume > 0 and vol < self.MIN_PIPETTE_VOLUME_USE * self.right_pipette_volume:  # Prefer left pipette despite multiple dispense steps
                pipette = self.left_pipette
            elif vol > self.right_pipette_volume and self.right_pipette_volume > 0 and vol >= self.MIN_PIPETTE_VOLUME_USE * self.left_pipette_volume:  # Prefer left pipette with only one dispense step
                pipette = self.left_pipette
            elif vol > self.left_pipette_volume and self.left_pipette_volume > 0 and vol >= self.MIN_PIPETTE_VOLUME_USE * self.left_pipette_volume:  # Prefer right pipette with only one dispense step
                pipette = self.right_pipette

            protocol += self.__write_code_addition_step(pipette=pipette, volume=vol, source_container=source_container, target_container=target_container, addition_rate=addition_rate[i], withdraw_rate=withdraw_rate[i], air_gap=air_gap, blow_out=blow_out)
            if addition_rate[i] is None:
                addition_rate[i] = FlowRate(self._get_default_addition_rate(pipette=pipette, api_is_v26=True), 'uL/s')

            self._last_used_addition_parameters.append((c, pipette, addition_rate[i]))

        if len(self.custom_labware_definition) > 0:
            filecontent = "import json\n"

        filecontent += f"from opentrons import protocol_api\nfrom opentrons.types import Location, Point\n\nmetadata = {{'apiLevel': '2.6'}}\n\n\ndef run(protocol: protocol_api.ProtocolContext):\n\t# Labware\n{labware}\n\t# Protocol\n{protocol}\n"

        if not os.path.exists(PathNames.OT2_TEMP_DIR.value):
            os.makedirs(PathNames.OT2_TEMP_DIR.value)

        tmp_file_name = os.path.join(PathNames.OT2_TEMP_DIR.value, f'tmp_{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")}')
        with open(tmp_file_name, 'w') as f:
            f.write(filecontent)

        logger.info(f'Automatically created protocol file for addition steps: {tmp_file_name}', extra=self._logger_dict)
        logger.info(f'The following chemicals will be added when executing this protocol:', extra=self._logger_dict)
        for i, c in enumerate(chemical):
            logger.info(f'Adding {str(c)} at a rate of {addition_rate[i]} ({c.container.name} -> {target_container.name})', extra=self._logger_dict)

        return self.run(tmp_file_name)

    def __write_code_addition_step(self, pipette: str, volume: float, source_container: Container, target_container: Container, withdraw_rate: Union[FlowRate, float, str, None] = None, addition_rate: Union[FlowRate, float, str, None] = None, air_gap: Union[float, None] = 0.01, blow_out: bool = True) -> str:
        """
        Writes python code for the OT2 for a simple addition step

        Parameters
        ----------
        pipette : str
            A string identifying which pipette to use for the addition step
        volume : float
            The volume to be added in microliters
        source_container : Container
            The container from which the chemical is aspirated.
        target_container : Container
            The container to which the chemical is added.
        withdraw_rate: Union[FlowRate, float, str, None] = None
            Rate at which the chemical is withdrawn. If a float is provided, it is assumed to be in microliters per second. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, None] = None
            Rate at which the chemical is added. If a float is provided, it is assumed to be in microliters per second. If set to None, the default rate is used. Default is None.
        air_gap: Union[float, None] = 0.01
            Use an air gap after aspirating liquid to prevent it from seeping out of the tip while moving. The value is given as a fraction of the max volume of the pipette. If set to None or a value <= 0, no air gap is used. Default is 0.01 (i.e., 1 %)
        blow_out: bool = True
            Whether to perform a blow out step after dispensing. Default is True.

        Returns
        -------
        str
            A step containing the python code for the addition step
        """
        protocol = ''

        source = self.configuration[source_container.deck_position]
        target = self.configuration[target_container.deck_position]

        if isinstance(addition_rate, str):
            addition_rate = FlowRate.from_string(addition_rate)
        elif isinstance(addition_rate, SupportsFloat):  # Use SupportsFloat in case the user provided an integer
            addition_rate = FlowRate(addition_rate, 'uL/s')
        if isinstance(withdraw_rate, str):
            withdraw_rate = FlowRate.from_string(withdraw_rate)
        elif isinstance(withdraw_rate, SupportsFloat):  # Use SupportsFloat in case the user provided an integer
            withdraw_rate = FlowRate(withdraw_rate, 'uL/s')

        if air_gap is not None and air_gap > 0:
            if pipette.startswith('p1000'):
                vol_air_gap = air_gap * 1000
            elif pipette.startswith('p300'):
                vol_air_gap = air_gap * 300
            else:
                vol_air_gap = air_gap * 20

        if pipette == self.left_pipette:
            self._get_next_pipette_tip_location(self.left_pipette)
            protocol += f"\tleft_pipette.pick_up_tip({self.current_tip_rack_for_left_pipette[0]}.wells()[{self.current_tip_index_for_left_pipette}])\n"
            if withdraw_rate is not None:
                protocol += f"\tleft_pipette.flow_rate.aspirate = {withdraw_rate.in_unit('uL/s')}\n"
            if addition_rate is not None:
                protocol += f"\tleft_pipette.flow_rate.dispense = {addition_rate.in_unit('uL/s')}\n"
            for v in range(0, math.ceil(volume / (self.left_pipette_volume - vol_air_gap))):
                z_offset_aspirate, z_offset_dispense = self.calculate_pipette_z_offset(source_container, target_container)
                if (isinstance(source, str)) or (isinstance(source, SampleHolderHardware) and source.hardware_definition['brand']['brand'].lower().startswith('opentrons')):
                    source_location = f"labware_{source_container.deck_position}.wells()[{source_container.slot_number-1}]"
                    if z_offset_aspirate > 0:
                        source_location += f'.bottom(z={z_offset_aspirate})'
                else:
                    assert isinstance(source_container.current_hardware, SampleHolderHardware)
                    pos = source_container.current_hardware.get_coordinates(slot_number=source_container.slot_number, offset_top_left=None, rotation_angle=0, invert_y=True)
                    x = self.DECK_SLOTS_TOP_LEFT[source_container.deck_position][0] + pos[0]
                    y = self.DECK_SLOTS_TOP_LEFT[source_container.deck_position][1] + pos[1]
                    z = self.DECK_SLOTS_TOP_LEFT[source_container.deck_position][2] + pos[2] + z_offset_aspirate
                    source_location = f"Location(Point({x}, {y}, {z}), None)"
                if (isinstance(target, str)) or (isinstance(target, SampleHolderHardware) and target.hardware_definition['brand']['brand'].lower().startswith('opentrons')):
                    target_location = f"labware_{target_container.deck_position}.wells()[{target_container.slot_number-1}]"
                    if z_offset_dispense > 0:
                        target_location += f'.bottom(z={z_offset_dispense})'
                else:
                    assert isinstance(target_container.current_hardware, SampleHolderHardware)
                    pos = target_container.current_hardware.get_coordinates(slot_number=target_container.slot_number, offset_top_left=None, rotation_angle=0, invert_y=True)
                    x = self.DECK_SLOTS_TOP_LEFT[target_container.deck_position][0] + pos[0]
                    y = self.DECK_SLOTS_TOP_LEFT[target_container.deck_position][1] + pos[1]
                    z = self.DECK_SLOTS_TOP_LEFT[target_container.deck_position][2] + pos[2] + z_offset_dispense
                    target_location = f"Location(Point({x}, {y}, {z}), None)"

                protocol += f"\tleft_pipette.aspirate({volume/math.ceil(volume / (self.left_pipette_volume - vol_air_gap))}, location={source_location})\n"

                if air_gap is not None and air_gap > 0:
                    protocol += f"\tleft_pipette.air_gap(volume={vol_air_gap})\n"

                protocol += f"\tleft_pipette.dispense({volume/math.ceil(volume / (self.left_pipette_volume - vol_air_gap)) + vol_air_gap}, location={target_location})\n"

                if blow_out:
                    protocol += f"\tleft_pipette.blow_out()\n"
                    if (isinstance(target, str)) or (isinstance(target, SampleHolderHardware) and target.hardware_definition['brand']['brand'].lower().startswith('opentrons')):
                        protocol += f"\tcurrent_position = {target_location}.point\n"
                        protocol += f"\tleft_pipette.move_to(location=Location(Point(current_position.x+2, current_position.y, current_position.z), None), force_direct=True)\n"  # Slightly move tip to shake off any residual droplet
                        protocol += f"\tleft_pipette.move_to(location=Location(Point(current_position.x, current_position.y, current_position.z), None), force_direct=True)\n"
                    else:
                        protocol += f"\tleft_pipette.move_to(location=Location(Point({x+2}, {y}, {z}), None), force_direct=True)\n"  # Slightly move tip to shake off any residual droplet
                        protocol += f"\tleft_pipette.move_to(location=Location(Point({x}, {y}, {z}), None), force_direct=True)\n"

                source_container.current_volume = Volume(source_container.current_volume - Volume(volume/math.ceil(volume / (self.left_pipette_volume - vol_air_gap)), 'uL'), source_container.current_volume.unit)
                target_container.current_volume = Volume(target_container.current_volume + Volume(volume/math.ceil(volume / (self.left_pipette_volume - vol_air_gap)), 'uL'), target_container.current_volume.unit)
            protocol += "\tleft_pipette.drop_tip()\n"
        elif pipette == self.right_pipette:
            self._get_next_pipette_tip_location(self.right_pipette)
            protocol += f"\tright_pipette.pick_up_tip({self.current_tip_rack_for_right_pipette[0]}.wells()[{self.current_tip_index_for_right_pipette}])\n"
            if withdraw_rate is not None:
                protocol += f"\tright_pipette.flow_rate.aspirate = {withdraw_rate.in_unit('uL/s')}\n"
            if addition_rate is not None:
                protocol += f"\tright_pipette.flow_rate.dispense = {addition_rate.in_unit('uL/s')}\n"
            for v in range(0, math.ceil(volume / (self.right_pipette_volume - vol_air_gap))):
                z_offset_aspirate, z_offset_dispense = self.calculate_pipette_z_offset(source_container, target_container)
                if (isinstance(source, str)) or (isinstance(source, SampleHolderHardware) and source.hardware_definition['brand']['brand'].lower().startswith('opentrons')):
                    source_location = f"labware_{source_container.deck_position}.wells()[{source_container.slot_number-1}]"
                    if z_offset_aspirate > 0:
                        source_location += f'.bottom(z={z_offset_aspirate})'
                else:
                    assert isinstance(source_container.current_hardware, SampleHolderHardware)
                    pos = source_container.current_hardware.get_coordinates(slot_number=source_container.slot_number, offset_top_left=None, rotation_angle=0, invert_y=True)
                    x = self.DECK_SLOTS_TOP_LEFT[source_container.deck_position][0] + pos[0]
                    y = self.DECK_SLOTS_TOP_LEFT[source_container.deck_position][1] + pos[1]
                    z = self.DECK_SLOTS_TOP_LEFT[source_container.deck_position][2] + pos[2] + z_offset_aspirate
                    source_location = f"Location(Point({x}, {y}, {z}), None)"
                if (isinstance(target, str)) or (isinstance(target, SampleHolderHardware) and target.hardware_definition['brand']['brand'].lower().startswith('opentrons')):
                    target_location = f"labware_{target_container.deck_position}.wells()[{target_container.slot_number-1}]"
                    if z_offset_dispense > 0:
                        target_location += f'.bottom(z={z_offset_dispense})'
                else:
                    assert isinstance(target_container.current_hardware, SampleHolderHardware)
                    pos = target_container.current_hardware.get_coordinates(slot_number=target_container.slot_number, offset_top_left=None, rotation_angle=0, invert_y=True)
                    x = self.DECK_SLOTS_TOP_LEFT[target_container.deck_position][0] + pos[0]
                    y = self.DECK_SLOTS_TOP_LEFT[target_container.deck_position][1] + pos[1]
                    z = self.DECK_SLOTS_TOP_LEFT[target_container.deck_position][2] + pos[2] + z_offset_dispense
                    target_location = f"Location(Point({x}, {y}, {z}), None)"

                protocol += f"\tright_pipette.aspirate({volume/math.ceil(volume / (self.right_pipette_volume - vol_air_gap))}, location={source_location})\n"

                if air_gap is not None and air_gap > 0:
                    protocol += f"\tright_pipette.air_gap(volume={vol_air_gap})\n"

                protocol += f"\tright_pipette.dispense({volume/math.ceil(volume / (self.right_pipette_volume - vol_air_gap)) + vol_air_gap}, location={target_location})\n"

                if blow_out:
                    protocol += f"\tright_pipette.blow_out()\n"
                    if (isinstance(target, str)) or (isinstance(target, SampleHolderHardware) and target.hardware_definition['brand']['brand'].lower().startswith('opentrons')):
                        protocol += f"\tcurrent_position = {target_location}.point\n"
                        protocol += f"\tright_pipette.move_to(location=Location(Point(current_position.x+2, current_position.y, current_position.z), None), force_direct=True)\n"  # Slightly move tip to shake off any residual droplet
                        protocol += f"\tright_pipette.move_to(location=Location(Point(current_position.x, current_position.y, current_position.z), None), force_direct=True)\n"
                    else:
                        protocol += f"\tright_pipette.move_to(location=Location(Point({x+2}, {y}, {z}), None), force_direct=True)\n"  # Slightly move tip to shake off any residual droplet
                        protocol += f"\tright_pipette.move_to(location=Location(Point({x}, {y}, {z}), None), force_direct=True)\n"

                source_container.current_volume = Volume(source_container.current_volume - Volume(volume/math.ceil(volume / (self.right_pipette_volume - vol_air_gap)), 'uL'), source_container.current_volume.unit)
                target_container.current_volume = Volume(target_container.current_volume + Volume(volume/math.ceil(volume / (self.right_pipette_volume - vol_air_gap)), 'uL'), target_container.current_volume.unit)
            protocol += "\tright_pipette.drop_tip()\n"

        return protocol

    @staticmethod
    def _get_default_addition_rate(pipette: str, api_is_v26: bool = True) -> float:
        """
        Returns the OT2 default addition rates for each pipette in uL/s.

        Parameters
        ----------
        pipette : str
            The name of the pipette.
        api_is_v26 : bool = True
            The API version that is used (version 2.6 and above use different values than version 2.5 and below). If set to True, it is assumed that the API version is >=2.6. Default is True.

        Returns
        -------
        float
            The default addition rate of the pipette in µL/s.
        """
        if pipette == 'p1000_single_gen2' and api_is_v26:
            return 274.7
        elif pipette == 'p1000_single_gen2' and not api_is_v26:
            return 137.35
        elif pipette == 'p300_single_gen2' and api_is_v26:
            return 92.86
        elif pipette == 'p300_single_gen2' and not api_is_v26:
            return 46.43
        elif pipette == 'p20_single_gen2' and api_is_v26:
            return 7.56
        elif pipette == 'p20_single_gen2' and not api_is_v26:
            return 3.78
        elif pipette == 'p300_multi_gen2':
            return 94
        elif pipette == 'p20_multi_gen2':
            return 7.6
        else:
            return -1

    
    def calculate_pipette_z_offset(self, source_container: Container, target_container: Container) -> Tuple[float, float]:
        """
        Calculates the height for aspirating and dispensing

        Parameters
        ----------
        source_container : Container
            The container from which the chemical is aspirated.
        target_container : Container
            The container to which the chemical is added.

        Returns
        -------
        Tuple[float, float]
            The heights for aspirating and dispensing. If a container is None, the corresponding height in the tuple will be 0
        """
        # get current heights
        z_offset_aspirate = source_container.get_solvent_level_height()
        z_offset_dispense = target_container.get_solvent_level_height()
        additional_offset = 0

        # calculate actual heights, taking into account that the pipette should be submerged during aspirating, but not during dispensing
        z_offset_aspirate -= self.HEIGHT_BELOW_SOLVENT_LEVEL_WHEN_ASPIRATING
        z_offset_aspirate = max(z_offset_aspirate, 1)
        z_offset_aspirate = min(z_offset_aspirate, source_container.container_type.container_height - self.HEIGHT_BELOW_SOLVENT_LEVEL_WHEN_ASPIRATING)

        if target_container.container_type is not None:
            if 'FLASK' in target_container.container_type.container_name.upper():
                additional_offset += self.HEIGHT_BELOW_CONTAINER_TOP_WHEN_DISPENSING_FLASKS
            elif 'FALCON_TUBE' in target_container.container_type.container_name.upper():
                additional_offset += self.HEIGHT_BELOW_CONTAINER_TOP_WHEN_DISPENSING_FALCON_TUBES

        z_offset_dispense += self.HEIGHT_ABOVE_SOLVENT_LEVEL_WHEN_DISPENSING
        z_offset_dispense = max(z_offset_dispense, self.HEIGHT_ABOVE_SOLVENT_LEVEL_WHEN_DISPENSING)
        z_offset_dispense = min(z_offset_dispense, target_container.container_type.container_height - additional_offset)

        return z_offset_aspirate, z_offset_dispense

    def run(self, protocol_file: str) -> bool:
        """
        Uploads and runs the specified file on the OT2 via HTTP POST requests.

        Parameters
        ----------
        protocol_file : str
            Path to the Python protocol file.

        Returns
        -------
        bool
            True if the protocol was run successfully.

        Raises
        ------
        RuntimeError
            If an error occurs when uploading the protocol to the robot.
        """
        if OT2.EMERGENCY_STOP_REQUEST:
            return False

        # POST the protocol files to OT2
        files = [("protocolFile", open(protocol_file, 'rb'))] + [("supportFiles", open(f, 'rb')) for f in self.custom_labware_definition]

        response = requests.post(
            url=f"http://{self.ip_address_resolved}:31950/protocols",
            headers={"Opentrons-Version": "2"},
            files=files  # With only 1 support file a dict can be used, but for support files a list is needed due to the key needing to be supportFile for each)
        )
        logger.debug(f"Create Protocol result: {response.json()}", extra=self._logger_dict)

        # Extract the uploaded protocol id from the response
        self.protocol_id = response.json()['data']['id']

        try:
            errors = response.json()['data'].get('errors')
            if errors:
                logger.critical(f"Errors in protocol: {errors}", extra=self._logger_dict)
                raise RuntimeError(f"Errors in protocol: {errors}")

            self.__run_protocol(self.protocol_id)
            return True

        finally:
            # Use the protocol_id to DELETE the protocol
            requests.delete(
                url=f"http://{self.ip_address_resolved}:31950/protocols/{self.protocol_id}",
                headers={"Opentrons-Version": "2"},
            )

    def __run_protocol(self, protocol_id: str) -> None:
        """
        Runs the specified protocol on the OT2.

        Parameters
        ----------
        protocol_id : str
            The ID of the uploaded protocol to be run.

        Raises
        ------
        RuntimeError
            If an error occurs while running the protocol.
        """
        if OT2.EMERGENCY_STOP_REQUEST:
            return

        # Create a protocol session
        response = requests.post(
            url=f"http://{self.ip_address_resolved}:31950/sessions",
            headers={"Opentrons-Version": "2"},
            json={
                "data": {
                    "sessionType": "protocol",
                    "createParams": {
                        "protocolId": protocol_id
                    }
                }
            }
        )
        logger.debug(f"Create Session result: {response.json()}", extra=self._logger_dict)
        # Extract the session id from the response
        self.session_id = response.json()['data']['id']

        try:
            # Creating the protocol session kicks off a full simulation which can
            # take some time. Wait until session is in the 'loaded' state before running
            while True:
                # Sleep for 1/2 a second
                time.sleep(.5)

                response = requests.get(
                    url=f"http://{self.ip_address_resolved}:31950/sessions/{self.session_id}",
                    headers={"Opentrons-Version": "2"},
                )

                current_state = response.json()['data']['details']['currentState']
                if current_state == 'loaded':
                    break
                elif current_state == 'error':
                    logger.critical(f"Error encountered {response.json()}", extra=self._logger_dict)
                    raise RuntimeError(f"Error encountered {response.json()}")

            # Send a command to begin a protocol run
            requests.post(
                url=f"http://{self.ip_address_resolved}:31950/sessions/{self.session_id}/commands/execute",
                headers={"Opentrons-Version": "2"},
                json={"data": {"command": "protocol.startRun", "data": {}}}
            )
            logger.info(f'Started executing protocol: {response.json()["data"]["details"]["protocolId"]}', extra=self._logger_dict)

            # Wait until session is in the 'finished' state
            while True:
                # Sleep for 1/2 a second
                time.sleep(.5)

                response = requests.get(
                    url=f"http://{self.ip_address_resolved}:31950/sessions/{self.session_id}",
                    headers={"Opentrons-Version": "2"},
                )

                current_state = response.json()['data']['details']['currentState']
                if current_state == 'finished':
                    logger.info(f'Protocol {response.json()["data"]["details"]["protocolId"]} completed.', extra=self._logger_dict)
                    logger.debug(response.json(), extra=self._logger_dict)
                    break
                elif current_state == 'error':
                    logger.critical(f"Error encountered {response.json()}", extra=self._logger_dict)
                    raise RuntimeError(f"Error encountered {response.json()}")

        finally:
            # Use the session_id to DELETE the session
            requests.delete(
                url=f"http://{self.ip_address_resolved}:31950/sessions/{self.session_id}",
                headers={"Opentrons-Version": "2"},
            )

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
        tmp_ot2_hardware_configuration = kwargs_dict.pop('configuration', None)
        if tmp_ot2_hardware_configuration is not None:
            for k, v in list(tmp_ot2_hardware_configuration.items()):
                tmp_ot2_hardware_configuration.pop(k)
                if v is not None and "<class 'Hardware.SampleHolder.SampleHolder.SampleHolder'>" in v:
                    tmp_ot2_hardware_configuration[int(k)] = loaded_configuration_dict['SampleHolder'][v]
                else:
                    tmp_ot2_hardware_configuration[int(k)] = v
            self.configuration = tmp_ot2_hardware_configuration
        self.left_pipette = kwargs_dict.pop('left_pipette', None)
        self.left_pipette_volume = kwargs_dict.pop('left_pipette_volume', -1)
        self.tip_racks_for_left_pipette = kwargs_dict.pop('tip_racks_for_left_pipette', [])
        self.current_tip_index_for_left_pipette = kwargs_dict.pop('current_tip_index_for_left_pipette', -1)
        self.current_tip_rack_for_left_pipette = kwargs_dict.pop('current_tip_rack_for_left_pipette', ('', ''))
        self.right_pipette = kwargs_dict.pop('right_pipette', None)
        self.right_pipette_volume = kwargs_dict.pop('right_pipette_volume', -1)
        self.tip_racks_for_right_pipette = kwargs_dict.pop('tip_racks_for_right_pipette', [])
        self.current_tip_index_for_right_pipette = kwargs_dict.pop('current_tip_index_for_right_pipette', -1)
        self.current_tip_rack_for_right_pipette = kwargs_dict.pop('current_tip_rack_for_right_pipette', ('', ''))
        self.custom_labware_definition = kwargs_dict.pop('custom_labware_definition', [])
        return True

    def emergency_stop(self) -> bool:
        """
        Sends a stop command for the current session to the OT2 via HTTP POST requests.

        Returns
        -------
        bool
            True if the emergency stop protocol was run successfully.

        Raises
        ------
        RuntimeError
            If an error occurs when uploading the protocol to the robot.
        """
        OT2.EMERGENCY_STOP_REQUEST = True

        response = requests.post(
            url=f"http://{self.ip_address_resolved}:31950/sessions/{self.session_id}/commands/execute",
            headers={"Opentrons-Version": "2"},
            json={"data": {"command": "protocol.pause", "data": {}}}   # protocol.cancel returns robot to home, resulting in further movement
        )

        emergency_protocol_id = response.json()['data']['id']

        try:
            errors = response.json()['data'].get('errors')
            if errors:
                logger.critical(f"Errors in emergency stop protocol: {errors}", extra=self._logger_dict)
                raise RuntimeError(f"Errors in emergency stop protocol: {errors}")

            logger.critical(f"Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
            return True

        finally:
            # Use the protocol_id to DELETE the protocol
            requests.delete(
                url=f"http://{self.ip_address_resolved}:31950/protocols/{emergency_protocol_id}",
                headers={"Opentrons-Version": "2"},
            )
            requests.delete(
                url=f"http://{self.ip_address_resolved}:31950/protocols/{self.protocol_id}",
                headers={"Opentrons-Version": "2"},
            )


# Note: The http Sessions API only works with version 4.0 of the OT-2 robot software
# See: https://github.com/Opentrons/http-api-beta/
# To enable the experimental features:
#
# Since these features are experimental, they're disabled by default. Here's how to enable them:
#
#     From the Robot tab, go to your OT-2's page.
#     Scroll down to the Advanced Settings section.
#     Turn on Enable Experimental HTTP Protocol Sessions.
#
# Note: While these experimental features are enabled, you won't be able to upload protocols the normal way, through the
#       Opentrons App.
#
# To restore the ability to upload protocols through the Opentrons App, turn off Enable Experimental HTTP Protocol
# Sessions. Feel free to toggle the setting whenever you need to.
