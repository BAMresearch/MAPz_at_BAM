/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef HotplateClampDCMotor_h
#define HotplateClampDCMotor_h
#include <Arduino.h>
#include <Servo.h>
#include "HelperFunctions.h"
class HotplateClampDCMotor {
public:
  HotplateClampDCMotor(void);
  HotplateClampDCMotor(byte dcMotorPin1, byte dcMotorPin2, byte servoPin, byte currentSensorPin, byte switchPinUp, byte switchPinDown, int servoClosedPos=0, int servoOpenedPos=180);
  bool goUp(int threshold);
  bool goDown(int threshold);
  bool goUp();
  bool goDown();
  bool stopStage();
  bool homePosition();
  float getCurrentSensorData(int averages=3);
  void openClamp(int servoPos=-1, int slowdownDegrees=20);
  void closeClamp(int servoPos=-1, int slowdownDegrees=25);
  int currentServoPos;
  byte errors;
private:
  int dcMotorPin1;
  int dcMotorPin2;
  int servoPin;
  int switchPinUp;
  int switchPinDown;
  int currentSensorPin;
  int servoClosedPos;
  int servoOpenedPos;
  Servo clampServo;
};
#endif
