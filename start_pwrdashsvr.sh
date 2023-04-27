#!/bin/sh
source dashenv.sh
if ["$CONTAINERNAME" == "" ]; then
    echo "Check dashenv.sh is valid"
    exit 1
fi
docker run -p ${APPPORT}:${APPPORT} -d --restart unless-stopped --rm --name ${CONTAINERNAME} ${IMAGENAME}
