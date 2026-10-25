"""Six thermo cards: mousepad layout principles with an independent blue palette."""
import numpy as np
from PIL import Image, ImageDraw, ImageOps
def fit(im, src, box):
    src = ImageOps.contain(src, (box[2]-box[0], box[3]-box[1]), Image.Resampling.LANCZOS)
    x=box[0]+(box[2]-box[0]-src.width)//2
    y=box[1]+(box[3]-box[1]-src.height)//2
    im.paste(src, (x,y), src if src.mode == 'RGBA' else None)
    return (x,y,x+src.width,y+src.height)

from printflow.products.thermo.infrastructure.gallery import slides as layout
from printflow.products.thermo.infrastructure.gallery.slides import mont, hand, INK, TERRA, CREAM
from printflow.services.gallery.renderer import JpegGalleryRenderer
from printflow.products.thermo.infrastructure.gallery.geometry import place_print, load_print
from printflow.services.gallery.geometry import homography
import io
import json

class Slide(layout.Slide):
    def pill(self, x, y, icon, text, size=41):
        self.icon(icon, x + 23, y + 31, 23, color=TERRA, ring=False)
        f = mont(size, 700)
        label = text.upper()
        while self.text_w(label, f) > self.W - x - 130:
            f = mont(f.size - 1, 700)
        self.draw.text((x + 65, y + 31), label, font=f, fill=INK, anchor='lm')
        right = x + 65 + self.text_w(label, f)
        self.draw.line((x, y + 79, right, y + 79), fill=TERRA, width=5)
        return y + 84

    def arrow(self, p0, p1, bend=0.3, color=(43, 89, 211)):
        return super().arrow(p0, p1, bend, color)


def background():
    yy, xx = np.mgrid[0:1600, 0:1200]
    t = np.clip((xx / 1200 + yy / 1600) / 2, 0, 1)[..., None]
    light = np.array([241, 248, 255])
    blue = np.array([203, 222, 243])
    im = Image.fromarray((light * (1-t) + blue * t).astype('uint8'))
    d = ImageDraw.Draw(im)
    d.ellipse((900,-280,1600,650),fill=(222,235,250))
    d.ellipse((-430,1150,350,1930),fill=(222,236,251))
    return im


def txt(c,x,y,value,size=32,weight=500,width=1000,color=INK):
    for para in value.split('\n'):
        line=''
        for word in para.split():
            new=(line+' '+word).strip()
            if line and c.text_w(new,mont(size,weight))>width:
                c.draw.text((x,y),line,font=mont(size,weight),fill=color)
                y+=size*1.35; line=word
            else: line=new
        c.draw.text((x,y),line,font=mont(size,weight),fill=color)
        y+=size*1.35
    return y


def centered_text(c, box, blocks, gap=10):
    """Wrap and center the actual glyph bounds of a text group inside a panel."""
    left, top, right, bottom = box
    lines = []
    for value, size, weight, color in blocks:
        f = mont(size, weight)
        for paragraph in value.split('\n'):
            line = ''
            for word in paragraph.split():
                candidate = (line + ' ' + word).strip()
                if line and c.text_w(candidate, f) > right-left:
                    bounds = c.draw.textbbox((0, 0), line, font=f, anchor='lt')
                    lines.append((line, f, color, bounds[3]-bounds[1]))
                    line = word
                else:
                    line = candidate
            bounds = c.draw.textbbox((0, 0), line, font=f, anchor='lt')
            lines.append((line, f, color, bounds[3]-bounds[1]))
    height = sum(line[3] for line in lines) + gap * max(0, len(lines)-1)
    y = top + (bottom-top-height)/2
    for line, f, color, h in lines:
        c.draw.text(((left+right)/2, y), line, font=f, fill=color, anchor='mt')
        y += h + gap


def start(title,sub,pill,note,scene=None):
    c=Slide(scene if scene is not None else background())
    y=c.heading(65,45,[title,sub],1070)
    y=c.pill(70,y+24,'sparkle',pill)
    if note:
        c.draw.text((70, 478), note, font=hand(60, 600), fill=INK, anchor='lt')
    return c


