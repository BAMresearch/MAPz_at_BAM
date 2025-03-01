#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import inspect
import json
import queue
import sys
import threading
import os.path
import time
from enum import Enum
from functools import total_ordering

from abc import ABC, abstractmethod, ABCMeta
from dataclasses import dataclass, field
from typing import NamedTuple, Union, Tuple, List, Dict, TYPE_CHECKING, Optional, Any, TypeVar, Type, Iterator, Callable, Iterable

import serial

from Minerva.API import MinervaAPI

if TYPE_CHECKING:
    from MinervaAPI import Chemical, Container


class PathNames(Enum):
    """Enum class with Path Names"""
    ROOT_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    LOG_DIR: str = os.path.join(ROOT_DIR, 'Logs')
    CONFIG_DIR: str = os.path.join(ROOT_DIR, 'Configuration')
    CHARACTERIZATION_DIR: str = os.path.join(ROOT_DIR, 'Characterization')
    OT2_TEMP_DIR: str = os.path.join(ROOT_DIR, 'OT2_Temp_Protocols')
    SPECTRAMAX_TEMP_DIR: str = os.path.join(ROOT_DIR, 'Spectramax_Temp_Protocols')
    ZETASIZER_DATABASE_DIR: str = os.path.join('C:\\', 'users', 'WS10003-minerva', 'Documents', 'Malvern Instruments', 'ZS XPLORER', 'Working File', 'ZetasizerWorkingFile.db')


