# Docker configuration file to setup and run the Dashboard Server Python script
# Based on the official Docker Python image https://hub.docker.com/_/python/
# Build with:
#      docker build . -t username/pwrdashsvr-app
# (or see rebuild_container.sh)

FROM python:3
WORKDIR /usr/src/app 
ENV TZ="Europe/London"
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt 

COPY . . 

# Expose the default port (change if that changes)
EXPOSE 7478

CMD [ "python", "./dashsvr.py"] 