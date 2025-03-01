/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include <Arduino.h>
#include <AceSorting.h>
#include <AccelStepper.h>
#include "SwitchingValve.h"
#include "HelperFunctions.h"

SwitchingValve::SwitchingValve(void) {
}

SwitchingValve::SwitchingValve(byte dirPin, byte stepPin, byte sleepPin, int hallSensorPin, byte microSteppingFactor=1, int stepsPerRevolution=200, byte reversedPolarityPos=3, byte ports=6, bool clockwiseNumbering=false, bool enableIsHigh=true) {
  const byte motorInterfaceType = 1;  // Motor interface type for AccelStepper library. Must be set to 1 when using a stepper motor driver
  
  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
  pinMode(sleepPin, OUTPUT);
  pinMode(hallSensorPin, INPUT);
  
  this->currentPos = 0;
  this->errors = 0;
  this->hallSensorIdleSignal = 0;
  this->hallSensorThreshold = 0;
  
  this->dirPin = dirPin;
  this->stepPin = stepPin;
  this->sleepPin = sleepPin;
  this->hallSensorPin = hallSensorPin;
  this->microSteppingFactor = microSteppingFactor;
  this->stepsPerRevolution = stepsPerRevolution * microSteppingFactor;
  this->reversedPolarityPos = reversedPolarityPos;
  this->ports = ports;
  this->clockwiseNumbering = clockwiseNumbering;
  this->enableIsHigh = enableIsHigh;
  
  this->valveStepper = AccelStepper(motorInterfaceType, stepPin, dirPin);
  this->valveStepper.setMaxSpeed(2400);
  this->stepsPerSecond = 400;

  this->logHallSensorData = false;  // set to true for debugging
}

void SwitchingValve::takeSteps(int dir, int steps, int stepsPerSec = 400) {
  stepsPerSec *= this->microSteppingFactor;
  if (this->clockwiseNumbering) {
    dir *= -1;
  }
  this->valveStepper.setCurrentPosition(0);
  while (this->valveStepper.currentPosition() != dir*steps)
  {
    this->valveStepper.setSpeed(dir*abs(stepsPerSec));
    this->valveStepper.runSpeed();
  }
}

int SwitchingValve::readHallSensorSignal(bool logResults=true) {
  int hallAnalogSignal=0;
  const int AVG = 4;
  
  analogRead(this->hallSensorPin);  // Discard first reading (reduces crosstalk when switching input pins)
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

bool SwitchingValve::gotoPosition(byte targetPos) {
  const int timeout = 2000;  // if the target position was not reached after 2 sec, give up
  byte mul = 3*this->microSteppingFactor;  // move 3 full steps at once
  int dir;
  int hallSignal = 0;
  int signalSteps = 0;
  byte signalCounter = 0;
  bool isAboveThreshold = false;
  unsigned long startTime = millis();

  if (mod(targetPos - this->currentPos, this->ports) < this->ports/2) {
    dir = 1;
    signalSteps = mod(targetPos-this->currentPos, this->ports);
  } else {
    dir = -1;
    signalSteps = this->ports-mod(targetPos-this->currentPos, this->ports);
  }

  digitalWrite(this->sleepPin, this->enableIsHigh);
  // Coarse adjustment: move in multiple steps
  while (signalCounter <= signalSteps) {
    this->takeSteps(dir, mul, this->stepsPerSecond);

    if (isTimedOut(startTime, timeout)) {
      digitalWrite(this->sleepPin, !(this->enableIsHigh));
      this->errors = 3;
      return true;  
    }
    hallSignal = this->readHallSensorSignal();
    if (!isAboveThreshold && ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold))) {
      signalCounter ++;
      isAboveThreshold = true;
    }
    if ((abs(hallSignal - this->hallSensorIdleSignal) < this->hallSensorThreshold)) {
      isAboveThreshold = false;
      if (signalCounter == signalSteps) {
        mul = this->microSteppingFactor;  // Reduce step width on falling flank of second to last peak for more precision when approaching last peak
      }
    }
  }

  // Fine adjustment: move in single steps
  int lastRead = hallSignal;
  while (!isAboveThreshold || (isAboveThreshold && (abs(lastRead - this->hallSensorIdleSignal) <= abs(hallSignal - this->hallSensorIdleSignal)))) {
    if (isTimedOut(startTime, timeout)) {
      digitalWrite(this->sleepPin, !(this->enableIsHigh));
      this->errors = 3;
      return false;  
    }
    takeSteps(dir, 1, this->stepsPerSecond);
    lastRead = hallSignal;
    hallSignal = this->readHallSensorSignal();
    isAboveThreshold = ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold));    
  }

  digitalWrite(this->sleepPin, !(this->enableIsHigh));
  this->currentPos = targetPos;
  this->errors = 0;
  return true;
}

