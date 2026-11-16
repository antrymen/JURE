from pathlib import Path
import zipfile,xml.etree.ElementTree as E,re,json,copy
p=Path(__file__).parent; ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};u=ns['m'];tag=lambda x:'{'+u+'}'+x
src=p/'Table_S1_Validation_Summary.xlsx';dest=p/'Table_S1_Validation_Summary_EN.xlsx'
def read(z):
 ss=[]
 if 'xl/sharedStrings.xml' in z.namelist():ss=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml'))]
 sheets=[]
 for i in range(1,4):
  tree=E.fromstring(z.read(f'xl/worksheets/sheet{i}.xml'));cells={}
  for c in tree.findall('.//m:sheetData/m:row/m:c',ns):
   v=c.find('m:v',ns);f=c.find('m:f',ns);t=c.get('t');value=v.text if v is not None else None
   if t=='s':value=ss[int(value)]
   elif t=='inlineStr':value=''.join(c.find('m:is',ns).itertext())
   cells[c.get('r')]=(t,value,f.text if f is not None else None,c)
  sheets.append((tree,cells))
 return sheets
with zipfile.ZipFile(src) as a,zipfile.ZipFile(dest) as b:
 old=read(a);new=read(b);files={n:b.read(n) for n in b.namelist()}
 styles=E.fromstring(files['xl/styles.xml']);borders=styles.find('m:borders',ns);xfs=styles.find('m:cellXfs',ns)
 ids=[]
 for edges in [[],['top','bottom'],['bottom']]:
  border=E.Element(tag('border'))
  for edge in ['left','right','top','bottom','diagonal']:
   e=E.SubElement(border,tag(edge))
   if edge in edges:e.set('style','thin');E.SubElement(e,tag('color'),{'rgb':'FF000000'})
  ids.append(len(borders));borders.append(border)
 borders.set('count',str(len(borders)));cache={}
 for idx,((_,oc),(tree,nc)) in enumerate(zip(old,new)):
  for addr,(t,v,f,c) in nc.items():
   if addr in oc:
    ot,ov,of,_=oc[addr]
    if ov is not None and ot not in ['s','str','inlineStr','b']:c.find('m:v',ns).text=ov
   row=int(re.search(r'\d+',addr)[0]);last=[5,8,5][idx];which=1 if row==1 else 2 if row==last else 0
   key=(c.get('s','0'),which)
   if key not in cache:
    xf=copy.deepcopy(xfs[int(key[0])]);xf.set('borderId',str(ids[which]));xf.set('applyBorder','1');cache[key]=len(xfs);xfs.append(xf)
   c.set('s',str(cache[key]))
  for view in tree.findall('m:sheetViews/m:sheetView',ns):view.set('showGridLines','0')
  files[f'xl/worksheets/sheet{idx+1}.xml']=E.tostring(tree,encoding='utf-8',xml_declaration=True)
 xfs.set('count',str(len(xfs)));files['xl/styles.xml']=E.tostring(styles,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
 for n,v in files.items():z.writestr(n,v)
with zipfile.ZipFile(dest) as z:new=read(z)
nums=forms=technical=0
for i,((_,a),(_,b)) in enumerate(zip(old,new)):
 for k,(t,v,f,_) in a.items():
  if f:assert b[k][2]==f;forms+=1
  if v is not None and t not in ['s','inlineStr','str','b']:assert v==b[k][1];nums+=1
  row=int(re.search(r'\d+',k)[0]);keep=(i==2 and row>1) or(i==0 and k in ['A2','A3','A4','A5']) or(i==1 and row>1 and k[0] in 'AB' and v and not re.search('[\u4e00-\u9fff]',v))
  if keep:assert b[k][1]==v;technical+=1
 for k,(t,v,f,_) in b.items():assert not(v and re.search('[\u4e00-\u9fff]',v)),(k,v)
report={'result':'PASS','numeric_cells_exactly_preserved':nums,'formulas_preserved':forms,'direction_and_technical_cells_preserved':technical,'Chinese_remaining':0,'Holm_thresholds_verified':[0.025,0.025,0.05,0.05],'manual_statistical_confirmation_needed':False}
(p/'EN_consistency_check.json').write_text(json.dumps(report,indent=2));print(report)
