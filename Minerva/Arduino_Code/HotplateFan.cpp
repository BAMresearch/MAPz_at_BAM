/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include "HotplateFan.h"
#include "HelperFunctions.h"

HotplateFan::HotplateFan(void) {
}

HotplateFan::HotplateFan(byte enablePin) {
  pinMode(enablePin, OUTPUT);
  this->enablePin = enablePin;
}

void HotplateFan::turnOn(void) {
  digitalWrite(this->enablePin, HIGH);
}

void HotplateFan::turnOff(void) {
  digitalWrite(this->enablePin, LOW);
}