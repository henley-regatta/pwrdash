#!/usr/bin/python3
#
# dashsvr.py
# ----------
# A simple web server that only serves up images constructed on-the-fly
# in low-res low-colour of a power dashboard.
#
# Intended as a server for a PiPico ePaper display that doesn't have the 
# memory to build it's own image so needs a server-supplied one.
#
# NON-STANDARD MODULES REQUIRED:
#   pip install influxdb-client
#########################################################################
import socket,threading,socketserver,sys,time,zlib
from datetime import date
from datetime import datetime
import pytz
import json
import requests
from PIL import Image, ImageFilter, ImageDraw, ImageOps, ImageFont

#Load our values from the cfg
cfg=json.load(open('dashsvrcfg.json','r'))

#TIMEZONE for Queries and stuff:
TZ=pytz.timezone(cfg['TIMEZONE'])
#BASE URL for Influx queries:
querybase = f"http://{cfg['INFLUXSVR']}:{cfg['INFLUXPORT']}/query?db={cfg['INFLUXDB']}&u={cfg['INFLUXUSER']}&p={cfg['INFLUXPASS']}&q="

#Load the fonts
tinyFont = ImageFont.truetype(cfg['NRMLFONT'],8)
smolFont = ImageFont.truetype(cfg['NRMLFONT'],14)
medFont  = ImageFont.truetype(cfg['BOLDFONT'],16)
largFont = ImageFont.truetype(cfg['NRMLFONT'],20)



#########################################################################
def pctfillbox(pct,tlX,tlY,brX,brY) :
    w = brX-tlX 
    h = brY-tlY
    subImg = Image.new('L',(w,h),cfg['GREYMAP'][3])
    draw = ImageDraw.Draw(subImg)
    draw.rectangle((0,0,w-1,h),fill=cfg['GREYMAP'][2],outline=cfg['GREYMAP'][1],width=1)
    pctHeight = int(h*(pct/100))
    draw.rectangle((0,h-pctHeight,w,h),fill=cfg['GREYMAP'][0],width=1)
    return subImg

#########################################################################
def yFract(v,minV,maxV) :
    yOut=0
    if v > maxV :
        yOut=1
    elif v < minV :
        yOut=0
    else :
        yOut = (v-minV)/(maxV-minV)
    return yOut
            
#########################################################################
def filledChart(series,minH,maxH,maxX,maxY,fColour) :
    subImg = Image.new('L',(maxX,maxY),cfg['GREYMAP'][3])
    draw=ImageDraw.Draw(subImg)
    draw.rectangle((0,0,maxX-1,maxY),fill=cfg['GREYMAP'][3],outline=cfg['GREYMAP'][2],width=1)
    #Work out the X step-width
    numVals=len(series)
    dX = maxX / numVals
    #now plot the bars
    lastX=1
    for v in series :
        nextX = lastX+dX
        #height of bar
        nextY=maxY - (yFract(v,minH,maxH)*maxY)
        draw.rectangle((lastX,maxY,int(nextX),int(nextY)),fill=fColour)
        lastX=nextX

    return subImg

#########################################################################
def lineChart(series,minH,maxH,maxX,maxY,lColour) :
    subImg = Image.new('L',(maxX,maxY),cfg['GREYMAP'][3])
    draw   = ImageDraw.Draw(subImg)
    #now offset the values for internal drawing 
    maxX -=1
    maxY -=1
    draw.rectangle((0,0,maxX,maxY),fill=cfg['GREYMAP'][3],outline=cfg['GREYMAP'][2],width=1)
    #Further offset for actual value plotting
    maxX -=1
    maxY -=1
    #steps and ranges
    numVals = len(series)
    dX = maxX / numVals 
  
    #We draw as line segments with the only hack being that
    #the start point is at the scale height of the first data point
    lastX=1
    lastY=maxY - (yFract(series[0],minH,maxH)*maxY)
    
    # SPECIAL - if minH < 0, draw a line across at zero
    if minH < 0 :
        zeroH = maxY - (yFract(0,minH,maxH)*maxY)
        draw.line((lastX,zeroH,maxX,zeroH),fill=cfg['GREYMAP'][2],width=1)
    
    for v in series :
        nextX = lastX+dX 
        nextY = maxY - (yFract(v,minH,maxH)*maxY)
        draw.line((int(lastX),int(lastY),int(nextX),int(nextY)),fill=lColour,width=1)
        lastX=nextX
        lastY=nextY
    return subImg

