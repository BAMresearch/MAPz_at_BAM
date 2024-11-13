import time
import datetime
import os
import threading

import API.MinervaAPI
import Minerva.Software.OpenBISELNIntegration.OpenBisElnIntegration
from Minerva import *
from Minerva.API.HelperClassDefinitions import PathNames

def CuO_CoreShell_Synthesis(container: Container, falcontube1: Container, falcontube2: Container):
    CTAB = Chemical(container=CTABContainer, name='CTAB', mass_concentration='4.2 mg/mL', mass='37.5 mg', lookup_missing_values=True)
    CuO_cores = Chemical(container=CuOContainer, name='CuO_cores', volume='0.5 mL', mass_concentration='12 mg/mL', lookup_missing_values=False)
    L_Arginine = Chemical(container=L_ArgContainer, name='Arginine', mass_concentration='10.0 mg/mL', mass='10.0 mg', lookup_missing_values=True)
    Water = Chemical(container=MilliQOT2, name='Water', volume='4.5 mL', lookup_missing_values=True, is_stock_solution=True)
    TEOS = Chemical(container=TEOSContainer, name='TEOS', volume='100 uL', lookup_missing_values=True)

    stirring_speed = 400  # rpm
    reaction_temperature = 95  # °C
    cooling_temperature = 40   # °C
    heating_time = '3 h'
    temperature_error = 2  # °C
    teos_infusion_rate = '5 mL/min'

    container.add_chemical([Water, CTAB, L_Arginine, CuO_cores])

    container.sonicate(sonicator=probesonicator, sonication_time=sonication_time, sonication_power=20, sonication_amplitude=20, bottom_clearance=12, container_for_cleaning=falcontube_for_cleaning)

    container.infuse_while_heating(chemical=TEOS,
                                   heating_temperature=reaction_temperature,
                                   stirring_speed=stirring_speed,
                                   heating_time=heating_time,
                                   addition_hardware=valve2,
                                   withdraw_rate='5 mL/min',
                                   addition_rate='5 mL/min',
                                   priming_volume='1.0 mL',
                                   purging_volume='2.5 mL',
                                   purging_port=0,
                                   priming_waste_container=WasteContainerValve2,
                                   cooldown_temperature=cooling_temperature,
                                   maximum_temperature_deviation=temperature_error,
                                   temperature_stabilization_time='30 min',
                                   active_cooling=True)

    container.transfer_content_to_container(target_containers=[falcontube1, falcontube2], transfer_hardware=valve1, bottom_clearance_withdrawing=8, dropoff_locations=[(flaskstation, 0), (falcon_tube_holder_15ml, 0), (falcon_tube_holder_15ml, 0)])

def NH4NO3_extraction(container: Container, falcontube1: Container, falcontube2: Container, falcontube3: Container, falcontube4: Container):
    stirring_speed = 300  # rpm
    reaction_temperature = 72  # °C
    heating_time = '1.5 h'
    temperature_error = 2  # °C
    cooling_temperature = 40  # °C

    falcontube1.transfer_content_to_container(container, transfer_hardware=valve1, bottom_clearance_withdrawing=7)
    falcontube2.transfer_content_to_container(container, transfer_hardware=valve1, bottom_clearance_withdrawing=7)

    container.heat(heating_temperature=reaction_temperature, stirring_speed=stirring_speed, heating_time=heating_time, cooldown_temperature=cooling_temperature, active_cooling=True, temperature_stabilization_time='10 min')

    container.transfer_content_to_container(target_containers=[falcontube3, falcontube4], transfer_hardware=valve1, bottom_clearance_withdrawing=8, dropoff_locations=[(flaskstation, 0), (falcon_tube_holder_15ml, 0), (falcon_tube_holder_15ml, 0)])

