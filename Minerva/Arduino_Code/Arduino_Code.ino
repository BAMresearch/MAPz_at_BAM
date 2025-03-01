/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include "SwitchingValve.h"
#include "SwitchingValveDCMotor.h"
#include "CapperDecapper.h"
#include "HotplateClampDCMotor.h"
#include "HotplateFan.h"
#include "DHT22Sensor.h"
#include "Electromagnet.h"
#include "HelperFunctions.h"
#include "SoftReset.h"

/**********************************
 * General Variables              *
 **********************************/
byte errors = 0;  // 0: ok; 1: Hall sensor error; 2: Magnet polarity error; 3: Timeout error
bool emergencyStopRequest = false;

/**********************************
 * Setup for Valves               *
 **********************************/
const byte microsteppingFactorValve1 = 2;
const int stepsPerRevolutionValve1 = 200;
const byte sleepPinValve1 = 42;
const byte stepPinValve1 = 43;
const byte dirPinValve1 = 44;
const int hallSensorPinValve1 = A2;
const byte reversedPolarityPosValve1 = 3;
const byte portsValve1 = 6;
const byte clockwiseNumberingValve1 = true;
const byte enableIsHighValve1 = true;
SwitchingValve valve1;

const byte microsteppingFactorValve2 = 4;
const int stepsPerRevolutionValve2 = 200;
const byte sleepPinValve2 = 51;
const byte stepPinValve2 = 49;
const byte dirPinValve2 = 50;
const int hallSensorPinValve2 = A7;
const byte reversedPolarityPosValve2 = 5;
const byte portsValve2 = 10;
const byte clockwiseNumberingValve2 = false;
const byte enableIsHighValve2 = false;
SwitchingValve valve2;

/**********************************
 * Setup for Hotplate Clamps      *
 **********************************/
const byte dcMotorPin1HotplateClamp1 = 22;
const byte dcMotorPin2HotplateClamp1 = 23;
const byte servoPinHotplateClamp1 = 2;
const byte currentSensorPinHotplateClamp1 = A4;
const byte switchPinHotplateClamp1Down = 30;
const byte switchPinHotplateClamp1Up = 31;
const int servoHotplateClamp1ClosedPos = 164;
const int servoHotplateClamp1OpenedPos = 85;
HotplateClampDCMotor hotplateClamp1;

const byte dcMotorPin1HotplateClamp2 = 24;
const byte dcMotorPin2HotplateClamp2 = 25;
const byte servoPinHotplateClamp2 = 4;
const byte currentSensorPinHotplateClamp2 = A5;
const byte switchPinHotplateClamp2Down = 32;
const byte switchPinHotplateClamp2Up = 33;
const int servoHotplateClamp2ClosedPos = 164;
const int servoHotplateClamp2OpenedPos = 85;
HotplateClampDCMotor hotplateClamp2;

const byte dcMotorPin1HotplateClamp3 = 26;
const byte dcMotorPin2HotplateClamp3 = 27;
const byte servoPinHotplateClamp3 = 5;
const byte currentSensorPinHotplateClamp3 = A6;
const byte switchPinHotplateClamp3Down = 34;
const byte switchPinHotplateClamp3Up = 35;
const int servoHotplateClamp3ClosedPos = 164;
const int servoHotplateClamp3OpenedPos = 85;
HotplateClampDCMotor hotplateClamp3;

/**********************************
 * Setup for Hotplate Fans        *
 **********************************/
const byte enablePinHotplateFan1 = 52;
HotplateFan hotplateFan1;

const byte enablePinHotplateFan2 = 53;
HotplateFan hotplateFan2;

const byte enablePinHotplateFan3 = 6;
HotplateFan hotplateFan3;

const byte enablePinHotplateFan4 = 7;
HotplateFan hotplateFan4;

/**********************************
 * Setup for DHT22 Sensors        *
 **********************************/
const byte dhtSensorPin1 = 8;
DHT22Sensor dhtSensor1;

/**********************************
 * Setup for Electromagnet        *
 **********************************/
const byte electromagnet1Pin1 = 38;
const byte electromagnet1Pin2 = 39;
Electromagnet electromagnet1;

/**********************************
 * Setup for Capper/Decapper      *
 **********************************/
