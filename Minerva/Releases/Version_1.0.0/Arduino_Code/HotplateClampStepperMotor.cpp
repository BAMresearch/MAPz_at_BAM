/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include <AccelStepper.h>
#include <Servo.h>
#include "HotplateClampStepperMotor.h"
#include "HelperFunctions.h"

HotplateClampStepperMotor::HotplateClampStepperMotor(void) {
}

HotplateClampStepperMotor::HotplateClampStepperMotor(byte dirPin, byte stepPin, byte sleepPin, byte servoPin, byte switchPin, int servoClosedPos=0, int servoOpenedPos=180, byte microSteppingFactor=1, int stepsPerRevolution=200, float mmPerRevolution=4.0) {
  const byte motorInterfaceType = 1;  // Motor interface type for AccelStepper library. Must be set to 1 when using a stepper motor driver
  
  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
  pinMode(sleepPin, OUTPUT);
  pinMode(servoPin, OUTPUT);
  pinMode(switchPin, INPUT);
  
  this->currentPos = 100;
  this->errors = 0;
  
  this->dirPin = dirPin;
  this->stepPin = stepPin;
  this->sleepPin = sleepPin;
  this->servoPin = servoPin;
  this->switchPin = switchPin;
  this->servoClosedPos = servoClosedPos;
  this->servoOpenedPos = servoOpenedPos;
  this->microSteppingFactor = microSteppingFactor;
  this->stepsPerRevolution = stepsPerRevolution;
  this->mmPerRevolution = mmPerRevolution;
  
  this->stageStepper = AccelStepper(motorInterfaceType, stepPin, dirPin);
  this->stageStepper.setMaxSpeed(2400);
  
  this->clampServo = Servo();
  this->clampServo.write(servoOpenedPos);
  this->clampServo.attach(servoPin);
  this->currentServoPos = servoOpenedPos;
}

void HotplateClampStepperMotor::takeSteps(int dir, int steps, int stepsPerSecond = 600) {
  const int timeout = 15000;  // if the target position was not reached after 15 sec, give up
  unsigned long startTime = millis();

  stepsPerSecond *= this->microSteppingFactor;
  dir *= -1;
  this->stageStepper.setCurrentPosition(0);
  while (this->stageStepper.currentPosition() != dir*steps && !isTimedOut(startTime, timeout))
  {
    this->stageStepper.setSpeed(dir*abs(stepsPerSecond));
    this->stageStepper.runSpeed();
  }
  if (this->stageStepper.currentPosition() != dir*steps) {
    this->errors = 1;
  }
}

bool HotplateClampStepperMotor::setCurrentPosition(int currentPos) {
  this->currentPos = currentPos;
  return true;
}

bool HotplateClampStepperMotor::gotoPosition(int targetPos) {
  int dir;

  if (targetPos > this->currentPos) {
    dir = 1;
  } else {
    dir = -1;
  }

  digitalWrite(this->sleepPin, HIGH);
  this->takeSteps(dir, (int)abs(((float)(targetPos - this->currentPos)/this->mmPerRevolution)*this->stepsPerRevolution*this->microSteppingFactor));
  digitalWrite(this->sleepPin, LOW);

  this->currentPos = targetPos;
  return true;
}

bool HotplateClampStepperMotor::homePosition() {
  const int dir = 1;
  const int stepsPerSecond = 600;
  const int timeout = 30000;  // if the target position was not reached after 30 sec, give up
  unsigned long startTime = millis();

  digitalWrite(this->sleepPin, HIGH);
  while (digitalRead(this->switchPin)==HIGH && !isTimedOut(startTime, timeout))
  {
    this->stageStepper.setSpeed(dir*abs(stepsPerSecond));
    this->stageStepper.runSpeed();
    delayMicroseconds(2000);
  }
  digitalWrite(this->sleepPin, LOW);

  delayMicroseconds(2000);
  if (digitalRead(this->switchPin)==HIGH) {
    this->errors = 1;  // timeout
    return false;    
  }

  this->stageStepper.setCurrentPosition(0);
  this->currentPos = 0;
  return true;
}

void HotplateClampStepperMotor::openClamp(int servoPos=-1, int slowdownDegrees=20) {
  int inc;
  const int waitPerStep = 100;

  if (servoPos == -1) {
    servoPos = this->servoOpenedPos;
  }
  
  if (servoPos == this->currentServoPos) {
    return;
  }
  
  slowdownDegrees = min(abs(this->currentServoPos - servoPos), slowdownDegrees);

  if (this->currentServoPos >= servoPos) {
    inc = -1;
  } else {
    inc = 1;
  }
  
  for (int i=0; i<slowdownDegrees; i++) {
    this->currentServoPos += inc;
    this->clampServo.write(this->currentServoPos);
    delay(waitPerStep);
  }  
  
  this->clampServo.write(servoPos);
  this->currentServoPos = servoPos;
}

void HotplateClampStepperMotor::closeClamp(int servoPos=-1, int slowdownDegrees=20) {
  int inc;
  const int waitPerStep = 100;

  if (servoPos == -1) {
    servoPos = this->servoClosedPos;
  }
  
  if (servoPos == this->currentServoPos) {
    return;
  }

  slowdownDegrees = min(abs(this->currentServoPos - servoPos), slowdownDegrees);
  
  if (this->currentServoPos >= servoPos) {
    inc = -1;
  } else {
    inc = 1;
  }
  
  this->clampServo.write(servoPos - inc * slowdownDegrees);
  this->currentServoPos = servoPos - inc * slowdownDegrees;

  for (int i=0; i<slowdownDegrees; i++) {
    this->currentServoPos += inc;
    this->clampServo.write(this->currentServoPos);
    delay(waitPerStep);
  }  

  this->currentServoPos = servoPos;
}
