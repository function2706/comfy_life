import time
ID="20261122_appoint_late_restore";DESC="11/22消えた約束を19:30に戻す"
DAY0=time.mktime((2026,11,22,0,0,0,0,0,-1));NEW_T=UNTIL=DAY0+70200
def apply(c):
 b=None
 for w in c.worlds():
  ps=c.store.load(c.store.dpath("worlds",w,"player.json"),None)or{}
  for x in ps.get("appoints")or[]:
   if x.get("status")=="missed"and not(x.get("plan")or{}).get("noshow")and DAY0<=x.get("t",0)<NEW_T and not any(x.get(k)for k in("favor","plants","care","help"))and(b is None or x["t"]>b[2]["t"]):b=(w,ps,x)
 if not b:return None
 w,ps,x=b;t0,p0=x["t"],x.get("place");pr=ps.get("presence")or{}
 if pr.get("mode")=="out"and pr.get("place")and not pr.get("travel"):x["place"]=pr["place"]
 x.update(t=NEW_T,status="set",plan={"noshow":False,"late":0,"cancel_checked":True,"move":False,"go":0});x.pop("arrived",None)
 c.store.save(c.store.dpath("worlds",w,"player.json"),ps)
 sp=c.store.dpath("worlds",w,"state",x["cid"]+".json");st=c.store.load(sp,None);m=0
 if st:
  for r in st.get("reasons")or[]:
   if r.get("action")=="_appoint"and"すっぽかした"in str(r.get("tell"))and abs(r.get("t",0)-t0)<10800 and not r.get("resolved"):r["resolved"]=True;m-=r.get("delta")or 0
  m=m or 8;pa=st.setdefault("params",{})
  for k,v in(("mood",m),("trust",4),("affection",2)):
   if k in pa:pa[k]=round(max(0,min(100,pa[k]+v)),2)
  g=st.get("regard")
  if g and"v"in g:g["v"]=round(min(100,g["v"]+5),2)
  c.store.save(sp,st)
 cp=c.store.dpath("worlds",w,"chats",x["cid"]+".json");ch=c.store.load(cp,None)
 if ch is not None:ch.setdefault("items",[]).append({"who":"sys","kind":"promise","t":time.time(),"text":"📅 約束し直した: 今日 19:30"});c.store.save(cp,ch)
 return "%s→19:30 %s→%s 機嫌+%.0f"%(time.strftime("%H:%M",time.localtime(t0)),p0,x["place"],m)
