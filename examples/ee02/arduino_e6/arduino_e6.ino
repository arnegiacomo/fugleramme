#include <FS.h>
using fs::FS;

#include <CRC32.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <WiFiManager.h>
#include <WiFiClientSecure.h>
//#include <qrcode_espi.h>
#include "PanelConvert.h"
#include "driver.h"
#include <TFT_eSPI.h>


#define LOW_BATTERY_BOOT 3.0
#define LOW_BATTERY_WIFI 3.4
#define LOW_BATTERY_WARNING 3.5

#define LOW_BATTERY_SLEEP_MINUTES ((uint8_t))60
#define MIN_SLEEP_MINUTES ((uint8_t)1)

#define uS_TO_S_FACTOR 1000000ULL /* Conversion factor for micro seconds to seconds */

Preferences prefs;
bool paramsChanged = false;

String frameHost = "";
String framePort = "";
bool useSSL = false;

EPaper epaper;

#define BATTERY_ADC A0
#define ADC_EN 6
#define VOLTAGE_DIVIDER_RATIO 2.0

struct __attribute__((__packed__)) Header {
    char     magic[4];  // 4s: 4-character string/bytes
    uint16_t version;   // H : 16-bit unsigned integer
    uint8_t  encoding;  // B : 8-bit unsigned integer
    uint8_t  poll;      // B : 8-bit unsigned integer
    uint16_t width;     // H : 16-bit unsigned integer
    uint16_t height;    // H : 16-bit unsigned integer
    uint32_t length;    // I : 32-bit unsigned integer
    uint32_t crc;       // I : 32-bit unsigned integer
};

void displayError(String message, bool persistent = false) {
  Serial.println(message);
}

uint8_t getFrame(String oldEtag = "") {
  HTTPClient http;

  const char* headerKeys[] = {"Etag"};
  size_t headerKeysCount = sizeof(headerKeys) / sizeof(headerKeys[0]);
  http.collectHeaders(headerKeys, headerKeysCount);

  String URL = frameHost + ":" + framePort + "/frame.e6";

  if(useSSL) {
    WiFiClientSecure *client = new WiFiClientSecure;
    client->setInsecure();
    http.begin(*client, "https://" + URL);
  } else {
    http.begin("http://" + URL);
  }

  if(oldEtag != "") {
    http.addHeader("If-None-Match",oldEtag);
  }

  int httpResponseCode = http.GET();

  switch(httpResponseCode) {
    case 304:
      // No change to display
      Serial.println("No change to frame.");
      http.end();
      return 0;
      break;
    case 404:
      displayError("The frame is not configured to serve external panels. Please enable \"External e-ink panel\" at on the admin page's \"Frame\" tab.",true);
      http.end();
      return 0;
      break;
    case 503:
      displayError("The frame has not drawn a page yet.");
      http.end();
      return 0;
      break;
    case 200:
      // Go on to display
      break;
    default:
      displayError("The frame answered with HTTP code " + httpResponseCode);
      http.end();
      return 0;
      break;
  }

  String Etag = http.header("Etag");

  NetworkClient& sock = http.getStream();
  Header header;
  char magic[] = {'E','6','F','1'};

  if (sock.readBytes((uint8_t*)&header, sizeof(Header))) {
    if(memcmp(header.magic, magic, 4) == 0 && header.version == 1 && header.encoding == 1) {
      Serial.print("Valid page received, length ");
      Serial.println(header.length);
      if(header.width == 1200 && header.height == 1600 && header.width * header.height / 2 == header.length) {
        Serial.println("Page is the correct size");
        uint8_t* pixels = (uint8_t*)ps_malloc(header.length);
        sock.readBytes(pixels, header.length);

        if(CRC32::calculate(pixels, header.length) != header.crc) {
          Serial.println("Checksum error!");
        } else {
          Serial.println("We got a frame!");
          prefs.putString("Etag",Etag);
          convertBuffer(pixels,header.length,header.width);
          Serial.println("Attempting to write:");
          epaper.pushImage(0, 0, header.width, header.height, (uint16_t *)pixels);
          epaper.update();
          epaper.sleep();
        }
        free(pixels);
      } else {
        Serial.println("Wrong page size.");
      }
    } else {
      Serial.println("Magic doesn't match.");
    }
  }
  sock.stop();
  http.end();

  return header.poll;
}
/*
void displaySetupInfo(WiFiManager *wifi) {
  EPaper epaper;
  QRcode_eSPI qrcode (&epaper);
  epaper.begin();
  qrcode.init();
  qrcode.create("WIFI:S:" + wifi->getConfigPortalSSID() + ";T:nopass;;");
  epaper.update();
  epaper.sleep();
}
*/

