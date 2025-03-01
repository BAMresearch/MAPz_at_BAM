/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include <Servo.h>
#include "HotplateClampDCMotor.h"
#include "HelperFunctions.h"

HotplateClampDCMotor::HotplateClampDCMotor(void) {
}

HotplateClampDCMotor::HotplateClampDCMotor(byte dcMotorPin1, byte dcMotorPin2, byte servoPin, byte currentSensorPin, byte switchPinUp, byte switchPinDown , int servoClosedPos=0, int servoOpenedPos=180) {
  
  pinMode(dcMotorPin1, OUTPUT);
  pinMode(dcMotorPin2, OUTPUT);
  pinMode(servoPin, OUTPUT);
  pinMode(currentSensorPin, INPUT);
  pinMode(switchPinUp, INPUT);
  pinMode(switchPinDown, INPUT);  
  this->errors = 0;
  
  this->dcMotorPin1 = dcMotorPin1;
  this->dcMotorPin2 = dcMotorPin2;
  this->servoPin = servoPin;
  this->currentSensorPin = currentSensorPin;
  this->switchPinUp = switchPinUp;
  this->switchPinDown = switchPinDown;
  this->servoClosedPos = servoClosedPos;
  this->servoOpenedPos = servoOpenedPos;
  
  this->clampServo = Servo();
  this->clampServo.write(servoOpenedPos);
  this->clampServo.attach(servoPin);
  this->currentServoPos = servoOpenedPos;
}

bool HotplateClampDCMotor::goUp(int currentThreshold) {
  const int timeout = 30000;  // if the target position was not reached after 30 sec, give up
  unsigned long startTime = millis();
  
  digitalWrite(this->dcMotorPin1, HIGH);
  digitalWrite(this->dcMotorPin2, LOW);
  HotplateClampDCMotor::getCurrentSensorData();
  delay(1500); //wait for 1500 ms before taking the first current reading
  while ((abs(HotplateClampDCMotor::getCurrentSensorData()) < abs(currentThreshold)) && !isTimedOut(startTime, timeout)) {
    delay(10);
  }
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
  if (isTimedOut(startTime, timeout)) {
    this->errors = 3;
    return false;
  } else {
    this->errors = 0;
    return true;
  }
}

bool HotplateClampDCMotor::goUp() {
  const int timeout = 30000;  // if the target position was not reached after 30 sec, give up
  unsigned long startTime = millis();

  digitalWrite(this->dcMotorPin1, HIGH);
  digitalWrite(this->dcMotorPin2, LOW);
  
  while (digitalRead(this->switchPinUp)==HIGH && !isTimedOut(startTime, timeout))
  {
    delayMicroseconds(2000);
  }

  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);

  delayMicroseconds(2000);
  if (digitalRead(this->switchPinUp)==HIGH) {
    this->errors = 3;  // timeout
    return false;    
  }
  // back off a little bit from the top position
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, HIGH);
  delay(250);
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
  
  return true;
}

bool HotplateClampDCMotor::goDown(int currentThreshold) {
  const int timeout = 30000;  // if the target position was not reached after 30 sec, give up
  unsigned long startTime = millis();

  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, HIGH);
  HotplateClampDCMotor::getCurrentSensorData();
  delay(500);  //wait for 500 ms before taking the first current reading
  while ((abs(HotplateClampDCMotor::getCurrentSensorData()) < abs(currentThreshold)) && !isTimedOut(startTime, timeout)) {
    delay(10);
  }
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
  if (isTimedOut(startTime, timeout)) {
    this->errors = 3;
    return false;
  } else {
    this->errors = 0;
    return true;
  }
}

bool HotplateClampDCMotor::goDown() {
  const int timeout = 30000;  // if the target position was not reached after 30 sec, give up
  unsigned long startTime = millis();

  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, HIGH);
  
  while (digitalRead(this->switchPinDown)==HIGH && !isTimedOut(startTime, timeout))
  {
    delayMicroseconds(2000);
  }

  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);

  delayMicroseconds(2000);
  if (digitalRead(this->switchPinDown)==HIGH) {
    this->errors = 3;  // timeout
    return false;    
  }
  // back off a little bit from the bottom position
  digitalWrite(this->dcMotorPin1, HIGH);
  digitalWrite(this->dcMotorPin2, LOW);
  delay(150);
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
  
  return true;
}

bool HotplateClampDCMotor::stopStage() {
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
  return true;
}

float HotplateClampDCMotor::getCurrentSensorData(int averages=3) {
  float current = 6000.f;
  float r;
  analogRead(this->currentSensorPin);  // discard first reading
  delay(10);
  for (int i = 0; i < averages; i++) {
    r = (2.5 - (analogRead(this->currentSensorPin)*5.0)/1024.0)/0.185*1000;
    if (abs(r) < abs(current)) {
      current = r;
    }
    delay(10);
  }
  current = current/averages;
  return current;
}

void HotplateClampDCMotor::openClamp(int servoPos=-1, int slowdownDegrees=20) {
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
  
  this->clampServo.write(this->servoOpenedPos - inc*slowdownDegrees);
  this->currentServoPos = this->servoOpenedPos - inc*slowdownDegrees;

  for (int i=0; i<slowdownDegrees; i++) {
    this->currentServoPos += inc;
    this->clampServo.write(this->currentServoPos);
    delay(waitPerStep);
  }  

}

void HotplateClampDCMotor::closeClamp(int servoPos=-1, int slowdownDegrees=25) {
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
