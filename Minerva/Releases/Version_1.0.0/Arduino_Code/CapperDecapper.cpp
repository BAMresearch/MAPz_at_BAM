/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include "CapperDecapper.h"
 
CapperDecapper::CapperDecapper(void) {
}

CapperDecapper::CapperDecapper(byte dcMotorPin1, byte dcMotorPin2, byte servoPin, int pressureSensorPin, int currentSensorDCMotorAddress=0x40, int currentSensorServoMotorAddress=0x41, int servoClosedPosDegrees=0, int servoOpenedPosDegrees=180, int servoClosedPosMillimeters = 4, int servoOpenedPosMillimeters=59) {
  // Pin conncetions
  this->dcMotorPin1 = dcMotorPin1;
  this->dcMotorPin2 = dcMotorPin2;
  this->servoPin = servoPin;
  this->pressureSensorPin = pressureSensorPin;
  this->currentSensorDCMotorAddress = currentSensorDCMotorAddress;
  this->currentSensorServoMotorAddress = currentSensorServoMotorAddress;
  this->servoClosedPosDegrees = servoClosedPosDegrees;
  this->servoOpenedPosDegrees = servoOpenedPosDegrees;
  this->servoClosedPosMillimeters = servoClosedPosMillimeters;
  this->servoOpenedPosMillimeters = servoOpenedPosMillimeters;
  this->degreesPerMillimeter = (float)(servoOpenedPosDegrees-servoClosedPosDegrees)/(servoOpenedPosMillimeters-servoClosedPosMillimeters);
  this->currentPos = servoOpenedPosMillimeters;
  const byte SDA_Pin = 20;  // I2C Pins on Arduino Mega are 20 (SDA) and 21 (SCL) (on the Uno they are A4 (SDA) and A5 (SCL)) --> Connect to corresponding pins on INA219 current sensor
  const byte SCL_Pin = 21;
  
  // Global variables
  byte errors = 0;
  bool emergencyStopRequest = false;

  // I2C Sensors
  Wire.begin();
  Wire.setWireTimeout(1000000, true); // Timeout in uS, reset on timeout
  this->currentSensorDCMotor = INA219_WE(this->currentSensorDCMotorAddress);
  this->currentSensorServoMotor = INA219_WE(this->currentSensorServoMotorAddress);
  
  // Set pin modes and attach motors
  pinMode(this->servoPin, OUTPUT);
  this->clampServo.write(this->servoOpenedPosDegrees+2);
  this->clampServo.attach(this->servoPin);
  delay(10);
  this->clampServo.write(this->servoOpenedPosDegrees);

  pinMode(this->dcMotorPin1, OUTPUT);
  pinMode(this->dcMotorPin2, OUTPUT);

  // Configure Sensors
  pinMode(this->pressureSensorPin, INPUT);
  
  if (!this->initializeCurrentSensor(&this->currentSensorDCMotor)) {
    this->errors = 1;
    Serial.println("CAPPER>ERROR " + String(errors) + ": " + "CURRENT SENSOR DC MOTOR ERROR");
  }
  if (!this->initializeCurrentSensor(&this->currentSensorServoMotor)) {
    this->errors = 1;
    Serial.println("CAPPER>ERROR " + String(errors) + ": " + "CURRENT SENSOR SERVO MOTOR ERROR");
  }
}

bool CapperDecapper::openContainer(int pos=31, int pThreshold=100, int timeout=10000) {
  unsigned long startTime = millis();
  int pCurrent = 0;
  
  while (!isTimedOut(startTime, timeout) && pCurrent < pThreshold) {
    pCurrent = this->readPressureSensor(64, true);
    delay(10);
  }

  if (pCurrent < pThreshold) {
    return false;
  }

  this->closeClamp(pos);
  this->turnWristCounterClockwise();
  delay(1000); // wait for 1 second before checking if the uncapping is done
  
  startTime = millis();
  while (!isTimedOut(startTime, timeout) && pCurrent > pThreshold) {
    pCurrent = this->readPressureSensor(64, true);
    delay(10);
  }

  if (pCurrent > pThreshold) {
    Serial.print("CAPPER>ERROR: TIMEOUT\n");
    this->openClamp();
  } else {
    Serial.print("CAPPER>OK: STOPPING CRITERION MET\n");
  }
  return (pCurrent <= pThreshold);
}

