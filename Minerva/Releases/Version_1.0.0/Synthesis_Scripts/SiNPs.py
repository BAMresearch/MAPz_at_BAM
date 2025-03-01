import time
import os
import threading

import API.MinervaAPI
import Minerva.Software.OpenBISELNIntegration.OpenBisElnIntegration
from Minerva import *
from Minerva.API.HelperClassDefinitions import PathNames

def Stober_Silica_Synthesis(container: Container, falcontube1: Container, falcontube2: Container):
    EtOH_NH3_water_mix = Chemical(container=EtOH_NH3_water_container, name='EtOH_NH3_water', volume='8.84 mL', lookup_missing_values=False)
    TEOS_ethanolic = Chemical(container=TEOS_container, name='TEOS', volume='27.67 mL', lookup_missing_values=True)
    Chemical_Cleaning_valve2 = Chemical(container=EthanolContainerValve2, name='Ethanol', volume='5 mL')

    stirring_speed = 300  # rpm
    reaction_temperature = 25  # °C
    heating_time = '24 h'
    temperature_error = 2  # °C

    container.add_chemical(chemical=EtOH_NH3_water_mix, priming_volume='1 mL', priming_waste_container=WasteContainerValve1)

    container.infuse_while_heating(chemical=[TEOS_ethanolic],
                                   heating_temperature=reaction_temperature,
                                   stirring_speed=stirring_speed,
                                   heating_time=heating_time,
                                   addition_hardware=valve2,
                                   withdraw_rate='20 mL/min',
                                   addition_rate='30 mL/min',
                                   priming_volume='1.5 mL',
                                   purging_volume='8 mL',
                                   purging_port=5,
                                   priming_waste_container=WasteContainerValve2,
                                   cooldown_temperature=None,
                                   maximum_temperature_deviation=temperature_error,
                                   temperature_stabilization_time='5 min',
                                   chemical_for_cleaning=Chemical_Cleaning_valve2,
                                   active_cooling=False)

    container.transfer_content_to_container(target_containers=[falcontube1, falcontube2], transfer_hardware=valve1, dropoff_locations=[(flaskstation, 0), (falcon_tube_holder_50ml, 0), (falcon_tube_holder_50ml, 0)], bottom_clearance_withdrawing=5)