const byte I2C_SDA_Pin = 20;
const byte I2C_SCL_Pin = 21;
const int servoClosedPosDegrees=30; //21
const int servoOpenedPosDegrees=150;  // 155
const int servoClosedPosMillimeters = 4;
const int servoOpenedPosMillimeters = 59;

const byte dcMotorPin1 = 45;
const byte dcMotorPin2 = 46;
const byte servoPinCapper = 3;
const int pressureSensorPin = A1;
const int currentSensorDCMotorAddress=0x40;
const int currentSensorServoMotorAddress=0x41;
CapperDecapper capper;

/**********************************
 * Command Handlers               *
 **********************************/
void handleValveCommand(String command) {
  byte attempts;
  byte valveNumber = (byte)command.substring(0, 1).toInt();
  SwitchingValve *valve;
  
  if (valveNumber == 1) {
    valve = &valve1;
  } else if (valveNumber == 2) {
    valve = &valve2;
  } else {
    Serial.println("VALVE" + String(valveNumber) + ">UNKNOWN VALVE NUMBER: " + command.substring(0, 1));
    return;
  }
  command = command.substring(1);
  
  if (valveNumber == 1 || valveNumber == 2) {
    if (command.startsWith("pos")) {
      if (command.length() == 3) {
        Serial.println("VALVE" + String(valveNumber) + ">POS " + String(valve->currentPos));
      } else {
        if (command.substring(3).toInt() == valve->currentPos) {
          Serial.println("VALVE" + String(valveNumber) + ">OK");
        }
        else if (valve->gotoPosition(command.substring(3).toInt())) {
          Serial.println("VALVE" + String(valveNumber) + ">OK");
        } else {
          Serial.println("VALVE" + String(valveNumber) + ">ERROR " + String(valve->errors) + ": " + getErrorMessage(valve->errors));
        }
      }
    } else if (command == "ini") {
      attempts = 0;
      while (!valve->initializeValve() && attempts < 3) {
        attempts ++;
      }
      if (attempts<3) {
        Serial.println("VALVE" + String(valveNumber) + ">OK");
      } else {
        Serial.println("VALVE" + String(valveNumber) + ">ERROR " + String(valve->errors) + ": " + getErrorMessage(valve->errors));
      }
    } else if (command == "par") {
      Serial.println("VALVE" + String(valveNumber) + ">Hall Sensor Idle Value:\t" + String(valve->hallSensorIdleSignal) + "\tHall Sensor Threshold Value:\t" + String(valve->hallSensorThreshold));
    } else {
      Serial.println("VALVE" + String(valveNumber) + ">UNK: " + command);
    }
  }
}

void handleMagnetCommand(String command) {
  byte magnetNumber = (byte)command.substring(0, 1).toInt();
  Electromagnet *magnet;
  
  if (magnetNumber == 1) {
    magnet = &electromagnet1;
  } else {
    Serial.println("MAGNET" + String(magnetNumber) + ">UNKNOWN ELECTROMAGNET NUMBER: " + String(magnetNumber));
    return;
  }

  if (command.substring(1) == "on") {
    magnet->magnetOn(false);
    Serial.println("MAGNET" + String(magnetNumber) + ">OK");
  } else if (command.substring(1) == "off") {
    magnet->magnetOff();
    Serial.println("MAGNET" + String(magnetNumber) + ">OK");
  } else if (command.substring(1) == "rev") {
    magnet->magnetOn(true);
    Serial.println("MAGNET" + String(magnetNumber) + ">OK");
  } else if (command.substring(1) == "rel") {
    magnet->magnetOn(true);
    delay(100);
    magnet->magnetOff();
    Serial.println("MAGNET" + String(magnetNumber) + ">OK");
  } else {
    Serial.println("MAGNET" + String(magnetNumber) + ">UNK: " + command);
  }
}

