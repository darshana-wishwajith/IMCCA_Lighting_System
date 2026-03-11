#include <FastLED.h>

// LED Configuration
#define LED_PIN     6
#define COLOR_ORDER GRB
#define CHIPSET     WS2812B
#define NUM_LEDS    120

#define DEFAULT_FADE_SPEED    10
#define DEFAULT_SPARKLE_SPEED 30

CRGB leds[NUM_LEDS];

// ── Mode enum ─────────────────────────────────────────────────────────────────
enum Mode {
  // ── Original combat modes ─────────────────────────────────────────────────
  NEON, INTRO, HEALTH, IDLE, COMBO,
  FATALITY, BRUTALITY,
  ROUND_START, ROUND_WIN, ROUND_LOSE,
  CRITICAL,
  LIGHT_HIT, MEDIUM_HIT, HEAVY_HIT, CRITICAL_HIT,
  PLAYER_COMBO, FATALITY_READY,

  // ── Screen-state modes ────────────────────────────────────────────────────
  // LOADING       : violet comet sweeping the strip
  // LOBBY         : cyan slow breathing  +  LOBBY_INPUT brown flash interrupt
  // CHAR_SELECT   : amber/gold chasing dots
  // PRE_CINEMATIC : magenta beam bouncing end-to-end
  // DIALOG_LINE   : teal flash interrupting PRE_CINEMATIC
  // PRE_SEQUENCE  : audio-reactive white/green alternating pattern  ← NEW
  // LOBBY_INPUT   : quick brown flash returning to LOBBY            ← NEW
  // END_MATCH     : ice-blue twinkle field
  LOADING,
  LOBBY,
  CHAR_SELECT,
  PRE_CINEMATIC,
  DIALOG_LINE,
  PRE_SEQUENCE,
  LOBBY_INPUT,
  END_MATCH
};

Mode currentMode  = NEON;
Mode previousMode = NEON;

// ── Global state ──────────────────────────────────────────────────────────────
int           currentHealth      = 100;
bool          inMatch            = false;
int           animationStep      = 0;
unsigned long animationStartTime = 0;
unsigned long lastAnimationTime  = 0;
int           brightness         = 250;
float         speedMultiplier    = 1.0;
int           comboHits          = 0;

int  comboFlashCount    = 0;
bool comboFlashOn       = false;
int  fatalityPulseCount = 0;
bool fatalityDimPhase   = false;

// ── Audio level (0-100) received from Python during PRE_SEQUENCE ──────────────
int  audioLevel     = 50;    // latest value sent by Python
int  prevAudioLevel = 50;    // previous value for beat detection

// ── High-frequency intensity (0-255) for sparkle overlay ──────────────────────
int  highFreqLevel  = 0;     // latest value from Python FFT

void setup() {
  Serial.begin(9600);
  FastLED.addLeds<CHIPSET, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS)
         .setCorrection(TypicalLEDStrip);
  FastLED.setBrightness(brightness);
  currentMode = NEON;
  Serial.println("ARDUINO_READY");
}

