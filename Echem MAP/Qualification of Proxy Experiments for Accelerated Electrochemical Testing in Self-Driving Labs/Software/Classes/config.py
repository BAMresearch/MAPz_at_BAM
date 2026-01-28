import os

class config:
    def __init__(self, path=None):
        self.path = path
        self.setup_paths()

    def setup_paths(self):
        
        # Impedance paths
        self.OUTPUT_PATH_Impedance = os.path.join(self.path, 'Impedance')
        self.OUTPUT_PATH_Impedance_csv = os.path.join(self.OUTPUT_PATH_Impedance, 'Impedance_csv')
        self.OUTPUT_PATH_OCP_Impedance_csv = os.path.join(self.OUTPUT_PATH_Impedance, 'OCP_Impedance_csv')

        # LPR paths
        self.OUTPUT_PATH_LPR = os.path.join(self.path, 'LPR')
        self.OUTPUT_PATH_LPR_csv = os.path.join(self.OUTPUT_PATH_LPR, 'LPR_csv')
        self.OUTPUT_PATH_OCP_LPR_csv = os.path.join(self.OUTPUT_PATH_LPR, 'OCP_LPR_csv')
        self.OUTPUT_PATH_LPR_stats = os.path.join(self.OUTPUT_PATH_LPR, 'LPR_stats')
        
        # CPP paths
        self.OUTPUT_PATH_CPP = os.path.join(self.path, 'CPP')
        self.OUTPUT_PATH_CPP_csv = os.path.join(self.OUTPUT_PATH_CPP, 'CPP_csv')
        self.OUTPUT_PATH_OCP_CPP_csv = os.path.join(self.OUTPUT_PATH_CPP, 'OCP_CPP_csv')
        
        '''# CA paths
        self.OUTPUT_PATH_CA = os.path.join(self.path, 'CA')
        self.OUTPUT_PATH_CA_csv = os.path.join(self.OUTPUT_PATH_CA, 'CA_csv')
        self.OUTPUT_PATH_OCP_CA_csv = os.path.join(self.OUTPUT_PATH_CA, 'OCP_CA_csv')
        
        # CP1 paths
        self.OUTPUT_PATH_CP1 = os.path.join(self.path, 'CP1')
        self.OUTPUT_PATH_CP1_csv = os.path.join(self.OUTPUT_PATH_CP1, 'CP_csv')
        
         # CP2 paths
        self.OUTPUT_PATH_CP2 = os.path.join(self.path, 'CP2')
        self.OUTPUT_PATH_CP2_csv = os.path.join(self.OUTPUT_PATH_CP2, 'CP_csv')
        
         # CP3 paths
        self.OUTPUT_PATH_CP3 = os.path.join(self.path, 'CP3')
        self.OUTPUT_PATH_CP3_csv = os.path.join(self.OUTPUT_PATH_CP3, 'CP_csv')
        
         # CP4 paths
        self.OUTPUT_PATH_CP4 = os.path.join(self.path, 'CP4')
        self.OUTPUT_PATH_CP4_csv = os.path.join(self.OUTPUT_PATH_CP4, 'CP_csv')'''


        # Create directories
        for p in [
            self.OUTPUT_PATH_LPR_csv,  self.OUTPUT_PATH_OCP_LPR_csv, self.OUTPUT_PATH_LPR_stats,
            self.OUTPUT_PATH_Impedance_csv,  self.OUTPUT_PATH_OCP_Impedance_csv,
            self.OUTPUT_PATH_CPP_csv, self.OUTPUT_PATH_OCP_CPP_csv,
            #self.OUTPUT_PATH_CA_csv, self.OUTPUT_PATH_OCP_CA_csv,
            #self.OUTPUT_PATH_CP1_csv,
            #self.OUTPUT_PATH_CP2_csv,
            #self.OUTPUT_PATH_CP3_csv,
            #self.OUTPUT_PATH_CP4_csv
        ]:
            os.makedirs(p, exist_ok=True)
