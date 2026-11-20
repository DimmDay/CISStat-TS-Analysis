"""Actual Tesseract controls on known synthetic pixels; never product acceptance."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw, ImageFont
from scripts.pgv13accept import oracles as O


class OCRTests(unittest.TestCase):
    def test_real_russian_pixels_and_missing_content_control(self):
        environment=O.ocr_environment()
        image=Image.new('RGB',O.GEOMETRY['a4-portrait'],'white')
        font=ImageFont.truetype('DejaVuSans.ttf',54)
        ImageDraw.Draw(image).multiline_text((100,100),'Паспорт свойств ряда\nБЕРЁЗА КИРИЛЛИЦА\n37',font=font,fill='black',spacing=20)
        with tempfile.TemporaryDirectory(prefix='pgv13-ocr-') as temp:
            path=Path(temp)/'control.png'
            image.save(path,format='PNG',dpi=(300,300))
            self.assertTrue(O.check_png(path.read_bytes(),'a4-portrait')['passed'])
            raw=O.capture(['tesseract',str(path),'stdout','-l','rus+eng','--psm','3','-c','tessedit_create_tsv=1'])
            self.assertTrue(O.check_ocr(raw,['Паспорт свойств ряда','берёза','кириллица'],['37'],image.size)['passed'])
            for needle in ['ВЫДУМАННАЯ ГРУППА','НЕСУЩЕСТВУЮЩЕЕ ПОДТВЕРЖДЕНИЕ']:
                with self.subTest(needle=needle),self.assertRaises(ValueError):
                    O.check_ocr(raw,[needle],[],image.size)
            with self.assertRaises(ValueError):
                O.check_ocr(raw,[],['9999'],image.size)
        print(json.dumps({'oracle_control':'PASS','tesseract':environment,
            'product_chromium_acceptance':False},ensure_ascii=False))


if __name__=='__main__':
    unittest.main()