bool SwitchingValve::initializeValve(void) {
  const int timeout = 2000;  // if the target position was not reached after 2 sec, give up
  const byte mul = 3*this->microSteppingFactor;  // move 3 full steps at once
  byte dir = 1;  // Go clockwise (arbitrary choice here)
  bool majorityHasPositivePolarity;
  byte posPolarityCounter = 0;
  byte negPolarityCounter = 0;
  int hallSignal = this->readHallSensorSignal();
  int stepsTaken = 0;
  bool isAboveThreshold = (abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold);
  byte signalCounter = 0;
  unsigned long startTime;
  int sensorSignals[(int)((float)this->stepsPerRevolution / mul)+1];
  int minValuesTmp[64];

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
  
  // Enable motor driver
  digitalWrite(this->sleepPin, this->enableIsHigh);

  this->hallSensorIdleSignal = 512;
  // Do a full rotation to calibrate the hall sensor
  for (int i=0; i < (sizeof(sensorSignals) / sizeof(int)); i++) {
    this->takeSteps(dir, mul, this->stepsPerSecond);
    sensorSignals[i] = this->readHallSensorSignal();
  }

  int j = 0;
  for (int i=1; i < (sizeof(sensorSignals) / sizeof(int)) - 1; i++) {
    if ((sensorSignals[i-1] >= sensorSignals[i]) && (sensorSignals[i+1] >= sensorSignals[i])) {
      minValuesTmp[j%64] = sensorSignals[i];
      j++;
    }
  }
  j=j%64;
  int minValues[j];
  for (int i=0; i < (sizeof(minValues) / sizeof(int)); i++) {
    minValues[i] = minValuesTmp[i];
  }

  ace_sorting::shellSortKnuth(minValues, sizeof(minValues) / sizeof(int));
  this->hallSensorIdleSignal = minValues[(int)(sizeof(minValues) / sizeof(int) * 0.5)];

  int maxValues[64];
  j = 0;
  for (int i=1; i < (sizeof(sensorSignals) / sizeof(int)) - 1; i++) {
    if ((abs(sensorSignals[i-1] - this->hallSensorIdleSignal) <= abs(sensorSignals[i] - this->hallSensorIdleSignal)) && (abs(sensorSignals[i+1] - this->hallSensorIdleSignal) <= abs(sensorSignals[i] - this->hallSensorIdleSignal))) {
      maxValues[j%64] = abs(sensorSignals[i] - this->hallSensorIdleSignal);
      j++;
    }
  }
  for (int i=j; i < (sizeof(maxValues) / sizeof(int)) - 1; i++) {
    maxValues[i] = 0;
  }

  ace_sorting::shellSortKnuth(maxValues, sizeof(maxValues) / sizeof(int));
  this->hallSensorThreshold = (int)(maxValues[(int)(sizeof(maxValues) / sizeof(int)) - this->ports] * 0.36787);

  // Do another full rotation, make sure that all magnets are present and check their polarity
  stepsTaken = 0;
  hallSignal = this->readHallSensorSignal();
  isAboveThreshold = (abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold);
  while (stepsTaken < (int)((float)this->stepsPerRevolution / mul)+1) {
    this->takeSteps(dir, mul, this->stepsPerSecond);
    hallSignal = this->readHallSensorSignal();
    if (!isAboveThreshold && ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold))) {
      isAboveThreshold = true;
      if (hallSignal > this->hallSensorIdleSignal) {
        posPolarityCounter ++;
      } else {
        negPolarityCounter ++;
      }
    }
    if (abs(hallSignal - this->hallSensorIdleSignal) < this->hallSensorThreshold) {
      isAboveThreshold = false;
    }
    stepsTaken++;
  }
  
  if (abs(posPolarityCounter - negPolarityCounter) != this->ports - 2) {
    digitalWrite(this->sleepPin, !(this->enableIsHigh));
    this->errors = 2;
    return false;
  }

  majorityHasPositivePolarity = (posPolarityCounter > negPolarityCounter);
  startTime = millis();
  
  // Find the position with opposite polarity
  if (isAboveThreshold && ((hallSignal > this->hallSensorIdleSignal) != majorityHasPositivePolarity)) {
    this->currentPos = this->reversedPolarityPos;
  } else {
    while (signalCounter <= 2*this->ports) {
      if (isTimedOut(startTime, timeout)) {
        digitalWrite(this->sleepPin, !(this->enableIsHigh));
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
      takeSteps(dir, mul, this->stepsPerSecond);
    }
  }
  if (signalCounter >= 2*this->ports) {
    digitalWrite(this->sleepPin, !(this->enableIsHigh));
    this->errors = 2;
    return false;
  }

  // find the peak with reversed polarity (fine adjustment)
  int lastRead = hallSignal;
  while (abs(lastRead - this->hallSensorIdleSignal) <= abs(hallSignal - this->hallSensorIdleSignal)) {
    if (isTimedOut(startTime, timeout)) {
      digitalWrite(this->sleepPin, !(this->enableIsHigh));
      this->errors = 3;
      return false;  
    }
    takeSteps(dir, 1, this->stepsPerSecond);
    lastRead = hallSignal;
    hallSignal = this->readHallSensorSignal();
    isAboveThreshold = ((abs(hallSignal - this->hallSensorIdleSignal) >= this->hallSensorThreshold));    
  }
  takeSteps(-dir, 1, this->stepsPerSecond);  // take 1 step back again (always overshoots by 1 step)
  digitalWrite(this->sleepPin, !(this->enableIsHigh));
  this->currentPos = this->reversedPolarityPos;
  this->gotoPosition(0);
  this->errors = 0;
  return true;
}
