# ePaper Powerwall Dashboard

This is a Client/Server application to generate a self-refreshing dashboard page of household power usage on an ePaper display controlled by an RPi Pico W microcontroller. I've also written a test server app if you just want a framework for shipping server-built screen images to a PicoW microcontroller.

## Client Application
The Client is `dashloader.py` a micropython script running on the Pico. This is attached to a WaveShare 4.2 inch (400x300 4-greyscale) ePaper display. I've done other projects using this combination, see in particular [henley-regatta/pico_calendar_display](https://github.com/henley-regatta/pico_calendar_display). A key feature of this combo is _limited memory_ on the Pico which means building an in-memory screenbuffer is out of the question (too big). So this client program is used to retrieve over HTTP a zLib compressed bytestream of the dashboard image constructed by a server. It just loops through sleeping, waking up, connecting to WiFi, retrieving the URL and then squirting it to the WaveShare library for display.

Note that the client applications depends on a _customised_ version of `WavePaper42.py` being present in the root of the Pico's filesystem (see the `pico_calendar_display` project for more details). Assuming you've initialised micropython on the device, copying that library, the config file `dashloadcfg.json` and a copy of `dashloader.py` onto the Pico then renaming `dashloader.py` as `main.py` will be enough to get the client app running there...

### Client configuration
The client is configured with a JSON file put into the root of the Pico's miniscule filesystem. `dashloadcfg.json` is fairly simple:

```json
{ "SSID" : "MYWIFINETWORK",
  "SSPASS" : "mysecurewifipassword",
  "SERVERURL" : "http://10.0.0.14:7478/",
  "SLEEPINTERVAL" : 300}
```
The only real notes on this are:
  - Probably best to make `SERVERURL` an IP address unless you're absolutely confident nameserver resolution works 100% of the time for your local network
  - Make sure the port used is the same as the server configuration (or that mapped by the `Dockerfile` configuration if different...)
  - Don't set `SLEEPINTERVAL` too low; the Datasheet for the ePaper display says "try not to refresh more often than 180 seconds". You'd have real trouble from a performance perspective using less than about a minute anyway. 

## Server Application
The Server is in `dashsvr.py`. This is a full-fat Python 3 script that is used to:
  - Connect to an Influx time-series database holding all the measurements
  - Uses the [Pillow](https://python-pillow.org/) library (in a _very_ hokey way...) to turn those measurements into an Image
  - Provides a micro-Webserver on a configured port to provide that image either to test browsers (as a PNG) or as a zLib compressed bytestream for the `dashloader.py` client 

I _very_ much doubt this server will be of use to _anyone_ else as-is, because it's heavily dependent on my internal power statistics capture-and-record workflow, which is built on an obsolete version of InfluxDB (so old I'm still using InfluxQL not Flux...). And it's really, really badly written although I'm _quite_ proud of using sub-images and pasting to build up the final image from a collection of common components. 

### Server configuration
Like the client, there's a JSON file `dashsvrcfg.json` that sits alongside the server providing the stuff I don't want the wider world to read:

```json
{"IMGWIDTH"     : 300,
 "IMGHEIGHT"    : 400,
 "GREYMAP"      : [0,64,128,255],
 "NRMLFONT"     : "./DejaVuSans.ttf",
 "BOLDFONT"     : "./DejaVuSans-Bold.ttf",
 "SVRPORT"      : 7478,
 "TIMEZONE"     : "Europe/London",
 "INFLUXSVR"    : "influxSvr.local",
 "INFLUXPORT"   : 8086,
 "INFLUXDB"     : "powerdata",
 "INFLUXUSER"   : "user",
 "INFLUXPASS"   : "password",
 "IMPUNITCOST"  : 0.45,
 "EXPUNITCOST"  : 0.117,
 "STANDINGCHRG" : 0.46
}
```
  
  - `IMGWIDTH`, `IMGHEIGHT` and `GREYMAP` all define how the image is produced; `GREYMAP` is really only used for the PNG, there's an internal conversion to the specific values used by the ePaper display for it's 4 grey levels. 
  - Pillow is _supposed_ to be able to lookup font paths "from the system" but I had very mixed results with this so instead I've chosen to hard-code paths to specific TrueType fonts I'm using. Most open-source systems running a GUI should have a copy of these two files on them that you can link to 
  - `SVRPORT` is the port the micro-server will listen on. If you're running a firewall, pick a port that'll make it out so your client can get to it. And make the values match on the client config too...
  - `TIMEZONE` turns out to be important mostly for the Influx queries; it's probably best to make this match the TZ of your _Client_ system so that the start-of-day calculations work out correctly...
  - `INFLUXSVR`, `INFLUXPORT`, `INFLUXUSER`, `INFLUXPASS` and `INFLUXDB` all control connectivity from the Server app to the InfluxDB instance. This _probably_ won't work on InfluxDB 2.x I'm afraid...
  - `IMPUNITCOST`, `EXPUNITCOST` and `STANDINGCHRG` represent the current electricity costs used to work out the costs. Substitute your own values but you'll probably want to do a quick search-and-replace for the "£" symbol in the code if you're not based in the UK...

## Test Programs
I found I needed to build a couple of test programs to verify functionality as I went. I include them because you may find them helpful too

  - `demosvr.py` is a simplified version of the full server. This builds a simple screen image in memory then provides the PNG (for a browser) or RAW (zLib compressed bytestream) for a Pico client. Although everything's hardcoded in this (instead of using the JSON) you might find it useful as a "testcard" server if you're more interested in the client side
  - `influxtest.py` is just a test suite I used to build and verify my InfluxQL queries before adding them to the main server script.
  - `rebuild_container.sh` is a script to try and automate container build. The word "...Eh...." springs to mind.

## Docker/Container Build
I've included an example `Dockerfile` (and associated `.dockerignore`) to allow containerisation of a build; this is very much in _"Works On My Machine"_ territory though. One problem is that things you'd like to be external - in particular the config files - get "baked in" to the build, which isn't ideal. Impressively broken is the fact that I'm specifying the server port in *three* places - the config file, the Dockerfile, and as part of the container build process in order to get it to work...

I also include `rebuild_container.sh` as an example of how to rebuild the container assuming a current repository clone in the current directory. Note that you'll _also_ have to create the appropriate JSON config files (at the very least `dashsvrcfg.json`) and source the font files *before* running this script (or else the built container just won't work). 