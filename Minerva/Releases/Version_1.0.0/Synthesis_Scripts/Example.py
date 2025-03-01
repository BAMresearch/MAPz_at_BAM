#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2022, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "0.9.1"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"
import Minerva

if __name__ == '__main__':
    # Define and initialize hardware
    robotArm = UFactory.XArm6(ip_address='192.168.1.204')
    ot2 = OpentronsOT2.OT2(ip_address='OT2CEP20210918R04.local')
    centrifuge = Herolab.RobotCen(com_port='COM8', initialize_rotor=False, home_rotor=False)
    valve1 = SwitchingValve.SwitchingValve(com_port='COM10')
    probeSonicator = Hielscher.UP200ST(ip_address='192.168.233.233')
    bathSonicator = Bandelin.SonorexDigitecHRC(com_port='COM15')
    hotPlate1 = IkaHotplate.RCTDigital5(com_port='COM18')
    hotPlate2 = IkaHotplate.RCTDigital5(com_port='COM4')
    hotPlate3 = IkaHotplate.RCTDigital5(com_port='COM6')
    syringe_pump = WPI.Aladdin(com_port='COM14')

    # Define Holders that are available
    holder1 = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_50mL_Foldable_Tube_Rack, deck_position=1)
    holder2 = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Isolab_15mL_Foldable_Tube_Rack, deck_position=2)
    corkRing1 = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Corkring_Small, deck_position=3)
    ot2Holder1 = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_50mL_Tube_Rack, parent_hardware=ot2, deck_position=1)
    ot2Holder2 = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_15mL_Tube_Rack, parent_hardware=ot2, deck_position=2)
    ot2Holder3 = SampleHolder.SampleHolder(SampleHolder.SampleHolderDefinitions.Opentrons_50mL_Flask_Rack, parent_hardware=ot2, deck_position=3)
    labsolute1000uLTipRack = SampleHolder.SampleHolder(SampleHolderDefinitions.Labsolute_96_Tip_Rack_1000uL, parent_hardware=ot2, deck_position=11)
    hotplate1Holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_50mL_Heating_Block, parent_hardware=hotPlate1, deck_position=1)
    hotplate2Holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_50mL_Heating_Block, parent_hardware=hotPlate2, deck_position=2)
    hotplate3Holder = SampleHolder.SampleHolder(SampleHolderDefinitions.Ika_50mL_Heating_Block, parent_hardware=hotPlate3, deck_position=3)

    # Define containers and chemicals that are available
    reactionFlask = Container(current_hardware=corkRing1, slot_number=1, name='Reaction Flask', container_type=ContainerTypeCollection.FLASK_50_ML)

    WasteContainer = Container(current_hardware=valve1, deck_position=0, name='Waste_Container', max_volume=Volume(5, 'L'))
    AirForPurging = Container(current_hardware=valve1, deck_position=1, name='Air')
    EtOHForWashingContainer = Container(current_hardware=valve1, deck_position=2, name='EtOH_Canister', current_volume=Volume(5, 'L'))
    AcetoneForWashingContainer = Container(current_hardware=valve1, deck_position=3, name='Acetone_Canister', current_volume=Volume(5, 'L'))
    WaterForWashingContainer = Container(current_hardware=valve1, deck_position=4, name='Water_Canister', current_volume=Volume(5, 'L'))

    EtOHContainer = Container(current_hardware=ot2, deck_position=8, slot_number=9, name='EtOH_Container', current_volume='50 mL', container_type=ContainerTypeCollection.FALCON_TUBE_50_ML)
    CTABContainer = Container(current_hardware=ot2, deck_position=8, slot_number=7, name='CTAB_Container', current_volume='50 mL', container_type=ContainerTypeCollection.FALCON_TUBE_50_ML)
    NH4OHContainer = Container(current_hardware=ot2, deck_position=8, slot_number=1, name='NH4OH_Container', current_volume='15 mL', container_type=ContainerTypeCollection.FALCON_TUBE_15_ML)
    TEOSContainer = Container(current_hardware=ot2, deck_position=8, slot_number=4, name='TEOS_Container', current_volume='15 mL', container_type=ContainerTypeCollection.FALCON_TUBE_15_ML)

    # Stock chemicals
    EtOHForWashing_Stock = Chemical(container=EtOHForWashingContainer, name='Ethanol for washing', is_stock_solution=True)
    AcetoneForWashing_Stock = Chemical(container=AcetoneForWashingContainer, name='Acetone for washing', is_stock_solution=True)
    WaterForWashing_Stock = Chemical(container=WaterForWashingContainer, name='Water for washing', is_stock_solution=True)

    # Washing solutions (showing how to instantiate them from stock solutions)
    EtOHForWashing = Chemical.from_stock_chemical(stock_chemical=EtOHForWashing_Stock, volume=Volume(50, 'mL'))
    AcetoneForWashing = Chemical.from_stock_chemical(stock_chemical=AcetoneForWashing_Stock, volume=Volume(50, 'mL'))
    WaterForWashing = Chemical.from_stock_chemical(stock_chemical=WaterForWashing_Stock, volume=Volume(50, 'mL'))

    # Reagents (showing how to instantiate them from scratch)
    EtOH = Chemical(container=EtOHContainer, name='Ethanol', volume='1 mL')
    CTAB = Chemical(container=CTABContainer, name='CTAB', concentration='500 mM', mass='200 mg')
    Ammonia = Chemical(container=NH4OHContainer, name='Ammonia', molar_amount='0.01 mol', mass_concentration=MassConcentration(300, 'g/L'))
    TEOS = Chemical(container=TEOSContainer, name='TEOS', cas='78-10-4', molar_amount='2 mmol')

    # Tell the hardware where to find which chemical/container
    OT2Configuration = {
        1: ot2Holder1,
        2: ot2Holder2,
        3: ot2Holder3,
        4: None,
        5: None,
        6: None,
        7: None,
        8: 'opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical',
        9: None,
        10: 'opentrons_96_tiprack_20ul',
        11: 'labsolute_96_tiprack_1000ul',
        12: 'p1000_single_gen2',  # left pipette
        13: 'p20_single_gen2',  # right pipette
    }

    ValveConfiguration = {
        0: WasteContainer,
        1: AirForPurging,
        2: EtOHForWashingContainer,
        3: AcetoneForWashingContainer,
        4: WaterForWashingContainer,
        5: 'Outlet',
        6: syringe_pump
    }

    ot2.set_hardware_configuration(OT2Configuration)
    valve1.set_configuration(ValveConfiguration)

    # Run the actual reaction
    reactionFlask.add_chemical([EtOH, CTAB, Ammonia, TEOS], robotArm)
    reactionFlask.heat(heating_temperature=Temperature(80, 'C'), stirring_speed=300, heating_time=Time(10, 's'))
    reactionFlask.move(corkRing1)

    # Manually save the current configuration to the specified path (it will also be autosaved unless this feature was disabled by calling MinervaAPI.Configuration.disable_autosave_on_exit().)
    Minerva.Configuration.save_configuration(configuration_file_path='./Example_Config.json', update_name_mappings=True)