// ─────────────────────────────────────────────────────────────────────────────

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    processCommand(command);
  }

  switch (currentMode) {
    case NEON:          animateNeon();          break;
    case INTRO:         animateIntro();         break;
    case HEALTH:        animateHealth();        break;
    case IDLE:          animateIdle();          break;
    case COMBO:         animateCombo();         break;
    case FATALITY:      animateFatality();      break;
    case BRUTALITY:     animateBrutality();     break;
    case ROUND_START:   animateRoundStart();    break;
    case ROUND_WIN:     animateRoundWin();      break;
    case ROUND_LOSE:    animateRoundLose();     break;
    case CRITICAL:      animateCritical();      break;
    case LIGHT_HIT:     animateLightHit();      break;
    case MEDIUM_HIT:    animateMediumHit();     break;
    case HEAVY_HIT:     animateHeavyHit();      break;
    case CRITICAL_HIT:  animateCriticalHit();   break;
    case PLAYER_COMBO:  animatePlayerCombo();   break;
    case FATALITY_READY:animateFatalityReady(); break;
    case LOADING:       animateLoading();       break;
    case LOBBY:         animateLobby();         break;
    case CHAR_SELECT:   animateCharSelect();    break;
    case PRE_CINEMATIC: animatePreCinematic();  break;
    case DIALOG_LINE:   animateDialogLine();    break;
    case PRE_SEQUENCE:  animatePreSequence();   break;
    case LOBBY_INPUT:   animateLobbyInput();    break;
    case END_MATCH:     animateEndMatch();      break;
  }

  // ── High-Frequency Sparkle Overlay ─────────────────────────────────────────
  // This reacts to high-pitched sounds (cymbals, impacts) by adding random
  // brilliant white sparkles over the current animation.
  if (highFreqLevel > 20) {
    // 1. DUCKING: Dim the current background to make the audio pop
    uint8_t duckAmount = map(highFreqLevel, 0, 255, 255, 160); // Dim to ~60% at peak
    for(int i = 0; i < NUM_LEDS; i++) {
      leds[i].nscale8(duckAmount);
    }

    // 2. SPARKLES: Brilliant white punctures - Top Priority
    int numSparkles = map(highFreqLevel, 0, 255, 0, NUM_LEDS / 4);
    for (int i = 0; i < numSparkles; i++) {
        int pos = random16(NUM_LEDS);
        // Pure White Overwrite (not additive) to ensure visibility
        leds[pos] = CRGB::White;
        
        // "Fat" Sparkle: extra adjacent pixels for very high intensity
        if (highFreqLevel > 160) {
            if (pos > 0)          leds[pos-1] |= CRGB(180, 180, 180);
            if (pos < NUM_LEDS-1) leds[pos+1] |= CRGB(180, 180, 180);
        }
    }
  }

  FastLED.show();
  delay(int(30 / speedMultiplier));
}

// ─────────────────────────────────────────────────────────────────────────────
// Command parser
// ─────────────────────────────────────────────────────────────────────────────