class TaskScheduler(ABC):
    EMERGENCY_STOP_REQUEST: bool = False
    shut_down: bool = False
    default_priority: int = 10
    default_blocking_behavior: bool = True
    task_group_waiting_list: List[Tuple[int, float, TaskGroupSynchronizationObject]] = []
    task_group_waiting_list_lock: threading.Lock = threading.Lock()
    task_scheduler_global_event = threading.Condition()
    HardwareQueues: Dict[Hardware, queue.PriorityQueue[PrioritizedItem]] = {}
    ConsumerThreads: Dict[Hardware, threading.Thread] = {}

    @staticmethod
    def scheduled_task(func: Callable) -> Callable:
        """
        Decorator for automatically using the TaskScheduler with the decorated method.

        Parameters
        ----------
        func: Callable
            The function that is decorated

        Returns
        -------
        Callable
            The result of the wrapped function
        """

        def wrap(*args: Union[Any, None], **kwargs: Union[Any, None]) -> Any:
            """
            Wrapper function for the decorated method.

            Parameters
            ----------
            args: Union[Any, None]
                Positional arguments of the function
            kwargs: Union[Any, None]
                Keyword arguments of the function

            Returns
            -------
            Any
                The return value of the wrapped function if block=True is specified in kwargs or TaskScheduler.default_blocking_behavior=True, otherwise a reference to a queue.Queue object that will receive the return value when done.
            """
            ret_val: queue.Queue = queue.Queue()

            if 'priority' in kwargs.keys() and kwargs['priority'] is not None:
                prio = kwargs['priority']
            else:
                prio = TaskScheduler.default_priority
            if 'block' in kwargs.keys() and kwargs['block'] is not None:
                block = kwargs['block']
            else:
                block = TaskScheduler.default_blocking_behavior
            if 'is_sequential_task' in kwargs.keys() and kwargs['is_sequential_task'] is not None:
                seq = kwargs['is_sequential_task']
            else:
                seq = True
            if 'task_group_synchronization_object' in kwargs.keys() and kwargs['task_group_synchronization_object'] is not None:
                tgso = kwargs['task_group_synchronization_object']
            else:
                tgso = None

            TaskScheduler.add_task(args[0], PrioritizedItem(priority=prio, task=func, task_group_synchronization_object=tgso, is_blocking_task=block, is_sequential_task=seq, args=args, kwargs=kwargs, result=ret_val))

            if block:
                return ret_val.get()
            else:
                return ret_val

        return wrap

    @staticmethod
    def register_object(hardware: Hardware) -> None:
        """
        Static method to register a new Object with this class. Called from the __post__init__ function of the Hardware superclass

        Parameters
        ----------
        hardware: Hardware
            The Object to register in this class

        Returns
        -------
        None
        """
        if hardware not in TaskScheduler.HardwareQueues.keys() and not isinstance(hardware, SampleHolderHardware):
            TaskScheduler.HardwareQueues[hardware] = queue.PriorityQueue()
            TaskScheduler.start_new_consumer_thread(hardware)

    @staticmethod
    def start_new_consumer_thread(hardware: Hardware) -> None:
        """
        Static method to start a new consumer thread that will read from a queue associated with a piece of hardware and execute the tasks

        Parameters
        ----------
        hardware: Hardware
            The Hardware object that is handled by the thread

        Returns
        -------
        None
        """
        if TaskScheduler.EMERGENCY_STOP_REQUEST or TaskScheduler.shut_down:
            return
        t = threading.Thread(target=TaskScheduler.process_queue, args=(hardware,), daemon=True)
        TaskScheduler.ConsumerThreads[hardware] = t
        t.start()

    @staticmethod
    def process_queue(hardware: Hardware) -> None:
        """
        Static method to process the next item in a queue

        Parameters
        ----------
        hardware: Hardware
            The Hardware object that is handled by the method

        Returns
        -------
        None
        """
        while not TaskScheduler.shut_down and not TaskScheduler.EMERGENCY_STOP_REQUEST:
            # Get the next job for this hardware from its queue
            next_job = TaskScheduler.HardwareQueues[hardware].get()
            tgso = next_job.task_group_synchronization_object

            if tgso is None:  # if the job does not have a tgso, execute it right away and return to the top
                ret_val = next_job.task(*next_job.args, **next_job.kwargs)
                next_job.result.put(ret_val)
                TaskScheduler.HardwareQueues[hardware].task_done()
                continue
            else:  # otherwise, if the task is sequential, acquire the synchronization condition, perform the task, and if it is the final task, return to the top for the next iteration....
                if next_job.is_sequential_task:
                    with tgso.sync_condition:
                        ret_val = next_job.task(*next_job.args, **next_job.kwargs)
                        next_job.result.put(ret_val)
                        TaskScheduler.HardwareQueues[hardware].task_done()
                else:
                    ret_val = next_job.task(*next_job.args, **next_job.kwargs)
                    next_job.result.put(ret_val)
                    TaskScheduler.HardwareQueues[hardware].task_done()

                if tgso.is_final_task[hardware].is_set():
                    continue

            # ... or else add the task group it is about to enter into the task_group waiting list (if not in there already) ...
            with TaskScheduler.task_group_waiting_list_lock:
                if tgso not in [i[2] for i in TaskScheduler.task_group_waiting_list]:
                    TaskScheduler.task_group_waiting_list.append((next_job.priority, time.time(), tgso))
                    TaskScheduler.task_group_waiting_list.sort(key=lambda task: task[0:2])
                    with TaskScheduler.task_scheduler_global_event:
                        TaskScheduler.task_scheduler_global_event.notify_all()

            # ... and enter a blocking while loop to wait for either all other hardware from the task group becoming available, or for something more urgent coming up
            while tgso is not None and not tgso.is_final_task[hardware].is_set() and not TaskScheduler.EMERGENCY_STOP_REQUEST:
                # In this blocking while loop, if the current task group is not active yet, wait for any updates...
                TaskScheduler.task_scheduler_global_event.acquire()
                TaskScheduler.task_scheduler_global_event.notify_all()
                TaskScheduler.task_scheduler_global_event.wait()
                TaskScheduler.task_scheduler_global_event.notify_all()
                TaskScheduler.task_scheduler_global_event.release()
                if not tgso.is_currently_active.is_set():
                    # When awakened, check if there are other task groups waiting that require this hardware as well
                    TaskScheduler.task_group_waiting_list_lock.acquire()
                    for j in TaskScheduler.task_group_waiting_list:
                        i = j[2]
                        if i == tgso:  # if the current tgso is encountered first, keep it and leave the loop
                            break
                        # if the hardware is listed in this tgso, and is not done with it already, and it is a different tgso, remove the is_ready flag from the current tgso, add the request to join the current tgso back to queue, and join the next tgso
                        if hardware in i.is_final_task.keys() and not i.is_final_task[hardware].is_set() and not tgso.is_final_task[hardware].is_set() and i != tgso:
                            with tgso.sync_condition:
                                tgso.is_ready[hardware].clear()
                            TaskScheduler._wait_for_entering_taskgroup(hardware, task_group_synchronization_object=tgso, block=False)
                            with tgso.sync_condition:
                                tgso.sync_condition.notify_all()
                            with i.sync_condition:
                                i.is_ready[hardware].set()
                                i.sync_condition.notify_all()
                            tgso = i
                            with TaskScheduler.task_scheduler_global_event:
                                TaskScheduler.task_scheduler_global_event.notify_all()
                            break
                    TaskScheduler.task_group_waiting_list_lock.release()
                    continue  # go back to the top with the updated tgso
                else:
                    if tgso.is_final_task[hardware].is_set():
                        with TaskScheduler.task_scheduler_global_event:
                            TaskScheduler.task_scheduler_global_event.notify_all()
                        break

                    # Check for pending tasks from this tgso
                    ret = TaskScheduler.check_for_tasks_from_taskgroup(TaskScheduler.HardwareQueues[hardware], tgso)
                    if ret is not None and not TaskScheduler.EMERGENCY_STOP_REQUEST:
                        if ret.is_sequential_task:
                            with tgso.sync_condition:
                                ret_val = ret.task(*ret.args, **ret.kwargs)
                                ret.result.put(ret_val)
                                TaskScheduler.HardwareQueues[hardware].task_done()
                        else:
                            ret_val = ret.task(*ret.args, **ret.kwargs)
                            ret.result.put(ret_val)
                            TaskScheduler.HardwareQueues[hardware].task_done()

    @staticmethod
    def check_for_tasks_from_taskgroup(task_queue: queue.PriorityQueue[PrioritizedItem], task_group_synchronization_object: TaskGroupSynchronizationObject) -> Optional[PrioritizedItem]:
        """
        Static method to find a PrioritizedItem holding a specified TaskGroupSynchronizationObject in a queue

        Parameters
        ----------
        task_queue: queue.PriorityQueue[PrioritizedItem]
            The task queue that is searched
        task_group_synchronization_object: TaskGroupSynchronizationObject
            The TaskGroupSynchronizationObject to find in the queue

        Returns
        -------
        Optional[PrioritizedItem]
            The PrioritizedItem holding the specified TaskGroupSynchronizationObject if found in the queue, None otherwise
        """
        q: List[PrioritizedItem] = []
        while not task_queue.empty():
            tmp = task_queue.get()
            if tmp.task_group_synchronization_object is not None and tmp.task_group_synchronization_object == task_group_synchronization_object:
                # If the item is from the same task group put all other items back in the priority queue and return it
                for i in q:
                    task_queue.put(i)
                return tmp
            else:
                q.append(tmp)  # Otherwise, put the item in a temporary array and check the next item

        # If nothing was found, put all items back in the priority queue and return None
        for i in q:
            task_queue.put(i)
        return None

    @staticmethod
    def add_task(hardware: Hardware, task: PrioritizedItem) -> Any:
        """
        Static method to add a new task to a hardware queue.

        Parameters
        ----------
        hardware: Hardware
            The Hardware object that is handled by the thread
        task: PrioritizedItem
            The task that is added to the hardware queue

        Returns
        -------
        A queue.Queue object that will receive the return value when done.
        """
        if TaskScheduler.EMERGENCY_STOP_REQUEST or TaskScheduler.shut_down:
            return False
        TaskScheduler.HardwareQueues[hardware].put(task)
        with TaskScheduler.task_scheduler_global_event:
            TaskScheduler.task_scheduler_global_event.notify_all()
        return task.result

    @staticmethod
    def add_event_if_necessary(hardware: Hardware, task_group_synchronization_object: TaskGroupSynchronizationObject) -> None:
        """
        Adds an event for the specified hardware to the specified task group synchronization object in case it does not have an event for is_final_task or is_ready in its task_group_synchronization_object yet; if it has one that has already been set it will be cleared.

        Parameters
        ----------
        hardware: Hardware
            The Hardware object for which a new Event is created
        task_group_synchronization_object:TaskGroupSynchronizationObject
            The TaskGroupSynchronizationObject that holds the sync condition and events

        Returns
        -------
        None
        """
        with task_group_synchronization_object.sync_condition:
            if hardware not in task_group_synchronization_object.is_final_task.keys():
                task_group_synchronization_object.is_final_task[hardware] = threading.Event()
            elif hardware in task_group_synchronization_object.is_final_task.keys() and task_group_synchronization_object.is_final_task[hardware].is_set():
                task_group_synchronization_object.is_final_task[hardware].clear()
            if hardware not in task_group_synchronization_object.is_ready.keys():
                task_group_synchronization_object.is_ready[hardware] = threading.Event()
            elif hardware in task_group_synchronization_object.is_ready.keys() and task_group_synchronization_object.is_ready[hardware].is_set():
                task_group_synchronization_object.is_ready[hardware].clear()

    @staticmethod
    def wait_for_hardware(hardware: Union[Iterable[Hardware], Hardware], task_group_synchronization_object: TaskGroupSynchronizationObject) -> None:
        """
        Waits until all the indicated hardware components entered the taskgroup of the task_group_synchronization_object. For each hardware, it creates an event for each hardware if necessary and posts a wait_for_entering_taskgroup task asynchronously to the task scheduler. Then it waits synchronously for each hardware to enter the task group.

        Parameters
        ----------
        hardware: Union[Iterable[Hardware], Hardware]
            The Hardware object(s) which need to enter the task group before proceeding
        task_group_synchronization_object:TaskGroupSynchronizationObject
            The TaskGroupSynchronizationObject of the task group all hardware needs to enter

        Returns
        -------
        None
        """
        if not isinstance(hardware, Iterable):
            hardware = [hardware]

        for h in hardware:
            TaskScheduler.add_event_if_necessary(h, task_group_synchronization_object)
            TaskScheduler._wait_for_entering_taskgroup(h, task_group_synchronization_object=task_group_synchronization_object, block=False, priority=TaskScheduler.default_priority)

        task_group_synchronization_object.sync_condition.acquire()
        while True:
            if all([r.is_set() for r in task_group_synchronization_object.is_ready.values()]):
                task_group_synchronization_object.is_currently_active.set()
                task_group_synchronization_object.sync_condition.release()
                break
            task_group_synchronization_object.sync_condition.wait()

        with TaskScheduler.task_scheduler_global_event:
            TaskScheduler.task_scheduler_global_event.notify_all()

    @staticmethod
    def finish_task_group_and_release_all(task_group_synchronization_object: TaskGroupSynchronizationObject) -> None:
        """
        Sets the events for all hardware from the task_group_synchronization_object, signalling that the task group is done and releasing all hardware from it.

        Parameters
        ----------
        task_group_synchronization_object:TaskGroupSynchronizationObject
            The TaskGroupSynchronizationObject of the task group from which all hardware should be released

        Returns
        -------
        None
        """
        with TaskScheduler.task_group_waiting_list_lock:
            for i in TaskScheduler.task_group_waiting_list:
                if i[2] == task_group_synchronization_object:
                    TaskScheduler.task_group_waiting_list.remove(i)
        with task_group_synchronization_object.sync_condition:
            task_group_synchronization_object.is_currently_active.clear()
            for e in task_group_synchronization_object.is_final_task.values():
                if not e.is_set():
                    e.set()
            for e in task_group_synchronization_object.is_ready.values():
                if not e.is_set():
                    e.set()
        with TaskScheduler.task_scheduler_global_event:
            TaskScheduler.task_scheduler_global_event.notify_all()

    @staticmethod
    def release_hardware(hardware: Union[Hardware, List[Hardware]], task_group_synchronization_object: TaskGroupSynchronizationObject) -> None:
        """
        Releases the hardware from the tgso.

        Parameters
        ----------
        hardware: Union[Hardware, List[Hardware, ...]]
            The hardware (or a list of hardware) that should be released
        task_group_synchronization_object:TaskGroupSynchronizationObject
            The TaskGroupSynchronizationObject of the task group from which the hardware should be released

        Returns
        -------
        None
        """
        if not isinstance(hardware, list):
            hardware = [hardware]

        for h in hardware:
            if h in task_group_synchronization_object.is_final_task.keys():
                with task_group_synchronization_object.sync_condition:
                    task_group_synchronization_object.is_final_task[h].set()
        with TaskScheduler.task_scheduler_global_event:
            TaskScheduler.task_scheduler_global_event.notify_all()

    @staticmethod
    @scheduled_task.__func__  # type: ignore  # mypy issue 11211); also no longer necessary in python >= 3.10
    def _wait_for_entering_taskgroup(hardware: Hardware, task_group_synchronization_object: TaskGroupSynchronizationObject, block: bool = False, is_sequential_task: bool = True, priority: int = default_priority) -> bool:
        """
        Dummy method to create an "empty" task that signals when the hardware is ready to process the task group. If called with block=False, the task scheduler will return a queue object for which the caller can wait with the get() method, and that should become true once this method gets processed. If associated with a tgso, the caller can also wait on the SyncCondition of the tgso and will be notified when the item is processed.

        Parameters
        ----------
        hardware: Hardware
            The Hardware object for which the empty task is created
        task_group_synchronization_object:TaskGroupSynchronizationObject
            The TaskGroupSynchronizationObject that belongs to the task group that should be entered
        block: bool
            Should always be set to False
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int
            Should at least be equal to the priorities of the other tasks in the task group

        Returns
        -------
        bool
            Set to true when the task scheduler processes this task (signalling that the hardware is now ready to process this task group)
        """
        with task_group_synchronization_object.sync_condition:
            task_group_synchronization_object.is_ready[hardware].set()
            task_group_synchronization_object.sync_condition.notify_all()
        with TaskScheduler.task_scheduler_global_event:
            TaskScheduler.task_scheduler_global_event.notify_all()
        return True


@dataclass
class TaskGroupSynchronizationObject:
    """
    Dataclass holding items that are required to synchronize tasks belonging to the same group in the task scheduler:
    sync_condition: threading.Condition
    is_final_task: Dict[Hardware, threading.Event]
    is_currently_active: threading.Event
    is_ready: Dict[Hardware, threading.Event]
    """
    sync_condition: threading.Condition
    is_final_task: Dict[Hardware, threading.Event]
    is_currently_active: threading.Event
    is_ready: Dict[Hardware, threading.Event]


@dataclass(order=True)
class PrioritizedItem:
    """Dataclass holding items that are added to a priorityQueue of the task scheduler"""
    priority: int
    task: Callable = field(compare=False)
    task_group_synchronization_object: TaskGroupSynchronizationObject = field(compare=False)
    is_blocking_task: bool = field(compare=False)
    is_sequential_task: bool = field(compare=False)
    args: Any = field(compare=False)
    kwargs: Any = field(compare=False)
    result: queue.Queue = field(compare=False)