def finish(c,badge=None,badge_y=1360):
    if badge: c.badge(55,badge_y,*badge)
    return c.result()


def photo(c,im,box,contain=False):
    target=(box[2]-box[0],box[3]-box[1])
    if contain:
        fitted=ImageOps.contain(im,target,Image.Resampling.LANCZOS)
        canvas=Image.new('RGB',target,(247,239,228))
        left=(target[0]-fitted.width)//2
        top=(target[1]-fitted.height)//2
        if left > 0 and fitted.height == target[1]:
            canvas.paste(fitted.crop((0,0,8,fitted.height)).resize((left,target[1]),Image.Resampling.BILINEAR),(0,0))
            right=target[0]-left-fitted.width
            canvas.paste(fitted.crop((fitted.width-8,0,fitted.width,fitted.height)).resize((right,target[1]),Image.Resampling.BILINEAR),(left+fitted.width,0))
        canvas.paste(fitted,(left,top))
        im=canvas.convert('RGBA')
    else:
        im=ImageOps.fit(im,target,centering=(.5,.5)).convert('RGBA')
    mask=Image.new('L',im.size,0); ImageDraw.Draw(mask).rounded_rectangle((0,0,im.width,im.height),radius=55,fill=255)
    im.putalpha(mask); c.img.alpha_composite(im,box[:2])


def steps(c,items):
    for i,(num,title,body) in enumerate(items):
        y=550+i*250
        c.draw.rounded_rectangle((60,y,1140,y+235),radius=45,fill=CREAM)
        c.draw.ellipse((86,y+30,170,y+114),fill=TERRA)
        c.draw.text((128,y+72),str(num),font=mont(45,800),fill=CREAM,anchor='mm')
        txt(c,202,y+28,title,37,800,width=885)
        txt(c,202,y+94,body,30,500,width=880)


def physical_print_zone(template_size, print_cm, mockup):
    """One pixel/cm scale for both axes: garment width calibrates physical print size."""
    w,h=template_size
    width_cm=float(mockup['reference_width_cm'])
    fraction=float(mockup['reference_width_fraction'])
    if width_cm <= 0 or not 0 < fraction <= 1 or min(print_cm) <= 0:
        raise ValueError('Invalid physical dimensions for thermo mockup')
    px_per_cm=w*fraction/width_cm
    pw,ph=print_cm[0]*px_per_cm,print_cm[1]*px_per_cm
    cx,cy=mockup['center'][0]*w,mockup['center'][1]*h
    return [(cx-pw/2,cy-ph/2),(cx+pw/2,cy-ph/2),
            (cx+pw/2,cy+ph/2),(cx-pw/2,cy+ph/2)]


def surface_print_zone(template_size, print_cm, spec):
    """Project real centimetres onto the garment plane, not an arbitrary print box."""
    sw,sh=map(float,spec['surface_cm'])
    pw,ph=map(float,print_cm)
    if min(sw,sh,pw,ph)<=0 or pw>sw or ph>sh:
        raise ValueError('Print does not fit the calibrated fabric surface')
    tw,th=template_size
    target=[(x*tw,y*th) for x,y in spec['surface']]
    transform=homography([(0,0),(sw,0),(sw,sh),(0,sh)],target)
    cx,cy=spec.get('center',[.5,.5]);cx*=sw;cy*=sh
    corners=[(cx-pw/2,cy-ph/2),(cx+pw/2,cy-ph/2),
             (cx+pw/2,cy+ph/2),(cx-pw/2,cy+ph/2)]
    output=[]
    for x,y in corners:
        u,v,w=transform@np.array([x,y,1.])
        output.append((u/w,v/w))
    return output


