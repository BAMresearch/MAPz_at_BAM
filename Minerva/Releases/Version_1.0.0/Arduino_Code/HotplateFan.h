/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef HotplateFan_h
#define HotplateFan_h
#include <Arduino.h>
#include "HelperFunctions.h"
class HotplateFan {
public:
  HotplateFan(void);
  HotplateFan(byte enablePin);
  void turnOn();
  void turnOff();
private:
  int enablePin;
};
#endif