@dataclass
class PathsToHardwareCollection(ABC):
    """Class with absolute height offsets and Paths for the robot arm. Last point should be the position of slot 1 before applying offsets.
    Format of the paths: [[x, y, z, roll, pitch, yaw, radius], ....]
    radius > 0 -> Arc, radius = 0 -> sharp turn, no deceleration, radius < 0 -> sharp turn, complete stop"""
    GRIPPER_BRACKETS_HEIGHT: float = 40.0
    GRIPPER_BRACKETS_WIDTH: float = 32.0
    TABLE_BASE_HEIGHT: float = 171.8     # mean of zpos_max and zpos_min from table levelling data
    TABLE_BASE_HEIGHT_SIDEWAYS: float = 12.0
    TABLE_MIN_HEIGHT_SIDEWAYS: float = 35
    OT2_BASE_HEIGHT: float = 236.5
    HOTPLATE_BASE_HEIGHT: float = 255
    HOTPLATE_BASE_HEIGHT_SIDEWAYS: float = 98.5
    PROBE_SONICATOR_BASE_HEIGHT: float = 448
    PROBE_SONICATOR_MAX_HEIGHT: float = 568
    BATH_SONICATOR_BASE_HEIGHT: float = 353
    ELECTROMAGNET1_BASE_HEIGHT: float = 545
    ELECTROMAGNET1_MAX_HEIGHT: float = 662
    NEEDLE_MAX_HEIGHT: float = 671
    NEEDLE_BASE_HEIGHT: float = 544
    CAPPER_BASE_HEIGHT: float = 301 - 20  # 301 is "real" base height, give it an extra 20 mm (corresponding to the gripper bracket width) for the final "slow" approach
    CAPPER_MAX_HEIGHT: float = 321
    GRIP_CHANGER_MIN_HEIGHT_SIDEWAYS: float = 43
    SAFE_HEIGHT: float = 600.0
    MIN_DISTANCE_FROM_Z_AXIS: float = 200  # in mm

    RestPosToInitialPos: Tuple[Tuple[int | float, ...], ...] = (
        (207, 0, 112, 180, 0, 0, 0),
        (207, 0, SAFE_HEIGHT, 180, 0, -90, 100),
    )
    InitialPosToOT2Holder1: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (0, -360, 468, 180, 0, -90, 50),
        (197 + 13.89, -604.5 - 17.74, 460, 180, 0, -90, 0),   # Top left well of 15 x 15mL holder (no offsets): (197, -604.5, 460)
    )
    InitialPosToOT2Holder2: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (0, -360, 468, 180, 0, -90, 50),
        (64 + 13.89, -604.5 - 17.74, 460, 180, 0, -90, 0),  # Top left well of 15 x 15mL holder (no offsets): (64, -604.5, 460)
    )
    InitialPosToOT2Holder3: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (0, -360, 468, 180, 0, -90, 50),
        (-69 + 13.89, -604.5 - 17.74, 460, 180, 0, -90, 0),  # Top left well of 15 x 15mL holder (no offsets): (-69, -604.5, 460)
    )
    InitialPosToSampleHolder1: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (0, 207, SAFE_HEIGHT, 180, 0, -90, 100),
        (-80.6, 215, 500, 180, 0, -90, 0),
    )
    InitialPosToSampleHolder2: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (0, 207, SAFE_HEIGHT, 180, 0, -90, 100),
        (-224.6, 205, 500, 180, 0, -90, 0),
    )
    InitialPosToSampleHolder3: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (0, 207, SAFE_HEIGHT, 180, 0, -90, 100),
        (-343.9, 518, 450, 180, 0, -90, 100),
    )
    InitialPosToHotplate3: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (527, 230, 280, 0, -90, -89, 50),
        (207.1, 250, 280, 0, -90, -89, 50),
        (203.2, 391, 280, 0, -90, -89, 50),
    )
    InitialPosToHotplate2: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (527, 230, 280, 0, -90, -89, 50),
        (384.3, 250, 280, 0, -90, -89, 50),
        (376.6, 391, 280, 0, -90, -89, 50),
    )
    InitialPosToHotplate1: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (527, 230, 280, 0, -90, -89, 50),
        (552.5, 391.2, 280, 0, -90, -89, 50),
    )
    InitialPosToCentrifugeRotorAF8503: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (442, 0, 400, 155, 0, -90, 100),
        (443.3, 0, 236, 155, 0, -90, 0),
        (298.3, -3.8, -72.5, 155, 0, -90, 0),
    )
    InitialPosToGripChangerHolder50mLFalconTubeSideways: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, -90, -90, 90, 10),
        (-72.5, -356, SAFE_HEIGHT, -90, -90, 90, 0),
    )
    InitialPosToGripChangerHolder50mLFalconTubeTop: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (-233.2, -356, SAFE_HEIGHT, 180, 0, -90, 0),
    )
    InitialPosToGripChangerHolder15mLFalconTubeSideways: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, -90, -90, 90, 10),
        (-72.5, -381.5, SAFE_HEIGHT, -90, -90, 90, 0),
    )
    InitialPosToGripChangerHolder15mLFalconTubeTop: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (-233.2, -382.3, SAFE_HEIGHT, 180, 0, -90, 0),
    )
    InitialPosToGripChangerHolderFlasksSideways: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, -90, -90, 90, 10),
        (-70.5, -296.9, SAFE_HEIGHT, -90, -90, 90, 0),
    )
    InitialPosToGripChangerHolderFlasksTop: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (-231.3, -296.3, SAFE_HEIGHT, 180, 0, -90, 0),
    )
    InitialPosToValveOutlet: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
    )
    InitialPosToBathSonicator50mLFalconTube: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (-430.5, -290, 565, 180, 0, -90, 0),
    )
    InitialPosToBathSonicator15mLFalconTube: Tuple[Tuple[int | float, ...], ...] = (
        RestPosToInitialPos[-1],
        (30, -207, SAFE_HEIGHT, 180, 0, -90, 10),
        (-394.2, -283.3, 565, 180, 0, -90, 0),
    )
    GripChangePosToProbeSonicator: Tuple[Tuple[int | float, ...], ...] = (
        InitialPosToGripChangerHolderFlasksSideways[1],
        (-224.0, -200, 360, -90, -90, 90, 0),
    )
    GripChangePosToElectromagnet1: Tuple[Tuple[int | float, ...], ...] = (
        InitialPosToGripChangerHolderFlasksSideways[1],
        (-90, -294, 360, -90, -90, 90, 0),
        (-150, -190, 360,  -90, -90, 90, 30),
        (-218, -131, 360,  -90, -90, 90, 30),
        (-143, 555, 450,  -90, -90, 90, 0),
        (-143, 555, 545,  -90, -90, 90, 0),
    )
    GripChangePosToValve: Tuple[Tuple[int | float, ...], ...] = (
        InitialPosToGripChangerHolderFlasksSideways[1],
        (-90, -294, 360, -90, -90, 90, 0),
        (-170, -184, 360, -90, -90, 90, 50),
        (-233, -1.9, 460, -90, -90, 90, 50),
    )
    GripChangePosToCapperDecapper: Tuple[Tuple[int | float, ...], ...] = (
        InitialPosToGripChangerHolderFlasksSideways[1],
        (-104, -243.4, 200, -62, -90, 90, 50),
        (-270.1, -331.7, 200, -62, -90, 90, 10),
    )
    TransitionPathSidewaysFrontToLeft: Tuple[Tuple[int | float, ...], ...] = (
        (527, 230, 280, 0, -90, -89, 100),
        (300, 150, SAFE_HEIGHT, -137, -90, -90, 100),
        (225, 0, SAFE_HEIGHT, -156, -90, -141, 50),
        (30, -207, SAFE_HEIGHT, -90, -90, 90, 10),
    )
    TransitionPathSidewaysFrontToRight: Tuple[Tuple[int | float, ...], ...] = (
        (527, 230, 280, 0, -90, -89, 100),
        (200, 200, 400, 0, -90, -89, 50),
        (150, 230, 400, 0, -90, -89, 50),
    )


class HardwareTypeDefinitions(Enum):
    """Enum class with predefined hardware types"""
    HotplateHardware = 'HotplateHardware'
    AdditionHardware = 'AdditionHardware'
    CentrifugeHardware = 'CentrifugeHardware'
    RobotArmHardware = 'RobotArmHardware'
    SampleHolderHardware = 'SampleHolderHardware'
    SonicatorHardware = 'SonicatorHardware'
    CapperDecapperHardware = 'CapperDecapperHardware'
    ElectromagnetHardware = 'ElectromagnetHardware'
    CameraHardware = 'CameraHardware'
    ClampHardware = 'ClampHardware'
    FanHardware = 'FanHardware'
    SensorHardware = 'SensorHardware'
    CharacterizationInstrumentHardware = 'CharacterizationInstrumentHardware'
    ControllerHardware = 'ControllerHardware'
    OtherHardware = 'OtherHardware'


class AbstractClassIterMeta(ABCMeta):
    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        for k, v in vars(self).items():
            if not k.startswith('_') and not callable(getattr(self, k)):
                yield k, v


class ConfigurationMeta(AbstractClassIterMeta):
    def __str__(self) -> str:
        """Returns a formatted, printable string of the configuration."""
        max_len = 0
        repr_string = f'Configuration:\n==============\n'
        for i, j in self:
            for k in j:
                max_len = max(len(k), max_len)

        for i, j in self:
            if len(j) > 0:
                repr_string += f"{''.join(' ' + char if char.isupper() else char.strip() for char in i).strip()}:\n"
                for k, v in j.items():
                    repr_string += f'\t{k:{max_len}} : {v}\n'

        return repr_string