def garment_mockup(art, size, mockup, templates_dir, render_scale=1):
    calibration=templates_dir/'mockup-calibration.json'
    if calibration.is_file():
        name=mockup['template'].split('-')[0]
        overrides=json.loads(calibration.read_text(encoding='utf-8')).get(name,{})
        mockup={**mockup,**overrides}
    tpl=Image.open(templates_dir/mockup['template']).convert('RGBA')
    if mockup.get('reference_height_cm'):
        # Measure the actual opaque body instead of guessing its top/bottom
        # from scene percentages; handles are narrower and stay unchanged.
        alpha=np.asarray(tpl.getchannel('A'))>128
        row_widths=alpha.sum(axis=1)
        body_rows=np.flatnonzero(row_widths>=row_widths.max()*.90)
        if not len(body_rows) or not row_widths.max():
            raise ValueError('Cannot calibrate an empty bag mockup')
        top,bottom=int(body_rows[0]),int(body_rows[-1])+1
        middle=(top+bottom)//2
        columns=np.flatnonzero(alpha[middle])
        body_width=int(columns[-1]-columns[0]+1)
        height=round(body_width/mockup['reference_width_cm']*mockup['reference_height_cm'])
        original_height=bottom-top
        normalized=Image.new('RGBA',(tpl.width,tpl.height+height-original_height))
        normalized.paste(tpl.crop((0,0,tpl.width,top)),(0,0))
        normalized.paste(tpl.crop((0,top,tpl.width,bottom)).resize((tpl.width,height),Image.Resampling.LANCZOS),(0,top))
        normalized.paste(tpl.crop((0,bottom,tpl.width,tpl.height)),(0,top+height))
        mockup={**mockup,'reference_width_fraction':body_width/tpl.width,
                'center':[(int(columns[0])+body_width/2)/tpl.width,(top+height/2)/normalized.height]}
        tpl=normalized
    if render_scale!=1:
        tpl=tpl.resize((tpl.width*render_scale,tpl.height*render_scale),Image.Resampling.LANCZOS)
    zone=physical_print_zone(tpl.size,size,mockup)
    rendered=place_print(tpl,art,zone,size[0]/size[1],.5).convert('RGBA')
    rendered.putalpha(tpl.getchannel('A'))
    return rendered


def scene_image(templates_dir, filename):
    path=templates_dir/filename
    if not path.is_file():
        return None
    with Image.open(path) as image:
        return image.convert('RGB').resize((1200,1600),Image.Resampling.LANCZOS)


def scene_mockup(art, size, name, templates_dir):
    scene=scene_image(templates_dir,f'{name}-scene.png')
    if scene is None:
        return None
    spec={'reference_width_cm':52 if name=='shirt' else 34,
          'reference_width_fraction':.44 if name=='shirt' else .48,
          'center':[.5,.54] if name=='shirt' else [.5,.67]}
    zone=physical_print_zone(scene.size,size,spec)
    return place_print(scene,art,zone,size[0]/size[1],.5)


from printflow.products.thermo.domain.assortment import sizes as set_sizes, caption as size_caption, copy_for, resolve_artwork, dimension_text


def label(c, box, title, subtitle=''):
    c.draw.rounded_rectangle(box, radius=30, fill=CREAM)
    blocks=[(title, 30, 800, INK)]
    if subtitle:
        blocks.append((subtitle, 23, 500, INK))
    centered_text(c, (box[0]+12,box[1]+10,box[2]-12,box[3]-10), blocks, gap=8)


def set_badge(c, title='В НАБОРЕ 3 ШТ.', subtitle='По одному принту каждого размера'):
    label(c, (65,1390,1135,1515), title, subtitle)


def bottom_note(c,text):
    c.draw.text((600,1555),text,font=mont(21,500),fill=INK,anchor='mm')


def cutout_mockup(art, size, name, product, templates_dir):
    spec=product['gallery']['mockups'][name]
    if (templates_dir/spec['template']).is_file():
        image=garment_mockup(art,size,spec,templates_dir)
        bounds=image.getchannel('A').getbbox()
        return image.crop(bounds) if bounds else image
    # Standalone template generation also works from freshly generated full scenes.
    rendered=scene_mockup(art,size,name,templates_dir)
    if rendered is None:
        raise FileNotFoundError(f'Missing thermo {name} mockup')
    box=(192,512,1008,1340) if name=='shirt' else (288,512,912,1340)
    return rendered.crop(box)


