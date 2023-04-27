#!/bin/bash
source dashenv.sh
if [ -z ${CONTAINERNAME} ]; then
    echo "Check dashenv.sh is valid"
    exit 1
fi
docker run -p ${APPPORT}:${APPPORT} -d --restart unless-stopped --name ${CONTAINERNAME} ${IMAGENAME}
docker ps
