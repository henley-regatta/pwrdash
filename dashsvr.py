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
from PIL import Image, ImageFilter, ImageDraw, ImageOps, ImageFont

cfg=json.load(open('dashsvrcfg.json','r'))

#Load our values from the cfg
# SETTINGS FOR THE GENERATED IMAGE:
IMGWIDTH  = cfg['IMGWIDTH']
IMGHEIGHT = cfg['IMGHEIGHT']
#AVAILABLE "COLOURS" IN THE IMAGE LISTED FROM DARK->LIGHT
IMGCOLS = cfg['IMGCOLS']

#PORT TO LISTEN ON
LISTENPORT = cfg['SVRPORT']
#TIMEZONE for Queries and stuff:
TZ=pytz.timezone(cfg['TIMEZONE'])
#BASE URL for Influx queries:
querybase = f"http://{cfg['INFLUXSVR']}:{cfg['INFLUXPORT']}/query?db={cfg['INFLUXDB']}&u={cfg['INFLUXUSER']}&p={cfg['INFLUXPASS']}&q="



#########################################################################
def gen_image(width,height) :
    #Generate a new (white) canvas in greyscale ('L') at required size:
    img = Image.new('L',(width,height),0xff)
    #put some placeholder crap on it
    draw = ImageDraw.Draw(img)
    draw.line((0,0) + img.size, fill=128)
    draw.line((0,img.size[1], img.size[0],0), fill=128)
    myFont = ImageFont.truetype("DejaVuSans.ttf", 60)
    draw.multiline_text((width/2,height/2), "Hello\nWorld!",font=myFont, anchor="ms",fill=0x00)
    
    return img
   
#########################################################################
# Here's our "web server" handler
class ThreadedTCPRequestHandler(socketserver.StreamRequestHandler) :
    def handle(self):
        self.data = self.rfile.readline().strip()
        p = str(self.data).split()
        print(f"{self.client_address[0]} requested: {p[1]}")
        stdhdrs=f"HTTP/1.1 200 OK\r\nServer: dashsvr/0.1\r\nAccept-Ranges: bytes\r\nDate: {datetime.now(TZ)}"
        if len(p)>0 and ("png" in p[1].lower()) :
            print("Writing PNG")
            self.wfile.write(b'HTTP/1.0 200 OK\nContent-Type: image/png\n\n')
            im = gen_image(IMGWIDTH,IMGHEIGHT)
            im.save(self.wfile,format='PNG')
        else :
            print("Writing RAW")
        
#########################################################################
# Here's our "Web Server":
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass 

#########################################################################
#########################################################################
#########################################################################
if __name__ == "__main__" :
    socketserver.TCPServer.allow_reuse_address = True #needed to allow restart after Ctrl-C
    server = ThreadedTCPServer(("",LISTENPORT), ThreadedTCPRequestHandler)
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


        

