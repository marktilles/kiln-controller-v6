#!/usr/bin/env python

import time
import os
import sys
import logging
import json
from datetime import datetime
import bottle

# Add for health feature
import subprocess
script_dir = os.path.dirname(os.path.abspath(__file__))
from bottle import template, TEMPLATE_PATH
# Now add views to TEMPLATE_PATH
TEMPLATE_PATH.insert(0, os.path.join(script_dir, 'views'))


import gevent
import geventwebsocket
#from bottle import post, get
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket import WebSocketError

# try/except removed here on purpose so folks can see why things break
import config

logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("kiln-controller")
log.info("Starting kiln controller")

script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')
profile_path = config.kiln_profiles_directory

from oven import SimulatedOven, RealOven, Profile
from ovenWatcher import OvenWatcher

app = bottle.Bottle()

# START BLINKING LED WHEN SERVICE IS RUNNING. REM OUT SECTION IF NOT DESIRED
#if config.service_running_led == True:
#    log.info("Starting GPIO service-running LED on GPIO " + str(config.service_running_led_gpio))
#    from gpiozero import Button, LEDBoard
#    from signal import pause
#    import warnings, os, sys
#    service_running_ledGPIO = config.service_running_led_gpio
#    service_running_led=LEDBoard(service_running_ledGPIO)
#    service_running_led.blink(on_time=1, off_time=1)
# END - START BLINKING LED WHEN SERVICE IS RUNNING

if config.simulate == True:
    log.info("this is a simulation")
    oven = SimulatedOven()
else:
    log.info("this is a real kiln")
    oven = RealOven()
ovenWatcher = OvenWatcher(oven)
# this ovenwatcher is used in the oven class for restarts
oven.set_ovenwatcher(ovenWatcher)

@app.route('/')
def index():
    return bottle.redirect('/picoreflow/index.html')

@app.route('/state')
def state():
    return bottle.redirect('/picoreflow/state.html')

@app.get('/api/stats')
def handle_api():
    log.info("/api/stats command received")
    if hasattr(oven,'pid'):
        if hasattr(oven.pid,'pidstats'):
            return json.dumps(oven.pid.pidstats)


@app.post('/api')
def handle_api():
    log.info("/api is alive")


    # run a kiln schedule
    if bottle.request.json['cmd'] == 'run':
        wanted = bottle.request.json['profile']
        log.info('api requested run of profile = %s' % wanted)

        # start at a specific minute in the schedule
        # for restarting and skipping over early parts of a schedule
        startat = 0;      
        if 'startat' in bottle.request.json:
            startat = bottle.request.json['startat']

        #Shut off seek if start time has been set
        allow_seek = True
        if startat > 0:
            allow_seek = False

        # get the wanted profile/kiln schedule
        profile = find_profile(wanted)
        if profile is None:
            return { "success" : False, "error" : "profile %s not found" % wanted }

        # FIXME juggling of json should happen in the Profile class
        profile_json = json.dumps(profile)
        profile = Profile(profile_json)
        oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        ovenWatcher.record(profile)

    if bottle.request.json['cmd'] == 'pause':
        log.info("api pause command received")
        oven.state = 'PAUSED'

    if bottle.request.json['cmd'] == 'resume':
        log.info("api resume command received")
        oven.state = 'RUNNING'

    if bottle.request.json['cmd'] == 'stop':
        log.info("api stop command received")
        oven.abort_run()

    if bottle.request.json['cmd'] == 'memo':
        log.info("api memo command received")
        memo = bottle.request.json['memo']
        log.info("memo=%s" % (memo))

    # get stats during a run
    if bottle.request.json['cmd'] == 'stats':
        log.info("api stats command received")
        if hasattr(oven,'pid'):
            if hasattr(oven.pid,'pidstats'):
                return json.dumps(oven.pid.pidstats)

    return { "success" : True }

def find_profile(wanted):
    '''
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    '''
    #load all profiles from disk
    profiles = get_profiles()
    json_profiles = json.loads(profiles)

    # find the wanted profile
    for profile in json_profiles:
        if profile['name'] == wanted:
            return profile
    return None

def run_profile(profile, startat=0):
    oven.run_profile(profile, startat)
    ovenWatcher.record(profile)


