"""Render the project's original vector-style brand artwork (requires Pillow)."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
BRAND=ROOT/'custom_components'/'blink_plus'/'brand'
ASSETS=ROOT/'docs'/'assets'
NAVY='#10233f';BLUE='#66c5ff';MINT='#73f3bf';WHITE='#f7fbff'
def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','C:/Windows/Fonts/segoeuib.ttf'):
        if Path(path).is_file():return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)
def icon(size):
    image=Image.new('RGBA',(1024,1024));d=ImageDraw.Draw(image)
    d.rounded_rectangle((0,0,1023,1023),radius=240,fill=NAVY)
    d.rounded_rectangle((128,328,652,716),radius=72,outline=BLUE,width=44)
    d.polygon(((690,426),(896,326),(896,718),(690,618)),fill=BLUE)
    d.ellipse((594,56,950,412),fill=MINT)
    d.line((772,144,772,324),fill=NAVY,width=40)
    d.line((682,234,862,234),fill=NAVY,width=40)
    return image.resize((size,size),Image.Resampling.LANCZOS)
def main():
    BRAND.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(parents=True,exist_ok=True)
    for scale,suffix in ((1,''),(2,'@2x')):
        size=256*scale
        icon(size).save(BRAND/f'icon{suffix}.png',optimize=True)
        for dark in (False,True):
            logo=Image.new('RGBA',(1000*scale,size))
            logo.alpha_composite(icon(size),(0,0));d=ImageDraw.Draw(logo)
            d.text((290*scale,67*scale),'Blink Plus',font=font(108*scale),fill=WHITE if dark else NAVY)
            logo.save(BRAND/f'{"dark_" if dark else ""}logo{suffix}.png',optimize=True)
    banner=Image.new('RGB',(1600,480),NAVY);d=ImageDraw.Draw(banner)
    banner.paste(icon(256),(90,112),icon(256))
    d.text((410,85),'Blink Plus',font=font(120),fill=WHITE)
    d.text((414,245),'Your Blink cameras. Inside Home Assistant.',font=font(36),fill=BLUE)
    x=414
    for label in ('LIVE VIDEO + AUDIO','LOCAL RECORDING','CLOUD CLIPS'):
        f=font(20);box=d.textbbox((0,0),label,font=f);width=box[2]+32
        d.rounded_rectangle((x,329,x+width,378),radius=16,fill='#203d5e')
        d.text((x+16,341),label,font=f,fill=MINT);x+=width+14
    banner.save(ASSETS/'banner.png',optimize=True)
    (ASSETS/'icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="60" fill="#10233f"/><rect x="32" y="82" width="131" height="97" rx="18" fill="none" stroke="#66c5ff" stroke-width="11"/><path d="M172.5 106.5 224 81.5v98L172.5 154.5z" fill="#66c5ff"/><circle cx="193" cy="58.5" r="44.5" fill="#73f3bf"/><path d="M193 36v45m-22.5-22.5h45" stroke="#10233f" stroke-width="10"/></svg>\n',encoding='utf-8')
if __name__=='__main__':main()