class HardwareMeta(ABCMeta):
    def __call__(cls: ABCMeta, *args: Any, **kwargs: Any) -> Hardware:
        # Before creating a new instance, check if a "similar" instance is already registered, and if so, return the existing instance instead
        duplicate = HardwareMeta._check_for_duplicates(cls, *args, **kwargs)
        if duplicate is None:
            obj = type.__call__(cls, *args, **kwargs)
            obj.__post__init__()
            return obj
        else:
            return duplicate

    def _check_for_duplicates(cls: ABCMeta, *args: Any, **kwargs: Any) -> Union[Hardware, None]:
        """Checks if a "similar" instance is already registered in the configuration"""
        # recreate the mapping from the args and kwargs to the signature of the constructor
        tmp_kwargs_dict = kwargs.copy()
        tmp_constructor_signature = [i for i in inspect.signature(cls.__init__).parameters]  # type: ignore
        for i, a in enumerate(args):
            tmp_kwargs_dict[tmp_constructor_signature[i+1]] = a

        tmp_string_rep = cls.__name__
        if 'valve_number' in tmp_kwargs_dict.keys():
            tmp_string_rep = f'{tmp_string_rep}{tmp_kwargs_dict["valve_number"]}'

        if 'com_port' in tmp_kwargs_dict.keys():
            tmp_string_rep = f'{tmp_string_rep}@{tmp_kwargs_dict["com_port"]}'
        elif 'ip_address' in tmp_kwargs_dict.keys():
            tmp_string_rep = f'{tmp_string_rep}@{tmp_kwargs_dict["ip_address"]}'
        elif 'arduino_controller' in tmp_kwargs_dict.keys():
            if 'parent_hardware' in tmp_kwargs_dict.keys():
                tmp_string_rep = f'{tmp_string_rep}@{tmp_kwargs_dict["parent_hardware"]}'
            tmp_string_rep = f'{tmp_string_rep}@{tmp_kwargs_dict["arduino_controller"]}'
        else:
            if 'hardware_definition' in tmp_kwargs_dict.keys():
                if not isinstance(tmp_kwargs_dict["hardware_definition"], dict):
                    if isinstance(tmp_kwargs_dict["hardware_definition"], SampleHolderDefinitions):
                        hardware_definition_str = tmp_kwargs_dict["hardware_definition"].value
                    else:
                        hardware_definition_str = str(tmp_kwargs_dict["hardware_definition"])
                    tmp_kwargs_dict["hardware_definition"] = json.load(open(hardware_definition_str))

                tmp_string_rep = tmp_kwargs_dict["hardware_definition"]["metadata"]["displayName"]
                if tmp_string_rep == '':
                    tmp_string_rep = 'SampleHolder'
            if 'deck_position' not in tmp_kwargs_dict.keys() or tmp_kwargs_dict['deck_position'] is None:
                pass
            elif 'parent_hardware' not in tmp_kwargs_dict.keys():
                tmp_string_rep = f'{tmp_string_rep}->deck {tmp_kwargs_dict["deck_position"]}'
            else:
                tmp_string_rep = f'{tmp_string_rep} at {tmp_kwargs_dict["parent_hardware"]}->deck {tmp_kwargs_dict["deck_position"]}'

        # Check if a "similar" Hardware is already registered (consider them similar if they have the same string representation):
        for i in MinervaAPI.Configuration:
            for k, v in i[1].items():
                if str(v) == tmp_string_rep:
                    return v
        return None


class Hardware(metaclass=HardwareMeta):
    """Abstract base class for all hardware."""
    def __init__(self, hardware_type: HardwareTypeDefinitions = HardwareTypeDefinitions.OtherHardware) -> None:
        self._parent_hardware: Union[Hardware, HotplateHardware, AdditionHardware, CentrifugeHardware, ControllerHardware, RobotArmHardware, SampleHolderHardware, SonicatorHardware] = self
        self._deck_position: Union[int, None] = None
        self.hardware_type = hardware_type

    def __post__init__(self) -> None:
        """Executed after the __init__ function."""
        MinervaAPI.Configuration.register_object(self)  # Only register the object if it was successfully created
        MinervaAPI.TaskScheduler.register_object(self)  # Only register the object if it was successfully created

    @property
    def parent_hardware(self) -> Union[Hardware, HotplateHardware, AdditionHardware, CentrifugeHardware, ControllerHardware, RobotArmHardware, SampleHolderHardware, SonicatorHardware]:
        return self._parent_hardware

    def dump_configuration(self) -> Dict[str, Any]:
        """Dump all current instance vars in a json-serializable dict. Override if some of your instance variables need other functionality (see OT2 for an example)."""
        return dict([(k, v) if _is_json_serializable(v) else (k, str(v)) if isinstance(v, Enum) else (k, f'{type(v)}-{id(v)}') for k, v in vars(self).items()])

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
        pass

    def __str__(self) -> str:
        """Function returning a human-readable string description of the class."""
        tmp = self.__class__.__name__
        if hasattr(self, 'valve_number'):
            tmp = f'{tmp}{self.valve_number}'

        if hasattr(self, 'com_port'):
            return f'{tmp}@{self.com_port}'
        elif hasattr(self, 'ip_address'):
            return f'{tmp}@{self.ip_address}'
        elif hasattr(self, 'arduino_controller'):
            if self.parent_hardware is not None and self.parent_hardware is not self:
                tmp = f'{tmp}@{self.parent_hardware}'
            return f'{tmp}@{self.arduino_controller}'
        else:
            if hasattr(self, 'hardware_definition'):
                tmp = self.hardware_definition["metadata"]["displayName"]
                if tmp == '':
                    tmp = 'SampleHolder'
            if self._deck_position is None:
                return f'{tmp}'
            elif self._parent_hardware is self:
                return f'{tmp}->deck {self._deck_position}'
            else:
                return f'{tmp} at {self._parent_hardware}->deck {self._deck_position}'


