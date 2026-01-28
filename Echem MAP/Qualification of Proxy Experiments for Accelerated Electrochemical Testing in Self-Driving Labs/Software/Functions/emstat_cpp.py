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
def emstat_cpp(cell_identifier, COM, Config):
    port = COM
    script = r'C:\Users\awetzel\Documents\Python\PSTrace_EmStat\MethodScripts\5_CPP.txt'

    OUTPUT_PATH_CPP_csv_measurement = os.path.join(Config.OUTPUT_PATH_CPP_csv)
    OUTPUT_PATH_OCP_CPP_csv_measurement = os.path.join(Config.OUTPUT_PATH_OCP_CPP_csv)
    os.makedirs(OUTPUT_PATH_CPP_csv_measurement, exist_ok=True)
    os.makedirs(OUTPUT_PATH_OCP_CPP_csv_measurement, exist_ok=True)

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

        # Save results to CSV
        data_file_cpp = pd.DataFrame({
            'Applied Potential (V)': applied_potential, 
            'Measured Current (A)': measured_current
        })
        
        data_file_ocp = pd.DataFrame({
            'OCP (V)': ocp 
        })

        csv_filename = f'CPP_Data_{cell_identifier}.csv'
        data_file_cpp.to_csv(os.path.join(OUTPUT_PATH_CPP_csv_measurement, csv_filename), index=False)
        
        csv_filename = f'OCP_Data_{cell_identifier}.csv'
        data_file_ocp.to_csv(os.path.join(OUTPUT_PATH_OCP_CPP_csv_measurement, csv_filename), index=False)

    except Exception as e:
        print(f"Error during CPP process: {str(e)}")