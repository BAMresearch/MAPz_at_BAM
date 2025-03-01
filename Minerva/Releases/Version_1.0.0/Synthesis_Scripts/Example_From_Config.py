#!/usr/bin/env python
# -*- coding: utf-8 -*-

# @author:      "Bastian Ruehle"
# @copyright:   "Copyright 2022, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
# @version:     "0.9.1"
# @maintainer:  "Bastian Ruehle"
# @email        "bastian.ruehle@bam.de"
import Minerva

if __name__ == '__main__':
    # Load previous configuration
    Minerva.Configuration.load_configuration('./Example_Config.json')
    reagents = [c for c in Minerva.Configuration.Chemicals.values()]
    reagents = [Minerva.Configuration.Chemicals['EtOH'],
                Minerva.Configuration.Chemicals['CTAB'],
                Minerva.Configuration.Chemicals['Ammonia'],
                Minerva.Configuration.Chemicals['TEOS']]

    Minerva.Configuration.Containers['reactionFlask'].add_chemical(reagents)
    Minerva.Configuration.Containers['reactionFlask'].heat(heating_temperature='80 C', stirring_speed=300, heating_time=Time(10, 's'))
    Minerva.Configuration.Containers['reactionFlask'].move(Minerva.Configuration.SampleHolder['corkRing1'])

    Minerva.Configuration.save_configuration(globals(), './Example_Config.json')
