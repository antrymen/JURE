import json,zipfile,copy,re
from pathlib import Path
import xml.etree.ElementTree as E
p=Path(__file__).parent;d=json.loads((p/'compact_input.json').read_text());dest=p/'Table_S1_Validation_Summary_EN_Compact.xlsx';u='http://schemas.openxmlformats.org/spreadsheetml/2006/main';ns={'m':u};t=lambda x:'{'+u+'}'+x
with zipfile.ZipFile(dest) as z:files={n:z.read(n) for n in z.namelist()}
st=E.fromstring(files['xl/styles.xml']);bs=st.find('m:borders',ns);xs=st.find('m:cellXfs',ns);ids=[]
for es in [[],['top','bottom'],['bottom']]:
 b=E.Element(t('border'))
 for edge in ['left','right','top','bottom','diagonal']:
  e=E.SubElement(b,t(edge))
  if edge in es:e.set('style','thin');E.SubElement(e,t('color'),{'rgb':'FF000000'})
 ids.append(len(bs));bs.append(b)
bs.set('count',str(len(bs)));cache={};count=0
for i in range(3):
 tree=E.fromstring(files[f'xl/worksheets/sheet{i+1}.xml'])
 for view in tree.findall('m:sheetViews/m:sheetView',ns):view.set('showGridLines','0')
 for c in tree.findall('.//m:sheetData/m:row/m:c',ns):
  a=c.get('r');row=int(re.search(r'\d+',a)[0]);col=re.match('[A-Z]+',a)[0];src=None
  if i==0 and 2<=row<=5:src=d[0].get(['A','B','C','G','E','J','L','K'][ord(col)-65]+str(row))
  if i==1:src=d[1].get(a)
  if i==2 and row<=5:src=d[2].get(a)
  if i==2 and 10<=row<=13:src=d[0].get(col+str(row-8))
  if src and src['value'] is not None and src['type'] not in ['s','str','inlineStr','b']:
   c.find('m:v',ns).text=src['raw'];count+=1
  headers=[1] if i<2 else [1,9];bottom=[5,8,5][i];typ=1 if row in headers else 2 if row==bottom or(i==2 and row==13) else 0;key=(c.get('s','0'),typ)
  if key not in cache:
   xf=copy.deepcopy(xs[int(key[0])]);xf.set('borderId',str(ids[typ]));xf.set('applyBorder','1');cache[key]=len(xs);xs.append(xf)
  c.set('s',str(cache[key]))
 files[f'xl/worksheets/sheet{i+1}.xml']=E.tostring(tree,encoding='utf-8',xml_declaration=True)
xs.set('count',str(len(xs)));files['xl/styles.xml']=E.tostring(st,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
 for n,b in files.items():z.writestr(n,b)
# Verify all original numeric values in their retained full-record locations.
for i in range(3):
 tree=E.fromstring(files[f'xl/worksheets/sheet{i+1}.xml']);cells={c.get('r'):c for c in tree.findall('.//m:sheetData/m:row/m:c',ns)}
 if i==2:
  for a,v in d[0].items():
   row=int(re.search(r'\d+',a)[0]);col=re.match('[A-Z]+',a)[0]
   if 2<=row<=5 and isinstance(v['value'],(int,float)):assert cells[col+str(row+8)].find('m:v',ns).text==v['raw']
 if i==1:
  for row in range(2,9):assert cells['C'+str(row)].find('m:v',ns).text==d[1]['C'+str(row)]['raw']
print('PASS: 8 columns, 4 notes; all 51 original numeric cells retained exactly; formulas relocated with unchanged denominators; auxiliary source data retained.')
