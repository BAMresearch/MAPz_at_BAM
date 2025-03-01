#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "1.0.0"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"

from __future__ import annotations

import threading
import requests
import logging
import time
import os.path
from typing import Dict, Union, Optional

from Minerva.API.HelperClassDefinitions import SonicatorHardware, ProbeSonicatorStatusFlags, ProbeSonicatorCommands, TaskScheduler, TaskGroupSynchronizationObject, PathNames

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


class UP200ST(SonicatorHardware):
    """
    Class for communication with the Hielscher UP200-ST Probe Sonicator via ethernet.

    Parameters
    ----------
    ip_address : str, default='192.168.233.233'
        The IP Address of the Sonicator (default is '192.168.233.233').

    Raises
    ------
    TimeoutError
        If the Sonicator is not responding to a query of its Status with "On".
    """
    EMERGENCY_STOP_REQUEST = False

    def __init__(self, ip_address: str = '192.168.233.233'):
        """
        Constructor of the UP200ST Class for communication with the Hielscher UP200-ST Probe Sonicator via ethernet.

        Parameters
        ----------
        ip_address : str
            The IP Address of the Sonicator.

        Raises
        ------
        TimeoutError
            If the Sonicator is not responding to a query of its Status with "On".
        """
        super().__init__()
        self.ip_address = str(ip_address)
        self._communication_lock = threading.Lock()
        self._logger_dict = {'instance_name': str(self)}

        response = self._send_request(ProbeSonicatorCommands.GET_PROCESS_DATA.value)
        res = response.replace('<mdata>', '').replace('</mdata>', '').split(';')
        if int(res[0]) > 100 or int(res[0]) == ProbeSonicatorStatusFlags.OVERLOAD.value or int(res[0]) == ProbeSonicatorStatusFlags.OVERTEMPERATURE.value or int(res[0]) == ProbeSonicatorStatusFlags.OVERSCAN.value or int(res[0]) == ProbeSonicatorStatusFlags.OVERTEMPERATURE_TRANSDUCER.value:
            logger.critical(f'Probe Sonicator not ready on {self.ip_address}. Current Process Parameters: {res}', extra=self._logger_dict)
            raise TimeoutError
        else:
            logger.info('Probe Sonicator ready on {}.'.format(self.ip_address), extra=self._logger_dict)

    @TaskScheduler.scheduled_task
    def start_sonication(self, sonication_time: Optional[float] = None, sonication_power: Optional[float] = None, sonication_amplitude: Optional[float] = None, sonication_temperature: Optional[float] = None, log: bool = True, block: bool = TaskScheduler.default_blocking_behavior, is_sequential_task: bool = True, priority: int = TaskScheduler.default_priority, task_group_synchronization_object: TaskGroupSynchronizationObject = None) -> bool:
        """
        Starts the sonication with the supplied or previously set setpoints.

        Parameters
        ----------
        sonication_time: Optional[float] = None
            The amount of time for which the container is sonicated (in seconds)
        sonication_power: Optional[float] = None
            The sonication power in percent (between 0 and 100)
        sonication_amplitude: Optional[float] = None
            The sonication amplitude in percent (between 0 and 100)
        sonication_temperature: Optional[float] = None
            Not supported by this device
        log: bool = True
            Set to False to disable logging for this query. Default is True.
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
            True if the successful, False otherwise
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        if sonication_amplitude is not None:
            if self.set_amplitude(sonication_amplitude) == -1:
                return False
        if sonication_power is not None:
            if self.set_power(sonication_power) == -1:
                return False
        if sonication_time is not None:
            if self.set_time_limit(sonication_time) == -1:
                return False
        if log:
            logger.info('Starting sonication...', extra=self._logger_dict)

        self.ultrasound_on()

        time.sleep(sonication_time)

        ret = self.ultrasound_off()

        if log:
            logger.info('Finished sonication.', extra=self._logger_dict)
        return ret


    def _send_request(self, msg: str, is_polling: bool = False) -> str:
        """
        Sends a request to the sonicator.

        Parameters
        ----------
        msg: str
            The message to send.
        is_polling: bool = False
            Whether the request is part of a regular polling of the device's process parameters (if True, the process will not wait for acquiring the lock if the instrument is busy to give priority to other commands). Derfault is False.

        Returns
        -------
        str
            The answer received from the request.
        """
        url = f'http://{self.ip_address}/{msg}'
        retries = 0
        while retries < 3:
            try:
                if self._communication_lock.locked() and is_polling:
                    return ''

                with self._communication_lock:
                    r = requests.get(url, timeout=0.5)
                return r.text
            except requests.exceptions.Timeout:
                retries += 1
                if retires < 4:
                    logger.warning(f'Timeout occured when sending message {msg}. Retrying ({retries}/3).')

        raise requests.exceptions.Timeout


    def ultrasound_on(self, log: bool = True) -> bool:
        """
        Turns the ultrasound on.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the ultrasound was switched on, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.ULTRASOUND_ON.value)
        res = response.replace('<mon>', '').replace('</mon>', '')
        if res != 'on':
            logger.error('Error turning ultrasound on.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Ultrasound turned on.', extra=self._logger_dict)
            return True

    def ultrasound_off(self, log: bool = True) -> bool:
        """
        Turns the ultrasound off.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the ultrasound was switched off, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.ULTRASOUND_OFF.value)
        res = response.replace('<moff>', '').replace('</moff>', '')
        if res != 'off':
            logger.error('Error turning ultrasound off.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Ultrasound turned off.', extra=self._logger_dict)
            return True

    def activate_temperature_control(self, log: bool = True) -> bool:
        """
        Activates the temperature control.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the temperature control was activated, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.ACTIVATE_TEMPERATURE_CONTROL.value)
        res = response.replace('<tctrl>', '').replace('</tctrl>', '')
        if res != 'ok':
            logger.error('Error activating temperature control.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Temperature control activated.', extra=self._logger_dict)
            return True

    def deactivate_temperature_control(self, log: bool = True) -> bool:
        """
        Deactivates the temperature control.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the temperature control was deactivated, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.DEACTIVATE_TEMPERATURE_CONTROL.value)
        res = response.replace('<tctrl>', '').replace('</tctrl>', '')
        if res != 'ok':
            logger.error('Error deactivating temperature control.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Temperature control deactivated.', extra=self._logger_dict)
            return True

    def set_stop_mode_final(self, log: bool = True) -> bool:
        """
        Sets the Stop Mode to final (reset). In the "Reset" mode energy and time are set to zero when switching on the ultrasound.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the stop mode was set successfully, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.SET_STOP_MODE_FINAL.value)
        res = response.replace('<stopMode>', '').replace('</stopMode>', '')
        if res != 'ok':
            logger.error('Error changing stop mode to final.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Stop mode changed to final.', extra=self._logger_dict)
            return True

    def set_stop_mode_continue(self, log: bool = True) -> bool:
        """
        Sets the Stop Mode to continue (pause). In the "Pause" mode, the values of the time counter and the energy
        input at the resumption of the sonication processes will be continued.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the stop mode was set successfully, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.SET_STOP_MODE_CONTINUE.value)
        res = response.replace('<stopMode>', '').replace('</stopMode>', '')
        if res != 'ok':
            logger.error('Error changing stop mode to continue.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Stop mode changed to continue.', extra=self._logger_dict)
            return True

    def activate_energy_limit(self, log: bool = True) -> bool:
        """
        Activates the energy limit. To set the energy limit value, use the function `set_energy_limit`.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the energy limit was activated, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.ACTIVATE_ENERGY_LIMIT.value)
        res = response.replace('<limit>', '').replace('</limit>', '')
        if res != 'ok':
            logger.error('Error activating energy limit.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Energy limit activated.', extra=self._logger_dict)
            return True

    def activate_time_limit(self, log: bool = True) -> bool:
        """
        Activates the time limit. To set the time limit value, use the function `set_time_limit`.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the time limit was activated, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.ACTIVATE_TIME_LIMIT.value)
        res = response.replace('<limit>', '').replace('</limit>', '')
        if res != 'ok':
            logger.error('Error activating time limit.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Time limit activated.', extra=self._logger_dict)
            return True

    def deactivate_energy_and_time_limit(self, log: bool = True) -> bool:
        """
        Deactivates the energy/time limit.

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        bool
            True if the energy/time limit was deactivated, False otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return False

        response = self._send_request(ProbeSonicatorCommands.DEACTIVATE_ENERGY_AND_TIME_LIMIT.value)
        res = response.replace('<limit>', '').replace('</limit>', '')
        if res != 'ok':
            logger.error('Error deactivating energy/time limit.', extra=self._logger_dict)
            return False
        else:
            if log:
                logger.info('Energy/time limit deactivated.', extra=self._logger_dict)
            return True

    def set_amplitude(self, sonication_amplitude: float, log: bool = True) -> float:
        """
        Sets the amplitude (in %).

        Parameters
        ----------
        sonication_amplitude : float
            The amplitude (in %).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new amplitude (in %) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        response = self._send_request(f'{ProbeSonicatorCommands.SET_AMPLITUDE.value}{int(sonication_amplitude * 10)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing amplitude.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Amplitude changed to {} %.'.format(int(sonication_amplitude*10)/10.0), extra=self._logger_dict)
            return int(sonication_amplitude*10)/10.0

    def set_power(self, sonication_power: float, log: bool = True) -> float:
        """
        Sets the power (in %).

        Parameters
        ----------
        sonication_power : float
            The power (in %).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new power (in %) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        response = self._send_request(f'{ProbeSonicatorCommands.SET_POWER.value}{int(sonication_power * 20)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing power.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Power changed to {} %.'.format(int(sonication_power*20)/20.0), extra=self._logger_dict)
            return int(sonication_power*20)/20.0

    def set_pulse(self, pulse: float, log: bool = True) -> float:
        """
        Sets the pulse (in %).

        Parameters
        ----------
        pulse : float
            The pulse (in %).
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new pulse (in %) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        response = self._send_request(f'{ProbeSonicatorCommands.SET_PULSE.value}{int(pulse * 10)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing pulse.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Pulse changed to {} %.'.format(int(pulse*10)/10.0), extra=self._logger_dict)
            return int(pulse*10)/10.0

    def set_lower_temperature_limit(self, limit: float, activate_limit: bool = True, log: bool = True) -> float:
        """
        Sets the lower temperature limit (in degrees Celsius).

        Parameters
        ----------
        limit : float
            The lower temperature limit (in degrees Celsius).
        activate_limit : bool, default=True
            Whether the limit should also be activated after setting the value (default is True)
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new lower temperature limit (in degrees Celsius) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        if activate_limit:
            self.activate_temperature_control()

        response = self._send_request(f'{ProbeSonicatorCommands.SET_LOWER_TEMPERATURE_LIMIT.value}{int(limit * 10)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing lower temperature limit.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Lower temperature limit changed to {} degrees Celsius.'.format(int(limit*10)/10.0), extra=self._logger_dict)
            return int(limit*10)/10.0

    def set_upper_temperature_limit(self, limit: float, activate_limit: bool = True, log: bool = True) -> float:
        """
        Sets the upper temperature limit (in degrees Celsius).

        Parameters
        ----------
        limit : float
            The upper temperature limit (in degrees Celsius).
        activate_limit : bool, default=True
            Whether the limit should also be activated after setting the value (default is True)
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new upper temperature limit (in degrees Celsius) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        if activate_limit:
            self.activate_temperature_control()

        response = self._send_request(f'{ProbeSonicatorCommands.SET_LOWER_TEMPERATURE_LIMIT.value}{int(limit * 10)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing upper temperature limit.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Upper temperature limit changed to {} degrees Celsius.'.format(int(limit*10)/10.0), extra=self._logger_dict)
            return int(limit*10)/10.0

    def set_energy_limit(self, limit: float, activate_limit: bool = True, log: bool = True) -> float:
        """
        Sets the energy limit (in Ws).

        Parameters
        ----------
        limit : float
            The energy limit (in Ws).
        activate_limit : bool, default=True
            Whether the limit should also be activated after setting the value (default is True)
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new energy limit (in Ws) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        if activate_limit:
            self.activate_energy_limit()

        response = self._send_request(f'{ProbeSonicatorCommands.SET_ENERGY_LIMIT.value}{int(limit * 10)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing energy limit.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Energy limit changed to {} Ws.'.format(int(limit*10)/10.0), extra=self._logger_dict)
            return int(limit*10)/10.0

    def set_time_limit(self, limit: float, activate_limit: bool = True, log: bool = True) -> float:
        """
        Sets the time limit (in s).

        Parameters
        ----------
        limit : float
            The time limit (in s).
        activate_limit : bool, default=True
            Whether the limit should also be activated after setting the value (default is True)
        log: bool = True
            Set to False to disable logging for this query. Default is True.

        Returns
        -------
        float
            The new time limit (in s) if it was set successfully, -1 otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return -1

        if activate_limit:
            self.activate_time_limit(log)

        response = self._send_request(f'{ProbeSonicatorCommands.SET_TIME_LIMIT.value}{int(limit * 10)}')
        res = response.replace('<paramsset>', '').replace('</paramsset>', '')
        if res != 'done':
            logger.error('Error changing time limit.', extra=self._logger_dict)
            return -1
        else:
            if log:
                logger.info('Time limit changed to {} s.'.format(int(limit*10)/10.0), extra=self._logger_dict)
            return int(limit*10)/10.0

    def get_process_data(self, log: bool = True, is_polling: bool = False) -> Dict[str, Union[int, float, str]]:
        """
        Gets the process data and status of the instrument (see `ProbeSonicatorStatusFlags` for the meaning of the status flags).

        Parameters
        ----------
        log: bool = True
            Set to False to disable logging for this query. Default is True.
        is_polling: bool = False
            Whether the request is part of a regular polling request. If so, do not wait on the communication lock if the hardware is busy and just return immediately. Default is False.

        Returns
        -------
        dict
            A dictionary with the process data and values, {} otherwise.
        """
        if UP200ST.EMERGENCY_STOP_REQUEST:
            return {}

        process_data: Dict[str, Union[int, float, str]] = {}

        res = self._send_request(ProbeSonicatorCommands.GET_PROCESS_DATA.value, is_polling=is_polling)
        if is_polling and response == '':
            return {}

        if not res.startswith('<mdata>'):
            logger.error('Error querying process data.', extra=self._logger_dict)
            return {}
        else:
            res = res.replace('<mdata>', '').replace('</mdata>', '').split(';')
            process_data['Status'] = int(res[0])
            process_data['Total Power (W)'] = float(res[1]) / 10.0
            process_data['Net Power (W)'] = float(res[2]) / 10.0
            process_data['Amplitude (%)'] = float(res[3]) / 10.0
            process_data['Energy (Ws)'] = float(res[4])
            process_data['ADC'] = float(res[5]) / 10.0
            process_data['Frequency (Hz)'] = float(res[6])
            process_data['Temperature (degrees Celsius)'] = float(res[7]) / 10.0
            process_data['Time (s)'] = float(res[8]) / 100.0  # is returned in 100 ms
            process_data['Controlbits'] = bin(int(res[9])).replace('0b', '')
            process_data['Limit Type'] = int(res[10])
            process_data['Set Power (%)'] = float(res[11]) / 20.0
            process_data['Cycle (%)'] = float(res[12]) / 10.0

            if log:
                logger.info('Process data successfully queried: {}'.format(process_data), extra=self._logger_dict)
            return process_data

    def emergency_stop(self) -> bool:
        """
        Stops the ultrasound.

        Returns
        -------
        bool
            True if the emergency stop was executed successfully.
        """
        UP200ST.EMERGENCY_STOP_REQUEST = True

        # Turn ultrasound off
        response = self._send_request(ProbeSonicatorCommands.ULTRASOUND_OFF.value)
        res = response.replace('<moff>', '').replace('</moff>', '')
        if res != 'off':
            logger.critical("Error while executing emergency stop protocol.", extra=self._logger_dict)
            return False
        else:
            logger.critical("Emergency stop executed. All further actions suspended.", extra=self._logger_dict)
            return True


# Command xml Browser
# Switch ultrasound on mOn.xml http://192.168.233.233/mOn.xml
# Switch ultrasound off mOff.xml http://192.168.233.233/mOff.xml
# Activate temperature control tctrlOn.xml http://192.168.233.233/tctrlOn.xml
# Deactivate temperature control tctrlOff.xml http://192.168.233.233/tctrlOff.xml
# Set Stop Mode to Final (Reset) stopModeFin.xml http://192.168.233.233/stopModeFin.xml
# Set Stop Mode to Continue (Pause) stopModeCont.xml http://192.168.233.233/stopModeCont.xml
# Activate Energy Limit limitE.xml http://192.168.233.233/limitE.xml
# Activate Time Limit limitT.xml http://192.168.233.233/limitT.xml
# Deactivate Energy/Time Limit limitOff.xml http://192.168.233.233/limitOff.xml
# Set amplitude to 90% setP.xml?ts1=a&ampl=900 http://192.168.233.233/setP.xml?ts1=a&ampl=900
# Set power to 100% setP.xml?ts=p&pw=1000 http://192.168.233.233/setP.xml?ts1=p&pw=1000
# Set pulse to 70% (only UP200/400) setP.xml?cc=700 http://192.168.233.233/setP.xml?cc=700
# Set Lower Temperature Limit to 10°C setP.xml?lTL=100 http://192.168.233.233/setP.xml?lTL=100
# Set Upper Temperature Limit to 70°C setP.xml?uTL=700 http://192.168.233.233/setP.xml?uTL=700
# Set Energy Limit to 300Ws setP.xml?tm=3000 http://192.168.233.233/setP.xml?tm=3000
#     PreCondition: limitE.xml is already called, Maximum 42000000 Ws
# Set Time Limit to 40s setP.xml?tm=400 http://192.168.233.233/setP.xml?tm=400
#     PreCondition: limitT.xml is already called, Maximum 8553600 s
#
# Limit Settings for Time and Energy are stored in RAM and get lost at power off
#
# Get process data mdata.xml http://192.168.233.233/mdata.xml
# Response: <mdata>2;80;80;1000;4.7000e+01;10170;26007;2480;58;1;0;2000;1000</mdata>
# Description: <mdata>status; total power x 10(W); net power x 10(W); amplitude x10(%); energy (Ws); ADC x 10; frequency (Hz); temperature x 10(°C); time(100ms); Controlbits; LimitType; setpower(%) x 20; cycle(%) x 10 </mdata>
#
# status: 2
# total power: 8 W
# net power: 8 W
# amplitude: 100%
# energy: 47 Ws
# ADC: 1017
# frequency: 26007 Hz
# temperature: 248 °C (PT100 not attached)
# time: 5.8 s
# Controlbits: 1 Bit[0] = 0 -> Powercontrol
# Bit[0] = 1 -> Amplitudecontrol
# Bit[1] = 0 -> Stopmode Final
# Bit[1] = 1 -> Stopmode Continue (Pause)
# Bit[2] = 0 -> Temperaturecontrol off
# Bit[2] = 1 -> Temperaturecontrol on
# LimitType: 0 LimitType = 0: No Limit
# LimitType = 1: Energy Limit
# LimitType = 2: Time Limit
# setpower: 100%
# cycle: 100%
#
# Status
# 1 READY
# 2 ON
# 3 OFF
# 4 OVERLOAD
# 5 FREQUENCY DOWN
# 6 FREQUENCY UP
# 7 READY AFTER OVERTEMPERATURE
# 8 OVERSCAN
# 10 TIME LIMIT
# 11 ENERGY LIMIT
# 12 OVERTEMPERATURE
# 14 POWER LIMIT
# 15 OVERTEMPERATURE TRANSDUCER
# 20 TEMPERATURE LIMIT
# 104 Warning Temperature Generator high
# 105 Warning Overload
# 106 Warning Maladaptation
# 107 period off
# 108 Temperature Limit
# 109 Pressure Limit
# 110 Calibration Error
# 111 Warning Frequency low
# 112 Warning Frequency high
# 114 Calibration
