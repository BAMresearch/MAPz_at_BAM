/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef HotplateClampStepperMotor_h
#define HotplateClampStepperMotor_h
#include <Arduino.h>
#include <Servo.h>
#include <AccelStepper.h>
#include "HelperFunctions.h"
class HotplateClampStepperMotor {
public:
  HotplateClampStepperMotor(void);
  HotplateClampStepperMotor(byte dirPin, byte stepPin, byte sleepPin, byte servoPin, byte switchPin, int servoClosedPos=0, int servoOpenedPos=180, byte microSteppingFactor=1, int stepsPerRevolution=200, float mmPerRevolution=4.0);
  void takeSteps(int dir, int steps, int stepsPerSecond=600);
  bool gotoPosition(int targetPos);
  bool homePosition();
  bool setCurrentPosition(int currentPos);
  void openClamp(int servoPos=-1, int slowdownDegrees=20);
  void closeClamp(int servoPos=-1, int slowdownDegrees=20);
  int currentPos;
  int currentServoPos;
  byte errors;
private:
  int dirPin;
  int stepPin;
  int sleepPin;
  int servoPin;
  int switchPin;
  int servoClosedPos;
  int servoOpenedPos;
  int microSteppingFactor;
  int stepsPerRevolution;
  float mmPerRevolution;
  AccelStepper stageStepper;
  Servo clampServo;
};
#endif