void processCommand(String command) {

  // ── Original commands ──────────────────────────────────────────────────────
  if (command.startsWith("HEALTH:")) {
    currentHealth = command.substring(7).toInt();
    currentMode   = HEALTH;
    inMatch       = true;
  }
  else if (command.startsWith("COMBO:")) {
    comboHits       = command.substring(6).toInt();
    comboFlashCount = 0;
    comboFlashOn    = true;
    previousMode    = currentMode;
    currentMode     = COMBO;
  }
  else if (command == "GAME_START") {
    currentMode        = INTRO;
    animationStep      = 0;
    animationStartTime = millis();
    inMatch            = false;
  }
  else if (command == "MATCH_END" || command == "GAME_END") {
    currentMode = IDLE;
    inMatch     = false;
  }
  else if (command == "NO_GAME") {
    currentMode = NEON;
    inMatch     = false;
  }
  else if (command == "FATALITY") {
    fatalityPulseCount = 0;
    fatalityDimPhase   = false;
    previousMode       = currentMode;
    currentMode        = FATALITY;
  }
  else if (command == "BRUTALITY") {
    previousMode       = currentMode;
    currentMode        = BRUTALITY;
    animationStep      = 0;
    animationStartTime = millis();
  }
  else if (command == "ROUND_START") {
    previousMode       = currentMode;
    currentMode        = ROUND_START;
    animationStep      = 0;
    animationStartTime = millis();
  }
  else if (command == "ROUND_WIN") {
    previousMode       = currentMode;
    currentMode        = ROUND_WIN;
    animationStep      = 0;
    animationStartTime = millis();
  }
  else if (command == "ROUND_LOSE") {
    previousMode       = currentMode;
    currentMode        = ROUND_LOSE;
    animationStep      = 0;
    animationStartTime = millis();
  }
  else if (command == "CRITICAL") {
    previousMode       = currentMode;
    currentMode        = CRITICAL;
    animationStartTime = millis();
  }
  else if (command == "LIGHT_HIT") {
    previousMode       = currentMode;
    currentMode        = LIGHT_HIT;
    animationStartTime = millis();
  }
  else if (command == "MEDIUM_HIT") {
    previousMode       = currentMode;
    currentMode        = MEDIUM_HIT;
    animationStartTime = millis();
  }
  else if (command == "HEAVY_HIT") {
    previousMode       = currentMode;
    currentMode        = HEAVY_HIT;
    animationStartTime = millis();
  }
  else if (command == "CRITICAL_HIT") {
    previousMode       = currentMode;
    currentMode        = CRITICAL_HIT;
    animationStartTime = millis();
  }
  else if (command.startsWith("PLAYER_COMBO:")) {
    comboHits          = command.substring(13).toInt();
    previousMode       = currentMode;
    currentMode        = PLAYER_COMBO;
    animationStartTime = millis();
  }
  else if (command == "FATALITY_READY") {
    previousMode       = currentMode;
    currentMode        = FATALITY_READY;
    animationStartTime = millis();
  }
  else if (command.startsWith("BRIGHTNESS:")) {
    brightness = constrain(command.substring(11).toInt(), 0, 255);
    FastLED.setBrightness(brightness);
  }
  else if (command.startsWith("SPEED:")) {
    speedMultiplier = constrain(command.substring(6).toInt() / 100.0, 0.1, 3.0);
  }

  // ── Screen-state commands ──────────────────────────────────────────────────
  else if (command == "LOADING") {
    currentMode = LOADING;
    inMatch     = false;
  }
  else if (command == "LOBBY") {
    currentMode = LOBBY;
    inMatch     = false;
  }
  else if (command == "CHAR_SELECT") {
    currentMode   = CHAR_SELECT;
    animationStep = 0;
  }
  else if (command == "PRE_CINEMATIC") {
    previousMode       = currentMode;
    currentMode        = PRE_CINEMATIC;
    animationStartTime = millis();
  }
  else if (command == "END_MATCH") {
    previousMode       = currentMode;
    currentMode        = END_MATCH;
    animationStartTime = millis();
  }
  else if (command == "DIALOG_LINE") {
    previousMode       = PRE_CINEMATIC;
    currentMode        = DIALOG_LINE;
    animationStep      = 0;
    animationStartTime = millis();
  }

  // ── PRE_SEQUENCE: enter mode ───────────────────────────────────────────────
  else if (command == "PRE_SEQUENCE") {
    previousMode       = currentMode;
    currentMode        = PRE_SEQUENCE;
    animationStartTime = millis();
    audioLevel         = 50;   // reset to neutral on entry
  }

  // ── AUDIO_LEVEL: streamed from Python during PRE_SEQUENCE ─────────────────
  // Python sends this at ~20 Hz while PRE_SEQUENCE is active.
  // The animation uses it directly – no mode change needed.
  else if (command.startsWith("AUDIO_LEVEL:")) {
    prevAudioLevel = audioLevel;
    audioLevel     = constrain(command.substring(12).toInt(), 0, 100);
  }

  // ── HIGH_FREQ: high-frequency intensity for sparkle overlay ───────────────
  else if (command.startsWith("HIGH_FREQ:")) {
    highFreqLevel = constrain(command.substring(10).toInt(), 0, 255);
  }

  // ── LOBBY_INPUT: player pressed a key/button in the lobby ─────────────────
  else if (command == "LOBBY_INPUT") {
    previousMode       = LOBBY;           // always return to lobby after flash
    currentMode        = LOBBY_INPUT;
    animationStep      = 0;
    animationStartTime = millis();
  }
}

// =============================================================================
// ORIGINAL ANIMATIONS  (unchanged)
// =============================================================================

void animateNeon() {
  static uint8_t hue = 0;
  fill_rainbow(leds, NUM_LEDS, hue, 7);
  hue++;
}

void animateIntro() {
  static uint8_t step = 0;
  static int b = 0;
  static unsigned long lastUpdate = 0;
  if (millis() - lastUpdate > (50 / speedMultiplier)) {
    lastUpdate = millis();
    switch (step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::Orange); b+=10; if(b>=255){b=255;step=1;} FastLED.setBrightness(b); break;
      case 1: fill_solid(leds,NUM_LEDS,CRGB::Yellow); b=255; FastLED.setBrightness(b); step=2; break;
      case 2: fill_solid(leds,NUM_LEDS,CRGB::White); step=3; break;
      case 3: b-=10; if(b<=brightness){b=brightness;step=0;currentMode=HEALTH;} FastLED.setBrightness(b); break;
    }
  }
}