void handleHotplateClampCommand(String command) {
  byte clampNumber = (byte)command.substring(0, 1).toInt();
  HotplateClampDCMotor *clamp;
  
  if (clampNumber == 1) {
    clamp = &hotplateClamp1;
  } else if (clampNumber == 2) {
    clamp = &hotplateClamp2;
  } else if (clampNumber == 3) {
    clamp = &hotplateClamp3;
  } else {
    Serial.println("CLAMP" + String(clampNumber) + ">UNKNOWN HOTPLATE CLAMP NUMBER: " + String(clampNumber));
    return;
  }
  command = command.substring(1);

  if (command == "close") {
    clamp->closeClamp();
    Serial.println("CLAMP" + String(clampNumber) + ">OK");
  } else if (command == "open") {
    clamp->openClamp();
    Serial.println("CLAMP" + String(clampNumber) + ">OK");
  } else if (command.startsWith("close")) {
    clamp->closeClamp(command.substring(5).toInt());
    Serial.println("CLAMP" + String(clampNumber) + ">OK");
  } else if (command.startsWith("open")) {
    clamp->openClamp(command.substring(4).toInt());
    Serial.println("CLAMP" + String(clampNumber) + ">OK");
  } else if (command == "up") {
    if (clamp->goUp()) {
      Serial.println("CLAMP" + String(clampNumber) + ">OK");
    } else {
      Serial.println("CLAMP" + String(clampNumber) + ">ERROR " + String(clamp->errors) + ": " + getErrorMessage(clamp->errors));
    }
  } else if (command == "down") {
    if (clamp->goDown()) {
      Serial.println("CLAMP" + String(clampNumber) + ">OK");
    } else {
      Serial.println("CLAMP" + String(clampNumber) + ">ERROR " + String(clamp->errors) + ": " + getErrorMessage(clamp->errors));
    }
  } else if (command.startsWith("up")) {
    if (clamp->goUp(command.substring(2).toInt())) {
      Serial.println("CLAMP" + String(clampNumber) + ">OK");
    } else {
      Serial.println("CLAMP" + String(clampNumber) + ">ERROR " + String(clamp->errors) + ": " + getErrorMessage(clamp->errors));
    }
  } else if (command.startsWith("down")) {
    if (clamp->goDown(command.substring(4).toInt())) {
      Serial.println("CLAMP" + String(clampNumber) + ">OK");
    } else {
      Serial.println("CLAMP" + String(clampNumber) + ">ERROR " + String(clamp->errors) + ": " + getErrorMessage(clamp->errors));
    }
  } else if (command == "stop") {
    if (clamp->stopStage()) {
      Serial.println("CLAMP" + String(clampNumber) + ">OK");
    } else {
      Serial.println("CLAMP" + String(clampNumber) + ">ERROR " + String(clamp->errors) + ": " + getErrorMessage(clamp->errors));
    }
  } else if (command == "motor_current") {
    Serial.print("CLAMP" + String(clampNumber) + ">" + String(clamp->getCurrentSensorData()) + "\n");
    Serial.println("CLAMP" + String(clampNumber) + ">OK");
  } else {
    Serial.println("CLAMP" + String(clampNumber) + ">UNK: " + command);
  }
}

void handleHotplateFanCommand(String command) {
  byte fanNumber = (byte)command.substring(0, 1).toInt();
  HotplateFan *fan;
  
  if (fanNumber == 1) {
    fan = &hotplateFan1;
  } else if (fanNumber == 2) {
    fan = &hotplateFan2;
  } else if (fanNumber == 3) {
    fan = &hotplateFan3;
  } else if (fanNumber == 4) {
    fan = &hotplateFan4;
  } else {
    Serial.println("FAN" + String(fanNumber) + ">UNKNOWN HOTPLATE FAN NUMBER: " + String(fanNumber));
    return;
  }
  command = command.substring(1);

  if (command == "on") {
    fan->turnOn();
    Serial.println("FAN" + String(fanNumber) + ">OK");
  } else if (command == "off") {
    fan->turnOff();
    Serial.println("FAN" + String(fanNumber) + ">OK");
  } else {
    Serial.println("FAN" + String(fanNumber) + ">UNK: " + command);
  }
}

void handleDHTCommand(String command) {
  byte sensorNumber = (byte)command.substring(0, 1).toInt();
  DHT22Sensor *sensor;
  float * res;
  
  if (sensorNumber == 1) {
    sensor = &dhtSensor1;
  } else {
    Serial.println("DHT22SENSOR" + String(sensorNumber) + ">UNKNOWN DHT22 SENSOR NUMBER: " + String(sensorNumber));
    return;
  }
  command = command.substring(1);

  if (command == "measure") {
    res = sensor->measure();
    if (res != NULL) {
      Serial.println("DHT22SENSOR" + String(sensorNumber) + ">" + String(* res) + "\n" + String(* res + sizeof(float)) + "\nOK");
    } else {
      Serial.println("DHT22SENSOR" + String(sensorNumber) + ">ERROR " + String(sensor->errors) + ": " + getErrorMessage(sensor->errors));
    }
  } else {
    Serial.println("DHT22SENSOR" + String(sensorNumber) + ">UNK: " + command);
  }
}

