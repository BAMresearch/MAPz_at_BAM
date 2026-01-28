import os.path
import threading
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plot_lock = threading.Lock()

import palmsens.instrument
import palmsens.mscript
import palmsens.serial

# Function to run EIS using potentiostat
# Modified from: https://github.com/PalmSens/MethodSCRIPT_Examples/tree/master/MethodSCRIPTExample_Python/MethodSCRIPTExample_Python
def emstat_impedance(cell_identifier, COM, type, Config):
    port = COM
    if type == 1:
        script = r'C:\Users\awetzel\Documents\Python\PSTrace_EmStat\MethodScripts\1_EIS1.txt'
    elif type == 2:
        script = r'C:\Users\awetzel\Documents\Python\PSTrace_EmStat\MethodScripts\2_EIS2.txt'
    elif type == 3:
        script = r'C:\Users\awetzel\Documents\Python\PSTrace_EmStat\MethodScripts\3_EIS3.txt'
    
    
    OUTPUT_PATH_Impedance_csv_measurement = os.path.join(Config.OUTPUT_PATH_Impedance_csv)
    os.makedirs(OUTPUT_PATH_Impedance_csv_measurement, exist_ok=True)
    OUTPUT_PATH_OCP_Impedance_csv_measurement = os.path.join(Config.OUTPUT_PATH_OCP_Impedance_csv)
    os.makedirs(OUTPUT_PATH_OCP_Impedance_csv_measurement, exist_ok=True)

    # Connect to device and read data
    try:
        with palmsens.serial.Serial(port, 1) as comm:
            device = palmsens.instrument.Instrument(comm)
            device.send_script(script)

            result_lines = device.readlines_until_end()

        # Parse the result
        curves = palmsens.mscript.parse_result_lines(result_lines)
        
        ocp = []
        applied_frequency = []
        Z_whole = []
        Z_Im = []
        Z_Re = []
        Z_Phase = []
        start_collecting = 0

        for curve in curves:
            for row in curve:
                if len(row) == 1:
                    ocp.append(row[0].value)
                if len(row) >= 2:
                    value = float(row[0].value)
                    if value == 100000:
                        start_collecting = True
                    if start_collecting:
                        applied_frequency.append(value)
                        Z_Re.append(float(row[1].value))
                        Z_Im.append(float(row[2].value))
            else:
                continue
        
        Z_Im = -np.array(Z_Im)
        Z_whole = Z_Re + 1j*Z_Im
        Z_Phase = np.angle(Z_whole, deg=True)
        Z_imp = np.abs(Z_whole)

        # Save results to CSV
        data_file_eis = pd.DataFrame({
            'Applied Frequency (Hz)': applied_frequency, 
            'Z (Ohm)': Z_imp,
            'ZRe (Ohm)': Z_Re, 
            '-ZIm (Ohm)': Z_Im,
            'Phase (degree)': Z_Phase, 
        })

        data_file_ocp = pd.DataFrame({
            'OCP (V)': ocp 
        })
        
        csv_filename = f'Impedance_Data_Type{type}_Cell{cell_identifier}.csv'
        data_file_eis.to_csv(os.path.join(OUTPUT_PATH_Impedance_csv_measurement, csv_filename), index=False)

        csv_filename = f'OpenCircuit_Data_Type{type}_Cell{cell_identifier}.csv'
        data_file_ocp.to_csv(os.path.join(OUTPUT_PATH_OCP_Impedance_csv_measurement, csv_filename), index=False)

    except Exception as e:
        print(f"Error during Impedance process: {str(e)}")
    