if __name__ == '__main__':
    esb = EmergencyStopButton.EmergencyStopButton(com_port='COM34')
    eln = Minerva.Software.OpenBISELNIntegration.OpenBisElnIntegration.ElectronicLabNotebook(space_name='1.0_MINERVA', project_code='SiNP')
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
    valve3 = SwitchingValve.SwitchingValveVici(com_port='COM17')
    pump1 = WPI.Aladdin(com_port='COM12')
    pump2 = WPI.Aladdin(com_port='COM9', baud_rate=9600, pump_type=SyringePumpType.AL_1010)
    pump3 = WPI.Aladdin(com_port='COM5', baud_rate=9600, pump_type=SyringePumpType.AL_1010)
    probesonicator = Hielscher.UP200ST(ip_address='192.168.233.233')
    centrifuge = Herolab.RobotCen(com_port='COM8', initialize_rotor=True, home_rotor=True)
    zetasizer = MalvernPanalytical.ZetaSizer(local_controller=local_server)

    gripchange_holder = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Corkring_Small, deck_position=4)
    hotplate1_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_100mL_Heating_Block, parent_hardware=hotplate1, deck_position=1)
    hotplate2_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_100mL_Heating_Block, parent_hardware=hotplate2, deck_position=2)
    hotplate3_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_100mL_Heating_Block, parent_hardware=hotplate3, deck_position=3)
    ot2_holder_15ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_15mL_Tube_Rack, parent_hardware=ot2, deck_position=2)
    ot2_holder_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_50mL_Tube_Rack, parent_hardware=ot2, deck_position=1)
    ot2_holder_flask_100ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_100mL_Flask_Rack, parent_hardware=ot2, deck_position=3)
    falcon_tube_holder_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_50mL_Foldable_Tube_Rack, deck_position=1)
    falcon_tube_holder_15ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_15mL_Foldable_Tube_Rack, deck_position=2)
    flaskstation = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Flask_Station, deck_position=3, leave_even_rows_empty=False)

    flask_1_100ml = Container(flaskstation, slot_number=1, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask1')
    flask_2_100ml = Container(flaskstation, slot_number=2, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask2')
    flask_3_100ml = Container(flaskstation, slot_number=3, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask3')
    flask_4_100ml = Container(flaskstation, slot_number=4, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask4')
    flask_5_100ml = Container(flaskstation, slot_number=5, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=False, name='flask5')
    falcontube1_15ml = Container(falcon_tube_holder_15ml, slot_number=1, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube2_15ml = Container(falcon_tube_holder_15ml, slot_number=2, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube3_15ml = Container(falcon_tube_holder_15ml, slot_number=3, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube15ml_counter = Container(falcon_tube_holder_15ml, slot_number=3, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='10 mL', is_capped=True)
    falcontube1_50ml = Container(falcon_tube_holder_50ml, slot_number=1, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='0 mL', is_capped=False)
    falcontube2_50ml = Container(falcon_tube_holder_50ml, slot_number=2, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='0 mL', is_capped=False)
    falcontube3_50ml = Container(falcon_tube_holder_50ml, slot_number=3, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='0 mL', is_capped=False)
    falcontube4_50ml = Container(falcon_tube_holder_50ml, slot_number=4, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='0 mL', is_capped=False)
    falcontube5_50ml = Container(falcon_tube_holder_50ml, slot_number=15, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='0 mL', is_capped=False)
    falcontube6_50ml = Container(falcon_tube_holder_50ml, slot_number=17, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='0 mL', is_capped=True)
    falcontube_for_cleaning = Container(falcon_tube_holder_50ml, slot_number=14, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='40 mL', is_capped=False)

    WasteContainerValve1 = Container(current_hardware=valve1, slot_number=0, name='Waste_Container', current_volume='2 L', max_volume='5 L')
    WasteContainerValve2 = Container(current_hardware=valve2, slot_number=6, name='Waste_ContainerValve2', current_volume='0 mL', max_volume='50 mL')
    DLSCell = Container(current_hardware=valve1, slot_number=4, name='DLS_Cell', current_volume='0 mL')
    MilliQ_ContainerValve1 = Container(current_hardware=valve1, slot_number=1, name='MilliQ_ContainerValve1', current_volume='1.2 L')
    Ethanol_wash_container = Container(current_hardware=valve1, slot_number=5, name='Ethanol_wash_valve1', current_volume='5 L')
    EthanolContainerValve2 = Container(current_hardware=valve2, slot_number=9, name='Ethanol_wash_valve2', current_volume='500 mL')

    Ethanol_wash = Chemical(container=Ethanol_wash_container, name='Ethanol', volume='15 mL', lookup_missing_values=True)
    Water_wash = Chemical(container=MilliQ_ContainerValve1, name='Water', volume='15 mL', lookup_missing_values=True)
    TEOS_container = Container(current_hardware=valve2, slot_number=9, name='TEOS_container', current_volume='100 mL', max_volume='500 mL')  # dilution 3 ml in 80 mL EtOH
    EtOH_NH3_water_container = Container(current_hardware=valve1, slot_number=6, name='EtOH_NH3_water_container', current_volume='53 mL', max_volume='100 mL')

    sonication_time = '40 s'
    centrifugation_speed = '14000 rcf'
    centrifugation_time_water = '20 min'
    centrifugation_time_EtOH = '15 min'
    washing_steps = 2
    sample_name_1 = 'MZ026'
    sample_name_2 = 'MZ027'
    sample_name_3 = 'MZ028'

    ot2_configuration = {
        1: ot2_holder_50ml,
        2: ot2_holder_15ml,
        3: ot2_holder_flask_100ml,
        4: None,
        5: None,
        6: None,
        7: None,
        8: 'opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical',
        9: None,
        10: 'opentrons_96_tiprack_300ul',
        11: 'labsolute_96_tiprack_1000ul',
        12: 'p1000_single_gen2',  # left pipette
        13: 'p300_single_gen2',  # right pipette
    }

    valve1_configuration = {
        0: None,
        1: MilliQ_ContainerValve1,
        2: Ethanol_wash_container,
        3: WasteContainerValve1,
        4: DLSCell,
        5: None,
        6: EtOH_NH3_water_container,
        7: None,
        8: 'Outlet',
        9: None,
        10: pump1
    }

    valve2_configuration = {
        0: None,
        1: hotplate1,
        2: hotplate2,
        3: hotplate3,
        4: MilliQ_ContainerValve2,
        5: None,
        6: WasteContainerValve2,
        7: None,
        8: None,
        9: TEOSContainer,
        10: pump2
    }

    valve3_configuration = {
        0: None,
        1: hotplate1,
        2: hotplate2,
        3: hotplate3,
        4: MilliQ_ContainerValve3,
        5: None,
        6: None,
        7: None,
        8: None,
        9: WasteContainerValve3,
        10: pump3
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
    pump1.set_syringe(Syringes.GLASS_SYRINGE_SOCOREX_50ML, default_addition_rate='70 mL/min')
    valve1.set_configuration(valve1_configuration)
    pump2.set_syringe(Syringes.PLASTICSYRINGE_LABSOLUTE_24ML, default_addition_rate='40 mL/min')
    valve2.set_configuration(valve2_configuration)
    valve2.set_dead_volumes(valve2_dead_volumes)
    pump3.set_syringe(Syringes.GLASS_SYRINGE_SOCOREX_5ML, default_addition_rate='20 mL/min')
    valve3.set_configuration(valve3_configuration)

    Stober_Silica_Synthesis_parameters = ((flask_1_100ml, falcontube1_50ml, falcontube2_50ml),
                                          (flask_2_100ml, falcontube3_50ml, falcontube4_50ml),
                                          (flask_3_100ml, falcontube5_50ml, falcontube6_50ml))

    threads = []
    for i, p in enumerate(Stober_Silica_Synthesis_parameters):
        threads.append(threading.Thread(name=f'Thread_{i}', target=Stober_Silica_Synthesis, args=tuple(p)))
        threads[0].start()
        time.sleep(40)
    for t in threads:
        t.join()

    # Washing
    falcontube1_50ml.centrifuge([falcontube2_50ml, falcontube3_50ml, falcontube4_50ml, falcontube5_50ml, falcontube6_50ml], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time_water)
    falcontube1_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Water_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
    falcontube2_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Water_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
    falcontube3_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Water_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
    falcontube4_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Water_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
    falcontube5_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Water_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
    falcontube6_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Water_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
    for _ in washing_steps:
        falcontube1_50ml.centrifuge([falcontube2_50ml, falcontube3_50ml, falcontube4_50ml, falcontube5_50ml, falcontube6_50ml], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time_EtOH)
        falcontube1_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Ethanol_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
        falcontube2_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Ethanol_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
        falcontube3_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Ethanol_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
        falcontube4_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Ethanol_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
        falcontube5_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Ethanol_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)
        falcontube6_50ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, redispersion_chemical=Ethanol_wash, sonicator=probesonicator, sonication_time=sonication_time, sonication_power=50, sonication_amplitude=50, container_for_cleaning=falcontube_for_cleaning)

    # Redispersion in water for DLS
    falcontube1_50ml.transfer_content_to_container(falcontube1_15ml, volume='2 mL', bottom_clearance_withdrawing=15, transfer_hardware=valve1, purging_volume='10 mL')
    falcontube1_15ml.add_chemical([Chemical.from_stock_chemical(Ethanol_wash, volume='8 mL')])
    falcontube3_50ml.transfer_content_to_container(falcontube2_15ml, volume='2 mL', bottom_clearance_withdrawing=15, transfer_hardware=valve1, purging_volume='10 mL')
    falcontube2_15ml.add_chemical([Chemical.from_stock_chemical(Ethanol_wash, volume='8 mL')])
    falcontube5_50ml.transfer_content_to_container(falcontube3_15ml, volume='2 mL', bottom_clearance_withdrawing=15, transfer_hardware=valve1, purging_volume='10 mL')
    falcontube3_15ml.add_chemical([Chemical.from_stock_chemical(Ethanol_wash, volume='8 mL')])

    falcontube1_15ml.centrifuge(containers=[falcontube2_15ml, falcontube3_15ml, falcontube4_15ml], centrifugation_time='12 min', centrifugation_speed=centrifugation_speed)
    falcontube1_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time='30 s', redispersion_chemical=Chemical.from_stock_chemical(Water_wash, volume='10 mL'), sonication_power=50, sonication_amplitude=50, sonicator=probesonicator, bottom_clearance_sonication=20, purging_volume='10 mL', bottom_clearance_withdrawing=2, container_for_cleaning=falcontube_for_cleaning)
    falcontube2_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time='30 s', redispersion_chemical=Chemical.from_stock_chemical(Water_wash, volume='10 mL'), sonication_power=50, sonication_amplitude=50, sonicator=probesonicator, bottom_clearance_sonication=20, purging_volume='10 mL', bottom_clearance_withdrawing=2, container_for_cleaning=falcontube_for_cleaning)
    falcontube3_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time='30 s', redispersion_chemical=Chemical.from_stock_chemical(Water_wash, volume='10 mL'), sonication_power=50, sonication_amplitude=50, sonicator=probesonicator, bottom_clearance_sonication=20, purging_volume='10 mL', bottom_clearance_withdrawing=2, container_for_cleaning=falcontube_for_cleaning)

    # DLS measurement
    falcontube1_15ml.measure_dls(dls_cell=DLSCell, sop_path=os.path.join('C:\\', 'users', 'WS8717-apollo', 'Desktop', 'Apollo', 'Characterization', 'DLS', 'SOP', 'DLS_ZETA_SiO2_in_Water.zskd'), sample_name=sample_name_1, chemical_for_cleaning=Water_wash, dls_device=zetasizer, bottom_clearance_sampling=9, waste_container=WasteContainerValve1)
    falcontube2_15ml.measure_dls(dls_cell=DLSCell, sop_path=os.path.join('C:\\', 'users', 'WS8717-apollo', 'Desktop', 'Apollo', 'Characterization', 'DLS', 'SOP', 'DLS_ZETA_SiO2_in_Water.zskd'), sample_name=sample_name_2, chemical_for_cleaning=Water_wash, dls_device=zetasizer, bottom_clearance_sampling=9, waste_container=WasteContainerValve1)
    falcontube3_15ml.measure_dls(dls_cell=DLSCell, sop_path=os.path.join('C:\\', 'users', 'WS8717-apollo', 'Desktop', 'Apollo', 'Characterization', 'DLS', 'SOP', 'DLS_ZETA_SiO2_in_Water.zskd'), sample_name=sample_name_3, chemical_for_cleaning=Water_wash, dls_device=zetasizer, bottom_clearance_sampling=9, waste_container=WasteContainerValve1)

    # ELN upload
    eln.write_synthesis_step(experiment_name=f"{sample_name1},{sample_name2},{sample_name_3}")