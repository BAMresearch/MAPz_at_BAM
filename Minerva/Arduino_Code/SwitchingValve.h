/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef SwitchingValve_h
#define SwitchingValve_h
#include <Arduino.h>
//#include <QuickMedianLib.h>
#include <AceSorting.h>
#include <AccelStepper.h>
#include "HelperFunctions.h"
class SwitchingValve {
public:
  SwitchingValve(void);
  SwitchingValve(byte dirPin, byte stepPin, byte sleepPin, int hallSensorPin, byte microSteppingFactor=1, int stepsPerRevolution=200, byte reversedPolarityPos=3, byte ports=6, bool clockwiseNumbering=false, bool enableIsHigh=true);
  void takeSteps(int dir, int steps, int stepsPerSecond=400);
  int readHallSensorSignal(bool logResults=true);
  bool gotoPosition(byte targetPos);
  bool initializeValve(void);
  byte currentPos;
  byte errors;
  int hallSensorIdleSignal;
  int hallSensorThreshold;
private:
  int dirPin;
  int stepPin;
  int sleepPin;
  int hallSensorPin;
  int microSteppingFactor;
  int stepsPerRevolution;
  int stepsPerSecond;
  byte reversedPolarityPos;
  byte ports;
  byte logHallSensorData;
  bool clockwiseNumbering;
  bool enableIsHigh;
  AccelStepper valveStepper;
};
#endif
