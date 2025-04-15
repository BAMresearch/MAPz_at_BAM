#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

import json
import os
import time
import re

import PIL
import dearpygui.dearpygui as dpg
import inspect
import ctypes
import logging
import typing
from typing import Any, List, get_type_hints, Union, Optional, _GenericAlias

import numpy as np

from transformers import pipeline, AutoModelForSeq2SeqLM, AutoTokenizer
import torch

import Minerva
import Minerva.API.HelperClassDefinitions
from Minerva.API.HelperClassDefinitions import Volume, Mass, MolarAmount, Concentration, MassConcentration, Time, Temperature, RotationSpeed

# Create a custom logger and set it to the lowest level
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create handler
c_handler = logging.StreamHandler()

# Configure the handler
c_format = logging.Formatter('%(asctime)s:%(message)s')
c_handler.setFormatter(c_format)

# Set the logging level for the handler
c_handler.setLevel(logging.INFO)

# Add handler to the logger
logger.addHandler(c_handler)

if __name__ == '__main__':
    def _make_titlecase(input_str: str) -> str:
        """
        Return a copy of the input string using Title Case

        Parameters
        ----------
        input_str (str): The input string that should be title-cased

        Returns
        -------
        str: The tiel-cased version of the input string
        """
        return ' '.join([i[0].upper() + i[1:] for i in input_str.replace('_', ' ').split(' ')])

    POPUP_MENU_WIDTH = 190
    FIRST_NODE_POSITION = (25, 25)
    NODE_PADDING = (8, 8)
    CONTAINER_TYPES = ['None'] + [i[0] for i in inspect.getmembers(Minerva.ContainerTypeCollection)[1:] if i[0] != 'name' and i[0] != 'value' and not i[0].startswith('_')]
    SYRINGES = [i[0] for i in inspect.getmembers(Minerva.Syringes) if i[0] != 'name' and i[0] != 'value' and not i[0].startswith('_')]
    SAMPLE_HOLDERS = [i[0] for i in inspect.getmembers(Minerva.SampleHolderDefinitions) if i[0] != 'name' and i[0] != 'value' and not i[0].startswith('_')]
    PUMP_TYPES = [i[0] for i in inspect.getmembers(Minerva.SyringePumpType) if i[0] != 'name' and i[0] != 'value' and i[0] != 'SyringePumpSpeeds' and not i[0].startswith('_')]
    HARDWARE = ['None']
    CURRENT_CONFIG = {}
    CLIPBOARD = ()
    IS_EXPANDED = True
    NEXT_CONTAINER_INDEX = 1
    COLLAPSE_TOGGLE = False
    IMAGE_TOGGLE = True
    SELECTED_FILE = ''
    CONFIGURATION_PATH = ''
    WARNING_MSG = ''
    PIPE = None
    CALL_PARAMETER_ONTOLOGY = set()
    IGNORE_TYPES = ('ABC', 'NoneType', 'Object', 'object')
    IGNORE_PARAMS = ('task_group_synchronization_object', 'is_final_task', 'is_ready', 'sync_condition', 'return')
    ORIGINAL_WIDTH = 150  # Original input field widths
    ZOOM_FACTOR = 1.0
    ZOOM_STEP = 0.1
    IS_PANNING = False
    LAST_MOUSE_POS = (0, 0)

    MB_ICONERROR = 0x000000010
    MB_ICONQUESTION = 0x000000020
    MB_ICONWARNING = 0x000000030
    MB_ICONINFORMATION = 0x00000040


    def create_node_from_object(obj: Any, pos: Optional[List[float]] = None)->Union[int, str]:
        """
        Creates a node representation of an object in Dear PyGui.

        Args:
            obj (Any): The object to be represented as a node.
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        global NEXT_CONTAINER_INDEX
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_reaction'))

        tmp_nodename = inspect.getsource(obj).lstrip(' ')
        tmp_nodename = _make_titlecase(tmp_nodename[tmp_nodename.find(' ')+1:min(tmp_nodename.find('('), tmp_nodename.find(':'))])

        tmp_signature = inspect.getdoc(obj)
        if 'Raises\n' in tmp_signature and 'Returns\n' in tmp_signature:
            end_index = min(tmp_signature.find('Raises'), tmp_signature.find('Returns'))-2
        elif 'Raises\n' in tmp_signature:
            end_index = tmp_signature.find('Raises')-2
        elif 'Returns\n' in tmp_signature:
            end_index = tmp_signature.find('Returns')-2
        else:
            end_index = -2

        tmp_signature = tmp_signature[tmp_signature.find('----------')+11:end_index].split('\n')
        tmp_signature_variables = [tmp_signature[i].replace(' ', '').replace(',default=', ':').replace('=', ':').replace('_', ' ').split(':') for i in range(0, len(tmp_signature), 2)]
        tmp_signature_tooltips = [tmp_signature[i].replace('    ', '') for i in range(1, len(tmp_signature), 2)]
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=active_ne, user_data=obj)

        if tmp_nodename == 'Container':
            dpg.bind_item_theme(node_id, container_titlebar_theme)
        elif tmp_nodename == 'Chemical':
            dpg.bind_item_theme(node_id, chemical_titlebar_theme)
        elif tmp_nodename == 'Hardware':
            dpg.bind_item_theme(node_id, hardware_titlebar_theme)
        elif tmp_nodename == 'Measure Dls':
            dpg.bind_item_theme(node_id, characterization_titlebar_theme)
        else:
            dpg.bind_item_theme(node_id, other_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        if tmp_nodename not in ('Chemical', 'Container'):
            tmp_signature_variables = [['Container', 'Container']] + tmp_signature_variables
            tmp_signature_tooltips = ['The container on which the action is performed.'] + tmp_signature_tooltips

        for ind in range(0, len(tmp_signature_variables)):
            if tmp_signature_variables[ind][0] in ['task group synchronization object', 'block', 'priority']:
                continue

            i = tmp_signature_variables[ind]
            i[0] = _make_titlecase(i[0])

            j = tmp_signature_tooltips[ind] + '\n'
            br = 0
            while len(j) - br > 40:
                br = j[:br+40].rfind(' ')
                j = j[:br] + '\n' + j[br+1:]
            j = j[:-1]
            default_value = ''
            if i[1] in ['int', 'float', 'str', 'bool']:
                shape = 4
            elif 'controller' in i[1].lower() or 'hardware' in i[1].lower():
                shape = 2
            else:
                shape = 0

            if 'Chemical' in i[1]:
                theme = chemical_pin_theme
            elif 'Container' in i[1] and 'Type' not in i[1]:
                theme = container_pin_theme
            elif 'Hardware' in i[1]:
                theme = hardware_pin_theme
            else:
                theme = other_pin_theme

            if len(i) > 2:
                node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_{i[0].lower()}', attribute_type=dpg.mvNode_Attr_Input, shape=shape)
            else:
                node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_{i[0].lower()}', attribute_type=dpg.mvNode_Attr_Input, shape=shape+1)

            dpg.bind_item_theme(node_attribute_id, theme)

            if i[1] == 'bool':
                if len(i) > 2:
                    default_value = (i[2] == 'True')
                field_id = dpg.add_checkbox(parent=node_attribute_id, label=i[0], default_value=default_value)
            elif i[1] == 'int':
                if len(i) > 2:
                    default_value = int(i[2])
                field_id = dpg.add_input_int(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif i[1] == 'float':
                if len(i) > 2:
                    default_value = float(i[2])
                field_id = dpg.add_input_float(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif 'ContainerTypeCollection' in i[1]:
                if len(i) > 2 and i[2] != 'None':
                    default_value = i[2]
                else:
                    default_value = CONTAINER_TYPES[0]
                field_id = dpg.add_combo(items=CONTAINER_TYPES, parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif 'Syringes' in i[1]:
                if len(i) > 2 and i[2] != 'None':
                    default_value = i[2]
                else:
                    default_value = SYRINGES[0]
                field_id = dpg.add_combo(items=SYRINGES, parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif 'SampleHolderDefinitions' in i[1]:
                if len(i) > 2 and i[2] != 'None':
                    default_value = i[2]
                else:
                    default_value = SAMPLE_HOLDERS[0]
                field_id = dpg.add_combo(items=SAMPLE_HOLDERS, parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif 'Hardware' in i[1]:
                if len(i) > 2 and i[2] != 'None':
                    default_value = i[2]
                else:
                    default_value = HARDWARE[0]
                field_id = dpg.add_combo(items=HARDWARE, parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif tmp_nodename == 'Container' and i[0].lower() == 'name':
                field_id = dpg.add_input_text(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=f'Container_{NEXT_CONTAINER_INDEX}')
                NEXT_CONTAINER_INDEX += 1
                dpg.bind_item_handler_registry(field_id, item_handler)
            elif tmp_nodename == 'Chemical' and i[0].lower() == 'name':
                field_id = dpg.add_input_text(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value='')
                dpg.bind_item_handler_registry(field_id, item_handler)
            else:
                if len(i) > 2:
                    default_value = i[2].replace("'", "")
                field_id = dpg.add_input_text(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_{i[1]}_{field_id}')
            dpg.add_text(j, parent=tooltip_id, label=f'tooltip_text_{i[1]}_{tooltip_id}')

        output = dpg.add_node_attribute(parent=node_id, label='node_attribute_output', attribute_type=dpg.mvNode_Attr_Output)
        if tmp_nodename == 'Chemical':
            dpg.bind_item_theme(output, chemical_pin_theme)

        dpg.bind_item_font(node_id, node_fonts[int(16 * ZOOM_FACTOR)])
        return node_id

    def create_controller_hardware_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates a controller hardware node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Controller Hardware'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        hardware_type = 'arduino_controllers'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Arduino Controllers{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'local_pc_server'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Local PC Server Controllers{" "*(34-len(hardware_type)-11)}\n{"="*(len(hardware_type)+12)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'emergency_stop_button'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Emergency Stop Buttons{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        return node_id

    def create_synthesis_hardware_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates a synthesis hardware node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Synthesis Hardware'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        hardware_type = 'robot_arm'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Robot Arms{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'hotplate'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Hotplates{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'centrifuge'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Centrifuges{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'probe_sonicator'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Probe Sonicators{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'bath_sonicator'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Bath Sonicators{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        return node_id

    def create_characterization_hardware_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates a characterization hardware node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Characterization Hardware'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        hardware_type = 'dls_zeta'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'DLS/Zeta{" "*(35-len(hardware_type))}\n{"="*(len(hardware_type))}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'plate_reader'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Plate Readers{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        return node_id

    def create_addition_hardware_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates an addition hardware node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Addition Hardware'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        hardware_type = 'pipetting_robot'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Pipetting Robots{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'syringe_pump'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Syringe Pumps{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'vici_valve'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Vici Valves{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'chemputer_valve'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Chemputer Valves{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        return node_id

    def create_addition_hardware_config_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates a synthesis hardware configuration node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Addition Hardware Configuration'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        hardware_type = 'addition_hardware_configuration'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Addition Hardware Configuration{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        return node_id

    def create_auxiliary_hardware_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates an auxiliary hardware node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Auxiliary Hardware'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        hardware_type = 'hotplate_clamp'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Hotplate Clamps{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'hotplate_fan'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Hotplate Fans{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'capper_decapper'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Capper/Decapper{" "*(35-len(hardware_type))}\n{"="*(len(hardware_type))}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'dht_22_sensor'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'DHT22 Sensors{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type)

        hardware_type = 'electromagnet'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Electromagnets{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)

        hardware_type = 'esp32_camera'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        dpg.add_text('\n', parent=node_attribute_id)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'ESP32 Cameras{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, Minerva.ESP32Camera.Camera)
        return node_id

    def create_sample_holder_hardware_node(pos: Optional[List[float]]=None)->Union[int, str]:
        """
        Creates a sample holder hardware node.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        tmp_nodename = 'Sample Holder Hardware'
        node_id = dpg.add_node(label=tmp_nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text(f'\n\nToggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')

        hardware_type = 'sample_holder'
        node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
        with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
            dpg.add_text(f'Sample Holders{" "*(34-len(hardware_type))}\n{"="*(len(hardware_type)+1)}', parent=group_id)
            _create_add_remove_buttons(group_id, hardware_type)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        _add_hardware(node_id, hardware_type, 0, True)
        return node_id

    def _initialize_node(pos: Optional[List[float]], nodename: str)->Union[int, str]:
        """
        Creates a "blank" node with the given name at the given position.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            nodename (str):

        Returns:
            Union[int, str]: The ID of the created node.
        """
        if pos is None:
            pos = _get_coordinates(mouse_pos=dpg.get_item_pos('right_click_menu_configuration'))

        node_id = dpg.add_node(label=nodename, pos=pos, parent=ne_configuration)
        dpg.bind_item_theme(node_id, hardware_titlebar_theme)

        node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_collapse button', attribute_type=dpg.mvNode_Attr_Static)
        field_id = dpg.add_button(parent=node_attribute_id, label='^', callback=collapse)
        tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_collapse_{field_id}')
        dpg.add_text('Toggle Expand/Collapse', parent=tooltip_id, label=f'tooltip_text_collapse_{tooltip_id}')
        return node_id

    def create_arduino_controller_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates an arduino controller hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Arduino Controller Hardware')
        hardware_type = 'arduino_controllers'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_server_controller_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a server controller hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Local Server Hardware')
        hardware_type = 'local_pc_server'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_emergency_stop_button_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates an emergency stop button hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Emergency Stop Button Hardware')
        hardware_type = 'emergency_stop_button'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_robot_arm_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a robot arm hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Robot Arm Hardware')
        hardware_type = 'robot_arm'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_hotplate_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a hotplate hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Hotplate Hardware')
        hardware_type = 'hotplate'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_centrifuge_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a centrifuge hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Centrifuge Hardware')
        hardware_type = 'centrifuge'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_probe_sonicator_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a probe sonicator hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Probe Sonicator Hardware')
        hardware_type = 'probe_sonicator'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_bath_sonicator_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a bath sonicator hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Bath Sonicator Hardware')
        hardware_type = 'bath_sonicator'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_dls_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a DLS hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'DLS/Zeta Hardware')
        hardware_type = 'dls_zeta'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_platereader_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a platereader hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Plate Reader Hardware')
        hardware_type = 'plate_reader'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_syringe_pump_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a syringe pump hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Syringe Pump Hardware')
        hardware_type = 'syringe_pump'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_pipetting_robot_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a pipetting robot hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Pipetting Robot Hardware')
        hardware_type = 'pipetting_robot'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        _add_addition_hardware_configuration(node_id, hardware_type, True, True)
        return node_id

    def create_vici_valve_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a vici valco multiport valve hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Vici Valve Hardware')
        hardware_type = 'vici_valve'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        _add_addition_hardware_configuration(node_id, hardware_type, True, True)
        return node_id

    def create_chemputer_valve_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a chemputer multiport valve hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Chemputer Valve Hardware')
        hardware_type = 'chemputer_valve'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        _add_addition_hardware_configuration(node_id, hardware_type, True, True)
        return node_id

    def create_hotplate_clamp_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a hotplate clamp hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Hotplate Clamp Hardware')
        hardware_type = 'hotplate_clamp'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_hotplate_fan_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a hotplate fan hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Hotplate Fan Hardware')
        hardware_type = 'hotplate_fan'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_capper_decapper_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a capper/decapper hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Capper/Decapper Hardware')
        hardware_type = 'capper_decapper'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_dht22_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a DHT22 temperature and humidity sensor hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Temperature/Humidity Sensor Hardware')
        hardware_type = 'dht_22_sensor'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_electromagnet_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates an electromagnet hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Electromagnet Hardware')
        hardware_type = 'electromagnet'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_esp32_camera_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates an ESP32 camera hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'ESP32 Camera Hardware')
        hardware_type = 'esp32_camera'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)
        return node_id

    def create_sample_holder_hardware_image_node(pos: Optional[List[float]]=None, image: Optional[str]=None)->Union[int, str]:
        """
        Creates a sample holder hardware node with the specified image from the texture library.

        Args:
            pos (Optional[List[float]], optional): The position of the node in the GUI. Defaults to None, in which case the coordinates of the popup menu are used.
            image (Optional[str], optional): The texture tag of the image in the texture library. Defaults to None, in which case no image is displayed.

        Returns:
            Union[int, str]: The ID of the created node.
        """
        node_id = _initialize_node(pos, 'Sample Holder Hardware ')
        hardware_type = 'sample_holder'
        if image is not None:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_image_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static)
            dpg.add_image(texture_tag=image, parent=node_attribute_id)
        _add_hardware(node_id, hardware_type, 0, False)

        return node_id

    def _add_hardware(node_id: Union[int, str], hardware_type: str, before: int=0, show_separator: bool=True)->Union[int, str, None]:
        """
        Parses the signature of the hardware class and adds the corresponding input and output fields to the specified hardware node.

        Args:
            node_id (Union[int, str]): The node ID of the parent node to which the fields are added
            hardware_type (str): A string identifying the hardware type of the parent hardware node
            before (int=0, optional): The ID of an item in the parent node before which the newly added fields should be inserted. Defaults to 0.
            show_separator (bool=True, optional): Whether to show a separator between the hardware fields and the configuration fields. Defaults to True.

        Returns:
            Union[int, str, None]: The ID of the added node attribute, or None if an invalid hardware type is given.
        """
        if hardware_type == 'robot_arm':
            obj = Minerva.UFactory.XArm6
        elif hardware_type == 'hotplate':
            obj = Minerva.IkaHotplate.RCTDigital5
        elif hardware_type == 'syringe_pump':
            obj = Minerva.WPI.Aladdin
        elif hardware_type == 'vici_valve':
            obj = Minerva.SwitchingValve.SwitchingValveVici
        elif hardware_type == 'chemputer_valve':
            obj = Minerva.SwitchingValve.SwitchingValveArduino
        elif hardware_type == 'pipetting_robot':
            obj = Minerva.OpentronsOT2.OT2
        elif hardware_type == 'centrifuge':
            obj = Minerva.Herolab.RobotCen
        elif hardware_type == 'arduino_controllers':
            obj = Minerva.ArduinoController.ArduinoController
        elif hardware_type == 'local_pc_server':
            obj = Minerva.LocalPCServer.LocalPCServer
        elif hardware_type == 'capper_decapper':
            obj = Minerva.CapperDecapper.CapperDecapper
        elif hardware_type == 'dht_22_sensor':
            obj = Minerva.DHT22Sensor.DHT22Sensor
        elif hardware_type == 'electromagnet':
            obj = Minerva.Electromagnet.Electromagnet
        elif hardware_type == 'emergency_stop_button':
            obj = Minerva.EmergencyStopButton.EmergencyStopButton
        elif hardware_type == 'esp32_camera':
            obj = Minerva.ESP32Camera.Camera
        elif hardware_type == 'hotplate_clamp':
            obj = Minerva.HotplateClamp.HotplateClampDCMotor
        elif hardware_type == 'hotplate_fan':
            obj = Minerva.HotplateFan.HotplateFan
        elif hardware_type == 'dls_zeta':
            obj = Minerva.MalvernPanalytical.ZetaSizer
        elif hardware_type == 'plate_reader':
            obj = Minerva.MolecularDevices.SpectraMaxM3
        elif hardware_type == 'probe_sonicator':
            obj = Minerva.Hielscher.UP200ST
        elif hardware_type == 'bath_sonicator':
            obj = Minerva.Bandelin.SonorexDigitecHRC
        elif hardware_type == 'sample_holder':
            obj = Minerva.SampleHolder.SampleHolder
        elif hardware_type == 'addition_hardware_configuration':
            shape = 0
            output_id = 0

            for i in dpg.get_item_children(node_id)[1]:
                if dpg.get_item_label(i) == 'node_attribute_output':
                    output_id = i
                    break

            if output_id == 0:
                i = (len(dpg.get_item_children(node_id)[1]) - 2)
            else:
                i = (len(dpg.get_item_children(node_id)[1]) - 4)

            before = output_id

            if output_id == 0:
                node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_name', attribute_type=dpg.mvNode_Attr_Input, shape=shape+1, before=before)
                field_id = dpg.add_input_text(parent=node_attribute_id, label=f'Name', width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value='')
                dpg.bind_item_theme(node_attribute_id, other_pin_theme)
                dpg.bind_item_handler_registry(field_id, item_handler)
                tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_name_{field_id}')
                dpg.add_text(f'Name of the addition hardware configuration', parent=tooltip_id, label=f'tooltip_text_{i}_{tooltip_id}')

            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_slot_{i}', attribute_type=dpg.mvNode_Attr_Input, shape=shape+1, before=before)
            field_id = dpg.add_input_text(parent=node_attribute_id, label=f'Slot {i}', width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value='None')
            dpg.bind_item_theme(node_attribute_id, hardware_pin_theme)
            tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_{i}_{field_id}')
            dpg.add_text(f'Configuration Slot {i}', parent=tooltip_id, label=f'tooltip_text_{i}_{tooltip_id}')

            if output_id == 0:
                output = dpg.add_node_attribute(parent=node_id, label='node_attribute_output', attribute_type=dpg.mvNode_Attr_Output, before=before, shape=3)
                dpg.bind_item_theme(output, hardware_pin_theme)
            return output
        else:
            return None

        tmp_signature = inspect.getdoc(obj)
        if 'Raises\n' in tmp_signature and 'Returns\n' in tmp_signature:
            end_index = min(tmp_signature.find('Raises'), tmp_signature.find('Returns'))-2
        elif 'Raises\n' in tmp_signature:
            end_index = tmp_signature.find('Raises')-2
        elif 'Returns\n' in tmp_signature:
            end_index = tmp_signature.find('Returns')-2
        else:
            end_index = -2

        tmp_signature = tmp_signature[tmp_signature.find('----------')+11:end_index].split('\n')
        tmp_signature_variables = [tmp_signature[i].replace(' ', '').replace(',default=', ':').replace('=', ':').replace('_', ' ').split(':') for i in range(0, len(tmp_signature), 2)]
        tmp_signature_tooltips = [tmp_signature[i].replace('    ', '') for i in range(1, len(tmp_signature), 2)]

        tmp_signature_variables = [['Name', 'Name']] + tmp_signature_variables
        tmp_signature_tooltips = ['The name of the hardware component.'] + tmp_signature_tooltips

        if dpg.get_item_label(node_id) == 'Addition Hardware':
            tmp_signature_variables = [['Configuration', 'Configuration']] + tmp_signature_variables
            tmp_signature_tooltips = ['The configuration of the addition hardware component.'] + tmp_signature_tooltips

        for ind in range(0, len(tmp_signature_variables)):
            i = tmp_signature_variables[ind]
            i[0] = _make_titlecase(i[0])

            j = tmp_signature_tooltips[ind] + '\n'
            pos = 0
            while len(j) - pos > 40:
                pos = j[:pos+40].rfind(' ')
                j = j[:pos] + '\n' + j[pos+1:]
            j = j[:-1]
            default_value = ''

            if 'Hardware' in i[1] or 'Controller' in i[1] or 'Configuration' in i[1]:
                theme = hardware_pin_theme
            else:
                theme = other_pin_theme

            if i[1] in ['int', 'float', 'str', 'bool']:
                shape = 4
            elif 'controller' in i[1].lower() or 'hardware' in i[1].lower() or 'configuration' in i[1].lower():
                shape = 2
            else:
                shape = 0

            if len(i) > 2:
                node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_{i[0].lower()}', attribute_type=dpg.mvNode_Attr_Input, shape=shape, before=before)
            else:
                node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_{i[0].lower()}', attribute_type=dpg.mvNode_Attr_Input, shape=shape+1, before=before)

            dpg.bind_item_theme(node_attribute_id, theme)

            if i[1] == 'bool':
                if len(i) > 2:
                    default_value = (i[2] == 'True')
                field_id = dpg.add_checkbox(parent=node_attribute_id, label=i[0], default_value=default_value)
            elif i[1] == 'int':
                if len(i) > 2:
                    default_value = int(i[2])
                field_id = dpg.add_input_int(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif i[1] == 'float':
                if len(i) > 2:
                    default_value = float(i[2])
                field_id = dpg.add_input_float(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            elif i[0].lower() == 'name':
                field_id = dpg.add_input_text(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value='')
                dpg.bind_item_handler_registry(field_id, item_handler)
            elif i[0].lower() == 'pump type':
                field_id = dpg.add_combo(items=PUMP_TYPES, parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=PUMP_TYPES[0])
                dpg.bind_item_handler_registry(field_id, item_handler)
            else:
                if len(i) > 2:
                    default_value = i[2].replace("'", "").replace("serial.PARITY NONE", "N")
                field_id = dpg.add_input_text(parent=node_attribute_id, label=i[0], width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=default_value)
            tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_{i[1]}_{field_id}')
            dpg.add_text(j, parent=tooltip_id, label=f'tooltip_text_{i[1]}_{tooltip_id}')

        if hardware_type == 'syringe_pump':
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_syringe', attribute_type=dpg.mvNode_Attr_Input, shape=4, before=before)
            dpg.bind_item_theme(node_attribute_id, other_pin_theme)
            field_id = dpg.add_combo(items=SYRINGES, parent=node_attribute_id, label='Syringe', width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value=SYRINGES[0])

        output = dpg.add_node_attribute(parent=node_id, label='node_attribute_output', attribute_type=dpg.mvNode_Attr_Output, before=before, shape=3)
        dpg.bind_item_theme(output, hardware_pin_theme)

        dpg.set_item_user_data(node_id, obj)

        if show_separator:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label='node_attribute_separator', attribute_type=dpg.mvNode_Attr_Static, before=before)
            dpg.add_text('-----------------------------------------', parent=node_attribute_id)
        return output

    def _create_add_remove_buttons(group_id: Union[int, str], hardware_type: str)->None:
        """
        Adds the "Add" and "Remove" buttons to the specified node that allow dynamically adding and removing fields from nodes with a variable number of fields.

        Args:
            group_id (Union[int, str]): The node ID of the group item on the parent node to which the buttons are added
            hardware_type (str): A string identifying the hardware type of the parent hardware node

        Returns:
            None
        """
        field_id = dpg.add_button(parent=group_id, label='+', user_data=hardware_type, callback=add_hardware_cb)
        tooltip_id = dpg.add_tooltip(field_id, label=f'add_{hardware_type}_{field_id}')
        dpg.add_text(f"Add {_make_titlecase(hardware_type.replace('_', ' '))}", parent=tooltip_id, label=f'tooltip_text_add_{hardware_type}_{tooltip_id}')
        field_id = dpg.add_button(parent=group_id, label='-', user_data=hardware_type, callback=remove_hardware_cb)
        tooltip_id = dpg.add_tooltip(field_id, label=f'remove_{hardware_type}_{field_id}')
        dpg.add_text(f"Remove {_make_titlecase(hardware_type.replace('_', ' '))}", parent=tooltip_id, label=f'tooltip_text_remove_{hardware_type}_{tooltip_id}')

    def _add_addition_hardware_configuration(node_id: Union[int, str], hardware_type: str, initialize: bool=False, add_slot: bool=True)->None:
        """
        Adds or removes an addition hardware configuration slot to the specified node.

        Args:
            node_id (Union[int, str]): The node ID of the addition hardxware node to which the slot is added added
            hardware_type (str): A string identifying the hardware type of the parent hardware node
            initialize (bool=False): If set to True, buttons for adding/renmoving slots will be added as well. Defaults to False
            add_slot (bool=True): If set to True, a slot is added, if set to False, the last slot is removed. Defaults to True

        Returns:
            None
        """
        shape = 0
        before = 0
        current_slot_number = 0

        for i in dpg.get_item_children(node_id)[1]:
            if dpg.get_item_label(i).startswith('node_attribute_slot_'):
                current_slot_number += 1
            elif dpg.get_item_label(i) == 'node_attribute_output':
                before = i

        if initialize:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_text_{hardware_type}', attribute_type=dpg.mvNode_Attr_Static, before=before)
            with dpg.group(parent=node_attribute_id, horizontal=True, horizontal_spacing=10) as group_id:
                dpg.add_text(f'Configuration:', parent=group_id)
                field_id = dpg.add_button(parent=group_id, label='+', user_data=hardware_type, callback=handle_slots_cb)
                tooltip_id = dpg.add_tooltip(field_id, label=f'add_{hardware_type}_{field_id}')
                dpg.add_text(f"Add {_make_titlecase(hardware_type.replace('_', ' '))} Configuration Slot", parent=tooltip_id, label=f'tooltip_text_add_{hardware_type}_{tooltip_id}')
                field_id = dpg.add_button(parent=group_id, label='-', user_data=hardware_type, callback=handle_slots_cb)
                tooltip_id = dpg.add_tooltip(field_id, label=f'remove_{hardware_type}_{field_id}')
                dpg.add_text(f"Remove {_make_titlecase(hardware_type.replace('_', ' '))} Configuration Slot", parent=tooltip_id, label=f'tooltip_text_remove_{hardware_type}_{tooltip_id}')

        if add_slot:
            node_attribute_id = dpg.add_node_attribute(parent=node_id, label=f'node_attribute_slot_{current_slot_number}', attribute_type=dpg.mvNode_Attr_Input, shape=shape+1, before=before)
            field_id = dpg.add_input_text(parent=node_attribute_id, label=f'Slot {current_slot_number}', width=ORIGINAL_WIDTH * ZOOM_FACTOR, default_value='None')
            dpg.bind_item_theme(node_attribute_id, hardware_pin_theme)
            tooltip_id = dpg.add_tooltip(field_id, label=f'tooltip_{current_slot_number}_{field_id}')
            dpg.add_text(f'Configuration Slot {current_slot_number}', parent=tooltip_id, label=f'tooltip_text_{current_slot_number}_{tooltip_id}')
        else:
            del_items = []
            for i in dpg.get_item_children(node_id)[1]:
                if dpg.get_item_label(i).startswith('node_attribute_slot_'):
                    del_items.append(i)

            if len(del_items) > 0:
                dpg.delete_item(del_items[-1])

    def _get_coordinates(mouse_pos: Optional[List[float]]=None)->None:
        """
        Gets the screen coordinates as relative positions in the node editor window (taking into account any zooming and panning inside the node editor relative to the parent window).

        Args:
            mouse_pos (Optional[List[float]]=None): The coordinates that should be converted into relative positions in the node editor window

        Returns:
            List[float]: The relative positions in the node editor window
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        if mouse_pos is None:
            pos = dpg.get_mouse_pos(local=False)
        else:
            pos = mouse_pos

        if len(dpg.get_item_children(active_ne, slot=1)) == 0:
            return pos

        ref_node = dpg.get_item_children(active_ne, slot=1)[0]
        ref_screen_pos = dpg.get_item_rect_min(ref_node)
        ref_grid_pos = dpg.get_item_pos(ref_node)
        pos[0] = pos[0] - (ref_screen_pos[0] - NODE_PADDING[0]) + ref_grid_pos[0]
        pos[1] = pos[1] - (ref_screen_pos[1] - NODE_PADDING[1]) + ref_grid_pos[1]
        return pos

    def right_click_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered upon a right mouse click.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            dpg.configure_item("right_click_menu_reaction", pos=dpg.get_mouse_pos(local=False))
            dpg.configure_item("right_click_menu_reaction", show=True)
        else:
            dpg.configure_item("right_click_menu_configuration", pos=dpg.get_mouse_pos(local=False))
            dpg.configure_item("right_click_menu_configuration", show=True)

    def left_click_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered upon a left mouse click.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_menu = "right_click_menu_reaction"
        else:
            active_menu = "right_click_menu_configuration"

        if not dpg.get_item_state(active_menu)['visible']:
            return

        window_pos = dpg.get_item_state(active_menu)['pos']
        window_size = dpg.get_item_state(active_menu)['rect_size']
        mouse_pos = dpg.get_mouse_pos(local=False)

        if mouse_pos[0] < window_pos[0] or mouse_pos[0] > window_pos[0] + window_size[0] or mouse_pos[1] < window_pos[1] or mouse_pos[1] > window_pos[1] + window_size[1]:
            dpg.configure_item(active_menu, show=False)

    def del_keypress_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered upon pressing the <DEL> key.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        for i in dpg.get_selected_nodes(active_ne):
            for j in dpg.get_item_children(active_ne)[0]:
                if dpg.get_item_label(j).startswith(f'link_{dpg.get_item_parent(i)}-'):
                    nodeeditor_unlink_cb(None, j, None)
        for i in list(dpg.get_selected_nodes(active_ne)):
            dpg.delete_item(i)

    def shortcut_keypress_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered upon pressing the <CTRL> key to handle all shortcuts.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global CLIPBOARD

        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        if dpg.is_key_down(dpg.mvKey_C):
            CLIPBOARD = (dpg.get_selected_nodes(active_ne), dpg.get_selected_links(active_ne))
        elif dpg.is_key_down(dpg.mvKey_S):
            save(sender, app_data, user_data)
        elif dpg.is_key_down(dpg.mvKey_E):
            export_python(sender, app_data, user_data)
        elif dpg.is_key_down(dpg.mvKey_X):
            export_config(sender, app_data, user_data)
        elif dpg.is_key_down(dpg.mvKey_O):
            load(sender, app_data, user_data)
        elif dpg.is_key_down(dpg.mvKey_V):
            if len(CLIPBOARD) == 0:
                return

            nodes, links = CLIPBOARD
            links = [(int(dpg.get_item_label(i).replace('link_', '').split('-')[0]), int(dpg.get_item_label(i).replace('link_', '').split('-')[1])) for i in links]
            pairs = {}
            minimized = []
            for i in nodes:
                offset = (0, 0)
                if len(nodes) > 1:
                    offset = (dpg.get_item_pos(i)[0] - dpg.get_item_pos(nodes[0])[0], dpg.get_item_pos(i)[1] - dpg.get_item_pos(nodes[0])[1])
                pos = _get_coordinates()
                pos[0] += offset[0]
                pos[1] += offset[1]
                if dpg.get_item_label(i) == 'Addition Hardware':
                    tmp = create_addition_hardware_node(pos)
                elif dpg.get_item_label(i) == 'Addition Hardware Configuration':
                    tmp = create_addition_hardware_config_node(pos)
                elif dpg.get_item_label(i) == 'Auxiliary Hardware':
                    tmp = create_auxiliary_hardware_node(pos)
                elif dpg.get_item_label(i) == 'Characterization Hardware':
                    tmp = create_characterization_hardware_node(pos)
                elif dpg.get_item_label(i) == 'Controller Hardware':
                    tmp = create_controller_hardware_node(pos)
                elif dpg.get_item_label(i) == 'Sample Holder Hardware':
                    tmp = create_sample_holder_hardware_node(pos)
                elif dpg.get_item_label(i) == 'Synthesis Hardware':
                    tmp = create_synthesis_hardware_node(pos)
                elif dpg.get_item_label(i) == 'Robot Arm Hardware':
                    tmp = create_robot_arm_hardware_image_node(pos=pos, image='robot_arm')
                elif dpg.get_item_label(i) == 'Temperature/Humidity Sensor Hardware':
                    tmp = create_dht22_hardware_image_node(pos=pos, image='dht22')
                elif dpg.get_item_label(i) == 'Centrifuge Hardware':
                    tmp = create_centrifuge_hardware_image_node(pos=pos, image='centrifuge')
                elif dpg.get_item_label(i) == 'DLS/Zeta Hardware':
                    tmp = create_dls_hardware_image_node(pos=pos, image='dls')
                elif dpg.get_item_label(i) == 'Platereader Hardware':
                    tmp = create_platereader_hardware_image_node(pos=pos, image='platereader')
                elif dpg.get_item_label(i) == 'Electromagnet Hardware':
                    tmp = create_electromagnet_hardware_image_node(pos=pos, image='electromagnet')
                elif dpg.get_item_label(i) == 'Hotplate Hardware':
                    tmp = create_hotplate_hardware_image_node(pos=pos, image='hotplate')
                elif dpg.get_item_label(i) == 'Arduino Controller Hardware':
                    tmp = create_arduino_controller_hardware_image_node(pos=pos, image='arduino')
                elif dpg.get_item_label(i) == 'Bath Sonicator Hardware':
                    tmp = create_bath_sonicator_hardware_image_node(pos=pos, image='bath_sonicator')
                elif dpg.get_item_label(i) == 'Capper/Decapper Hardware':
                    tmp = create_capper_decapper_hardware_image_node(pos=pos, image='capper_decapper')
                elif dpg.get_item_label(i) == 'Chemputer Valve Hardware':
                    tmp = create_chemputer_valve_hardware_image_node(pos=pos, image='chemputer_valve')
                elif dpg.get_item_label(i) == 'Hotplate Clamp Hardware':
                    tmp = create_hotplate_clamp_hardware_image_node(pos=pos, image='hotplate_clamp')
                elif dpg.get_item_label(i) == 'Hotplate Fan Hardware':
                    tmp = create_hotplate_fan_hardware_image_node(pos=pos, image='hotplate_fan')
                elif dpg.get_item_label(i) == 'Pipetting Robot Hardware':
                    tmp = create_pipetting_robot_hardware_image_node(pos=pos, image='ot2')
                elif dpg.get_item_label(i) == 'Probe Sonicator Hardware':
                    tmp = create_probe_sonicator_hardware_image_node(pos=pos, image='probe_sonicator')
                elif dpg.get_item_label(i) == 'Local Server Hardware':
                    tmp = create_server_controller_hardware_image_node(pos=pos, image='server')
                elif dpg.get_item_label(i) == 'Syringe Pump Hardware':
                    tmp = create_syringe_pump_hardware_image_node(pos=pos, image='syringe_pump')
                elif dpg.get_item_label(i) == 'Vici Valve Hardware':
                    tmp = create_vici_valve_hardware_image_node(pos=pos, image='vici_valve')
                elif dpg.get_item_label(i) == 'Sample Holder Hardware ':
                    tmp = create_sample_holder_hardware_image_node(pos=pos, image='sample_holder')
                elif dpg.get_item_label(i) == 'Emergency Stop Button Hardware':
                    tmp = create_emergency_stop_button_hardware_image_node(pos=pos, image='emergency_stop_button')
                elif dpg.get_item_label(i) == 'ESP32 Camera Hardware':
                    tmp = create_esp32_camera_hardware_image_node(pos=pos, image='esp32_camera')
                else:
                    tmp = create_node_from_object(dpg.get_item_user_data(i), pos)
                for j, c in enumerate(dpg.get_item_children(i)[1]):
                    val = dpg.get_item_children(c)[1]
                    pairs[c] = dpg.get_item_children(tmp)[1][j]
                    if dpg.get_item_label(c) == 'node_attribute_collapse button' and dpg.get_item_label(dpg.get_item_children(c)[1][0]) == 'v':
                        minimized.append(dpg.get_item_children(dpg.get_item_children(tmp)[1][j])[1][0])
                    if len(val) == 0 or (dpg.get_item_label(i) == 'Container' and dpg.get_item_label(c) == 'node_attribute_name') or any([c in k for k in links]):
                        continue
                    val = dpg.get_value(val[0])
                    dpg.set_value(dpg.get_item_children(dpg.get_item_children(tmp)[1][j])[1][0], val)

            for i in links:
                if dpg.get_item_parent(i[0]) in nodes and dpg.get_item_parent(i[1]) in nodes:
                    nodeeditor_link_cb(sender=active_ne, app_data=[pairs[i[0]], pairs[i[1]]], user_data=None)

            for i in minimized:
                collapse(i, None, None)

            CLIPBOARD = []

    def nodeeditor_link_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when a new link between two nodes is created.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        if update_field(app_data):
            link = dpg.add_node_link(app_data[0], app_data[1], parent=sender, label=f'link_{app_data[0]}-{app_data[1]}')
            if dpg.get_item_label(dpg.get_item_children(app_data[1])[1][0]) == 'Container' and dpg.get_item_label(dpg.get_item_parent(app_data[1])) != 'Chemical':
                dpg.bind_item_theme(link, container_link_theme)

    def nodeeditor_unlink_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when a link between two nodes is deleted.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        clear_field(app_data)
        dpg.delete_item(app_data)

    def update_field(app_data: Any)->bool:
        """
        Automatically enables, disables, and updates fields such as container or chemicals names of "downstream" nodes when a node is linked.

        Args:
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets

        Returns:
            bool: True if successful, False otherwise
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        is_linked = any([app_data[1] == int(dpg.get_item_label(i).replace('link_', '').split('-')[1]) for i in dpg.get_item_children(active_ne)[0]])

        if dpg.get_item_label(dpg.get_item_parent(app_data[0])) == 'Chemical':
            for i in dpg.get_item_children(dpg.get_item_parent(app_data[0]))[1]:
                if dpg.get_item_label(i) == 'node_attribute_name':
                    name = dpg.get_value(dpg.get_item_children(i)[1][0])
                    break
            else:
                return False
            if dpg.get_item_label(app_data[1]) == 'node_attribute_chemical':
                if not is_linked:
                    dpg.set_value(dpg.get_item_children(app_data[1])[1][0], name)
                else:
                    dpg.set_value(dpg.get_item_children(app_data[1])[1][0], ';'.join(val for val in dpg.get_value(dpg.get_item_children(app_data[1])[1][0]).split(';') + [name] if val != '' and val != 'None'))
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=False)
            elif 'chemical' in dpg.get_item_label(app_data[1]):
                for i in dpg.get_item_children(active_ne)[0]:
                    if app_data[1] == int(dpg.get_item_label(i).replace('link_', '').split('-')[1]):
                        clear_field(i)
                        dpg.delete_item(i)
                        break
                dpg.set_value(dpg.get_item_children(app_data[1])[1][0], name)
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=False)
            else:
                return False
        elif 'Hardware' in dpg.get_item_label(dpg.get_item_parent(app_data[0])) and ('parent hardware' in dpg.get_item_label(app_data[1]) or 'current hardware' in dpg.get_item_label(app_data[1]) or 'controller' in dpg.get_item_label(app_data[1]) or 'slot' in dpg.get_item_label(app_data[1]) or 'configuration' in dpg.get_item_label(app_data[1])):
            for i in dpg.get_item_children(dpg.get_item_parent(app_data[0]))[1]:
                if dpg.get_item_label(i) == 'node_attribute_name':
                    name = dpg.get_value(dpg.get_item_children(i)[1][0])
                elif i == app_data[0]:
                    break
            else:
                return False

            for i in dpg.get_item_children(active_ne)[0]:
                if app_data[1] == int(dpg.get_item_label(i).replace('link_', '').split('-')[1]):
                    clear_field(i)
                    dpg.delete_item(i)
                    break
            dpg.set_value(dpg.get_item_children(app_data[1])[1][0], name)
            dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=False)
        else:
            names = []
            for i in dpg.get_item_children(dpg.get_item_parent(app_data[0]))[1]:
                if dpg.get_item_label(i) == 'node_attribute_name' or dpg.get_item_label(i) == 'node_attribute_container':
                    names.append(dpg.get_value(dpg.get_item_children(i)[1][0]))
                elif dpg.get_item_label(i) == 'node_attribute_containers':
                    names += dpg.get_value(dpg.get_item_children(i)[1][0]).split(';')
            if len(names) == 0:
                return False
            elif len(names) == 1:
                name = names[0]
            else:
                cnt = 0
                for i in dpg.get_item_children(active_ne)[0]:
                    if str(app_data[0]) in dpg.get_item_label(i).replace('link_', '').split('-'):
                        cnt += 1
                if cnt < len(names) - 1:
                    name = names[cnt + 1]
                else:
                    name = names[0]
            if dpg.get_item_label(app_data[1]) == 'node_attribute_containers':
                if not is_linked:
                    dpg.set_value(dpg.get_item_children(app_data[1])[1][0], name)
                else:
                    dpg.set_value(dpg.get_item_children(app_data[1])[1][0], ';'.join(val for val in dpg.get_value(dpg.get_item_children(app_data[1])[1][0]).split(';') + [name] if val != '' and val != 'None'))
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=False)
            elif 'container' in dpg.get_item_label(app_data[1]) or dpg.get_item_label(app_data[1]) == 'node_attribute_dls cell' or 'slot' in dpg.get_item_label(app_data[1]):
                for i in dpg.get_item_children(active_ne)[0]:
                    if app_data[1] == int(dpg.get_item_label(i).replace('link_', '').split('-')[1]):
                        clear_field(i)
                        dpg.delete_item(i)
                        break
                dpg.set_value(dpg.get_item_children(app_data[1])[1][0], name)
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=False)
            else:
                return False

        return True

    def clear_field(app_data: Any)->bool:
        """
        Automatically enables, disables, and clears fields such as container or chemicals names of "downstream" nodes when a node link is deleted.

        Args:
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets

        Returns:
            bool: True if successful, False otherwise
        """
        app_data = [int(i) for i in dpg.get_item_label(app_data).replace('link_', '').split('-')]
        if dpg.get_item_label(dpg.get_item_parent(app_data[0])) == 'Chemical':
            for i in dpg.get_item_children(dpg.get_item_parent(app_data[0]))[1]:
                if dpg.get_item_label(i) == 'node_attribute_name':
                    name = dpg.get_value(dpg.get_item_children(i)[1][0])
                    break
            else:
                return False
            if dpg.get_item_label(app_data[1]) == 'node_attribute_chemical':
                dpg.set_value(dpg.get_item_children(app_data[1])[1][0], ';'.join(val for val in dpg.get_value(dpg.get_item_children(app_data[1])[1][0]).replace(name, '').split(';') if val != '' and val != 'None'))
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=(dpg.get_value(dpg.get_item_children(app_data[1])[1][0]) == ''))
            elif 'chemical' in dpg.get_item_label(app_data[1]):
                dpg.set_value(dpg.get_item_children(app_data[1])[1][0], '')
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=True)
            else:
                return False
        else:
            for i in dpg.get_item_children(dpg.get_item_parent(app_data[0]))[1]:
                if dpg.get_item_label(i) == 'node_attribute_name' or dpg.get_item_label(i) == 'node_attribute_container':
                    name = dpg.get_value(dpg.get_item_children(i)[1][0])
                    break
            else:
                return False
            if dpg.get_item_label(app_data[1]) == 'node_attribute_containers':
                dpg.set_value(dpg.get_item_children(app_data[1])[1][0], ';'.join(val for val in dpg.get_value(dpg.get_item_children(app_data[1])[1][0]).replace(name, '').split(';') if val != '' and val != 'None'))
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=(dpg.get_value(dpg.get_item_children(app_data[1])[1][0]) == ''))
            elif 'container' in dpg.get_item_label(app_data[1]) or dpg.get_item_label(app_data[1]) == 'node_attribute_dls cell' or 'controller' in dpg.get_item_label(app_data[1]) or 'hardware' in dpg.get_item_label(app_data[1]) or 'slot' in dpg.get_item_label(app_data[1]) or 'configuration' in dpg.get_item_label(app_data[1]):
                dpg.set_value(dpg.get_item_children(app_data[1])[1][0], '')
                dpg.configure_item(dpg.get_item_children(app_data[1])[1][0], enabled=True)
            else:
                return False

        return True

    def save_nodes(file_path: str)->None:
        """
        Saves the node configuratiuon as a json file to the specified file path

        Args:
            file_path (str): The file path where the configuration is saved

        Returns:
            None
        """
        data = {'nodes': {}, 'links': {}}
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        for node in dpg.get_item_children(active_ne)[1]:
            data['nodes'][node] = {'type': dpg.get_item_label(node), 'pos': dpg.get_item_pos(node), 'fields': {}}
            for c in dpg.get_item_children(node)[1]:
                data['nodes'][node]['fields'][c] = {}
                data['nodes'][node]['fields'][c]['label'] = dpg.get_item_label(c)
                if dpg.get_item_label(c) == 'node_attribute_collapse button':
                    data['nodes'][node]['fields'][c]['is_collapsed'] = (dpg.get_item_label(dpg.get_item_children(c)[1][0]) == 'v')
                elif len(dpg.get_item_children(c)[1]) > 0:
                    data['nodes'][node]['fields'][c]['value'] = dpg.get_value(dpg.get_item_children(c)[1][0])

        for link in dpg.get_item_children(active_ne)[0]:
            data['links'][link] = {}
            tmp = [int(i) for i in dpg.get_item_label(link).replace('link_', '').split('-')]
            data['links'][link]['linked_nodes'] = [int(dpg.get_item_parent(tmp[0])), int(dpg.get_item_parent(tmp[1]))]
            data['links'][link]['linked_fields'] = [int(tmp[0]), int(tmp[1])]

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)

    def load_nodes(file_path: str)->None:
        """
        Loads a previously saved node configuratiuon from the specified file path

        Args:
            file_path (str): The file path where the configuration is saved

        Returns:
            None
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        with open(file_path, 'r') as f:
            data = json.load(f)

        mappings = {}
        collapsed = []
        for node in data['nodes'].keys():
            mappings[node] = {}
            if data['nodes'][node]['type'] == 'Container':
                mappings[node]['node'] = create_node_from_object(Minerva.Container, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Chemical':
                mappings[node]['node'] = create_node_from_object(Minerva.Chemical, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Add Chemical':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.add_chemical, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Heat':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.heat, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Infuse While Heating':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.infuse_while_heating, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Centrifuge':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.centrifuge, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Remove Supernatant And Redisperse':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.remove_supernatant_and_redisperse, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Sonicate':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.sonicate, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Transfer Content To Container':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.transfer_content_to_container, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Measure Dls':
                mappings[node]['node'] = create_node_from_object(Minerva.Container.measure_dls, data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Addition Hardware':
                mappings[node]['node'] = create_addition_hardware_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Addition Hardware Configuration':
                mappings[node]['node'] = create_addition_hardware_config_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Auxiliary Hardware':
                mappings[node]['node'] = create_auxiliary_hardware_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Characterization Hardware':
                mappings[node]['node'] = create_characterization_hardware_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Controller Hardware':
                mappings[node]['node'] = create_controller_hardware_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Sample Holder Hardware':
                mappings[node]['node'] = create_sample_holder_hardware_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Synthesis Hardware':
                mappings[node]['node'] = create_synthesis_hardware_node(data['nodes'][node]['pos'])
            elif data['nodes'][node]['type'] == 'Robot Arm Hardware':
                mappings[node]['node'] = create_robot_arm_hardware_image_node(pos=data['nodes'][node]['pos'], image='robot_arm')
            elif data['nodes'][node]['type'] == 'Temperature/Humidity Sensor Hardware':
                mappings[node]['node'] = create_dht22_hardware_image_node(pos=data['nodes'][node]['pos'], image='dht22')
            elif data['nodes'][node]['type'] == 'Centrifuge Hardware':
                mappings[node]['node'] = create_centrifuge_hardware_image_node(pos=data['nodes'][node]['pos'], image='centrifuge')
            elif data['nodes'][node]['type'] == 'DLS/Zeta Hardware':
                mappings[node]['node'] = create_dls_hardware_image_node(pos=data['nodes'][node]['pos'], image='dls')
            elif data['nodes'][node]['type'] == 'Platereader Hardware':
                mappings[node]['node'] = create_platereader_hardware_image_node(pos=data['nodes'][node]['pos'], image='platereader')
            elif data['nodes'][node]['type'] == 'Electromagnet Hardware':
                mappings[node]['node'] = create_electromagnet_hardware_image_node(pos=data['nodes'][node]['pos'], image='electromagnet')
            elif data['nodes'][node]['type'] == 'Hotplate Hardware':
                mappings[node]['node'] = create_hotplate_hardware_image_node(pos=data['nodes'][node]['pos'], image='hotplate')
            elif data['nodes'][node]['type'] == 'Arduino Controller Hardware':
                mappings[node]['node'] = create_arduino_controller_hardware_image_node(pos=data['nodes'][node]['pos'], image='arduino')
            elif data['nodes'][node]['type'] == 'Bath Sonicator Hardware':
                mappings[node]['node'] = create_bath_sonicator_hardware_image_node(pos=data['nodes'][node]['pos'], image='bath_sonicator')
            elif data['nodes'][node]['type'] == 'Capper/Decapper Hardware':
                mappings[node]['node'] = create_capper_decapper_hardware_image_node(pos=data['nodes'][node]['pos'], image='capper_decapper')
            elif data['nodes'][node]['type'] == 'Chemputer Valve Hardware':
                mappings[node]['node'] = create_chemputer_valve_hardware_image_node(pos=data['nodes'][node]['pos'], image='chemputer_valve')
            elif data['nodes'][node]['type'] == 'Hotplate Clamp Hardware':
                mappings[node]['node'] = create_hotplate_clamp_hardware_image_node(pos=data['nodes'][node]['pos'], image='hotplate_clamp')
            elif data['nodes'][node]['type'] == 'Hotplate Fan Hardware':
                mappings[node]['node'] = create_hotplate_fan_hardware_image_node(pos=data['nodes'][node]['pos'], image='hotplate_fan')
            elif data['nodes'][node]['type'] == 'Pipetting Robot Hardware':
                mappings[node]['node'] = create_pipetting_robot_hardware_image_node(pos=data['nodes'][node]['pos'], image='ot2')
            elif data['nodes'][node]['type'] == 'Probe Sonicator Hardware':
                mappings[node]['node'] = create_probe_sonicator_hardware_image_node(pos=data['nodes'][node]['pos'], image='probe_sonicator')
            elif data['nodes'][node]['type'] == 'Local Server Hardware':
                mappings[node]['node'] = create_server_controller_hardware_image_node(pos=data['nodes'][node]['pos'], image='server')
            elif data['nodes'][node]['type'] == 'Syringe Pump Hardware':
                mappings[node]['node'] = create_syringe_pump_hardware_image_node(pos=data['nodes'][node]['pos'], image='syringe_pump')
            elif data['nodes'][node]['type'] == 'Vici Valve Hardware':
                mappings[node]['node'] = create_vici_valve_hardware_image_node(pos=data['nodes'][node]['pos'], image='vici_valve')
            elif data['nodes'][node]['type'] == 'Sample Holder Hardware ':
                mappings[node]['node'] = create_sample_holder_hardware_image_node(pos=data['nodes'][node]['pos'], image='sample_holder')
            elif data['nodes'][node]['type'] == 'Emergency Stop Button Hardware':
                mappings[node]['node'] = create_emergency_stop_button_hardware_image_node(pos=data['nodes'][node]['pos'], image='emergency_stop_button')
            elif data['nodes'][node]['type'] == 'ESP32 Camera Hardware':
                mappings[node]['node'] = create_esp32_camera_hardware_image_node(pos=data['nodes'][node]['pos'], image='esp32_camera')

            dpg.configure_item(mappings[node]['node'], show=False)
            mappings[node]['fields'] = {}
            for key, val in data['nodes'][node]['fields'].items():
                if val['label'].startswith('node_attribute_slot_') and not val['label'] == 'node_attribute_slot_0':
                    _add_addition_hardware_configuration(node_id=mappings[node]['node'], hardware_type=data['nodes'][node]['type'], initialize=False, add_slot=True)
                for i in dpg.get_item_children(mappings[node]['node'])[1]:
                    if dpg.get_item_label(i) == val['label']:
                        mappings[node]['fields'][key] = i
                        if 'value' in val.keys():
                            dpg.set_value(dpg.get_item_children(i)[1][0], val['value'])
                        elif 'is_collapsed' in val.keys() and val['is_collapsed']:
                            collapsed.append(dpg.get_item_children(i)[1][0])
                        break
                else:
                    msg = f'Invalid key-value pair:\n{key}: {val}'
                    ctypes.windll.user32.MessageBoxW(0, msg, "Minerva Node Editor - Error", MB_ICONERROR)
                    logger.error(msg)

        for link in data['links'].values():
            try:
                node0 = mappings[str(link['linked_nodes'][0])]['fields'][str(link['linked_fields'][0])]
                node1 = mappings[str(link['linked_nodes'][1])]['fields'][str(link['linked_fields'][1])]
            except KeyError:
                continue
            li = dpg.add_node_link(node0, node1, parent=active_ne, label=f'link_{node0}-{node1}')
            if dpg.get_item_label(dpg.get_item_children(node1)[1][0]) == 'Container' and dpg.get_item_label(dpg.get_item_parent(node1)) != 'Chemical':
                dpg.bind_item_theme(li, container_link_theme)
            dpg.configure_item(dpg.get_item_children(node1)[1][0], enabled=False)

        for i in collapsed:
            collapse(i, None, None)

        for i in dpg.get_item_children(active_ne)[1]:
            dpg.configure_item(i, show=True)

    def item_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when a add_item_deactivated_after_edit event occurs.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        links = [(j, [int(i) for i in dpg.get_item_label(j).replace('link_', '').split('-')]) for j in dpg.get_item_children(active_ne)[0]]
        for i in links:
            nodeeditor_unlink_cb(active_ne, i[0], None)
        for i in links:
            nodeeditor_link_cb(active_ne, i[1], None)

    def find_linked_node_outputs(output_node_id: Union[int, str], all_connections: bool=True)->List[Union[int, str]]:
        """
        Recursively finds "downstream" resp. "right" nodes that are connected to the output field with the specified output node id.

        Args:
            output_node_id (Union[int, str]): The ID of the output field for which the connected nodes are searched
            all_connections (bool=True): If set to True, all connected nodes are included, if set to False, only connected nodes with a 'Container' field are included. Defaults to True

        Returns:
            List[Union[int, str]]: A list of the IDs of the connected "downstream" nodes
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        links = [[int(i) for i in dpg.get_item_label(j).replace('link_', '').split('-')] for j in dpg.get_item_children(active_ne)[0]]
        linked_nodes = [output_node_id]
        for i in links:
            if i[0] == output_node_id:
                if 'chemical' not in dpg.get_item_label(dpg.get_item_children(i[1])[1][0]).lower():
                    for j in dpg.get_item_children(dpg.get_item_parent(i[1]))[1]:
                        if dpg.get_item_label(j) == 'node_attribute_output':
                            if dpg.get_item_label(dpg.get_item_children(i[1])[1][0])=='Container' or all_connections:
                                linked_nodes += find_linked_node_outputs(j, all_connections)
                            else:
                                find_linked_node_outputs(j, all_connections)
                else:
                    linked_nodes += [i[1]]
        return linked_nodes

    def find_left_nodes(node_id: Union[int, str])->List[Union[int, str]]:
        """
        Recursively finds "upstream" resp. "left" nodes whose output are connected to any input field of the node with the specified node id.

        Args:
            node_id (Union[int, str]): The ID of the node for which the connected nodes are searched

        Returns:
            List[Union[int, str]]: A list of the IDs of the connected "upstream" nodes
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration
        links = [[int(i) for i in dpg.get_item_label(j).replace('link_', '').split('-')] for j in dpg.get_item_children(active_ne)[0]]

        left_nodes = []
        for i in links:
            if dpg.get_item_parent(i[1]) == node_id:
                left_nodes.append(dpg.get_item_parent(i[0]))
        return left_nodes

    def add_container_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Container node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container)

    def add_chemical_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Chemical node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Chemical)

    def add_addition_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Addition node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.add_chemical)

    def add_heat_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Heat node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.heat)

    def add_infuse_while_heating_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Infuse_While_Heating node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.infuse_while_heating)

    def add_centrifuge_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Centrifuge node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.centrifuge)

    def add_redisperse_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Redisperse node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.remove_supernatant_and_redisperse)

    def add_sonication_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Sonication node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.sonicate)

    def add_transfer_content_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Transfer_Content_To_Container node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.transfer_content_to_container)

    def add_measure_dls_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Measure_DLS node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        create_node_from_object(Minerva.Container.measure_dls)

    def add_synthesis_hardware_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Synthesis_Hardware node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_synthesis_hardware_node()

    def add_characterization_hardware_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Characterization_Hardware node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_characterization_hardware_node()

    def add_addition_hardware_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Addition_Hardware node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_addition_hardware_node()

    def add_addition_hardware_config_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Addition_Hardware_Configuration node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_addition_hardware_config_node()

    def add_auxiliary_hardware_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Auxiliary_Hardware node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_auxiliary_hardware_node()

    def add_controller_hardware_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Controller_Hardware node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_controller_hardware_node()

    def add_sample_holder_hardware_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Sample_Holder_Hardware node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_sample_holder_hardware_node()

    def add_robot_arm_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Robot_Arm_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_robot_arm_hardware_image_node(pos=None, image='robot_arm')

    def add_dht22_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a DHT22_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_dht22_hardware_image_node(pos=None, image='dht22')

    def add_centrifuge_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Centrifuge_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_centrifuge_hardware_image_node(pos=None, image='centrifuge')

    def add_dls_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a DLS_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_dls_hardware_image_node(pos=None, image='dls')

    def add_platereader_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Platereader_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_platereader_hardware_image_node(pos=None, image='platereader')

    def add_electromagnet_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Electromagnet_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_electromagnet_hardware_image_node(pos=None, image='electromagnet')

    def add_hotplate_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Hotplate_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_hotplate_hardware_image_node(pos=None, image='hotplate')

    def add_arduino_controller_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Arduino_Controller_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_arduino_controller_hardware_image_node(pos=None, image='arduino')

    def add_bath_sonicator_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Sonicator_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_bath_sonicator_hardware_image_node(pos=None, image='bath_sonicator')

    def add_capper_decapper_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Capper_Decapper_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_capper_decapper_hardware_image_node(pos=None, image='capper_decapper')

    def add_chemputer_valve_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Chemputer_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_chemputer_valve_hardware_image_node(pos=None, image='chemputer_valve')

    def add_hotplate_clamp_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Hotplate_Clamp_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_hotplate_clamp_hardware_image_node(pos=None, image='hotplate_clamp')

    def add_hotplate_fan_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Hotplate_Fan_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_hotplate_fan_hardware_image_node(pos=None, image='hotplate_fan')

    def add_pipetting_robot_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Pipetting_Robot_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_pipetting_robot_hardware_image_node(pos=None, image='ot2')

    def add_probe_sonicator_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Probe_Sonicator_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_probe_sonicator_hardware_image_node(pos=None, image='probe_sonicator')

    def add_server_controller_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Server_Controller_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_server_controller_hardware_image_node(pos=None, image='server')

    def add_syringe_pump_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Syringe_Pump_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_syringe_pump_hardware_image_node(pos=None, image='syringe_pump')

    def add_vici_valve_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Vici_Valco_Valve_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_vici_valve_hardware_image_node(pos=None, image='vici_valve')

    def add_sample_holder_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding a Sample_Holder_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_sample_holder_hardware_image_node(pos=None, image='sample_holder')

    def add_emergency_stop_button_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an Emergency_Stop_Button_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_emergency_stop_button_hardware_image_node(pos=None, image='emergency_stop_button')

    def add_esp32_camera_hardware_image_node(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user selects adding an ESP32_Camera_Hardware image node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_configuration", show=False)
        create_esp32_camera_hardware_image_node(pos=None, image='esp32_camera')

    def save(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to save the node setup.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        if SELECTED_FILE != '':
            save_nodes(SELECTED_FILE)
        else:
            if dpg.get_item_configuration(ne_reaction)['show']:
                dpg.configure_item("file_dialog_save_rxn", show=True, user_data='save_nodes')
            else:
                dpg.configure_item("file_dialog_save_conf", show=True, user_data='save_nodes')

    def save_as(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to save the node setup under a diffferent file name.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        if dpg.get_item_configuration(ne_reaction)['show']:
            dpg.configure_item("file_dialog_save_rxn", show=True, user_data='save_nodes')
        else:
            dpg.configure_item("file_dialog_save_conf", show=True, user_data='save_nodes')

    def load(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to load a previously saved node setup.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        dpg.configure_item("file_dialog_open", show=True, user_data='load')

    def export_python(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to export the current node setup to python.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        dpg.configure_item("file_dialog_save_py", show=True, user_data='save_python')

    def export_config(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to export the current hardware configuration.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        dpg.configure_item("file_dialog_save_json", show=True, user_data='save_config')

    def export_knowledge_graph(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to create a knowledge graph from the currently active node setup.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        dpg.configure_item("file_dialog_save_kg", show=True, user_data='save_knowledgegraph')

    def collapse(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to collapse or expand a node by clicking on the ^ or v button.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        is_expanded = (dpg.get_item_label(sender) == '^')

        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        for i in dpg.get_item_children(dpg.get_item_parent(dpg.get_item_parent(sender)))[1]:
            if dpg.get_item_label(i) == 'node_attribute_collapse button' or dpg.get_item_label(i) == 'node_attribute_output' or dpg.get_item_configuration(i)['shape'] in (1, 5) or dpg.get_item_label(dpg.get_item_children(i)[1][0]) == 'Container' or dpg.get_item_label(dpg.get_item_children(i)[1][0]) == 'Name' or dpg.get_item_label(dpg.get_item_children(i)[1][0]) == 'Chemical' or dpg.get_item_label(dpg.get_item_children(i)[1][0]) == 'Parent Hardware'  or dpg.get_item_label(dpg.get_item_children(i)[1][0]) == 'Arduino Controller':
                continue

            if not any([str(i) in dpg.get_item_label(j).replace('link_', '').split('-') for j in dpg.get_item_children(active_ne)[0]]):
                dpg.configure_item(i, show=not is_expanded)

        if is_expanded:
            dpg.configure_item(sender, label='v')
        else:
            dpg.configure_item(sender, label='^')

    def collapse_all(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to collapse or expand all nodes.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global COLLAPSE_TOGGLE
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        for i in dpg.get_item_children(active_ne)[1]:
            s = dpg.get_item_children(dpg.get_item_children(i)[1][0])[1][0]
            if (dpg.get_item_label(s) == '^' and not COLLAPSE_TOGGLE) or (dpg.get_item_label(s) == 'v' and COLLAPSE_TOGGLE):
                collapse(s, None, None)

        COLLAPSE_TOGGLE = not COLLAPSE_TOGGLE

    def toggle_images(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user wants to toggle the display of images for the hardware image nodes.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global IMAGE_TOGGLE
        IMAGE_TOGGLE = not IMAGE_TOGGLE

        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        for i in dpg.get_item_children(active_ne)[1]:
            for j in dpg.get_item_children(i)[1]:
                if dpg.get_item_label(j).startswith('node_attribute_image_'):
                    dpg.configure_item(j, show=IMAGE_TOGGLE)
                    pass

    def file_dialog_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when a file dialog is shown, e.g., for saving, loading or exporting node setups.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global SELECTED_FILE
        global HARDWARE
        global CONFIGURATION_PATH
        global CURRENT_CONFIG

        file_path = app_data['file_path_name']
        if dpg.get_item_user_data(sender) == 'load':
            if file_path.endswith('.rxn') and dpg.get_item_configuration(ne_configuration)['show']:
                switch_view(ne_reaction, None, None)
            elif file_path.endswith('.conf') and dpg.get_item_configuration(ne_reaction)['show']:
                switch_view(ne_configuration, None, None)

        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        if dpg.get_item_user_data(sender) == 'load':
            for i in dpg.get_item_children(active_ne)[0]:
                dpg.delete_item(i)
            for i in dpg.get_item_children(active_ne)[1]:
                dpg.delete_item(i)
            load_nodes(file_path)
            SELECTED_FILE = file_path
            if file_path.endswith('.conf'):
                _update_current_config(None, None, None)

        elif dpg.get_item_user_data(sender) == 'save_nodes':
            save_nodes(file_path)
            if file_path.endswith('.conf'):
                _update_current_config(None, None, None)
        elif dpg.get_item_user_data(sender) == 'save_python':
            write_python_file(file_path)
        elif dpg.get_item_user_data(sender) == 'save_config':
            CURRENT_CONFIG = write_config_file(file_path)
            CONFIGURATION_PATH = file_path
            HARDWARE +=  [j for i, j in CURRENT_CONFIG['NameMappings'].items() if 'MinervaAPI.Container' not in i and 'MinervaAPI.Chemical' not in i]
        elif dpg.get_item_user_data(sender) == 'save_knowledgegraph':
            write_knowledgegraph_file(file_path)

    def _update_current_config(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the current hardware configuration is updated.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global CURRENT_CONFIG
        global HARDWARE
        CURRENT_CONFIG = write_config_file(None)
        HARDWARE +=  [j for i, j in CURRENT_CONFIG['NameMappings'].items() if 'MinervaAPI.Container' not in i and 'MinervaAPI.Chemical' not in i]
        # Update list with available hardware
        for ind, node_id in enumerate(dpg.get_item_children(ne_reaction)[1]):
            for node_attribute in dpg.get_item_children(node_id)[1]:
                for i in dpg.get_item_children(node_attribute)[1]:
                    if dpg.get_item_type(i) == 'mvAppItemType::mvCombo':
                        dpg.configure_item(i, items=HARDWARE)

    def add_hardware_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user clicks on the + button for dynamically adding hardware to a configuration node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        before = 0
        parent_node = dpg.get_item_parent(dpg.get_item_parent(dpg.get_item_parent(sender)))
        found_ht = False
        for i in dpg.get_item_children(parent_node)[1]:
            if dpg.get_item_label(i) == f'node_attribute_text_{user_data}':
                found_ht = True
            elif dpg.get_item_label(i).startswith('node_attribute_text') and found_ht:
                before = i
                break

        _add_hardware(parent_node, user_data, before)

    def remove_hardware_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user clicks on the - button for dynamically removing hardware from a configuration node.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        found_ht = False
        del_items = []
        for i in dpg.get_item_children(dpg.get_item_parent(dpg.get_item_parent(dpg.get_item_parent(sender))))[1]:
            if dpg.get_item_label(i) == f'node_attribute_text_{user_data}':
                found_ht = True
            elif dpg.get_item_label(i).startswith('node_attribute_text') and found_ht:
                break
            if found_ht:
                del_items.append(i)

        del_items.reverse()
        separator_id = 0

        for i, j in enumerate(del_items):
            if dpg.get_item_label(j) != 'node_attribute_separator' and not dpg.get_item_label(j).startswith('node_attribute_add') and not dpg.get_item_label(j).startswith('node_attribute_text'):
                dpg.delete_item(j)
            elif dpg.get_item_label(j) == 'node_attribute_separator' and separator_id == 0:
                separator_id = j
            else:
                break

        dpg.delete_item(separator_id)

    def llm_model_selection_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user changes the selection of the LLM model from the combo box.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global PIPE
        PIPE = None

    def zoom_callback(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user scrolls the mouse wheel for zooming in or out.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global ZOOM_FACTOR

        if any((dpg.get_item_configuration(dialog)['show'] for dialog in (fdo, fdsc, fdsr, fdsp, fdsj, fdsk))):
            return

        # Update zoom factor based on mouse wheel input
        if app_data > 0:
            ZOOM_FACTOR += ZOOM_STEP  # Zoom in
        elif app_data < 0:
            ZOOM_FACTOR -= ZOOM_STEP  # Zoom out

        # Clamp zoom factor to prevent excessive zooming
        if ZOOM_FACTOR < 0.1 or ZOOM_FACTOR > 1.5:
            ZOOM_FACTOR = max(0.1, min(1.5, ZOOM_FACTOR))
            return

        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        # Get current node sizes and positions
        node_sizes_old = np.array([dpg.get_item_rect_size(node_id) for node_id in dpg.get_item_children(active_ne)[1]])
        node_positions = np.array([dpg.get_item_pos(node_id) for node_id in dpg.get_item_children(active_ne)[1]])

        # Get center:
        cx, cy = np.mean(node_positions + node_sizes_old/2.0, axis = 0)

        # Scale text and input widget widths
        for ind, node_id in enumerate(dpg.get_item_children(active_ne)[1]):
            dpg.bind_item_font(node_id, node_fonts[int(16 * ZOOM_FACTOR)])
            for node_attribute in dpg.get_item_children(node_id)[1]:
                for i in dpg.get_item_children(node_attribute)[1]:
                    item_type = dpg.get_item_type(i)
                    if item_type not in ("mvAppItemType::mvTooltip", "mvAppItemType::mvButton", "mvAppItemType::mvCheckbox", "mvAppItemType::mvImage"):
                        dpg.set_item_width(i, int(ORIGINAL_WIDTH * ZOOM_FACTOR))
                        # dpg.set_item_height(i, int(20 * ZOOM_FACTOR))
                    elif item_type == "mvAppItemType::mvImage":
                        ar = dpg.get_item_width(i) / dpg.get_item_height(i)
                        dpg.set_item_width(i, int(ORIGINAL_WIDTH * ZOOM_FACTOR))
                        dpg.set_item_height(i, int(ORIGINAL_WIDTH * ZOOM_FACTOR / ar))

        # Update node sizes
        dpg.split_frame()  # wait for 1 frame to render new node sizes

        # Adjust positions
        node_sizes_new = np.array([dpg.get_item_rect_size(node_id) for node_id in dpg.get_item_children(active_ne)[1]])
        s = node_sizes_new/node_sizes_old
        if app_data > 0:
            s = np.max(s, axis=0)
        else:
            s = np.min(s, axis=0)

        for ind, node_id in enumerate(dpg.get_item_children(active_ne)[1]):
            dpg.set_item_pos(node_id, [round((node_positions[ind][0]-cx-node_sizes_old[ind][0]/2.0)*s[0]+cx+node_sizes_new[ind][0]/2.0, 0), round((node_positions[ind][1]-cy-+node_sizes_old[ind][1]/2.0)*s[1]+cy+node_sizes_new[ind][1]/2.0, 0)])


    # Panning with Ctrl + Drag:
    def mouse_move_callback(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user moves the mouse (used for detecting panning with <CTRL> + Dragging the mouse).

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        global IS_PANNING, LAST_MOUSE_POS

        # If Ctrl + Left Mouse Button is pressed
        if (dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)) and dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            if dpg.get_item_configuration(ne_reaction)['show']:
                active_ne = ne_reaction
            else:
                active_ne = ne_configuration

            # Get current mouse position
            current_mouse_pos = dpg.get_mouse_pos(local=False)

            if not IS_PANNING:
                IS_PANNING = True
                LAST_MOUSE_POS = current_mouse_pos
            else:
                # Calculate delta movement
                delta_x = current_mouse_pos[0] - LAST_MOUSE_POS[0]
                delta_y = current_mouse_pos[1] - LAST_MOUSE_POS[1]

                for node_id in dpg.get_item_children(active_ne)[1]:
                    current_pos = dpg.get_item_pos(node_id)
                    dpg.set_item_pos(node_id, [current_pos[0] + delta_x, current_pos[1] + delta_y])
                # Update last mouse position
                LAST_MOUSE_POS = current_mouse_pos
        else:
            IS_PANNING = False


    def handle_slots_cb(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user clicks on the + or - buttons for dynamically adding/removing hardware.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        parent_node = dpg.get_item_parent(dpg.get_item_parent(dpg.get_item_parent(sender)))
        mode = (dpg.get_item_label(sender) == '+')
        _add_addition_hardware_configuration(parent_node, user_data, False, mode)

    def _format_param(k: str, p: Any)->Any:
        """
        Helper function that takes keys and parameters and converts the parameters to the appropriate python types.

        Parameters:
            k (str): The key value
            p (Any): The parameter value

        Returns
            Any: The parameter p convereted to the appropriate python type
        """

        try:
            if not isinstance(p, str):
                return p
            elif p == 'None':
                return None
            elif p in CURRENT_CONFIG['NameMappings'].values() and 'container' not in k and 'chemical' not in k and 'cell' not in k:
                for k, v in CURRENT_CONFIG['NameMappings'].items():
                    if v == p:
                        if 'Minerva.API.' in k:
                            hardware_type = k.split('.')[3]
                        elif 'Minerva.Hardware.' in k:
                            hardware_type = k.split('.')[2]
                        else:
                            hardware_type = k.split('.')[1]
                        hardware_type = hardware_type.replace('<class ', '')
                        if "'>" in hardware_type:
                            hardware_type = hardware_type[:hardware_type.find("'>")]
                        if hardware_type == 'Chemical' or hardware_type == 'Container':
                            hardware_type += 's'
                        return f"Configuration.{hardware_type}['{p}']"
                else:
                    return p
            elif k == 'container_type':
                return f'ContainerTypeCollection.{p.replace(" ", "_")}'
            elif p != 'None' and 'container' not in k and 'chemical' not in k and 'cell' not in k and 'clearance' not in k:
                p = p.replace("'", "")
                return f"'{p}'"
            elif ';' in p:
                return f'[{", ".join(i for i in p.split(";"))}]'
            else:
                return float(p)
        except ValueError:
            return p

    def _make_valid_variable_name(s: str)->str:
        """
        Function that removes all characters that are invalid in python variable names form the supplied string and replaces them with underscores.

        Parameters:
            s (str): The string that should be turned into a valid variable name

        Returns:
            str: A string that should be a valid variable name in python
        """
        return s.replace(' ', '_').replace('.', '_').replace(',', '_').replace('-', '_').replace(':', '_').replace(';', '_').replace('(', '').replace('[', '').replace('{', '').replace('<', '').replace(')', '').replace(']', '').replace('}', '').replace('>', '').replace('"', '').replace("'", "").replace('`', '').lower()

    def write_python_file(filename: str)->None:
        """
        Method for saving the current node setups as an executable python file.

        Parameters:
            filename (str): The filename of the python file

        Returns:
            None
        """
        global CONFIGURATION_PATH
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        indent = '    '

        containers_dict = {}
        chemicals_dict = {}
        start_nodes = []
        links = [[int(i) for i in dpg.get_item_label(link).replace('link_', '').split('-')] for link in dpg.get_item_children(active_ne)[0]]

        for node in dpg.get_item_children(active_ne)[1]:
            if dpg.get_item_label(node) == 'Chemical':
                tmp_params = {dpg.get_item_label(dpg.get_item_children(i)[1][0]).replace(' ', '_').lower(): dpg.get_value(dpg.get_item_children(i)[1][0]) for i in dpg.get_item_children(node)[1] if dpg.get_item_label(i) != 'node_attribute_output' and dpg.get_item_label(i) != 'node_attribute_collapse button'}
                var_name = f'chemical_{_make_valid_variable_name(tmp_params["name"])}'
                tmp_list = list(chemicals_dict.values())
                tmp_list.reverse()
                for i in tmp_list:
                    if i[0].startswith(var_name):
                        if i[0].split('_')[-1].isdigit():
                            var_name += f'_{int(i[0].split("_")[-1]) + 1}'
                        else:
                            var_name += '_1'
                        break
                p = ", ".join([f'{k}={_format_param(k, v)}' for k, v in tmp_params.items()])
                chemicals_dict[node] = (var_name, f'Chemical({p})', tmp_params['name'])
            elif dpg.get_item_label(node) == 'Container':
                tmp_params = {dpg.get_item_label(dpg.get_item_children(i)[1][0]).replace(' ', '_').lower(): dpg.get_value(dpg.get_item_children(i)[1][0]) for i in dpg.get_item_children(node)[1] if dpg.get_item_label(i) != 'node_attribute_output' and dpg.get_item_label(i) != 'node_attribute_collapse button'}
                if tmp_params['name'] == '':
                    tmp_params['name'] = f'unknown_container_{node}'
                var_name = _make_valid_variable_name(tmp_params['name'])
                p = ", ".join([f'{k}={_format_param(k, v)}' for k, v in tmp_params.items()])
                containers_dict[node] = (var_name, f'Container({p})', tmp_params['name'])

        for k in list(chemicals_dict.keys()):
            for link in links:
                if dpg.get_item_parent(link[1]) == k:
                    if dpg.get_item_label(dpg.get_item_parent(link[0])) == 'Container':
                        chemicals_dict[k] = (chemicals_dict[k][0], chemicals_dict[k][1].replace(f'container={containers_dict[dpg.get_item_parent(link[0])][2]}', f'container={containers_dict[dpg.get_item_parent(link[0])][0]}'), chemicals_dict[k][2])

        CONFIGURATION_PATH = filename.replace('.py', '.json')
        write_config_file(CONFIGURATION_PATH)

        cp = CONFIGURATION_PATH.replace('\\', '\\\\')
        fc = '# Automatically created with Minerva Node Editor\n'
        fc += 'import threading\n'
        fc += 'from Minerva import *\n\n'
        fc += "if __name__ == '__main__':\n"
        fc += f'{indent}Configuration.load_configuration("{cp}")\n\n'
        fc += f'{indent}# Containers\n'
        for i, j, _ in containers_dict.values():
            if f'{indent}{i} = ' in fc:
                continue
            fc += f'{indent}{i} = {j}\n'
        fc += f'\n{indent}# Chemicals\n'
        for i, j, _ in chemicals_dict.values():
            fc += f'{indent}{i} = {j}\n'

        # find start node
        for link in links:
            for node_id in containers_dict.keys():
                if node_id == dpg.get_item_parent(link[0]) and dpg.get_item_label(dpg.get_item_children(link[1])[1][0]) == 'Container' and dpg.get_item_label(dpg.get_item_parent(link[1])) != 'Chemical':
                    start_nodes.append(node_id)

        fc += f'\n{indent}# Reactions\n'
        for start_node_index, start_node in enumerate(start_nodes):
            fc += f'{indent}def reaction_{start_node_index}():\n'
            for i in dpg.get_item_children(start_node)[1]:
                if dpg.get_item_label(i) == 'node_attribute_output':
                    output_node_id = i
                    break
            else:
                return

            node_outputs = find_linked_node_outputs(output_node_id, all_connections=False)[1:]

            for next_node_output in node_outputs:
                next_node = dpg.get_item_parent(next_node_output)
                tmp_method = dpg.get_item_label(dpg.get_item_parent(next_node_output)).replace(' ', '_').lower()
                tmp_params = {i: [dpg.get_item_label(dpg.get_item_children(i)[1][0]).replace(' ', '_').lower(), dpg.get_value(dpg.get_item_children(i)[1][0])] for i in dpg.get_item_children(next_node)[1] if dpg.get_item_label(i) != 'node_attribute_output' and dpg.get_item_label(i) != 'node_attribute_collapse button'}

                for k in list(tmp_params.keys()):
                    if dpg.get_item_label(next_node) != 'Chemical' and tmp_params[k][0] == 'container':
                        current_container_name = tmp_params.pop(k)[1]
                        break
                for i in containers_dict.values():
                    if i[2] == current_container_name:
                        current_container_var_name = i[0]

                for k in list(tmp_params.keys()):
                    for link in links:
                        if link[1] == k:
                            if dpg.get_item_label(dpg.get_item_parent(link[0])) == 'Chemical':
                                tmp = tmp_params[k][1].split(';')
                                for i in range(0, len(tmp)):
                                    for j in chemicals_dict.values():
                                        if tmp[i] == j[2]:
                                            tmp[i] = j[0]
                                        tmp_params[k] = [tmp_params[k][0], ';'.join(tmp)]
                            elif dpg.get_item_label(dpg.get_item_parent(link[0])) == 'Container':
                                if dpg.get_item_label(dpg.get_item_parent(link[1])) == 'Centrifuge':
                                    tmp_name = []
                                    for i in dpg.get_item_children(dpg.get_item_parent(link[1]))[1]:
                                        if dpg.get_item_label(i) == 'node_attribute_output':
                                            continue
                                        if 'Container' in dpg.get_item_label(dpg.get_item_children(i)[1][0]):
                                            tmp_name += [j.strip() for j in dpg.get_value(dpg.get_item_children(i)[1][0]).split(';')]
                                    tmp = tmp_params[k][1].split(';')
                                    for i in range(0, len(tmp)):
                                        for j in containers_dict.values():
                                            if tmp[i] == j[2]:
                                                tmp[i] = j[0]
                                            tmp_params[k] = [tmp_params[k][0], ';'.join(tmp)]
                                else:
                                    tmp_params[k] = [tmp_params[k][0], tmp_params[k][1].replace(containers_dict[dpg.get_item_parent(link[0])][2], containers_dict[dpg.get_item_parent(link[0])][0])]
                            elif dpg.get_item_label(dpg.get_item_parent(link[0])) == 'Centrifuge':
                                tmp_name = []
                                for i in dpg.get_item_children(dpg.get_item_parent(link[0]))[1]:
                                    if dpg.get_item_label(i) == 'node_attribute_output':
                                        continue
                                    if 'Container' in dpg.get_item_label(dpg.get_item_children(i)[1][0]):
                                        tmp_name += [j.strip() for j in dpg.get_value(dpg.get_item_children(i)[1][0]).split(';')]
                                tmp = tmp_params[k][1].split(',')
                                for i in range(0, len(tmp)):
                                    for j in containers_dict.values():
                                        if tmp[i].replace('[', '').replace(']', '').replace('(', '').replace(')', '').strip() == j[2]:
                                            tmp[i] = tmp[i].replace(j[2], j[0])
                                        tmp_params[k] = [tmp_params[k][0], ','.join(tmp)]
                            else:
                                tmp_name = ''
                                for i in dpg.get_item_children(dpg.get_item_parent(link[0]))[1]:
                                    if dpg.get_item_label(i) == 'node_attribute_output':
                                        continue
                                    if dpg.get_item_label(dpg.get_item_children(i)[1][0]) == 'Container':
                                        tmp_name = dpg.get_value(dpg.get_item_children(i)[1][0])
                                        break
                                for i in containers_dict.values():
                                    if tmp_name == i[2]:
                                        tmp_params[k] = [tmp_params[k][0], tmp_params[k][1].replace(i[2], i[0])]

                p = ", ".join([f'{v[0]}={_format_param(v[0], v[1])}' for v in tmp_params.values()])
                fc += f'{indent}{indent}{current_container_var_name}.{tmp_method}({p})\n'

            fc += '\n\n'

        fc += f'{indent}# Start reactions in individual threads\n'

        for i in range(0, len(start_nodes)):
            fc += f'{indent}reaction_thread_{i} = threading.Thread(target=reaction_{i})\n'
            fc += f'{indent}reaction_thread_{i}.start()\n'

        fc += f'\n{indent}# Wait for all threads to finish\n'

        for i in range(0, len(start_nodes)):
            fc += f'{indent}reaction_thread_{i}.join()\n'

        with open(filename, 'w') as f:
            f.write(fc)

    def write_config_file(filename: str)->None:
        """
        Method for saving the current hardware node setup as a hardware configuration file.

        Parameters:
            filename (str): The filename of the configuration file

        Returns:
            None
        """
        fc = {'NameMappings': {}, 'ControllerHardware': {}, 'Hotplates': {}, 'AdditionHardware':{}, 'Centrifuges': {}, 'RobotArms': {}, 'SampleHolder': {}, 'Sonicators': {}, 'OtherHardware': {}, 'Containers': {}, 'Chemicals': {}}
        links = [[int(i) for i in dpg.get_item_label(link).replace('link_', '').split('-')] for link in dpg.get_item_children(ne_configuration)[0]]

        for node in dpg.get_item_children(ne_configuration)[1]:
            if 'Minerva.API.' in str(dpg.get_item_user_data(node)):
                hardware_type = str(dpg.get_item_user_data(node)).split('.')[3]
            elif 'Minerva.Hardware.' in str(dpg.get_item_user_data(node)):
                hardware_type = str(dpg.get_item_user_data(node)).split('.')[2]
            else:
                hardware_type = str(dpg.get_item_user_data(node)).split('.')[1]
            hardware_type = hardware_type.replace('<class ', '')
            if "'>" in hardware_type:
                hardware_type = hardware_type[:hardware_type.find("'>")]
            if hardware_type == 'Chemical' or hardware_type == 'Container':
                hardware_type += 's'
            hardware_id = f'{dpg.get_item_user_data(node)}-{node}'
            fc[hardware_type][hardware_id] = {}
            if hardware_type == 'AdditionHardware' and 'WPI' not in str(dpg.get_item_user_data(node)):
                fc[hardware_type][hardware_id]['configuration'] = {}

            for attribute in dpg.get_item_children(node)[1]:
                if len(dpg.get_item_children(attribute)[1]) == 0:
                    continue
                field = dpg.get_item_children(attribute)[1][0]
                if dpg.get_item_label(field) == 'Name':
                    fc['NameMappings'][hardware_id] = dpg.get_value(field)
                elif dpg.get_item_label(field) != 'v' and dpg.get_item_label(field) != '^' and dpg.get_item_label(field) != '':
                    for link in links:
                        if link[1] == attribute:
                            val = f'{dpg.get_item_user_data(dpg.get_item_parent(link[0]))}-{dpg.get_item_parent(link[0])}'
                            break
                    else:
                        val = dpg.get_value(field)
                    if val == 'None':
                        val = None
                    if hardware_type == 'AdditionHardware' and 'Slot ' in dpg.get_item_label(field):
                        fc[hardware_type][hardware_id]['configuration'][dpg.get_item_label(field).replace('Slot ', '')] = val
                    elif hardware_type == 'SampleHolder' and dpg.get_item_label(field) == 'Hardware Definition':
                        for i in Minerva.SampleHolderDefinitions:
                            if val.replace('SampleHolder.', '') == str(i):
                                fc[hardware_type][hardware_id][dpg.get_item_label(field).lower().replace(' ', '_')] = json.load(open(i.value))
                                break
                    else:
                        fc[hardware_type][hardware_id][dpg.get_item_label(field).lower().replace(' ', '_')] = val

        if filename is not None:
            with open(filename, 'w') as f:
                json.dump(fc, f, indent=4)

        return fc

    def create_from_nlp()->None:
        """
        Method for creating a node setup from natural language.

        Returns:
            None
        """
        dpg.configure_item("right_click_menu_reaction", show=False)
        dpg.configure_item("right_click_menu_configuration", show=False)
        dpg.configure_item("nlp_input", show=True, user_data='load')

    def nlp()->None:
        """
        Run natural language processing on the text in the textfield to create a node setup.

        Returns:
            None
        """
        ag = create_actiongraph(dpg.get_value('nlp_input_text_id'), f"bruehle/{dpg.get_value('nlp_input_model_id')}")
        parse_actiongraph(ag)
        arrange_nodes()
        dpg.configure_item("nlp_input", show=False)

    def create_actiongraph(rawtext: str, model_id: str)->str:
        """
        Use natural language processing for creating an action graph from synthesis procedures in natural language

        Parameters:
            rawtext (str): The raw text of the synthesis procedure
            rawtext (str): The raw text of the synthesis procedure
            model_id (str): The name or path of the LLM model that is used

        Returns:
            str: The action graph that was constructed from the raw text
        """
        global PIPE

        rawtext = rawtext.replace('( ', '(').replace(' )', ')').replace('[ ', '[').replace(' ]', ']').replace(' . ', '. ').replace(' , ', ', ').replace(' : ', ': ').replace(' ; ', '; ').replace('\r', ' ').replace('\n', ' ').replace('\t', '').replace('  ', ' ')
        rawtext = rawtext.replace('μ', 'u').replace('μ', 'u').replace('× ', 'x').replace('×', 'x')
        for m in re.finditer(r'[0-9]x\s[0-9]', rawtext):
            rawtext = rawtext.replace(m.group(), m.group().strip())

        if PIPE is None:
            model = AutoModelForSeq2SeqLM.from_pretrained(model_id, device_map='auto')
            tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)

            PIPE = pipeline("text2text-generation", model=model, tokenizer=tokenizer)

        return PIPE(rawtext, max_new_tokens=512, do_sample=False, temperature=None, top_p=None)[0]['generated_text']

    def execute()->None:
        """
        Directly executes the currently loaded node setup.

        Returns:
            None
        """
        global CONFIGURATION_PATH

        filename = f'./tmp_{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")}'
        CONFIGURATION_PATH = f'{filename}.json'
        write_config_file(CONFIGURATION_PATH)
        write_python_file(f'{filename}.py')
        with open(f'{filename}.py') as f:
            c = f.read()

        code_obj = compile(c, os.path.splitext(os.path.basename(f'{filename}.py'))[0], 'exec')
        exec(code_obj)

    def switch_view(sender: Union[int, str], app_data: Any, user_data: Any)->None:
        """
        The callback function that gets triggered when the user switches the view between the Configuration Editor and the Reaction Editor.

        Args:
            sender (Union[int, str]): The tag of the item that triggered the callback, or 0 if triggered by the application
            app_data (Any): Additional information for the callback, i.e., the current value of most basic widgets
            user_data (Any): Any additional user data associated with the item

        Returns:
            None
        """
        if 'Configuration Editor' in dpg.get_item_label(sender):
            dpg.set_primary_window(wi_reaction, False)
            dpg.configure_item(ne_reaction, show=False)
            dpg.configure_item(wi_reaction, show=False)
            dpg.configure_item(mi_reaction, label=u'    Reaction Editor')
            dpg.set_primary_window(wi_configuration, True)
            dpg.configure_item(ne_configuration, show=True)
            dpg.configure_item(wi_configuration, show=True)
            dpg.set_value(mi_configuration, True)
            dpg.configure_item(mi_configuration, label=u'\u2713 Configuration Editor')
            _update_current_config(None, None, None)
        elif 'Reaction Editor' in dpg.get_item_label(sender):
            dpg.set_primary_window(wi_configuration, False)
            dpg.configure_item(ne_configuration, show=False)
            dpg.configure_item(wi_configuration, show=False)
            dpg.configure_item(mi_configuration, label=u'    Configuration Editor')
            dpg.set_primary_window(wi_reaction, True)
            dpg.configure_item(ne_reaction, show=True)
            dpg.configure_item(wi_reaction, show=True)
            dpg.configure_item(mi_reaction, label=u'\u2713 Reaction Editor')

    def add_texture(texture_registry: Union[int, str], image_path: str, target_width: int=ORIGINAL_WIDTH * ZOOM_FACTOR)->Union[int, str]:
        """
        Adds an image to the specified texture registry.

        Parameters:
            texture_registry (Union[int, str]): The ID of the texture registry
            image_path (str): The path to the image file that should be added to the texture registry
            target_width (int=ORIGINAL_WIDTH * ZOOM_FACTOR): The size of the image. Defaults to ORIGINAL_WIDTH * ZOOM_FACTOR

        Returns:
            Union[int, str]: The ID of the added texture
        """
        image = PIL.Image.open(image_path)
        image.putalpha(255)
        image = image.resize((int(target_width / image.width * image.width), int(target_width / image.width * image.height)))
        return dpg.add_static_texture(parent=texture_registry, width=image.width, height=image.height, default_value=np.frombuffer(image.tobytes(), dtype=np.uint8) / 255.0, tag=os.path.splitext(os.path.basename(image_path))[0])

    def arrange_nodes()->None:
        """
        Automatically arrange the nodes in the Reaction Editor in a grid pattern

        Returns:
            None
        """
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration
            raise NotImplementedError

        start_nodes = []
        links = [[int(i) for i in dpg.get_item_label(link).replace('link_', '').split('-')] for link in dpg.get_item_children(active_ne)[0]]
        row_offset = 0
        XSPACING = 100
        YSPACING = 10

        for node in dpg.get_item_children(active_ne)[1]:
            if dpg.get_item_label(node) == 'Container':
                # find start node
                for link in links:
                    if node == dpg.get_item_parent(link[0]) and dpg.get_item_label(dpg.get_item_children(link[1])[1][0]) == 'Container' and dpg.get_item_label(dpg.get_item_parent(link[1])) != 'Chemical':
                        start_nodes.append(node)

        for start_node_index, start_node in enumerate(start_nodes):
            node_grid = []  # [[node_id, row, col], ...]

            for i in dpg.get_item_children(start_node)[1]:
                if dpg.get_item_label(i) == 'node_attribute_output':
                    output_node_id = i
                    break
            else:
                return

            node_grid.append([start_node, 0, 0])
            col = 0

            node_outputs = find_linked_node_outputs(output_node_id, all_connections=False)[1:]

            for next_node_output in node_outputs:
                left_nodes = find_left_nodes(dpg.get_item_parent(next_node_output))
                cols = [i[2] for i in node_grid if i[0] in left_nodes]
                if len(cols) > 0:
                    col = max(cols)

                col += 1

                rows = [i[1] for i in node_grid if i[2]==col]
                if len(rows) == 0:
                    row = -1
                else:
                    row = max(rows)
                row += 1

                if not any([i[0]==dpg.get_item_parent(next_node_output) for i in node_grid]):
                    node_grid.append([dpg.get_item_parent(next_node_output), row, col])
                left_nodes = [i for i in left_nodes if i not in np.array(node_grid)[:, 0]]

                next_left_nodes = []
                col2 = col
                while len(left_nodes) > 0:
                    col2 -= 1
                    for j in left_nodes:
                        next_left_nodes += find_left_nodes(j)
                        rows = [i[1] for i in node_grid if i[2]==col2]
                        if len(rows) == 0:
                            row = -1
                        else:
                            row = max(rows)
                        if not any([i[0]==j for i in node_grid]):
                            node_grid.append([j, row + 1, col2])

                    left_nodes = [i for i in next_left_nodes if i not in np.array(node_grid)[:, 0]]

            node_grid.sort(key=lambda x: (x[2], x[1]))  # sort by columns, then by rows
            current_column = node_grid[0][2]
            current_offset_x = 0
            current_offset_y = row_offset
            max_width = 0
            max_height = 0

            for node in node_grid:
                if current_column != node[2]:
                    current_column = node[2]
                    current_offset_x += max_width + XSPACING
                    current_offset_y = row_offset
                    max_width = 0

                w, h = dpg.get_item_rect_size(node[0])
                dpg.configure_item(node[0], pos=(current_offset_x, current_offset_y))
                current_offset_y += h + YSPACING
                max_width = max(max_width, w)
                max_height = max(max_height, current_offset_y)

            row_offset = max_height + 200

    def cleanup_string(s: str)->str:
        """
        Replaces some common non-ASCII characters in synthesis procedures with ASCII counterparts (done before running them through the LLM model for generating action graphs).

        Parameters:
            s (str): The string for cleanup

        Returns:
            str: The cleaned-up string

        """
        return s.replace('\r', '').replace('\n', '').replace('°C.', '°C').replace('µ', 'u').replace('μ', 'u').replace('×', 'x').replace('  ', ' ').strip()

    def _parse_parameters(s: str)->str:
        """
        Helper function to parse the actions and parameters from an action graph.

        Parameters:
            s (str): The string from the action graph for parsing

        Returns:
            str: The action and associated parameters
        """
        global WARNING_MSG

        inp = [i.replace('<nbsp>', ' ') for i in s.strip().replace('room temperature', 'room<nbsp>temperature').replace('over night', 'over<nbsp>night').split(' ')]

        if inp[0] in ('YIELD', 'DEGASS', 'SYNTHESIZE', 'APPARATUSACTION'):
            return [inp[0],]
        elif inp[0] in ('ADD', 'PRECIPITATE', 'QUENCH'):
            inp[0] = 'ADD'
        elif inp[0] in ('DISSOLVE', ):
            inp[0] = 'DISSOLVE'
        elif inp[0] in ('EXTRACT', 'FILTER', 'PARTITION', 'DRY', 'REMOVE', 'RECOVER', 'CONCENTRATE'):
            inp[0] = 'CENTRIFUGE'
        elif inp[0] in ('PURIFY', 'WASH'):
            inp[0] = 'WASH'

        if len(inp) == 1:
            return [inp[0],]

        ret = []
        i = 1

        while i < len(inp):
            val = ''
            unit = ''
            try:
                val = float(inp[i])
                i += 1
                if i < len(inp):
                    unit = inp[i]
                    quantity = _try_parse_quantity(inp[0], f'{val} {unit}')
                    if quantity is not None:
                        ret.append(quantity)
                else:
                    msg = 'WARNING: Unit expected for value {val} in {inp[0]} step.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
            except ValueError:
                if inp[i].startswith('slow') or inp[i].startswith('gentl'):
                    current_value = 100
                    current_unit = 'rpm'
                    msg = f'WARNING: Inprecise Speed description found: {inp[i]}. Assuming {current_value} {current_unit}.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    ret.append(RotationSpeed.from_string(f'{current_value} {current_unit}'))
                elif inp[i].startswith('vigorous') or inp[i].startswith('quick') or inp[i].startswith('fast'):
                    current_value = 600
                    current_unit = 'rpm'
                    msg = f'WARNING: Inprecise Speed description found: {inp[i]}. Assuming {current_value} {current_unit}.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    ret.append(RotationSpeed.from_string(f'{current_value} {current_unit}'))
                elif inp[i].startswith('overnight') or inp[i].startswith('over night'):
                    current_value = 16
                    current_unit = 'h'
                    msg = f'WARNING: Inprecise Time description found: {inp[i]}. Assuming {current_value} {current_unit}.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    ret.append(Time.from_string(f'{current_value} {current_unit}'))
                elif inp[i].startswith('roomtemperature') or inp[i].startswith('room temperature') or inp[i].startswith('RT') or inp[i].startswith('R.T.'):
                    current_value = 25
                    current_unit = 'C'
                    msg = f'WARNING: Inprecise Temperature description found: {inp[i]}. Assuming {current_value} {current_unit}.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    ret.append(Temperature.from_string(f'{current_value} {current_unit}'))
                elif inp[i].startswith('boil') or inp[i].startswith('reflux'):
                    current_value = 100  # TODO: Implement lookup of boiling point
                    current_unit = 'C'
                    msg = f'WARNING: Inprecise Temperature description found: {inp[i]}. Assuming {current_value} {current_unit}.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    ret.append(Temperature.from_string(f'{current_value} {current_unit}'))
                else:
                    if len(ret) > 0 and isinstance(ret[-1], str):
                        ret[-1] += f' {inp[i]}'
                    else:
                        ret.append(inp[i])
            i += 1

        return [inp[0]] + ret

    def _try_parse_quantity(current_action: str, quantity_string: str)->Optional[Minerva.API.HelperClassDefinitions.Quantity]:
        """
        Helper function for creating Quantities from their string representations.

        Parameters:
            current_action (str): The string describing the current action
            quantity_string (str): The string describing the quantity

        Returns:
            Optional[Minerva.API.HelperClassDefinitions.Quantity]: An instance of the appropriate Quantity subclass representing the supplied string value
        """
        global WARNING_MSG

        current_quantity = None
        if current_action in ('ADD', 'DISSOLVE'):
            for quantity in (Volume, Mass, MolarAmount, Concentration, MassConcentration):
                try:
                    current_quantity = quantity.from_string(quantity_string)
                    break
                except AssertionError:
                    pass  # Try to parse it as the next type of Quantity

            if current_quantity is None:
                msg = f'WARNING: Expected a Volume, Mass, Molar Amount, Concentration, or Mass Concentration as parameter a {current_action} step, but found {quantity_string}.'
                logger.warning(msg)
                WARNING_MSG += msg + '\n'

        elif current_action in ('HEAT', 'COOL', 'STIR', 'WAIT'):
            for quantity in (Temperature, Time, RotationSpeed):
                try:
                    current_quantity = quantity.from_string(quantity_string)
                    break
                except AssertionError:
                    pass  # Try to parse it as the next type of Quantity

            if current_quantity is None:
                msg = f'WARNING: Expected a Temperature, Time, or Rotation Speed as parameter a {current_action} step, but found {quantity_string}.'
                logger.warning(msg)
                WARNING_MSG += msg + '\n'

        elif current_action in ('CENTRIFUGE', 'WASH'):
            for quantity in (Temperature, Time, RotationSpeed, Volume):
                try:
                    current_quantity = quantity.from_string(quantity_string)
                    break
                except AssertionError:
                    pass  # Try to parse it as the next type of Quantity

            if current_quantity is None:
                msg = f'WARNING: Expected a Volume, Temperature, Time, or Rotation Speed as parameter a {current_action} step, but found {quantity_string}.'
                logger.warning(msg)
                WARNING_MSG += msg + '\n'

        return current_quantity


    def parse_actiongraph(ag: str)->None:
        """
        Parse an Action Graph and create the corresponding node graph

        Parameters:
            ag (str): The string representation of the action graph

        Returns:
            None
        """
        global WARNING_MSG

        WARNING_MSG = ''
        # split at tokens
        ag = cleanup_string(ag).replace('°','').replace('>','').split('<')[1:]
        seq = []
        for step in ag:
            seq.append(_parse_parameters(step))

        # Zeroth pass: Take care of REPEAT steps
        i = 0
        actions = []
        while i < len(seq):
            s = seq[i]
            if s[0] == 'REPEAT' and i > 0:
                if len(s) < 2:
                    repeats = 1
                else:
                    for j in s:
                        if j.replace('x', '').strip().isnumeric():
                            repeats = int(j.replace('x', '').strip())
                            break
                    else:
                        repeats = 1
                for _ in range(0, repeats):
                    actions.append(seq[i-1])
            else:
                actions.append(s)
            i += 1
        seq = actions

        for i in seq:
            logger.debug('; '.join([str(j) for j in i]))
        logger.debug('-'*30)

        # First pass: Consolidate and expand steps
        actions = []
        i = 0
        while i < len(seq):
            s = seq[i]
            if s[0] in ('YIELD', 'DEGASS', 'SYNTHESIZE', 'APPARATUSACTION', 'ADJUSTPH'):
                msg = f'WARNING: skipping unsupported step: {s[0]}'
                logger.warning(msg)
                WARNING_MSG += msg + '\n'
                i += 1
                continue

            if len(actions) > 0 and s[0] == 'WAIT' and actions[-1][0] in ('HEAT', 'COOL', 'STIR', 'WAIT'):
                # consolidate heating/stirring-related steps steps if parameters don't conflict
                for j in range(1, len(s)):
                    if any([type(j)==type(k) for k in actions[-1] if type(k) is not str]):
                        break
                else:
                    actions[-1] += s[1:]
                    i += 1
                    continue
            elif i+1 < len(seq) and s[0] == 'DISSOLVE' and (seq[i+1][0] != 'STIR'):
                msg = 'INFORMATION: Encountered a DISSOLVE step. Automatically expanding to an ADD and a STIR step (5 min at 400 rpm).'
                logger.warning(msg)
                WARNING_MSG += msg + '\n'
                s[0] == 'ADD'
                actions.append(s)
                actions.append(['STIR', Time.from_string('5 min'), RotationSpeed.from_string('400 rpm')])
                i += 1
                continue
            elif i+1 < len(seq) and s[0] == 'CENTRIFUGE' and (seq[i+1][0] in ('WASH', 'PURIFY')):
                # consolidate centrifugation-related steps steps if parameters don't conflict
                for j in range(1, len(s)):
                    if any([type(j)==type(k) for k in actions[-1] if type(k) is not str]):
                        break
                else:
                    actions[-1][0] = 'WASH'
                    actions[-1] += s[1:]
                    i += 1
                    continue
            elif len(actions) > 0 and s[0] == actions[-1][0]:
                # consolidate steps if parameters don't conflict
                for j in s:
                    if any([type(j)==type(k) for k in actions[-1] if type(k) is not str]):
                        break
                else:
                    actions[-1] += s[1:]
                    i += 1
                    continue
            actions.append(s)
            i += 1
        for i in seq:
            logger.debug('; '.join([str(j) for j in i]))
        logger.debug('-'*30)

        # Second pass: chek if necessary parameters are present
        seq = []
        i = 0
        while i < len(actions):
            s = actions[i]
            tmp = [s[0],]

            if s[0] in ('ADD', 'DISSOLVE', 'PRECIPITATE', 'QUENCH'):
                if len(s) < 2:
                    msg = f'WARNING: No parameters found for {s[0]} step. Skipping this step!'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    i += 1
                    continue
                j = 1
                c = []
                while j < len(s):
                    if not isinstance(s[j], str):
                        msg = f'WARNING: {s[0]} step: Chemical name expected, but found {str(s[j])}.'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        k = j + 1
                        while k < len(s):
                            if isinstance(s[k], str):
                                break
                            msg = f'WARNING: {s[0]} step: Chemical name expected, but found {str(s[k])}.'
                            logger.warning(msg)
                            WARNING_MSG += msg + '\n'
                            k += 1
                        j = k
                        continue
                    else:
                        c.append(s[j])
                        k = j + 1
                        while k < len(s):
                            if isinstance(s[k], str):
                                break
                            c.append(s[k])
                            k += 1
                        if len(c) == 1:
                            msg = f'WARNING: {s[0]} step: No amount specified for chemical {c[0]}.'
                            logger.warning(msg)
                            WARNING_MSG += msg + '\n'
                        else:
                            tmp.append(c)
                        j = k
                        c = []
                        continue
            elif s[0] in ('HEAT', 'COOL', 'STIR', 'WAIT'):
                if len(s) < 2:
                    msg = f'WARNING: No parameters found for {s[0]} step. Using default parameters: 5 min, 300 rpm, 25 C.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    tmp += [Time.from_string('5 min'), Temperature.from_string('25 C'), RotationSpeed.from_string('300 rpm')]
                else:
                    if not any([isinstance(j, Time) for j in s]):
                        msg = f'WARNING: No time specified for {s[0]} step. Using default time: 5 min'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Time.from_string('5 min'))
                    if not any([isinstance(j, Temperature) for j in s]):
                        msg = f'WARNING: No temperature specified for {s[0]} step. Using default temperature: 25 C'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Temperature.from_string('25 C'))
                    if not any([isinstance(j, RotationSpeed) for j in s]):
                        msg = f'WARNING: No stirring speed specified for {s[0]} step. Using default stirring speed: 300 rpm'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(RotationSpeed.from_string('300 rpm'))
                    tmp += [j for j in s[1:]]
            elif s[0] in ('EXTRACT', 'FILTER', 'PARTITION', 'DRY', 'REMOVE', 'RECOVER', 'CONCENTRATE', 'CENTRIFUGE'):
                if len(s) < 2:
                    msg = f'WARNING: No parameters found for {s[0]} step. Using default parameters: 15 min, 8000 rpm, 25 C.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    tmp += [Time.from_string('15 min'), Temperature.from_string('25 C'), RotationSpeed.from_string('8000 rpm')]
                else:
                    if not any([isinstance(j, Time) for j in s]):
                        msg = f'WARNING: No time specified for {s[0]} step. Using default time: 15 min'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Time.from_string('15 min'))
                    if not any([isinstance(j, Temperature) for j in s]):
                        msg = f'WARNING: No temperature specified for {s[0]} step. Using default temperature: 25 C'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Temperature.from_string('25 C'))
                    if not any([isinstance(j, RotationSpeed) for j in s]):
                        msg = f'WARNING: No centrifugation speed specified for {s[0]} step. Using default centrifugation speed: 8000 rpm'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(RotationSpeed.from_string('8000 rpm'))
                    tmp += [j for j in s[1:]]
            elif s[0] in ('SONICATE',):
                if len(s) < 2:
                    msg = f'WARNING: No parameters found for {s[0]} step. Using default parameters: 10 min.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    tmp += [Time.from_string('10 min')]
                else:
                    if not any([isinstance(j, Time) for j in s]):
                        msg = f'WARNING: No time specified for {s[0]} step. Using default time: 10 min'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Time.from_string('10 min'))
                    tmp += [j for j in s[1:]]
            elif s[0] in ('PURIFY', 'WASH'):
                if len(s) < 2:
                    msg = f'WARNING: No parameters and chemicals found for {s[0]} step. Using centrifugation only with default parameters: 15 min, 8000 rpm, 25 C.'
                    logger.warning(msg)
                    WARNING_MSG += msg + '\n'
                    tmp[0] = 'CENTRIFUGE'
                    tmp += [Time.from_string('15 min'), Temperature.from_string('25 C'), RotationSpeed.from_string('8000 rpm')]
                else:
                    if not any([isinstance(j, Time) for j in s]):
                        msg = f'WARNING: No time specified for {s[0]} step. Using default time: 15 min'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Time.from_string('15 min'))
                    if not any([isinstance(j, Temperature) for j in s]):
                        msg = f'WARNING: No temperature specified for {s[0]} step. Using default temperature: 25 C'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(Temperature.from_string('25 C'))
                    if not any([isinstance(j, RotationSpeed) for j in s]):
                        msg = f'WARNING: No centrifugation speed specified for {s[0]} step. Using default centrifugation speed: 8000 rpm'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp.append(RotationSpeed.from_string('8000 rpm'))
                    if not any([isinstance(j, str) for j in s]):
                        msg = f'WARNING: No chemicals found for {s[0]} step. Using centrifugation only.'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp[0] = 'CENTRIFUGE'
                        tmp.append(j for j in s[1:])
                    else:
                        j = 1
                        c = []
                        while j < len(s):
                            if isinstance(s[j], Time) or isinstance(s[j], Temperature) or isinstance(s[j], RotationSpeed):
                                tmp.append(s[j])
                                j += 1
                                continue
                            if not isinstance(s[j], str):
                                msg = f'WARNING: {s[0]} step: Chemical name expected, but found {str(s[j])}.'
                                logger.warning(msg)
                                WARNING_MSG += msg + '\n'
                                k = j + 1
                                while k < len(s):
                                    if isinstance(s[k], str):
                                        break
                                    msg = f'WARNING: {s[0]} step: Chemical name expected, but found {str(s[k])}.'
                                    logger.warning(msg)
                                    WARNING_MSG += msg + '\n'
                                    k += 1
                                j = k
                                continue
                            else:
                                c.append(s[j])
                                k = j + 1
                                while k < len(s):
                                    if isinstance(s[k], str):
                                        break
                                    c.append(s[k])
                                    k += 1
                                if len(c) == 1:
                                    msg = f'WARNING: {s[0]} step: No amount specified for chemical {c[0]}.'
                                    logger.warning(msg)
                                    WARNING_MSG += msg + '\n'
                                else:
                                    tmp.append(c)
                                j = k
                                c = []
                                continue

                    if not any([isinstance(j, list) for j in tmp]):
                        msg = f'WARNING: No chemicals found for {s[0]} step. Using centrifugation only.'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                        tmp[0] = 'CENTRIFUGE'

            seq.append(tmp)
            i += 1

        logger.debug('-'*30)
        for i in seq:
            logger.debug('; '.join([str(j) for j in i]))

        # Third pass: Final clean up
        actions = []
        i = 0
        while i < len(seq):
            s = seq[i]
            if i < len(seq)-2 and s[0] in ('HEAT', 'COOL', 'STIR') and seq[i+1][0] in ('ADD', 'DISSOLVE', 'PRECIPITATE', 'QUENCH') and s[0] in ('HEAT', 'COOL', 'STIR'):
                msg = 'INFORMATION: Encountered a HEAT step after an ADD step after a HEAT step. Automatically merging into HEAT and INFUSE_WHILE_HEATING steps.'
                logger.info(msg)
                WARNING_MSG += msg + '\n'
                actions.append(s)
                s = seq[i+2]
                s[0] = 'INFUSE_WHILE_HEATING'
                actions.append(s)
                actions[-1] += seq[i+1][1:]
                i += 3
                continue
            elif i < len(seq)-1 and s[0] in ('HEAT', 'COOL', 'STIR') and seq[i+1][0] in ('ADD', 'DISSOLVE', 'PRECIPITATE', 'QUENCH'):
                msg = 'INFORMATION: Encountered an ADD step after a HEAT step. Automatically merging into INFUSE_WHILE_HEATING step.'
                logger.info(msg)
                WARNING_MSG += msg + '\n'
                s[0] = 'INFUSE_WHILE_HEATING'
                actions.append(s)
                actions[-1] += seq[i+1][1:]
                i += 2
                continue
            else:
                actions.append(s)
                i += 1

        logger.debug('-'*30)
        for i in actions:
            logger.debug('; '.join([str(j) for j in i]))

        # Create the nodes
        switch_view(ne_reaction, None, None)
        created_nodes = [create_node_from_object(Minerva.Container, FIRST_NODE_POSITION), ]
        previous_node = created_nodes[-1]
        current_node = None
        for i in actions:
            if i[0] in ('DISSOLVE', 'ADD'):
                created_nodes.append(create_node_from_object(Minerva.Container.add_chemical, FIRST_NODE_POSITION))
                current_node = created_nodes[-1]
                nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
                for j in i[1:]:
                    created_nodes.append(create_node_from_object(Minerva.Chemical, FIRST_NODE_POSITION))
                    for k in j:
                        ind = _get_input_field_index(k, created_nodes[-1])
                        if ind is None:
                            msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                            logger.warning(msg)
                            WARNING_MSG += msg + '\n'
                        else:
                            dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(k))
                    ind = _get_input_field_index('raw:chemical', current_node)
                    nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(created_nodes[-1])[1][-1], dpg.get_item_children(current_node)[1][ind]], None)
            elif i[0] in ('STIR', 'HEAT', 'COOL'):
                created_nodes.append(create_node_from_object(Minerva.Container.heat, FIRST_NODE_POSITION))
                for j in i[1:]:
                    ind = _get_input_field_index(j, created_nodes[-1])
                    if ind is None:
                        msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                    else:
                        dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(j))
                current_node = created_nodes[-1]
                nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
            elif i[0] in ('INFUSE_WHILE_HEATING'):
                created_nodes.append(create_node_from_object(Minerva.Container.infuse_while_heating, FIRST_NODE_POSITION))
                current_node = created_nodes[-1]
                nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
                for j in i[1:]:
                    if isinstance(j, list):
                        created_nodes.append(create_node_from_object(Minerva.Chemical, FIRST_NODE_POSITION))
                        for k in j:
                            ind = _get_input_field_index(k, created_nodes[-1])
                            if ind is None:
                                msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                                logger.warning(msg)
                                WARNING_MSG += msg + '\n'
                            else:
                                dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(k))
                        ind = _get_input_field_index('raw:chemical', current_node)
                        nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(created_nodes[-1])[1][-1], dpg.get_item_children(current_node)[1][ind]], None)
                    elif isinstance(j, Time):
                        ind = _get_input_field_index(j, created_nodes[-1])
                        if ind is None:
                            msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                            logger.warning(msg)
                            WARNING_MSG += msg + '\n'
                        else:
                            dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(j))
                    else:
                        ind = _get_input_field_index(j, created_nodes[-1])
                        if ind is None:
                            msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                            logger.warning(msg)
                            WARNING_MSG += msg + '\n'
                        else:
                            dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(j))
            elif i[0] == 'SONICATE':
                created_nodes.append(create_node_from_object(Minerva.Container.sonicate, FIRST_NODE_POSITION))
                for j in i[1:]:
                    ind = _get_input_field_index(j, created_nodes[-1])
                    if ind is None:
                        msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                    else:
                        dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(j))
                current_node = created_nodes[-1]
                nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
            elif i[0] == 'CENTRIFUGE':
                created_nodes.append(create_node_from_object(Minerva.Container.centrifuge, FIRST_NODE_POSITION))
                for j in i[1:]:
                    ind = _get_input_field_index(j, created_nodes[-1])
                    if ind is None:
                        msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                        logger.warning(msg)
                        WARNING_MSG += msg + '\n'
                    else:
                        dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(j))
                current_node = created_nodes[-1]
                nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
            elif i[0] == 'WASH':
                chemicals = [j for j in i if isinstance(j, list)]
                for c in chemicals:
                    created_nodes.append(create_node_from_object(Minerva.Container.centrifuge, FIRST_NODE_POSITION))
                    for j in i[1:]:
                        if not isinstance(j, list):
                            ind = _get_input_field_index(j, created_nodes[-1])
                            if ind is None:
                                msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                                logger.warning(msg)
                                WARNING_MSG += msg + '\n'
                            else:
                                dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(j))
                    current_node = created_nodes[-1]
                    nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
                    previous_node = current_node

                    created_nodes.append(create_node_from_object(Minerva.Container.remove_supernatant_and_redisperse, FIRST_NODE_POSITION))
                    current_node = created_nodes[-1]
                    nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(previous_node)[1][-1], dpg.get_item_children(current_node)[1][1]], None)
                    previous_node = current_node

                    created_nodes.append(create_node_from_object(Minerva.Chemical, FIRST_NODE_POSITION))
                    for k in c:
                        ind = _get_input_field_index(k, created_nodes[-1])
                        if ind is None:
                            msg = f'WARNING: Skipping unsupported parameter {j} for step {i[0]}.'
                            logger.warning(msg)
                            WARNING_MSG += msg + '\n'
                        else:
                            dpg.set_value(dpg.get_item_children(dpg.get_item_children(created_nodes[-1])[1][ind])[1][0], str(k))
                    ind = _get_input_field_index('raw:chemical', current_node)
                    nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(created_nodes[-1])[1][-1], dpg.get_item_children(current_node)[1][ind]], None)
                    previous_node = current_node

            previous_node = current_node

        collapse_all(ne_reaction, None, None)
        dpg.set_primary_window(wi_reaction, True)
        arrange_nodes()
        if WARNING_MSG != '':
            ctypes.windll.user32.MessageBoxW(0, f'There were warnings while creating the node setup (see also console output for details):\n\n{WARNING_MSG}', "Minerva Node Editor - Warning", MB_ICONWARNING)

    def _get_input_field_index(inp:Union[str, Minerva.API.HelperClassDefinitions.Quantity], node: Union[int, str])->int:
        """
        Finds the index of a field on the given node that takes the specified input.

        Parameters:
            inp (Union[str, Minerva.API.HelperClassDefinitions.Quantity]): The input for which the index of the corresponding field should be returned
            node (Union[int, str]): The ID of the node

        Returns:
            int: The index of the field on the node for the specified input
        """
        if isinstance(inp, str):
            if inp.startswith('raw:'):
                inp = inp[4:]
            else:
                inp = 'name'
        elif isinstance(inp, Mass):
            inp = 'node_attribute_mass'
            exact_match = True
        elif isinstance(inp, Volume):
            inp = 'volume'
        elif isinstance(inp, Concentration):
            inp = 'node_attribute_concentration'
        elif isinstance(inp, MolarAmount):
            inp = 'molar amount'
        elif isinstance(inp, MassConcentration):
            inp = 'mass concentration'
        elif isinstance(inp, Temperature):
            inp = 'temperature'
        elif isinstance(inp, Time):
            inp = 'time'
        elif isinstance(inp, RotationSpeed):
            inp = 'speed'

        for i, j in enumerate(dpg.get_item_children(node)[1]):
            if inp in dpg.get_item_label(j):
                return i

    def write_knowledgegraph_file(filepath:str)->None:
        """
        Creates a knowledge graph from the node setup and saves it to the specified filepath as a csv file.

        Parameters:
            filepath (str): The file path where the generated knowledge graph is saved

        Returns
            None
        """
        kg = {'source': [], 'target': [], 'edge': []}
        if dpg.get_item_configuration(ne_reaction)['show']:
            active_ne = ne_reaction
        else:
            active_ne = ne_configuration

        used_node_types = []

        node_name_mappings = {}
        for node in dpg.get_item_children(active_ne)[1]:
            node_type = dpg.get_item_label(node)
            for c in dpg.get_item_children(node)[1]:
                if dpg.get_item_label(c) == 'node_attribute_name':
                    node_id = f'{node_type}-{dpg.get_value(dpg.get_item_children(c)[1][0])}'
                    if node_type == 'Chemical':
                        node_id = f'{node_id}-{node}'
                    break
            else:
                node_id = f'{node_type}-{node}'
            node_name_mappings[node] = node_id
            if node_type not in used_node_types:
                used_node_types.append(node_type)
                _get_call_parameter_types(node)

            for c in dpg.get_item_children(node)[1]:
                if dpg.get_item_label(c) != 'node_attribute_collapse button' and len(dpg.get_item_children(c)[1]) > 0:
                    kg['source'].append(node_id)
                    kg['target'].append(dpg.get_item_label(c)[len('node_attribute_'):])
                    kg['edge'].append('has_property')

                    kg['source'].append(f"{node_id}-{dpg.get_item_label(c)[len('node_attribute_'):]}")
                    kg['target'].append(dpg.get_value(dpg.get_item_children(c)[1][0]))
                    kg['edge'].append('has_value')

        for link in dpg.get_item_children(active_ne)[0]:
            tmp = [int(i) for i in dpg.get_item_label(link).replace('link_', '').split('-')]
            linked_nodes = [int(dpg.get_item_parent(tmp[0])), int(dpg.get_item_parent(tmp[1]))]
            linked_fields = [int(tmp[0]), int(tmp[1])]

            if dpg.get_item_label(linked_nodes[0]) == 'Container' and dpg.get_item_label(linked_nodes[1]) == 'Chemical':
                kg['source'].append(node_name_mappings[linked_nodes[0]])
                kg['target'].append(node_name_mappings[linked_nodes[1]])
                kg['edge'].append('contains_chemical')
                kg['source'].append(node_name_mappings[linked_nodes[1]])
                kg['target'].append(node_name_mappings[linked_nodes[0]])
                kg['edge'].append('is_contained_in')
            else:
                kg['source'].append(node_name_mappings[linked_nodes[0]])
                kg['target'].append(node_name_mappings[linked_nodes[1]])
                kg['edge'].append('is_used_by')
                kg['source'].append(node_name_mappings[linked_nodes[1]])
                kg['target'].append(node_name_mappings[linked_nodes[0]])
                kg['edge'].append('uses_material_from')

        for i in CALL_PARAMETER_ONTOLOGY:
            kg['source'].append(i[0])
            kg['edge'].append(i[1])
            kg['target'].append(i[2])

        with open(filepath, 'w') as f:
            f.write('source\ttarget\tedge\n')
            for i in range(0, len(kg['source'])):
                f.write(f"{kg['source'][i]}\t{kg['target'][i]}\t{kg['edge'][i]}\n")

    def _get_call_parameter_types(node: Union[int, str])->None:
        """
        Helper function for getting the types of the call parameters of a method.

        Parameters:
            node (Union[int, str]): The node associated with the method

        Returns
            None
        """
        obj = dpg.get_item_user_data(node)
        if dpg.get_item_label(node) in ('Chemical', 'Container'):
            _get_parameter_classes(obj.__init__)
        else:
            _get_parameter_classes(obj)

    def _get_class_hierarchy(cls: Any)->List[Any]:
        """
        Recursively get the class hierarchy for a given class.

        Parameters:
            cls (Any): The class for which the hierarchy should be retrieved

        Returns
            List[Any]: A list with the base classes
        """
        if cls is None:
            return []
        hierarchy = []
        while cls is not None:
            hierarchy.append(cls)
            cls = getattr(cls, '__base__', None)
        return hierarchy

    def _handle_generic_type(param_type:Any, param_name: str)->None:
        """
        Helper function that handles cases during parameter class lookup where the parameter type is a generic (e.g., Union, Optional, list, tuple).

        Parameters:
            param_type (Any): The type of the parameter
            param_name (str): The name of the parameter

        Returns:
            None
        """
        if isinstance(param_type, _GenericAlias) and param_type.__origin__ in (Union, list, tuple):
            # If it is a Union, List, or Tuple, iterate over its arguments
            for subtype in param_type.__args__:
                _handle_generic_type(subtype, param_name)
        else:
            if inspect.isclass(param_type):
                if param_name not in IGNORE_PARAMS and param_type.__name__ not in IGNORE_TYPES:
                    CALL_PARAMETER_ONTOLOGY.add((param_name, 'is_a', param_type.__name__))
            else:
                if param_name not in IGNORE_PARAMS and param_type not in IGNORE_TYPES:
                    CALL_PARAMETER_ONTOLOGY.add((param_name, 'is_a', param_type))

            if inspect.isclass(param_type):
                hierarchy = _get_class_hierarchy(param_type)
                for cls in hierarchy:
                    if param_name not in IGNORE_PARAMS and cls.__name__ not in IGNORE_TYPES:
                        CALL_PARAMETER_ONTOLOGY.add((param_name, 'is_a', cls.__name__))
                    _get_parameter_classes(cls.__init__)

    def _get_parameter_classes(method: Any)->None:
        """
        Get classes and their parent classes for all parameters of a given method.

        Parameters:
              method (Any): The method for which the parameter classes are looked up

        Returns:
            None
        """
        # Get type hints of the method parameters
        type_hints = get_type_hints(method)

        # Iterate through the type hints of the parameters
        for param_name, param_type in type_hints.items():
            _handle_generic_type(param_type, param_name)

    dpg.create_context()
    dpg.create_viewport(title='Minerva Node Editor', width=1800, height=1000, small_icon=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'icon.ico'), large_icon=os.path.join('hardware_images', 'icon.ico'))
    wi_reaction = dpg.add_window(label="Node Editor Window (Reaction)", tag="reaction_editor_window", width=1800 - 15, height=1000 - 40, show=True)
    ne_reaction = dpg.add_node_editor(parent=wi_reaction, label="Reaction Editor", tag="reaction_editor", callback=nodeeditor_link_cb, delink_callback=nodeeditor_unlink_cb, minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight)
    wi_configuration = dpg.add_window(label="Node Editor Window (Configuration)", tag="configuration_editor_window", width=1800 - 15, height=1000 - 40, show=False)
    ne_configuration = dpg.add_node_editor(parent=wi_configuration, label="Configuration Editor", tag="configuration_editor", callback=nodeeditor_link_cb, delink_callback=nodeeditor_unlink_cb, minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight, show=False)
    dpg.set_primary_window(wi_reaction, True)

    with dpg.font_registry():
        menu_font = dpg.add_font(os.path.join('C:\\', 'Windows', 'Fonts', 'seguisym.ttf'), 16)
        dpg.add_font_range(0x2700, 0x27BF, parent=menu_font)
        node_fonts = {i: dpg.add_font(os.path.join('C:\\', 'Windows', 'Fonts', 'calibri.ttf'), i) for i in range(1, 25)}

    with dpg.handler_registry(label='handlers'):
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Right, callback=right_click_cb, label='right_click_callback')
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=left_click_cb, label='left_click_callback')
        dpg.add_key_press_handler(key=dpg.mvKey_Delete, callback=del_keypress_cb, label='del_keypress_cb')
        dpg.add_key_press_handler(key=dpg.mvKey_LControl, callback=shortcut_keypress_cb, label='shortcut_keypress_cb')
        dpg.add_key_press_handler(key=dpg.mvKey_RControl, callback=shortcut_keypress_cb, label='shortcut_keypress_cb')
        dpg.add_mouse_wheel_handler(callback=zoom_callback, label='mousewheel_scroll_callback')
        dpg.add_mouse_move_handler(callback=mouse_move_callback, label='mouse_move_callback')

    with dpg.item_handler_registry(label="item_handler") as item_handler:
        dpg.add_item_deactivated_after_edit_handler(callback=item_cb)

    with dpg.texture_registry(label="textures") as texture_registry:
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'ot2.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'syringe_pump.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'vici_valve.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'chemputer_valve.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'capper_decapper.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'dht22.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'electromagnet.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'emergency_stop_button.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'esp32_camera.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'hotplate_clamp.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'hotplate_fan.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'dls.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'platereader.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'arduino.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'server.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'sample_holder.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'centrifuge.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'hotplate.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'robot_arm.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'bath_sonicator.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)
        add_texture(texture_registry=texture_registry, image_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'hardware_images', 'probe_sonicator.bmp'), target_width=ORIGINAL_WIDTH * ZOOM_FACTOR)

    with dpg.window(label="Right click window reaction", modal=False, show=False, tag="right_click_menu_reaction", no_title_bar=True):
        dpg.add_text("Containers & Chemicals")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Container", width=POPUP_MENU_WIDTH, callback=add_container_node)
            dpg.add_button(label="Chemical", width=POPUP_MENU_WIDTH, callback=add_chemical_node)
        dpg.add_text("Synthesis Actions")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Add Chemical", width=POPUP_MENU_WIDTH, callback=add_addition_node)
            dpg.add_button(label="Heat", width=POPUP_MENU_WIDTH, callback=add_heat_node)
            dpg.add_button(label="Infuse While Heating", width=POPUP_MENU_WIDTH, callback=add_infuse_while_heating_node)
        dpg.add_text("Handling & Purification")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Redisperse", width=POPUP_MENU_WIDTH, callback=add_redisperse_node)
            dpg.add_button(label="Sonicate", width=POPUP_MENU_WIDTH, callback=add_sonication_node)
            dpg.add_button(label="Centrifuge", width=POPUP_MENU_WIDTH, callback=add_centrifuge_node)
            dpg.add_button(label="Transfer Content", width=POPUP_MENU_WIDTH, callback=add_transfer_content_node)
        dpg.add_text("Characterization")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Measure DLS", width=POPUP_MENU_WIDTH, callback=add_measure_dls_node)
            # dpg.add_button(label="Measure Plate", width=POPUP_MENU_WIDTH, callback=add_measure_platereader_node)  # TODO: Implement platereader measurement

    with dpg.window(label="Right click window configuration", modal=False, show=False, tag="right_click_menu_configuration", no_title_bar=True):
        dpg.add_text("Containers & Chemicals")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Container", width=POPUP_MENU_WIDTH, callback=add_container_node)
            dpg.add_button(label="Chemical", width=POPUP_MENU_WIDTH, callback=add_chemical_node)
        dpg.add_text("Addition Hardware")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Pipetting Robot", width=POPUP_MENU_WIDTH, callback=add_pipetting_robot_hardware_image_node)
            dpg.add_button(label="Syringe Pump", width=POPUP_MENU_WIDTH, callback=add_syringe_pump_hardware_image_node)
            dpg.add_button(label="Valve (Vici)", width=POPUP_MENU_WIDTH, callback=add_vici_valve_hardware_image_node)
            dpg.add_button(label="Valve (Chemputer)", width=POPUP_MENU_WIDTH, callback=add_chemputer_valve_hardware_image_node)
        dpg.add_text("Auxiliary Hardware")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Capper/Decapper", width=POPUP_MENU_WIDTH, callback=add_capper_decapper_hardware_image_node)
            dpg.add_button(label="DHT22 Sensor", width=POPUP_MENU_WIDTH, callback=add_dht22_hardware_image_node)
            dpg.add_button(label="Electromagnet", width=POPUP_MENU_WIDTH, callback=add_electromagnet_hardware_image_node)
            dpg.add_button(label="Emergency Stop Button", width=POPUP_MENU_WIDTH, callback=add_emergency_stop_button_hardware_image_node)
            dpg.add_button(label="ESP32 Camera", width=POPUP_MENU_WIDTH, callback=add_esp32_camera_hardware_image_node)
            dpg.add_button(label="Hotplate Clamp", width=POPUP_MENU_WIDTH, callback=add_hotplate_clamp_hardware_image_node)
            dpg.add_button(label="Hotplate Fan", width=POPUP_MENU_WIDTH, callback=add_hotplate_fan_hardware_image_node)
        dpg.add_text("Characterization Hardware")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="DLS/Zeta", width=POPUP_MENU_WIDTH, callback=add_dls_hardware_image_node)
            dpg.add_button(label="Platereader", width=POPUP_MENU_WIDTH, callback=add_platereader_hardware_image_node)
        dpg.add_text("Controller Hardware")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Arduino Controller", width=POPUP_MENU_WIDTH, callback=add_arduino_controller_hardware_image_node)
            dpg.add_button(label="Server Controller", width=POPUP_MENU_WIDTH, callback=add_server_controller_hardware_image_node)
        dpg.add_text("Sample Holder Hardware")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Sample Holder", width=POPUP_MENU_WIDTH, callback=add_sample_holder_hardware_image_node)
        dpg.add_text("Synthesis Hardware")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Centrifuge", width=POPUP_MENU_WIDTH, callback=add_centrifuge_hardware_image_node)
            dpg.add_button(label="Hotplate", width=POPUP_MENU_WIDTH, callback=add_hotplate_hardware_image_node)
            dpg.add_button(label="Robot Arm", width=POPUP_MENU_WIDTH, callback=add_robot_arm_hardware_image_node)
            dpg.add_button(label="Sonicator (Bath)", width=POPUP_MENU_WIDTH, callback=add_bath_sonicator_hardware_image_node)
            dpg.add_button(label="Sonicator (Probe)", width=POPUP_MENU_WIDTH, callback=add_probe_sonicator_hardware_image_node)
        dpg.add_text("Group Nodes")
        dpg.add_separator()
        with dpg.group(horizontal=False):
            dpg.add_button(label="Addition Hardware", width=POPUP_MENU_WIDTH, callback=add_addition_hardware_node)
            dpg.add_button(label="Addition Hardware Configuration", width=POPUP_MENU_WIDTH, callback=add_addition_hardware_config_node)
            dpg.add_button(label="Auxiliary Hardware", width=POPUP_MENU_WIDTH, callback=add_auxiliary_hardware_node)
            dpg.add_button(label="Characterization Hardware", width=POPUP_MENU_WIDTH, callback=add_characterization_hardware_node)
            dpg.add_button(label="Controller Hardware", width=POPUP_MENU_WIDTH, callback=add_controller_hardware_node)
            dpg.add_button(label="Sample Holder", width=POPUP_MENU_WIDTH, callback=add_sample_holder_hardware_node)
            dpg.add_button(label="Synthesis Hardware", width=POPUP_MENU_WIDTH, callback=add_synthesis_hardware_node)

    with dpg.viewport_menu_bar(label="Main Menu") as main_menu:
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="Open... (Ctrl+O)", callback=load)
            dpg.add_separator()
            dpg.add_menu_item(label="Save", callback=save)
            dpg.add_menu_item(label="Save As... (Ctrl+S)", callback=save_as)
            with dpg.menu(label="Export"):
                dpg.add_menu_item(label="Export As Python... (Ctrl+E)", callback=export_python)
                dpg.add_menu_item(label="Export As Configuration... (Ctrl+X)", callback=export_config)
                dpg.add_menu_item(label="Export As Knowledge Graph...", callback=export_knowledge_graph)
            dpg.add_separator()
            dpg.add_menu_item(label="Create from Natural Language...", callback=create_from_nlp)
            dpg.add_menu_item(label="Run Reaction", callback=execute)
            dpg.add_separator()
            dpg.add_menu_item(label="Quit", callback=lambda sender, app_data, user_data: dpg.stop_dearpygui())
            
        with dpg.menu(label="View"):
            dpg.add_menu_item(label="Collapse/Expand", callback=collapse_all)
            dpg.add_menu_item(label="Toggle Hardware Images", callback=toggle_images)
            dpg.add_separator()
            mi_reaction = dpg.add_menu_item(label=u"\u2713 Reaction Editor", callback=switch_view)
            mi_configuration = dpg.add_menu_item(label=u"    Configuration Editor", callback=switch_view)
            dpg.add_separator()
            dpg.add_menu_item(label="Arrange Nodes", callback=arrange_nodes)

        with dpg.menu(label="Nodes"):
            with dpg.menu(label="Reaction Nodes"):
                dpg.add_text("Containers & Chemicals")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Container", callback=add_container_node)
                    dpg.add_menu_item(label="Chemical", callback=add_chemical_node)
                dpg.add_text("\nSynthesis Actions")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Add Chemical", callback=add_addition_node)
                    dpg.add_menu_item(label="Heat", callback=add_heat_node)
                    dpg.add_menu_item(label="Infuse While Heating", callback=add_infuse_while_heating_node)
                dpg.add_text("\nHandling & Purification")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Redisperse", callback=add_redisperse_node)
                    dpg.add_menu_item(label="Sonicate", callback=add_sonication_node)
                    dpg.add_menu_item(label="Centrifuge", callback=add_centrifuge_node)
                    dpg.add_menu_item(label="Transfer Content", callback=add_transfer_content_node)
                dpg.add_text("\nCharacterization")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Measure DLS", callback=add_measure_dls_node)
                    # dpg.add_menu_item(label="Measure Plate", callback=add_measure_platereader_node)  # TODO: Implement platereader measurement
            with dpg.menu(label="Configuration Nodes"):
                dpg.add_text("Containers & Chemicals")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Container", callback=add_container_node)
                    dpg.add_menu_item(label="Chemical", callback=add_chemical_node)
                dpg.add_text("\nAddition Hardware")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Pipetting Robot", callback=add_pipetting_robot_hardware_image_node)
                    dpg.add_menu_item(label="Syringe Pump", callback=add_syringe_pump_hardware_image_node)
                    dpg.add_menu_item(label="Valve (Vici)", callback=add_vici_valve_hardware_image_node)
                    dpg.add_menu_item(label="Valve (Chemputer)", callback=add_chemputer_valve_hardware_image_node)
                dpg.add_text("\nAuxiliary Hardware")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Capper/Decapper", callback=add_capper_decapper_hardware_image_node)
                    dpg.add_menu_item(label="DHT22 Sensor", callback=add_dht22_hardware_image_node)
                    dpg.add_menu_item(label="Electromagnet", callback=add_electromagnet_hardware_image_node)
                    dpg.add_menu_item(label="Emergency Stop Button", callback=add_emergency_stop_button_hardware_image_node)
                    dpg.add_menu_item(label="ESP32 Camera", callback=add_esp32_camera_hardware_image_node)
                    dpg.add_menu_item(label="Hotplate Clamp", callback=add_hotplate_clamp_hardware_image_node)
                    dpg.add_menu_item(label="Hotplate Fan", callback=add_hotplate_fan_hardware_image_node)
                dpg.add_text("\nCharacterization Hardware")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="DLS/Zeta", callback=add_dls_hardware_image_node)
                    dpg.add_menu_item(label="Platereader", callback=add_platereader_hardware_image_node)
                dpg.add_text("\nController Hardware")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Arduino Controller", callback=add_arduino_controller_hardware_image_node)
                    dpg.add_menu_item(label="Server Controller", callback=add_server_controller_hardware_image_node)
                dpg.add_text("\nSample Holder Hardware")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Sample Holder", callback=add_sample_holder_hardware_image_node)
                dpg.add_text("\nSynthesis Hardware")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Centrifuge", callback=add_centrifuge_hardware_image_node)
                    dpg.add_menu_item(label="Hotplate", callback=add_hotplate_hardware_image_node)
                    dpg.add_menu_item(label="Robot Arm", callback=add_robot_arm_hardware_image_node)
                    dpg.add_menu_item(label="Sonicator (Bath)", callback=add_bath_sonicator_hardware_image_node)
                    dpg.add_menu_item(label="Sonicator (Probe)", callback=add_probe_sonicator_hardware_image_node)
                dpg.add_text("\nGroup Nodes")
                dpg.add_separator()
                with dpg.group(horizontal=False):
                    dpg.add_menu_item(label="Addition Hardware", callback=add_addition_hardware_node)
                    dpg.add_menu_item(label="Addition Hardware Configuration", callback=add_addition_hardware_config_node)
                    dpg.add_menu_item(label="Auxiliary Hardware", callback=add_auxiliary_hardware_node)
                    dpg.add_menu_item(label="Characterization Hardware", callback=add_characterization_hardware_node)
                    dpg.add_menu_item(label="Controller Hardware", callback=add_controller_hardware_node)
                    dpg.add_menu_item(label="Sample Holder", callback=add_sample_holder_hardware_node)
                    dpg.add_menu_item(label="Synthesis Hardware", callback=add_synthesis_hardware_node)

    with dpg.window(label="Natural Language Input", modal=True, show=False, tag="nlp_input"):
        dpg.add_text("Add the text below:")
        dpg.add_input_text(label='', tag='nlp_input_text_id', multiline=True, height=400, width=800)
        dpg.add_separator()
        dpg.add_combo(label='Select LLM Model', tag='nlp_input_model_id', items=('BigBirdPegasus_Llama', 'LED-Base-16384_Llama', 'BigBirdPegasus_Chemtagger', 'LED-Base-16384_Chemtagger'), default_value='BigBirdPegasus_Llama', callback=llm_model_selection_cb)
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=75, callback=nlp)
            dpg.add_button(label="Cancel", width=75, callback=lambda: dpg.configure_item("nlp_input", show=False))

    dpg.bind_item_font(mi_reaction, menu_font)
    dpg.bind_item_font(mi_configuration, menu_font)

    fdo = dpg.add_file_dialog(label="Choose File...", modal=True, directory_selector=False, show=False, callback=file_dialog_cb, width=700, height=400, tag="file_dialog_open", default_filename='')
    dpg.add_file_extension("Node Setup Files (*.conf *.rxn){.conf,.rxn}", parent=fdo)
    dpg.add_file_extension(".conf", parent=fdo, color=(0, 255, 0, 255), custom_text="[Configuration Node Setup]")
    dpg.add_file_extension(".rxn", parent=fdo, color=(255, 0, 0, 255), custom_text="[Reaction Node Setup]")
    dpg.add_file_extension(".*", parent=fdo, color=(255, 255, 255, 255), custom_text="[All Files]")

    fdsc = dpg.add_file_dialog(label="Choose File...", modal=True, directory_selector=False, show=False, callback=file_dialog_cb, width=700, height=400, tag="file_dialog_save_conf", default_path=Minerva.API.HelperClassDefinitions.PathNames.CONFIG_DIR.value, default_filename='Configuration')
    dpg.add_file_extension(".conf", parent=fdsc, color=(0, 255, 0, 255), custom_text="[Configuration Node Setup]")

    fdsr = dpg.add_file_dialog(label="Choose File...", modal=True, directory_selector=False, show=False, callback=file_dialog_cb, width=700, height=400, tag="file_dialog_save_rxn", default_path=Minerva.API.HelperClassDefinitions.PathNames.ROOT_DIR.value + '/Synthesis_Scripts', default_filename='Reaction')
    dpg.add_file_extension(".rxn", parent=fdsr, color=(255, 0, 0, 255), custom_text="[Reaction Node Setup]")

    fdsp = dpg.add_file_dialog(label="Choose File...", modal=True, directory_selector=False, show=False, callback=file_dialog_cb, width=700, height=400, tag="file_dialog_save_py", default_path=Minerva.API.HelperClassDefinitions.PathNames.ROOT_DIR.value + '/Synthesis_Scripts', default_filename='Reaction')
    dpg.add_file_extension(".py", parent=fdsp, color=(255, 255, 0, 255), custom_text="[Python File]")

    fdsj = dpg.add_file_dialog(label="Choose File...", modal=True, directory_selector=False, show=False, callback=file_dialog_cb, width=700, height=400, tag="file_dialog_save_json", default_path=Minerva.API.HelperClassDefinitions.PathNames.CONFIG_DIR.value, default_filename='Configuration')
    dpg.add_file_extension(".json", parent=fdsj, color=(0, 255, 255, 255), custom_text="[Minerva Configuration]")

    fdsk = dpg.add_file_dialog(label="Choose File...", modal=True, directory_selector=False, show=False, callback=file_dialog_cb, width=700, height=400, tag="file_dialog_save_kg", default_path=Minerva.API.HelperClassDefinitions.PathNames.ROOT_DIR.value + '/Synthesis_Scripts', default_filename='Knowledge_Graph')
    dpg.add_file_extension(".csv", parent=fdsk, color=(255, 0, 255, 255), custom_text="[Knowledge Graph]")

    with dpg.theme() as disabled_theme:
        with dpg.theme_component(dpg.mvInputText, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (0x3E, 0x3E, 0x3E))
    dpg.bind_theme(disabled_theme)

    with dpg.theme() as container_link_theme:
        with dpg.theme_component(dpg.mvNodeLink):
            dpg.add_theme_color(target=dpg.mvNodeCol_Link, value=(150, 150, 10), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_LinkHovered, value=(200, 200, 10), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as container_pin_theme:
        with dpg.theme_component(dpg.mvNodeAttribute):
            dpg.add_theme_color(target=dpg.mvNodeCol_Pin, value=(200, 200, 10), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_PinHovered, value=(255, 255, 20), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as chemical_pin_theme:
        with dpg.theme_component(dpg.mvNodeAttribute):
            dpg.add_theme_color(target=dpg.mvNodeCol_Pin, value=(220, 64, 10), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_PinHovered, value=(255, 128, 20), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as hardware_pin_theme:
        with dpg.theme_component(dpg.mvNodeAttribute):
            dpg.add_theme_color(target=dpg.mvNodeCol_Pin, value=(10, 200, 64), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_PinHovered, value=(20, 255, 128), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as other_pin_theme:
        with dpg.theme_component(dpg.mvNodeAttribute):
            dpg.add_theme_color(target=dpg.mvNodeCol_Pin, value=(10, 200, 200), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_PinHovered, value=(20, 255, 255), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as container_titlebar_theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBar, value=(96, 96, 10), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBarHovered, value=(128, 128, 20), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as chemical_titlebar_theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBar, value=(96, 32, 10), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBarHovered, value=(128, 64, 20), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as hardware_titlebar_theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBar, value=(10, 96, 32), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBarHovered, value=(20, 128, 64), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as characterization_titlebar_theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBar, value=(32, 10, 96), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBarHovered, value=(64, 20, 128), category=dpg.mvThemeCat_Nodes)

    with dpg.theme() as other_titlebar_theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBar, value=(10, 96, 96), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(target=dpg.mvNodeCol_TitleBarHovered, value=(20, 128, 128), category=dpg.mvThemeCat_Nodes)

    n1 = create_node_from_object(Minerva.Container, FIRST_NODE_POSITION)
    n2 = create_node_from_object(Minerva.Chemical, (400, 25))
    nodeeditor_link_cb(ne_reaction, [dpg.get_item_children(n1)[1][-1], dpg.get_item_children(n2)[1][1]], None)
    switch_view(ne_configuration, None, None)
    create_robot_arm_hardware_image_node(FIRST_NODE_POSITION, 'robot_arm')
    switch_view(ne_reaction, None, None)

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()
