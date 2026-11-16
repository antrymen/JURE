from pathlib import Path
import zipfile,xml.etree.ElementTree as E,html,hashlib
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table,TableStyle,Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from pypdf import PdfReader
root=Path('/Users/mac/Documents/ChatGPT/JURE');src=Path(__file__).parent/'Table_S1_Validation_Summary_EN_Compact.xlsx';out=root/'output/pdf/Table_S1.pdf';out.parent.mkdir(parents=True,exist_ok=True)
original=hashlib.sha256(src.read_bytes()).hexdigest();ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(src) as z:
 strings=[]
 if 'xl/sharedStrings.xml' in z.namelist():strings=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml'))]
 cells={}
 for c in E.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:sheetData/m:row/m:c',ns):
  v=c.find('m:v',ns);value=v.text if v is not None else ''
  if c.get('t')=='s':value=strings[int(value)]
  elif c.get('t')=='inlineStr':value=''.join(c.find('m:is',ns).itertext())
  cells[c.get('r')]=value
heads=[cells[f'{col}1'] for col in 'ABCDEFGH'];rows=[]
for i in range(2,6):
 vals=[]
 for col in 'ABCDEFGH':
  v=cells[col+str(i)]
  if col=='A':vals.append(v)
  elif col in 'BCF':vals.append(f'{float(v):,.0f}')
  elif col in 'DGH':vals.append(f'{float(v):.2%}')
  else:vals.append(f'{float(v):.3f}')
 rows.append(vals)
fontdir=Path('/Users/mac/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources/fonts/truetype')
for name,file in [('DV','DejaVuSans.ttf'),('DV-Bold','DejaVuSans-Bold.ttf')]:pdfmetrics.registerFont(TTFont(name,str(fontdir/file)))
style=ParagraphStyle('header',fontName='DV-Bold',fontSize=7.3,leading=9,alignment=1)
widths=[77,45,49,65,48,87,66,65];margin=3
table=Table([[Paragraph(html.escape(h),style) for h in heads]]+rows,colWidths=widths,rowHeights=[35,23,23,23,23])
table.setStyle(TableStyle([('FONTNAME',(0,1),(-1,-1),'DV'),('FONTSIZE',(0,1),(-1,-1),8),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(1,1),(-1,-1),'RIGHT'),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),('BACKGROUND',(0,0),(-1,-1),colors.white),('LINEABOVE',(0,0),(-1,0),.65,colors.black),('LINEBELOW',(0,0),(-1,0),.45,colors.black),('LINEBELOW',(0,-1),(-1,-1),.65,colors.black)]))
w,h=table.wrap(1000,1000);c=canvas.Canvas(str(out),pagesize=(w+2*margin,h+2*margin));c.setTitle('Table S1');table.drawOn(c,margin,margin);c.save()
pdf=PdfReader(out);assert len(pdf.pages)==1;page=pdf.pages[0];text=page.extract_text();normal=' '.join(text.split())
for h in heads:assert ' '.join(h.split()) in normal,h
for row in rows:
 for val in row:assert val in text,val
assert 'Table Notes' not in text and 'Supplementary' not in text
assert not list(page.images)
assert hashlib.sha256(src.read_bytes()).hexdigest()==original
print('PASS: 8 headers, 4 rows, vector text, no raster images, no title/notes; source unchanged.');print(out)
