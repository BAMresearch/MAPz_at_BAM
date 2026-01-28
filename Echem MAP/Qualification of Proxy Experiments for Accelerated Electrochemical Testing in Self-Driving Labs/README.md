This repository comprises information and respective code for running the electrochemical sequence from our reserach paper "Qualification of Proxy Experiments for Accelerated Electrochemical Testing in Self-Driving Labs" and contains the following:

1) **Software which comprises:**
    - Main_scripts 
        
        *This is the execution code for the whole sequence OCP<sub>1</sub>-EIS<sub>1Hz</sub>-OCP<sub>2</sub>-EIS<sub>0.1Hz</sub>-OCP3-EIS<sub>0.01Hz</sub>-OCP<sub>4</sub>-LPR-OCP<sub>5</sub>-CPP*
    - Main_plotting 
        
        *This is the optional plotting code that helps transfer and visualize the data with Origin* 
    - Functions 
        
        *emstat_impedance: To perform EIS; emstat_lpr: To perform LPR; emstat_cpp: To perform CPP*
    - Classes 
        
        *Config: A separate class used to store all the path files for data saving and script calling.*
    - PalmSens 
        
        *PalmSens specific modules*
    - MethodScripts 
        
        *Contains MethodSCRIPT file for each electrochemical method.*
    - Results 
        
        *Output folder for acquired data.*
    - Plotting 
        
        *transfer_to_origin: builds project from CSVs; rearrange_OCP: inserts 'time' column for OCP books; generate_plots: builds graphs, exports TIFF, saves project*

2) **Hardware**

For any questions please contact Mert Ozan (mert.ozan@bam.de) or Annica Heyne (annica.heyne@bam.de)

Notes: 
- Please be aware that chronopotentiometric measurements have conducted manually, and were not part of the sequence.
- For OCP measurements, one needs to measure the OCP within the measurement method. The script separate the OCP from the measurement.