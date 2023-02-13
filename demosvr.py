#!/usr/bin/python3
import socket,threading,socketserver,sys,time,zlib
from datetime import datetime
import pytz
from PIL import Image, ImageFilter, ImageShow, ImageOps, ImageDraw, ImageFont

# SETTINGS FOR THE GENERATED IMAGE:
IMGWIDTH  = 400
IMGHEIGHT = 300
#AVAILABLE "COLOURS" IN THE IMAGE LISTED FROM DARK->LIGHT
IMGCOLS = [0x00,0xaa,0x55,0xff]

#PORT TO LISTEN ON
LISTENPORT = 7478
TZ = pytz.timezone('Europe/London')

demoimg="beach.jpg"
svrdata=bytearray()

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
        print(f"{self.client_address[0]} requested: {p[1]} ({p})")
        stdhdrs=f"HTTP/1.1 200 OK\r\nServer: demosvr/0.1\r\nAccept-Ranges: bytes\r\nDate: {datetime.now(TZ)}"
        
        if len(p)>0 and ("png" in p[1].lower()) :
            print("Writing PNG")
            hdr = f"{stdhdrs}\r\nContent-Type: image/png\r\n\r\n"
            self.wfile.write(bytes(hdr,encoding="utf-8"))
            im = gen_image(IMGWIDTH,IMGHEIGHT)
            im.save(self.wfile,format='PNG')
        else :
            print("Writing RAW")
            hdr = f"{stdhdrs}\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(svrdata)}\r\n\r\n"
            self.wfile.write(bytes(hdr,encoding="utf-8"))
            self.wfile.write(svrdata)
#########################################################################
# Here's our "Web Server":
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass 

#########################################################################
#########################################################################
#########################################################################
if __name__ == "__main__" :
    
    with Image.open(demoimg) as pic:
        pic.thumbnail((IMGWIDTH,IMGHEIGHT))
        greypic = ImageOps.grayscale(pic)
        twobitpic = ImageOps.posterize(greypic,2).tobytes(encoder_name='raw')
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
        print(f"Posterised raw image length = {len(epd4gray)}")
        svrdata=zlib.compress(epd4gray)
    print(f"zLib compressed data size = {len(svrdata)} bytes")
    
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