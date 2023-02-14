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
# NOTE: this will look better "Portrait" so everything's rotated 90 degrees
def gen_image(width,height) :
    #Generate a new (white) canvas in greyscale ('L') at required size:
    img = Image.new('L',(width,height),cfg['GREYMAP'][3])
    draw = ImageDraw.Draw(img)

    d= influx_query("SELECT last(soc) FROM batterycharge")
    soc=d[0][1]

    tStr = parse_influxts(d[0][0])
    draw.text((int(cfg['IMGWIDTH']/2),2), tStr,fill=cfg['GREYMAP'][0],font=largFont,anchor="mt")
        
    #Battery State Info
    bbox=[int(cfg['IMGWIDTH']/2),24,cfg['IMGWIDTH'],90]
    draw.rectangle(bbox,outline=cfg['GREYMAP'][2],width=1)
    draw.text((bbox[0]+25,bbox[1]+10),f"Batt:",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[0]+25,bbox[1]+35),f"{soc:.0f}%",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont)
    pctBox = pctfillbox(int(soc),0,0,20,bbox[3]-bbox[1])
    img.paste(pctBox, box=(bbox[0]+51,bbox[1]))
    soc=influx_query("SELECT mean(soc) FROM batterycharge WHERE time >= now() - 1d GROUP BY time(30m)")
    socs = just_the_data(soc,1)
    battChrgGraph = filledChart(socs,0,100,(bbox[2]-bbox[0])-70,bbox[3]-bbox[1],cfg['GREYMAP'][1])
    img.paste(battChrgGraph, box=(bbox[0]+72,bbox[1]))
 
    #Accountancy Data
    bbox=[0,24,int(cfg['IMGWIDTH']/2),90]
    draw.rectangle(bbox,outline=cfg['GREYMAP'][2],width=1)
    aQuery=f"SELECT ((last(gridImport)-first(gridImport))/1000), ((last(gridExport)-first(gridExport))/1000), ((last(houseImport)-first(houseImport))/1000),((last(solarExport)-first(solarExport))/1000) FROM energyusage WHERE time >= '{gen_today()}'"
    a=influx_query(aQuery)
    gridIn = a[0][1]
    gridOut = a[0][2]
    houseIn = a[0][3]
    solarOut = a[0][4]
    netGrid = gridIn-gridOut
    selfSufficiency = (houseIn-netGrid) / houseIn
    cost = (gridIn*cfg['IMPUNITCOST'] - gridOut*cfg['EXPUNITCOST']) + cfg['STANDINGCHRG']
        
    draw.text((int(bbox[2]/4),bbox[1]+10),f"Cost:",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((int(bbox[2]/4),bbox[1]+35),f"£{cost:.2f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont)
        
    draw.text((bbox[2]-int(bbox[2]/4),bbox[1]+10),f"Off-Grid",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2]-int(bbox[2]/4),bbox[1]+35),f"{selfSufficiency:.0%}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont)

    pwr=influx_query("SELECT mean(solarPower), mean(housePower), mean(gridPower), mean(batteryPower) FROM instantpower WHERE time >= now() -1d GROUP BY time(10m)")
    #The space we've got left is now...
    dBot = 90
    brRem = [cfg['IMGWIDTH'],cfg['IMGHEIGHT']]
    gRight=cfg['IMGWIDTH'] - 80
    hStep = (cfg['IMGHEIGHT']-dBot) / 4
    bbox=[0,dBot,gRight,dBot+hStep]
    midtBox = gRight+int((cfg['IMGWIDTH']-gRight)/2)
        
    hp=just_the_data(pwr,2)
    hpChart=filledChart(hp,0,10000,gRight,int(hStep),cfg['GREYMAP'][0])
    img.paste(hpChart,box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"House",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"10kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    draw.text((midtBox,bbox[1]+15),"House kWh",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((midtBox,bbox[1]+35),f"{houseIn:.1f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont )
    
    bbox[1] += hStep
    bbox[3] += hStep
    gp=just_the_data(pwr,3)
    gpChart=lineChart(gp,-1500,10000,gRight,int(hStep),cfg['GREYMAP'][0])
    img.paste(gpChart, box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"Grid",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"10kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    draw.text((bbox[2],bbox[3]),"-1.5kW",fill=cfg['GREYMAP'][1],anchor="rd",align="right",font=tinyFont)
    draw.text((midtBox,bbox[1]),"Grid kWh",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((midtBox,bbox[1]+20),f"{netGrid:.1f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont )
    bbox[1] += hStep
    bbox[3] += hStep
    sp=just_the_data(pwr,1)
    spChart=lineChart(sp,0,3200,gRight,int(hStep),cfg['GREYMAP'][0])
    img.paste(spChart, box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"Solar",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"3.2kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    draw.text((midtBox,bbox[1]-15),"Solar kWh",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((midtBox,bbox[1]+5),f"{solarOut:.1f}",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=medFont )
    bbox[1] += hStep
    bbox[3] += hStep
    bp=just_the_data(pwr,4)
    bpChart=lineChart(bp,-2000,5000,gRight,int(hStep),cfg['GREYMAP'][0])
    img.paste(bpChart,box=(bbox[0],int(bbox[1])))
    draw.text((bbox[0]+int(bbox[2]/2),bbox[1]),"Battery",fill=cfg['GREYMAP'][0],anchor="ma",align="center",font=smolFont)
    draw.text((bbox[2],bbox[1]),"5kW",fill=cfg['GREYMAP'][1],anchor="ra",align="right",font=tinyFont)
    draw.text((bbox[2],bbox[3]),"-2kW",fill=cfg['GREYMAP'][1],anchor="rd",align="right",font=tinyFont)
    
    #And in the bottom-right goes the latest power data:
    bbox=[gRight,int(bbox[1]-40),cfg['IMGWIDTH'],cfg['IMGHEIGHT']]
    #we need this area in 4:
    cX=int(bbox[2]-bbox[0])-1
    cY=int((bbox[3]-bbox[1])/4)-1
    draw.rectangle(bbox,outline=cfg['GREYMAP'][2],width=1)
    lp=influx_query("SELECT last(batteryPower),last(gridPower),last(housePower),last(solarPower) FROM instantpower")
    hBar=miniBar(lp[0][3]/1000,"House kW",0,10,cX,cY)
    img.paste(hBar,box=(bbox[0],bbox[1]))
    gBar=miniBar(lp[0][2]/1000,"Grid kW",-1,10,cX,cY)
    img.paste(gBar,box=(bbox[0],bbox[1]+cY+1))
    sBar=miniBar(lp[0][4]/1000,"Solar kW",0,4,cX,cY)
    img.paste(sBar,box=(bbox[0],bbox[1]+2*cY+2))
    bBar=miniBar(lp[0][1]/1000,"Batt kW",-2,5,cX,cY)
    img.paste(bBar,box=(bbox[0],bbox[1]+3*cY+3))


    return img

#helper functions for influx queries
#########################################
def gen_today() :
    t = datetime.now()
    return t.strftime("%Y-%m-%dT00:00:00Z")

#########################################
def get_results(json) :
    return json['results'][0]['series'][0]['values']

#########################################
def just_the_data(results,ndx) :
    d=[]
    for r in results :
        if len(r)>=ndx and r[ndx] is not None :
            d.append(r[ndx])
    return d

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