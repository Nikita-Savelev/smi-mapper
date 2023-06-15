# smi-mapper


## Getting started

1. First you need to create a config.ini file based on config_template.ini
2. Next you need to create a bash script for download, build and run the project
```
#!/bin/sh
export PRJ=smi-mapper
mkdir $PRJ
cd $PRJ
cp ~/config.ini ./config/
docker build --no-cache -t "$PRJ" .
docker stop $PRJ"_running"
docker rm $PRJ"_running"
docker run -d --name $PRJ"_running" --restart unless-stopped --network host -e TZ=$(cat /etc/timezone) $PRJ
docker logs $PRJ"_running" -f
```
instead of LOGIN:PASSWORD you need to enter your data

3. Copy the config.ini and bash script files to the instance and connect to the instance
```
export SERV=IP_ADDRESS; ssh-keygen -R $SERV;  scp FILES ubuntu@$SERV:~ ; ssh ubuntu@$SERV
```

4. Run bash script for download, build and run the project

