import logging
import os
from digitalio import DigitalInOut
import busio

########################################################################
#
#   General options

# Give the kiln a name for the GUI
kiln_name = "AIM"

# Password required to avoid accidental firing cancellations or curve modifications 
# The password is also required to execute optional BACKEND-FUNCTIONs 1 and 2
# set passcode to "" to disable
#function_passcode = "pass"
function_passcode = ""

# Enable a blinking LED while service is running.
# Requires modules: gpiozero, signal, warnings, os, sys
# Set to "False" if not desired or if not all of the above modules are installed.
service_running_led = True
service_running_led_gpio = 6 # Old system
#service_running_led_gpio = 16 # New development system

### Logging
log_level = logging.INFO
log_format = '%(asctime)s %(levelname)s %(name)s: %(message)s'

### Server
listening_port = 8081

########################################################################
# Cost Information
#
# This is used to calculate a cost estimate before a run. It's also used
# to produce the actual cost during a run. My kiln has three
# elements that when my switches are set to high, consume 9460 watts.
# 1,1451 net avgift
# 0,4364 kwh price
# 1,5815 total
kwh_rate        = 0.26  # cost per kilowatt hour per currency_type to calculate cost to run job
kw_elements     = 7.78  # if the kiln elements are on, the wattage in kilowatts
currency_type   = "$"   # Currency Symbol to show when calculating cost to run job

########################################################################
#
# Hardware Setup (uses BCM Pin Numbering)
#
# kiln-controller.py uses SPI interface from the blinka library to read
# temperature data from the adafruit-31855 or adafruit-31856.
# Blinka supports many different boards. I've only tested raspberry pi.
#
# First you must decide whether to use hardware spi or software spi.
# 
# Hardware SPI
#
# - faster
# - requires 3 specific GPIO pins be used on rpis
# - no pins are listed in this config file 
# 
# Software SPI
#
# - slower (which will not matter for reading a thermocouple
# - can use any GPIO pins
# - pins must be specified in this config file

#######################################
# SPI pins if you choose Hardware SPI #
#######################################
# On the raspberry pi, you MUST use predefined
# pins for HW SPI. In the case of the adafruit-31855, only 3 pins are used:
#
#    SPI0_SCLK = BCM pin 11 = CLK on the adafruit-31855
#    SPI0_MOSI = BCM pin 10 = not connected
#    SPI0_MISO = BCM pin 9  = D0 on the adafruit-31855
#   
# plus a GPIO output to connect to CS. You can use any GPIO pin you want.
# I chose gpio pin 5:
#
#    GPIO5    = BCM pin 5   = CS on the adafruit-31855
#
# Note that NO pins are configured in this file for hardware spi

#######################################
# SPI pins if you choose software spi #
#######################################
# For software SPI, you can choose any GPIO pins you like.
# You must connect clock, mosi, miso and cs each to a GPIO pin
# and configure them below based on your connections.

#######################################
# SPI is Autoconfigured !!!
#######################################
# whether you choose HW or SW spi, it is autodetected. If you list the PINs
# below, software spi is assumed.

#######################################
# Output to control the relay
#######################################
# A single GPIO pin is used to control a relay which controls the kiln.
# I use GPIO pin 23.

try:
    import board
    spi_sclk  = board.D11 #spi CLK clock
    spi_miso  = board.D9  #spi SDO Microcomputer In Serial Out
    spi_cs    = board.D8  #spi CS Chip Select
    spi_mosi  = board.D10 #spi SDI Microcomputer Out Serial In (not connected) 
    gpio_heat = board.D23 #RELAY output that controls relay
except (NotImplementedError,AttributeError):
    print("not running on blinka recognized board, probably a simulation")

#######################################
### Thermocouple breakout boards
#######################################
# There are only two breakoutboards supported. 
#   max31855 - only supports type K thermocouples
#   max31856 - supports many thermocouples
max31855 = 0
max31856 = 1
# uncomment these two lines if using MAX-31856
import adafruit_max31856
thermocouple_type = adafruit_max31856.ThermocoupleType.K

# here are the possible max-31856 thermocouple types
#   ThermocoupleType.B
#   ThermocoupleType.E
#   ThermocoupleType.J
#   ThermocoupleType.K
#   ThermocoupleType.N
#   ThermocoupleType.R
#   ThermocoupleType.S
#   ThermocoupleType.T

########################################################################
#
# If your kiln is above the starting temperature of the schedule when you 
# click the Start button... skip ahead and begin at the first point in 
# the schedule matching the current kiln temperature.
seek_start = True

########################################################################
#
# duty cycle of the entire system in seconds
# 
# Every N seconds a decision is made about switching the relay[s] 
# on & off and for how long. The thermocouple is read 
# temperature_average_samples times during and the average value is used.
# Note: changing this might affect the Heat% calculation displayed in the GUI. But this is only visual.
sensor_time_wait = 2

########################################################################
#
#   PID parameters
#
# These parameters control kiln temperature change. These settings work
# well with the simulated oven. You must tune them to work well with 
# your specific kiln. Note that the integral pid_ki is
# inverted so that a smaller number means more integral action.

# If you have oscillations that don't stop or increase in size, reduce pid_kp
# If you have an oscillation but the temperature is mostly below the setpoint, decrease pid_ki.

#pid_kp = 10   # Proportional 25,200,200
#pid_ki = 80   # Integral
#pid_kd = 220  #220.83497910261562 # Derivative
pid_kp = 3
pid_ki = 44
pid_kd = 129
########################################################################
#
# Initial heating and Integral Windup
#
# this setting is deprecated and is no longer used. this happens by
# default and is the expected behavior.
stop_integral_windup = True