@app.route('/picoreflow/:filename#.*#')
def send_static(filename):
    log.debug("serving %s" % filename)
    return bottle.static_file(filename, root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public"))


def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get('wsgi.websocket')
    if not wsock:
        abort(400, 'Expected WebSocket request.')
    return wsock


@app.route('/control')
def handle_control():
    wsock = get_websocket_from_request()
    log.info("websocket (control) opened")
    while True:
        try:
            message = wsock.receive()
            if message:
                log.info("Received (control): %s" % message)
                msgdict = json.loads(message)
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    profile_obj = msgdict.get('profile')
                    if profile_obj:
                        profile_json = json.dumps(profile_obj)
                        profile = Profile(profile_json)
                    oven.run_profile(profile)
                    ovenWatcher.record(profile)

                elif msgdict.get("cmd") == "SCHEDULED_RUN":
                    log.info("SCHEDULED_RUN command received")
                    scheduled_start_time = msgdict.get('scheduledStartTime')
                    profile_obj = msgdict.get('profile')
                    if profile_obj:
                        profile_json = json.dumps(profile_obj)
                        profile = Profile(profile_json)

                    start_datetime = datetime.fromisoformat(
                        scheduled_start_time,
                    )
                    oven.scheduled_run(
                        start_datetime,
                        profile,
                        lambda: ovenWatcher.record(profile),
                    )

                elif msgdict.get("cmd") == "SIMULATE":
                    log.info("SIMULATE command received")
                    #profile_obj = msgdict.get('profile')
                    #if profile_obj:
                    #    profile_json = json.dumps(profile_obj)
                    #    profile = Profile(profile_json)
                    #simulated_oven = Oven(simulate=True, time_step=0.05)
                    #simulation_watcher = OvenWatcher(simulated_oven)
                    #simulation_watcher.add_observer(wsock)
                    #simulated_oven.run_profile(profile)
                    #simulation_watcher.record(profile)
                elif msgdict.get("cmd") == "STOP":
                    log.info("Stop command received")
                    oven.abort_run()
                #time.sleep(1)

                # CUSTOM MENU-ACCESSED FUNCTONS- these backend scripts are simple password protected - see config.py
                elif msgdict.get("cmd") == "BACKEND_FUNCTION_1":
                    log.info("BACKEND_FUNCTION_1 shutdown command received")
                    os.system ("sudo shutdown -P +0 &"); # shutdown and power off
                elif msgdict.get("cmd") == "BACKEND_FUNCTION_3":
                    log.info("BACKEND_FUNCTION_3 reinit service command received")
 #                  os.system("sudo sh -c 'sleep 3; /home/pi/kiln-controller/mark-scripts/startkilns' &")
  #                 os.system("sudo  /home/pi/kiln-controller/mark-scripts/stopkilns")
                    os.system("sudo systemctl restart kiln-controller.service &")
                elif msgdict.get("cmd") == "BACKEND_FUNCTION_2":
                    log.info("BACKEND_FUNCTION_2 reboot command received")
                    os.system ("sudo reboot")
                # END CUSTOM MENU-ACCESSED FUNCTONS
        except WebSocketError as e:
            log.error(e)
            break
    log.info("websocket (control) closed")


@app.route('/storage')
def handle_storage():
    wsock = get_websocket_from_request()
    log.info("websocket (storage) opened")
    while True:
        try:
            message = wsock.receive()
            if not message:
                break
            log.debug("websocket (storage) received: %s" % message)

            try:
                msgdict = json.loads(message)
            except:
                msgdict = {}

            if message == "GET":
                log.info("GET command received")
                wsock.send(get_profiles())
            elif msgdict.get("cmd") == "DELETE":
                log.info("DELETE command received")
                profile_obj = msgdict.get('profile')
                if delete_profile(profile_obj):
                  msgdict["resp"] = "OK"
                wsock.send(json.dumps(msgdict))
                #wsock.send(get_profiles())
            elif msgdict.get("cmd") == "PUT":
                log.info("PUT command received")
                profile_obj = msgdict.get('profile')
                #force = msgdict.get('force', False)
                force = True
                if profile_obj:
                    #del msgdict["cmd"]
                    if save_profile(profile_obj, force):
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
                    log.debug("websocket (storage) sent: %s" % message)

                    wsock.send(json.dumps(msgdict))
                    wsock.send(get_profiles())
            time.sleep(1) 
        except WebSocketError:
            break
    log.info("websocket (storage) closed")


@app.route('/config')
def handle_config():
    wsock = get_websocket_from_request()
    log.info("websocket (config) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send(get_config())
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (config) closed")


@app.route('/status')
def handle_status():
    wsock = get_websocket_from_request()
    ovenWatcher.add_observer(wsock)
    log.info("websocket (status) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send("Your message was: %r" % message)
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (status) closed")


def get_profiles():
    try:
        profile_files = os.listdir(profile_path)
    except:
        profile_files = []
    profiles = []
    for filename in profile_files:
        with open(os.path.join(profile_path, filename), 'r') as f:
            profiles.append(json.load(f))
    profiles = normalize_temp_units(profiles)
    return json.dumps(profiles)


def save_profile(profile, force=False):
    profile=add_temp_units(profile)
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    if not force and os.path.exists(filepath):
        log.error("Could not write, %s already exists" % filepath)
        return False
    with open(filepath, 'w+') as f:
        f.write(profile_json)
        f.close()
    log.info("Wrote %s" % filepath)
    return True

def add_temp_units(profile):
    """
    always store the temperature in degrees c
    this way folks can share profiles
    """
    if "temp_units" in profile:
        return profile
    profile['temp_units']="c"
    if config.temp_scale=="c":
        return profile
    if config.temp_scale=="f":
        profile=convert_to_c(profile);
        return profile

def convert_to_c(profile):
    newdata=[]
    for (secs,temp) in profile["data"]:
        temp = (5/9)*(temp-32)
        newdata.append((secs,temp))
    profile["data"]=newdata
    return profile

def convert_to_f(profile):
    newdata=[]
    for (secs,temp) in profile["data"]:
        temp = ((9/5)*temp)+32
        newdata.append((secs,temp))
    profile["data"]=newdata
    return profile

def normalize_temp_units(profiles):
    normalized = []
    for profile in profiles:
        if "temp_units" in profile:
            if config.temp_scale == "f" and profile["temp_units"] == "c": 
                profile = convert_to_f(profile)
                profile["temp_units"] = "f"
        normalized.append(profile)
    return normalized

def delete_profile(profile):
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True


def get_config():
    return json.dumps({"temp_scale": config.temp_scale,
        "time_scale_slope": config.time_scale_slope,
        "time_scale_profile": config.time_scale_profile,
        "kwh_rate": config.kwh_rate,
        "currency_type": config.currency_type,
        "kw_elements": config.kw_elements,
        "currency_type": config.currency_type,
        # ADDED TO PORT IN MORE INFO FROM BACKEND
        "pid_kp": config.pid_kp,
        "pid_ki": config.pid_ki,
        "pid_kd": config.pid_kd,
        "kiln_name": config.kiln_name,
        "service_running_led_gpio": config.service_running_led_gpio,
        "function_passcode": config.function_passcode,
        "kiln_must_catch_up": config.kiln_must_catch_up,
        "pid_control_window": config.pid_control_window,
        "emergency_shutoff_temp": config.emergency_shutoff_temp,
        "ignore_pid_control_window_until": config.ignore_pid_control_window_until})
        # ADDED TO PORT IN MORE INFO FROM BACKEND

def main():
    ip = "0.0.0.0"
    port = config.listening_port
    log.info("listening on %s:%d" % (ip, port))

    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()

# --- System health report ---
def run_health_command(command, timeout=5):
    """Run a read-only diagnostic command and return its output."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += ("\n" if output else "") + result.stderr.strip()
        return output if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "(command timed out)"
    except Exception as e:
        return f"(error: {e})"


def get_system_health():
    """Collect current, read-only Raspberry Pi OS/Debian health information."""
    return {
        "hostname": run_health_command(["hostname"]),
        "date": run_health_command(["date", "+%Y-%m-%d %H:%M:%S %Z"]),
        "uptime": run_health_command(["uptime"]),
        "disk": run_health_command(
            ["df", "-hT", "-x", "tmpfs", "-x", "devtmpfs"]
        ),
        "inodes": run_health_command(
            ["df", "-hi", "-x", "tmpfs", "-x", "devtmpfs"]
        ),
        "memory": run_health_command(["free", "-h"]),
        "load": run_health_command(
            ["awk", '{print "1 min: " $1 "\n5 min: " $2 "\n15 min: " $3}', "/proc/loadavg"]
        ),
        "process_count": run_health_command(
            ["bash", "-c", "ps -e --no-headers | wc -l"]
        ),
        "top_memory": run_health_command(
            ["bash", "-c", "ps aux --sort=-%mem | head -11"]
        ),
        "top_cpu": run_health_command(
            ["bash", "-c", "ps aux --sort=-%cpu | head -11"]
        ),
        "failed_services": run_health_command(
            ["systemctl", "--failed", "--no-legend"]
        ),
        "network": run_health_command(["ip", "-brief", "addr"]),
        "route": run_health_command(["ip", "route", "show", "default"]),
        "dns": run_health_command(
            ["bash", "-c", "grep -v '^[[:space:]]*#' /etc/resolv.conf"]
        ),
        "kernel_errors": run_health_command(
            ["dmesg", "--level=warn,err", "--ctime"]
        ),
        "journal_errors": run_health_command(
            ["journalctl", "-p", "err", "-b", "--no-pager", "-n", "40"]
        ),
        "mounts": run_health_command(
            ["findmnt", "-rn", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"]
        ),
    }


class DotDict(dict):
    """Dictionary subclass that allows attribute-style access (e.g., obj.key)."""
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"'DotDict' object has no attribute '{item}'")

@app.route("/health")
def health():
    """Display a live system health report."""
    raw_health = get_system_health()
    health_obj = DotDict(raw_health)
    
    # Pass health_obj as both 'health' and unpacked kwargs
    return template("health.html", health=health_obj, **health_obj)



if __name__ == "__main__":
    main()