class AdditionHardware(Hardware, ABC):
    """Abstract base class for addition hardware."""
    def __init__(self) -> None:
        super(AdditionHardware, self).__init__(hardware_type=HardwareTypeDefinitions.AdditionHardware)

    @abstractmethod
    def add(self, chemical: Union[Chemical, List[Chemical], Tuple[Chemical, ...]], target_container: Container, withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Override this method to implement the addition with this hardware.

        Parameters
        ----------
        chemical: Union[Chemical, List[Chemical], Tuple[Chemical, ...]]
            A chemical or list of chemicals that is added to the target container
        target_container: Container
            The target container to which the chemical is added.
        withdraw_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are withdrawn. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        addition_rate: Union[FlowRate, float, str, None, List[Union[FlowRate, float, str, None]]] = None
            Rate at which the chemical(s) are added. If a float is provided, it is assumed to be in milliliters per minute. If set to None, the default rate is used. Default is None.
        block: bool = MinervaAPI.TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = MinervaAPI.TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.


        Returns
        -------
        bool
            True if successful, False otherwise
        """
        pass


class CentrifugeHardware(Hardware, ABC):
    """Abstract base class for centrifugation hardware."""

    def __init__(self) -> None:
        super(CentrifugeHardware, self).__init__(hardware_type=HardwareTypeDefinitions.CentrifugeHardware)

    @abstractmethod
    def start_centrifugation(self, run_time: Union[int, None], speed: Union[int, None], temperature: Union[int, None] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """Override this method to implement starting a centrifugation with this hardware.

        run_time: Union[int, None]
            The centrifugation time in seconds. If set to None, the current time setpoint is used. Default is None.
        speed: Union[int, None]
            The centrifugation speed in rpm. If set to None, the current speed setpoint is used. Default is None.
        temperature: Union[int, None] = None
            The centrifugation temperature in degrees Celsius. If set to None, the current temperature setpoint is used. Default is None.
        block: bool = MinervaAPI.TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = MinervaAPI.TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        pass


class HotplateHardware(Hardware, ABC):
    """Abstract base class for hotplates/magnetic stirrers hardware."""

    def __init__(self) -> None:
        super(HotplateHardware, self).__init__(hardware_type=HardwareTypeDefinitions.HotplateHardware)
        self.stable_temperature_reached = threading.Event()

    @abstractmethod
    def heat(self, heating_temperature: float, heating_time: float, stirring_speed: Optional[float] = None, temperature_stabilization_time: Optional[float] = None, maximum_temperature_deviation: Optional[float] = None, cooldown_temperature: Optional[float] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Override this method to implement starting the heating/stirring with this hardware.

        Parameters
        ----------
        heating_temperature: float
            The temperature to which this container is heated (in degrees Celsius)
        heating_time: float
            The amount of time for which the container is heated/stirred (in seconds)
        stirring_speed: Optional[float]
            The stirring speed during heating (in rpm) if the heating device supports stirring
        temperature_stabilization_time: Optional[float]
            Time (in seconds) for how long the temperature has to stay within maximum_temperature_deviation degrees from the target temperature to be considered stable
        maximum_temperature_deviation: Optional[float]
            Maximum deviation from the target temperature that is still considered as "stable" during the stabilization time
        cooldown_temperature: Optional[float]
            After the heating_time elapsed, wait until the temperature falls below this setpoint (in degrees Celsius) for at least as long as temperature_stabilization_time
        block: bool = MinervaAPI.TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = MinervaAPI.TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
            True if successful, false otherwise
        """
        pass


class RobotArmHardware(Hardware, ABC):
    """Abstract base class for robot arm hardware."""

    def __init__(self) -> None:
        super(RobotArmHardware, self).__init__(hardware_type=HardwareTypeDefinitions.RobotArmHardware)

    @abstractmethod
    def move(self, container: Container, target_hardware: Hardware, target_deck_position: int = 0, target_slot_number: int = 0, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Override this method with your own implementation for moving a container to a different hardware.

        Parameters
        ----------
        container : Container
            The container which should be moved.
        target_hardware : Hardware
            The sample holder (or hardware if the hardware does not have an associated sample holder) to which the container should be moved.
        target_deck_position : int, default = 0
            Optional deck position of the holder (or the valve position when hardware is a syringe pump) to which the container should be moved. If the target_hardware is a SampleHolder, the deck position of the holder will be used. Default is 0.
        target_slot_number : int, default = 0
            Optional number of the slot of the holder (for holders with several slots) to which the container should be moved, default is 0
        block: bool = MinervaAPI.TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = MinervaAPI.TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Other Parameters
        ----------------
        kwargs
            Any additional hardware-specific parameters your robot arm will need to know to execute the movement, passed as keyword arguments

        Returns
        -------
        bool
            True if the container was moved successfully, False otherwise
        """
        pass


class SonicatorHardware(Hardware, ABC):
    """Abstract base class for Sonicator hardware."""

    def __init__(self) -> None:
        super(SonicatorHardware, self).__init__(hardware_type=HardwareTypeDefinitions.SonicatorHardware)

    @abstractmethod
    def start_sonication(self, sonication_time: Optional[float] = None, sonication_power: Optional[float] = None, sonication_amplitude: Optional[float] = None, sonication_temperature: Optional[float] = None, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None) -> bool:
        """
        Starts the sonication with the supplied or previously set setpoints

        Parameters
        ----------
        sonication_time: Optional[float] = None
            The amount of time for which the container is sonicated (in seconds)
        sonication_power: Optional[float] = None
            The sonication power in percent (between 0 and 100)
        sonication_amplitude: Optional[float] = None
            The sonication amplitude in percent (between 0 and 100)
        sonication_temperature: Optional[float] = None
            The temperature during sonication (in degrees Celsius)
        block: bool = MinervaAPI.TaskScheduler.default_blocking_behavior
            Whether to wait for the result of this call or return a reference to a queue.Queue object that will hold the result (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_blocking_behavior.
        is_sequential_task: bool = True
            If set to True, this task will only start after the currently running task from the same task group has finished. Likewise, the next sequential task from the same task group will also wait for this task to finish first. This is the intended behavior in most cases. Default is True.
        priority: int = MinervaAPI.TaskScheduler.default_priority
            Priority of this task (when decorated with MinervaAPI.TaskScheduler.scheduled_task). Default is configured in MinervaAPI.TaskScheduler.default_priority.
        task_group_synchronization_object: Optional[TaskGroupSynchronizationObject] = None
            An object holding a threading.Condition() and threading.Event() instance that can be used to keep tasks across different hardware grouped together in the task scheduler (e.g., for adding or removing liquid or probe sonicating the liquid in the open container after decapping). Default is None.

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        pass


class ControllerHardware(Hardware, ABC):
    """Abstract base class for other hardware controllers (such as Arduino)."""

    def __init__(self) -> None:
        super(ControllerHardware, self).__init__(hardware_type=HardwareTypeDefinitions.ControllerHardware)


class SampleHolderHardware(Hardware, ABC):
    """Abstract base class for sample holder hardware."""

    def __init__(self) -> None:
        super(SampleHolderHardware, self).__init__(hardware_type=HardwareTypeDefinitions.SampleHolderHardware)
        self.available_slots: Dict[int, Union[str, None]] = {}
        self._hardware_definition: Any = {}

    @property
    def deck_position(self) -> int:
        return self._deck_position

    @property
    def hardware_definition(self) -> Any:
        return self._hardware_definition

    @abstractmethod
    def get_coordinates(self, slot_number: int, offset_top_left: Union[Tuple[float, ...], List[float], dict, None] = (0.0, 0.0, 0.0), rotation_angle: float = 0, invert_y: bool = True) -> Union[Tuple[float, float, float], None]:
        """
        Override this method with your own implementation to get the coordinates of a slot number of a sample holder.

        Parameters
        ----------
        slot_number: int
            The number of the slot in the holder (starting at 1, counting from top left)
        offset_top_left:  Union[Tuple[float, ...], List[float, ...], dict, None] = (0.0, 0.0, 0.0)
            Optional offset to be added to all positions. If None, the offset is read from the json file used when creating the instance. If dict, has to have the keys x0, y0, and z0.
        rotation_angle: float = 0
            Optional counterclockwise rotation angle in degrees about the z-Axis of the holder to match the returned coordinates with the robot coordinate system. Typically, the longer side is along the x-Axis. Default is 0.
        invert_y: bool = True
            Optional value indicating to invert the y coordinates (should be used when spacings are positive and slot 1 is in the top left corner)

        Returns
        -------
        Union[Tuple[float, float, float], None]
            A tuple containing the x, y, and z coordinates of the slot in the specified holder, or None if an invalid slot number was given
        """
        pass

    @abstractmethod
    def get_next_free_slot(self) -> Union[int, None]:
        """
        Override this method to implement getting the number of the next free slot in this hardware.

        Returns
        -------
        Union[int, None]
            An integer of the next free slot, or None if no free slots are available in the holder
        """
        pass


@dataclass
class ContainerTypeCollection(ABC):
    """Collection of Container Types."""
    class ContainerDescription(NamedTuple):
        """
        Class derived from Named Tuple for describing containers.

        Parameters
        ----------
        container_name : str
            The name of the container. The container_name string should also be in the metadata tags of the corresponding sample holder hardware definition.
        container_height : float
            The height the container in Millimeter
        container_max_volume : float
            The maximum volume of the container in Milliliter
        """
        container_name: str
        container_height: float
        container_max_volume: float
        container_diameter: float

    FALCON_TUBE_15_ML = ContainerDescription('FALCON_TUBE_15_ML', 120, 15, 16)  # Labsolute Conical Tube
    FALCON_TUBE_50_ML = ContainerDescription('FALCON_TUBE_50_ML', 115, 50, 28)  # Labsolute Conical Tube
    FLASK_10_ML = ContainerDescription('FLASK_10_ML', 70, 10, 35)  # Labsolute Round-Bottom Flask
    FLASK_25_ML = ContainerDescription('FLASK_25_ML', 85, 25, 41)  # Labsolute Round-Bottom Flask
    FLASK_50_ML = ContainerDescription('FLASK_50_ML', 90, 50, 51)  # Labsolute Round-Bottom Flask
    FLASK_100_ML = ContainerDescription('FLASK_100_ML', 105, 100, 64)  # Labsolute Round-Bottom Flask
    FLASK_250_ML = ContainerDescription('FLASK_250_ML', 140, 250, 85)  # Labsolute Round-Bottom Flask
    FLASK_500_ML = ContainerDescription('FLASK_500_ML', 163, 500, 105)  # Labsolute Round-Bottom Flask
    EPPENDORF_TUBE_2_ML = ContainerDescription('EPPENDORF_TUBE_2_ML', 40, 2, 10.5)  # Eppendorf Tube

class SampleHolderDefinitions(Enum):
    """Enum class with the file paths to the hardware definitions of the individual holders"""

    Isolab_15mL_Foldable_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Isolab_15mL_Foldable_Tube_Rack.json')
    Isolab_15mL_Push_and_Hold_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Isolab_15mL_Push-and-Hold_Tube_Rack.json')
    Isolab_50mL_Foldable_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Isolab_50mL_Foldable_Tube_Rack.json')
    Isolab_50mL_Push_and_Hold_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Isolab_50mL_Push-and-Hold_Tube_Rack.json')
    Opentrons_15mL_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_15mL_Tube_Rack.json')
    Opentrons_50mL_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_50mL_Tube_Rack.json')
    Opentrons_10mL_Flask_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_10mL_Flask_Rack.json')
    Opentrons_25mL_Flask_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_25mL_Flask_Rack.json')
    Opentrons_50mL_Flask_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_50mL_Flask_Rack.json')
    Opentrons_100mL_Flask_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_100mL_Flask_Rack.json')
    Opentrons_250mL_Flask_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_250mL_Flask_Rack.json')
    Opentrons_2mL_Eppendorf_Tube_Rack = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Opentrons_2mL_Eppendorf_Tube_Rack.json')
    Corning_96_Wellplate_360ul_flat = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Corning_96_Wellplate_360ul_flat.json')
    Labsolute_96_Tip_Rack_1000uL = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Labsolute_96_Tip_Rack_1000uL.json')
    Ika_10mL_Heating_Block = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Ika_10mL_Heating_Block.json')
    Ika_25mL_Heating_Block = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Ika_25mL_Heating_Block.json')
    Ika_50mL_Heating_Block = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Ika_50mL_Heating_Block.json')
    Ika_100mL_Heating_Block = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Ika_100mL_Heating_Block.json')
    Ika_250mL_Heating_Block = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Ika_250mL_Heating_Block.json')
    Ika_500mL_Heating_Block = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Ika_500mL_Heating_Block.json')
    Corkring_Small = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Corkring_Small.json')
    Grip_Change_Holder_15mL_Conical_Tubes = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Grip_Change_Holder_15mL_Conical_Tubes.json')
    Grip_Change_Holder_50mL_Conical_Tubes = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Grip_Change_Holder_50mL_Conical_Tubes.json')
    Bath_Sonicator_Holder_50mL = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Bath_Sonicator_Holder_50mL_Conical_Tubes_Push-and-Hold.json')
    Bath_Sonicator_Holder_15mL = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Bath_Sonicator_Holder_15mL_Conical_Tubes_Push-and-Hold.json')
    Flask_Station = os.path.join(PathNames.ROOT_DIR.value, 'SampleHolder', 'Flask_Station.json')


class RotorInfo(NamedTuple):
    """
    Class holding the information of a rotor.
    """
    rotor_id: str
    mg_count: int
    code_1: int
    code_2: int
    code_3: int
    code_4: int
    rotor_type: str
    bottle_number: int
    max_rpm: int
    first_position: int
    numbering_is_clockwise: bool = True
    steps_per_slot: float = 0
    radius_in_mm: float = 100

    @classmethod
    def from_string(cls, rotor_info_string: str, steps_per_revolution: int = 25600) -> RotorInfo:
        """
        Class Method for constructing the class directly from the string returned when using the serial command 'NRROTm'.

        Parameters
        ----------
        rotor_info_string : str
            The string to be parsed.
        steps_per_revolution : int = 25600
            Optional parameter specifying the number of steps for one full revolution of the rotor, default is 25600

        Returns
        -------
        RotorInfo
            An instance of the class with the fields filled with their respective values from the string.
        """
        rotor_info_list = rotor_info_string.strip(' ').strip('\t').strip('\r').strip('\n').split(',')
        if rotor_info_list[6] == 'AF 8.50.3':
            numbering_is_clockwise = True
            radius_in_mm = 104
        elif rotor_info_list[6] == 'AF 24.2':
            numbering_is_clockwise = False
            radius_in_mm = 100
        else:
            numbering_is_clockwise = True  # default value
            radius_in_mm = 100
        steps_per_slot = steps_per_revolution / float(rotor_info_list[7])

        return cls(*[val if ind in [0, 6] else int(val) for ind, val in enumerate(rotor_info_list)], numbering_is_clockwise=numbering_is_clockwise, steps_per_slot=steps_per_slot, radius_in_mm=radius_in_mm)  # type: ignore


class Unit(NamedTuple):
    """
    Class derived from Named Tuple for defining units.

    Parameters
    ----------
    id : int
        An ID value for the units.
    string_representations : Tuple[str, ...]
        The string representations of the units.
    conversion_factor : float
        The factor used for converting the unit to SI base units.
    """
    id: int
    string_representations: Tuple[str, ...]
    conversion_factor: float


@total_ordering
class Quantity(ABC):
    """
    Abstract class from which classes specifying a quantity are derived (density, volume, mass, etc.)

    Parameters
    ----------
    value : float
        The numerical value of the quantity in the given unit (cannot be negative).
    unit : str
        The string representation of the unit used for the quantity. Has to be defined in the units of the class.

    Raises
    ------
    AssertionError
        If a negative value is entered.
    """
    units: list[Unit]

    def __init__(self, value: float, unit: str):
        assert value >= 0, "Value has to be >= 0."
        for u in self.units:
            if unit.lower() in map(str.lower, u.string_representations):
                break
        else:
            raise AssertionError('Invalid unit. Please make sure the unit is defined in the class.')

        self.value = value
        self._unit = unit

    @classmethod
    def from_string(cls: Type[T], quantity_string: str) -> T:
        """
        Alternative constructor working with a single string that contains both the value and the unit

        Parameters
        ----------
        quantity_string: str
            A single string that contains both the value and the unit

        Returns
        -------
        Quantity
            An instance of the class constructed from the string
        """
        quantity_string = quantity_string.replace(' ', '').strip()
        ind = [char.isalpha() for char in quantity_string].index(True)
        return cls(float(quantity_string[:ind]), quantity_string[ind:])

    @property
    def unit(self) -> str:
        return self._unit

    def in_si(self) -> float:
        """
        Returns the value of the quantity in the SI base unit, without changing any values of the instance itself. Use convert_to to change the value and unit of this instance in place.

        Returns
        -------
        float
            The value in the SI base unit, or None if the conversion fails.

        Raises
        ------
        ValueError
            If the conversion fails (usually because of an invalid unit)
        """
        for u in self.units:
            if self._unit.lower() in map(str.lower, u.string_representations):
                return self.value * u.conversion_factor
        raise ValueError

    def in_unit(self, target_unit: str) -> float:
        """
        Returns the value of the quantity in the specified unit, without changing any values of the instance itself. Use convert_to to change the value and unit of this instance in place.

        Parameters
        ----------
        target_unit : str
            The string representation of the target unit (has to be defined in the classes Unit field).

        Returns
        -------
        float
            The value in the target unit, or None if the conversion fails (due to the target value not being defined).

        Raises
        ------
        ValueError
            If the conversion fails (usually because of an invalid target unit)
        """
        for u in self.units:
            if target_unit.lower() in map(str.lower, u.string_representations):
                si_value = self.in_si()
                if si_value is not None:
                    return si_value / u.conversion_factor
        raise ValueError

    def convert_to(self: T, target_unit: str) -> T:
        """
        Converts the value and unit of this instance in place, and returns the instance with updated values. Use in_unit to just returns the value of the quantity in the specified unit without changing any values of the instance itself.

        Parameters
        ----------
        target_unit : str
            The string representation of the target unit (has to be defined in the classes Unit field).

        Returns
        -------
        Quantity
            The same instance with the value and unit changed in place.
        """
        for u in self.units:
            if target_unit.lower() in map(str.lower, u.string_representations):
                self.value = self.in_si()/u.conversion_factor
                self._unit = target_unit
                break
        return self

    def __add__(self, other: Union[Quantity, int, float], keep_original_unit: bool = True) -> float:
        """
        Add method for adding a number or another quantities to this quantity. If two quantities are added and the units are different, the unit for the first value is used by default for the result.
        Parameters
        ----------
        other : Union[Quantity, int, float]
            The number or quantity to be added.
        keep_original_unit: bool = True
            If True, the result will be returned in the unit of the first Quantity, if False and the second value is also a Quantity, the unit of the second Quantity will be used.

        Returns
        -------
        float
            The result of the addition.

        """
        if isinstance(other, Quantity):
            if keep_original_unit:
                return self.value + other.in_unit(self._unit)
            else:
                return self.in_unit(other._unit) + other.value
        else:
            return self.value + other

    def __sub__(self, other: Union[Quantity, int, float], keep_original_unit: bool = True) -> float:
        """
        Subtract method for subtracting a number or another quantities to this quantity. If two quantities are subtracted and the units are different, the unit for the first value is used by default for the result.
        Parameters
        ----------
        other : Union[Quantity, int, float]
            The number or quantity to be subtracted.
        keep_original_unit: bool = True
            If True, the result will be returned in the unit of the first Quantity, if False and the second value is also a Quantity, the unit of the second Quantity will be used.

        Returns
        -------
        float
            The result of the subtraction.

        """
        if isinstance(other, Quantity):
            if keep_original_unit:
                return self.value - other.in_unit(self._unit)
            else:
                return self.in_unit(other._unit) - other.value
        else:
            return self.value - other

    def __mul__(self, other: Union[Quantity, int, float]) -> float:
        """
        Muliplication method for multiplying a number or another quantities with this quantity. If both values are Quantities, they will be converted to SI base units first.

        Parameters
        ----------
        other : Union[Quantity, int, float]
            The number or quantity to be multiplied.

        Returns
        -------
        float
            The result of the multiplication.
        """
        if isinstance(other, Quantity):
            return self.in_si() * other.in_si()
        else:
            return self.value * other

    def __truediv__(self, other: Union[Quantity, int, float]) -> float:
        """
        Division method for dividing this quantity by a number or another quantities. If both values are Quantities, they will be converted to SI base units first.

        Parameters
        ----------
        other : Union[Quantity, int, float]
            The number or quantity by which this quantity is divided.

        Returns
        -------
        float
            The result of the division.
        """
        if isinstance(other, Quantity):
            return self.in_si() / other.in_si()
        else:
            return self.value / other

    def __eq__(self, other: object) -> bool:
        """
        Method for comparing this quantity to a number or another quantities. If both values are Quantities, they will be converted to SI base units first, otherwise it will be assumed that they use the same unit

        Parameters
        ----------
        other : object
            The number or quantity to with which equality should be checked.

        Returns
        -------
        bool
            The result of the equality comparison

        Raises
        ------
        NotImplementedError
            If the other object is not a Quantity, int or float
        """
        if isinstance(other, Quantity):
            return self.in_si() == other.in_si()
        elif isinstance(other, int) or isinstance(other, float):
            return self.value == other
        else:
            raise NotImplementedError

    def __lt__(self, other: object) -> bool:
        """
        Method for comparing this quantity to a number or another quantities. If both values are Quantities, they will be converted to SI base units first, otherwise it will be assumed that they use the same unit

        Parameters
        ----------
        other : Union[Quantity, int, float]
            The number or quantity to with which this quantity should be compared.

        Returns
        -------
        bool
            The result of the comparison

        Raises
        ------
        NotImplementedError
            If the other object is not a Quantity, int or float
        """
        if isinstance(other, Quantity):
            return self.in_si() < other.in_si()
        elif isinstance(other, int) or isinstance(other, float):
            return self.value < other
        else:
            raise NotImplementedError

    def __str__(self) -> str:
        """
        Method for giving a string representation of the class instance

        Returns
        -------
        str
            A human-readable string representation of the object
        """
        return f'{self.value} {self._unit}'


class WikidataUnitEnum(Enum):
    """Enum Class with units used by WikiData"""
    GRAM_PER_CUBIC_CENTIMETER: str = 'Q13147228'
    KILOGRAM_PER_CUBIC_METER: str = 'Q844211'
    DALTON: str = 'Q483261'
    KILODALTON: str = 'Q14623804'
    FAHRENHEIT: str = 'Q42289'
    CELSIUS: str = 'Q25267'


class RobotCenRotorEnum(Enum):
    """Enum Class with rotors for the RobotCen centrifuge"""
    AF_24_2: Tuple[str, ...] = ('AF 24.2 fixed angle rotor, 24x1.5/2.2 ml tubes, max. 16000 rpm, 28621 rcf, 100 mm',)
    AF_8_50_3: Tuple[str, ...] = ('AF 8.50.3 fixed angle rotor, aerosol tight, 40°, 8x50 ml conical tubes, max. 13500 rpm, 21191 rcf, 104 mm',)


class Volume(Quantity):
    """Quantity class representing a volume. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('m3', 'm^3', 'cubic meter', 'cubic metre'), conversion_factor=1),
        Unit(id=1, string_representations=('L', 'liter', 'liters', 'litre', 'litres'), conversion_factor=1e-3),
        Unit(id=2, string_representations=('mL', 'ccm', 'mils', 'mills', 'milliliter', 'milliliters', 'millilitre', 'millilitres'), conversion_factor=1e-6),
        Unit(id=3, string_representations=('uL', 'µL', 'microliter', 'microliters', 'microlitre', 'microlitres'), conversion_factor=1e-9),
    ]


