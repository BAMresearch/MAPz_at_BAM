/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include "Electromagnet.h"
#include "HelperFunctions.h"

Electromagnet::Electromagnet(void) {
}

Electromagnet::Electromagnet(byte electromagnetPin1, byte electromagnetPin2) {
  pinMode(electromagnetPin1, OUTPUT);
  pinMode(electromagnetPin2, OUTPUT);
  
  this->errors = 0;
  
  this->electromagnetPin1 = electromagnetPin1;
  this->electromagnetPin2 = electromagnetPin2;
}

void Electromagnet::magnetOn(bool reversedPolarity = false) {
  digitalWrite(this->electromagnetPin1, !reversedPolarity);
  digitalWrite(this->electromagnetPin2, reversedPolarity);
}

void Electromagnet::magnetOff(void) {
  digitalWrite(this->electromagnetPin1, LOW);
  digitalWrite(this->electromagnetPin2, LOW);
}
