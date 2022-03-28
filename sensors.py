
import gc
gc.enable()

import machine, time
import network
import urequests
from machine import Pin
import ads1115
gc.collect()


class HCSR04:
    """
    Driver to use the untrasonic sensor HC-SR04.
    The sensor range is between 2cm and 4m.
    The timeouts received listening to echo pin are converted to OSError('Out of range')
    """
    # echo_timeout_us is based in chip range limit (400cm)
    def __init__(self, trigger_pin, echo_pin, echo_timeout_us=500*2*30):
        """
        trigger_pin: Output pin to send pulses
        echo_pin: Readonly pin to measure the distance. The pin should be protected with 1k resistor
        echo_timeout_us: Timeout in microseconds to listen to echo pin.
        By default is based in sensor limit range (4m)
        """
        self.echo_timeout_us = echo_timeout_us
        # Init trigger pin (out)
        self.trigger = Pin(trigger_pin, mode=Pin.OUT, pull=None)
        self.trigger.value(0)

        # Init echo pin (in)
        self.echo = Pin(echo_pin, mode=Pin.IN, pull=None)

    def _send_pulse_and_wait(self):
        """
        Send the pulse to trigger and listen on echo pin.
        We use the method `machine.time_pulse_us()` to get the microseconds until the echo is received.
        """
        self.trigger.value(0) # Stabilize the sensor
        time.sleep_us(5)
        self.trigger.value(1)
        # Send a 10us pulse.
        time.sleep_us(10)
        self.trigger.value(0)
        try:
            pulse_time = machine.time_pulse_us(self.echo, 1, self.echo_timeout_us)
            return pulse_time
        except OSError as ex:
            if ex.args[0] == 110: # 110 = ETIMEDOUT
                raise OSError('Out of range')
            raise ex

    def distance_mm(self):
        """
        Get the distance in milimeters without floating point operations.
        """
        pulse_time = self._send_pulse_and_wait()

        # To calculate the distance we get the pulse_time and divide it by 2
        # (the pulse walk the distance twice) and by 29.1 becasue
        # the sound speed on air (343.2 m/s), that It's equivalent to
        # 0.34320 mm/us that is 1mm each 2.91us
        # pulse_time // 2 // 2.91 -> pulse_time // 5.82 -> pulse_time * 100 // 582
        mm = pulse_time * 100 // 582
        return mm

    def distance_cm(self):
        """
        Get the distance in centimeters with floating point operations.
        It returns a float
        """
        pulse_time = self._send_pulse_and_wait()

        # To calculate the distance we get the pulse_time and divide it by 2
        # (the pulse walk the distance twice) and by 29.1 becasue
        # the sound speed on air (343.2 m/s), that It's equivalent to
        # 0.034320 cm/us that is 1cm each 29.1us
        cms = (pulse_time / 2) / 29.1
        return cms


class AnalogReader:
  def __init__(self, sda_pin, scl_pin, addr_1, addr_2, layout):
    self.i2c = machine.I2C(1, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=400000)
    self.adc_1 = ads1115.ADS1115(self.i2c, address=addr_1)
    self.adc_2 = ads1115.ADS1115(self.i2c, address=addr_2)
    self.layout = layout

  def read_sensor_values(self, order):
    buckets = [0, 20, 40, 80, 160, 220]
    light = []
    voltage = []
    other = []

    def read_light_sensor(adc, channel):
      try:
        raw = (adc.read(4, channel) - 335) / 30483
        return max([n for n, p in zip(buckets, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]) if raw >= p] + [0])
      except OSError:
        return -1.0

    def read_voltage_sensor(adc, channel):
      try:
        raw = (adc.read(4, channel) - 5169) / 27067
        return max([n for n, p in zip(buckets, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]) if raw >= p] + [0])
      except OSError:
        return -1.0

    def read_other_sensor(adc, channel):
      try: return adc.read(4, channel)
      except OSError: return -1.0

    for i, c in enumerate(self.layout[:4]):
      if c == "l": light.append(read_light_sensor(self.adc_1, i))
      elif c == "v": voltage.append(read_voltage_sensor(self.adc_1, i))
      else: other.append(read_other_sensor(self.adc_1, i))

    for i, c in enumerate(self.layout[4:]):
      if c == "l": light.append(read_light_sensor(self.adc_2, i))
      elif c == "v": voltage.append(read_voltage_sensor(self.adc_2, i))
      else: other.append(read_other_sensor(self.adc_2, i))

    data = []
    for o in order:
      if o == "l": data.append(light.pop(0) if light else 0.0)
      elif o == "v": data.append(voltage.pop(0) if voltage else 0.0)
      else: data.append(other.pop(0) if other else 0.0)

    return data


