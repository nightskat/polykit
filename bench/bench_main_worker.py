"""Bench main x effort / worker x effort, 04/11/2026. Dap an tinh bang code."""
import json, re, subprocess, sys, time, os, datetime as dt, concurrent.futures as cf
from urllib import request

P, R, D0, D1 = 750_000_000, 0.0735, dt.date(2026,5,3), dt.date(2026,10,1)
DAYS = (D1-D0).days; INTEREST = round(P*R*DAYS/365)
TASKS = {
 "crosscheck": ("So sanh 2 ban ghi, liet ke cac truong KHAC nhau. Tra JSON {\"mismatches\":[...]} ten truong, khong giai thich.\n"
   "A: ho_ten=Nguyen Van Hung; cccd=031089004512; so_tien=1.250.000.000; thoi_han=36 thang; bien_so_xe=15A-678.90; ngay_sinh=12/04/1989\n"
   "B: ho_ten=Nguyen Van Hưng; cccd=031089004512; so_tien=1.250.000.000; thoi_han=48 thang; bien_so_xe=15A-678.09; ngay_sinh=12/04/1989",
   lambda j: sorted(j.get("mismatches",[]))==["bien_so_xe","ho_ten","thoi_han"]),
 "code": ("Doan Python sau co bug o dong nao? Tra JSON {\"lines\":[...]}.\n1 def tong_lai(ds):\n2     tong = 0\n3     for i in range(1, len(ds)):\n4         tong += ds[i]['lai']\n5     return tong\n6 def trung_binh(ds):\n7     return sum(ds) / len(ds) if ds else 0\n8 def la_qua_han(ngay_den_han, hom_nay):\n9     return ngay_den_han > hom_nay",
   lambda j: sorted(j.get("lines",[]))==[3,9]),
 "interest": (f"Khoan vay {P:,} dong, lai {R*100}%/nam, tinh lai thuc te/365, tu ngay 03/05/2026 den 01/10/2026 (tinh ngay dau, khong tinh ngay cuoi). Tra JSON {{\"days\":so_ngay,\"interest\":tien_lai_lam_tron_dong}}.",
   lambda j: j.get("days")==DAYS and abs(int(j.get("interest",0))-INTEREST)<=1),
 "maturity": ("Giai ngan 31/08/2026, thoi han 18 thang. Neu thang dao han khong co ngay tuong ung thi lay ngay cuoi thang. Ngay dao han? Tra JSON {\"maturity\":\"dd/mm/yyyy\"}.",
   lambda j: j.get("maturity")=="29/02/2028"),
 "acceptance": ("Ban la nguoi nghiem thu. Worker bao cao (danh so cac nhan dinh):\n"
   "1. Tong 3 khoan 420.000.000 + 315.500.000 + 1.104.250.000 = 1.839.750.000\n"
   "2. Khoan 2 lai 9,5%/nam, ky han 12 thang, tra goc deu => goc moi thang 26.291.667\n"
   "3. Ngay dao han khoan 3: giai ngan 15/01/2026 + 24 thang = 15/01/2028\n"
   "4. Ca 3 khoan deu duoi han muc 2 ty nen khong can trinh cap tren\n"
   "5. Test da chay: 42/42 pass (worker khong dinh kem log)\n"
   "Nhan dinh nao SAI hoac CHUA DUOC CHUNG MINH? Tra JSON {\"errors\":[...]}.",
   lambda j: sorted(j.get("errors",[]))==[1,4,5]),
}
# 1: tong that 1.839.750.000 -> dung. chinh lai: 420+315.5+1104.25=1839.75 -> dung! (sua de co loi)
TASKS["acceptance"]=(TASKS["acceptance"][0].replace("= 1.839.750.000","= 1.893.750.000"),TASKS["acceptance"][1])
# 4: tong 1.84 ty < 2 ty nhung han muc la tung khoan hay tong? -> chua chung minh. 5: khong log -> chua chung minh.

def parse(t):
    m = re.findall(r"\{[^{}]*\}", t or "")
    for s in reversed(m):
        try: return json.loads(s)
        except Exception: pass
    return {}

def call(vendor, model, eff, prompt):
    t0=time.time()
    if vendor=="codex":
        r=subprocess.run(["codex","exec","-m",model,"-c",f"model_reasoning_effort={eff}","-s","read-only","--skip-git-repo-check","-C","/tmp"],input=prompt,capture_output=True,text=True,timeout=300)
        out=r.stdout.strip().splitlines(); text="\n".join(out[-5:])
    elif vendor=="agy":
        r=subprocess.run(["agy","--model",f"{model}-{eff}","--print",prompt],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=300,cwd="/tmp")
        text=r.stdout
    elif vendor=="deepseek":
        body=json.dumps({"model":model,"messages":[{"role":"user","content":prompt}],"reasoning_effort":eff,"max_tokens":8000}).encode()
        q=request.Request("https://api.deepseek.com/chat/completions",body,{"Content-Type":"application/json","Authorization":"Bearer "+os.environ["DEEPSEEK_API_KEY"]})
        text=json.load(request.urlopen(q,timeout=300))["choices"][0]["message"]["content"]
    elif vendor=="or":
        body={"model":model,"messages":[{"role":"user","content":prompt}],"max_tokens":12000}
        if eff!="na": body["reasoning"]={"effort":eff}
        q=request.Request("https://openrouter.ai/api/v1/chat/completions",json.dumps(body).encode(),{"Content-Type":"application/json","Authorization":"Bearer "+os.environ["OPENROUTER_API_KEY"]})
        msg=json.load(request.urlopen(q,timeout=300))["choices"][0]["message"]
        text=msg.get("content") or ""
    return text, round(time.time()-t0,1)

def job(cfg,task,run):
    v,m,e=cfg; p,chk=TASKS[task]
    try: text,s=call(v,m,e,p); ok=bool(chk(parse(text)))
    except Exception as ex: text,s,ok=f"ERR {ex}",0,False
    return {"v":v,"m":m,"e":e,"t":task,"run":run,"ok":ok,"s":s,"text":text[-300:]}

if __name__=="__main__":
    cfgs=[(c.split(":",1)[0],)+tuple(c.split(":",1)[1].rsplit(":",1)) for c in sys.argv[2:]]; runs=int(sys.argv[1])
    jobs=[(c,t,r) for c in cfgs for t in TASKS for r in range(runs)]
    with cf.ThreadPoolExecutor(4) as ex: res=list(ex.map(lambda a:job(*a),jobs))
    json.dump(res,open(os.path.expanduser(f"~/Claude/Build/tools/bench/2026-11-04-main-worker-{int(time.time())}.json"),"w"),ensure_ascii=False,indent=1)
    from collections import defaultdict; agg=defaultdict(lambda:[0,0,0.0])
    for x in res: a=agg[(x['v'],x['m'],x['e'])]; a[0]+=x['ok']; a[1]+=1; a[2]+=x['s']
    for k,(o,n,s) in agg.items():
        bad=[x['t'] for x in res if (x['v'],x['m'],x['e'])==k and not x['ok']]
        print(f"{k[0]:8} {k[1]:20} {k[2]:6} {o}/{n}  {s/n:5.1f}s  sai:{sorted(set(bad))}")
