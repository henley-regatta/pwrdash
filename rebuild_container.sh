#!/bin/sh

CONTAINERNAME="pwrdashsvr"
IMAGENAME="${USER}/${CONTAINERNAME}-app"
APPPORT=7478

set -x
#This assumes it's already running. These steps are
#redundant if not

docker stop ${CONTAINERNAME}
docker container rm ${CONTAINERNAME}
docker image rm ${IMAGENAME}

# We will ALWAYS want to run these though:

git pull
docker build . -t ${IMAGENAME}
docker run -p ${APPPORT}:${APPPORT} -d --name ${CONTAINERNAME} ${IMAGENAME}
docker logs -f ${CONTAINERNAME}

set +x
