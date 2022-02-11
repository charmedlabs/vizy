#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

# Copyright 2021 Charmed Labs LLC
#
# This file is part of Vizy Software. 
#
# This source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use this source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#
"""
This module is used with the Vizy Power Board, which is a printed circuit 
board that plugs into the Raspberry Pi I/O connector and is included
with the Vizy camera.  

More information 
about Vizy can be found [here](https://vizycam.com).
"""    
import smbus
import wiringpi as wp
import time
import datetime
import os
from functools import wraps

COMPAT_HW_VERSION = [3, 0]

TRIES = 4

ERROR_BUSY = 0x80

EXEC_OFFSET = 0xc0
EXEC_SEMAPHORE = 0xff
EXEC_RW = 0x80
EXEC_WRITE = 0x80
EXEC_NVCONFIG = 1
EXEC_AD = 2
EXEC_DA = 3
EXEC_RTC = 16
EXEC_RTC_CALIBRATE = 17

IO_MODE_INPUT = 0
"""Used with `VizyPowerBoard.io_set_mode()`."""
IO_MODE_OUTPUT = 0x80 
"""Used with `VizyPowerBoard.io_set_mode()`."""
IO_MODE_HIGH_CURRENT = IO_MODE_OUTPUT | 0x40
"""Used with `VizyPowerBoard.io_set_mode()`."""
IO_MODE_SERIAL = 0x100
"""Used with `VizyPowerBoard.io_set_mode()`."""
DIPSWITCH_1_BOOT_MODE = 0x00
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_2_BOOT_MODES = 0x01
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_3_BOOT_MODES = 0x02
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_4_BOOT_MODES = 0x03
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_5_BOOT_MODES = 0x04
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_6_BOOT_MODES = 0x05
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_7_BOOT_MODES = 0x06
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_8_BOOT_MODES = 0x07
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_EXT_BUTTON = 0x08
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_MUTE_BUZZER = 0x10
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_NO_BG_LED = 0x20
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_POWER_DEFAULT_OFF = 0x00
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_POWER_DEFAULT_ON = 0x40
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_POWER_SWITCH = 0x80
"""Used with `VizyPowerBoard.dip_switches()`."""
DIPSWITCH_POWER_PLUG = 0xc0
"""Used with `VizyPowerBoard.dip_switches()`."""

POWER_ON_SOURCE_ALARM = 0x01
"""Used with `VizyPowerBoard.power_on_source()`."""
POWER_ON_SOURCE_POWER_BUTTON = 0x02
"""Used with `VizyPowerBoard.power_on_source()`."""
POWER_ON_SOURCE_12V = 0x03
"""Used with `VizyPowerBoard.power_on_source()`."""
POWER_ON_SOURCE_5V = 0x04
"""Used with `VizyPowerBoard.power_on_source()`."""

CHANNEL_VIN = 4
"""Used with `VizyPowerBoard.measure()`."""
CHANNEL_5V = 5
"""Used with `VizyPowerBoard.measure()`."""


def get_cpu_temp():
    """
    Read CPU temperature using Raspberry Pi drivers 
    """
    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
        temp = f.readline()
    return float(temp)/1000        


def check(result=None):
    """
    Method decorator to handle things gracefully if no Vizy Power Board is present.  
    """
    def wrap_func(func):
        @wraps(func)
        def _wrap_func(self, *args, **kwargs):
            if not self.connected:
                return result
            for i in range(TRIES):
                try:
                    return func(self, *args, **kwargs)
                except:
                    time.sleep(0.001) 
            self.connected = False 
            return result
        return _wrap_func
    return wrap_func


