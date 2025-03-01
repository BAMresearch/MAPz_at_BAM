#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import json
import math
from typing import Union, Tuple, List, Dict, Any, TYPE_CHECKING
from Minerva.API.HelperClassDefinitions import Hardware, SampleHolderHardware, SampleHolderDefinitions



class SampleHolder(SampleHolderHardware):
    """
    Class to get the coordinates of a slot in a sample holder

    Parameters
    ----------
    hardware_definition : Union[SampleHolderDefinitions, str, Dict[str, Any]]
        Either a string containing the path to the json file with the hardware definition, a member of the SampleHolderDefinitions Enum class, or a dict with the contents of the file
    parent_hardware : Union[Hardware, None] = None
        Optional field specifying the parent hardware where this sample holder is located. Use None if it is directly on the "root" object (Lab Bench).
    deck_position : int, default = 0
        The deck number of the holder (if the parent hardware has several positions for holders). Default is 0.
    leave_even_rows_empty : bool, default = True
        If set to True, only every other row will be filled with containers (might be necessary to give the gripper enough space for gripping a container, depending on the row spacing)

    Raises
    ------
    AssertionError
        If an invalid value is entered for any of the fields.
    """

    def __init__(self, hardware_definition: Union[SampleHolderDefinitions, str, Dict[str, Any]], parent_hardware: Union[Hardware, None] = None, deck_position: int = 0, leave_even_rows_empty: bool = True) -> None:
        super().__init__()
        assert isinstance(deck_position, int) and deck_position >= 0, 'deck_position must be an integer >= 0'

        if isinstance(hardware_definition, dict):
            self._hardware_definition = hardware_definition
        else:
            if isinstance(hardware_definition, SampleHolderDefinitions):
                hardware_definition_str = hardware_definition.value
            else:
                hardware_definition_str = str(hardware_definition)
            self._hardware_definition = json.load(open(hardware_definition_str))

        self._parent_hardware: Union[Hardware, None] = None
        if parent_hardware is None:
            self._parent_hardware = self
        else:
            self._parent_hardware = parent_hardware

        self.leave_even_rows_empty = leave_even_rows_empty
        self._deck_position = deck_position
        slot = 1
        self.available_slots: Dict[int, Union[str, None]] = {}
        if self.leave_even_rows_empty:
            for row in range(1, self._hardware_definition['dimensions']['rows'] + 1):
                if row % 2 == 1:
                    for col in range(slot, slot + self._hardware_definition['dimensions']['columnsInOddRows']):
                        self.available_slots[slot] = None
                        slot += 1
                else:
                    slot += self._hardware_definition['dimensions']['columnsInEvenRows']
        else:
            self.available_slots = {p + 1: None for p in range(0, self._hardware_definition['dimensions']['totalPlaces'])}

    @property
    def hardware_definition(self) -> Any:
        return self._hardware_definition

    @property
    def parent_hardware(self) -> Hardware:
        return self._parent_hardware

    @property
    def deck_position(self) -> int:
        return self._deck_position

    def save_configuration(self) -> Dict[str, Any]:
        """
        Method for saving the relevant parameters of this Hardware.

        Returns
        -------
        Dict[str, Any]
            A Dictionary with the relevant information of the class that should be saved and can be restored with load_configuration.
        """
        return {repr(self): vars(self)}

    def get_coordinates(self, slot_number: int, offset_top_left: Union[Tuple[float, ...], List[float], dict, None] = (0.0, 0.0, 0.0), rotation_angle: float = 0, invert_y: bool = True) -> Union[Tuple[float, float, float], None]:
        """
        Get the coordinates of a slot in a sample holder

        Parameters
        ----------
        slot_number: int
            The number of the slot in the holder (starting at 1, counting from top left)
        offset_top_left:  Union[Tuple[float, ...], List[float, ...], dict, None] = (0.0, 0.0, 0.0)
            Optional offset to be added to all positions. If None, the offset is read from the json file used when creating the instance. If dict, has to have the keys x0, y0, and z0.
        rotation_angle: float = 0
            Optional counterclockwise rotation angle in degrees about the z-Axis of the holder to match the returned coordinates with the robot coordinate system. Typically, the longer side is along the x-Axis. Default is 0.
        invert_y: bool = True
            Optional value indicating to invert the y coordinates (should be used when spacings are positive and slot 1 is in the top left corner). NB that this creates a left-handed coordinate system, i.e., rotationbs will be clockwise.

        Returns
        -------
        Union[Tuple[float, float, float], None]
            A tuple containing the x, y, and z coordinates of the slot in the specified holder, or None if an invalid slot number was given
        """
        if slot_number < 1 or slot_number > self.hardware_definition['dimensions']['totalPlaces']:
            return None

        if offset_top_left is None:
            offset_top_left = self.hardware_definition['wells']['offsetTopLeft']
        if isinstance(offset_top_left, Dict):
            for k in offset_top_left:
                if offset_top_left[k] is None:
                    offset_top_left[k] = self.hardware_definition['wells']['offsetTopLeft'][k]
            offset_top_left = (offset_top_left["x0"], offset_top_left["y0"], offset_top_left["z0"])

        p = self.hardware_definition['dimensions']['columnsInOddRows']
        row_counter = 1

        while p <= self.hardware_definition['dimensions']['totalPlaces']:
            if slot_number // (p + 1) == 0:
                break

            if row_counter % 2 == 0:
                p += self.hardware_definition['dimensions']['columnsInOddRows']
            else:
                p += self.hardware_definition['dimensions']['columnsInEvenRows']

            row_counter += 1

        x = self.hardware_definition['wells']['spacings']['xs'] * (slot_number - 1 - (row_counter // 2 * self.hardware_definition['dimensions']['columnsInOddRows']) - ((row_counter - 1) // 2 * self.hardware_definition['dimensions']['columnsInEvenRows']))
        y = self.hardware_definition['wells']['spacings']['ys'] * (row_counter - 1)
        z = self.hardware_definition['wells']['spacings']['zs']

        x += ((row_counter + 1) % 2) * self.hardware_definition['wells']['evenRowAdditionalOffset']['xe'] + offset_top_left[0]
        y += ((row_counter + 1) % 2) * self.hardware_definition['wells']['evenRowAdditionalOffset']['ye'] + offset_top_left[1]
        z += ((row_counter + 1) % 2) * self.hardware_definition['wells']['evenRowAdditionalOffset']['ze'] + offset_top_left[2]

        if invert_y:
            y = -y

        if rotation_angle != 0:
            phi = math.radians(rotation_angle % 360)
            
            x_rot = x * math.cos(phi) - y * math.sin(phi)
            y_rot = x * math.sin(phi) + y * math.cos(phi)
            x = x_rot
            y = y_rot

        return x, y, z

    def get_next_free_slot(self) -> Union[int, None]:
        """
        Gets the number of a free slot in a sample holder

        Returns
        -------
        Union[int, None]
            An integer of the next free slot, or None if no free slots are available in the holder
        """
        for slot in self.available_slots:
            if self.available_slots[slot] is None:
                return slot

        return None