if __name__ == '__main__':
    esb = EmergencyStopButton.EmergencyStopButton(com_port='COM34')
    eln = Minerva.Software.OpenBISELNIntegration.OpenBisElnIntegration.ElectronicLabNotebook(space_name='1.0_MINERVA', project_code='CORE_SHELL')
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
    hotplate1_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_50mL_Heating_Block, parent_hardware=hotplate1, deck_position=1)
    hotplate2_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_50mL_Heating_Block, parent_hardware=hotplate2, deck_position=2)
    hotplate3_holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_50mL_Heating_Block, parent_hardware=hotplate3, deck_position=3)
    ot2_holder_15ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_15mL_Tube_Rack, parent_hardware=ot2, deck_position=2)
    ot2_holder_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_50mL_Tube_Rack, parent_hardware=ot2, deck_position=1)
    ot2_holder_flask_100ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_100mL_Flask_Rack, parent_hardware=ot2, deck_position=6)
    ot2_holder_flask_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_50mL_Flask_Rack, parent_hardware=ot2, deck_position=3)
    falcon_tube_holder_50ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_50mL_Foldable_Tube_Rack, deck_position=1)
    falcon_tube_holder_15ml = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_15mL_Foldable_Tube_Rack, deck_position=2)
    flaskstation = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Flask_Station, deck_position=3, leave_even_rows_empty=False)

    flask_1_50ml = Container(flaskstation, slot_number=1, container_type=ContainerTypeCollection.FLASK_50_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask1')
    flask_2_50ml = Container(flaskstation, slot_number=2, container_type=ContainerTypeCollection.FLASK_50_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask2')
    flask_3_50ml = Container(flaskstation, slot_number=3, container_type=ContainerTypeCollection.FLASK_50_ML, current_volume=Volume(0, 'mL'), has_stirbar=True, name='flask3')
    flask_1_100ml = Container(flaskstation, slot_number=5, container_type=ContainerTypeCollection.FLASK_100_ML, current_volume=Volume(0, 'mL'), has_stirbar=False, name='flask5')

    falcontube1_15ml = Container(falcon_tube_holder_15ml, slot_number=1, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube2_15ml = Container(falcon_tube_holder_15ml, slot_number=2, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube3_15ml = Container(falcon_tube_holder_15ml, slot_number=3, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube4_15ml = Container(falcon_tube_holder_15ml, slot_number=4, container_type=ContainerTypeCollection.FALCON_TUBE_15_ML, current_volume='0 mL', is_capped=True)
    falcontube_for_cleaning = Container(falcon_tube_holder_50ml, slot_number=14, container_type=ContainerTypeCollection.FALCON_TUBE_50_ML, current_volume='40 mL', is_capped=False)

    WasteContainerValve1 = Container(current_hardware=valve1, slot_number=0, name='Waste_Container', current_volume='2 L', max_volume='5 L')
    WasteContainerValve2 = Container(current_hardware=valve2, slot_number=6, name='Waste_ContainerValve2', current_volume='0 mL', max_volume='50 mL')
    DLSCell = Container(current_hardware=valve1, slot_number=4, name='DLS_Cell', current_volume='0 mL')
    MilliQ_ContainerValve1 = Container(current_hardware=valve1, slot_number=1, name='MilliQ_ContainerValve1', current_volume='1.2 L')
    Ethanol_wash_container = Container(current_hardware=valve1, slot_number=5, name='Ethanol_wash', current_volume='5 L')
    NH4NO3Container = Container(current_hardware=valve1, slot_number=6, name='NH4NO3_Container', current_volume='10 mL')

    Ethanol_wash = Chemical(container=Ethanol_wash_container, name='Ethanol', volume='6 mL', lookup_missing_values=True)
    Water_wash = Chemical(container=MilliQ_ContainerValve1, name='Water', volume='6 mL', lookup_missing_values=True)

    TEOSContainer = Container(current_hardware=valve2, slot_number=9, name='TEOS_Container', current_volume='35 mL', container_type=ContainerTypeCollection.FALCON_TUBE_50_ML)
    MilliQOT2 = Container(current_hardware=ot2, deck_position=8, slot_number=8, name='MilliQOT2', current_volume='31 mL', container_type=ContainerTypeCollection.FALCON_TUBE_50_ML)
    CTABContainer = Container(current_hardware=ot2, deck_position=8, slot_number=7, name='CTAB_Container', current_volume='17 mL', container_type=ContainerTypeCollection.FALCON_TUBE_50_ML)
    L_ArgContainer = Container(current_hardware=ot2, deck_position=8, slot_number=1, name='L_ArgContainer', current_volume='3 mL', container_type=ContainerTypeCollection.FALCON_TUBE_15_ML)
    CuOContainer = Container(current_hardware=ot2, deck_position=8, slot_number=2, name='CuOContainer', current_volume='5.1 mL', container_type=ContainerTypeCollection.FALCON_TUBE_15_ML)
    NH4NO3 = Chemical(container=NH4NO3Container, volume='6 mL', mass_concentration='20 mg/mL', lookup_missing_values=True)

    sonication_time = '20 s'
    centrifugation_speed = '14000 rcf'
    centrifugation_time = '15 min'
    washing_steps = 2
    sample_name = 'MZ023'

    ot2_configuration = {
        1: ot2_holder_15ml,
        2: ot2_holder_flask_10ml,
        3: ot2_holder_flask_25ml,
        4: ot2_holder_flask_100ml,
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
        6: NH4NO3Container,
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
    pump2.set_syringe(Syringes.GLASS_SYRINGE_SOCOREX_1ML, default_addition_rate='3 mL/min')
    valve2.set_configuration(valve2_configuration)
    valve2.set_dead_volumes(valve2_dead_volumes)
    pump3.set_syringe(Syringes.GLASS_SYRINGE_SOCOREX_5ML, default_addition_rate='20 mL/min')
    valve3.set_configuration(valve3_configuration)

    CuO_CoreShell_Synthesis_parameters = ((flask_1_50ml, falcontube1_15ml, falcontube2_15ml))

    threads = []
    for i, p in enumerate(CuO_CoreShell_Synthesis_parameters):
        threads.append(threading.Thread(name=f'Thread_{i}', target=CuO_CoreShell_Synthesis, args=tuple(p)))
        threads[-1].start()

    for t in threads:
        t.join()

    # Washing after synthesis
    falcontube1_15ml.centrifuge([falcontube2_15ml], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time)
    falcontube1_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Water_wash, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=18, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
    falcontube2_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Water_wash, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=18, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
    for _ in range(0, washing_steps-1):
        falcontube1_15ml.centrifuge([falcontube15ml_counter_reaction], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time)
        falcontube1_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Ethanol_wash, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=18, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
        falcontube2_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Ethanol_wash, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=18, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
    centrifuge.close_lid()

    # Redispersion in ammonium nitrate
    falcontube1_15ml.centrifuge([falcontube2_15ml], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time)
    falcontube1_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=NH4NO3, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=18, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
    falcontube2_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=NH4NO3, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=18, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)

    # extraction protocol
    NH4NO3_Extraction_parameters = ((flask_1_50ml, falcontube1_15ml, falcontube2_15ml, falcontube3_15ml, falcontube4_15ml))

    threads = []
    for i, p in enumerate(NH4NO3_Extraction_parameters):
        threads.append(threading.Thread(name=f'Thread_{i}', target=NH4NO3_extraction, args=tuple(p)))
        threads[-1].start()

    for t in threads:
        t.join()

    # washing after extraction
    for _ in range(0, washing_steps):
        falcontube3_15ml.centrifuge([falcontube4_15ml], centrifugation_speed=centrifugation_speed, centrifugation_time=centrifugation_time)
        falcontube3_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Ethanol_wash, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=15, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
        falcontube4_15ml.remove_supernatant_and_redisperse(waste_container=WasteContainerValve1, sonication_time=sonication_time, redispersion_chemical=Ethanol_wash, sonication_power=20, sonication_amplitude=20, sonicator=probesonicator, bottom_clearance_sonication=15, bottom_clearance_withdrawing=12, container_for_cleaning=falcontube_for_cleaning)
    centrifuge.close_lid()

    #ELN upload
    eln.write_synthesis_step(experiment_name=f"{sample_name1}")