class VizyPowerBoard:
    """
    This class may be
    instantiated by more than one process.  The vizy-power-monitor service
    instantiates this class and uses it to monitor and control things such 
    as power-off requests, CPU temperature, fan speed, etc.  
    User programs can also instantiate this class and
    use its methods simultaneously.
    """    
    def __init__(self, addr=0x14, bus=1, check_hwver=True):
        """
        Args:
          addr (integer, optional, default=0x14): I2C address of the board
          bus (integer, optional, default=1): the I2C bus number 

        """    
        # We need to lock here because it can affect other process' read operations.
        self.bus = smbus.SMBus(bus)
        self.addr = addr
        self.connected = True
        if check_hwver:
            hwv = self.hw_version()
            if hwv!=COMPAT_HW_VERSION:
                raise RuntimeError("The hardware version of your Vizy Power Board (" + str(hwv[0])+'.'+str(hwv[1]) + ") is incompatible with this software file (" + str(COMPAT_HW_VERSION[0])+'.'+str(COMPAT_HW_VERSION[1]) + ").")
        wp.wiringPiSetupPhys()

    @staticmethod
    def _bcd2decimal(bcd):
        tens = (bcd&0xf0)>>4
        ones = bcd&0x0f
        return tens*10 + ones

    @staticmethod
    def _decimal2bcd(dec):
        tens = int(dec/10)
        ones = dec%10
        return (tens<<4) | ones

    @staticmethod
    def _u_int8(i):
        i = round(i)
        if i>0xff:
            return 0xff
        if i<0:
            return 0
        return i

    @staticmethod
    def _int8(i):
        i = round(i)
        if i>0x7f:
            return 0x7f
        if i<-0x80:
            return 0x80
        if i<0:
            return 0x100+i
        return i

    @staticmethod
    def _uint16(i):
        i = round(i)
        if i>0xffff:
            return 0xffff
        if i<0:
            return 0
        return i

    def _status(self):
        return self.bus.read_i2c_block_data(self.addr, 0, 1)[0]

    def _status_exec(self):
        return self.bus.read_i2c_block_data(self.addr, EXEC_OFFSET, 1)[0]

    def _grab_semaphore(self):
        count = 0
        while self._status_exec()!=EXEC_SEMAPHORE:
            time.sleep(0.001)
            if count==1000: # Essentially time-out if we can't grab semaphore.
                # Force release semaphore.  This might be necessary because the process
                # exits before releasing the semaphore (it's interrupted, killed, it crashes, etc.)
                print("Force Vizy Power Board semaphore release")
                self._release_semaphore()
                count = 0
            count += 1

    def _release_semaphore(self):
        self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_SEMAPHORE])
        # Give other processes some time to grab semaphore.
        time.sleep(0.001)

    def _wait_until_not_busy(self):
        while self._status()&ERROR_BUSY:
            time.sleep(0.001)

    @check(COMPAT_HW_VERSION)
    def hw_version(self):
        """
        Returns the major and minor versions of the PCB as a 2-item list.
        """ 
        return self.bus.read_i2c_block_data(self.addr, 1, 2)

    @check([0, 0, 0])
    def fw_version(self):
        """
        Returns the major, minor and build versions of the firmware as 
        a 3-item list.
        """ 
        return self.bus.read_i2c_block_data(self.addr, 3, 3)

    @check('')
    def resource_url(self):
        """
        Returns the url of a JSON file that contains information about 
        resources, such as the location of the latest version of this code, 
        latest firmware, etc.
        """
        chars = self.bus.read_i2c_block_data(self.addr, 6, 32)
        s = ''
        for c in chars:
            if c==0: # read up to the null character
                break
            s += chr(c)
        return s

    @check([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    def uuid(self):
        """
        Returns a 16-byte unique ID that can be used an a unique
        ID for your Vizy camera.  This unique ID is stored on the Vizy Power
        Board and remains constant regardless of firmware upgrades, etc.
        """
        return self.bus.read_i2c_block_data(self.addr, 22, 16)

    @check()    
    def power_off_requested(self, req=None):
        """
        Returns `True` if Vizy's button is held down for more than 5 seconds
        indicating that the user wishes to initiate safe shutdown and power
        off.  Returns `False` otherwise.
        Alternatively, if `True` is passed as an argument, it will simulate a 
        power-down sequence as if Vizy were powered down by holding down 
        button. 

        This is used by the vizy-power-monitor service. 
        """
        if req is None:
            button = self.bus.read_i2c_block_data(self.addr, 38, 1)
            if button[0]==0x0f:
                return True
            else:
                return False
        # Initiate power down as if we pressed the button
        elif req:
            self.buzzer(250, 500)
            self.bus.write_i2c_block_data(self.addr, 38, [0x0f])

    @check()
    def power_off(self, t=5000):
        """
        Powers Vizy off. The `t` argument specifies how long 
        to wait before turning off (specified in milliseconds).  The 
        vizy-power-monitor service calls this upon shutdown.
        """
        self.bus.write_i2c_block_data(self.addr, 38, [0x1f, int(t/100)])

    @check(0)
    def boot_mode(self):
        """
        Returns the boot mode number that was selected upon power up with the power button.
        The mode numbers have the following mapping:
        * 0: default (selected by doing nothing) 
        * 1: red 
        * 2: orange
        * 3: yellow
        * 4: green
        * 5: blue (lighter blue, or cyan)
        * 6: indigo (darker blue)
        * 7: voilet (purple)

        See `VizyPowerBoard.dip_switches()` for more information about boot mode selection. 
        """
        return self.bus.read_i2c_block_data(self.addr, 38, 1)[0]

    @check()
    def power_on_alarm_date(self, datetime_=None):
        """
        If you wish to power off your Vizy and have it "wake up" at a
        specified time and date, call this method with the desired
        datetime object and initiate a shutdown. (e.g. `sudo shutdown now`).


        The code below tells Vizy to turn on on December 2, 2022, 1:18pm.

            import vizypowerboard as vpb
            from datetime import datetime
            v = vpb.VizyPowerBoard()
            d=datetime(year=2022, month=12, day=2, hour=13, minute=18, second=0)
            v.power_on_alarm_date(d)

        Args:
          datetime_ (datetime, optional, default=None): `datetime` object that
            specifies the date/time to "wake up" (turn on).

        Returns:
          Calling without a datetime object returns a `datetime` object 
          reflecting the active alarm time.  If there is no active alarm,
          `None` is returned.
           
        Notes:
          * Once setting the alarm date, Vizy will retain it even if Vizy loses
          power for extended periods of time.
          * If the alarm expires while Vizy is on, Vizy will emit a buzzer tone
          and remain on.
          * If the alarm expires while Vizy is off (but plugged into and
          receiving power), Vizy will turn on.
          * If the alarm expires while Vizy is unplugged from (or not receiving)
          power, Vizy will turn on as soon as it receives power.  
        """
        if datetime_ is None:
            t = self.bus.read_i2c_block_data(self.addr, 41, 6)
            if t[5]==0:
                return None
            return datetime.datetime(year=self._bcd2decimal(t[5])+2016, month=self._bcd2decimal(t[4]), day=self._bcd2decimal(t[3]), hour=self._bcd2decimal(t[2]), minute=self._bcd2decimal(t[1]), second=self._bcd2decimal(t[0]))
        t = [self._decimal2bcd(datetime_.second), self._decimal2bcd(datetime_.minute), self._decimal2bcd(datetime_.hour), self._decimal2bcd(datetime_.day), self._decimal2bcd(datetime_.month), self._decimal2bcd(datetime_.year-2016)]
        self.bus.write_i2c_block_data(self.addr, 41, t)
    

    @check()
    def power_on_alarm_seconds(self, seconds=None):
        """
        Allows you to specify a power on alarm in seconds in the future. 
        For example, if you wish for Vizy to turn back on in 5 minutes, you
        would call `power_on_alarm_seconds(300)` and then initiate a shutdown.
        See `VizyPowerBoard.power_on_alarm_date()` for more information about the power on 
        alarm.

        Args:
          seconds (integer, optional, default=None): Number of seconds in the
            future you wish Vizy to turn on in.

        Returns:
          Calling this method without arguments returns the number of seconds
          until the alarm expires.  If no alarm is pending, `None` is returned.
        """
        if seconds is None:
            pod = self.power_on_alarm_date()
            if pod is None:
                return None
            diff = pod - self.rtc()
            return diff.days*86400+diff.seconds 
        # Add seconds to current time and set power on alarm    
        self.power_on_alarm_date(self.rtc()+datetime.timedelta(seconds=seconds))

    @check(0)
    def power_on_source(self):
        """
        Returns the source of what turned on Vizy for the current power cycle.
        It is one of either:

        * POWER_ON_SOURCE_ALARM, indicates that Vizy was powered on
        by the power on alarm expiring.  See power_on_alarm_date() and
        power_on_alarm_seconds().
        * POWER_ON_SOURCE_POWER_BUTTON, indicates that Vizy was powered 
        on by someone pressing the button.
        * POWER_ON_SOURCE_12V = indicates that Vizy was powered on
        by power being applied to 12V power input.  This only applies if the
        dip switch power mode allows powering on by plugging in power via the
        12V power input.
        * POWER_ON_SOURCE_5V, indicates that Vizy was powered on by applying
        power to the Raspberry Pi's USB-C power input.
        """
        source = self.bus.read_i2c_block_data(self.addr, 40, 1)[0]
        return source

    @check(False)
    def button(self):
        """
        Returns `True` if the button is being pressed currently, `False` otherwise.
        """
        button = self.bus.read_i2c_block_data(self.addr, 47, 1)
        if button[0]&0x02:
            return True
        else:
            return False

    @check(False)
    def button_pressed(self):
        """
        Returns `True` if the button was pressed within the last 5 seconds,
        `False` otherwise.  This is useful if the polling is intermittant or
        slow, as button presses are not missed (as long as you check at least
        every 5 seconds!)
        """
        button = self.bus.read_i2c_block_data(self.addr, 47, 1)
        if button[0]&0x01:
            # Reset bit
            self.bus.write_i2c_block_data(self.addr, 47, [0])
            return True
        else:
            return False

    @check(False)
    def vcc12(self, state=None):
        """
        If `state` is `True`, the 12V output on Vizy's I/O connector (pin 2) will be enabled and output 12V.  If `state` is `False`, the 12V output
        will be disabled.  Calling without arguments returns its current state.
        """ 
        config = self.bus.read_i2c_block_data(self.addr, 48, 1)[0]
        if state is None:
            return True if config&0x01 else False
        if state:
            config |= 0x01
        else:
            config &= ~0x01

        self.bus.write_i2c_block_data(self.addr, 48, [config])

    @check(False)
    def vcc5(self, state=None):
        """
        If `state` is `True`, the 5V output on Vizy's I/O connector (pin 3) will
        be enabled and output 5V.  If `state` is `False`, the 5V output will be
        disabled.  Calling without arguments returns its current state.
        """ 
        config = self.bus.read_i2c_block_data(self.addr, 48, 1)[0]
        if state is None:
            return True if config&0x02 else False
        if state:
            config |= 0x02
        else:
            config &= ~0x02

        self.bus.write_i2c_block_data(self.addr, 48, [config])

    @check()
    def led(self, r=0, g=0, b=0, flashes=0, repeat=False, atten=255, on=100, off=100, pause=200):
        """
        Controls the RGB LED in one of several modes:

        * **Continuous**: just setting `r`, `g`, and `b` will set set the LED color
        and turn it on continuously.  `r`, `g`, and `b` values range between 0 
        and  255.

                led(255, 0, 0)   # turn on LED, red color
                led(255, 255, 0) # turn on LED, yellow color
                led(0, 0, 255)   # turn on LED, blue color
                led(0, 0, 0)     # turn off LED

        * **Flashes**: setting the `flashes` value to a non-zero value will
        cause the LED to flash the indicated number of times.  You can also
        specify the `on` and `off` arguments to indicate the amount of time 
        the LED is on and off for each flash (specified in milliseconds).

                led(0, 0, 255, 3)  # flash blue 3 times (then stop)
                led(0, 0, 255, 3, on=500, off=500)  # flash blue 3 times, much more slowly

        * **Repeated flashes**: setting the `repeat` argument to `True` 
        will cause the indicated flash pattern to repeat forever.  You can
        modify the pause time between flash sequences by setting `pause`
        (milliseconds).

                led(0, 0, 255, 3, True, pause=500)  # flash blue 3 times, pause, then repeat
                led(0, 0, 255, repeat=True, on=500, off=500)`  # flash blue forever

        * **Flashing with attenuation**: you can also set the `atten` 
        argument to make the LED to turn on and off slowly, like an
        incandescent light.  The value is the rate of change, so lower values
        cause the LED color to change more slowly. 

                led(0, 0, 255, repeat=True, atten=10, on=500, off=500) # flash blue forever, but turn on and turn off very slowly
        """
        on = self._u_int8(on/10)
        off = self._u_int8(off/10)
        pause = self._u_int8(pause/10)
        if flashes==0:
            mode = 0
        if repeat:
            mode = 0x02
        else:
            mode = 0x01
        self.bus.write_i2c_block_data(self.addr, 49, [mode, self._u_int8(r), self._u_int8(g), self._u_int8(b),
            on, off, self._u_int8(flashes), pause, self._u_int8(atten)])

    @check()
    def led_unicorn(self, speed=10):
        """
        This causes the LED to change color in succession: red, orange, yellow, 
        green, cyan, blue, violet and then repeat again.  The `speed` argument 
        ranges between 0 and 10.  For example, a `speed` of 0 causes the color 
        to change once every couple of seconds.  A `speed` of 10 causes the color to change about 6 times per second.
        """
        if speed>10:
            speed = 10
        elif speed<0:
            speed = 0

        on = self._u_int8(10 + (10-speed)*140/10)
        atten = self._u_int8(3 + speed*47/10)    
        self.bus.write_i2c_block_data(self.addr, 49, [0x08, 0, 0, 0, on, 0, 0, 0, atten])

    @check()
    def led_background(self, r=-1, g=-1, b=-1):
        """
        The "background" LED color is the color of the LED when the LED is 
        turned "off".  It is used by system programs such as vizy-power-monitor to
        indicate Vizy's system state such as, booting (yellow), finished
        booting (green), running server (blue), etc.  Note, the background
        color does not influence the LED colors set by calls to led().

        Calling led_background() without arguments returns the current 
        background color r, g, and b values in a list. 

            led_background(48, 48, 0)  # set background color to yellow
            led(0, 255, 0)  # turn on LED, green (as expected)
            led(0, 0, 0)  # turn LED off, and restore background color (yellow as set previously)    
        """
        if r==-1:
            return self.bus.read_i2c_block_data(self.addr, 58, 3)
        self.bus.write_i2c_block_data(self.addr, 58, [self._u_int8(r), self._u_int8(g), self._u_int8(b)])
 

    @check()
    def buzzer(self, freq, on=250, off=250, count=1, shift=0):
        """
        Emit tones through the buzzer.  The `freq` argument sets the frequency 
        of the tone in Hz and the `on` argument sets the length of the tone in
        milliseconds.  

        If you wish to emit more than 1 tone, you can set the
        `count` argument to the desired number.  

        The `off` argument sets 
        the pause between tones in milliseconds.  The `shift` argument is a
        value ranging between -128 and 127 that causes the tone's frequency to
        raise if `shift` is greater than 0, or descend if `shift` is less 
        than 0.

            buzzer(2000, 500) # emit a 2000Hz tone for 500ms
            buzzer(1000, count=3) # emit a 1000Hz tone 3 times   
            buzzer(1000, 500, 100, 3) # emit a longer 1000Hz tone 3 times
            buzzer(500, 250, 0, 10, 50) # emit 10 warbling tones like a siren
        """
        freq = self._uint16(freq)
        f0 = freq&0xff
        f1 = (freq>>8)&0xff
        self.bus.write_i2c_block_data(self.addr, 61, [0, f0, f1, self._u_int8(on/10), self._u_int8(off/10), 
            self._u_int8(count), self._int8(shift)])

    @check()
    def io_set_mode(self, bit, mode=None):
        """
        Sets or gets the io mode of the given bit.  The `bit` argument ranges
        between  0 and 3 and corresponds to pins 4 through 7 on Vizy's IO
        connector. Calling this method with no mode argument returns the mode
        of the given bit, otherwise, the `mode` argument can be one of 
        the following:

        * IO_MODE_INPUT, sets the bit to high impedance input mode with 
        a weak pull-up resistor to 3.3V.  The input voltage can range between
        0 and Vin where Vin is the supply voltage.  Voltages lower than 1V 
        read as logic 0 via `VizyPowerBoard.io_bits()`.  Voltages higher 
        than 1V are read as logic 1.
        * IO_MODE_OUTPUT, sets the bit to output mode.  If the bit is set to
        logic 0 via `VizyPowerBoard.io_bits()`, the output voltage is 0V.  
        If the bit is set to logic 1, the output voltage is 3.3V.  In this mode, each bit can source and sink 5mA.  
        * IO_MODE_HIGH_CURRENT, sets the bit to a special high current mode
        that allows the bit to sink as much as 870mA continuously, when the bit 
        is set to logic 0 via `VizyPowerBoard.io_bits()`.  Otherwise, this mode
        behaves exactly as IO_MODE_OUTPUT.  Note, when using this mode, the bits
        are not current-limited, so it is
        possible to damage a bit's hardware by sinking more 
        than 870mA for extended periods of time.  
        * IO_MODE_SERIAL, only applies to bits 2 and 3.  Setting bit 2 as
        IO_MODE_SERIAL makes it serial TX output.  Setting bit 3 as IO_MODE_SERIAL
        makes it serial RX input.     
        """
        if mode is None:
            return self.bus.read_i2c_block_data(self.addr, 68+bit, 1)[0]
        if (bit==0 or bit==1) and mode==IO_MODE_SERIAL:
            raise RuntimeError("Only bits 2 and 3 can be set IO_MODE_SERIAL")
        elif bit==2:
            if mode==IO_MODE_SERIAL:
                # set ALT5 mode (serial TX output)
                wp.pinModeAlt(8, 2) 
                mode=IO_MODE_INPUT
            else:
                # set pin 8 (UART TXD) as input so it doesn't conflict
                wp.pinMode(8, 0)
        elif bit==3:
            if mode==IO_MODE_SERIAL:
                # set ALT5 mode (serial input)
                wp.pinModeAlt(10, 2) 
                mode=IO_MODE_INPUT
            else:
                # set pin 10 (UART RX) as input so it doesn't receive garbage
                wp.pinMode(19, 0)

        self.bus.write_i2c_block_data(self.addr, 68+bit, [self._u_int8(mode)])

    @check(0)
    def io_bits(self, bits=None):
        """
        Sets or gets the logic state of the IO bits 0 through 3, corresponding
        to pins 4 through 7 on Vizy's IO connector.  The `bits` argument ranges
        between 0 and 15 as it is a binary representation of the logic state
        of the 4 IO bits.  If the `bits` argument isn't specified, the logic
        state of the 4 bits are returned.

            io_bits(1)   # set IO bit 0 to logic 1 and bits 1, 2, 3 to logic 0
            io_bits(10)  # set IO bits 1 and 3 to logic 1 and bits 0 and 2 to logic 0
            bits = io_bits()  # get logic state of IO bits
            io_bits(io_bits()|1)  # set IO bit 0 to logic 1, leave bits 1, 2, 3 unchanged. 
        """
        if bits is None:
            return self.bus.read_i2c_block_data(self.addr, 72, 1)[0]
        self.bus.write_i2c_block_data(self.addr, 72, [bits])

    @check()
    def io_set_bit(self, bit):
        """
        Sets the specified `bit` to logic 1.

            io_set_bit(0)  # set bit 0 to logic 1
        """
        self.io_bits(self.io_bits() | (1<<bit))

    @check()
    def io_reset_bit(self, bit):
        """
        Sets the specified `bit` to logic 0.

            io_reset_bit(0)  # set bit 0 to logic 0
        """
        self.io_bits(self.io_bits() & ~(1<<bit))

    @check(0)
    def io_get_bit(self, bit):
        """
        Returns the masked `bit`.  If the bit is logic 0, the result with be 0.  
        If the bit is logic 1, a value of 1<<bit is returned. 

            io_get_bit(0)  # get state of bit 0
        """
        return self.io_bits()&(1<<bit)

    @check(True)
    def ir_filter(self, state=None, duration=None):
        """
        Actuates the electro-mechanical IR-cut filter on Vizy's camera.  Vizy
        uses a CMOS sensor which is very sensitive to IR light.  IR light can 
        adversely affect color fidelity during the daytime so an IR-cut filter
        is used to block the IR light (`state`=True).  During nighttime IR light
        is typically used as a discreet method of illumination and the IR-cut
        filter is removed (`state`=False).  If the `state` argument is `True`,
        the filter is actuated in place (and will stay there) until another
        call is made with the state argument set to `False` (in which case the
        IR-cut filter will be removed).  

        The `duration` argument is optional and
        controls how long (in milliseconds) the actuation coil receives power.

        Calling this method without arguments returns the state of IR-cut
        filter.
        """
        if state is None:
            return True if self.bus.read_i2c_block_data(self.addr, 73, 1)[0] else False
        data = [1] if state else [0]
        if duration is not None:
            data.append(int(duration/10))
        self.bus.write_i2c_block_data(self.addr, 73, data)

    @check(0)
    def fan(self, speed=None):
        """
        Set or get the fan speed.  The `speed` argument can range between 0 
        and 4 where 0 is off and 4 is maximum speed.  The fan speed 
        is typically regulated automatically by vizy-power-monitor.

        Calling this method without arguments returns the current fan speed.  
        """
        if speed is None:
            return self.bus.read_i2c_block_data(self.addr, 75, 1)[0]
        self.bus.write_i2c_block_data(self.addr, 75, [self._u_int8(speed)])
       

    @check(datetime.datetime.now())
    def rtc(self, datetime_=None):
        """
        Set or get the real-time clock time/date.  The Vizy power board has a 
        battery-backed real-time clock that keeps track of time/date, power 
        alarms, etc. even while Vizy is receiving no power.  Passing in a
        datetime object sets the time/date.  

        Calling this method with no
        arguments returns a datetime object representing the current 
        date/time. 

        For example, the code below sets the date to December 2, 2020, 1:18pm:

            from datetime import datetime
            import vizypowerboard as vpb
            v = vpb.VizyPowerBoard()
            t = datetime(year=2020, month=12, day=2, hour=13, minute=18, second=0)
            v.rtc(t)
        """
        if datetime_ is None:
            # Initiate RTC retrieval.
            self._grab_semaphore()
            self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_RTC])
            # Wait until it's ready.
            self._wait_until_not_busy()
            t = self.bus.read_i2c_block_data(self.addr, EXEC_OFFSET+1, 8)
            self._release_semaphore()
            try:
                return datetime.datetime(year=self._bcd2decimal(t[7])+2016, month=self._bcd2decimal(t[6]), day=self._bcd2decimal(t[4]), hour=self._bcd2decimal(t[3]), minute=self._bcd2decimal(t[2]), second=self._bcd2decimal(t[1]))
            except:
                print(t)
                t = self.bus.read_i2c_block_data(self.addr, EXEC_OFFSET+1, 8)
                print(t)
                raise Exception

 
        t = [EXEC_RTC|EXEC_WRITE, 0, self._decimal2bcd(datetime_.second), self._decimal2bcd(datetime_.minute), self._decimal2bcd(datetime_.hour), self._decimal2bcd(datetime_.day), 0, self._decimal2bcd(datetime_.month), self._decimal2bcd(datetime_.year-2016)]
        self._grab_semaphore()
        self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, t)
        self._wait_until_not_busy()
        self._release_semaphore()

    @check(0)
    def dip_switches(self, val=None):
        """
        Set or get the (virtual) DIP switch state.  The DIP switches are a set 
        of "switches" that allow you to control Vizy's power-on or power-off
        behavior.  Like real DIP switches, their settings will be retained 
        regardless of power

        The switches are a set of values that can be ORed together:

        * DIPSWITCH_EXT_BUTTON, used to set external/remote power button, 
        e.g. with outdoor enclosure.  Default disabled.
        * DIPSWITCH_MUTE_BUZZER, used to mute the buzzer.  Default disabled.
        * DIPSWITCH_NO_BG_LED, used to disable the background LED, which is 
        normally set to yellow upon power up.  Default disabled.
        * DIPSWITCH_POWER_DEFAULT_OFF, if this power mode is set and you 
        plug in power via the 12V power input, Vizy will remain off by default
        until you press the button to power Vizy on.  And if power is
        interrupted while Vizy is on, *Vizy will turn off*.  If power is
        interrupted while Vizy is off, Vizy will remain off.  This is the
        default power mode.
        * DIPSWITCH_POWER_DEFAULT_ON, if this power mode is set and you 
        plug in power via the 12V power input, Vizy will turn on by default
        without pressing the button.  And if power is interrupted while Vizy
        is on, Vizy will reset, but remain on.  If power is interrupted while
        Vizy is off, *Vizy will turn on*.  Default disabled.
        * DIPSWITCH_POWER_SWITCH, if this power mode is set and you plug in
        power via the 12V power input, Vizy will remain off (as in
        DIPSWITCH_POWER_DEFAULT_OFF mode), unless power was 
        removed while Vizy was on.  In this case Vizy will turn on when you
        (re)apply power.  If power is interrupted while Vizy is off, Vizy 
        will remain off.  This behavior is similar to the behavior of a real
        power switch in that it retains the power "state" (on or off) and acts
        accordingly.  Default disabled.
        * DIPSWITCH_POWER_PLUG, if this power mode is set Vizy will remain
        powered on as long as it receives power through the 12V power plug, 
        and you will not be able to turn off Vizy via button or software as
        long as it's plugged in and receiving power.  Default disabled.
        * DIPSWITCH_1_BOOT_MODE, DIPSWITCH_2_BOOT_MODES ... DIPSWITCH_8_BOOT_MODES, upon 
        power-up, and if you so choose, you can select among up to 8 different
        "boot modes" for Vizy.  The selected boot mode can read later and used by the Vizy
        software to do something different than default. 
        Selecting the boot mode is done by holding down Vizy's button upon power-up until
        the LED starts to cycle colors.  This will occur after holding down the button 
        for 3 seconds.  The LED will then cycle through colors.
        Releasing the button will select the corresponding boot mode.  For example, 
        if you release the button while the LED is red, you have selected the "red" boot
        mode.   Vizy ships with
        DIPSWITCH_2_BOOT_MODES set.  This means that you have a choice between default (LED off) 
        and red (LED red) boot modes.  (Red boot mode is considered the "safe" or "recovery" boot mode.)   Setting DIPSWITCH_3_BOOT_MODES 
        will allow you to select among 3 boot modes (default, red and orange boot modes), 
        and so on.  See `VizyPowerBoard.boot_mode()` on how to read the boot mode that
        was selected upon power-up.  
        Question: what color is associated with default boot mode?  
        Answer: no color.  Default boot mode can be selected when the LED is off, which 
        is part of the LED color cycling.  You can also "select" default boot mode 
        by not holding down the button upon power-up (doing nothing special upon power-up). 
        But if you
        find yourself holding down the button too long upon power-up and cycling 
        through the colors and decide that you want to 
        choose default boot mode after all, 
        then just release the button when the LED is off.  
    
        For example, to set the DIP switches: 
            # set external power button, power switch mode, and 3 selectable boot modes
            dip_switches(DIPSWITCH_EXT_BUTTON | DIPSWITCH_POWER_SWITCH | DIPSWITCH_3_BOOT_MODES)  
        """
        if val is None:
            self._grab_semaphore()
            self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_NVCONFIG])
            # Wait until it's ready.
            self._wait_until_not_busy()
            res = self.bus.read_i2c_block_data(self.addr, EXEC_OFFSET+1, 1)[0]
            self._release_semaphore()
            return res

        self._grab_semaphore()
        self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_NVCONFIG|EXEC_WRITE, self._u_int8(val)])
        self._wait_until_not_busy()
        self._release_semaphore()

    @check()
    def rtc_adjust(self, val=None):
        """
        Set or get the real-time clock adjustment.  Vizy's real-time clock 
        crystal has an accuracy of 20ppm, which means that it can lose or gain 
        up to 20 seconds for every 1 million elapsed seconds.  Normally, this
        isn't an issue, but if Vizy spends a lengthy period of time (months)
        without Internet access, it could lose or gain minutes, which 
        depending on the application could be significant. The adjustment
        value can offset this inaccuracy.  The `val` argument can range 
        between -128 and 127 and has a multiplier of 2.170 ppm.  

        For example, 
        if the RTC is gaining 10 seconds every 1 million seconds, you would 
        call `rtc_adjust(-5)`.  If the RTC is losing 10 seconds every million
        seconds you would call `rtc_adjust(5)`.
        
        The adjustment value is retained by the real-time clock even when 
        Vizy's power is removed. 
        """
        if val is None:
            self._grab_semaphore()
            self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_RTC_CALIBRATE])
            # Wait until it's ready.
            self._wait_until_not_busy()
            res = self.bus.read_i2c_block_data(self.addr, EXEC_OFFSET+1, 1)[0]
            self._release_semaphore()
            return res

        self._grab_semaphore()
        self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_RTC_CALIBRATE|EXEC_WRITE, self._int8(val)])
        self._wait_until_not_busy()
        self._release_semaphore()


    @check(0.0)
    def measure(self, channel):
        """
        Get the voltage values of various channels.  The returned value is 
        the voltage measured (in Volts) of the given channel.  The `channel`
        argument can be one of the following:

        * CHANNEL_VIN, this channel measures the voltage present at the 12V
        power input.
        * CHANNEL_5V, this channel measures the voltage present at the 5V
        voltage rail provided to the Raspberry Pi.
        """  
        self._grab_semaphore()
        self.bus.write_i2c_block_data(self.addr, EXEC_OFFSET, [EXEC_AD, self._u_int8(channel)])
        # Wait until it's ready.
        self._wait_until_not_busy()
        val = self.bus.read_i2c_block_data(self.addr, EXEC_OFFSET+2, 2)
        self._release_semaphore()
        return (val[1]*0x100 + val[0])/1000

    def rtc_set_system_datetime(self, datetime_=None):
        """
        A convenience method that sets the system time/date based on the 
        real-time time/date.  This is called by vizy-power-monitor upon power-up. 
        """
        if os.geteuid()!=0:
            raise PermissionError("You need root permission to set the time/date.")
        if datetime_ is None:
            datetime_ = self.rtc()
        s = datetime_.isoformat()
        os.system(f"sudo date -s {s}")

