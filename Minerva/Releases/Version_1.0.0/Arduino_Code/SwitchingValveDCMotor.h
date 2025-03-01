/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef SwitchingValveDCMotor_h
#define SwitchingValveDCMotor_h
#include <Arduino.h>
#include <AceSorting.h>
#include "HelperFunctions.h"
class SwitchingValveDCMotor {
public:
  SwitchingValveDCMotor(void);
  SwitchingValveDCMotor(byte dcMotorPin1, byte dcMotorPin2, int hallSensorPin, byte reversedPolarityPos=5, byte ports=10, bool clockwiseNumbering=false);
  void startTurning(bool dirIncreasing);
  void stopTurning();
  int readHallSensorSignal(bool logResults=true);
  bool gotoPosition(byte targetPos);
  bool initializeValve(void);
  byte currentPos;
  byte errors;
  int hallSensorIdleSignal;
  int hallSensorThreshold;
private:
  int dcMotorPin1;
  int dcMotorPin2;
  int hallSensorPin;
  byte reversedPolarityPos;
  byte ports;
  byte logHallSensorData;
  bool clockwiseNumbering;
};
#endif
