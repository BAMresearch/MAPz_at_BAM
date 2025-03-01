#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import math
import time

import numpy as np
import scipy.optimize
import json
import logging
import os.path

from xarm.wrapper import XArmAPI
from typing import Union, Tuple, List, Optional, Any, Dict, Iterable, TYPE_CHECKING
from Minerva.API.HelperClassDefinitions import Hardware, RobotArmHardware, ContainerTypeCollection, PathNames, PathsToHardwareCollection, SampleHolderDefinitions, TaskScheduler, TaskGroupSynchronizationObject

import Minerva.API.MinervaAPI

from Minerva.Hardware.Sonicators import Bandelin, Hielscher
from Minerva.Hardware.AdditionHardware import SwitchingValve, OpentronsOT2, WPI
from Minerva.Hardware.Hotplates import IkaHotplate
from Minerva.Hardware.SampleHolder import SampleHolder
from Minerva.Hardware.Centrifuges import Herolab
from Minerva.Hardware.OtherHardware import Electromagnet, CapperDecapper

if TYPE_CHECKING:
    from Minerva.API.MinervaAPI import Container

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
DEBUG_WAIT = True


class XArm6(RobotArmHardware):
    """
    Class to control the XArm 6 robotic arm
    
    Parameters
    ----------
    ip_address: str
        The IP Address of the robot arm
    levelling_data_file: Optional[str]
        Path to a json file containing levelling data (x, y, z) for the table in the top grip (a plane will be fit to these data and used as additional offsets depending on the position of the arm). Default is None.
    """
    
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, ip_address: str, levelling_data_file: Optional[str] = None) -> None:
        super().__init__()
        self.ip_address = ip_address
        self.arm = XArmAPI(ip_address, do_not_open=False, is_radian=False)
        
        self.arm.motion_enable(enable=True)
        self.arm.set_mode(0)
        self.arm.set_state(state=0)
        
        self.arm.reset(wait=True)
        self.arm.set_gripper_enable(True)
        self.arm.set_mode(0)
        self.arm.set_gripper_speed(3000)

        self.is_current_grip_from_top = True
        self.is_in_resting_pos = True
        self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT / 2
        self._logger_dict = {'instance_name': str(self)}
        
        if levelling_data_file is not None:
            data = json.load(open(levelling_data_file))
            self._table_levelling_parameters, _ = scipy.optimize.curve_fit(XArm6._table_plane, (data["x"], data["y"]), data["z"], p0=(0, 0, 0, 0, 0, 178))
        else:
            self._table_levelling_parameters = None


    @staticmethod
    def _table_plane(xy: Iterable, a: float, b: float, c: float, d: float, e: float, offset: float) -> np.ndarray:
        x, y = np.asarray(xy)
        z = offset + a * x + b * y + c * x ** 2 + d * y ** 2 + e * x * y
        return z.ravel()

    def _change_grip(self, container: Minerva.API.MinervaAPI.Container, last_pos: List, grip_offset_sideways: Optional[float] = None, grip_offset_top: Optional[float] = None) -> bool:
        """
        Method used for changing the grip on the hardware (from top or sideways).

        Parameters
        ----------
        container : MinervaAPI.Container
            The container for which the grip should be changed.
        last_pos: List
            The last position the robot arm was in.
        grip_offset_sideways : float
            How far below the top (in mm) the container should be gripped (measured from the top of the container to the bottom of the gripper), default is None, which will result in the gripper width plus 30 for Falcon Tubes and plus 8 for Flasks.
        grip_offset_top : float
            How far below the top (in mm) the container should be gripped (measured from the top of the container to the bottom of the gripper), default is None, which will result in half the gripper height.

        Returns
        -------
        bool
            True if the container was successfully moved, False otherwise
        """
        if XArm6.EMERGENCY_STOP_REQUEST:
            return False

        path: Union[Tuple[Tuple[float | int, ...], ...], List[List[float | int]]] = ((0, 0, 0), )
        gripper_pos_open = 475
        grip_change_holder: Optional[SampleHolder.SampleHolderHardware] = None
        if grip_offset_top is None:
            grip_offset_top = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT / 2

        if container.container_type.container_name == 'FALCON_TUBE_15_ML':
            grip_change_holder = SampleHolder.SampleHolder(hardware_definition=SampleHolderDefinitions.Grip_Change_Holder_15mL_Conical_Tubes)
            if grip_offset_sideways is None:
                grip_offset_sideways = PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH + 30
        elif container.container_type.container_name == 'FALCON_TUBE_50_ML':
            grip_change_holder = SampleHolder.SampleHolder(hardware_definition=SampleHolderDefinitions.Grip_Change_Holder_50mL_Conical_Tubes)
            if grip_offset_sideways is None:
                grip_offset_sideways = PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH + 30
        elif 'FLASK' in container.container_type.container_name:
            grip_change_holder = SampleHolder.SampleHolder(hardware_definition=SampleHolderDefinitions.Corkring_Small)
            if grip_offset_sideways is None:
                grip_offset_sideways = PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH / 2

        if self.is_current_grip_from_top:
            z_pos = PathsToHardwareCollection.TABLE_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, grip_change_holder.hardware_definition["dimensions"]["zDimension"])
            if container.container_type.container_name == 'FALCON_TUBE_15_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder15mLFalconTubeTop
            elif container.container_type.container_name == 'FALCON_TUBE_50_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop
            elif 'FLASK' in container.container_type.container_name:
                path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksTop
                if container.container_type.container_name == 'FLASK_10_ML' or container.container_type.container_name == 'FLASK_25_ML':
                    z_pos -= 5  # Correct for 10 and 25 mL Flaks sitting deeper in the cork rings
        else:
            z_pos = max(PathsToHardwareCollection.TABLE_BASE_HEIGHT_SIDEWAYS + max(container.container_type.container_height - self.current_grip_height, grip_change_holder.hardware_definition["dimensions"]["zDimension"]), PathsToHardwareCollection.GRIP_CHANGER_MIN_HEIGHT_SIDEWAYS)
            if container.container_type.container_name == 'FALCON_TUBE_15_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder15mLFalconTubeSideways
            elif container.container_type.container_name == 'FALCON_TUBE_50_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeSideways
            elif 'FLASK' in container.container_type.container_name:
                path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksSideways
                if container.container_type.container_name == 'FLASK_10_ML' or container.container_type.container_name == 'FLASK_25_ML':
                    z_pos -= 5  # Correct for 10 and 25 mL Flaks sitting deeper in the cork rings

        last_pos[2] = max(path[1][2], last_pos[2])
        self.take_transition_path(last_pos, path[1:])
 
        offsets = grip_change_holder.get_coordinates(slot_number=1, offset_top_left={'x0': 0, 'y0': 0, 'z0': None})  # get only z offsets of hardware
        path = [list(i) for i in path]
        path[-1][0] += offsets[0]
        path[-1][1] += offsets[1]
        z_pos += offsets[2]
        if self._table_levelling_parameters is not None:  # If there is levelling data, add the deviation from the "default" table base height to z_pos
            z_pos += XArm6._table_plane((path[-1][0], path[-1][1]), *self._table_levelling_parameters)[0] - PathsToHardwareCollection.TABLE_BASE_HEIGHT
        self.arm.move_arc_lines(paths=path[1:], speed=300, times=1, wait=DEBUG_WAIT)
        self.arm.set_position(*[path[-1][i] if i != 2 else z_pos for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
        self.arm.set_gripper_position(gripper_pos_open, wait=True)

        path.reverse()
        self.arm.move_arc_lines(paths=path[:-1], speed=300, times=1, wait=True)

        # Make sure none of the joint angles are close to their limits (some positions are degenerate)
        if self.arm.angles[3] > 180 or self.arm.angles[5] > 180:
            self.arm.set_servo_angle(servo_id=4, angle=0, is_radian=False, speed=50, wait=DEBUG_WAIT)
            self.arm.set_servo_angle(servo_id=6, angle=0, is_radian=False, speed=50, wait=DEBUG_WAIT)

        self.is_current_grip_from_top = not self.is_current_grip_from_top

        path: Union[Tuple[Tuple[float | int, ...], ...], List[List[float | int]]] = ((0, 0, 0), )
        if self.is_current_grip_from_top:
            self.current_grip_height = grip_offset_top
            z_pos = PathsToHardwareCollection.TABLE_BASE_HEIGHT + max(container.container_type.container_height - grip_offset_top, grip_change_holder.hardware_definition["dimensions"]["zDimension"])
            if container.container_type.container_name == 'FALCON_TUBE_15_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder15mLFalconTubeTop
            elif container.container_type.container_name == 'FALCON_TUBE_50_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop
            elif 'FLASK' in container.container_type.container_name:
                path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksTop
                if container.container_type.container_name == 'FLASK_10_ML' or container.container_type.container_name == 'FLASK_25_ML':
                    z_pos -= 3  # Correct for 10 and 25 mL Flaks sitting deeper in the cork rings
        else:
            self.current_grip_height = grip_offset_sideways
            z_pos = max(PathsToHardwareCollection.TABLE_BASE_HEIGHT_SIDEWAYS + max(container.container_type.container_height - grip_offset_sideways, grip_change_holder.hardware_definition["dimensions"]["zDimension"]), PathsToHardwareCollection.GRIP_CHANGER_MIN_HEIGHT_SIDEWAYS)
            if container.container_type.container_name == 'FALCON_TUBE_15_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder15mLFalconTubeSideways
            elif container.container_type.container_name == 'FALCON_TUBE_50_ML':
                path = PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeSideways
            elif 'FLASK' in container.container_type.container_name:
                path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksSideways
                if container.container_type.container_name == 'FLASK_10_ML' or container.container_type.container_name == 'FLASK_25_ML':
                    z_pos -= 3  # Correct for 10 and 25 mL Flaks sitting deeper in the cork rings

        offsets = grip_change_holder.get_coordinates(slot_number=1, offset_top_left={'x0': 0, 'y0': 0, 'z0': None})  # get only z offsets of hardware
        path = [list(i) for i in path]
        path[-1][0] += offsets[0]
        path[-1][1] += offsets[1]
        z_pos += offsets[2]
        if self._table_levelling_parameters is not None:  # If there is levelling data, add the deviation from the "default" table base height to z_pos
            z_pos += XArm6._table_plane((path[-1][0], path[-1][1]), *self._table_levelling_parameters)[0] - PathsToHardwareCollection.TABLE_BASE_HEIGHT
        self.arm.move_arc_lines(paths=path[1:], speed=300, times=1, wait=DEBUG_WAIT)
        self.arm.set_position(*[path[-1][i] if i != 2 else z_pos for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
        self.arm.set_gripper_position(0, wait=True)

        if self.is_current_grip_from_top:
            self.arm.set_position(*[path[-1][i] if i != 2 else PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop[-1][2] for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            logger.info(f'Changed grip on container {container.name} to a top grip.', extra=self._logger_dict)
        else:
            self.arm.set_position(*[path[-1][i] if i != 2 else PathsToHardwareCollection.GripChangePosToValve[1][2] for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
            logger.info(f'Changed grip on container {container.name} to a sideways grip.', extra=self._logger_dict)

        return self.is_okay()

    @TaskScheduler.scheduled_task
    def move(self, container: Minerva.API.MinervaAPI.Container, target_hardware: Hardware, target_deck_position: int = 0, target_slot_number: int = 0, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None, **kwargs: Optional[Any]) -> bool:
        """
        Method used for moving a container to a different hardware.

        Parameters
        ----------
        container : MinervaAPI.Container
            The container which should be moved.
        target_hardware : Union[Hardware, XArm6]
            The sample holder (or hardware if the hardware does not have an associated sample holder) to which the container should be moved.
        target_deck_position : int, default = 0
            Optional deck position of the holder (or the valve position when hardware is a syringe pump) to which the container should be moved. If the target_hardware is a SampleHolder, the deck position of the holder will be used. Default is 0.
        target_slot_number : int, default = 0
            Optional number of the slot of the holder (for holders with several slots) to which the container should be moved, default is 0
        block: bool = TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_blocking_behavior
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = TaskScheduler.default_priority
            Priority of this task (when decorated with TaskScheduler.scheduled_task). Default is configured in TaskScheduler.default_priority
        task_group_synchronization_object: TaskGroupSynchronizationObject = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Other Parameters
        ----------------
        bottom_clearance : float, default = None
            Optional parameter indicating the height in mm above the bottom of the vessel for the tip of the Probe Sonicator, stirbar retriever, or needle from a syringe pump or valve. Default is None, resulting in 30mm for UP200ST, 5/15/25mm for the stirbar retriever and flasks/50mL Falcon Tubes/15mL Falcon Tubes, and 8mm for the 6-way valve.

        Returns
        -------
        bool
            True if the container was moved successfully, False otherwise
        """
        if XArm6.EMERGENCY_STOP_REQUEST:
            return False
        bottom_clearance: float = kwargs.get('bottom_clearance', None)
        if bottom_clearance is None:
            if isinstance(target_hardware, Hielscher.UP200ST):
                bottom_clearance = 30
            elif isinstance(target_hardware, SwitchingValve.SwitchingValve):
                bottom_clearance = 8
            elif isinstance(target_hardware, Electromagnet.Electromagnet):
                if container.container_type.container_name == 'FALCON_TUBE_15_ML':
                    bottom_clearance = 25
                elif container.container_type.container_name == 'FALCON_TUBE_50_ML':
                    bottom_clearance = 15
                elif 'FLASK' in container.container_type.container_name:
                    bottom_clearance = 5

        path: Union[Tuple[Tuple[Union[float, int], ...], ...], List[List[Union[float, int]]]] = ((0, 0, 0), )
        last_pos: Union[Tuple[Union[float, int], ...], List[Union[float, int]]] = (0, 0, 0, 0, 0, 0)
        z_pos = 0.0
        gripper_pos_open = 475
        source_hardware = container.current_hardware
        grip_offset_top = None

        if source_hardware == target_hardware and container.deck_position == target_deck_position and container.slot_number == target_slot_number:
            return True

        if self.is_in_resting_pos:
            self.arm.move_arc_lines(PathsToHardwareCollection.RestPosToInitialPos, speed=300, times=1, wait=True)
            self.is_in_resting_pos = False

        if isinstance(source_hardware, SampleHolder.SampleHolder) or isinstance(source_hardware, Herolab.RobotCen):
            is_pick_and_place = True

            # Hardware that will always be approached in a sideways grip (as defined in their path). Currently this applies only to Hotplates
            if isinstance(source_hardware.parent_hardware, IkaHotplate.RCTDigital5):
                self.is_current_grip_from_top = False
            elif not (isinstance(source_hardware, SampleHolder.SampleHolder) and source_hardware.parent_hardware is source_hardware and container.deck_position == 4):  # Hardware that will always be approached in a top grip (as defined in their path). Currently everything but Hotplates and grip change sample holders
                self.is_current_grip_from_top = True

            if isinstance(source_hardware.parent_hardware, IkaHotplate.RCTDigital5):
                self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH / 2
            elif isinstance(source_hardware.parent_hardware, Herolab.RobotCen) or isinstance(target_hardware.parent_hardware, Herolab.RobotCen):
                self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT * 1 / 15   
                if isinstance(target_hardware.parent_hardware, Herolab.RobotCen):
                    gripper_pos_open = 355
                else:
                    gripper_pos_open = 430
            elif isinstance(source_hardware.parent_hardware, OpentronsOT2.OT2) or isinstance(target_hardware.parent_hardware, OpentronsOT2.OT2):
                self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT * 2 / 3
                if container.container_type.container_name == 'FLASK_10_ML' or container.container_type.container_name == 'FLASK_25_ML':
                    gripper_pos_open = 300
                else:
                    gripper_pos_open = 430
            elif (isinstance(source_hardware.parent_hardware, SampleHolder.SampleHolder) or isinstance(source_hardware.parent_hardware, Bandelin.SonorexDigitecHRC)) and isinstance(target_hardware.parent_hardware, Bandelin.SonorexDigitecHRC):
                self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT * 7/8
            elif isinstance(source_hardware, SampleHolder.SampleHolder) and source_hardware.parent_hardware is source_hardware and container.deck_position == 4:  # Grip change holders; should not be used as a source in 'move' method (only in _change_grip), intended for testing/legacy support only.
                if self.is_current_grip_from_top:
                    self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT / 2
                else:
                    self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH + 80
            else:
                self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT / 2

            if isinstance(source_hardware.parent_hardware, OpentronsOT2.OT2):
                assert isinstance(source_hardware, SampleHolder.SampleHolder)
                offsets = source_hardware.get_coordinates(container.slot_number, rotation_angle=180, invert_y=True, offset_top_left=None)
                z_pos = PathsToHardwareCollection.OT2_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, source_hardware.hardware_definition["dimensions"]["zDimension"])
                if container.deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToOT2Holder1
                elif container.deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToOT2Holder2
                elif container.deck_position == 3:
                    path = PathsToHardwareCollection.InitialPosToOT2Holder3
            elif isinstance(source_hardware.parent_hardware, Bandelin.SonorexDigitecHRC):
                assert isinstance(source_hardware, SampleHolder.SampleHolder)
                offsets = source_hardware.get_coordinates(container.slot_number, rotation_angle=90, invert_y=False)
                z_pos = PathsToHardwareCollection.BATH_SONICATOR_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, source_hardware.hardware_definition["dimensions"]["zDimension"])
                if container.deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToBathSonicator50mLFalconTube
                elif container.deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToBathSonicator15mLFalconTube
            elif isinstance(source_hardware.parent_hardware, IkaHotplate.RCTDigital5):
                assert isinstance(source_hardware, SampleHolder.SampleHolder)
                offsets = source_hardware.get_coordinates(container.slot_number, offset_top_left=None)
                z_pos = PathsToHardwareCollection.HOTPLATE_BASE_HEIGHT_SIDEWAYS + container.container_type.container_height - self.current_grip_height
                if container.deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToHotplate1
                elif container.deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToHotplate2
                elif container.deck_position == 3:
                    path = PathsToHardwareCollection.InitialPosToHotplate3
                elif container.deck_position == 4:
                    path = PathsToHardwareCollection.InitialPosToHotplate4
            elif isinstance(source_hardware, Herolab.RobotCen):
                if container.container_type is ContainerTypeCollection.FALCON_TUBE_50_ML:
                    offsets = (0.0, 0.0, 0.0)
                elif container.container_type is ContainerTypeCollection.FALCON_TUBE_15_ML:
                    offsets = (math.sin(math.radians(31))*6, 0.0, 6.0)         # 15 mL tube adapters 6 mm higher         # Angle of approach 31 degrees
                centrifuge_rotor = source_hardware.rotor_info.rotor_type
                if centrifuge_rotor == 'AF 8.50.3':
                    path = PathsToHardwareCollection.InitialPosToCentrifugeRotorAF8503
                elif centrifuge_rotor == 'AF 24.2':
                    raise NotImplementedError  
                z_pos = path[-1][2]
            elif source_hardware.parent_hardware is source_hardware:  # "Root" Sample Holder
                assert isinstance(source_hardware, SampleHolder.SampleHolder)
                offsets = source_hardware.get_coordinates(container.slot_number, rotation_angle=90, invert_y=True, offset_top_left={'x0': 0, 'y0': 0, 'z0': None})  # get only z offsets of hardware
                z_pos = PathsToHardwareCollection.TABLE_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, source_hardware.hardware_definition["dimensions"]["zDimension"])
                if container.deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToSampleHolder1
                elif container.deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToSampleHolder2
                elif container.deck_position == 3:
                    path = PathsToHardwareCollection.InitialPosToSampleHolder3
                    if container.container_type.container_name == 'FLASK_10_ML':
                        z_pos -= 4  # Correct for 10 and 25 mL Flaks sitting deeper in the cork rings
                    elif container.container_type.container_name == 'FLASK_25_ML':
                        z_pos -= 1
                elif container.deck_position == 4:
                    if self.is_current_grip_from_top:
                        path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksTop
                    else:
                        path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksSideways
                        z_pos = PathsToHardwareCollection.TABLE_BASE_HEIGHT_SIDEWAYS + max(container.container_type.container_height - self.current_grip_height, source_hardware.hardware_definition["dimensions"]["zDimension"])
                if self._table_levelling_parameters is not None:  # If there is levelling data, add the deviation from the "default" table base height to z_pos
                    z_pos += XArm6._table_plane((path[-1][0], path[-1][1]), *self._table_levelling_parameters)[0] - PathsToHardwareCollection.TABLE_BASE_HEIGHT
            else:
                z_pos = 0.0
                offsets = (0.0, 0.0, 0.0)
        else:
            is_pick_and_place = False
            z_pos = 0.0
            offsets = (0.0, 0.0, 0.0)

            if isinstance(source_hardware, SwitchingValve.SwitchingValve):
                path = PathsToHardwareCollection.GripChangePosToValve
            elif isinstance(source_hardware, Hielscher.UP200ST):
                path = PathsToHardwareCollection.GripChangePosToProbeSonicator
            elif isinstance(source_hardware, Electromagnet.Electromagnet):
                if source_hardware.magnet_number == 0:
                    raise NotImplementedError  
                elif source_hardware.magnet_number == 1:
                    path = PathsToHardwareCollection.GripChangePosToElectromagnet1
                else:
                    raise NotImplementedError
            elif isinstance(source_hardware, CapperDecapper.CapperDecapper):
                path = PathsToHardwareCollection.GripChangePosToCapperDecapper
            else:
                raise NotImplementedError

        # Path movement to source
        path = [list(i) for i in path]
        path[-1][0] += offsets[0]
        path[-1][1] += offsets[1]
        z_pos += offsets[2]

        if is_pick_and_place:
            # Calculate the transition path (if necessary) to go from current pos to new starting point, avoiding self-collision (ignoring the z-coordinate)
            last_pos = self.arm.position
            assert isinstance(last_pos, list)
            if self.is_current_grip_from_top:
                angles: list = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop[-1][3:6])
            else:
                angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeSideways[-1][3:6])
            last_pos[3:6] = angles[:]  # If the angles are close to +/-180, the sign might change abruptly, leading to "wrong" interpolation -> use only coordinates
            last_pos[2] = max(path[1][2], last_pos[2])
            self.take_transition_path(last_pos, path[1:])

            if isinstance(source_hardware, Herolab.RobotCen):
                self.arm.set_gripper_position(350, wait=True)
                path[-1][2] = z_pos
                self.arm.move_arc_lines(paths=path[1:-1], speed=300, times=1, wait=DEBUG_WAIT)
                self.arm.set_position(*path[-1], speed=150, wait=True)
                self.arm.set_gripper_position(0, wait=True)
            else:
                self.arm.move_arc_lines(paths=path[1:], speed=300, times=1, wait=DEBUG_WAIT)
                self.arm.set_gripper_position(gripper_pos_open, wait=True)
                self.arm.set_position(*[path[-1][i] if i != 2 else z_pos for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
                self.arm.set_gripper_position(0, wait=True)
                self.arm.set_position(*path[-1], wait=DEBUG_WAIT)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument

            path.reverse()
            self.arm.move_arc_lines(path[:-1], speed=300, times=1, wait=True)

            last_pos = path[-2]

        else:
            # Do not move arm to these hardware sources if it is not a pick&place operation (it already has to be there since it cannot drop anything off here and needs to already be holding the container in place)
            path.reverse()
            self.arm.move_arc_lines(path[:-1], speed=150, times=1, wait=True)
            last_pos = path[-2]

        logger.info(f'Finished moving robot arm to source destination: {source_hardware}.', extra=self._logger_dict)

        ###############################
        # End path movement to source #
        ###############################

        # After picking up a flask from the hotplate, take a transition path either clockwise or counter-clockwise, and continue from there to the other hardware components
        if 'FLASK' in container.container_type.container_name and not self.is_current_grip_from_top and isinstance(source_hardware.parent_hardware, IkaHotplate.RCTDigital5) and last_pos[0] >= 0 and last_pos[1] >= 0:
            # Determine whether to go clockwise or counter-clockwise, depending on the servo angles of joint 1
            servo_angle_j1 = self.arm.get_servo_angle(servo_id=1, is_radian=True)[1]
            if abs(servo_angle_j1) < math.pi:
                transition_path = [list(i) for i in PathsToHardwareCollection.TransitionPathSidewaysFrontToLeft]
            else:
                transition_path = [list(i) for i in PathsToHardwareCollection.TransitionPathSidewaysFrontToRight]
            self.arm.move_arc_lines(paths=transition_path, speed=150, times=1, wait=True)
            last_pos = transition_path[-1]
            logger.debug(f'Taken transition path coming from the hotplates from {transition_path[0]} to {transition_path[-1]}', extra=self._logger_dict)

        path: Union[Tuple[Tuple[Union[float, int], ...], ...], List[List[Union[float, int]]]] = ((0, 0, 0), )
        if isinstance(target_hardware, SampleHolder.SampleHolder) or isinstance(target_hardware, Herolab.RobotCen):
            is_pick_and_place = True
            if isinstance(target_hardware, SampleHolder.SampleHolder):
                target_deck_position = target_hardware.deck_position
                if isinstance(target_hardware.parent_hardware, OpentronsOT2.OT2):
                    grip_offset_top = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT * 2 / 3
                elif isinstance(target_hardware.parent_hardware, Bandelin.SonorexDigitecHRC):
                    self.current_grip_height = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT * 7 / 8
                else:
                    grip_offset_top = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT / 2
            elif isinstance(target_hardware.parent_hardware, Herolab.RobotCen) or (isinstance(source_hardware, Herolab.RobotCen) and isinstance(target_hardware, SampleHolder.SampleHolder)):
                grip_offset_top = PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT * 1 / 6

            if not self.is_current_grip_from_top:
                if not isinstance(target_hardware.parent_hardware, IkaHotplate.RCTDigital5) and not (target_hardware.parent_hardware is target_hardware and target_deck_position == 4):
                    self._change_grip(container=container, last_pos=last_pos, grip_offset_top=grip_offset_top)
                    last_pos = self.arm.position
                    assert isinstance(last_pos, list)
                    if self.is_current_grip_from_top:
                        angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop[-1][3:6])  # type:ignore[unreachable] # Statement is not unreachable, self.is_current_grip_from_top can change in self._change_grip
                    else:
                        angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeSideways[-1][3:6])
                    last_pos[3:6] = angles[:]  # If the angles are close to +/-180, the sign might change abruptly, leading to "wrong" interpolation -> use only coordinates
                elif isinstance(target_hardware, Herolab.RobotCen):
                    self._change_grip(container=container, last_pos=last_pos, grip_offset_top=grip_offset_top)
                    last_pos = self.arm.position
            else:
                if isinstance(target_hardware.parent_hardware, IkaHotplate.RCTDigital5):
                    grip_offset_sideways: Union[float, None] = PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH / 2
                    self._change_grip(container=container, last_pos=last_pos, grip_offset_sideways=grip_offset_sideways)
                    last_pos = self.arm.position
                    assert isinstance(last_pos, list)
                    if self.is_current_grip_from_top:
                        angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop[-1][3:6])
                    else:
                        angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeSideways[-1][3:6])
                    last_pos[3:6] = angles[:]  # If the angles are close to +/-180, the sign might change abruptly, leading to "wrong" interpolation -> use only coordinates

            if isinstance(target_hardware.parent_hardware, OpentronsOT2.OT2):
                assert isinstance(target_hardware, SampleHolder.SampleHolder)
                offsets = target_hardware.get_coordinates(target_slot_number, rotation_angle=180, invert_y=True, offset_top_left=None)
                z_pos = PathsToHardwareCollection.OT2_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, target_hardware.hardware_definition["dimensions"]["zDimension"])
                if target_deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToOT2Holder1
                elif target_deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToOT2Holder2
                elif target_deck_position == 3:
                    path = PathsToHardwareCollection.InitialPosToOT2Holder3
            elif isinstance(target_hardware.parent_hardware, Bandelin.SonorexDigitecHRC):
                assert isinstance(target_hardware, SampleHolder.SampleHolder)
                offsets = target_hardware.get_coordinates(target_slot_number, rotation_angle=90, invert_y=False)
                z_pos = PathsToHardwareCollection.BATH_SONICATOR_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, target_hardware.hardware_definition["dimensions"]["zDimension"])
                if target_deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToBathSonicator50mLFalconTube
                elif target_deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToBathSonicator15mLFalconTube
            elif isinstance(target_hardware.parent_hardware, IkaHotplate.RCTDigital5):
                assert isinstance(target_hardware, SampleHolder.SampleHolder)
                offsets = target_hardware.get_coordinates(target_slot_number, offset_top_left=None)
                z_pos = PathsToHardwareCollection.HOTPLATE_BASE_HEIGHT_SIDEWAYS + container.container_type.container_height - self.current_grip_height
                if target_deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToHotplate1
                elif target_deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToHotplate2
                elif target_deck_position == 3:
                    path = PathsToHardwareCollection.InitialPosToHotplate3
                elif target_deck_position == 4:
                    path = PathsToHardwareCollection.InitialPosToHotplate4
            elif isinstance(target_hardware, Herolab.RobotCen):
                if container.container_type is ContainerTypeCollection.FALCON_TUBE_50_ML:
                    offsets = (0.0, 0.0, 0.0)
                elif container.container_type is ContainerTypeCollection.FALCON_TUBE_15_ML:
                    offsets = (math.sin(math.radians(31))*6, 0.0, 6.0)           # 15 mL tube adapters 6 mm higher   # Angle of approach 31 degrees
                centrifuge_rotor = target_hardware.rotor_info.rotor_type
                if centrifuge_rotor == 'AF 8.50.3' and self.is_current_grip_from_top:
                    path = PathsToHardwareCollection.InitialPosToCentrifugeRotorAF8503
                elif centrifuge_rotor == 'AF 24.2':
                    raise NotImplementedError
                z_pos = path[-1][2]
            elif target_hardware.parent_hardware is target_hardware:
                assert isinstance(target_hardware, SampleHolder.SampleHolder)
                offsets = target_hardware.get_coordinates(target_slot_number, rotation_angle=90, invert_y=True, offset_top_left={'x0': 0, 'y0': 0, 'z0': None})
                z_pos = PathsToHardwareCollection.TABLE_BASE_HEIGHT + max(container.container_type.container_height - self.current_grip_height, target_hardware.hardware_definition["dimensions"]["zDimension"])
                if target_deck_position == 1:
                    path = PathsToHardwareCollection.InitialPosToSampleHolder1
                elif target_deck_position == 2:
                    path = PathsToHardwareCollection.InitialPosToSampleHolder2
                elif target_deck_position == 3:
                    path = PathsToHardwareCollection.InitialPosToSampleHolder3
                    if container.container_type.container_name == 'FLASK_10_ML' or container.container_type.container_name == 'FLASK_25_ML':
                        z_pos -= 3  # Correct for 10 and 25 mL Flaks sitting deeper in the cork rings
                elif target_deck_position == 4:
                    if self.is_current_grip_from_top:
                        path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksTop
                    else:
                        path = PathsToHardwareCollection.InitialPosToGripChangerHolderFlasksSideways
                        z_pos = PathsToHardwareCollection.TABLE_BASE_HEIGHT_SIDEWAYS + max(container.container_type.container_height - self.current_grip_height, target_hardware.hardware_definition["dimensions"]["zDimension"])
                if self._table_levelling_parameters is not None:  # If there is levelling data, add the deviation from the "default" table base height to z_pos
                    z_pos += XArm6._table_plane((path[-1][0], path[-1][1]), *self._table_levelling_parameters)[0] - PathsToHardwareCollection.TABLE_BASE_HEIGHT
            else:
                z_pos = 0.0
                offsets = (0.0, 0.0, 0.0)
        else:
            is_pick_and_place = False
            z_pos = 0.0
            offsets = (0.0, 0.0, 0.0)

            if isinstance(target_hardware, Hielscher.UP200ST) or isinstance(target_hardware, Electromagnet.Electromagnet) or isinstance(target_hardware, SwitchingValve.SwitchingValve) or isinstance(target_hardware, CapperDecapper.CapperDecapper):
                if self.is_current_grip_from_top:
                    grip_offset_sideways = None
                    if isinstance(target_hardware, CapperDecapper.CapperDecapper):
                        grip_offset_sideways = 80.0
                    self._change_grip(container=container, last_pos=last_pos, grip_offset_sideways=grip_offset_sideways)
                    last_pos = self.arm.position
                    assert isinstance(last_pos, list)
                    if self.is_current_grip_from_top:
                        angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeTop[-1][3:6])
                    else:
                        angles = list(PathsToHardwareCollection.InitialPosToGripChangerHolder50mLFalconTubeSideways[-1][3:6])
                    last_pos[3:6] = angles[:]  # If the angles are close to +/-180, the sign might change abruptly, leading to "wrong" interpolation -> use only coordinates
                if isinstance(target_hardware, Hielscher.UP200ST):
                    z_pos = PathsToHardwareCollection.PROBE_SONICATOR_BASE_HEIGHT + min(container.container_type.container_height - self.current_grip_height + PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH - bottom_clearance, PathsToHardwareCollection.PROBE_SONICATOR_MAX_HEIGHT - PathsToHardwareCollection.PROBE_SONICATOR_BASE_HEIGHT)
                    path = PathsToHardwareCollection.GripChangePosToProbeSonicator
                elif isinstance(target_hardware, Electromagnet.Electromagnet) and target_hardware.magnet_number == 0:
                    pass  
                elif isinstance(target_hardware, Electromagnet.Electromagnet) and target_hardware.magnet_number == 1:
                    z_pos = PathsToHardwareCollection.ELECTROMAGNET1_BASE_HEIGHT + min(container.container_type.container_height - self.current_grip_height + PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH - bottom_clearance, PathsToHardwareCollection.ELECTROMAGNET1_MAX_HEIGHT - PathsToHardwareCollection.ELECTROMAGNET1_BASE_HEIGHT - self.current_grip_height + PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH)
                    path = PathsToHardwareCollection.GripChangePosToElectromagnet1
                elif isinstance(target_hardware, SwitchingValve.SwitchingValve):
                    z_pos = PathsToHardwareCollection.NEEDLE_BASE_HEIGHT + min(container.container_type.container_height - self.current_grip_height + PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH - bottom_clearance, PathsToHardwareCollection.NEEDLE_MAX_HEIGHT - PathsToHardwareCollection.NEEDLE_BASE_HEIGHT)
                    path = PathsToHardwareCollection.GripChangePosToValve
                elif isinstance(target_hardware, CapperDecapper.CapperDecapper):
                    z_pos = min(PathsToHardwareCollection.CAPPER_BASE_HEIGHT - self.current_grip_height + PathsToHardwareCollection.GRIPPER_BRACKETS_WIDTH, PathsToHardwareCollection.CAPPER_BASE_HEIGHT)
                    path = PathsToHardwareCollection.GripChangePosToCapperDecapper

        # Path movement to target
        path = [list(i) for i in path]
        path[-1][0] += offsets[0]
        path[-1][1] += offsets[1]
        z_pos += offsets[2]

        if 'FLASK' in container.container_type.container_name and not self.is_current_grip_from_top and isinstance(target_hardware.parent_hardware, IkaHotplate.RCTDigital5) and last_pos[1] < 0:
            # if coming from the left side in a sideways grip and trying to go to the hotplate, take this transition path
            transition_path = [list(i) for i in PathsToHardwareCollection.TransitionPathSidewaysFrontToLeft]
            transition_path.reverse()
            self.arm.move_arc_lines(paths=transition_path, speed=150, times=1, wait=True)
            logger.debug(f'Taken transition path for going to the hotplates from {transition_path[0]} to {transition_path[-1]}', extra=self._logger_dict)
        else:
            # in all other cases, calculate the transition path (if necessary) to go from last pos to new starting point, avoiding self-collision (ignoring the z-coordinate)
            assert isinstance(last_pos, list)
            last_pos[2] = max(path[1][2], last_pos[2])
            self.take_transition_path(last_pos, path[1:])

        if is_pick_and_place:
            if isinstance(target_hardware, Herolab.RobotCen):
                path[-1][2] = z_pos
                self.arm.move_arc_lines(paths=path[1:-1], speed=300, times=1, wait=DEBUG_WAIT)
                self.arm.set_position(*path[-1], speed=150, wait=True)
                self.arm.set_gripper_position(350, wait=True)
                path.reverse()
                self.arm.move_arc_lines(path[:-1], speed=300, times=1, wait=True)
            else:
                self.arm.move_arc_lines(paths=path[1:], speed=300, times=1, wait=DEBUG_WAIT)
                self.arm.set_position(*[path[-1][i] if i != 2 else z_pos for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
                self.arm.set_gripper_position(gripper_pos_open, wait=True)
                self.arm.set_position(*path[-1], wait=DEBUG_WAIT)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
                path.reverse()
                self.arm.move_arc_lines(path[1:-1], speed=200, times=1, wait=True)

        else:
            if isinstance(target_hardware, Hielscher.UP200ST) or isinstance(target_hardware, Electromagnet.Electromagnet) or isinstance(target_hardware, SwitchingValve.SwitchingValve) or isinstance(target_hardware, CapperDecapper.CapperDecapper):
                self.arm.set_position(*[path[1][i] if i != 2 else path[1][2] for i in range(0, len(path[1]))], wait=DEBUG_WAIT)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
                self.arm.move_arc_lines(paths=path[1:], speed=150, times=1, wait=DEBUG_WAIT)
                self.arm.set_position(*[path[-1][i] if i != 2 else z_pos for i in range(0, len(path[-1]))], wait=True)  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument

        logger.info(f'Finished moving robot arm to target destination: {target_hardware}.', extra=self._logger_dict)

        ###############################
        # End path movement to target #
        ###############################

        if is_pick_and_place and isinstance(target_hardware.parent_hardware, IkaHotplate.RCTDigital5):
            # Check if Joint4 is close to its maximum, and if it is, fix it and move to initial pos
            servo_angles = list(self.arm.get_servo_angle(is_radian=False)[1])
            if abs(servo_angles[3]) > 250 or TaskScheduler.HardwareQueues[self].qsize() == 0:
                servo_angles[3] = 0
                servo_angles[4] = 0
                self.arm.set_servo_angle(servo_id=8, angle=servo_angles, speed=50, is_radian=False, wait=True)

            if TaskScheduler.HardwareQueues[self].qsize() == 0:  
                if abs(servo_angles[0]) > 180:
                    self.arm.move_arc_lines(paths=[PathsToHardwareCollection.InitialPosToSampleHolder1[1]], speed=150, times=1, wait=True)
                    servo_angles[0] = 0
                else:
                    servo_angles[5] = 0
                servo_angles = [15.633383, 27.629572, -77.059959, 0, 0, 0, 0.0]  # workaround for arm ocassionaly moving backwards/having "wrong" angles
                self.arm.set_servo_angle(servo_id=8, angle=servo_angles, speed=100, is_radian=False, wait=True)
                self.arm.move_arc_lines(paths=[PathsToHardwareCollection.RestPosToInitialPos[0]], speed=150, times=1, wait=True)
                self.is_in_resting_pos = True

        return self.is_okay()


    @staticmethod
    def get_triangle_parameters(p1: Union[Tuple[float | int, ...], List[float | int], np.ndarray], p2: Union[Tuple[float | int, ...], List[float | int], np.ndarray], p3: Union[Tuple[float | int, ...], List[float | int], np.ndarray]) -> Tuple[float, float, np.ndarray, np.ndarray, bool, bool]:
        """
        Calculates some parameters of a triangle defined by the three points p1, p2, and p3

        Parameters
        ----------
        p1 : Union[Tuple[float | int, ...], List[float | int], np.ndarray]
            The first point of the triangle (2D or 3D).
        p2 : Union[Tuple[float | int, ...], List[float | int], np.ndarray]
            The second point of the triangle (2D or 3D).
        p3 : Union[Tuple[float | int, ...], List[float | int], np.ndarray]
            The third point of the triangle (2D or 3D).

        Returns
        -------
        Tuple[float, float, np.ndarray, np.ndarray, bool, bool]
            The length of the vector p1-p2, the height, the coordinates of the foot point of p3 above the side defined by p1 and p2, the angle between (p3-p1) and (p3-p2), whether the foot point is between p1 and p2, and whether the orientation of p1->p3->p2 is clockwise.
        """
        if len(p1) > 3 or len(p2) > 3 or len(p3) > 2:
            raise NotImplementedError('Method only works for 2D or 3D triangles')

        p1 = np.asarray(p1)
        p2 = np.asarray(p2)
        p3 = np.asarray(p3)

        va = p1 - p3
        vb = p2 - p3
        vc = p2 - p1

        a = np.sqrt(va.dot(va))
        b = np.sqrt(vb.dot(vb))
        c = np.sqrt(vc.dot(vc))

        # get orientation of p1->p3->p2: val > 0 -> cw; val < 0: ccw; val == 0: colinear
        val = (float(p3[1] - p1[1]) * (p2[0] - p3[0])) - (float(p3[0] - p1[0]) * (p2[1] - p3[1]))
        is_clockwise = (val > 0)
        # if p1->p3->p2 is clockwise, then p1->p2 is counter-clockwise and vice versa, but the angle of xarm servo 1 decreases for clockwise rotation, so the sign is correct
        if abs(val) > 1e-5:
            val = val / abs(val)
            gamma = val * np.arccos(va.dot(vb) / (a * b))
        else:
            gamma = math.pi

        if c == 0:
            return 0, a, p1, gamma, True, is_clockwise
        else:
            if gamma == math.pi:
                return c, 1e-5, 1e-5 * np.asarray([-math.sin(math.atan(vc[1] / vc[0])), math.cos(math.atan(vc[1] / vc[0]))]), gamma, True, is_clockwise
            else:
                fhc = p2 + (-vb).dot(vc) / c * vc / c
                # check whether fhc is between p1 and p2
                is_fhc_between_p1_p2 = min(p1[0], p2[0]) <= fhc[0] and max(p1[0], p2[0]) >= fhc[0] and min(p1[1], p2[1]) <= fhc[1] and max(p1[1], p2[1]) >= fhc[1]
                return c, np.sqrt(fhc.dot(fhc)), fhc, gamma, is_fhc_between_p1_p2, is_clockwise

    def take_transition_path(self, current_position: Union[Tuple[float | int, ...], List[float | int], np.ndarray], next_path: Union[Tuple[Tuple[Union[float, int], ...], ...], List[List[Union[float, int]]]], center_point: Union[Tuple[float | int, float | int, float | int], List[float | int], np.ndarray] = (0, 0, 0), num: int = 5, minimum_distance: float = PathsToHardwareCollection.MIN_DISTANCE_FROM_Z_AXIS) -> bool:
        """
        Take a transition path when going from the current position to the beginning of the next planned path while keeping a minimum distance of minimum_distance from center_point and making sure that Joint 1 does not exceed its limits.

        Parameters
        ----------
        current_position : Union[Tuple[float | int, ...], List[float | int], np.ndarray]
            The starting point of the path ([x, y, z, roll, pitch, yaw]).
        next_path : Union[Tuple[Tuple[Union[float, int], ...], ...], List[List[Union[float, int]]]]
            The end point of the path ([x, y, z, roll, pitch, yaw]).
        center_point: Union[Tuple[float | int, float | int, float | int], List[float | int], np.ndarray]
            The center point which is to be avoided. Default is (0, 0, 0)
        num : int = 5
            The number of points to insert. Default is 5.
        minimum_distance : float = PathsToHardwareCollection.MIN_DISTANCE_FROM_Z_AXIS
            The minimum distance from the center point when going from start_point to end_point.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        EPSILON = 5 * (math.pi / 180)  # 5 degrees
        p3 = np.asarray(center_point[0:2])
        current_position = current_position[:6]
        end_point = next_path[0][:6]
        c, hc, fhc, alpha, is_inside, is_clockwise = XArm6.get_triangle_parameters(current_position[0:2], end_point[0:2], center_point[0:2])
        if not (hc < minimum_distance and is_inside and num > 0):
            return True

        # Before reading the servo angle, make sure that the arm has reached the position (by calling move to current position with wait=True)
        self.arm.move_arc_lines([current_position], wait=True)
        servo_angle = self.arm.get_servo_angle(servo_id=1, is_radian=True)[1]

        common_z = max(current_position[2], end_point[2])
        target_point = next_path[-1]
        _, _, _, beta, _, _ = XArm6.get_triangle_parameters(end_point[0:2], target_point[0:2], center_point[0:2])  # Take into account that this point later also needs to be reached without exceeding joint limits

        if abs(servo_angle + alpha + beta) <= 2 * math.pi - EPSILON and abs(servo_angle + alpha) <= 2 * math.pi - EPSILON:
            p4 = (p3 + fhc / np.sqrt(fhc.dot(fhc)) * minimum_distance).tolist()
            gamma = 2 * math.acos(hc / minimum_distance) / (num + 1)
        else:
            p4 = (p3 - fhc / np.sqrt(fhc.dot(fhc)) * minimum_distance).tolist()
            gamma = (2 * math.pi - 2 * math.acos(hc / minimum_distance)) / (num + 1)

        _, _, _, _, _, is_clockwise = XArm6.get_triangle_parameters(current_position[0:2], p4, center_point[0:2])
        tmp = p3 + XArm6.rot_mat_2d((-1) ** int(is_clockwise) * (num + 1) * gamma / 2) @ p4

        transition_path = [[*current_position, 50]]
        for i in range(1, num + 1):
            transition_path.append([*(p3 + XArm6.rot_mat_2d((-1) ** int(not is_clockwise) * i * gamma) @ tmp).tolist(), common_z, *[(1-i/(num + 1)) * current_position[j] + (i / (num + 1)) * end_point[j] for j in range(3, 6)], 50])
        transition_path.append([*end_point, 50])
        self.arm.set_position(*[transition_path[0][i] if i != 2 else common_z for i in range(0, len(transition_path[0]))], wait=DEBUG_WAIT)  # Go up first, then follow the transition path  # Workaround for Bug in xArm Python SDK (1.11.6) using old x and y positions when providing only z as an argument
        self.arm.move_arc_lines(paths=transition_path, speed=150, times=1, wait=True)

        logger.debug(f'Taken transition path from {current_position} to {end_point}', extra=self._logger_dict)

        return self.is_okay()

    @staticmethod
    def rot_mat_2d(gamma: float) -> np.ndarray:
        """
        Calculates and returns the 2D Rotation Matrix for ccw rotation about an angle gamma in radians

        Parameters
        ----------
        gamma : float
            The rotation angle in radians.

        Returns
        -------
        np.ndarray
            the 2D Rotation Matrix for ccw rotation about an angle gamma in radians.
        """
        return np.array([[math.cos(gamma), -math.sin(gamma)], [math.sin(gamma), math.cos(gamma)]])

    @TaskScheduler.scheduled_task
    def return_to_initial_position(self, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Returns the robot arm to its initial position

        Parameters
        ----------
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
            True if successful, False otherwise
        """
        if self.is_in_resting_pos:
            return True

        path = [list(i) for i in PathsToHardwareCollection.RestPosToInitialPos]
        path.reverse()
        self.arm.move_arc_lines(path, speed=300, times=1, wait=True)
        self.is_in_resting_pos = True

        return self.is_okay()

    def is_okay(self) -> bool:
        """Returns True if the arm has no errors, or False otherwise. If a collision was detected, an emergency stop request is sent"""
        i = 0
        # workaround for move_arclines returning early (even with wait=True) -> check if arm is still in motion
        while i < 5:  # Make sure that 5 consecutive readings indicate stopped motion   
            state_code = self.arm.get_state()
            if state_code != (0, 1):  # (0, 1) means in motion)
                i += 1
            else:
                i = 0
            time.sleep(0.1)

        err_warn_code = self.arm.get_err_warn_code()
        if err_warn_code != (0, [0, 0]):
            # if err_warn_code == (0, [31, 0]):  # (0, [31, 0]) means abnormal current, probably due to collision:
            if err_warn_code[0] != 0 or err_warn_code[1][0] != 0:  # format is (api_code, (err_code, warn_code)); if api code is not 0 (success) or there is an error code, perform an emergency stop (ignore warn codes for now)
                XArm6.EMERGENCY_STOP_REQUEST = True
                logger.critical('Robot arm error occured. Emergency stop requested.', extra=self._logger_dict)
                Minerva.API.MinervaAPI.Configuration.request_emergency_stop()
                return False
        return True

    def emergency_stop(self) -> None:
        """Performs an emergency stop."""
        self.arm.emergency_stop()

   
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
        self.is_current_grip_from_top = kwargs_dict.pop('is_current_grip_from_top', True)
        self.is_in_resting_pos = kwargs_dict.pop('is_in_resting_pos', True)
        self.current_grip_height = kwargs_dict.pop('current_grip_height', PathsToHardwareCollection.GRIPPER_BRACKETS_HEIGHT / 2)
        return True

    def shut_off(self) -> None:
        self.arm.reset(wait=True)
        self.arm.disconnect()
