/*
@author:      "Bastian Ruehle"
@copyright:   "Copyright 2025, Bastian Ruehle, Federal Institute for Materials Research and Testing (BAM)"
@version:     "1.0.0"
@maintainer:  "Bastian Ruehle"
@email        "bastian.ruehle@bam.de"
*/

#ifndef Electromagnet_h
#define Electromagnet_h
#include "HelperFunctions.h"
class Electromagnet {
public:
  Electromagnet(void);
  Electromagnet(byte electromagnetPin1, byte electromagnetPin2);
  void magnetOn(bool reversedPolarity=false);
  void magnetOff(void);
  byte errors;
private:
  byte electromagnetPin1;
  byte electromagnetPin2;
};
#endif
