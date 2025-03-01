/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#include "Arduino.h"
#include "HelperFunctions.h"

int mod(int x, int y){
  return x<0 ? ((x+1)%y)+y-1 : x%y;  // modulo function for negative numbers (mod(-1,4)=3, whereas in Arduino (-1%4)=-1)
}

bool isTimedOut(unsigned long startTime, int timeout) {
  return ((unsigned long)(millis() - startTime) > timeout);  // subtract and cast to unsigned long to avoid overflow problem
}

String getErrorMessage(byte errors) {
  if (errors == 0) {
    return "";
  } else if (errors == 1) {
    return "SENSOR ERROR";
  } else if (errors == 2) {
    return "MAGNET POLARITY ERROR";
  } else if (errors == 3) {
    return "TIMEOUT ERROR";
  }
}

void displayHelp() {
  Serial.println(F(
    "Available Commands:\n"
    "All commands are case-insensitive and single spaces are removed. Commands are teminated with a line feed (CHR 10).\n"
    "Parts written in square brackets are [optional], parts written in angle brackets denote a <datatype>.\n\n"
    "******************************************\n"
    "*            General Commands            *\n"
    "******************************************\n"
    "esr                                         Request Emergency Stop\n"
    "ces                                         Clear Emergency Stop Request\n"
    "help                                        Display this help text\n\n"
    "******************************************\n"
    "*             Valve Commands             *\n"
    "******************************************\n"
    "valve<int number> pos                       Query current position of the valve with the number <number>\n"
    "valve<int number> pos <int pos>             Rotate the valve to position <pos> (between 0 and 5)\n"
    "valve<int number> ini                       Re-initialize the valve\n"
    "valve<int number> par                       Display the parameters (threshold and offset) of the hall sensor\n\n"
    "******************************************\n"
    "*         Electromagnet Commands         *\n"
    "******************************************\n"
    "magnet<int number> on                       Turn the magnet with the number <number> on\n"
    "magnet<int number> off                      Turn the magnet with the number <number> off\n"
    "magnet<int number> rev                      Reverse the polarity of the magnet with the number <number>\n"
    "magnet<int number> rel                      Release the stirbar from the magnet with the number <number> (briefly reverses polarity and turns the magnet off)\n\n"
    "******************************************\n"
    "*        Hotplate Clamp Commands         *\n"
    "******************************************\n"
    "clamp<int number> up [int threshold]        Moves clamp with the number <number> up either until the threshold in mA is reached (if provided) or until the limit switch is triggered.\n"
    "clamp<int number> down [int threshold]      Moves clamp with the number <number> down either until the threshold in mA is reached (if provided) or until the limit switch is triggered.\n"
    "clamp<int number> stop                      Stops movement of the clamp with the number <number>\n"
    "clamp<int number> motor_current             Returns the DC Motor current for clamp number <number>\n"
    "clamp<int number> open [int angle] [int d]  Open the clamp (up to a servo angle of [angle], or all the way if not specified), slowing down for the first d degrees\n"
    "clamp<int number> close [int angle] [int d] Close the clamp (up to a servo angle of [angle], or all the way if not specified), slowing down for the last d degrees\n\n"
    "******************************************\n"
    "*         Hotplate Fan Commands          *\n"
    "******************************************\n"
    "fan<int number> on                          Turns the fan with the number <number> on.\n"
    "fan<int number> off                         Turns the fan with the number <number> off.\n\n"
    "******************************************\n"
    "*       Capper/Decapper Commands         *\n"
    "******************************************\n"
    "capper clamp_get_position                   Query current clamp bracket opening in millimeters\n"
    "capper clamp_set_position <int width>       Set the clamp bracket opening to the specified <width> in millimeters \n"
    "capper pressure                             Query value of pressure sensor\n"
    "capper motor_current [all]                  Query dc motor current in mA (or all values provided by the sensor if [all] is specified)\n"
    "capper servo_current [all]                  Query servo motor current in mA (or all values provided by the sensor if [all] is specified)\n"
    "capper log <int timeout>                    Logs pressure, motor current, and servo current for the specified time (in milliseconds)\n"
    "capper open <int pos> <int p> [int to]      Opens a container: Wait until the pressure threshold <p> or timeout [to] is reached, close the gripper to position <pos>, rotate wrist until 'jumping' occurs or timeout [to] is reached\n"
    "capper close <int p> <float i> [int to]     Closes a container: Wait until pressure threshold <p> or timeout [to] is reached, rotate wrist until current threshold <i> in mA or timeout [to] is reached, open gripper\n"
    "capper turn_cw                              Rotates the wrist of the capper clockwise\n"
    "capper turn_ccw                             Rotates the wrist of the capper counter-clockwise\n"
    "capper turn_stop                            Stops wrist rotation\n"
    "capper clamp_open [float threshold]         Open the clamp (until the current threshold [threshold] in mA or the open position is reached)\n"
    "capper clamp_close [float threshold]        Close the clamp (until the current threshold [threshold] in mA or the closed position is reached)\n\n"
    "******************************************\n"
    "*            DHT22 Commands              *\n"
    "******************************************\n"
    "dht22sensor<int number> measure             Performs a measurement with the sensor number <number> and returns the temperature (in centrigrades) and humidity (in percent) readings.\n\n"
    "******************************************\n"
    "*              Error Codes               *\n"
    "******************************************\n"
    "0                                           No error\n"
    "1                                           Sensor error\n"
    "2                                           Magnet polarity error\n"
    "3                                           Timeout error\n"
  ));
}