def start():
  def print_f(msg):
    with open("log.txt", "a") as file:
      file.write(msg.strip() + "\n")

  # print_f("===========================\nline 138: Start")
  # process config
  bot_id = -1
  wifi_name = ""
  wifi_pswd = ""
  aws_endpoint = ""
  dist_sensors = {}
  i2c_pins = {}
  adcs = []

  # print_f("line 148: processing config")
  with open("config.txt") as config_file:
    for line in config_file.read().splitlines():
      args = line.split()
      if not args:
        continue
      if args[0] == "id":
        bot_id = int(args[1])
      elif args[0] == "wifi":
        wifi_name = " ".join(args[1:])
      elif args[0] == "w_pwd":
        wifi_pswd = " ".join(args[1:])
      elif args[0] == "aws_endp":
        aws_endpoint = args[1]
      elif args[0] in ["scl", "sda"]:
        i2c_pins[args[0]] = int(args[1])
      elif args[0][0] == "d":
        dist_sensors[args[0]] = [int(n) for n in args[1:]]
      elif args[0].startswith("adc"):
        adcs.append((args[1], int(args[2], 16)))
  gc.collect()
  # print_f("line 169: config processed")


  # set up wifi
  # print_f("line 173: connecting to wifi")
  wlan = network.WLAN(network.STA_IF)
  gc.collect()
  # print_f("line 175: started wlan")
  wlan.active(True)
  gc.collect()
  # print_f("line 177: set wlan to active")
  wlan.connect(wifi_name, wifi_pswd)
  # print_f("line 179: connected to network")

  while not wlan.isconnected():
    machine.idle()

  # print_f("Line 180: pre-loop")
  try:
    ads = AnalogReader(i2c_pins["sda"], i2c_pins["scl"], adcs[0][1], adcs[1][1], adcs[0][0] + adcs[1][0])
    distance_sensors = [HCSR04(t, e) for t, e in dist_sensors.values()]
    ctr = 0
    # print_f("Line 185: sensors instantiated")
    while True:
      gc.collect()
      data = [bot_id] + [ds.distance_mm() for ds in distance_sensors[:2]]\
           + ads.read_sensor_values("vvll_")
      data_str = str(data).replace(" ", "")
      gc.collect()
      try:
        response = None
        if wlan.isconnected():
          response = urequests.post(aws_endpoint+"?data="+data_str, timeout=50)
        print(ctr, ": Posted:", data_str)
        # print_f("line 197: posted data")
        ctr += 1
        body = response.json()
        print("Response:", body)
        # print_f("Response: " + str(body))
        if body["endLoop"]:
          print("Server issued Kill Signal. Stopping!")
          break
      except (IndexError, KeyError, OSError) as e:
        print("An error was produced: ", e)
        # print_f("Error produced!")
        if not wlan.isconnected():
          print("The WiFi disconnected. Reconnecting...")
          wlan.active(True)
          wlan.connect(wifi_name, wifi_pswd)
          while not wlan.isconnected():
            machine.idle()
      time.sleep(0.1)
  except KeyboardInterrupt:
    if wlan and wlan.isconnected():
      wlan.disconnect()
      wlan.active(False)

