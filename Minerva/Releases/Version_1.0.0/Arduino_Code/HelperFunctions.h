/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef HelperFunctions_h
#define HelperFunctions_h
#include "Arduino.h" 
int mod(int x, int y);
bool isTimedOut(unsigned long startTime, int timeout);
String getErrorMessage(byte errors);
void displayHelp(void);
#endif
