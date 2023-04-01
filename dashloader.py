# A PiPico uPython script to periodically reload a
# raw "EPD" format image from a web location
# which allows "server side rendering" on this 
# platform with limited memory.
#
# To load this at boot, rename to main.py
#
# Note that "WaveShareEpaper42.py" and "dashloadercfg.json"
# must also be in the root of the Pico's filesystem for this to work.
#
# an EPD is a custom zlib compressed bytestream
# of exactly 400x300 pixels, uncompressing to a 
# bytestream matching the EPD 4Gray (black/darkgrey/greyish/white)
# *values*. (0x00,0xaa,0x55,00xff yes I know the middle are reversed that's deliberate)
#
# Note the config values for network, source URL and refresh rate (in seconds) are 
# loaded from an external JSON. 
#
# There is VERY little error checking done here....
###########################################################
import gc

def pMem(why) :
    print(f"{why}: {gc.mem_alloc()} / {gc.mem_free()}")
import WaveShareEpaper42
import utime
import urequests
import uio
import json 
import zlib
import machine
led = machine.Pin("LED", machine.Pin.OUT)

import network
cfg=json.load(open('dashloadercfg.json','r'))

#Setup globals:
MAXWIDTH=WaveShareEpaper42.EPD_WIDTH
MAXHEIGHT=WaveShareEpaper42.EPD_HEIGHT
CHARWIDTH=8
CHARHEIGHT=8
#Bit poor form but treat this as a global:
epd=WaveShareEpaper42.EPD_4in2()

###########################################################
def blinkLED(count, onMS) :
    for x in range(count*2) :
        led.toggle()
        utime.sleep_ms(onMS)
    led.off()

########################################
def wait_for_wifi():
    global wlan
    max_wait = 10
    while max_wait > 0:
        blinkLED(1,100)
        s=wlan.status()
        if s < 0 or s >= 3:
            break
        max_wait -= 1
        utime.sleep_ms(1000)
    return s

###########################################################
def centreText(txt,maxWidth) :
    tLen = len(txt) * CHARWIDTH
    border = maxWidth - tLen
    if border <= 0 :
        return 0
    else :
        return int(border / 2)

###########################################################
def errDumpText(texttodump) :
    global epd
    gc.collect() # voodoo
    epd.EPD_4IN2_Init()
    #Initialise the framebuffer to white:
    epd.image4Gray.fill(0xff)

    maxCharsPerLine=int(MAXWIDTH/CHARWIDTH)-2*CHARWIDTH
    errLines=list(texttodump[0+i:maxCharsPerLine+i] for i in range(0,len(texttodump),maxCharsPerLine))
    tHeight=int(MAXHEIGHT/2)-len(errLines)*CHARHEIGHT+2
    
    for errLine in errLines :
        epd.image4Gray.text(errLine,centreText(errLine,MAXWIDTH),tHeight,epd.black)
        tHeight += CHARHEIGHT+2
    epd.EPD_4IN2_4GrayDisplay(epd.buffer_4Gray)
    epd.Sleep()
    epd.reset()
    epd.module_exit()
    gc.collect() # voodoo

########################################
def get_gscale(gscale_url): 
    try:
        print(f"Getting Image Data from {gscale_url}")
        hdrs={"Accept" : "application/octet-stream",
              "User-Agent" : "dashloader/0.1"}
        r = urequests.get(gscale_url,headers=hdrs)
        if r.status_code >= 200 and r.status_code < 300 :
            print(f"Request OK with rc={r.status_code}, content-size: {len(r.content)}")
            buff=r.content
            r.close() #bad things happen if you don't close the request
            return(buff)
        else :
            rc=r.status_code
            r.close()
            raise IOError(f'GET of {gscale_url} failed with response code = {rc}')
        #If we got here, we failed. Own it.
        raise IOError(f'Unknown error retrieving {gscale_url}')
    except Exception as err:
        errType = type(err).__name__
        errString=(f"Exception retrieving {gscale_url} : {errType}\n{err}")
        print(errString)
        for x in range(5) :
            blinkLED(3,250)
            utime.sleep_ms(500)
            blinkLED(3,666)
            utime.sleep_ms(500)
            blinkLED(3,250)
            utime.sleep_ms(1000)
            machine.reset() # or what, just hang forever? Lame!

########################################
def display_img(imgdata) :
   #Blank the ePaper
    epd.EPD_4IN2_Init()
    #Initialise the framebuffer to white:
    epd.image4Gray.fill(0xff)

    psuid = uio.BytesIO(imgdata)
    decomp = zlib.DecompIO(psuid)
    for y in range(MAXHEIGHT) :
        lData = decomp.read(MAXWIDTH)
        if lData :
            for x in range(MAXWIDTH) :
                epd.image4Gray.pixel(x,y,lData[x])
            
    epd.EPD_4IN2_4GrayDisplay(epd.buffer_4Gray)
    epd.Sleep()
        
########################################
# This is important in giving a
# window of control - once we get to
# system.lightsleep() we lose control of
# REPL - this isn't just diagnostics it's
# an opportunity to break out
blinkLED(10,250)
initTxt = f"Refresh every {cfg['SLEEPINTERVAL']/60} minutes for {cfg['SERVERURL']} connecting to {cfg['SSID']}"
print(initTxt)
errDumpText(initTxt)        
########################################
# Main program loop:
while True:
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(cfg['SSID'],cfg['SSPASS'])
    while (wait_for_wifi() != 3) :
        utime.sleep_ms(1000)
        wlan.connect(cfg['SSID'],cfg['SSPASS'])

    #Indicator of connection established:
    blinkLED(2,1000)

    # PAYLOAD GOES HERE
    try:
        display_img(get_gscale(cfg['SERVERURL']))
    except TypeError :
        print(f"Failed to get/display image. I Sleep.")
  

    #If proposing to system.lightsleep(), epd.Sleep() isn't enough
    #one needs some more drastic disconnect:
    epd.reset()
    epd.module_exit()

    #Indicator of display complete:
    blinkLED(10,100)
    
    wlan.disconnect()
    wlan.active(False)
    #https://github.com/orgs/micropython/discussions/9135
    #vital for actually turning wifi off:
    wlan.deinit()
    wlan = None
    blinkLED(1,10) ##effectively an "off"
    #note that the ePaper needs to be "disconnected" before
    #sleep to prevent a dim screen (pin going high?).
    #check ePaper code not only does epd.Sleep() but also
    #epd.reset()/epd.module_exit() before we get to this
    #point:
    machine.idle() 
    machine.lightsleep(cfg['SLEEPINTERVAL'] * 1000)