/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include <AceSorting.h>
#include "SwitchingValveDCMotor.h"
#include "HelperFunctions.h"

SwitchingValveDCMotor::SwitchingValveDCMotor(void) {
}

SwitchingValveDCMotor::SwitchingValveDCMotor(byte dcMotorPin1, byte dcMotorPin2, int hallSensorPin, byte reversedPolarityPos=5, byte ports=10, bool clockwiseNumbering=false) {
  
  pinMode(dcMotorPin1, OUTPUT);
  pinMode(dcMotorPin2, OUTPUT);
  pinMode(hallSensorPin, INPUT);
  
  this->currentPos = 0;
  this->errors = 0;
  this->hallSensorIdleSignal = 0;
  this->hallSensorThreshold = 0;
  
  this->dcMotorPin1 = dcMotorPin1;
  this->dcMotorPin2 = dcMotorPin2;
  this->hallSensorPin = hallSensorPin;
  this->reversedPolarityPos = reversedPolarityPos;
  this->ports = ports;
  this->clockwiseNumbering = clockwiseNumbering;
  
  this->logHallSensorData = false;  // set to true for debugging
}

void SwitchingValveDCMotor::startTurning(bool dirIncreasing) {
  if ((this->clockwiseNumbering && dirIncreasing) || (!this->clockwiseNumbering && !dirIncreasing)) {
    digitalWrite(this->dcMotorPin1, HIGH);
    digitalWrite(this->dcMotorPin2, LOW);
  } else {
    digitalWrite(this->dcMotorPin1, LOW);
    digitalWrite(this->dcMotorPin2, HIGH);
  }
}

void SwitchingValveDCMotor::stopTurning() {
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
}

int SwitchingValveDCMotor::readHallSensorSignal(bool logResults=true) {
  int hallAnalogSignal=0;
  const int AVG = 4;
  
  analogRead(this->hallSensorPin); // Discard first reading (reduces crosstalk when switching input pins)
  delayMicroseconds(100);
  
  for (int i = 0; i < AVG; i++) {  // Average a few readings to reduce noise
    hallAnalogSignal += analogRead(this->hallSensorPin);
    delayMicroseconds(100);
  }
  hallAnalogSignal /= AVG;
  if (this->logHallSensorData && logResults) {
    Serial.print(hallAnalogSignal-this->hallSensorIdleSignal);
    Serial.print("\t");
    Serial.print(this->hallSensorThreshold);
    Serial.print("\t");
    Serial.print(-this->hallSensorThreshold);
    Serial.print("\n");
  }
  return hallAnalogSignal;
}

bool SwitchingValveDCMotor::gotoPosition(byte targetPos) {
  const int timeout = 1500;  // if the target position was not reached after 1.5 sec, give up
  bool dirIncreasing;
  int hallSignal = 0;
  int signalSteps = 0;
  byte signalCounter = 0;
  bool isAboveThreshold = false;
  unsigned long startTime = millis();

  if (mod(targetPos - this->currentPos, this->ports) < this->ports/2) {
    dirIncreasing = false;
    signalSteps = mod(targetPos-this->currentPos, this->ports);
  } else {
    dirIncreasing = true;
    signalSteps = this->ports-mod(targetPos-this->currentPos, this->ports);
  }

  this->startTurning(dirIncreasing);
  while (signalCounter <= signalSteps) {
    if (isTimedOut(startTime, timeout)) {
      this->stopTurning();
      this->errors = 3;
      return false;  
    }
    hallSignal = this->readHallSensorSignal();
    if (!isAboveThreshold && ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold))) {
      signalCounter ++;
      isAboveThreshold = true;
    }
    if ((abs(hallSignal - this->hallSensorIdleSignal) < this->hallSensorThreshold)) {
      isAboveThreshold = false;
    }
  }
  this->stopTurning();
  
  this->currentPos = targetPos;
  this->errors = 0;
  return true;
}

