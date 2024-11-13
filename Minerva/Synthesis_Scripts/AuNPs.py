import time
import os
import threading

import API.MinervaAPI
import Minerva.Software.OpenBISELNIntegration.OpenBisElnIntegration
from Minerva import *
from Minerva.API.HelperClassDefinitions import PathNames

def Au_NP_Synthesis(container: Container, falcontube1: Container):
    HAuCl4 = Chemical(container=HAuCl4_Container, name='Tetrachloroaurate trihydrate', volume='1 mL', concentration='2.5 mM', lookup_missing_values=True)
    MilliQ_dilution = Chemical(container=Water_dilution_container, name='Water', volume='9.0 mL', lookup_missing_values=True)
    Sodium_Citrate = Chemical(container=Citrate_container, name='Sodium citrate dihydrate', volume='350 uL', lookup_missing_values=True)

    container.add_chemical([HAuCl4, MilliQ_dilution])

    container.infuse_while_heating(chemical=Sodium_Citrate,
                                    heating_temperature=95,
                                    stirring_speed=750,
                                    heating_time='30 min',
                                    addition_hardware=valve2,
                                    withdraw_rate='5 mL/min',
                                    addition_rate='10 mL/min',
                                    purging_addition_rate='10 mL/min',
                                    priming_volume='1 mL',
                                    purging_volume='2.5 mL',
                                    purging_port=5,
                                    priming_waste_container=WasteContainerValve2,
                                    cooldown_temperature=cooling_temperature,
                                    maximum_temperature_deviation=temperature_error,
                                    temperature_stabilization_time='20 min',
                                    chemical_for_cleaning=Water_wash_valve2,
                                    active_cooling=True)

    container.transfer_content_to_container(target_containers=[falcontube1], transfer_hardware=valve1, dropoff_locations=[(flaskstation, 0), (falcon_tube_holder_15ml, 0)], bottom_clearance_withdrawing=5)

