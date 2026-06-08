"""Consolidate ALL angle records from the session transcript -> full fin_exemplars.sqlite + KG (option-C dual layer).
Run: python3 fin_kb/build_full.py
"""
import json, sqlite3, collections, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TX = Path.home() / ".claude/projects/-Users-yuncongliu/63818b1e-a920-4535-8579-8fa59f4f39b0.jsonl"
OUTJ = ROOT / "fin_kb/exemplars_full.json"
DB = ROOT / "fin_kb/fin_exemplars.sqlite"

FIN_PROPS = {"non-stationarity","heavy-tails","no-arbitrage-accounting","microstructure",
             "pit-restatement","cross-sectional-dependence","regime"}

def texts_from(obj):
    out=[]; msg=obj.get("message",{}); c=msg.get("content")
    if isinstance(c,str): out.append(c)
    elif isinstance(c,list):
        for b in c:
            if not isinstance(b,dict): continue
            if b.get("type")=="text": out.append(b.get("text",""))
            tr=b.get("content")
            if isinstance(tr,str): out.append(tr)
            elif isinstance(tr,list):
                for x in tr:
                    if isinstance(x,dict) and x.get("type")=="text": out.append(x.get("text",""))
    tur=obj.get("toolUseResult")
    if isinstance(tur,str): out.append(tur)
    elif isinstance(tur,dict):
        for v in tur.values():
            if isinstance(v,str): out.append(v)
            elif isinstance(v,list):
                for x in v:
                    if isinstance(x,dict) and x.get("type")=="text": out.append(x.get("text",""))
    return out

def extract_arrays(text):
    res=[]; i=0; n=len(text)
    while i<n:
        if text[i]=='[':
            depth=0; j=i; instr=False; esc=False
            while j<n:
                ch=text[j]
                if esc: esc=False
                elif ch=='\\': esc=True
                elif ch=='"': instr=not instr
                elif not instr:
                    if ch=='[': depth+=1
                    elif ch==']':
                        depth-=1
                        if depth==0:
                            chunk=text[i:j+1]
                            if '"slug"' in chunk and '"publishable_shape"' in chunk:
                                try: res.append(json.loads(chunk))
                                except: pass
                            i=j; break
                j+=1
        i+=1
    return res

recs={}
for line in open(TX):
    line=line.strip()
    if not line: continue
    try: obj=json.loads(line)
    except: continue
    for t in texts_from(obj):
        if '"publishable_shape"' not in t: continue
        for arr in extract_arrays(t):
            for r in arr:
                if isinstance(r,dict) and r.get("slug"): recs[r["slug"]]=r

# normalize + filter non-papers
clean=[]
for r in recs.values():
    if r["slug"].startswith("proceedings-of-the"): continue
    if "N/A" in str(r.get("one_liner","")) or "SKIPPED" in str(r.get("one_liner","")): continue
    r["publishable_shape"]=str(r.get("publishable_shape","")).split()[0] if r.get("publishable_shape") else "?"
    r["finance_property"]=str(r.get("finance_property","none-generic")).strip().lower()
    r["label_type"]=str(r.get("label_type","other")).strip()
    clean.append(r)

# option-C strict tier
def strict_eval(r):
    named=r["finance_property"] in FIN_PROPS
    nonret=r["label_type"]!="return-SNR"
    noopt=str(r.get("has_classical_optimum","")).strip().lower().startswith("no")
    p=sum([named,nonret,noopt]); fails=[n for n,ok in [("named-finance",named),("non-return",nonret),("no-classical-optimum",noopt)] if not ok]
    return ("strong" if p==3 else "borderline" if p==2 else "weak"), ",".join(fails)
for r in clean:
    r["strict_tier"],r["strict_fails"]=strict_eval(r)

OUTJ.write_text(json.dumps(clean,ensure_ascii=False,indent=0),encoding="utf-8")
cols=["slug","title","venue","year","mode","one_liner","publishable_shape","finance_property","ai_mechanism",
      "target_quantity","label_type","has_classical_optimum","incumbent_beaten","novelty_angle","data_used",
      "why_accepted","confidence","strict_tier","strict_fails"]
con=sqlite3.connect(DB); con.execute("DROP TABLE IF EXISTS fin_exemplars")
con.execute(f"CREATE TABLE fin_exemplars ({','.join(c+' TEXT' for c in cols)})")
con.executemany(f"INSERT INTO fin_exemplars VALUES ({','.join('?'*len(cols))})",
                [[str(r.get(c,"")) for c in cols] for r in clean]); con.commit()

def dist(k,f=lambda x:x): return collections.Counter(f(r.get(k,"?")) for r in clean).most_common()
print(f"=== FULL fin_exemplars: {len(clean)} papers -> {DB.name} ===\n")
print("publishable_shape:", dist("publishable_shape"))
print("label_type:       ", dist("label_type"))
print("has_classical_opt:", dist("has_classical_optimum", lambda x:x.split(" —")[0].split(" -")[0].strip().lower()[:7]))
print("finance_property: ", dist("finance_property"))
print("venue:            ", dist("venue", lambda x: x[:24]))
named=[r for r in clean if r["finance_property"] in FIN_PROPS]
print(f"\nNAMED finance_property: {len(named)}/{len(clean)} ({len(named)/len(clean)*100:.0f}%)  | none-generic: {len(clean)-len(named)}")
print("OPTION-C strict_tier:", dist("strict_tier"))
print("strict_fails:        ", collections.Counter(f for r in clean for f in (r["strict_fails"].split(",") if r["strict_fails"] else [])).most_common())
strong=[r for r in clean if r["strict_tier"]=="strong"]
print(f"\nSTRONG-tier exemplars (pass all 3: named-finance + non-return + no-classical-optimum) = {len(strong)}:")
for r in strong:
    print(f"  · [{r['publishable_shape']}|{r['label_type']}|{r['finance_property']}] {r['title'][:54]}")
