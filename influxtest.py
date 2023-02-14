#!/usr/bin/python3
import requests
import datetime 
import json 


cfg=json.load(open('dashsvrcfg.json','r'))


querybase = f"http://{cfg['INFLUXSVR']}:{cfg['INFLUXPORT']}/query?db={cfg['INFLUXDB']}&u={cfg['INFLUXUSER']}&p={cfg['INFLUXPASS']}&q="

#########################################
def gen_today() :
    t = datetime.datetime.now()
    return t.strftime("%Y-%m-%dT00:00:00Z")

#########################################
def get_results(json) :
    return json['results'][0]['series'][0]['values']



r = requests.get(querybase + "SHOW measurements")
if r.status_code >= 200 and r.status_code < 300 :
    print(r.content)

r= requests.get(querybase + "SELECT mean(\"soc\") FROM \"batterycharge\" WHERE time >= now() -1d GROUP BY time(1h)")
print(get_results(r.json()))

r = requests.get(querybase + "SELECT mean(solarPower), mean(housePower), mean(gridPower), mean(batteryPower) FROM instantpower WHERE time >= now() -1d GROUP BY time(30m)")
print(get_results(r.json()))

impClause = f"((last(gridImport)-first(gridImport))/1000)"
expClause = f"((last(gridExport)-first(gridExport))/1000)"
query=f"SELECT {impClause} AS \"IMPORT\", {expClause} AS \"EXPORT\" FROM energyusage WHERE time >= '{gen_today()}' TZ('{cfg['TIMEZONE']}')"
r = requests.get(querybase + query)
res=get_results(r.json())
importkWh = res[0][1]
exportkWh = res[0][2]
print(importkWh)
impCost = importkWh * cfg['IMPUNITCOST']
expGen  = exportkWh * cfg['EXPUNITCOST']
print(f"Cost today: £{(impCost - expGen) + cfg['STANDINGCHRG']:.2f}")