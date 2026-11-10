"""Render the project's original brand artwork (requires Pillow; Nunito Sans gives the intended lettering)."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
BRAND=ROOT/'custom_components'/'blink_plus'/'brand'
ASSETS=ROOT/'docs'/'assets'
NAVY='#10233f';BLUE='#66c5ff';MINT='#73f3bf';WHITE='#f7fbff';SKY='#1aa7f2'
def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','C:/Windows/Fonts/segoeuib.ttf'):
        if Path(path).is_file():return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)
def wordmark(size):
    """A heavy rounded face for the lowercase name on the icon (Nunito Sans Black where installed)."""
    for path in ('/usr/share/fonts/truetype/nunito-sans/NunitoSans-VariableFont_YTLC,opsz,wdth,wght.ttf',):
        if Path(path).is_file():
            face=ImageFont.truetype(path,size)
            try:face.set_variation_by_name('Black')
            except (OSError,ValueError):pass
            return face
    return font(size)
def icon(size):
    """The lowercase name in white on a sky-blue tile with a plus badge. Original lettering, not Blink's logo artwork."""
    image=Image.new('RGBA',(1024,1024));d=ImageDraw.Draw(image)
    d.rounded_rectangle((0,0,1023,1023),radius=240,fill=SKY)
    face=wordmark(330);box=d.textbbox((0,0),'blink',font=face)
    d.text(((1024-(box[2]-box[0]))/2-box[0],610-(box[3]-box[1])/2-box[1]),'blink',font=face,fill=WHITE)
    d.ellipse((664,70,954,360),fill=WHITE)
    d.line((809,140,809,290),fill=SKY,width=44)
    d.line((734,215,884,215),fill=SKY,width=44)
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
    (ASSETS/'icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="60" fill="#1aa7f2"/><text x="128" y="181" text-anchor="middle" font-family="Nunito Sans, Nunito, Arial Rounded MT Bold, Arial, sans-serif" font-weight="900" font-size="82" fill="#f7fbff">blink</text><circle cx="202" cy="54" r="36" fill="#f7fbff"/><path d="M202 35v38m-19-19h38" stroke="#1aa7f2" stroke-width="11"/></svg>'+chr(10),encoding='utf-8')
if __name__=='__main__':main()