void handleCapperDecapperCommand(String command) {
  if (command=="clamp_get_position") {
    Serial.print("CAPPER>" + String(capper.currentPos) + "\n");
    Serial.println("CAPPER>OK");
  } else if (command.startsWith("clamp_set_position")) {
    capper.setClampPosition(command.substring(18).toInt());
    Serial.println("CAPPER>OK");
  } else if (command == "pressure") {
    capper.readPressureSensor();
    Serial.println("CAPPER>OK");
  } else if (command == "motor_current") {
    capper.readCurrentSensorDCMotor(4, true, false);
    Serial.println("CAPPER>OK");
  } else if (command == "motor_currentall") {
    capper.readCurrentSensorDCMotor(4, true, true);
    Serial.println("CAPPER>OK");
  } else if (command == "servo_current") {
    capper.readCurrentSensorServoMotor(4, true, false);
    Serial.println("CAPPER>OK");
  } else if (command == "servo_currentall") {
    capper.readCurrentSensorServoMotor(4, true, true);
    Serial.println("CAPPER>OK");
  } else if (command.startsWith("log")) {
    if (command.length()==3) {
      capper.logSensorSignals();
    } else {
      capper.logSensorSignals(command.substring(3).toInt(), true);
    }
    Serial.println("CAPPER>OK");
  } else if (command.startsWith("open")) {
    command = command.substring(4);
    char buf[command.length()+1];
    command.toCharArray(buf, command.length());
    char* part = strtok(buf, ";");
    int i = 0;
    int pos = 0;
    int p = 0;
    long timeout = 0;
    while (part != 0) {
        if (i==0) {
          pos = atoi(buf);
        } else if (i==1) {
          p = atoi(buf);
        } else if (i==2) {
          timeout = atol(buf);
        }
        i++;
        part = strtok(0, ";");
    }
    if (capper.openContainer(pos, p, timeout)) {
      Serial.println("CAPPER>OK");
    } else {
      Serial.println(F("CAPPER>ERROR OPENING CONTAINER"));
    }
  } else if (command=="close") {
    command = command.substring(5);
    char buf[command.length()+1];
    command.toCharArray(buf, command.length());
    char* part = strtok(buf, ";");
    int i = 0;
    int p = 0;
    float current = 0.0;
    long timeout = 0;
    while (part != 0) {
        if (i==0) {
          p = atoi(buf);
        } else if (i==1) {
          current = atof(buf);
        } else if (i==2) {
          timeout = atol(buf);
        }
        i++;
        part = strtok(0, ";");
    }
    if (capper.closeContainer(p, current, timeout)) {
      Serial.println("CAPPER>OK");
    } else {
      Serial.println(F("CAPPER>ERROR CLOSING CONTAINER"));
    }
  } else if (command=="turn_cw") {
    capper.turnWristClockwise();
    Serial.println("CAPPER>OK");
  } else if (command=="turn_ccw") {
    capper.turnWristCounterClockwise();
    Serial.println("CAPPER>OK");
  } else if (command=="turn_stop") {
    capper.stopWristRotation();
    Serial.println("CAPPER>OK");
  } else if (command.startsWith("clamp_open")) {
    if (command.length()==10) {
      capper.openClamp();
    } else {
      capper.openClamp(command.substring(10).toFloat());
    }
    Serial.println("CAPPER>OK");
  } else if (command.startsWith("clamp_close")) {
    if (command.length()==11) {
      capper.closeClamp();
    } else {
      capper.closeClamp(command.substring(11).toFloat());
    }
    Serial.println("CAPPER>OK");
  } else {
    Serial.println("CAPPER>UNK: " + command);
  }
}

/**********************************
 * Setup                          *
 **********************************/