bool SwitchingValveDCMotor::initializeValve(void) {
  const int timeout = 3000;  // if the target position was not reached after 2 sec, give up
  bool dirIncreasing = true;  // Arbitrary choice here
  bool majorityHasPositivePolarity;
  byte posPolarityCounter = 0;
  byte negPolarityCounter = 0;
  int hallSignal;
  bool isAboveThreshold;
  byte signalCounter = 0;
  unsigned long startTime;
  int sensorSignals[512];
  int minValuesTmp[64];
  int minValue = 1023;
  int maxValue = 0;

  // Make sure the Hall sensor is responding
  this->hallSensorThreshold = 0;
  this->hallSensorIdleSignal = 0;
  for (int i=0; i < 3; i++) {
    this->hallSensorIdleSignal+= this->readHallSensorSignal(false);
    delayMicroseconds(2000);
  }
  if (this->hallSensorIdleSignal == 0) {
    this->errors = 1;
    return false;
  }
  hallSignal = this->readHallSensorSignal();
  isAboveThreshold = (abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold);
  
  this->hallSensorIdleSignal = 512;

  this->startTurning(dirIncreasing);
  // Rotate for a few seconds to calibrate the hall sensor
  for (int i=0; i < (sizeof(sensorSignals) / sizeof(int)); i++) {
    sensorSignals[i] = this->readHallSensorSignal();
    if (sensorSignals[i] > maxValue && abs(sensorSignals[i]-this->hallSensorIdleSignal)<200) {
      maxValue = sensorSignals[i];
    } else if (sensorSignals[i] < minValue && abs(sensorSignals[i]-this->hallSensorIdleSignal)<200) {
      minValue = sensorSignals[i];
    }
  }
  this->stopTurning();

  int j = 0;
  for (int i=1; i < (sizeof(sensorSignals) / sizeof(int)) - 1; i++) {
    if ((sensorSignals[i-1] >= sensorSignals[i]) && (sensorSignals[i+1] >= sensorSignals[i])) {
      minValuesTmp[j] = sensorSignals[i];
      j++;
    }
  }
  int minValues[j];
  for (int i=0; i < (sizeof(minValues) / sizeof(int)); i++) {
    minValues[i] = minValuesTmp[i];
  }

  ace_sorting::shellSortKnuth(minValues, sizeof(minValues) / sizeof(int));
  this->hallSensorIdleSignal = minValues[(int)(sizeof(minValues) / sizeof(int) * 0.5)];

  ace_sorting::shellSortKnuth(sensorSignals, sizeof(sensorSignals) / sizeof(int));
  this->hallSensorThreshold = (int)(min(abs(minValue - this->hallSensorIdleSignal), abs(maxValue - this->hallSensorIdleSignal))/2.5);

  // Do two full rotations to check magnet polarity
  hallSignal = this->readHallSensorSignal();
  isAboveThreshold = (abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold);
  startTime = millis();
  this->startTurning(dirIncreasing);
  while (signalCounter < 2 * this->ports) {
    hallSignal = this->readHallSensorSignal();
    if (!isAboveThreshold && ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold))) {
      isAboveThreshold = true;
      signalCounter++;
      if (hallSignal > this->hallSensorIdleSignal) {
        posPolarityCounter ++;
      } else {
        negPolarityCounter ++;
      }
    }
    if (abs(hallSignal - this->hallSensorIdleSignal) < this->hallSensorThreshold) {
      isAboveThreshold = false;
    }
    if (isTimedOut(startTime, timeout)) {
      this->stopTurning();
      this->errors = 3;
      return false;  
    }
  }
  this->stopTurning();
  if (abs(posPolarityCounter - negPolarityCounter) != 2 * (this->ports - 2)) {
    this->errors = 2;
    return false;
  }

  majorityHasPositivePolarity = (posPolarityCounter > negPolarityCounter);
  startTime = millis();
  signalCounter = 0;
  
  // Find the position with opposite polarity
  this->startTurning(dirIncreasing);
  if (isAboveThreshold && ((hallSignal > this->hallSensorIdleSignal) != majorityHasPositivePolarity)) {
    this->currentPos = this->reversedPolarityPos;
  } else {
    while (signalCounter <= 2*this->ports) {
      if (isTimedOut(startTime, timeout)) {
        this->stopTurning();
        this->errors = 3;
        return false;
      }
      hallSignal = this->readHallSensorSignal();
      if (!isAboveThreshold && ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold))) {
        signalCounter ++;
        isAboveThreshold = true;
        if ((hallSignal > this->hallSensorIdleSignal) != majorityHasPositivePolarity) {
          break;
        }
      }
      if ((abs(hallSignal - this->hallSensorIdleSignal) < this->hallSensorThreshold)) {
        isAboveThreshold = false;
      }
    }
  }
  this->stopTurning();
  
  if (signalCounter >= 2*this->ports) {
    this->errors = 2;
    return false;
  }

  this->currentPos = this->reversedPolarityPos;
  
  this->gotoPosition(0);
  this->errors = 0;
  return true;
}
