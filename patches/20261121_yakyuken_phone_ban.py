import time
ID="20261121_yakyuken_phone_ban";DESC="11/21野球拳のスマホ禁止を外す";CID="c036592b9"
LO=time.mktime((2026,11,22,16,50,0,0,0,-1));HI=UNTIL=LO+600
def apply(c):
 n=0
 for w in c.worlds():
  p=c.store.dpath("worlds",w,"state",CID+".json");s=c.store.load(p,None);d=((s or{}).get("forfeit")or{}).get("day")or[]
  k=[x for x in d if not(x.get("who")=="me"and x.get("what")=="phone"and LO<=float(x.get("until")or 0)<=HI)]
  if len(k)<len(d):n+=len(d)-len(k);s["forfeit"]["day"]=k;c.store.save(p,s)
 return "外した（%d 件）"%n if n else None