#########################################################################
#This draws a "line" but uses categorised data by band to differentiate
def lineChartWithCategories(series,minH,maxH,maxX,maxY) :
    subImg = Image.new('L',(maxX,maxY),cfg['GREYMAP'][3])
    draw   = ImageDraw.Draw(subImg)
    #now offset the values for internal drawing 
    maxX -=1
    maxY -=1
    draw.rectangle((0,0,maxX,maxY),fill=cfg['GREYMAP'][3],outline=cfg['GREYMAP'][2],width=1)
    #Further offset for actual value plotting
    maxX -=1
    maxY -=1
    #steps and ranges
    numVals = len(series)
    dX = maxX / numVals 
  
    #We draw as line segments with the hacks being that
    #the start point is at the scale height of the first data point
    #and we'll draw a "background" rectangle for CHEAP/PEAK
    lastX=1
    lastY=maxY - (yFract(series[0][0],minH,maxH)*maxY)
    
    # SPECIAL - if minH < 0, draw a line across at zero
    if minH < 0 :
        zeroH = maxY - (yFract(0,minH,maxH)*maxY)
        draw.line((lastX,zeroH,maxX,zeroH),fill=cfg['GREYMAP'][2],width=1)
    
    for v in series :
        nextX = lastX+dX 
        nextY = maxY - (yFract(v[0],minH,maxH)*maxY)
        #colour determined by timeblock
        if v[1] == 2 :   # CHEAP
            lColour = cfg['GREYMAP'][0]
            draw.rectangle((int(lastX),0,int(nextX),int(maxY)),fill=cfg['GREYMAP'][2])
        elif v[1] == 1 : # PEAK
            lColour = cfg['GREYMAP'][3]
            draw.rectangle((int(lastX),0,int(nextX),int(maxY)),fill=cfg['GREYMAP'][1])
        else :           # STANDARD
            lColour = cfg['GREYMAP'][0]
        draw.line((int(lastX),int(lastY),int(nextX),int(nextY)),fill=lColour,width=1)
        lastX=nextX
        lastY=nextY
    return subImg

#########################################################################    
def miniBar(data,title,minV,maxV,dimX,dimY) :
    subImg = Image.new('L',(dimX,dimY),cfg['GREYMAP'][3])
    draw = ImageDraw.Draw(subImg)
    dFmt=f"{data:2.1f}"
    if dimY>20 :
        cBound=[30,0,dimX,dimY]
        draw.text((15,int(dimY/2)),dFmt,fill=cfg['GREYMAP'][0],align='center',anchor="mm",font=smolFont)
    else :
        cBound=[15,0,dimX,dimY]
        draw.text((7,int(dimY/2)),dFmt,fill=cfg['GREYMAP'][0],align='center',anchor='mm',font=tinyFont)
    draw.rectangle(cBound,fill=cfg['GREYMAP'][2],width=1)
    xRange=maxV-minV
    pctFull = (data-minV)/xRange
    if pctFull > 1 :
        pctFull = 1
    elif pctFull < 0 :
        pctFull = 0
    xBar = cBound[0] + int((cBound[2]-cBound[0])*pctFull)
    draw.rectangle((cBound[0],cBound[1],xBar,cBound[3]),fill=cfg['GREYMAP'][0],width=1)
    #SPECIAL CASE if minV < 0 draw a line at this point to mark it
    if minV < 0 :
        zeroLine = (0-minV)/xRange
        zeroLine = cBound[0] + int((cBound[2]-cBound[0])*zeroLine)
        draw.line((zeroLine,0,zeroLine,dimY),fill=cfg['GREYMAP'][3])
    #OVERLAY the title in white
    draw.text((cBound[0]+int((cBound[2]-cBound[0])/2),int(cBound[3]/2)),title,fill=cfg['GREYMAP'][3],align='center',anchor='mm',font=tinyFont)
    
    return subImg

#########################################################################    
#GIVEN: Grid usage "today", determine usage by time-block (std/peak/cheap)
def usageByTimeblockToday(gridData) :
    usage={"imp" : [0,0,0], #STD,PEAK,CHEAP
           "exp" : [0,0,0]}
    #these are meter readings, we want to track a delta which means holding
    #previous values
    pVals=gridData[0][1:]

    for p in gridData:
        dImp=p[1]-pVals[0]
        dExp=p[2]-pVals[1]
        ts=influxts_to_ts(p[0])
        #Determine cost bracket
        if ts>=cheapTime[0] and ts <=cheapTime[1] :  #CHEAP?
            usage["imp"][2] += dImp 
            usage["exp"][2] += dExp
        elif ts>=peakTime[0] and ts<=peakTime[1] : #PEAK?
            usage["imp"][1] += dImp 
            usage["exp"][1] += dExp
        else :                               #STD?
            usage["imp"][0] += dImp 
            usage["exp"][0] += dExp
        #reset the counters
        pVals=p[1:]
    return usage