void handle_wakeup() {
  esp_sleep_wakeup_cause_t wakeup_reason;

  wakeup_reason = esp_sleep_get_wakeup_cause();

  switch (wakeup_reason) {
    case ESP_SLEEP_WAKEUP_EXT0:     Serial.println("Wakeup caused by external signal using RTC_IO"); break;
    case ESP_SLEEP_WAKEUP_EXT1:     Serial.println("Wakeup caused by external signal using RTC_CNTL"); break;
    case ESP_SLEEP_WAKEUP_TIMER:    Serial.println("Wakeup caused by timer"); break;
    case ESP_SLEEP_WAKEUP_TOUCHPAD: Serial.println("Wakeup caused by touchpad"); break;
    case ESP_SLEEP_WAKEUP_ULP:      Serial.println("Wakeup caused by ULP program"); break;
    default:                        Serial.printf("Wakeup was not caused by deep sleep: %d\n", wakeup_reason); break;
  }
}

void saveParams() {
  paramsChanged = true;
}

#include "soc/io_mux_reg.h"

void printAllPullupsS3() {
  Serial.println("--- ESP32-S3 GPIO Pull-Up Status Dump ---");
  
  // The ESP32-S3 has 49 GPIO pins (0 through 48)
  for (int gpio = 0; gpio <= 48; gpio++) {
    
    // Explicitly skip non-existent registers to avoid CPU panic/hangs
    // GPIO 22-25 do not exist as physical pins or registers on the S3
    if (gpio >= 22 && gpio <= 25) {
      continue;
    }
    
    // Calculate the IO MUX register address for this specific pin
    uint32_t reg_addr = IO_MUX_GPIO0_REG + (gpio * 4);
    
    // Read the current hardware configuration for the pad
    uint32_t reg_val = REG_READ(reg_addr);
    
    // Extract pull-up and pull-down configurations
    bool pullup_enabled = (reg_val & FUN_PU);
    bool pulldown_enabled = (reg_val & FUN_PD);
    
    Serial.print("GPIO ");
    if (gpio < 10) Serial.print(" "); // Formatting spacer
    Serial.print(gpio);
    Serial.print(": ");
    
    if (pullup_enabled) {
      Serial.println("[PULL-UP ENABLED]");
    } else if (pulldown_enabled) {
      Serial.println("(Pull-Down Enabled)");
    } else {
      Serial.println("Floating / High-Z");
    }
  }
  Serial.println("-----------------------------------------");
}

float readBatteryVoltage() {
    analogReadResolution(12);
    pinMode(BATTERY_ADC, INPUT);
    pinMode(ADC_EN, OUTPUT);
    digitalWrite(ADC_EN, HIGH);

    uint32_t sum = 0;
    for(int i = 0; i < 16; i++) {
        sum += analogReadMilliVolts(BATTERY_ADC);
        delay(1);
    }
    return sum * VOLTAGE_DIVIDER_RATIO / 16 / 1000.0;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("13.3\" Bird frame");
  
  handle_wakeup();

  epaper.begin();
  epaper.sleep();

  prefs.begin("BirdFrame");

  float battery = readBatteryVoltage();

  Serial.printf("Battery voltage is %.2f\n",battery);

  WiFiManager wm;
  //wm.resetSettings();
  
  WiFiManagerParameter fuglerammeHost("frameHost", "Fugleramme Host", frameHost.c_str(), 128);
  WiFiManagerParameter fuglerammePort("framePort", "Fugleramme Port", framePort.c_str(), 5);
  
  //wm.setAPCallback(displaySetupInfo);
  wm.setSaveParamsCallback(saveParams);
  wm.addParameter(&fuglerammeHost);
  wm.addParameter(&fuglerammePort);

  if(!wm.autoConnect()) {
    delay(3000);
    ESP.restart();
    delay(5000);
  }

  if(paramsChanged) {
    frameHost = fuglerammeHost.getValue();
    framePort = fuglerammePort.getValue();

    prefs.putString("frameHost", frameHost);
    prefs.putString("framePort", framePort);
    prefs.putBool("useSSL", useSSL);
  } else {
    frameHost = prefs.getString("frameHost", "fugleramme.local");
    framePort = prefs.getString("framePort", "8080");
    useSSL = prefs.getBool("useSSL", false);
  }

  framePort = "443";
  useSSL = true;

  String Etag = prefs.getString("Etag","");
  Serial.println("Loaded frame host " + frameHost + ":" + framePort);

  uint8_t sleep = getFrame(Etag);
  
  //printAllPullupsS3();
  // Any need to disable pullups or isolate RTC GPIOs before sleep?

  //esp_sleep_enable_timer_wakeup(max(sleep,MIN_SLEEP_MINUTES) * 60 * uS_TO_S_FACTOR);
  //esp_deep_sleep_start();
}

void loop() {
// Zzzzzzzzzzz
}