if __name__ == '__main__':
    esb = EmergencyStopButton.EmergencyStopButton(com_port='COM34')
    eln = Minerva.Software.OpenBISELNIntegration.OpenBisElnIntegration.ElectronicLabNotebook(space_name='1.0_MINERVA', project_code='Gold_RM')
    local_server = LocalPCServer.LocalPCServer(com_port='COM7')
    arduino = ArduinoController.ArduinoController(com_port='COM25')
    dht22 = DHT22Sensor.DHT22Sensor(arduino_controller=arduino)
    robotarm = UFactory.XArm6(ip_address='192.168.1.204', levelling_data_file=os.path.join('..', 'SampleHolder', 'Table_Levelling_Data.json'))
    ot2 = OpentronsOT2.OT2(ip_address='OT2CEP20210918R04.local')
    hotplate1 = IkaHotplate.RCTDigital5(com_port='COM6')
    hotplate2 = IkaHotplate.RCTDigital5(com_port='COM4')
    hotplate3 = IkaHotplate.RCTDigital5(com_port='COM18')
    hotplate1_clamp = HotplateClamp.HotplateClampDCMotor(arduino_controller=arduino, parent_hardware=hotplate1, clamp_number=1)
    hotplate2_clamp = HotplateClamp.HotplateClampDCMotor(arduino_controller=arduino, parent_hardware=hotplate2, clamp_number=2)
    hotplate3_clamp = HotplateClamp.HotplateClampDCMotor(arduino_controller=arduino, parent_hardware=hotplate3, clamp_number=3)
    hotplate_fan_1 = HotplateFan.HotplateFan(hotplate1, arduino_controller=arduino, fan_number=1)
    hotplate_fan_2 = HotplateFan.HotplateFan(hotplate2, arduino_controller=arduino, fan_number=2)
    hotplate_fan_3 = HotplateFan.HotplateFan(hotplate3, arduino_controller=arduino, fan_number=3)
    capper = CapperDecapper.CapperDecapper(arduino_controller=arduino)
    valve1 = SwitchingValve.SwitchingValveVici(com_port='COM3')
    valve2 = SwitchingValve.SwitchingValveVici(com_port='COM14')
    pump1 = WPI.Aladdin(com_port='COM12')
    pump2 = WPI.Aladdin(com_port='COM9', baud_rate=9600, pump_type=SyringePumpType.AL_1010)
    probesonicator = Hielscher.UP200ST(ip_address='192.168.233.233')
    centrifuge = Herolab.RobotCen(com_port='COM8', initialize_rotor=True, home_rotor=True)
    zetasizer = MalvernPanalytical.ZetaSizer(local_controller=local_server)

    gripchange_holder = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Corkring_Small, deck_position=4)
    hotplate1_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_25mL_Heating_Block, parent_hardware=hotplate1, deck_position=1)
    hotplate2_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_25mL_Heating_Block, parent_hardware=hotplate2, deck_position=2)
    hotplate3_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_25mL_Heating_Block, parent_hardware=hotplate3, deck_position=3)
    ot2_holder_15ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_15mL_Tube_Rack, parent_hardware=ot2, deck_position=1)
    ot2_holder_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_50mL_Tube_Rack, parent_hardware=ot2, deck_position=4)
    ot2_holder_flask_10ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_10mL_Flask_Rack, parent_hardware=ot2, deck_position=2)
    ot2_holder_flask_25ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_25mL_Flask_Rack, parent_hardware=ot2, deck_position=3)
    falcon_tube_holder_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_50mL_Foldable_Tube_Rack, deck_position=1, leave_even_rows_empty=True)
    falcon_tube_holder_15ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_15mL_Foldable_Tube_Rack, deck_position=2, leave_even_rows_empty=True)
    flaskstation = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Flask_Station, deck_position=3, leave_even_rows_empty=False)

    flaskflush = Container(flaskstation, slot_number=5, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask_flush')
    flask_1_25ml = Container(flaskstation, slot_number=1, container_type=ContainerTypeCollection.FLASK_25_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask1')
    flask_2_25ml = Container(flaskstation, slot_number=2, container_type=ContainerTypeCollection.FLASK_25_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask2')
    flask_3_25ml = Container(flaskstation, slot_number=3, container_type=ContainerTypeCollection.FLASK_25_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask3')
    falcontube1_15ml = Container(falcon_tube_holder_15ml, slot_number=1, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube2_15ml = Container(falcon_tube_holder_15ml, slot_number=2, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube3_15ml = Container(falcon_tube_holder_15ml, slot_number=3, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube4_15ml = Container(falcon_tube_holder_15ml, slot_number=4, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube5_15ml = Container(falcon_tube_holder_15ml, slot_number=5, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)

    falcontube_for_cleaning = Container(falcon_tube_holder_50ml, slot_number=14, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='40 mL', is_capped=True)

    WasteContainerValve1 = Container(current_hardware=valve1, slot_number=3, name='Waste_Container', current_volume='2 L', max_volume='5 L')
    WasteContainerValve2 = Container(current_hardware=valve2, slot_number=6, name='Waste_ContainerValve2', current_volume='0 mL', max_volume='50 mL')
    DLSCell = Container(current_hardware=valve1, slot_number=4, name='DLS_Cell', current_volume='0 mL')
    MilliQ_ContainerValve1 = Container(current_hardware=valve1, slot_number=1, name='MilliQ_ContainerValve1', current_volume='1.2 L')
    MilliQ_ContainerValve2 = Container(current_hardware=valve2, slot_number=4, name='CleaningChemicalValve2', current_volume='50 mL')
    Ethanol_wash_container = Container(current_hardware=valve1, slot_number=2, name='Ethanol_wash', current_volume='5 L')

    HAuCl4_Container = Container(current_hardware=ot2, deck_position=8, slot_number=1, name='HAuCl4_Container', current_volume='2.5 mL', container_type=ContainerTypeCollection.FALCON_TUBE_15_ML)
    Water_dilution_container = Container(current_hardware=ot2, deck_position=8, slot_number=7, name='Water_Container', current_volume='25 mL', container_type=ContainerTypeCollection.FALCON_TUBE_50_ML)
    Citrate_container = Container(current_hardware=valve2, slot_number=0, name='Sodium_Citrate_Container', current_volume='3 mL')

    Water_wash_valve2 = Chemical(container=MilliQ_ContainerValve2, name='Water', volume='2 mL', lookup_missing_values=True)
    Water_wash = Chemical(container=MilliQ_ContainerValve1, name='Water', volume='10 mL', lookup_missing_values=True)
    Ethanol_wash = Chemical(container=Ethanol_wash_container, name='Ethanol', volume='20 mL', lookup_missing_values=True)

    temperature_error = 2  # °C
    cooling_temperature = 30  # °C
    sonication_time = '5 s'
    washing_steps = 1
    centrifugation_speed = '3500 rcf'
    centrifugation_time = '90 min'
    centrifugation_temp = 5  # °C
    sample_name_1 = 'MZ146'
    sample_name_2 = 'MZ147'

    ot2_configuration = {
        1: ot2_holder_15ml,
        2: ot2_holder_flask_10ml,
        3: ot2_holder_flask_25ml,
        4: None,
        5: None,
        6: None,
        7: None,
        8: 'opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical',
        9: None,
        10:'opentrons_96_tiprack_20ul',    # 'opentrons_96_tiprack_300ul'
        11:'labsolute_96_tiprack_1000ul',
        12:'p1000_single_gen2',  # left pipette
        13:'p20_single_gen2',  # right pipette  'p300_single_gen2'
    }

    valve1_configuration = {
        0: None,
        1: MilliQ_ContainerValve1,
        2: Ethanol_wash_container,
        3: WasteContainerValve1,
        4: DLSCell,
        5: None,
        6: None,
        7: None,
        8: 'Outlet',
        9: None,
        10: pump1
    }

    valve2_configuration = {
        0: Citrate_container,
        1: hotplate1,
        2: hotplate2,
        3: hotplate3,
        4: MilliQ_ContainerValve2,
        5: None,
        6: WasteContainerValve2,
        7: None,
        8: None,
        9: None,
        10: pump2
    }

    valve2_dead_volumes = {
        0: None,
        1: '1.390 mL',
        2: '1.35 mL',
        3: '1.87 mL',
        4: None,
        5: None,
        6: None,
        7: None,
        8: None,
        9: None,
        10: None
    }

    ot2.set_hardware_configuration(ot2_configuration)
    pump1.set_syringe(Syringes.GLASS_SYRINGE_SOCOREX_50ML, default_addition_rate='50 mL/min')
    valve1.set_configuration(valve1_configuration)
    pump2.set_syringe(Syringes.GLASS_SYRINGE_SOCOREX_5ML, default_addition_rate='10 mL/min')
    valve2.set_configuration(valve2_configuration)
    valve2.set_dead_volumes(valve2_dead_volumes)

    Au_NP_Synthesis_reaction_parameters = ((flask_1_25ml, falcontube1_15ml),
                                           (flask_2_25ml, falcontube2_15ml))


    threads = []
    for i, p in enumerate(Au_NP_Synthesis_reaction_parameters):
        threads.append(threading.Thread(name=f'Thread_{i}', target=Au_NP_Synthesis, args=tuple(p)))
        threads[-1].start()
        time.sleep(300)

    for t in threads:
       t.join()

    # Washing
    for _ in washing_steps:
        falcontube1_15ml.centrifuge([falcontube2_15ml], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time, centrifugation_temperature=centrifugation_temp)
        falcontube1_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Water_wash, sonication_power=50, sonication_amplitude=50, sonicator=probesonicator, bottom_clearance_sonication=10, container_for_cleaning=falcontube_for_cleaning)
        falcontube2_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Water_wash, sonication_power=50, sonication_amplitude=50, sonicator=probesonicator, bottom_clearance_sonication=10, container_for_cleaning=falcontube_for_cleaning)

    # Dilution for DLS measurement
    falcontube1_15ml.transfer_content_to_container(falcontube3_15ml, transfer_hardware=valve1, volume='1 mL', bottom_clearance_withdrawing=10)
    falcontube1_15ml.add_chemical(chemical=Chemical.from_stock_chemical(Water_wash, volume='4 mL'))
    falcontube2_15ml.transfer_content_to_container(falcontube4_15ml, transfer_hardware=valve1, volume='1 mL', bottom_clearance_withdrawing=10)
    falcontube2_15ml.add_chemical(chemical=Chemical.from_stock_chemical(Water_wash, volume='4 mL'))

    # DLS measurement
    falcontube3_15ml.measure_dls(dls_cell=DLSCell, sop_path=os.path.join('C:\\', 'users', 'WS8717-apollo', 'Desktop', 'Apollo', 'Characterization', 'DLS', 'SOP', 'DLS_Au_in_Water.zskd'), sample_name=sample_name_1, chemical_for_cleaning=Water_wash, dls_device=zetasizer, bottom_clearance_sampling=9, waste_container=WasteContainerValve1)
    falcontube4_15ml.measure_dls(dls_cell=DLSCell, sop_path=os.path.join('C:\\', 'users', 'WS8717-apollo', 'Desktop', 'Apollo', 'Characterization', 'DLS', 'SOP', 'DLS_Au_in_Water.zskd'), sample_name=sample_name_2, chemical_for_cleaning=Water_wash, dls_device=zetasizer, bottom_clearance_sampling=9, waste_container=WasteContainerValve1)

    # ELN upload
    eln.write_synthesis_step(experiment_name=f"{sample_name1},{sample_name2}")


