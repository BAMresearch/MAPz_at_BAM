/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef DHT22Sensor_h
#define DHT22Sensor_h
#include <Arduino.h>
#include "SimpleDHT.h"
#include "HelperFunctions.h"

class DHT22Sensor {
public:
  DHT22Sensor(void);
  DHT22Sensor(byte sensorPin);
  float * measure();
  byte errors;
private:
  SimpleDHT22 dhtSensor;
  int sensorPin;
};
#endif