class Mass(Quantity):
    """Quantity class representing a mass. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('kg', 'kilogram', 'kilograms'), conversion_factor=1),
        Unit(id=1, string_representations=('g', 'gram', 'grams'), conversion_factor=1e-3),
        Unit(id=2, string_representations=('mg', 'milligram', 'milligrams'), conversion_factor=1e-6),
        Unit(id=3, string_representations=('ug', 'µg', 'microgram', 'micrograms'), conversion_factor=1e-9)
    ]


class MolarAmount(Quantity):
    """Quantity class representing a molar amount. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('mol', 'moles'), conversion_factor=1),
        Unit(id=1, string_representations=('mmol', 'millimol', 'millimoles'), conversion_factor=1e-3),
        Unit(id=2, string_representations=('umol', 'µmol', 'micromol', 'micromoles'), conversion_factor=1e-6)
    ]


class Density(Quantity):
    """Quantity class representing a density. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('kg/m3', 'kg/m^3'), conversion_factor=1),
        Unit(id=1, string_representations=('g/ccm', 'g/cm3', 'g/cm^3', 'g/ml', 'kg/l', 'kg/dm3', 'kg/dm^3'), conversion_factor=1e3),
    ]


class MolarMass(Quantity):
    """Quantity class representing a molar mass. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('kg/mol', 'g/mmol', 'mg/µmol', 'mg/umol', 'kDa', 'kilodalton', 'kilodaltons'), conversion_factor=1),
        Unit(id=1, string_representations=('g/mol', 'mg/mmol', 'µg/µmol', 'ug/umol', 'Da', 'dalton', 'daltons'), conversion_factor=1e-3)
    ]


