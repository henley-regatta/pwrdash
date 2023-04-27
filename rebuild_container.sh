#!/bin/sh

source dashenv.sh
if ["$CONTAINERNAME" == "" ]; then
    echo "Check dashenv.sh is valid"
    exit 1
fi

set -x
#This assumes it's already running. These steps are
#redundant if not

docker stop ${CONTAINERNAME}
docker container rm ${CONTAINERNAME}
docker image rm ${IMAGENAME}

# We will ALWAYS want to run these though:
git pull
docker build . -t ${IMAGENAME}
source start_pwrdashsvr.sh

docker logs -f ${CONTAINERNAME}

set +x
