"""Professional local PDF reports from a calculated Steel Studio snapshot.

The report consumes the same member coordinates, assignments and quantities as
the UI. Its required 3D PNG comes from a clean render of that snapshot.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime
from io import BytesIO
import math
from pathlib import Path
import re
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


PAGE_W, PAGE_H = landscape(letter)
MARGIN = 40
CONTENT_W = PAGE_W - MARGIN * 2
INK = colors.HexColor('#17374b')
MUTED = colors.HexColor('#657f90')
LINE = colors.HexColor('#d7e2e9')
PALE = colors.HexColor('#f1f5f8')
TEAL = colors.HexColor('#367f89')
BLUE = colors.HexColor('#597caa')
GOLD = colors.HexColor('#b68853')


def clean(value):
    return str(value if value is not None else '').replace('\u2014', '-').replace('\u2013', '-').replace('\u2011', '-').replace('\x00', '')


def number(value, digits=2):
    return f'{float(value or 0):,.{digits}f}'.rstrip('0').rstrip('.') if digits else f'{float(value or 0):,.0f}'


def letter_label(index):
    out = ''
    index += 1
    while index:
        index, char = divmod(index - 1, 26)
        out = chr(65 + char) + out
    return out


def validate_image(data_url):
    if not isinstance(data_url, str) or not data_url.startswith('data:image/png;base64,'):
        raise ValueError('A PNG rendering of the 3D model is required for the report.')
    try:
        data = base64.b64decode(data_url.split(',', 1)[1], validate=True)
        if len(data) > 12 * 1024 * 1024:
            raise ValueError('The 3D report image is too large.')
        with PILImage.open(BytesIO(data)) as image:
            if image.format != 'PNG' or not 600 <= image.width <= 5000 or not 300 <= image.height <= 3000 or image.width * image.height > 12_000_000:
                raise ValueError('The report image must be a PNG between 600 x 300 and 5000 x 3000 pixels.')
            image.verify()
    except (OSError, SyntaxError, base64.binascii.Error) as exc:
        raise ValueError('The 3D model image could not be read.') from exc
    return data


def report_options(raw):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError('Report details must be an object.')
    result = {}
    for key, default, limit in [('company', 'ARCO', 70), ('prepared_by', '', 80), ('project_number', '', 60), ('revision', '01', 30), ('issue', 'For quantity review', 70)]:
        result[key] = clean(raw.get(key, default)).strip()[:limit]
    result['include_members'] = raw.get('include_members') is True
    return result


def fonts():
    if 'Studio' not in pdfmetrics.getRegisteredFontNames():
        regular = Path('C:/Windows/Fonts/segoeui.ttf')
        bold = Path('C:/Windows/Fonts/segoeuib.ttf')
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont('Studio', str(regular)))
            pdfmetrics.registerFont(TTFont('Studio-Bold', str(bold)))
        else:
            return 'Helvetica', 'Helvetica-Bold'
    return 'Studio', 'Studio-Bold'


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved_pages = []

    def showPage(self):
        self.saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self.saved_pages)
        for state in self.saved_pages:
            self.__dict__.update(state)
            self.setFont('Helvetica', 8)
            self.setFillColor(MUTED)
            self.drawRightString(PAGE_W - MARGIN, 24, f'{self._pageNumber:02d} / {total:02d}')
            super().showPage()
        super().save()


class SteelReport:
    def __init__(self, model, image, options):
        self.model, self.project, self.options = model, model['project'], options
        self.image = ImageReader(BytesIO(image))
        self.buffer = BytesIO()
        self.c = NumberedCanvas(self.buffer, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
        self.font, self.bold = fonts()
        self.generated = datetime.now().astimezone().strftime('%d %b %Y, %H:%M %Z')
        self.title = clean(self.project.get('name') or 'Structural steel project')
        self.c.setTitle(f'{self.title} - Structural Steel Takeoff')
        self.c.setAuthor(options['prepared_by'] or options['company'])
        self.c.setSubject('Calculated steel, pad footing and gross wall takeoff with 3D model')
        self.c.setCreator('Steel Studio')
        self.pages = 0
        self.y = 480

    def text(self, text, x, y, size=9, color=INK, bold=False, width=None, align='left'):
        font = self.bold if bold else self.font
        value = clean(text)
        if width:
            while value and pdfmetrics.stringWidth(value, font, size) > width:
                value = value[:-2].rstrip() + '.'
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        fn = self.c.drawRightString if align == 'right' else self.c.drawCentredString if align == 'center' else self.c.drawString
        fn(x, y, value)

    def paragraph(self, text, x, top, width, size=9, color=MUTED, leading=None, bold=False):
        style = ParagraphStyle('report', fontName=self.bold if bold else self.font, fontSize=size, leading=leading or size*1.45, textColor=color, alignment=TA_LEFT)
        p = Paragraph(escape(clean(text)).replace('\n', '<br/>'), style)
        _, height = p.wrap(width, 2000)
        p.drawOn(self.c, x, top - height)
        return height

    def rule(self, x, y, width, color=LINE):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(.5)
        self.c.line(x, y, x+width, y)

    def page(self, heading, kicker='STRUCTURAL STEEL TAKEOFF', subtitle=''):
        if self.pages:
            self.c.showPage()
        self.pages += 1
        self.text(self.options['company'] or 'STEEL STUDIO', MARGIN, PAGE_H-30, 11, bold=True, width=230)
        self.text(self.title, PAGE_W-MARGIN, PAGE_H-30, 8, MUTED, width=390, align='right')
        self.rule(MARGIN, PAGE_H-44, CONTENT_W)
        self.text(kicker, MARGIN, PAGE_H-65, 8, TEAL, bold=True)
        height = self.paragraph(heading, MARGIN, PAGE_H-76, CONTENT_W, 22, INK, 27, True)
        self.y = PAGE_H-81-height
        if subtitle:
            self.y -= self.paragraph(subtitle, MARGIN, self.y, CONTENT_W, 9)+10
        else:
            self.y -= 12
        self.rule(MARGIN, 41, CONTENT_W)
        self.text(f'Rev {self.options["revision"] or "-"}  |  {self.options["issue"]}', MARGIN, 24, 7.5, MUTED, width=410)
        self.text('Steel Studio', PAGE_W-112, 24, 7.5, MUTED, align='right')

    def section(self, heading):
        self.text(heading, MARGIN, self.y, 11, bold=True)
        self.y -= 17

    def table(self, headings, rows, widths, *, continuation='Schedule - continued', size=8.2):
        def header():
            self.c.setFillColor(INK)
            self.c.rect(MARGIN, self.y-26, sum(widths), 26, fill=1, stroke=0)
            x = MARGIN
            for title, width in zip(headings, widths):
                self.paragraph(title, x+8, self.y-6, width-16, 7.7, colors.white, 10, True)
                x += width
            self.y -= 26
        if self.y < 115:
            self.page(continuation)
        header()
        for index, row in enumerate(rows):
            cells = []
            for value, width in zip(row, widths):
                p = Paragraph(escape(clean(value)), ParagraphStyle('cell', fontName=self.font, fontSize=size, leading=size*1.4, textColor=INK))
                _, height = p.wrap(width-16, 1000)
                cells.append((p, height))
            height = max([h for _, h in cells] + [12]) + 14
            if self.y-height < 61:
                self.page(continuation)
                header()
            if index % 2 == 0:
                self.c.setFillColor(PALE)
                self.c.rect(MARGIN, self.y-height, sum(widths), height, fill=1, stroke=0)
            x = MARGIN
            for (p, h), width in zip(cells, widths):
                p.drawOn(self.c, x+8, self.y-7-h)
                x += width
            self.rule(MARGIN, self.y-height, sum(widths))
            self.y -= height
        self.y -= 18

    def metrics(self, items, x, y, width, height=57):
        cell = width/len(items)
        for i, (label, value, unit) in enumerate(items):
            bx=x+i*cell
            self.c.setFillColor(PALE)
            self.c.roundRect(bx, y, cell-8, height, 4, fill=1, stroke=0)
            self.text(label, bx+10, y+height-15, 7.5, MUTED, width=cell-24)
            self.text(f'{value} {unit}', bx+10, y+14, 15, INK, True, width=cell-24)

    def cover(self):
        o, s, tf = self.options, self.model['summary'], self.model['takeoffs']
        self.page(self.title, 'STRUCTURAL STEEL / TAKEOFF REPORT', f'{o["issue"]}   |   Revision {o["revision"]}   |   {self.generated}')
        meta = []
        if o['project_number']:
            meta.append(f'Project no. {o["project_number"]}')
        if o['prepared_by']:
            meta.append(f'Prepared by {o["prepared_by"]}')
        if meta:
            self.text('   |   '.join(meta), MARGIN, self.y, 9, MUTED, width=CONTENT_W)
            self.y -= 17
        self.text('3D structural model', MARGIN, self.y, 11, bold=True)
        image_top = self.y-13
        image_bottom = 160
        self.c.drawImage(self.image, MARGIN, image_bottom, width=CONTENT_W, height=image_top-image_bottom, preserveAspectRatio=True, anchor='c', mask='auto')
        legend = [('Joists', TEAL), ('Girders', BLUE), ('Columns', GOLD)]
        for i, (label, color) in enumerate(legend):
            x = MARGIN+i*86
            self.c.setFillColor(color)
            self.c.rect(x, 147, 12, 3, stroke=0, fill=1)
            self.text(label, x+18, 145, 8, MUTED)
        self.text('Southeast view | North arrow shown | Steel framing only', PAGE_W-MARGIN, 145, 8, MUTED, align='right')
        pads = sum(tf[k]['summary'].get('total_cy_with_waste', 0) for k in ['footings', 'mezzanine_footings'])
        self.metrics([('Active footprint', number(s['floor_area_sf'],0), 'sf'), ('Selected steel', number(s['weight_tons']), 'tons'), ('Pad concrete + waste', number(pads), 'CY'), ('Gross wall area', number(tf['walls']['summary']['total_area_sf'],0), 'sf')], MARGIN, 73, CONTENT_W, 57)
        self.text('Schematic takeoff model. Member capacity, connections and lateral stability are not verified.', MARGIN, 54, 7.8, MUTED)

    def basis(self):
        p, s = self.project, self.model['summary']
        self.page('Design basis & quantity summary', subtitle='Calculated values from the same saved design snapshot as the model and drawings.')
        loads=p['load_inputs_psf']
        rows=[['Building envelope', f'{number(self.model["grid"]["width_ft"])} x {number(self.model["grid"]["length_ft"])} ft', 'Clear height', f'{number(p["clear_height_ft"])} ft'],
              ['Roof', p['roof_type'], 'Roof calculation', 'Original slope / clear-height rules' if p['roof_calculation_mode']=='original' else 'Explicit eave / rise'],
              ['Dead / live load', f'{number(loads["dead_load_psf"])} / {number(loads["live_load_psf"])} psf', 'Ground snow load', f'{number(loads["snow_load_psf"])} psf'],
              ['Collateral addition', f'{number(loads["collateral_addition_psf"])} psf', 'Snow basis', loads.get('snow_code','ASCE 7-16')],
              ['Bearing capacity', f'{number(p["bearing_capacity_psf"],0)} psf', 'Pad depth', f'{number(p["footing_depth_ft"])} ft']]
        self.table(['Input','Value','Input','Value'], rows, [138,218,138,218])
        self.section('Steel quantities by building level')
        rows=[]
        for level, label in [('roof','Main / roof'),('mezzanine','Mezzanine')]:
            members=[m for m in self.model['members'] if m['level']==level]
            if not members:
                continue
            weights=[sum(m['weight_lbs'] or 0 for m in members if m['type']==kind)/2000 for kind in ['joist','girder','column']]
            rows.append([label, str(len(members)), *[number(w,3) for w in weights], number(sum(weights),3)])
        rows.append(['TOTAL', str(s['member_count']), *[number(sum(m['weight_lbs'] or 0 for m in self.model['members'] if m['type']==kind)/2000,3) for kind in ['joist','girder','column']], number(s['weight_tons'],3)])
        self.table(['Level','Members','Joists (tons)','Girders (tons)','Columns (tons)','Total (tons)'],rows,[160,72,120,120,120,120])
        notes=[f'{s["selected_count"]} assigned members; {s["unassigned_count"]} unassigned. Unassigned members contribute no steel weight.',
               'Joist and girder weights use plan spans; column weights use modeled height. Connections, deck, bridging and miscellaneous steel are excluded.',
               'Automatic choices follow the original catalog workflow and remain unchecked. Footings use the original bearing-area method; wall area is the gross exterior envelope.']
        if s.get('unknown_weight_count'):
            notes.insert(1,f'{s["unknown_weight_count"]} members have unknown unit weight.')
        if loads.get('snow_code')=='ASCE 7-22':
            notes.append(f'Manual reduced snow load: {number(loads.get("reduced_snow_load_psf_manual",0))} psf.')
        for note in notes:
            self.y -= self.paragraph(note,MARGIN,self.y,CONTENT_W,8.5)+6

    def plan(self, box, *, zone=None):
        """Draw north-up plans directly from calculated X/Y coordinates."""
        bx,by,bw,bh=box
        grid=self.model['grid']
        xs,ys=grid['x_lines_ft'],grid['y_lines_ft']
        if zone:
            source=next(z for z in self.project['mezzanines'] if z['id']==zone['zone_id'])
            from steel_model import _zone_nodes
            xs,ys=_zone_nodes(self.project,zone)
            members=[m for m in self.model['members'] if m['demand'].get('zone_id')==zone['zone_id']]
        else:
            source=None
            members=[m for m in self.model['members'] if m['level']=='roof']
        x0,x1,y0,y1=xs[0],xs[-1],ys[0],ys[-1]
        scale=min((bw-65)/max(x1-x0,1),(bh-60)/max(y1-y0,1))
        left=bx+(bw-(x1-x0)*scale)/2
        top=by+bh-(bh-(y1-y0)*scale)/2
        X=lambda v:left+(v-x0)*scale
        Y=lambda v:top-(v-y0)*scale
        self.c.setFillColor(colors.HexColor('#fafcfd'))
        self.c.setStrokeColor(LINE)
        self.c.rect(X(x0),Y(y1),(x1-x0)*scale,(y1-y0)*scale,fill=1,stroke=1)
        if not zone:
            for b in self.project['inactive_bays']:
                ix=int(b['x_bay'])-1
                iy=next((i for i in range(len(ys)-1) if letter_label(i)==b['y_bay']),-1)
                if not (0<=ix<len(xs)-1 and 0<=iy<len(ys)-1):continue
                self.c.setFillColor(colors.HexColor('#dde3e8'))
                self.c.rect(X(xs[ix]),Y(ys[iy+1]),(xs[ix+1]-xs[ix])*scale,(ys[iy+1]-ys[iy])*scale,fill=1,stroke=0)
            self.c.setFillColor(colors.HexColor('#dcecf3'))
            for mz in self.model['results']['mezzanine']['mezzanine_zones']:
                from steel_model import _zone_nodes
                zx,zy=_zone_nodes(self.project,mz)
                self.c.rect(X(zx[0]),Y(zy[-1]),(zx[-1]-zx[0])*scale,(zy[-1]-zy[0])*scale,fill=1,stroke=0)
        self.c.setStrokeColor(LINE)
        self.c.setLineWidth(.4)
        x_step=max(1,math.ceil((len(xs)-1)/16))
        y_step=max(1,math.ceil((len(ys)-1)/12))
        for i,x in enumerate(xs):
            self.c.line(X(x),Y(y0)+7,X(x),Y(y1))
            if i % x_step == 0 or i==len(xs)-1:
                self.text(str(i+1),X(x),Y(y0)+13,8,MUTED,align='center')
            if i<len(xs)-1 and (xs[i+1]-x)*scale>24:
                self.text(number(xs[i+1]-x),X((x+xs[i+1])/2),Y(y0)+3,6.7,MUTED,align='center')
        for i,y in enumerate(ys):
            self.c.line(X(x0)-7,Y(y),X(x1),Y(y))
            if i % y_step == 0 or i==len(ys)-1:
                self.text(letter_label(i),X(x0)-13,Y(y)-3,8,MUTED,align='center')
        # Draw structure with no member IDs; tables carry the identification.
        for m in sorted(members,key=lambda m:m['type']=='column'):
            a,b=m['start'],m['end']
            if m['type']=='column':
                self.c.setFillColor(GOLD)
                self.c.rect(X(a[0])-1.7,Y(a[1])-1.7,3.4,3.4,fill=1,stroke=0)
            else:
                self.c.setStrokeColor(TEAL if m['type']=='joist' else BLUE)
                self.c.setLineWidth(.3 if m['type']=='joist' else .9)
                self.c.line(X(a[0]),Y(a[1]),X(b[0]),Y(b[1]))
        for wall in self.model['walls']:
            a,b=wall['start'],wall['end']
            if zone and not (x0-1e-5<=a[0]<=x1+1e-5 and y0-1e-5<=a[1]<=y1+1e-5 and x0-1e-5<=b[0]<=x1+1e-5 and y0-1e-5<=b[1]<=y1+1e-5):continue
            self.c.setStrokeColor(GOLD);self.c.setLineWidth(1.6)
            self.c.line(X(a[0]),Y(a[1]),X(b[0]),Y(b[1]))
        self.text(f'{number(x1-x0)} x {number(y1-y0)} ft', (X(x0)+X(x1))/2,Y(y1)-22,9,MUTED,align='center')
        nx,ny=bx+bw-12,by+bh-22
        self.c.setStrokeColor(INK);self.c.setLineWidth(1)
        self.c.line(nx,ny-18,nx,ny)
        path=self.c.beginPath();path.moveTo(nx,ny+3);path.lineTo(nx-3,ny-4);path.lineTo(nx+3,ny-4);path.close()
        self.c.setFillColor(INK);self.c.drawPath(path,fill=1,stroke=0)
        self.text('N',nx,ny+9,8,INK,True,align='center')

    def building_plan(self):
        self.page('Building framing plan',subtitle='North is up. Numbered grids run west to east; lettered grids run north to south. Dimensions are in feet.')
        self.plan((MARGIN,118,CONTENT_W,self.y-120))
        legend='Teal: joists   |   Blue: girders   |   Gold: columns / bearing walls   |   Gray: excluded bays   |   Pale blue: mezzanine areas'
        self.paragraph(legend,MARGIN,105,CONTENT_W,8)
        zones=self.model['results']['mezzanine']['mezzanine_zones']
        if zones:
            self.paragraph('Mezzanines: '+'; '.join(f'{z["name"]} ({number(z["area_sf"],0)} sf at {number(z["elevation_ft"])} ft)' for z in zones),MARGIN,83,CONTENT_W,8)

    def roof(self):
        g,p=self.model['grid'],self.project
        ys,heights=g['y_lines_ft'],g['roof_heights_ft']
        self.page('Roof profile & elevations',subtitle='North-to-south section through the lettered building grids. Elevations are top of joist.')
        low=min(p['clear_height_ft']-2,min(heights)-1)
        high=max(heights)+2
        left,right,bottom,top=78,714,211,self.y-25
        X=lambda v:left+(right-left)*v/ys[-1]
        Y=lambda v:bottom+(top-bottom)*(v-low)/(high-low)
        self.c.setStrokeColor(LINE);self.c.setLineWidth(.5)
        for i in range(5):
            elev=low+(high-low)*i/4
            self.c.line(left,Y(elev),right,Y(elev))
            self.text(number(elev),left-10,Y(elev)-3,8,MUTED,align='right')
        self.c.setDash(4,3);self.c.setStrokeColor(GOLD)
        self.c.line(left,Y(p['clear_height_ft']),right,Y(p['clear_height_ft']))
        self.c.setDash()
        self.text(f'Clear height {number(p["clear_height_ft"])} ft',right-6,Y(p['clear_height_ft'])-12,8,GOLD,align='right')
        step=max(1,math.ceil((len(ys)-1)/12))
        for i,y in enumerate(ys):
            self.c.setStrokeColor(LINE);self.c.setLineWidth(.5)
            self.c.line(X(y),bottom-8,X(y),Y(heights[i]))
            if i % step==0 or i==len(ys)-1:
                self.text(letter_label(i),X(y),bottom-24,9,MUTED,align='center')
                offset=5 if i==0 else -5 if i==len(ys)-1 else 0
                alignment='left' if i==0 else 'right' if i==len(ys)-1 else 'center'
                self.text(f'{number(heights[i])} ft',X(y)+offset,Y(heights[i])+10,8,INK,True,align=alignment)
            if i<len(ys)-1:
                slope=(heights[i+1]-heights[i])/(ys[i+1]-y)*12
                self.c.setStrokeColor(TEAL);self.c.setLineWidth(1.8)
                self.c.line(X(y),Y(heights[i]),X(ys[i+1]),Y(heights[i+1]))
                if (X(ys[i+1])-X(y))>48:
                    self.text(f'{number(abs(slope),3)} in/ft',X((y+ys[i+1])/2),Y((heights[i]+heights[i+1])/2)-16,8,TEAL,align='center')
        self.y=162
        self.metrics([('Roof form',p['roof_type'],''),('Lowest roof',number(min(heights)),'ft'),('Highest roof',number(max(heights)),'ft'),('North-south run',number(ys[-1]),'ft')],MARGIN,94,CONTENT_W)
        self.paragraph('Vertical scale is expanded for legibility. Roof line elevations, assigned joist depths and speed-bay rules follow the calculated model; this drawing is not to a common horizontal/vertical scale.',MARGIN,78,CONTENT_W,8)

    def mezzanines(self):
        for index,z in enumerate(self.model['results']['mezzanine']['mezzanine_zones'],1):
            self.page(f'{index:02d} / {z["name"]}', 'MEZZANINE FRAMING', 'North-up floor plan and calculated quantities for this area.')
            self.plan((MARGIN,155,440,self.y-152),zone=z)
            members=[m for m in self.model['members'] if m['demand'].get('zone_id')==z['zone_id']]
            mx=505;yy=self.y-10
            info=[('Area',f'{number(z["area_sf"],0)} sf'),('Floor elevation',f'{number(z["elevation_ft"])} ft'),('Dead / live load',f'{number(z["dead_load_psf"])} / {number(z["live_load_psf"])} psf'),('Joist direction','North-south (Y)' if z['joist_direction']=='vertical' else 'East-west (X)'),('Framing panels',str(z['panel_count'])),('Building columns',f'{z["main_support_connections"]} connections'),('Bearing walls',f'{z["lb_wall_support_connections"]} connections')]
            for label,value in info:
                self.text(label,mx,yy,8,MUTED)
                self.text(value,mx,yy-16,11,INK,True,width=235)
                yy-=40
            self.y=147
            padrows=[f for f in self.model['takeoffs']['mezzanine_footings']['column_footings'] if any(m['id']==f['column_id'] for m in members)]
            quantities=[]
            for kind,label in [('joist','Joists'),('girder','Girders'),('column','Additional columns')]:
                items=[m for m in members if m['type']==kind]
                quantities.append((label,str(len(items)),'members'))
            quantities.append(('Additional pads',str(len(padrows)),'pads'))
            self.metrics(quantities,MARGIN,87,CONTENT_W)
            self.paragraph('Building columns reused by the mezzanine are not counted again as additional columns or pad footings. Combined roof and mezzanine demand on reused supports is not verified.',MARGIN,74,CONTENT_W,8)

    def steel_schedules(self):
        self.page('Steel section schedule',subtitle=f'Total selected steel: {number(self.model["summary"]["selected_weight_lbs"],0)} lb ({number(self.model["summary"]["weight_tons"],3)} tons). Grouped using the original takeoff lengths; unassigned steel is shown explicitly.')
        groups=defaultdict(list)
        for m in self.model['members']:
            section=m['section']
            key=(m['level'],m['type'],section.get('designation') or 'Unassigned',section.get('weight_plf'))
            groups[key].append(m)
        rows=[]
        for (level,kind,designation,unit),members in sorted(groups.items(),key=lambda item:(item[0][0],item[0][1],item[0][2])):
            lengths=[m['weight_length_ft'] for m in members]
            length=number(min(lengths)) if abs(max(lengths)-min(lengths))<.01 else f'{number(min(lengths))} - {number(max(lengths))}'
            rows.append([('Roof' if level=='roof' else 'Mezz')+' / '+kind,designation,str(len(members)),length,number(sum(lengths)),number(unit) if unit else '-',number(sum(m['weight_lbs'] or 0 for m in members),0) if unit else 'Unassigned'])
        self.table(['Level / type','Section','Qty','Length range (ft)','Total length (ft)','Unit wt. (lb/ft)','Weight (lb)'],rows,[91,174,35,102,100,94,116],continuation='Steel section schedule - continued',size=8)

    def concrete_walls(self):
        tf=self.model['takeoffs']
        self.page('Pad footings & gross wall area',subtitle='Concrete is reported separately from steel. Pad totals include the original 10% waste allowance.')
        groups=defaultdict(list)
        for category,label in [('footings','Main building'),('mezzanine_footings','Additional mezzanine')]:
            for f in tf[category]['column_footings']:
                groups[(label,f['footing_size_ft'],f['footing_depth_ft'])].append(f)
        rows=[]
        for (level,size,depth),items in sorted(groups.items()):
            volume=sum(f['footing_volume_cy'] for f in items)
            rows.append([level,str(len(items)),f'{number(size)} x {number(size)}',number(depth),number(volume,3),number(volume*1.1,3)])
        pads=[f for items in groups.values() for f in items]
        volume=sum(f['footing_volume_cy'] for f in pads)
        rows.append(['TOTAL',str(len(pads)),'','',number(volume,3),number(volume*1.1,3)])
        self.table(['Location','Pads','Pad size (ft)','Depth (ft)','Net concrete (CY)','With waste (CY)'],rows,[190,50,130,90,126,126],continuation='Pad footing schedule - continued')
        if self.y<280:self.page('Gross wall area')
        self.section('Exterior wall envelope')
        rows=[]
        for side in ['north','south','east','west']:
            wall=tf['walls'][f'{side}_wall']
            rows.append([side.title(),number(wall['length_ft']),number(wall['area_sf'],0)])
        rows.append(['TOTAL','',number(tf['walls']['summary']['total_area_sf'],0)])
        self.table(['Wall','Length (ft)','Gross area (sf)'],rows,[240,236,236],continuation='Wall area - continued')
        if self.y<90:self.page('Concrete and wall basis')
        self.paragraph(f'Soil bearing input: {number(self.project["bearing_capacity_psf"],0)} psf. Pad sizes round up to quarter-foot increments. Wall area follows the original rectangular exterior envelope, dock heights and stepped wall elevations; openings and footprint cutouts are not deducted.',MARGIN,self.y,CONTENT_W,8.5)

    def notes(self):
        self.page('Calculation notes & scope',subtitle='Read these items with the schedules and drawings. This report records a takeoff, not an engineering certification.')
        notes=list(dict.fromkeys(clean(n) for n in self.model.get('notices',[])))
        for i,note in enumerate(notes,1):
            style=ParagraphStyle('note',fontName=self.font,fontSize=8.7,leading=13,textColor=MUTED)
            p=Paragraph(escape(note),style);_,h=p.wrap(CONTENT_W-30,2000)
            if self.y-h<85:self.page('Calculation notes - continued')
            self.text(f'{i:02d}',MARGIN,self.y-10,8,TEAL,True)
            p.drawOn(self.c,MARGIN+30,self.y-h)
            self.y-=h+14
        if self.y<130:self.page('Report scope')
        self.rule(MARGIN,self.y,CONTENT_W);self.y-=16
        self.paragraph('The 3D image is a clean render of the complete calculated steel model, independent of viewport isolation, layer hiding, clipping and selection. Fabrication geometry is schematic. Drawings and tables share the same calculation snapshot. Changes made after export are not part of this report.',MARGIN,self.y,CONTENT_W,8.5)

    def member_appendix(self):
        if not self.options['include_members']:return
        self.page('Detailed member schedule', 'APPENDIX', 'One row per modeled steel member. Required loads come directly from the original demand calculators.')
        rows=[]
        for m in self.model['members']:
            demand=m['demand']
            if 'required_capacity_plf' in demand:load=f'{number(demand["required_capacity_plf"])} plf'
            elif 'required_capacity_kips' in demand:load=f'{number(demand["required_capacity_kips"])} kips'
            else:load=f'{number(demand.get("required_capacity_lbs"))} lb'
            rows.append([m['id'],m['level']+' / '+m['type'],m['section']['designation'],number(m['weight_length_ft']),load,number(m['weight_lbs'],0) if m['weight_lbs'] is not None else 'Unassigned'])
        self.table(['Member','Level / type','Section','Takeoff ft','Required load','Weight (lb)'],rows,[171,108,154,70,112,97],continuation='Detailed member schedule - continued',size=7.6)

    def build(self):
        self.cover();self.basis();self.building_plan();self.roof();self.mezzanines()
        self.steel_schedules();self.concrete_walls();self.notes();self.member_appendix()
        self.c.showPage();self.c.save()
        return self.buffer.getvalue()


def build_report(model, model_image, options=None):
    image=validate_image(model_image)
    opts=report_options(options)
    return SteelReport(model,image,opts).build()


def report_filename(project):
    name=re.sub(r'[^A-Za-z0-9 _-]+','',str(project.get('name') or 'Steel Project')).strip()[:90]
    return f'{name or "Steel Project"} - Structural Steel Report.pdf'
