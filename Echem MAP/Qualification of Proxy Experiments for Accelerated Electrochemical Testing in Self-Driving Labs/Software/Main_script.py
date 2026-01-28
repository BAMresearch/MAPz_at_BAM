#check the COM and change!!!!

import threading
import time
import datetime
import os

from Functions.emstat_impedance import emstat_impedance
from Functions.emstat_lpr import emstat_lpr
from Functions.emstat_cpp import emstat_cpp
#from Functions.emstat_ca import emstat_ca
from Classes.config import config

# Define output paths and store them in a class
Output_Path = r'C:\Users\Results'
now = datetime.datetime.now().strftime('%d-%m-%Y_%H%M')
RUN_Directory = os.path.join(Output_Path, f'EXPERIMENT_{now}')

Config = config(path=RUN_Directory)

Cell1_COM = "COM8"
Cell2_COM = "COM9"
Cell3_COM = "COM10"
Cell4_COM = "COM11"

'''###### EIS1 #######
thread1 = threading.Thread(target=emstat_impedance, args=(1, Cell1_COM, 1, Config))
thread2 = threading.Thread(target=emstat_impedance, args=(2, Cell2_COM, 1, Config))
thread3 = threading.Thread(target=emstat_impedance, args=(3, Cell3_COM, 1, Config))
thread4 = threading.Thread(target=emstat_impedance, args=(4, Cell4_COM, 1, Config))

thread1.start()
time.sleep(0.2)
thread2.start()
time.sleep(0.2)
thread3.start()
time.sleep(0.2)
thread4.start()
time.sleep(0.2)    

thread1.join()
time.sleep(0.2)
thread2.join()
time.sleep(0.2)
thread3.join()
time.sleep(0.2)
thread4.join()
time.sleep(0.2)
#############

###### EIS2 #######
thread1 = threading.Thread(target=emstat_impedance, args=(1, Cell1_COM, 2, Config))
thread2 = threading.Thread(target=emstat_impedance, args=(2, Cell2_COM, 2, Config))
thread3 = threading.Thread(target=emstat_impedance, args=(3, Cell3_COM, 2, Config))
thread4 = threading.Thread(target=emstat_impedance, args=(4, Cell4_COM, 2, Config))

thread1.start()
time.sleep(0.2)
thread2.start()
time.sleep(0.2)
thread3.start()
time.sleep(0.2)
thread4.start()
time.sleep(0.2)    

thread1.join()
time.sleep(0.2)
thread2.join()
time.sleep(0.2)
thread3.join()
time.sleep(0.2)
thread4.join()
time.sleep(0.2)
#############

###### EIS3 #######
thread1 = threading.Thread(target=emstat_impedance, args=(1, Cell1_COM, 3, Config))
thread2 = threading.Thread(target=emstat_impedance, args=(2, Cell2_COM, 3, Config))
thread3 = threading.Thread(target=emstat_impedance, args=(3, Cell3_COM, 3, Config))
thread4 = threading.Thread(target=emstat_impedance, args=(4, Cell4_COM, 3, Config))

thread1.start()
time.sleep(0.2)
thread2.start()
time.sleep(0.2)
thread3.start()
time.sleep(0.2)
thread4.start()
time.sleep(0.2)    

thread1.join()
time.sleep(0.2)
thread2.join()
time.sleep(0.2)
thread3.join()
time.sleep(0.2)
thread4.join()
time.sleep(0.2)
#############

###### LPR #######
thread1 = threading.Thread(target=emstat_lpr, args=(1, Cell1_COM, Config))
thread2 = threading.Thread(target=emstat_lpr, args=(2, Cell2_COM, Config))
thread3 = threading.Thread(target=emstat_lpr, args=(3, Cell3_COM, Config))
thread4 = threading.Thread(target=emstat_lpr, args=(4, Cell4_COM, Config))

thread1.start()
time.sleep(0.2)
thread2.start()
time.sleep(0.2)
thread3.start()
time.sleep(0.2)
thread4.start()
time.sleep(0.2)    

thread1.join()
time.sleep(0.2)
thread2.join()
time.sleep(0.2)
thread3.join()
time.sleep(0.2)
thread4.join()
time.sleep(0.2)
#############'''

###### CPP #######
thread1 = threading.Thread(target=emstat_cpp, args=(1, Cell1_COM, Config))
thread2 = threading.Thread(target=emstat_cpp, args=(2, Cell2_COM, Config))
thread3 = threading.Thread(target=emstat_cpp, args=(3, Cell3_COM, Config))
thread4 = threading.Thread(target=emstat_cpp, args=(4, Cell4_COM, Config))

thread1.start()
time.sleep(0.2)
thread2.start()
time.sleep(0.2)
thread3.start()
time.sleep(0.2)
thread4.start()
time.sleep(0.2)    

thread1.join()
time.sleep(0.2)
thread2.join()
time.sleep(0.2)
thread3.join()
time.sleep(0.2)
thread4.join()
time.sleep(0.2)
#############

'''###### CA #######
thread1 = threading.Thread(target=emstat_ca, args=(1, Cell1_COM, Config))
thread2 = threading.Thread(target=emstat_ca, args=(2, Cell2_COM, Config))
thread3 = threading.Thread(target=emstat_ca, args=(3, Cell3_COM, Config))
thread4 = threading.Thread(target=emstat_ca, args=(4, Cell4_COM, Config))

thread1.start()
time.sleep(0.2)
thread2.start()
time.sleep(0.2)
thread3.start()
time.sleep(0.2)
thread4.start()
time.sleep(0.2)    

thread1.join()
time.sleep(0.2)
thread2.join()
time.sleep(0.2)
thread3.join()
time.sleep(0.2)
thread4.join()
time.sleep(0.2)
#############'''