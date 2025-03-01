#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import json
import os.path
import threading
import time
from ctypes import windll

import pyautogui
import pygetwindow
import win32clipboard
import win32com.client
import win32gui
import win32ui
import win32api
import win32con
import numpy as np
import serial

import sqlite3
import struct
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import logging
import os.path
import platform

from typing import Union, Iterable, TYPE_CHECKING, List, Tuple, cast, Any

from Minerva.API.HelperClassDefinitions import Hardware, HardwareTypeDefinitions, PathNames
from Minerva.Hardware.ControllerHardware import LocalPCServer, LocalPCClient

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


class ZetaSizer(Hardware):
    """
    Class for controlling the ZetaSizer by sending keystrokes/clicks to the ZS Xplorer software.

    Parameters
    ----------
    local_controller: Union[LocalPCServer, LocalPCClient, None] = None
        A local controller for network communication if the device is not directly connected to this machine. If set to None, it is assumed that the device is directly connected. Default is None.
    network_id: str = ''
        A unique identifier of the instrument on the server and client PC. Only has an effect if a local_controller is used. Default is '', which will result in an automatically chosen ID (however, it is up to the user to ensure that the IDs are unique and the same on the server and client PC).

    Raises
    ------
    TimeoutError
        If the ZetaSizer is not responding or the ZS Xplorer software is not running.
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, local_controller: Union[LocalPCServer, LocalPCClient, None] = None, network_id: str = '') -> None:
        """
        Constructor for the ZetaSizer Class for sending keystrokes/clicks to the ZS Xplorer software.

        Parameters
        ----------
        local_controller: Union[LocalPCServer, LocalPCClient, None] = None
            A local controller for network communication if the device is not directly connected to this machine. If set to None, it is assumed that the device is directly connected. Default is None.

        Raises
        ------
        TimeoutError
            If the ZetaSizer is not responding or the ZS Xplorer software is not running.
        """
        super().__init__(hardware_type=HardwareTypeDefinitions.CharacterizationInstrumentHardware)
        if int(platform.version().split('.')[2]) < 22621:  # Windows 10
            scaling_factor_y = 1.0
        else:  # Windows 11
            scaling_factor_y = 1154/1160

        self.check_connection_pixel_color = (56, 137, 83)
        self.check_measurement_pixel_color = (100, 185, 127)
        self.check_connection_pixel_coordinates = {'x': 1840, 'y': round(1110*scaling_factor_y)}
        self.measure_menu_coordinates = {'x': 200, 'y': round(50*scaling_factor_y)}
        self.open_sop_coordinates = {'x': 215, 'y': round(85*scaling_factor_y)}
        self.sop_name_textbox_coordinates = {'x': 400, 'y': round(700*scaling_factor_y)}
        self.sample_name_textbox_coordinates = {'x': 40, 'y': round(145*scaling_factor_y)}
        self.project_name_dropdown_coordinates = {'x': 160, 'y': round(305*scaling_factor_y)}
        self.project_name_coordinates = {'x': 50, 'y': round(325*scaling_factor_y)}
        self.run_measurement_coordinates = {'x': 350, 'y': round(85*scaling_factor_y)}
        self.analyse_menu_coordinates = {'x': 400, 'y': round(50*scaling_factor_y)}
        self.enter_project_explorer_coordinates = {'x': 20, 'y': round(90*scaling_factor_y)}
        self.select_project_name_coordinates = {'x': 42, 'y': round(200*scaling_factor_y)}
        self.exit_project_explorer_coordinates = {'x': 415, 'y': round(90*scaling_factor_y)}
        self.filter_sample_name_coordinates = {'x': 508, 'y': round(183*scaling_factor_y)}
        self.filter_checkbox_coordinates = {'x': 515, 'y': round(220*scaling_factor_y)}
        self.filter_textbox_coordinates = {'x': 520, 'y': round(245*scaling_factor_y)}  
        self.first_entry_coordinates = {'x': 85, 'y': round(210*scaling_factor_y)}
        self.report_template_coordinates = {'x': 1180, 'y': round(95*scaling_factor_y)}
        self.statistics_table_export_menu_coordinates = {'x': 1240, 'y': round(140*scaling_factor_y)}
        self.statistics_table_export_button_coordinates = {'x': 1265, 'y': round(230*scaling_factor_y)}
        self.size_distribution_roundensity_export_menu_coordinates = {'x': 1895, 'y': round(140*scaling_factor_y)}
        self.size_distribution_roundensity_export_button_coordinates = {'x': 1895, 'y': round(230*scaling_factor_y)}
        self.size_distribution_number_export_menu_coordinates = {'x': 1240, 'y': round(630*scaling_factor_y)}
        self.size_distribution_number_export_button_coordinates = {'x': 1265, 'y': round(720*scaling_factor_y)}
        self.zeta_potential_distribution_export_menu_coordinates = {'x': 1895, 'y': round(630*scaling_factor_y)}
        self.zeta_potential_distribution_export_button_coordinates = {'x': 1895, 'y': round(670*scaling_factor_y)}

        self.wait_short = 0.4
        self.wait_long = 0.8
        self.wait_measurement = 5

        self.local_controller = local_controller
        self._logger_dict = {'instance_name': str(self)}

        if self.local_controller is not None:
            if network_id == '':
                self.network_id = 'ZetaSizer'
            else:
                self.network_id = network_id
            self.read_queue = self.local_controller.get_read_queue(self.network_id)

        if not isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.zs_xplorer_window = pyautogui.getWindowsWithTitle('ZS XPLORER')
            if len(self.zs_xplorer_window) == 0:
                logger.critical('ZS Explorer Software not running. Please start ZS Explorer first.', extra=self._logger_dict)
                raise TimeoutError
            else:
                self.zs_xplorer_window = self.zs_xplorer_window[0]
                self.hwnd = win32gui.FindWindow(None, 'ZS XPLORER')

            # Check if the instrument is connected
            self._ensure_window_maximized()
            if not self._get_pixel(**self.check_connection_pixel_coordinates) == self.check_connection_pixel_color:
                logger.critical('Zetasizer instrument not connected.', extra=self._logger_dict)
                raise TimeoutError
            self._exporter = DataExporter()

        if isinstance(self.local_controller, LocalPCClient.LocalPCClient):
            self.command_listener_thread = threading.Thread(target=self._command_listener, daemon=True)
            self.command_listener_thread.start()


    def perform_measurement_and_export_data(self, sop_path: str, export_path: str = '', sample_name: str = '') -> bool:
        """
        Method to perfrom a measurement according to a given SOP and export the results.

        Parameters
        ----------
        sop_path : str
            File path to the SOP that is used for the measurement
        export_path : str, default = ''
            Folder to which the files are exported. When not specified, os.path.join(str(HelperClassDefinitions.PathNames.CHARACTERIZATION_DIR.value), 'DLS') is used.
        sample_name : str, default = ''
            Sample name. When not specified, the name Sample_yyyy-mm-dd_hh-mm-ss is used.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>perform_measurement_and_export_data;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            return json.loads(self.read_queue.get())

        if export_path == '':
            export_path = os.path.join(PathNames.CHARACTERIZATION_DIR.value, 'DLS')
        if sample_name == '':
            sample_name = f'Sample_{time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())}'

        # Make sure the SOP path is valid:
        if not os.path.exists(sop_path):
            logger.warning(f'SOP not found at {sop_path}. Aborting measurement.', extra=self._logger_dict)
            return False

        # Go to Measure tab
        self._ensure_window_active()
        pyautogui.click(**self.measure_menu_coordinates)
        time.sleep(self.wait_long)

        # Open the SOP file chooser
        self._ensure_window_active()
        pyautogui.click(**self.open_sop_coordinates)
        time.sleep(self.wait_long * 2)

        # Select the SOP
        self._ensure_window_active()
        pyautogui.click(**self.sop_name_textbox_coordinates)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(sop_path)
        pyautogui.hotkey('enter')
        time.sleep(self.wait_long * 5)

        # Select the project name
        self._ensure_window_active()
        pyautogui.click(**self.project_name_dropdown_coordinates)
        time.sleep(self.wait_long)
        pyautogui.click(**self.project_name_coordinates)
        time.sleep(self.wait_long * 2)

        # Type in the sample name
        self._ensure_window_active()
        pyautogui.click(**self.sample_name_textbox_coordinates)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(sample_name)
        time.sleep(self.wait_long * 2)

        # Start the measurement
        self._ensure_window_active()
        if not self._get_pixel(**self.run_measurement_coordinates) == self.check_measurement_pixel_color:
            logger.warning('Cannot start measurement.', extra=self._logger_dict)
            return False
        pyautogui.click(**self.run_measurement_coordinates)
        time.sleep(self.wait_measurement)

        # Wait until the measurement is done
        self._ensure_window_maximized()
        while not self._get_pixel(**self.check_connection_pixel_coordinates) == self.check_connection_pixel_color:
            time.sleep(self.wait_measurement)
            self._ensure_window_maximized()

        self.export_data_from_sqlite_database(export_path=export_path, sample_name=sample_name)
        return True

    def export_data_from_sqlite_database(self, export_path: str, sample_name: str) -> bool:
        """
        Method that reads all the data belonging to the specified sample name from the .db file and dumps it into a csv. Also creates a plot of the data.

        Parameters
        ----------
        export_path: str
            Path to which the data is exported.
        sample_name: str
            Sample name which is queried from the database

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if isinstance(self.local_controller, LocalPCServer.LocalPCServer):
            self.local_controller.write(f'{self.network_id}>export_data_from_sqlite_database;' + json.dumps({k: v for k, v in locals().items() if k != "self"}) + '\r\n')
            if self.read_queue.get() == 'True':
                return True
            else:
                return False
        if self._exporter.export_data_from_sqlite_database(export_path=export_path, sample_name=sample_name, create_preview=True, create_metadata_file=True):
            logger.info(f'Exported DLS/Zeta Potential measurement data for sample {sample_name} to {os.path.join(export_path, f"{sample_name}_all_data.csv")}', extra=self._logger_dict)
            logger.info(f'Exported DLS/Zeta Potential preview plot for sample {sample_name} to {os.path.join(export_path, f"{sample_name}_preview.png")}', extra=self._logger_dict)
            logger.info(f'Exported DLS/Zeta Potential metadata {sample_name} to {os.path.join(export_path, f"{sample_name}.md")}', extra=self._logger_dict)
            return True
        return False

    def _ensure_window_active(self) -> None:
        """
        Method that (i) maximizes the ZS Xplorer Window (ii) shows the window and (iii) activates the window

        Returns
        -------
        None
        """
        try:
            self.zs_xplorer_window.maximize()
            if not self.zs_xplorer_window.visible:
                self.zs_xplorer_window.show()
            if not self.zs_xplorer_window.isActive:
                self.zs_xplorer_window.activate()
            time.sleep(self.wait_short/2.0)
        except pygetwindow.PyGetWindowException as ex:
            if 'completed successfully' in ex.args[0]:
                pass  # pygetwindow.PyGetWindowException also raises an exception for error code 0, which means success. Ignore these "errors"

    def _ensure_window_maximized(self) -> None:
        """
        Method that makes sure the ZS Xplorer Window is maximized (if not, it is maximized and focus is immediately shifted back to the previous window)

        Returns
        -------
        None
        """
        if win32gui.GetWindowPlacement(self.hwnd)[1] != win32con.SW_MAXIMIZE:
            active_window_hwnd = win32gui.GetForegroundWindow()
            win32gui.ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)
            win32gui.ShowWindow(active_window_hwnd, win32con.SW_NORMAL)
            win32gui.SetActiveWindow(active_window_hwnd)

    @staticmethod
    def get_clipboard_content() -> str:
        """
        Static method that reads the clipboard values and returns them as a String

        Returns
        -------
        str
            The current content of the clipboard
        """
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData()
        win32clipboard.CloseClipboard()

        return data

    def _get_pixel(self, x: int, y: int) -> Union[Tuple[int, int, int], Tuple[Any, ...]]:
        """
        Method that reads and returns the pixel value at the specified screen coordinates.

        Parameters
        ----------
        x: int
            The x coordinate of the pixel
        x: int
            The y coordinate of the pixel

        Returns
        -------
        Union[Tuple[int, int, int], Tuple[Any, ...]]
            The rgb (or rgba) value of the pixel
        """
        left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
        width = right - left
        height = bottom - top

        hwnd_dc = win32gui.GetWindowDC(self.hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        save_bit_map = win32ui.CreateBitmap()
        save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)

        save_dc.SelectObject(save_bit_map)

        # Take the screenshot of the window's device context (change the last number (3 in this case) if you only get a black window)
        windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 3)

        bmpinfo = save_bit_map.GetInfo()
        bmpstr = save_bit_map.GetBitmapBits(True)

        im = np.frombuffer(bmpstr, dtype='uint8').reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)).copy()
        # Convert from bgra to rgb (remove alpha channel and swap r <-> b)
        im = im[:, :, :3]
        im[:, :, [0, 1, 2]] = im[:, :, [2, 1, 0]]

        # Crop to screen size
        screenwidth, screenheight = windll.user32.GetSystemMetrics(0), windll.user32.GetSystemMetrics(1)
        if left < 0:
            x1 = abs(left)
        else:
            x1 = 0
        if top < 0:
            y1 = abs(top)
        else:
            y1 = 0
        x2 = min(screenwidth, right)
        y2 = min(screenheight, bottom)
        im = im[y1:y1+y2, x1:x1+x2, :]

        win32gui.DeleteObject(save_bit_map.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, hwnd_dc)

        return tuple(im[y, x, :])

    def _command_listener(self)->None:
        """Method that waits for incoming commands on the client side and dispatches them to the measurement hardware"""
        while not ZetaSizer.EMERGENCY_STOP_REQUEST:
            item = self.read_queue.get().split(';')
            cmd = item[0]
            args = json.loads(item[1])

            if cmd == 'perform_measurement_and_export_data':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.perform_measurement_and_export_data(**args)) + '\r\n')
            elif cmd == 'export_data_from_sqlite_database':
                self.local_controller.write(f'{self.network_id}>' + json.dumps(self.export_data_from_sqlite_database(**args)) + '\r\n')
            else:
                logger.warning(f'Invalid command: {cmd} called with args {args}', extra=self._logger_dict)

class DataExporter:
    def __init__(self, path_to_database: Union[str, None]=None):
        if path_to_database is None:
            self.path_to_database = PathNames.ZETASIZER_DATABASE_DIR.value
        else:
            self.path_to_database = path_to_database

        con = sqlite3.connect(self.path_to_database)
        try:
            cur = con.cursor()

            # Build dictionaries
            t = 'RecordParameterTypes'
            data = cur.execute(f"SELECT * FROM {t}")
            self._param_type_name_mapping = {i[0]: i[3].replace('\u03bc', 'u') for i in data}  # Avoid encoding error for µ (\u03bc) occuring in µs

            t = 'RecordParameterTreeNodes'
            data = cur.execute(f"SELECT * FROM {t}")
            self._param_tree_nodes_raw = [i for i in data]
            self.full_param_names_table = {i: self._find_root_node_friendly_name(i)[:-1] for i in range(1, len(self._param_tree_nodes_raw) + 1)}

        finally:
            con.close()


    def _find_root_node_friendly_name(self, id: int, full_name: str = '') -> str:
        """
        Method that reads traverses the RecordParameterTreeNodes recursively and constructs the full parameter names from the node names (using a slash as delimiter)

        Parameters
        ----------
        id: int
            The id for which the name should be retrieved
        full_name: str
            The full name consisting of the tree node names (will be built up recursively while traversing the tree)

        Returns
        -------
        str
            The full name consisting of the tree node names that were traversed, using a slash as delimiter
        """
        id -= 1  # ids in the table start at 1, the array starts at 0
        full_name += f'{self._param_type_name_mapping[self._param_tree_nodes_raw[id][2]]}/'  # Column 3 is RecordParameterTypeFriendlyName
        if self._param_tree_nodes_raw[id][3] is not None:  # Column 4 is ParentNodeIndex
            full_name = self._find_root_node_friendly_name(self._param_tree_nodes_raw[id][3], full_name)
        return full_name

    def export_data_from_sqlite_database(self, export_path: str, sample_name: str, create_preview: bool = True, create_metadata_file: bool = True) -> bool:
        """
        Method that reads all the data belonging to the specified sample name from the .db file and dumps it into a csv. Also creates a plot of the data.

        Parameters
        ----------
        export_path: str
            Path to which the data is exported.
        sample_name: str
            Sample name which is queried from the database
        create_preview: bool = True
            Create a preview plot
        create_metadata_file: bool = True
            Create a metadata file for OpenBis import

        Returns
        -------
        bool
            True if successful, False otherwise
        """

        con = None
        MAGIC_DELIMITER = b'\x06\x01\x01\x01\x02\x01'
        MAGIC_OFFSET = 17

        numbers = []
        volumes = []
        intensities = []
        sizes = []
        zetas = []
        pots = []

        try:
            con = sqlite3.connect(self.path_to_database)
            cur = con.cursor()

            t = 'RecordParameterData'
            c = cur.execute(f"SELECT * FROM {t} WHERE RecordID IN (SELECT RecordID from {t} WHERE ParameterTypeId=99 AND Data_Text='{sample_name}');")
            data = sorted([i for i in c], key=lambda x: (x[-1], x[-4]))  # Sort by run index (to ensure data for each run stays grouped together), then entry index (to ensure peak information appears in the correct order)
            first_index = data[0][-1] - 1
            index = first_index

            export_file_path = os.path.join(export_path, f'{sample_name}_all_data.csv')
            fc = ''
            for row in data:
                if row[-1] != index:
                    index = row[-1]
                    if index != first_index + 1:
                        fc += '\n'
                    fc += f'Data for {sample_name} ({row[-1] - first_index}):\n'
                param_name = self.full_param_names_table[row[-3]]
                if row[1] is not None and b'PublicKeyToken=' in row[1]:
                    binary = row[1][row[1].rfind(b'PublicKeyToken=') + len(b'PublicKeyToken=') + MAGIC_OFFSET:].split(MAGIC_DELIMITER)[1:]
                    decoded = [struct.unpack('@d', j)[0] for j in binary]
                    if param_name.startswith('Sizes') and 'Unclassified Size Analysis Result' not in param_name:
                        sizes.append(decoded)
                    elif param_name.startswith('Particle Size Number Distribution') and 'Unclassified Size Analysis Result' not in param_name:
                        numbers.append(decoded)
                    elif param_name.startswith('Particle Size Volume Distribution (%)') and 'Unclassified Size Analysis Result' not in param_name:
                        volumes.append(decoded)
                    elif param_name.startswith('Particle Size Intensity Distribution') and 'Unclassified Size Analysis Result' not in param_name:
                        intensities.append(decoded)
                    elif param_name.startswith('Zeta Potentials'):
                        pots.append(decoded)
                    elif param_name.startswith('Zeta Potential Distribution Intensities (kcps)'):
                        zetas.append(decoded)
                    field_value = ';'.join([str(j) for j in decoded])
                else:
                    field_value = [str(j) for j in row if j is not None][1]

                fc += f"{param_name};{field_value}\n"

            header = f'Datapoints for Distributions of {sample_name}:\nSize Distributions:\n'
            for i in range(0, len(sizes)):
                header += f'Sizes [nm] (Run {i+1});{";".join([str(j) for j in sizes[i]])}\n'
                header += f'Intensity [%] (Run {i+1});{";".join([str(j) for j in intensities[i]])}\n'
                header += f'Volume [%] (Run {i+1});{";".join([str(j) for j in volumes[i]])}\n'
                header += f'Number [%] (Run {i+1});{";".join([str(j) for j in numbers[i]])}\n\n'

            for i in range(0, len(pots)):
                header += f'Zeta Potential [mV] (Run {i+1});{";".join([str(j) for j in pots[i]])}\n'
                header += f'Counts [kcps] (Run {i+1});{";".join([str(j) for j in zetas[i]])}\n\n'

            header += 'All metadata:\n'

            with open(export_file_path, 'w') as f:
                f.write(header + fc)

            if create_preview:
                self._plot_results(csv_file_path=export_file_path)
            if create_metadata_file:
                self._extract_metadata_for_openbis(csv_file_path=export_file_path)

            return True

        finally:
            con.close()  # Close the connection to the sql database

    @staticmethod
    def _plot_results(csv_file_path: str) -> None:
        """
        Static method to plot the provided data

        Parameters
        ----------
        csv_file_path: str
            Path and file name where to the csv file with the data

        Returns
        -------
        None
        """
        numbers: list[list[float]] = []
        volumes: list[list[float]] = []
        intensities: list[list[float]] = []
        sizes: list[list[float]] = []
        zetas: list[list[float]] = []
        pots: list[list[float]] = []
        int_sizes: list[list[float]] = []
        int_widths: list[list[float]] = []
        int_areas: list[list[float]] = []
        vol_sizes: list[list[float]] = []
        vol_widths: list[list[float]] = []
        vol_areas: list[list[float]] = []
        num_sizes: list[list[float]] = []
        num_widths: list[list[float]] = []
        num_areas: list[list[float]] = []
        zeta_potentials: list[list[float]] = []
        zeta_widths: list[list[float]] = []
        zeta_areas: list[list[float]] = []
        zaverages: list[float] = []
        polydispersities: list[float] = []
        runs = -1
        li = [int_areas, int_sizes, int_widths, vol_areas, vol_sizes, vol_widths, num_areas, num_sizes, num_widths, zeta_areas, zeta_potentials, zeta_widths]

        # Read file content
        fc = [i.replace('\r', '').replace('\n', '').split(';') for i in open(csv_file_path, 'r', encoding='latin1')]

        # Extract data
        for i, c in enumerate(fc):
            if c[0] == '' or 'Unclassified ' in c[0]:
                continue

            if c[0].startswith('Sizes [nm] (Run '):
                sizes.append([float(j) for j in c[1:]])
            elif c[0].startswith('Intensity [%] (Run '):
                intensities.append([float(j) for j in c[1:]])
            elif c[0].startswith('Volume [%] (Run '):
                volumes.append([float(j) for j in c[1:]])
            elif c[0].startswith('Number [%] (Run '):
                numbers.append([float(j) for j in c[1:]])
            elif c[0].startswith('Zeta Potential [mV] (Run '):
                pots.append([float(j) for j in c[1:]])
            elif c[0].startswith('Counts [kcps] (Run '):
                zetas.append([float(j) for j in c[1:]])
            elif c[0].startswith('Data for '):
                runs += 1
                for j in li:
                    j.append([])
            elif c[0] == 'Mean/Size Peak/Particle Size Intensity Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                int_sizes[runs].append(float(c[1]))
            elif c[0] == 'Standard Deviation/Size Peak/Particle Size Intensity Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                int_widths[runs].append(float(c[1]))
            elif c[0] == 'Area/Size Peak/Particle Size Intensity Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                int_areas[runs].append(float(c[1]))
            elif c[0] == 'Mean/Size Peak/Particle Size Volume Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                vol_sizes[runs].append(float(c[1]))
            elif c[0] == 'Standard Deviation/Size Peak/Particle Size Volume Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                vol_widths[runs].append(float(c[1]))
            elif c[0] == 'Area/Size Peak/Particle Size Volume Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                vol_areas[runs].append(float(c[1]))
            elif c[0] == 'Mean/Size Peak/Particle Size Number Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                num_sizes[runs].append(float(c[1]))
            elif c[0] == 'Standard Deviation/Size Peak/Particle Size Number Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                num_widths[runs].append(float(c[1]))
            elif c[0] == 'Area/Size Peak/Particle Size Number Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                num_areas[runs].append(float(c[1]))
            elif c[0] == 'Mean/Size Peak/Zeta Peaks/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                zeta_potentials[runs].append(float(c[1]))
            elif c[0] == 'Standard Deviation/Size Peak/Zeta Peaks/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                zeta_widths[runs].append(float(c[1]))
            elif c[0] == 'Area/Size Peak/Zeta Peaks/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                zeta_areas[runs].append(float(c[1]))
            elif c[0] == 'Z-Average (nm)/Cumulants Result/Cumulants Result/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                zaverages.append(float(c[1]))
            elif c[0] == 'Polydispersity Index (PI)/Cumulants Result/Cumulants Result/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                polydispersities.append(float(c[1]))

        # Average peaks across runs
        all_items = [[int_areas, int_sizes, int_widths], [vol_areas, vol_sizes, vol_widths], [num_areas, num_sizes, num_widths], [zeta_areas, zeta_potentials, zeta_widths]]
        # Fill rugged arrays with nans for converting to numpy, then average across runs, ignoring nans and using slice notation [:] to modify in-place
        for li in all_items:
            max_len = max([len(jt) for it in li for jt in it])
            k = 0
            for it in li:
                for jt in it:
                    while len(jt) < max_len:
                        jt.append(np.nan)
                it[:] = np.nanmean(it[:], axis=0)

        # Sort peaks by Area
        if len(int_areas) > 0:
            int_areas, int_sizes, int_widths = zip(*sorted(list(zip(int_areas, int_sizes, int_widths)), reverse = True))
        if len(vol_areas) > 0:
            vol_areas, vol_sizes, vol_widths = zip(*sorted(list(zip(vol_areas, vol_sizes, vol_widths)), reverse = True))
        if len(num_areas) > 0:
            num_areas, num_sizes, num_widths = zip(*sorted(list(zip(num_areas, num_sizes, num_widths)), reverse = True))
        if len(zeta_areas) > 0:
            zeta_areas, zeta_potentials, zeta_widths  = zip(*sorted(list(zip(zeta_areas, zeta_potentials, zeta_widths)), reverse = True))

        # Plot Data
        f = 1
        if len(zeta_areas) > 0:
            rows = 3
            cols = 2
        else:
            rows = 2
            cols = 2
        sizes = np.asarray(sizes)
        numbers = np.asarray(numbers)
        volumes = np.asarray(volumes)
        intensities = np.asarray(intensities)
        zetas = [np.asarray(i) for i in zetas]  # number of entries can vary for zeta potential and numpy does not like ragged arrays
        pots = [np.asarray(i) for i in pots]

        fig = plt.figure(figsize=(12, 9 * rows / cols))
        if intensities.shape[0] > 0:
            a = fig.add_subplot(rows, cols, f)
            plt.xscale('log')
            for i in range(0, sizes.shape[0]):
                plt.plot(sizes[i], intensities[i], label=f'Run {i+1}')
            a.set_xlabel('Size [nm]')
            a.set_ylabel('Intensity [%]')
            res = ";".join([f'{round(int_sizes[i], 1)}+/-{round(int_widths[i], 1)}' for i in range(0, len(int_sizes))])
            a.set_title(f'Size Intensity Distribution:\nPeak Position (Avg) [nm]: {res}')
            a.legend()
            f += 1
        if volumes.shape[0] > 0:
            a = fig.add_subplot(rows, cols, f)
            plt.xscale('log')
            for i in range(0, sizes.shape[0]):
                plt.plot(sizes[i], volumes[i], label=f'Run {i+1}')
            a.set_xlabel('Size [nm]')
            a.set_ylabel('Volume [%]')
            res = ";".join([f'{round(vol_sizes[i], 1)}+/-{round(vol_widths[i], 1)}' for i in range(0, len(vol_sizes))])
            a.set_title(f'Size Volume Distribution:\nPeak Position (Avg) [nm]: {res}')
            a.legend()
            f += 1
        if numbers.shape[0] > 0:
            a = fig.add_subplot(rows, cols, f)
            plt.xscale('log')
            for i in range(0, sizes.shape[0]):
                plt.plot(sizes[i], numbers[i], label=f'Run {i+1}')
            a.set_xlabel('Size [nm]')
            a.set_ylabel('Number [%]')
            res = ";".join([f'{round(num_sizes[i], 1)}+/-{round(num_widths[i], 1)}' for i in range(0, len(num_sizes))])
            a.set_title(f'Size Number Distribution:\nPeak Position (Avg) [nm]: {res}')
            a.legend()
            f += 1

        a = fig.add_subplot(rows, cols, f)
        plt.xscale('log')
        if len(intensities) > 0:
            plt.plot(sizes[0], np.mean(intensities, 0), 'b', label='Intensity')
        if len(volumes) > 0:
            plt.plot(sizes[0], np.mean(volumes, 0), 'g', label='Volume')
        if len(numbers) > 0:
            plt.plot(sizes[0], np.mean(numbers, 0), 'r', label='Number')
        a.set_xlabel('Size [nm]')
        a.set_ylabel('Frequency [%]')
        res = ";".join([f'Run {i+1}: {round(zaverages[i], 1)} ({round(polydispersities[i], 2)})' for i in range(0, len(zaverages))])
        a.set_title(f'Combined Plots: Z-Average (PDI) [nm]:\n{res}')
        a.legend()
        f += 1

        if len(zetas) > 0:
            a = fig.add_subplot(rows, cols, f)
            for i in range(0, len(zetas)):
                plt.plot(pots[i], zetas[i], label=f'Run {i+1}')
            a.set_xlabel('Zeta Potential [mV]')
            a.set_ylabel('Intensity [kcps]')
            res = ";".join([f'{round(zeta_potentials[i], 1)}+/-{round(zeta_widths[i], 1)}' for i in range(0, len(zeta_potentials))])
            a.set_title(f'Zeta Potential Distribution:\nPeak Position (Avg) [mv]: {res}')
            a.legend()
            f += 1

        plt.tight_layout()
        plt.savefig(csv_file_path[:-len('_all_data.csv')] + '_preview.png')

    @staticmethod
    def _extract_metadata_for_openbis(csv_file_path: str, write_to_file: bool = True) -> dict[str, Union[str, float, int]]:
        """
        Static method to extract metadata from exported files and fill the respective fields in openbis

        Parameters
        ----------
        csv_file_path: str
            Path and file name where the data (as csv) is saved
        write_to_file: bool = True
            Whether to write the metadata to a file. Default is True.

        Returns
        -------
        dict[str, Union[str, float, int]]
            The metadata dict with the OpenBis field codes as keys and the corresponding values as values
        """
        # Mapping of extracted values to their field names in OpenBIS
        PROPERTY_TYPE_CODE_DICT = {
            'Sample Name': '$NAME',
            'Measurement Start Date And Time/Size Measurement Result': 'START_DATE',
            'Name/Material Settings/Material/Sample Settings/Sample Settings/Size Measurement Result': 'DLS.MATERIAL',
            'Name/Dispersant Settings/Dispersant/Sample Settings/Sample Settings/Size Measurement Result': 'DLS.DISPERSANT',
            'Analysis Model/Size Analysis Settings/Size Analysis/Size Measurement Settings/Measurement Settings/Size Measurement Result': 'DLS.ANALYSISMODEL',
            'Cell Name/Cell Description Settings/View Settings/Cell Settings/Cell/Sample Settings/Sample Settings/Size Measurement Result': 'DLS.CELLDESCRIPTION',
            'Description/Cell Description Settings/View Settings/Cell Settings/Cell/Sample Settings/Sample Settings/Size Measurement Result': 'DLS.CELLDESCRIPTION',
            'Fka Model/Zeta Fka Parameter Settings/Zeta F Ka Parameter Settings/Zeta Analysis Settings/Zeta Analysis/Zeta Measurement Settings/Measurement Settings/Zeta Measurement Result': 'DLS.FKAMODEL'
        }

        metadata: dict[str, Union[str, float, int]] = {}
        attenuators: list[float] = []
        temperatures: list[float] = []
        zaverages: list[float] = []
        polydispersities: list[float] = []
        zeta_averages: list[float] = []
        int_sizes: list[list[float]] = []
        int_widths: list[list[float]] = []
        int_areas: list[list[float]] = []
        vol_sizes: list[list[float]] = []
        vol_widths: list[list[float]] = []
        vol_areas: list[list[float]] = []
        num_sizes: list[list[float]] = []
        num_widths: list[list[float]] = []
        num_areas: list[list[float]] = []
        zeta_potentials: list[list[float]] = []
        zeta_widths: list[list[float]] = []
        zeta_areas: list[list[float]] = []
        intercepts: list[float] = []
        cumulants_errors: list[float] = []
        multimodal_errors: list[float] = []
        conductivities: list[float] = []
        voltages: list[float] = []

        runs = -1
        li = [int_areas, int_sizes, int_widths, vol_areas, vol_sizes, vol_widths, num_areas, num_sizes, num_widths, zeta_areas, zeta_potentials, zeta_widths]

        # Read file content
        fc = [i.replace('\r', '').replace('\n', '').split(';') for i in open(csv_file_path, 'r', encoding='latin1')]

        # Extract data (averaging in case of multiple entries)
        for i, c in enumerate(fc):
            if c[0] == '':
                continue
            if c[0] in PROPERTY_TYPE_CODE_DICT.keys():
                # Check if it is a String field (those have the full name in the PROPERTY_TYPE_CODE_DICT), and if so, just use the value directly
                if c[0] == 'Measurement Start Date And Time/Size Measurement Result':
                    metadata[PROPERTY_TYPE_CODE_DICT[c[0]]] = fc[i][1].replace('T', ' ').replace('Z', '').split('.')[0]
                else:
                    metadata[PROPERTY_TYPE_CODE_DICT[c[0]]] = fc[i][1]
            else:
                # If it is a float field, append the results for averaging
                if 'Unclassified ' in c[0]:
                    continue

                if c[0] == 'Attenuator/Actual Instrument Settings/Actual Instrument Settings/Size Measurement Result':
                    attenuators.append(float(fc[i][1]))
                elif c[0] == 'Temperature (°C)/Actual Instrument Settings/Actual Instrument Settings/Size Measurement Result':
                    temperatures.append(float(fc[i][1]))
                elif c[0] == 'Z-Average (nm)/Cumulants Result/Cumulants Result/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    zaverages.append(float(fc[i][1]))
                elif c[0] == 'Polydispersity Index (PI)/Cumulants Result/Cumulants Result/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    polydispersities.append(float(fc[i][1]))
                elif c[0] == 'Intercept/Cumulants Result/Cumulants Result/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    intercepts.append(float(fc[i][1]))
                elif c[0] == 'Fit Error/Cumulants Result/Cumulants Result/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    cumulants_errors.append(float(fc[i][1]))
                elif c[0] == 'Fit Error/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    multimodal_errors.append(float(fc[i][1]))
                elif c[0] == 'Zeta Potential (mV)/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                    zeta_averages.append(float(fc[i][1]))
                elif c[0] == 'Measured Voltage (V)/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                    voltages.append(float(fc[i][1]))
                elif c[0] == 'Conductivity (mS/cm)/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                    conductivities.append(float(fc[i][1]))
                elif c[0].startswith('Data for '):
                    runs += 1
                    for j in li:
                        j.append([])
                elif c[0] == 'Mean/Size Peak/Particle Size Intensity Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    int_sizes[runs].append(float(c[1]))
                elif c[0] == 'Standard Deviation/Size Peak/Particle Size Intensity Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    int_widths[runs].append(float(c[1]))
                elif c[0] == 'Area/Size Peak/Particle Size Intensity Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    int_areas[runs].append(float(c[1]))
                elif c[0] == 'Mean/Size Peak/Particle Size Volume Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    vol_sizes[runs].append(float(c[1]))
                elif c[0] == 'Standard Deviation/Size Peak/Particle Size Volume Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    vol_widths[runs].append(float(c[1]))
                elif c[0] == 'Area/Size Peak/Particle Size Volume Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    vol_areas[runs].append(float(c[1]))
                elif c[0] == 'Mean/Size Peak/Particle Size Number Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    num_sizes[runs].append(float(c[1]))
                elif c[0] == 'Standard Deviation/Size Peak/Particle Size Number Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    num_widths[runs].append(float(c[1]))
                elif c[0] == 'Area/Size Peak/Particle Size Number Distribution Peaks ordered by area/Size Analysis Result/Size Analysis Result/Size Measurement Result':
                    num_areas[runs].append(float(c[1]))
                elif c[0] == 'Mean/Size Peak/Zeta Peaks/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                    zeta_potentials[runs].append(float(c[1]))
                elif c[0] == 'Standard Deviation/Size Peak/Zeta Peaks/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                    zeta_widths[runs].append(float(c[1]))
                elif c[0] == 'Area/Size Peak/Zeta Peaks/Zeta Analysis Result/Zeta Analysis Result/Zeta Measurement Result':
                    zeta_areas[runs].append(float(c[1]))

        # Average peaks across runs
        all_items = [[int_areas, int_sizes, int_widths], [vol_areas, vol_sizes, vol_widths], [num_areas, num_sizes, num_widths], [zeta_areas, zeta_potentials, zeta_widths]]
        # Fill rugged arrays with nans for converting to numpy, then average across runs, ignoring nans and using slice notation [:] to modify in-place
        for li in all_items:
            max_len = max([len(jt) for it in li for jt in it])
            k = 0
            for it in li:
                for jt in it:
                    while len(jt) < max_len:
                        jt.append(np.nan)
                it[:] = np.nanmean(it[:], axis=0)

        # Sort peaks by Area
        if len(int_areas) > 0:
            int_areas, int_sizes, int_widths = zip(*sorted(list(zip(int_areas, int_sizes, int_widths)), reverse = True))
        if len(vol_areas) > 0:
            vol_areas, vol_sizes, vol_widths = zip(*sorted(list(zip(vol_areas, vol_sizes, vol_widths)), reverse = True))
        if len(num_areas) > 0:
            num_areas, num_sizes, num_widths = zip(*sorted(list(zip(num_areas, num_sizes, num_widths)), reverse = True))
        if len(zeta_areas) > 0:
            zeta_areas, zeta_potentials, zeta_widths  = zip(*sorted(list(zip(zeta_areas, zeta_potentials, zeta_widths)), reverse = True))

        # Calculate PD for individual Peaks
        int_pis = np.array(int_widths) / np.array(int_sizes)
        vol_pis = np.array(vol_widths) / np.array(vol_sizes)
        num_pis = np.array(num_widths) / np.array(num_sizes)

        # Average the numerical values for certain fields and add them to the metadata dict:
        metadata['DLS.ATTENUATOR'] = int(np.array(attenuators).mean())
        metadata['DLS.TEMPERATURE'] = round(np.array(temperatures).mean(), 2)
        metadata['DLS.ZAVG'] = round(np.array(zaverages).mean(), 2)
        metadata['DLS.PDI'] = round(np.array(polydispersities).mean(), 3)
        metadata['DLS.INTERCEPT'] = round(np.array(intercepts).mean(), 3)
        metadata['DLS.CUMULANTSFITERROR'] = round(np.array(cumulants_errors).mean(), 6)
        metadata['DLS.MULTIMODALFITERROR'] = round(np.array(multimodal_errors).mean(), 6)
        if len(zeta_areas) > 0:
            metadata['DLS.ZETA'] = round(np.array(zeta_averages).mean(), 2)
            metadata['DLS.VOLT'] = round(np.array(voltages).mean(), 2)
            metadata['DLS.COND'] = round(np.array(conductivities).mean(), 4)

        # For the different distribution types, report data for the first three peaks
        for i in range(0, min(3, len(int_sizes))):
            metadata[f'DLS.PK{i + 1}INT'] = round(int_sizes[i], 2)
            metadata[f'DLS.PK{i + 1}INTWIDTH'] = round(int_widths[i], 2)
            metadata[f'DLS.PK{i + 1}INTPD'] = round(int_pis[i], 2)
        for i in range(0, min(3, len(vol_sizes))):
            metadata[f'DLS.PK{i + 1}VOL'] = round(vol_sizes[i], 2)
            metadata[f'DLS.PK{i + 1}VOLWIDTH'] = round(vol_widths[i], 2)
            metadata[f'DLS.PK{i + 1}VOLPD'] = round(vol_pis[i], 2)
        for i in range(0, min(3, len(num_sizes))):
            metadata[f'DLS.PK{i + 1}NUM'] = round(num_sizes[i], 2)
            metadata[f'DLS.PK{i + 1}NUMWIDTH'] = round(num_widths[i], 2)
            metadata[f'DLS.PK{i + 1}NUMPD'] = round(num_pis[i], 2)
        for i in range(0, min(3, len(zeta_potentials))):
            metadata[f'DLS.PK{i + 1}ZETA'] = round(zeta_potentials[i], 2)
            metadata[f'DLS.PK{i + 1}ZETAWIDTH'] = round(zeta_widths[i], 2)

        if write_to_file:
            with open(csv_file_path[:-len('.csv')] + '.md', 'w') as f:
                f.write(json.dumps(metadata, indent=4))

        return metadata