class Concentration(Quantity):
    """Quantity class representing a concentration. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('mol/m3', 'mol/m^3', 'mmol/L', 'µmol/mL', 'umol/mL', 'mmol/L', 'mM', 'umol/mL', 'µmol/mL'), conversion_factor=1),
        Unit(id=1, string_representations=('mol/L', 'mol/ccm', 'mol/cm3', 'mol/cm^3', 'mmol/mL', 'µmol/µL', 'umol/uL', 'M'), conversion_factor=1e3),
        Unit(id=2, string_representations=('umol/L', 'µmol/L', 'umol/dm3', 'µmol/dm3', 'umol/dm^3', 'µmol/dm^3', 'µM', 'uM'), conversion_factor=1e-3)
    ]


class MassConcentration(Quantity):
    """Quantity class representing a mass concentration. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('mg/mL', 'mg/ccm', 'mg/cm3', 'mg/cm^3', 'g/L', 'g/dm3', 'g/dm^3', 'µg/µL', 'ug/uL', 'kg/m3', 'kg/m^3'), conversion_factor=1),
        Unit(id=1, string_representations=('mg/L', 'µg/mL', 'µg/ccm', 'µg/cm3', 'µg/cm^3', 'ug/mL', 'ug/ccm', 'ug/cm3', 'ug/cm^3', 'g/m3', 'g/m^3'), conversion_factor=1e-3),
    ]


class Time(Quantity):
    """Quantity class representing a time. Units are not case sensitive. Conversion factors are for the conversion to SI base units."""
    units: List[Unit] = [
        Unit(id=0, string_representations=('s', 'sec', 'secs', 'second', 'seconds'), conversion_factor=1),
        Unit(id=1, string_representations=('min', 'mins', 'minute', 'minutes'), conversion_factor=60),
        Unit(id=2, string_representations=('h', 'hr', 'hrs', 'hour', 'hours'), conversion_factor=3600)
    ]


class Temperature(Quantity):
    """Quantity class representing a temperature. Units are not case sensitive. """
    units: List[Unit] = [
        Unit(id=0, string_representations=('C', '.C', '°C', 'degrees', 'centigrades'), conversion_factor=1),
    ]


class RotationSpeed(Quantity):
    """Quantity class representing a rotation speed. Units are not case sensitive. """
    units: List[Unit] = [
        Unit(id=0, string_representations=('rpm',), conversion_factor=1),
        Unit(id=1, string_representations=('rcf', 'g', 'xg'), conversion_factor=1)
    ]


class FlowRate(Quantity):
    """Quantity class representing a flow rate. Units are not case sensitive. """
    units: List[Unit] = [
        Unit(id=0, string_representations=('m3/s', 'm^3/s', 'm3/sec', 'm^3/sec', 'm3/second', 'm^3/second'), conversion_factor=1),
        Unit(id=1, string_representations=('L/s', 'dm3/s', 'dm^3/s', 'cdm/s', 'L/sec', 'dm3/sec', 'dm^3/sec', 'ccd/sec', 'L/second', 'dm3/second', 'dm^3/second', 'cdm/second'), conversion_factor=1e-3),
        Unit(id=2, string_representations=('mL/s', 'cm3/s', 'cm^3/s', 'ccm/s', 'mL/sec', 'cm3/sec', 'cm^3/sec', 'ccm/sec', 'mL/second', 'cm3/second', 'cm^3/second', 'ccm/second'), conversion_factor=1e-6),
        Unit(id=3, string_representations=('µL/s', 'uL/s', 'mm3/s', 'mm^3/s', 'cmm/s', 'µL/sec', 'uL/sec', 'mm3/sec', 'mm^3/sec', 'cmm/sec', 'µL/second', 'uL/second', 'mm3/second', 'mm^3/second', 'cmm/second'), conversion_factor=1e-9),
        Unit(id=4, string_representations=('m3/min', 'm^3/min', 'm3/minute', 'm^3/minute'), conversion_factor=1/60),
        Unit(id=5, string_representations=('L/min', 'dm3/min', 'dm^3/min', 'ccd/min', 'L/minute', 'dm3/minute', 'dm^3/minute', 'cdm/minute'), conversion_factor=1e-3/60),
        Unit(id=6, string_representations=('mL/min', 'cm3/min', 'cm^3/min', 'ccm/min', 'mL/minute', 'cm3/minute', 'cm^3/minute', 'ccm/minute'), conversion_factor=1e-6/60),
        Unit(id=7, string_representations=('µL/min', 'uL/min', 'mm3/min', 'mm^3/min', 'cmm/min', 'µL/minute', 'uL/minute', 'mm3/minute', 'mm^3/minute', 'cmm/minute'), conversion_factor=1e-9/60),
        Unit(id=8, string_representations=('m3/h', 'm^3/h', 'm3/hour', 'm^3/hour'), conversion_factor=1/3600),
        Unit(id=9, string_representations=('L/h', 'dm3/h', 'dm^3/h', 'ccd/h', 'L/hour', 'dm3/hour', 'dm^3/hour', 'cdm/hour'), conversion_factor=1e-3/3600),
        Unit(id=10, string_representations=('mL/h', 'cm3/h', 'cm^3/h', 'ccm/h', 'mL/hour', 'cm3/hour', 'cm^3/hour', 'ccm/hour'), conversion_factor=1e-6/3600),
        Unit(id=11, string_representations=('µL/h', 'uL/h', 'mm3/h', 'mm^3/h', 'cmm/h', 'µL/hour', 'uL/hour', 'mm3/hour', 'mm^3/hour', 'cmm/hour'), conversion_factor=1e-9/3600),
    ]


class BathSonicatorErrorFlags(Enum):
    """Enum Class with Error Flags and their meaning"""
    NOT_ASSIGNED_0: Tuple[int, str] = (0b00000001, '<Not Assigned>')
    TEMPERATURE_SENSOR_ERROR: Tuple[int, str] = (0b00000010, 'Error in Temperature Sensor')
    NOT_ASSIGNED_2: Tuple[int, str] = (0b00000100, '<Not Assigned>')
    TRANSMISSION_ERROR: Tuple[int, str] = (0b00001000, 'Transmission Error')
    NOT_ASSIGNED_4: Tuple[int, str] = (0b00010000, '<Not Assigned>')
    NOT_ASSIGNED_5: Tuple[int, str] = (0b00100000, '<Not Assigned>')
    NOT_ASSIGNED_6: Tuple[int, str] = (0b01000000, '<Not Assigned>')
    NOT_ASSIGNED_7: Tuple[int, str] = (0b10000000, '<Not Assigned>')


