/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef CapperDecapper_h
#define CapperDecapper_h
#include <Servo.h>
#include <Wire.h>
#include <INA219_WE.h>
#include <Arduino.h>
#include "HelperFunctions.h"
class CapperDecapper {
public:
  CapperDecapper(void);
  CapperDecapper(byte dcMotorPin1, byte dcMotorPin2, byte servoPin, int pressureSensorPin, int currentSensorDCMotorAddress=0x40, int currentSensorServoMotorAddress=0x41, int servoClosedPosDegrees=0, int servoOpenedPosDegrees=180, int servoClosedPosMillimeters = 4, int servoOpenedPosMillimeters=59);
  int readPressureSensor(byte averages=16, bool logResults=true);
  float readCurrentSensorDCMotor(byte averages=8, bool logResults=true, bool logAll=false);
  float readCurrentSensorServoMotor(byte averages=8, bool logResults=true, bool logAll=false);
  void logSensorSignals(unsigned long timeout=5000, bool logResults=true);
  bool openContainer(int pos=31, int pThreshold=100, int timeout=10000);
  bool closeContainer(int pThreshold=1000, float iThreshold=200.0, int timeout=10000);
  void turnWristClockwise(void);
  void turnWristCounterClockwise(void);
  void stopWristRotation(void);
  void setClampPosition(int clampPosition);
  void openClamp(float currentThreshold=1000.0, bool logResults=false);
  void closeClamp(float currentThreshold=350.0, bool logResults=false);
  int currentPos;
  int sensorSignals[3];
  byte errors;
private:
  bool CapperDecapper::initializeCurrentSensor(INA219_WE *currentSensor);
  byte dcMotorPin1;
  byte dcMotorPin2;
  byte servoPin;
  int pressureSensorPin;
  int currentSensorDCMotorAddress;
  int currentSensorServoMotorAddress;
  int servoClosedPosDegrees;
  int servoOpenedPosDegrees;
  int servoClosedPosMillimeters;
  int servoOpenedPosMillimeters;
  float degreesPerMillimeter;
  Servo clampServo;
  INA219_WE currentSensorDCMotor;
  INA219_WE currentSensorServoMotor;
};
#endif