void animateHealth() {
  int n = int((currentHealth / 100.0) * NUM_LEDS);
  FastLED.setBrightness(brightness);
  for (int i = 0; i < NUM_LEDS; i++) {
    if (i < n) {
      if      (currentHealth > 80) leds[i] = CHSV(85, 255, beatsin8(30,200,255));
      else if (currentHealth > 60) leds[i] = CHSV(60, 255, 255);
      else if (currentHealth > 40) leds[i] = CHSV(30, 255, 255);
      else if (currentHealth > 20) leds[i] = CHSV(15, 255, beatsin8(20,150,255));
      else                         leds[i] = CHSV(0,  255, 255);
    } else { leds[i] = CRGB::Black; }
  }
}

void animateIdle() { fill_solid(leds,NUM_LEDS,CRGB::Blue); FastLED.setBrightness(brightness); }

void animateCombo() {
  static unsigned long lastFlash = 0;
  if (millis()-lastFlash > (100/speedMultiplier)) {
    lastFlash = millis();
    if (comboFlashOn) { fill_solid(leds,NUM_LEDS,CRGB::White); FastLED.setBrightness(255); }
    else              { FastLED.setBrightness(brightness/2); comboFlashCount++; }
    comboFlashOn = !comboFlashOn;
    if (comboFlashCount >= min(comboHits+1,5)) { currentMode=previousMode; comboFlashCount=0; }
  }
}

void animateFatality() {
  static unsigned long lastPulse = 0;
  if (millis()-lastPulse > (200/speedMultiplier)) {
    lastPulse = millis();
    if (!fatalityDimPhase) {
      fill_solid(leds,NUM_LEDS,CRGB::Red); FastLED.setBrightness(255);
      if (++fatalityPulseCount >= 3) fatalityDimPhase = true;
    } else {
      static uint8_t fb = 255; fb -= 20; FastLED.setBrightness(fb);
      if (fb <= 50) { fb=255; currentMode=IDLE; fatalityPulseCount=0; fatalityDimPhase=false; }
    }
  }
}

void animateBrutality() {
  static uint8_t step = 0;
  static unsigned long lastUpdate = 0;
  if (millis()-lastUpdate > (80/speedMultiplier)) {
    lastUpdate = millis();
    switch(step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::Orange); FastLED.setBrightness(255); step=1; break;
      case 1: fill_solid(leds,NUM_LEDS,CRGB::Yellow); step=2; break;
      case 2: fill_solid(leds,NUM_LEDS,CRGB::White);  step=3; break;
      case 3: fill_solid(leds,NUM_LEDS,CRGB::Yellow); step=4; break;
      case 4: fill_solid(leds,NUM_LEDS,CRGB::Orange); step=5; break;
      case 5: { static int fade=255; fade-=25; if(fade<0)fade=0; FastLED.setBrightness((uint8_t)fade);
                if(fade<=brightness){fade=255;step=0;currentMode=IDLE;} } break;
    }
  }
}

void animateRoundStart() {
  static uint8_t step = 0;
  static unsigned long lastUpdate = 0;
  if (millis()-lastUpdate > (100/speedMultiplier)) {
    lastUpdate = millis();
    switch(step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::White); FastLED.setBrightness(255); step=1; break;
      case 1: fill_solid(leds,NUM_LEDS,CRGB::Black); step=2; break;
      case 2: fill_solid(leds,NUM_LEDS,CRGB::White); step=3; break;
      case 3: FastLED.setBrightness(brightness); step=0; currentMode=HEALTH; break;
    }
  }
}

void animateRoundWin() {
  static uint8_t pulseCount = 0;
  static unsigned long lastPulse = 0;
  if (millis()-lastPulse > (300/speedMultiplier)) {
    lastPulse = millis();
    if (pulseCount < 6) {
      if (pulseCount%2==0) { fill_solid(leds,NUM_LEDS,CRGB::Green); FastLED.setBrightness(255); }
      else                 { fill_solid(leds,NUM_LEDS,CRGB::Black); }
      pulseCount++;
    } else { pulseCount=0; currentMode=IDLE; }
  }
}