void setup() {
  // initialize the serial port:
  Serial.begin(9600);
  
  // Initialize connected Hardware
  capper = CapperDecapper(dcMotorPin1, dcMotorPin2, servoPinCapper, pressureSensorPin, currentSensorDCMotorAddress, currentSensorServoMotorAddress, servoClosedPosDegrees, servoOpenedPosDegrees, servoClosedPosMillimeters, servoOpenedPosMillimeters);
  valve1 = SwitchingValve(dirPinValve1, stepPinValve1, sleepPinValve1, hallSensorPinValve1, microsteppingFactorValve1, stepsPerRevolutionValve1, reversedPolarityPosValve1, portsValve1, clockwiseNumberingValve1, enableIsHighValve1);
  valve2 = SwitchingValve(dirPinValve2, stepPinValve2, sleepPinValve2, hallSensorPinValve2, microsteppingFactorValve2, stepsPerRevolutionValve2, reversedPolarityPosValve2, portsValve2, clockwiseNumberingValve2, enableIsHighValve2);
  hotplateClamp1 = HotplateClampDCMotor(dcMotorPin1HotplateClamp1, dcMotorPin2HotplateClamp1, servoPinHotplateClamp1, currentSensorPinHotplateClamp1, switchPinHotplateClamp1Up, switchPinHotplateClamp1Down , servoHotplateClamp1ClosedPos, servoHotplateClamp1OpenedPos);
  hotplateClamp2 = HotplateClampDCMotor(dcMotorPin1HotplateClamp2, dcMotorPin2HotplateClamp2, servoPinHotplateClamp2, currentSensorPinHotplateClamp2, switchPinHotplateClamp2Up, switchPinHotplateClamp2Down , servoHotplateClamp2ClosedPos, servoHotplateClamp2OpenedPos);
  hotplateClamp3 = HotplateClampDCMotor(dcMotorPin1HotplateClamp3, dcMotorPin2HotplateClamp3, servoPinHotplateClamp3, currentSensorPinHotplateClamp3, switchPinHotplateClamp3Up, switchPinHotplateClamp3Down , servoHotplateClamp3ClosedPos, servoHotplateClamp3OpenedPos);
  hotplateFan1 = HotplateFan(enablePinHotplateFan1);
  hotplateFan2 = HotplateFan(enablePinHotplateFan2);
  hotplateFan3 = HotplateFan(enablePinHotplateFan3);
  hotplateFan4 = HotplateFan(enablePinHotplateFan4);
  dhtSensor1 = DHT22Sensor(dhtSensorPin1);
  electromagnet1 = Electromagnet(electromagnet1Pin1, electromagnet1Pin2);
}

/**********************************
 * Main Loop                      *
 **********************************/
void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil(10);
    command.replace("\r", "");
    command.replace("\n", "");
    command.replace(" ", "");
    command.toLowerCase();
    if (command == "esr") {
      emergencyStopRequest = true;      
      Serial.println("Emergency Stop Request: OK");
      soft_restart();  //reset arduino
    } else if (command == "ces") {
      emergencyStopRequest = false;
      Serial.println("Clear Emergency Stop: OK");
    } else if ((!emergencyStopRequest) && (command.startsWith("help"))) {
      displayHelp();
    } else if ((!emergencyStopRequest) && (command.startsWith("valve"))) {
      handleValveCommand(command.substring(5));
    } else if ((!emergencyStopRequest) && (command.startsWith("magnet"))) {
      handleMagnetCommand(command.substring(6));
    } else if ((!emergencyStopRequest) && (command.startsWith("clamp"))) {
      handleHotplateClampCommand(command.substring(5));
    } else if ((!emergencyStopRequest) && (command.startsWith("fan"))) {
      handleHotplateFanCommand(command.substring(3));
    } else if ((!emergencyStopRequest) && (command.startsWith("dht22sensor"))) {
      handleDHTCommand(command.substring(11));
    } else if ((!emergencyStopRequest) && (command.startsWith("capper"))) {
      handleCapperDecapperCommand(command.substring(6));
    } else if (emergencyStopRequest) {
      Serial.println(F("EMERGENCY STOP ACTIVE - NEEDS TO BE CLEARED BEFORE PROCESSING NEW COMMANDS"));
    } else {
      Serial.println("Unknown Command: " + command);
    }
  }
  delay(20);
}