bool CapperDecapper::closeContainer(int pThreshold=1000, float iThreshold=200.0, int timeout=10000) {
  unsigned long startTime = millis();
  int pCurrent = 0;
  float iCurrent = 0.0;
  
  while (!isTimedOut(startTime, timeout) && pCurrent < pThreshold) {
    pCurrent = this->readPressureSensor(64, true);
    delay(10);
  }

  if (pCurrent < pThreshold) {
    Serial.print("CAPPER>ERROR: TIMEOUT\n");
    return false;
  }
  Serial.print("CAPPER>OK: PRESSURE THRESHOLD REACHED\n");
  
  this->turnWristClockwise();
  delay(1000); // wait for 1 second before checking if the capping is done
  
  startTime = millis();
  while (!isTimedOut(startTime, timeout) && abs(iCurrent) < abs(iThreshold)) {
    iCurrent = this->readCurrentSensorDCMotor(2, true, false);
    delay(10);
  }
  
  if (abs(iCurrent) < abs(iThreshold)) {
    Serial.print("CAPPER>ERROR: TIMEOUT\n");
  } else {
    Serial.print("CAPPER>OK: CURRENT THRESHOLD REACHED\n");
  }
  
  this->openClamp();
  return (iCurrent > iThreshold);
}

void CapperDecapper::turnWristCounterClockwise() {
  digitalWrite(this->dcMotorPin1, HIGH);
  digitalWrite(this->dcMotorPin2, LOW);
}

void CapperDecapper::turnWristClockwise() {
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, HIGH);
}

void CapperDecapper::stopWristRotation() {
  digitalWrite(this->dcMotorPin1, LOW);
  digitalWrite(this->dcMotorPin2, LOW);
}

void CapperDecapper::setClampPosition(int clampPosition) {
  this->clampServo.write(((clampPosition - this->servoClosedPosMillimeters) * this->degreesPerMillimeter + this->servoClosedPosDegrees));
  this->currentPos = clampPosition;
}

void CapperDecapper::openClamp(float currentThreshold=1000.0, bool logResults=false) {
  float iCurrent;
  byte aboveThresholdCounter = 0; 

  iCurrent = this->readCurrentSensorServoMotor(8, false, false);
  if (abs(iCurrent) > abs(currentThreshold)) {
    aboveThresholdCounter++;
  }
  if (logResults) {
    Serial.println("CAPPER>" + String(iCurrent));
  }

  while ((this->currentPos < this->servoOpenedPosMillimeters) && (aboveThresholdCounter < 1)) {
    this->currentPos += 1;
    this->clampServo.write(((this->currentPos - this->servoClosedPosMillimeters)*this->degreesPerMillimeter + this->servoClosedPosDegrees));
    iCurrent = this->readCurrentSensorServoMotor(8, false, false);
    if (abs(iCurrent) > abs(currentThreshold)) {
      aboveThresholdCounter++;
    } else {
      aboveThresholdCounter = 0;
    }
    if (logResults) {
      Serial.println("CAPPER>" + String(iCurrent));
    }
  }
}

void CapperDecapper::closeClamp(float currentThreshold=350.0, bool logResults=false) {
  float iCurrent;
  byte aboveThresholdCounter = 0; 

  iCurrent = this->readCurrentSensorServoMotor(8, false, false);
  if (abs(iCurrent) > abs(currentThreshold)) {
    aboveThresholdCounter++;
  }
  if (logResults) {
    Serial.println("CAPPER>" + String(iCurrent));
  }

  while ((this->currentPos > this->servoClosedPosMillimeters) && (aboveThresholdCounter < 1)) {
    this->currentPos -= 1;
    this->clampServo.write(((this->currentPos - this->servoClosedPosMillimeters)*this->degreesPerMillimeter + this->servoClosedPosDegrees));
    iCurrent = this->readCurrentSensorServoMotor(8, false, false);;
    if (abs(iCurrent) > abs(currentThreshold)) {
      aboveThresholdCounter++;
    } else {
      aboveThresholdCounter = 0;
    }
    if (logResults) {
      Serial.println("CAPPER>" + String(iCurrent));
    }
  }
}