########################################################################
#
#   Simulation parameters
simulate = False
sim_t_env      = 65   # deg
sim_c_heat     = 500.0  # J/K  heat capacity of heat element
sim_c_oven     = 5000.0 # J/K  heat capacity of oven
sim_p_heat     = 5450.0 # W    heating power of oven
sim_R_o_nocool = 0.5   # K/W  thermal resistance oven -> environment
sim_R_o_cool   = 0.05   # K/W  " with cooling
sim_R_ho_noair = 0.1    # K/W  thermal resistance heat element -> oven
sim_R_ho_air   = 0.05   # K/W  " with internal air circulation

# if you want simulations to happen faster than real time, this can be
# set as high as 1000 to speed simulations up by 1000 times.
sim_speedup_factor = 1


########################################################################
#
#   Time and Temperature parameters
#
# If you change the temp_scale, all settings in this file are assumed to
# be in that scale.

temp_scale          = "c" # c = Celsius | f = Fahrenheit - Unit to display
time_scale_slope    = "h" # s = Seconds | m = Minutes | h = Hours - Slope displayed in temp_scale per time_scale_slope
time_scale_profile  = "m" # s = Seconds | m = Minutes | h = Hours - Enter and view target time in time_scale_profile

# emergency shutoff the profile if this temp is reached or exceeded.
# This just shuts off the profile. If your SSR is working, your kiln will
# naturally cool off. If your SSR has failed/shorted/closed circuit, this
# means your kiln receives full power until your house burns down.
# this should not replace you watching your kiln or use of a kiln-sitter
emergency_shutoff_temp = 1270

# If the kiln cannot heat or cool fast enough and is off by more than
# pid_control_window the entire schedule is shifted until
# the desired temperature is reached. If your kiln cannot attain the
# wanted temperature, the schedule will run forever. This is often used
# for heating as fast as possible in a section of a kiln schedule/profile.
kiln_must_catch_up = False

# This setting is required.
# This setting defines the window within which PID control occurs.
# Outside this window (N degrees below or above the current target)
# the elements are either 100% on because the kiln is too cold
# or 100% off because the kiln is too hot. No integral builds up
# outside the window. The bigger you make the window, the more
# integral you will accumulate.This should be a positive integer.
pid_control_window = 5 #degrees

# Ignore over-swings and let the firing curve progress until this temp is reached. This shortens the firing time
# because oherwise overswings over the pid_control_window cause the timer to stop until the kiln cools off. But
# there isn't really any risk involved since we are still at such a low temp, just let the curve continue on until
# the target temp catches up to the overshot temp and then continue normally. If you dont want this, set to 10
ignore_pid_control_window_until = 70 

# thermocouple offset
# If you put your thermocouple in ice water and it reads 36F, you can
# set set this offset to -4 to compensate.  This probably means you have a
# cheap thermocouple.  Invest in a better thermocouple.
# Only full decimals
thermocouple_offset = -8

# number of samples of temperature to take over each duty cycle.
# The larger the number, the more load on the board. K type 
# thermocouples have a precision of about 1/2 degree C. 
# The median of these samples is used for the temperature.
temperature_average_samples = 10 

# Thermocouple AC frequency filtering - set to True if in a 50Hz locale, else leave at False for 60Hz locale
ac_freq_50hz = False

########################################################################
# Emergencies - or maybe not
########################################################################
# There are all kinds of emergencies that can happen including:
# - temperature is too high (emergency_shutoff_temp exceeded)
# - lost connection to thermocouple
# - unknown error with thermocouple
# - too many errors in a short period from thermocouple
# but in some cases, you might want to ignore a specific error, log it,
# and continue running your profile instead of having the process die.
#
# You should only set these to True if you experience a problem
# and WANT to ignore it to complete a firing.
ignore_temp_too_high = False
ignore_tc_lost_connection = False
ignore_tc_cold_junction_range_error = False
ignore_tc_range_error = False
ignore_tc_cold_junction_temp_high = False
ignore_tc_cold_junction_temp_low = False
ignore_tc_temp_high = False
ignore_tc_temp_low = False
ignore_tc_voltage_error = False
ignore_tc_short_errors = False 
ignore_tc_unknown_error = False

# This overrides all possible thermocouple errors and prevents the 
# process from exiting.
ignore_tc_too_many_errors = False

########################################################################
# automatic restarts - if you have a power brown-out and the raspberry pi
# reboots, this restarts your kiln where it left off in the firing profile.
# This only happens if power comes back before automatic_restart_window
# is exceeded (in minutes). The kiln-controller.py process must start
# automatically on boot-up for this to work.
# DO NOT put automatic_restart_state_file anywhere in /tmp. It could be
# cleaned up (deleted) by the OS on boot.
# The state file is written to disk every sensor_time_wait seconds (2s by default)
# and is written in the same directory as config.py.
automatic_restarts = True
automatic_restart_window = 15 # max minutes since power outage
automatic_restart_state_file = os.path.abspath(os.path.join(os.path.dirname( __file__ ),'state.json'))

########################################################################
# load kiln profiles from this directory
# created a repo where anyone can contribute profiles. The objective is
# to load profiles from this repository by default.
# See https://github.com/jbruce12000/kiln-profiles
kiln_profiles_directory = os.path.abspath(os.path.join(os.path.dirname( __file__ ),"storage", "profiles")) 
#kiln_profiles_directory = os.path.abspath(os.path.join(os.path.dirname( __file__ ),'..','kiln-profiles','pottery')) 


########################################################################
# low temperature throttling of elements
# kiln elements have lots of power and tend to drastically overshoot
# at low temperatures. When under the set point and outside the PID
# control window and below throttle_below_temp, only throttle_percent
# of the elements are used max.
# To prevent throttling, set throttle_percent to 100.
throttle_below_temp = 300
throttle_percent = 60
#throttle_percent = 100