void animateRoundLose() {
  static unsigned long lastDim = 0;
  static int dimValue = 255;
  if (millis()-lastDim > (50/speedMultiplier)) {
    lastDim = millis();
    fill_solid(leds,NUM_LEDS,CRGB::Red);
    dimValue -= 15; if(dimValue<30) dimValue=30;
    FastLED.setBrightness((uint8_t)dimValue);
    if (millis()-animationStartTime > 2000) { dimValue=255; currentMode=IDLE; }
  }
}

void animateCritical() {
  static unsigned long lastFlash = 0;
  static bool flashOn = true;
  if (millis()-lastFlash > (150/speedMultiplier)) {
    lastFlash = millis();
    if (flashOn) { fill_solid(leds,NUM_LEDS,CRGB::Red); FastLED.setBrightness(255); }
    else         { fill_solid(leds,NUM_LEDS,CRGB::Black); }
    flashOn = !flashOn;
    if (millis()-animationStartTime > 3000) currentMode = HEALTH;
  }
}

void animateLightHit() {
  static unsigned long lastUpdate = 0;
  static uint8_t step = 0;
  if (millis()-lastUpdate > (50/speedMultiplier)) {
    lastUpdate = millis();
    switch(step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::Yellow); FastLED.setBrightness(255); step=1; break;
      case 1: step=0; currentMode=previousMode; FastLED.setBrightness(brightness); break;
    }
  }
}

void animateMediumHit() {
  static unsigned long lastUpdate = 0;
  static uint8_t step = 0;
  if (millis()-lastUpdate > (80/speedMultiplier)) {
    lastUpdate = millis();
    switch(step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::Orange); FastLED.setBrightness(255); step=1; break;
      case 1: fill_solid(leds,NUM_LEDS,CRGB::Yellow); step=2; break;
      case 2: step=0; currentMode=previousMode; FastLED.setBrightness(brightness); break;
    }
  }
}

void animateHeavyHit() {
  static unsigned long lastUpdate = 0;
  static uint8_t step = 0;
  if (millis()-lastUpdate > (100/speedMultiplier)) {
    lastUpdate = millis();
    switch(step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::OrangeRed); FastLED.setBrightness(255); step=1; break;
      case 1: fill_solid(leds,NUM_LEDS,CRGB::Orange);    step=2; break;
      case 2: fill_solid(leds,NUM_LEDS,CRGB::Yellow);    step=3; break;
      case 3: step=0; currentMode=previousMode; FastLED.setBrightness(brightness); break;
    }
  }
}

void animateCriticalHit() {
  static unsigned long lastUpdate = 0;
  static uint8_t step = 0;
  if (millis()-lastUpdate > (60/speedMultiplier)) {
    lastUpdate = millis();
    switch(step) {
      case 0: fill_solid(leds,NUM_LEDS,CRGB::White);     FastLED.setBrightness(255); step=1; break;
      case 1: fill_solid(leds,NUM_LEDS,CRGB::OrangeRed); step=2; break;
      case 2: fill_solid(leds,NUM_LEDS,CRGB::Red);       step=3; break;
      case 3: fill_solid(leds,NUM_LEDS,CRGB::Orange);    step=4; break;
      case 4: step=0; currentMode=previousMode; FastLED.setBrightness(brightness); break;
    }
  }
}

void animatePlayerCombo() {
  static unsigned long lastUpdate = 0;
  static uint8_t hue = 0, flashCount = 0;
  if (millis()-lastUpdate > (80/speedMultiplier)) {
    lastUpdate = millis();
    fill_rainbow(leds,NUM_LEDS,hue,10); hue+=20;
    FastLED.setBrightness(255); flashCount++;
    if (flashCount >= min(max(comboHits,3)*2,20)) {
      flashCount=0; hue=0; currentMode=previousMode; FastLED.setBrightness(brightness);
    }
  }
}

