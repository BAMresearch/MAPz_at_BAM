import os.path
import threading
import pandas as pd
import numpy as np
from scipy.stats import linregress
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plot_lock = threading.Lock()

import palmsens.instrument
import palmsens.mscript
import palmsens.serial

# Function to run LPR using potentiostat
# Modified from: https://github.com/PalmSens/MethodSCRIPT_Examples/tree/master/MethodSCRIPTExample_Python/MethodSCRIPTExample_Python
def emstat_lpr(cell_identifier, COM, Config):
    port = COM
    script = r'C:\Users\awetzel\Documents\Python\PSTrace_EmStat\MethodScripts\4_LPR.txt'

    OUTPUT_PATH_LPR_csv_measurement = os.path.join(Config.OUTPUT_PATH_LPR_csv)
    OUTPUT_PATH_OCP_LPR_csv_measurement = os.path.join(Config.OUTPUT_PATH_OCP_LPR_csv)
    OUTPUT_PATH_LPR_stats_calculation = os.path.join(Config.OUTPUT_PATH_LPR_stats)
    os.makedirs(OUTPUT_PATH_LPR_csv_measurement, exist_ok=True)
    os.makedirs(OUTPUT_PATH_OCP_LPR_csv_measurement, exist_ok=True)
    os.makedirs(OUTPUT_PATH_LPR_stats_calculation, exist_ok=True)

    # Connect to device and read data
    try:
        with palmsens.serial.Serial(port, 1) as comm:
            device = palmsens.instrument.Instrument(comm)
            device.send_script(script)

            result_lines = device.readlines_until_end()

        # Parse the result
        curves = palmsens.mscript.parse_result_lines(result_lines)
        
        ocp = []
        applied_potential = []
        measured_current = []
        start_collecting = 0
        previous_value = None
        
        for curve in curves:
            for row in curve:
                if len(row) == 1:
                    ocp.append(row[0].value)
                if len(row) >= 2:
                    value = row[0].value
                    if previous_value is not None and value != previous_value:
                        start_collecting = True
                    previous_value = value
                    if start_collecting:
                        applied_potential.append(row[0].value)
                        measured_current.append(row[1].value)
            else:
                continue

        applied_potential = np.array(applied_potential)
        measured_current = np.array(measured_current)

        # Save results to CSV
        data_file_lpr = pd.DataFrame({
            'Applied Potential (V)': applied_potential, 
            'Measured Current (A)': measured_current
        })
        
        data_file_ocp = pd.DataFrame({
            'OCP (V)': ocp 
        })

        csv_filename = f'LPR_Data_{cell_identifier}.csv'
        data_file_lpr.to_csv(os.path.join(OUTPUT_PATH_LPR_csv_measurement, csv_filename), index=False)
        
        csv_filename = f'OCP_Data_{cell_identifier}.csv'
        data_file_ocp.to_csv(os.path.join(OUTPUT_PATH_OCP_LPR_csv_measurement, csv_filename), index=False)

        # Seperate OCP from LPR from rest
        sign_changes = np.where(np.diff(np.sign(measured_current)))[0]
        if len(sign_changes) > 0:
            ocp_lpr = np.mean(applied_potential[sign_changes])
        else:
            ocp_lpr = applied_potential[np.argmin(np.abs(measured_current))]

        # Select data around OCP for resistance calculation
        delta_V = 0.003  # Potential window around OCP
        mask = (applied_potential >= ocp_lpr - delta_V) & (applied_potential <= ocp_lpr + delta_V)

        if np.sum(mask) > 2:  # Ensure enough points for regression
            slope, _, _, _, _ = linregress(measured_current[mask], applied_potential[mask])
            resistance = slope  # R = dV/dI
        else:
            resistance = None

        # Save stats to a text file
        stats_filename = os.path.join(OUTPUT_PATH_LPR_stats_calculation, f'LPR_Resistance_{cell_identifier}.txt')
        with open(stats_filename, 'w') as stats_file:
            stats_file.write(f'OCP (V): {np.mean(ocp):.6f}\n')
            stats_file.write(f'OCP(LPR) (V): {np.mean(ocp_lpr):.6f}\n')
            stats_file.write(f'Polarization Resistance (Ohm): {np.array(resistance):.2f}\n')

    except Exception as e:
        print(f"Error during LPR process: {str(e)}")