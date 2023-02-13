#!/usr/bin/python3
import requests
import datetime 
import json 


cfg=json.load(open('influxcfg.json','r'))


querybase = f"http://{cfg['SERVER']}:{cfg['SVRPORT']}/query?db={cfg['DATABASE']}&u={cfg['USER']}&p={cfg['PASSWORD']}&q="

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


STDCHARGE=0.2095
IMPORTRATE=0.117
EXPORTRATE=0.117
impClause = f"((last(gridImport)-first(gridImport))/1000)"
expClause = f"((last(gridExport)-first(gridExport))/1000)"
query=f"SELECT {impClause} AS \"IMPORT\", {expClause} AS \"EXPORT\" FROM energyusage WHERE time >= '{gen_today()}' TZ('Europe/London')"
r = requests.get(querybase + query)
res=get_results(r.json())
importkWh = res[0][1]
exportkWh = res[0][2]
print(importkWh)
impCost = importkWh * IMPORTRATE 
expGen  = exportkWh * EXPORTRATE
print(f"Cost today: £{(impCost - expGen) + STDCHARGE:.2f}")