class BathSonicatorStatusFlags(Enum):
    """Enum class with Status Flags and their meaning"""
    REMOTE_CONTROL: Tuple[int, str] = (0b0000000000000001, '<reserved> Remote Control')
    SERVICE_MODE: Tuple[int, str] = (0b0000000000000010, '<reserved> Service Mode')
    ULTRASOUND_OR_DEGAS_STARTED: Tuple[int, str] = (0b0000000000000100, 'Ultrasound or Degas started')
    DEGAS_ON: Tuple[int, str] = (0b0000000000001000, 'Degas on')
    HEATING_REGULATION: Tuple[int, str] = (0b0000000000010000, '<reserved> Heating Regulation')
    INTERRUPTION: Tuple[int, str] = (0b0000000000100000, 'Interruption of Ultrasound output (pause)')
    STANDBY: Tuple[int, str] = (0b0000000001000000, 'Standby')
    NOT_ASSIGNED_7: Tuple[int, str] = (0b0000000010000000, '<Not Assigned>')

    ULTRASOUND_POWER_OUTPUT: Tuple[int, str] = (0b0000000100000000, 'Ultrasound Power Output (current output)')
    HEATING_POWER_OUTPUT: Tuple[int, str] = (0b0000001000000000, 'Heating power output')
    CALIBRATION_FUNCTION: Tuple[int, str] = (0b0000010000000000, 'Calibration function: 20ms')
    NOT_ASSIGNED_11: Tuple[int, str] = (0b0000100000000000, '<Not Assigned>')
    NOT_ASSIGNED_12: Tuple[int, str] = (0b0001000000000000, '<Not Assigned>')
    NOT_ASSIGNED_13: Tuple[int, str] = (0b0010000000000000, '<Not Assigned>')
    NOT_ASSIGNED_14: Tuple[int, str] = (0b0100000000000000, '<Not Assigned>')
    NOT_ASSIGNED_15: Tuple[int, str] = (0b1000000000000000, 'Service Function "full access"')


class ProbeSonicatorStatusFlags(Enum):
    """Enum class with Status Flags"""
    READY: int = 1
    ON: int = 2
    OFF: int = 3
    OVERLOAD: int = 4
    FREQUENCY_DOWN: int = 5
    FREQUENCY_UP: int = 6
    READY_AFTER_OVERTEMPERATURE: int = 7
    OVERSCAN: int = 8
    TIME_LIMIT: int = 10
    ENERGY_LIMIT: int = 11
    OVERTEMPERATURE: int = 12
    POWER_LIMIT: int = 14
    OVERTEMPERATURE_TRANSDUCER: int = 15
    TEMPERATURE_LIMIT: int = 20
    WARNING_TEMPERATURE_GENERATOR_HIGH: int = 104
    WARNING_OVERLOAD: int = 105
    WARNING_MALADAPTATION: int = 106
    PERIOD_OFF: int = 107
    TEMPERATURE_LIMIT2: int = 108
    PRESSURE_LIMIT: int = 109
    CALIBRATION_ERROR: int = 110
    WARNING_FREQUENCY_LOW: int = 111
    WARNING_FREQUENCY_HIGH: int = 112
    CALIBRATION: int = 114


class ProbeSonicatorCommands(Enum):
    """Enum class with Probe Sonicator xml commands"""
    ULTRASOUND_ON: str = 'mOn.xml'
    ULTRASOUND_OFF: str = 'mOff.xml'
    ACTIVATE_TEMPERATURE_CONTROL: str = 'tctrlOn.xml'
    DEACTIVATE_TEMPERATURE_CONTROL: str = 'tctrlOff.xml'
    SET_STOP_MODE_FINAL: str = 'stopModeFin.xml'  # Reset
    SET_STOP_MODE_CONTINUE: str = 'stopModeCont.xml'  # Pause
    ACTIVATE_ENERGY_LIMIT: str = 'limitE.xml'
    ACTIVATE_TIME_LIMIT: str = 'limitT.xml'
    DEACTIVATE_ENERGY_AND_TIME_LIMIT: str = 'limitOff.xml'
    SET_AMPLITUDE: str = 'setP.xml?ts1=a&ampl='  # setP.xml?ts1=a&ampl=900 for 90%
    SET_POWER: str = 'setP.xml?ts1=p&pw='  # http://192.168.233.233/setP.xml?ts1=p&pw=1000 for 50%
    SET_PULSE: str = 'setP.xml?cc='  # http://192.168.233.233/setP.xml?cc=700 for 70%
    SET_LOWER_TEMPERATURE_LIMIT: str = 'setP.xml?lTL='  # http://192.168.233.233/setP.xml?lTL=100 for 10°C
    SET_UPPER_TEMPERATURE_LIMIT: str = 'setP.xml?uTL='  # http://192.168.233.233/setP.xml?uTL=700 for 70°C
    SET_ENERGY_LIMIT: str = 'setP.xml?tm='  # http://192.168.233.233/setP.xml?tm=3000 for 300 Ws; PreCondition: limitE.xml is already called, Maximum 42000000 Ws
    SET_TIME_LIMIT: str = 'setP.xml?tm='  # http://192.168.233.233/setP.xml?tm=400 for 40 s; PreCondition: limitT.xml is already called, Maximum 8553600 s
    GET_PROCESS_DATA: str = 'mdata.xml'  # Response: <mdata>status; total power x 10(W); net power x 10(W); amplitude x10(%); energy (Ws); ADC x 10; frequency (Hz); temperature x 10(°C); time(100ms); Controlbits; LimitType; setpower(%) x 20; cycle(%) x 10 </mdata>


class SyringePumpType(Enum):
    """Enum Class with Syringe Pumps and their min and max speed in cm/min"""
    class SyringePumpSpeeds(NamedTuple):
        """
        Class derived from Named Tuple for describing the minimum and maximum speed of the different pump types.

        Parameters
        ----------
        min_speed : float
            The minimum speed of the pump type in cm/min
        max_speed : float
            The maximum speed of the pump type in cm/min
        """
        min_speed: float
        max_speed: float

    AL_1010: SyringePumpSpeeds = SyringePumpSpeeds(0.00014015, 18.36964)
    AL_1050: SyringePumpSpeeds = SyringePumpSpeeds(0.00061, 80.01)


class SyringeParameters(NamedTuple):
    """
    Class derived from Named Tuple for describing the inner diameters in Millimeters and volume in Milliliters of a syringe.

    Parameters
    ----------
    inner_diameter : float
        The inner diameter of the syringe in mm
    volume : float
        The volume of the syringe in mL
    """
    inner_diameter: float
    volume: float


class Syringes(Enum):
    """Enum Class with Syringes"""
    PLASTICSYRINGE_NORMJECT_6ML: SyringeParameters = SyringeParameters(12.5, 6)
    PLASTICSYRINGE_NORMJECT_12ML: SyringeParameters = SyringeParameters(15.9, 12)
    PLASTICSYRINGE_LABSOLUTE_24ML: SyringeParameters = SyringeParameters(19.83, 24)
    GLASS_SYRINGE_SOCOREX_1ML: SyringeParameters = SyringeParameters(6.75, 1)
    GLASS_SYRINGE_SOCOREX_5ML: SyringeParameters = SyringeParameters(12.0, 5)
    GLASS_SYRINGE_SOCOREX_10ML: SyringeParameters = SyringeParameters(14.75, 10)
    GLASS_SYRINGE_SOCOREX_50ML: SyringeParameters = SyringeParameters(28.10, 50)


class PumpUnitsVolume(Enum):
    """Enum Class with volume units used by the pump and their human-readable description"""
    MICROLITERS: tuple[str, str] = ('UL', 'uL')
    MILLILITERS: tuple[str, str] = ('ML', 'mL')


class PumpUnitsRate(Enum):
    """Enum Class with rate units used by the pump and their human-readable description"""
    MICROLITERS_PER_MINUTE: tuple[str, str] = ('UM', 'uL/min')
    MICROLITERS_PER_HOUR: tuple[str, str] = ('UH', 'uL/h')
    MILLILITERS_PER_MINUTE: tuple[str, str] = ('MM', 'mL/min')
    MILLILITERS_PER_HOUR: tuple[str, str] = ('MH', 'mL/h')


@dataclass
class OpenBISInstrumentPermIDs(ABC):
    """Class with PermIDs of instruments from OpenBIS inventory (for setting parent-child-relations)."""
    ZETASIZER_ULTRA_RED: str = '20240514175804717-3108'
    SPECTRAMAX_M3: str = '20240514180732941-3109'


class CustomError(Exception):
    """Custom Exception to be used as a guard clause"""
    pass


def _get_instance_name_from_object(obj: Any, global_dict: Optional[Any] = None) -> str:
    """
    Function to get the first name of a variable from the global scope dict that points to this object

    Parameters
    ----------
    obj : Any
        The object whose name should be retrieved
    global_dict : Optional[str, Any] = None
        The dictionary in which to look for the Object. If None, the global scope of __main__ will be used

    Returns
    -------
    str
        The first name of a "named" variable from the global scope that points to this object, or obj.__repr__ if no variable is found
    """
    if global_dict is None:
        global_list = [(i, j) for i, j in vars(sys.modules['__main__']).items() if ' object at 0x' in repr(j) and not i.startswith('__')]  # Dictionary with variable name mappings from the main namespace
    else:
        global_list = [(i, j) for i, j in globals().items() if ' object at 0x' in repr(j) and not i.startswith('__')]

    for k, v in global_list:
        if v is obj and k != repr(v):  # attempt to find "named" objects
            return k

    return f'{type(obj)}-{id(obj)}'


def _is_json_serializable(obj: Any) -> bool:
    """
    Function to check whether an object is serializable as json.

    Parameters
    ----------
    obj : Any
        The object that should be checked

    Returns
    -------
    bool
        True if the object is serializable, False otherwise
    """
    try:
        json.dumps(obj)
        return True
    except (TypeError, OverflowError):
        return False


T = TypeVar('T', bound='Quantity')
