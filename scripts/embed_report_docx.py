"""Make the local Word report portable: embed images and normalize local links."""
import argparse,zipfile
from pathlib import Path
from urllib.parse import urlparse,unquote
from lxml import etree as E
p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');a=p.parse_args();source=Path(a.input).resolve();target=Path(a.output).resolve()
with zipfile.ZipFile(source) as z:files={n:z.read(n) for n in z.namelist()}
REL='http://schemas.openxmlformats.org/package/2006/relationships';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
rels=E.fromstring(files['word/_rels/document.xml.rels']);doc=E.fromstring(files['word/document.xml']);ct=E.fromstring(files['[Content_Types].xml']);embedded=0
for rel in rels:
 path=rel.get('Target','');kind=rel.get('Type','')
 if kind.endswith('/image') and rel.get('TargetMode')=='External':
  parsed=urlparse(path);image=Path(unquote(parsed.path)) if parsed.scheme=='file' else (source.parent/unquote(path)).resolve()
  assert image.is_file(),image
  embedded+=1;name=f'quality-image-{embedded}'+image.suffix.lower();files['word/media/'+name]=image.read_bytes();rel.set('Target','media/'+name);rel.attrib.pop('TargetMode',None)
  rid=rel.get('Id')
  for blip in doc.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip'):
   if blip.get('{'+R+'}link')==rid:blip.attrib.pop('{'+R+'}link');blip.set('{'+R+'}embed',rid)
  ext=image.suffix.lstrip('.').lower()
  if not any(x.get('Extension')==ext for x in ct):E.SubElement(ct,'{'+REL.replace('relationships','content-types')+'}Default',Extension=ext,ContentType='image/png' if ext=='png' else 'image/jpeg')
 elif kind.endswith('/hyperlink') and rel.get('TargetMode')=='External' and path and not urlparse(path).scheme and not path.startswith('#'):
  rel.set('Target',(source.parent/unquote(path)).resolve().as_uri())
# Limit figures to the content width while preserving their actual aspect ratio.
ns={'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
maximum=int(6.7*914400)
for drawing in doc.findall('.//{'+W+'}drawing'):
 extent=drawing.find('.//wp:extent',ns)
 if extent is not None and int(extent.get('cx','0'))>maximum:
  ratio=maximum/int(extent.get('cx'));extent.set('cy',str(round(int(extent.get('cy'))*ratio)));extent.set('cx',str(maximum))
  for ext in drawing.findall('.//a:xfrm/a:ext',ns):ext.set('cx',extent.get('cx'));ext.set('cy',extent.get('cy'))
for section in doc.findall('.//{'+W+'}sectPr'):
 margins=section.find('{'+W+'}pgMar')
 if margins is not None:
  for key in ('top','bottom','left','right'):margins.set('{'+W+'}'+key,'850')
files['word/_rels/document.xml.rels']=E.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True);files['word/document.xml']=E.tostring(doc,xml_declaration=True,encoding='UTF-8',standalone=True);files['[Content_Types].xml']=E.tostring(ct,xml_declaration=True,encoding='UTF-8',standalone=True)
target.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
 for name,data in files.items():z.writestr(name,data)
print('Embedded actual figures:',embedded,'Word:',target)