int CapperDecapper::readPressureSensor(byte averages=16, bool logResults=true) {
  long pressureSensorSignal=0;
  analogRead(pressureSensorPin); // Discard first reading after switching analog input pins
  delay(25);

  for (int i = 0; i < averages; i++) {  // Average a few readings to reduce noise
    pressureSensorSignal += analogRead(pressureSensorPin);
    delayMicroseconds(100);
  }
  pressureSensorSignal /= averages;
  if (logResults) {
    Serial.print("CAPPER>" + String(pressureSensorSignal));
    Serial.print("\n");
  }
  return pressureSensorSignal;
}

float CapperDecapper::readCurrentSensorDCMotor(byte averages=8, bool logResults=true, bool logAll=false) {
  float val = 0.0;
  float current_mA = 0.0;
  float shuntVoltage_mV = 0.0;
  float loadVoltage_V = 0.0;
  float busVoltage_V = 0.0;
  float power_mW = 0.0; 
  bool ina219_overflow = false;
  
  this->currentSensorDCMotor.startSingleMeasurement();  // Discard first measurement
  delayMicroseconds(100);
  
  for (int i = 0; i < averages; i++) {  // Average a few readings to reduce noise
    this->currentSensorDCMotor.startSingleMeasurement();
    val += this->currentSensorDCMotor.getCurrent_mA();

    if (logResults && logAll) {
      shuntVoltage_mV += this->currentSensorDCMotor.getShuntVoltage_mV();
      busVoltage_V += this->currentSensorDCMotor.getBusVoltage_V();
      power_mW += this->currentSensorDCMotor.getBusPower();
      loadVoltage_V += busVoltage_V + (shuntVoltage_mV/1000);
      ina219_overflow &= this->currentSensorDCMotor.getOverflow();
    }
    
    delayMicroseconds(100);
  }
  
  val /= averages;
  shuntVoltage_mV /= averages;
  busVoltage_V /= averages;
  power_mW /= averages;
  loadVoltage_V /= averages;

  if (logResults && !logAll) {
    Serial.print("CAPPER>" + String(val));
    Serial.print("\n");
  } else if (logResults && logAll) {
    Serial.print("CAPPER>Current[mA]: " + String(val));
    Serial.print("\n");
    Serial.print("CAPPER>Shunt Voltage [mV]: " + String(shuntVoltage_mV));
    Serial.print("\n");
    Serial.print("CAPPER>Bus Voltage [V]: " + String(busVoltage_V));
    Serial.print("\n");
    Serial.print("CAPPER>Load Voltage [V]: " + String(loadVoltage_V));
    Serial.print("\n");
    Serial.print("CAPPER>Bus Power [mW]: " + String(power_mW));
    Serial.print("\n");
    if(!ina219_overflow){
      Serial.print("CAPPER>No overflow: OK");
    } else {
      Serial.print("CAPPER>Overflow: Lower Gain");
    }
    Serial.print("\n");
  }
  return val;
}

