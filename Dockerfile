# Docker configuration file to setup and run the Dashboard Server Python script
# Based on the official Docker Python image https://hub.docker.com/_/python/

FROM python:3
WORKDIR /usr/src/app 
ENV TZ="Europe/London"
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt 

COPY . . 

# Expose the default port (change if that changes)
EXPORT 7478

CMD [ "python", "./dashsvr.py"] 