def single_cover(art, item, backdrop):
    c=start('ТЕРМО','НАКЛЕЙКА','Для одежды и аксессуаров','Обнови любимую вещь!',scene=backdrop)
    label(c,(855,535,1140,645),size_caption(item))
    fit(c.img,art,(160,655,1040,1325))
    c.badge(55,1390,'sparkle','Декоративный','ПРИНТ')
    return c.result()


def single_mockup(art,item,name,product,templates_dir,backdrop):
    title,sub,pill=('НОВЫЙ ОБРАЗ','ЛЮБИМОЙ ФУТБОЛКИ','Перенос утюгом') if name=='shirt' else ('ТВОЙ ШОППЕР','С ХАРАКТЕРОМ','Для аксессуаров')
    c=start(title,sub,pill,'',scene=backdrop)
    rendered=cutout_mockup(art,item['size_cm'],name,product,templates_dir)
    fit(c.img,rendered,(95,480,1105,1325))
    if name=='shirt':
        c.draw.text((600,1337),'На фото футболка размера L',font=mont(24,500),fill=INK,anchor='mt')
    c.badge(55,1365,'sparkle','Пример нанесения','НА ФУТБОЛКЕ' if name=='shirt' else 'НА ШОППЕРЕ')
    bottom_note(c,'Вещь показана для примера и в комплект не входит')
    return c.result()


def single_dimensions(art,item,backdrop):
    c=start('ЯРКИЙ ПРИНТ','ЗАМЕТНЫЙ АКЦЕНТ','Размер '+size_caption(item),'Сначала примерь расположение',scene=backdrop)
    w,h=item['size_cm']
    unit=min(730/w,700/h)
    width,height=round(w*unit),round(h*unit)
    left=round(660-width/2);top=580
    right,bottom=left+width,top+height
    fit(c.img,art,(left,top,right,bottom))
    # Arrows measure the physical format, not the artwork's arbitrary transparent margins.
    def dimension_arrow(p0,p1):
        c.draw.line((p0,p1),fill=TERRA,width=6)
        dx,dy=p1[0]-p0[0],p1[1]-p0[1]
        length=(dx*dx+dy*dy)**.5;ux,uy=dx/length,dy/length
        for point,sign in [(p0,1),(p1,-1)]:
            x,y=point
            for side in (-1,1):
                c.draw.line(((x,y),(x+sign*ux*25-side*uy*17,y+sign*uy*25+side*ux*17)),fill=TERRA,width=6)
    dimension_arrow((left-55,top),(left-55,bottom))
    dimension_arrow((left,bottom+55),(right,bottom+55))
    c.draw.text((left-85,(top+bottom)/2),dimension_text(h)+' см',font=mont(28,700),fill=INK,anchor='rm')
    c.draw.text(((left+right)/2,bottom+80),dimension_text(w)+' см',font=mont(28,700),fill=INK,anchor='mt')
    c.badge(55,1390,'sparkle','Ориентируйтесь','НА РАЗМЕРЫ')
    return c.result()


def three_mockups(art, sizes, name, product, templates_dir, backdrop):
    count=len(sizes)
    words=copy_for(sizes)
    title,sub=('ТВОЯ ФУТБОЛКА','С ХАРАКТЕРОМ') if name=='shirt' else ('ТВОЙ ШОППЕР','С ХАРАКТЕРОМ')
    c=start(title,sub,words['pill'],'',scene=backdrop)
    note='Так выглядит принт на вещи' if count==1 else 'Одна вещь — разные размеры принта'
    c.draw.text((600,475),note,font=hand(48,600),fill=INK,anchor='mt')
    row=product['gallery']['comparison_row']
    columns=min(count,3)
    rows=(count+columns-1)//columns
    margin,gap=row['margin'],row['gap']
    width=(1200-2*margin-(columns-1)*gap)/columns
    for index,item in enumerate(sizes):
        line=index//columns
        cells=min(columns,count-line*columns)
        offset=(1200-(cells*width+(cells-1)*gap))/2
        center=offset+width/2+(index%columns)*(width+gap)
        bottom=row['bottom'] if rows==1 else 815+line*435
        maximum_height=(600 if count==1 else row['max_height']) if rows==1 else 310
        rendered=cutout_mockup(art,item['size_cm'],name,product,templates_dir)
        fitted=ImageOps.contain(rendered,(int(width),maximum_height),Image.Resampling.LANCZOS)
        c.img.alpha_composite(fitted,(round(center-fitted.width/2),bottom-fitted.height))
        half=min(177,width/2-8)
        label(c,(center-half,bottom+32,center+half,bottom+118),item['label'],size_caption(item))
    noun='футболке' if name=='shirt' else 'шоппере'
    if name=='shirt':
        c.draw.text((600,1340),'На фото футболки размера L',font=mont(24,500),fill=INK,anchor='mt')
    set_badge(c,'ПРИМЕР НАНЕСЕНИЯ' if count==1 else 'ПРИМЕРЫ НАНЕСЕНИЯ','На '+noun)
    bottom_note(c,'Вещи в комплект не входят')
    return c.result()