######################################################################### 
#GIVEN: A set of time-series data, detemine which time-block each value goes into
def catByTimeblock(data,ndx) :
    categorised=[]
    for v in data :
        #ts always index 0 
        ts = influxts_to_ts(v[0])
        if ts>=cheapTime[0] and ts <= cheapTime[1] :
            categorised.append([v[ndx],2])
        elif ts>=peakTime[0] and ts <= peakTime[1] :
            categorised.append([v[ndx],1])
        else :
            categorised.append([v[ndx],0])
    return categorised


#########################################################################
# NOTE: this will look better "Portrait" so everything's rotated 90 degrees
def gen_image(width,height) :
    #Generate a new (white) canvas in greyscale ('L') at required size:
    img = Image.new('L',(width,height),cfg['GREYMAP'][3])
    draw = ImageDraw.Draw(img)

    d= influx_query("SELECT last(soc) FROM batterycharge")
    soc=d[0][1]

    #Header including current time
    tStr = parse_influxts(d[0][0])
    draw.text((int(cfg['IMGWIDTH']/2),2), tStr,fill=cfg['GREYMAP'][0],font=largFont,anchor="mt")
        
    #Battery State Info
    bbox=[int(cfg['IMGWIDTH']/2),24,cfg['IMGWIDTH'],90]
    draw.rectangle(bbox,outline=cfg['GREYMAP'][2],width=1)
    draw.text((bbox[0]+25,bbox[1]+10),f"Batt:",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[0]+25,bbox[1]+35),f"{soc:.0f}%",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont)
    #The battery state box
    pctBox = pctfillbox(int(soc),0,0,15,bbox[3]-bbox[1])
    img.paste(pctBox, box=(bbox[2]-15,bbox[1]))
    #The state-of-charge-over-last-day chart
    soc=influx_query("SELECT mean(soc) FROM batterycharge WHERE time >= now() - 1d GROUP BY time(30m)")
    socs = just_the_data(soc,1)
    battChrgGraph = filledChart(socs,0,100,(bbox[2]-bbox[0])-61,bbox[3]-bbox[1],cfg['GREYMAP'][1])
    img.paste(battChrgGraph, box=(bbox[0]+45,bbox[1]))
 
    #Accountancy Data
    bbox=[0,24,int(cfg['IMGWIDTH']/2),90]
    draw.rectangle(bbox,outline=cfg['GREYMAP'][2],width=1)
    aQuery=f"SELECT ((last(gridImport)-first(gridImport))/1000), ((last(gridExport)-first(gridExport))/1000), ((last(houseImport)-first(houseImport))/1000),((last(solarExport)-first(solarExport))/1000) FROM energyusage WHERE time >= {gen_today()}s"
    a=influx_query(aQuery)
    [gridIn,gridOut,houseIn,solarOut, netGrid, selfSufficiency] = [0,0,0,0,0,1]
    if len(a) > 0 :
        gridIn = a[0][1] 
        gridOut = a[0][2]
        houseIn = a[0][3] 
        solarOut = a[0][4]
        netGrid = gridIn-gridOut
        selfSufficiency = (houseIn-netGrid) / houseIn
    if selfSufficiency > 1 :
        selfSufficiency = 1 #Technically correct to be >100% efficient if we're back-feeding grid, but not a helpful value to display
    #MCE 2023-07-04 - COST is about to get a whole heap harder to work out
    # thanks to smart tariffs. So, here goes....
    usage=usageByTimeblockToday(influx_query(f"SELECT gridImport/1000, gridExport/1000 from energyusage WHERE time >= {gen_today()}s"))
    cost = cfg['STANDINGCHRG'] + \
           (usage["imp"][0] * cfg['STDIMPCOST'] - usage["exp"][0] * cfg['STDEXPCOST']) + \
           (usage["imp"][1] * cfg['PEAKIMPCOST'] - usage["exp"][1] * cfg['PEAKEXPCOST']) + \
           (usage["imp"][2] * cfg['CHEAPIMPCOST'] - usage["exp"][2] * cfg['CHEAPEXPCOST'])
           
    pwr=influx_query("SELECT mean(solarPower), mean(housePower), mean(gridPower), mean(batteryPower) FROM instantpower WHERE time >= now() -1d GROUP BY time(10m)")
        
    draw.text((int(bbox[2]/4),bbox[1]+10),f"Cost:",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((int(bbox[2]/4),bbox[1]+35),f"£{cost:.2f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont)
        
    draw.text((bbox[2]-int(bbox[2]/4),bbox[1]+10),f"Off-Grid",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2]-int(bbox[2]/4),bbox[1]+35),f"{selfSufficiency:.0%}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont)

    #The "main" left-lower portion is our 4 charts of power gen/consumption:
    dBot = 90 # the area lies BELOW this line (y>=dBot)
    gRight=cfg['IMGWIDTH'] - 80
    hStep = (cfg['IMGHEIGHT']-dBot) / 4
    bbox=[0,dBot,gRight,dBot+hStep]
    #This is the centre point for the text summaries of production/consumption on the RIGHT
    midtBox = gRight+int((cfg['IMGWIDTH']-gRight)/2)
    
    #MCE 2023-07-04 - GRID power needs to reflect time-of-day to be useful for cost analysis
    gp=catByTimeblock(pwr,3)
    gpChart=lineChartWithCategories(gp,-1500,10000,gRight,int(hStep))
    img.paste(gpChart, box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"Grid",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"10kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    draw.text((bbox[2],bbox[3]),"-1.5kW",fill=cfg['GREYMAP'][1],anchor="rd",align="right",font=tinyFont)
    
    #HOUSE USAGE data doesn't need to worry about time-of-day
    bbox[1] += hStep
    bbox[3] += hStep        
    hp=just_the_data(pwr,2)
    hpChart=filledChart(hp,0,10000,gRight,int(hStep),cfg['GREYMAP'][0])
    img.paste(hpChart,box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"House",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"10kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    
    #SOLAR generation doesn't need to worry about time-of-day
    bbox[1] += hStep
    bbox[3] += hStep
    sp=just_the_data(pwr,1)
    spChart=filledChart(sp,0,3200,gRight,int(hStep),cfg['GREYMAP'][1])
    img.paste(spChart, box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"Solar",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"3.2kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    
    #BATTERY charge-rate might be useful to categorise by time-of-day
    bbox[1] += hStep
    bbox[3] += hStep
    #bp=just_the_data(pwr,4)
    #bpChart=lineChart(bp,-2000,5000,gRight,int(hStep),cfg['GREYMAP'][0])
    bp=catByTimeblock(pwr,4)
    bpChart=lineChartWithCategories(bp,-2000,5000,gRight,int(hStep))
    img.paste(bpChart,box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"Battery",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"5kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    draw.text((bbox[2],bbox[3]),"-2kW",fill=cfg['GREYMAP'][1],anchor="rd",align="right",font=tinyFont)
    
    
    lp=influx_query("SELECT last(batteryPower),last(gridPower),last(housePower),last(solarPower) FROM instantpower")        
    
    #Down the right hand side go the summaries of consumption plus the bar-charts of current 
    #production/usage.
    sBox = dBot+5 # our starting point is at the top of the area
    #we need to work out how much space is available per bar-chart. We can do this by subtracting 
    #the size of the text we need (25 * 2 * 3 = 120) from the remaining space
    remChartSpace = cfg['IMGHEIGHT'] - sBox - (25 * 2 * 3)
    #Making each chart size...
    cX = cfg['IMGWIDTH'] - gRight
    cY = int(remChartSpace/4) - 5
    #Now do the GRID:
    sOffset = sBox
    draw.text((midtBox,sOffset),"Grid kWh",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((midtBox,sOffset+20),f"{netGrid:.1f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont )
    gBar=miniBar(lp[0][2]/1000,"Grid kW",-1,10,cX,cY)
    img.paste(gBar,box=(gRight,sOffset+45))
    
    #Now do the HOUSE:
    sOffset = sBox+45+cY+10
    draw.text((midtBox,sOffset),"House kWh",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((midtBox,sOffset+20),f"{houseIn:.1f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont )
    hBar=miniBar(lp[0][3]/1000,"House kW",0,10,cX,cY)
    img.paste(hBar,box=(gRight,sOffset+45))
    
    #Now do the SOLAR:
    sOffset = sOffset+45+cY+10
    draw.text((midtBox,sOffset),"Solar kWh",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((midtBox,sOffset+20),f"{solarOut:.1f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont )
    sBar=miniBar(lp[0][4]/1000,"Solar kW",0,4,cX,cY)
    img.paste(sBar,box=(gRight,sOffset+45))
    #Poor old Battery just goes on the bottom....
    bBar=miniBar(lp[0][1]/1000,"Batt kW",-2,5,cX,cY)
    img.paste(bBar,box=(gRight,cfg['IMGHEIGHT']-cY))


    return img

#helper functions for influx queries
#########################################
def gen_today() :
    #This timestamp stuff needs specifying in Epoch
    today=date.today()
    return int(datetime.combine(today, datetime.min.time()).timestamp())

#########################################
#TODO - seeing errors on this when getting a blank result
#       (one with no data). Need to handle it.
def get_results(json) :
    if 'series' in json['results'][0] :
        return json['results'][0]['series'][0]['values']
    else :
        print(f"ERROR - no 'series' in json results: {json['results']}")
        return []

#########################################
def just_the_data(results,ndx) :
    d=[]
    for r in results :
        if len(r)>=ndx and r[ndx] is not None :
            d.append(r[ndx])
    return d

#########################################
def influxts_to_ts(influxts) :
    notz=influxts.split('+')
    noDecimal = notz[0].split('.')
    noDate = noDecimal[0].split('T')
    return datetime.strptime(noDate[1],"%H:%M:%S")

#########################################
def cfgblktime_to_ts(cfgblktime):
    return datetime.strptime(cfgblktime,"%H:%M")

#########################################
def parse_influxts(influxts) :
    noDecimal = influxts.split('.')
    ts = datetime.strptime(noDecimal[0],"%Y-%m-%dT%H:%M:%S")
    outTS=ts.strftime("%a %d %b %H:%M")
    return outTS

#########################################
def influx_query(query) :
    full_q = f"{querybase}{query} TZ('{cfg['TIMEZONE']}')"
    r = requests.get(full_q)
    if r.status_code >= 200 and r.status_code < 300 :
        return get_results(r.json())
    else :
        print(f"Influx query failed. Query = \n{full_q}\n RC={r.status_code}")
        return None

#########################################
def prepRawData(img) :
    #source is portrait, rotate to landscape
    land=img.transpose(method=Image.ROTATE_90)
    twobitpic = ImageOps.posterize(land,2).tobytes(encoder_name='raw')
    epd4gray = bytearray()
    for b in range(len(twobitpic)) :
        v = twobitpic[b]
        if v == 0 :
            epd4gray.append(0x00)
        elif v == 64 :
            epd4gray.append(0xaa)   # NOTE: this is deliberately in the wrong order;
        elif v == 128 :
            epd4gray.append(0x55)   # for reasons unknown, "light grey" has a lower byte index than "dark gray"
        else :
            epd4gray.append(0xff)
    return zlib.compress(epd4gray)

#########################################################################
# Here's our "web server" handler
class ThreadedTCPRequestHandler(socketserver.StreamRequestHandler) :
    def handle(self):
        self.data = self.rfile.readline().strip()
        p = str(self.data).split()
        print(f"{self.client_address[0]} requested: {p}")
        stdhdrs=f"HTTP/1.1 200 OK\r\nServer: dashsvr/0.1\r\nAccept-Ranges: bytes\r\nDate: {datetime.now(TZ)}"
        if len(p)>1 and ("favicon" not in p[1].lower()) : 
            im=gen_image(cfg['IMGWIDTH'],cfg['IMGHEIGHT'])
            if ("png" in p[1].lower()) :
                print("Returning PNG")
                self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n')
                im.save(self.wfile,format='PNG')
            else :
                print("Returning RAW")
                svrdata=prepRawData(im)
                hdr = f"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(svrdata)}\r\n\r\n"
                self.wfile.write(bytes(hdr,encoding="utf-8"))
                self.wfile.write(svrdata)
        else :
            print("Ignoring request")
        
#########################################################################
# Here's our "Web Server":
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass 

#########################################################################
#########################################################################
#########################################################################
if __name__ == "__main__" :
    #Determine the time-brackets for cheap/peak/standard
    cheapTime=[cfgblktime_to_ts(cfg['CHEAPSTART']),cfgblktime_to_ts(cfg['CHEAPEND'])]
    peakTime=[cfgblktime_to_ts(cfg['PEAKSTART']),cfgblktime_to_ts(cfg['PEAKEND'])]
    socketserver.TCPServer.allow_reuse_address = True #needed to allow restart after Ctrl-C
    server = ThreadedTCPServer(("",cfg['SVRPORT']), ThreadedTCPRequestHandler)
    with server :
        ip, port = server.server_address
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True 
        server_thread.start()
        print(f"Listening at {ip} on port {port} via {server_thread.name}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Intercepted Ctrl-C")
            server.shutdown()
            sys.exit()