void animateFatalityReady() {
  static unsigned long lastUpdate = 0;
  static uint8_t pv = 0;
  static bool inc = true;
  if (millis()-lastUpdate > (20/speedMultiplier)) {
    lastUpdate = millis();
    if (inc) { pv+=5; if(pv>=255){pv=255;inc=false;} }
    else     { pv-=5; if(pv<=50) {pv=50; inc=true;} }
    for (int i=0;i<NUM_LEDS;i++)
      leds[i] = (i%4<2) ? CRGB(255,pv/4,0) : CRGB(255,(pv*3)/4,0);
    FastLED.setBrightness(pv);
    if (millis()-animationStartTime > 10000) {
      pv=0; inc=true; currentMode=HEALTH; FastLED.setBrightness(brightness);
    }
  }
}

// =============================================================================
// SCREEN-STATE ANIMATIONS  (from previous version, unchanged)
// =============================================================================

void animateLoading() {
  static int pos = 0;
  static unsigned long lastUpdate = 0;
  if (millis()-lastUpdate > (uint32_t)(25/speedMultiplier)) {
    lastUpdate = millis();
    fadeToBlackBy(leds, NUM_LEDS, 40);
    leds[pos]                              = CHSV(192,255,255);
    leds[(pos+NUM_LEDS-1)%NUM_LEDS]       = CHSV(192,255,160);
    leds[(pos+NUM_LEDS-2)%NUM_LEDS]       = CHSV(192,255, 80);
    leds[(pos+NUM_LEDS-3)%NUM_LEDS]       = CHSV(192,255, 30);
    pos = (pos+1)%NUM_LEDS;
    FastLED.setBrightness(brightness);
  }
}

void animateLobby() {
  static unsigned long lastUpdate = 0;
  if (millis()-lastUpdate > (uint32_t)(20/speedMultiplier)) {
    lastUpdate = millis();
    fill_solid(leds, NUM_LEDS, CHSV(128, 255, beatsin8(10,45,220)));
    FastLED.setBrightness(brightness);
  }
}

void animateCharSelect() {
  static int pos = 0;
  static unsigned long lastUpdate = 0;
  const int NUM_DOTS = 6;
  if (millis()-lastUpdate > (uint32_t)(35/speedMultiplier)) {
    lastUpdate = millis();
    fill_solid(leds, NUM_LEDS, CHSV(42, 220, 55));
    for (int d=0; d<NUM_DOTS; d++) {
      int head = (pos+(NUM_LEDS/NUM_DOTS)*d)%NUM_LEDS;
      leds[head]                        = CHSV(42,255,255);
      leds[(head+NUM_LEDS-1)%NUM_LEDS] = CHSV(42,240,130);
    }
    pos = (pos+1)%NUM_LEDS;
    FastLED.setBrightness(brightness);
  }
}

void animatePreCinematic() {
  static int pos = 0;
  static int8_t dir = 1;
  static unsigned long lastUpdate = 0;
  if (millis()-lastUpdate > (uint32_t)(18/speedMultiplier)) {
    lastUpdate = millis();
    fadeToBlackBy(leds, NUM_LEDS, 45);
    for (int i=-4; i<=4; i++) {
      int p = pos+i;
      if (p<0 || p>=NUM_LEDS) continue;
      leds[p] = CHSV(213, 255, 255 - (uint8_t)(abs(i)*45));
    }
    pos += dir;
    if (pos>=NUM_LEDS-1) { pos=NUM_LEDS-1; dir=-1; }
    if (pos<=0)          { pos=0;           dir= 1; }
    FastLED.setBrightness(brightness);
  }
}

void animateDialogLine() {
  static unsigned long lastUpdate = 0;
  static uint8_t step = 0;
  if (millis()-lastUpdate > (uint32_t)(60/speedMultiplier)) {
    lastUpdate = millis();
    switch (step) {
      case 0: fill_solid(leds,NUM_LEDS,CHSV(144,180,255)); FastLED.setBrightness(255); step=1; break;
      case 1: fill_solid(leds,NUM_LEDS,CHSV(144,220,200)); step=2; break;
      case 2: fill_solid(leds,NUM_LEDS,CHSV(144,255,120)); FastLED.setBrightness(brightness); step=3; break;
      case 3: step=0; currentMode=previousMode; FastLED.setBrightness(brightness); break;
    }
  }
}