def contents_card(art,sizes,backdrop):
    words=copy_for(sizes)
    c=start(words['contents_title'],words['contents_sub'],words['pill'],'Размеры указаны в сантиметрах',scene=backdrop)
    count=len(sizes);columns=min(count,3);rows=(count+columns-1)//columns
    width=(1090-(columns-1)*35)/columns
    for i,item in enumerate(sizes):
        line=i//columns;cells=min(columns,count-line*columns)
        offset=(1200-(cells*width+(cells-1)*35))/2
        x=offset+(i%columns)*(width+35)
        bottom=1208 if rows==1 else 815+line*425
        # Identical pixels/cm in both axes, with the artwork contained in its physical box.
        unit=min(width/max(s['size_cm'][0] for s in sizes),(650 if rows==1 else 290)/max(s['size_cm'][1] for s in sizes))
        w,h=(max(1,round(v*unit)) for v in item['size_cm'])
        fit(c.img,art,(round(x+(width-w)/2),bottom-h,round(x+(width+w)/2),bottom))
        label(c,(x,bottom+32,x+width,bottom+118),item['label'],size_caption(item))
    set_badge(c,words['badge'],words['subtitle'])
    return c.result()


def accents_card(art, sizes, product, templates_dir):
    scene=scene_image(templates_dir,'accents-scene.png')
    if scene is None:
        raise FileNotFoundError('Missing accents-scene.png; regenerate thermo templates')
    # Calibrate the whole fabric surface, then inset the actual print size in cm.
    zones=product['gallery']['accents']
    calibration=templates_dir/'accents-calibration.json'
    if calibration.is_file():
        zones=json.loads(calibration.read_text(encoding='utf-8'))
    placements=[(sizes[-1],'shirt'),(sizes[(len(sizes)-1)//2],'shopper')]
    if len(sizes)>=3 and sizes[0]['size_cm'][1]<=zones['pouch']['surface_cm'][1]:
        placements.append((sizes[0],'pouch'))
    for item,name in placements:
        spec=zones[name]
        quad=surface_print_zone((1200,1600),item['size_cm'],spec)
        scene=place_print(scene,art,quad,item['size_cm'][0]/item['size_cm'][1],.3)
    c=Slide(scene)
    y=c.heading(65,45,['ТЕРМО','НАКЛЕЙКИ'],1070)
    words=copy_for(sizes)
    c.pill(70,y+24,'sparkle',words['pill'],size=35)
    c.draw.text((70,450),'Обнови любимые вещи!',font=hand(50,600),fill=INK,anchor='lt')
    set_badge(c,words['badge'],words['subtitle'])
    bottom_note(c,'Вещи показаны для примера и в комплект не входят')
    return c.result()


def compose(art, product, templates_dir):
    if art.getchannel('A').getbbox():
        product = resolve_artwork(product, art.size)
    sizes = set_sizes(product)
    cards=[]
    backdrop=scene_image(templates_dir,'background-scene.png')
    if len(sizes)==1:
        cards.extend([
            ('01-cover',single_cover(art,sizes[0],backdrop)),
            ('02-shirt',single_mockup(art,sizes[0],'shirt',product,templates_dir,backdrop)),
            ('03-shopper',single_mockup(art,sizes[0],'shopper',product,templates_dir,backdrop)),
            ('04-size',single_dimensions(art,sizes[0],backdrop)),
        ])
    else:
        cards.append(('01-cover',accents_card(art,sizes,product,templates_dir)))
        cards.append(('02-shirt',three_mockups(art,sizes,'shirt',product,templates_dir,backdrop)))
        cards.append(('03-shopper',three_mockups(art,sizes,'shopper',product,templates_dir,backdrop)))
        cards.append(('04-size',contents_card(art,sizes,backdrop)))
    c=start('ПЕРЕНОС УТЮГОМ','ПОШАГОВО','Вся инструкция на одной карточке','Немного тепла — и готово',scene=backdrop)
    items = [
        ('Подготовьте ткань', 'Твёрдая ровная основа. Расправьте складки и прогрейте ткань.'),
        ('Выключите пар', 'Ориентир: 150–160 °C. Сверьте с инструкцией к плёнке и ярлыком ткани.'),
        ('Прижмите рисунок', 'Положите наклейку рисунком вверх. Сильно прижимайте утюг 15–20 секунд по всей площади.'),
        ('Остудите и снимите плёнку', 'Для холодного снятия подождите 3–5 минут. Медленно тяните плёнку за уголок.'),
        ('Проверьте перенос', 'Край отходит? Верните плёнку и повторите прижим. Если требует инструкция, закрепите через пергамент.')]
    for i,(title,body) in enumerate(items):
        y=535+i*166
        c.draw.rounded_rectangle((60,y,1140,y+151),radius=30,fill=CREAM)
        c.draw.ellipse((82,y+42.5,148,y+108.5),fill=TERRA)
        centered_text(c,(82,y+42.5,148,y+108.5),[(str(i+1),34,800,CREAM)])
        centered_text(c,(177,y+16,1110,y+135),[(title,32,800,INK),(body,26,500,INK)],gap=12)
    if len(sizes)>1:
        set_badge(c,'ПЕРЕНОС УТЮГОМ','Следуйте инструкции к вашей плёнке')
    bottom_note(c,'Режим и тип снятия — по инструкции к вашей плёнке')
    cards.append(('05-application',finish(c)))
    c=start('ЛЮБИМЫМ ВЕЩАМ','БЕРЕЖНЫЙ УХОД','Чтобы принт радовал дольше','Сохрани эту памятку',scene=backdrop)
    items=[('30 °C','СТИРАЙТЕ С ИЗНАНКИ','Деликатная или ручная программа.'),('400–600','ОБОРОТОВ ПРИ ОТЖИМЕ','Выбирайте бережный режим.'),('БЕЗ','ОТБЕЛИВАТЕЛЯ','Используйте мягкое моющее средство.'),('УТЮГ','ТОЛЬКО С ИЗНАНКИ','Не касайтесь лицевой стороны принта.')]
    for i,(big,title,body) in enumerate(items):
        y=550+i*190
        c.draw.rounded_rectangle((130,y,1070,y+170),radius=36,fill=CREAM)
        c.draw.line((370,y+28,370,y+142),fill=(182,202,233),width=3)
        centered_text(c,(150,y+20,350,y+150),[(big,37,800,TERRA)])
        centered_text(c,(400,y+20,1040,y+150),[(title,29,800,INK),(body,26,500,INK)],gap=14)
    if len(sizes)>1:
        set_badge(c,'БЕРЕЖНЫЙ УХОД','Сохрани эту памятку')
    cards.append(('06-care',finish(c)))
    return dict(cards)


class ThermoGalleryRenderer(JpegGalleryRenderer):
    slides = ['01-cover', '02-shirt', '03-shopper', '04-size', '05-application', '06-care']

    def compose_print(self, print_png, variant):
        if variant != 'main':
            raise ValueError(f'Unknown thermo variant: {variant}')
        art = load_print(io.BytesIO(print_png))
        if not art.getchannel('A').getbbox():
            raise ValueError('Empty thermo print')
        return compose(art, self.product, self.templates_dir)
