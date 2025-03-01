/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include "DHT22Sensor.h"
#include "SimpleDHT.h"
#include "HelperFunctions.h"

DHT22Sensor::DHT22Sensor(void) {
}

DHT22Sensor::DHT22Sensor(byte sensorPin) {
  this->sensorPin = sensorPin;
  this->dhtSensor = SimpleDHT22(this->sensorPin);
  this->errors = 0;
}

float * DHT22Sensor::measure() {
  float t = 0;
  float h = 0;
  int err = SimpleDHTErrSuccess;
  static float res[2];
  
  if ((err = this->dhtSensor.read2(&t, &h, NULL)) != SimpleDHTErrSuccess) {
    this->errors = 1;
    return NULL;
  } else {
    res[0] = t;
    res[1] = h;
    this->errors = 0;
    return res;
  }
}