void animateEndMatch() {
  static unsigned long lastUpdate = 0;
  if (millis()-lastUpdate > (uint32_t)(55/speedMultiplier)) {
    lastUpdate = millis();
    fill_solid(leds, NUM_LEDS, CHSV(140, 160, 110));
    for (int i=0; i<4; i++) leds[random8(NUM_LEDS)] = CHSV(145, 70, 255);
    FastLED.setBrightness(brightness);
  }
}

// =============================================================================
// NEW ANIMATIONS
// =============================================================================

// ─────────────────────────────────────────────────────────────────────────────
// PRE_SEQUENCE – audio-reactive white / green pattern
// ─────────────────────────────────────────────────────────────────────────────
//
// Two interleaved zones: pure WHITE (odd LEDs) and pure GREEN (even LEDs).
// The overall brightness is driven directly by audioLevel (0-100 from Python).
// Beat response: when audio jumps by ≥25 from the previous reading, the zones
// briefly INVERT (white↔green) for two frames as a sharp visual punch,
// then immediately return to normal.  This makes drum hits, explosions, and
// voice-over impacts physically visible on the strip.
//
// Colour choices:
//   White  CRGB(255,255,255) – bright, neutral punch
//   Green  CHSV(96,255,V)    – a vivid lime-green, unused elsewhere
//
// Both colours are distinct from every other mode in the system.
// ─────────────────────────────────────────────────────────────────────────────
void animatePreSequence() {
  static unsigned long lastUpdate = 0;
  static bool beatInvert  = false;   // are we mid-inversion?
  static uint8_t invertFrames = 0;   // frames remaining in inversion

  if (millis() - lastUpdate > (uint32_t)(25 / speedMultiplier)) {
    lastUpdate = millis();

    // Map audioLevel (0-100) → brightness (55-255)
    // Even at silence the pattern remains faintly visible.
    uint8_t bright = (uint8_t)map(audioLevel, 0, 100, 55, 255);

    // Beat detection: sudden loud spike → trigger inversion
    int audioDelta = audioLevel - prevAudioLevel;
    if (audioDelta >= 25 && !beatInvert) {
      beatInvert    = true;
      invertFrames  = 3;   // invert for 3 animation frames (~75 ms)
    }

    if (beatInvert) {
      invertFrames--;
      if (invertFrames == 0) beatInvert = false;
    }

    // Paint alternating white / green  (inverted on beat)
    for (int i = 0; i < NUM_LEDS; i++) {
      bool isWhiteSlot = (i % 2 == 0);
      if (beatInvert) isWhiteSlot = !isWhiteSlot;   // swap on beat

      if (isWhiteSlot) {
        // Pure white – scale brightness
        uint8_t v = bright;
        leds[i] = CRGB(v, v, v);
      } else {
        // Vivid lime-green – hue 96, full saturation, scaled brightness
        leds[i] = CHSV(96, 255, bright);
      }
    }

    FastLED.setBrightness(brightness);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// LOBBY_INPUT – brown flash for every player input in the lobby
// ─────────────────────────────────────────────────────────────────────────────
//
// Brown is a dark, warm colour unlike any other mode in this system.
// CRGB(101, 67, 33)  ≈  HSV hue 22, high saturation, low-medium value.
//
// Animation: 3-step fade  bright brown → mid brown → return to LOBBY cyan.
// Short duration (≈180 ms) so it punches without disrupting the lobby feel.
// ─────────────────────────────────────────────────────────────────────────────
void animateLobbyInput() {
  static unsigned long lastUpdate = 0;
  static uint8_t step = 0;

  if (millis() - lastUpdate > (uint32_t)(60 / speedMultiplier)) {
    lastUpdate = millis();

    switch (step) {
      case 0:
        // Bright warm brown burst
        fill_solid(leds, NUM_LEDS, CRGB(160, 82, 25));
        FastLED.setBrightness(255);
        step = 1;
        break;

      case 1:
        // Darker brown mid-tone
        fill_solid(leds, NUM_LEDS, CRGB(101, 52, 14));
        FastLED.setBrightness(200);
        step = 2;
        break;

      case 2:
        // Done – return to LOBBY (cyan breathing)
        step        = 0;
        currentMode = previousMode;    // previousMode is always LOBBY
        FastLED.setBrightness(brightness);
        break;
    }
  }
}