float CapperDecapper::readCurrentSensorServoMotor(byte averages=8, bool logResults=true, bool logAll=false) {
  float val = 0.0;
  float current_mA = 0.0;
  float shuntVoltage_mV = 0.0;
  float loadVoltage_V = 0.0;
  float busVoltage_V = 0.0;
  float power_mW = 0.0; 
  bool ina219_overflow = false;
  
  this->currentSensorServoMotor.startSingleMeasurement();  // Discard first measurement
  delayMicroseconds(100);
  
  for (int i = 0; i < averages; i++) {  // Average a few readings to reduce noise
    this->currentSensorServoMotor.startSingleMeasurement();
    val += this->currentSensorServoMotor.getCurrent_mA();

    if (logResults && logAll) {
      shuntVoltage_mV += this->currentSensorServoMotor.getShuntVoltage_mV();
      busVoltage_V += this->currentSensorServoMotor.getBusVoltage_V();
      power_mW += this->currentSensorServoMotor.getBusPower();
      loadVoltage_V += busVoltage_V + (shuntVoltage_mV/1000);
      ina219_overflow &= this->currentSensorServoMotor.getOverflow();
    }
    
    delayMicroseconds(100);
  }
  
  val /= averages;
  shuntVoltage_mV /= averages;
  busVoltage_V /= averages;
  power_mW /= averages;
  loadVoltage_V /= averages;

  if (logResults && !logAll) {
    Serial.print("CAPPER>" + String(val));
    Serial.print("\n");
  } else if (logResults && logAll) {
    Serial.print("CAPPER>Current[mA]: " + String(val));
    Serial.print("\n");
    Serial.print("CAPPER>Shunt Voltage [mV]: " + String(shuntVoltage_mV));
    Serial.print("\n");
    Serial.print("CAPPER>Bus Voltage [V]: " + String(busVoltage_V));
    Serial.print("\n");
    Serial.print("CAPPER>Load Voltage [V]: " + String(loadVoltage_V));
    Serial.print("\n");
    Serial.print("CAPPER>Bus Power [mW]: " + String(power_mW));
    Serial.print("\n");
    if(!ina219_overflow){
      Serial.print("CAPPER>No overflow: OK");
    } else {
      Serial.print("CAPPER>Overflow: Lower Gain");
    }
    Serial.print("\n");
  }
  return val;
}

void CapperDecapper::logSensorSignals(unsigned long timeout=5000, bool logResults=true) {
  float pressureSensorSignal=0.0;
  float currentSensorDCMotorSignal=0.0;
  float currentSensorServoMotorSignal=0.0;
  unsigned long startTime = millis();
  
  while (!isTimedOut(startTime, timeout)) {
    pressureSensorSignal=this->readPressureSensor(64, false);
    currentSensorDCMotorSignal=this->readCurrentSensorDCMotor(2, false, false);
    currentSensorServoMotorSignal=this->readCurrentSensorServoMotor(2, false, false);
    
    if (logResults) {
      Serial.print("CAPPER>");
      Serial.print("\t");
      Serial.print(pressureSensorSignal);
      Serial.print("\t");
      Serial.print(currentSensorDCMotorSignal);
      Serial.print("\t");
      Serial.print(currentSensorServoMotorSignal);
      Serial.print("\n");
    }
  }
  this->sensorSignals[0] = pressureSensorSignal;
  this->sensorSignals[1] = currentSensorDCMotorSignal;
  this->sensorSignals[2] = currentSensorServoMotorSignal;
}

bool CapperDecapper::initializeCurrentSensor(INA219_WE *currentSensor) {
  if(!(currentSensor->init())){
    errors = 1;
    return false;
  }
  currentSensor->setADCMode(SAMPLE_MODE_4); // Set ADC Mode for Bus and ShuntVoltage (BIT_MODE_12 is default (available: 9, 10, 11, 12), SAMPLE_MODE_32 means averaging 32 samples which takes 17.02 ms (available: 2, 4, 8, 16, 32, 64, 128))
  currentSensor->setMeasureMode(TRIGGERED); // Set measure mode (available: POWER_DOWN, TRIGGERED, ADC_OFF, CONTINUOUS)
  currentSensor->setPGain(PG_160); // Gain setting (available: PG_40 (40mV, 0.4A), PG_80 (80mV, 0.8A), PG_160 (160mV, 1.6A), PG_320 (320mV, 3.2A))
  currentSensor->setBusRange(BRNG_32); // Set Bus Voltage Range (available: BRNG_16 -> 16 V, BRNG_32 -> 32 V (DEFAULT))
  // currentSensor->setCorrectionFactor(0.98); // insert correction factor if necessary
  // currentSensor->setShuntVoltOffset_mV(0.5); // insert shunt voltage (millivolts) detected at zero current if necessary
  return true;
}
