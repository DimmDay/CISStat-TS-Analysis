"""Actual Tesseract controls on known synthetic pixels; never product acceptance."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw, ImageFont
from scripts.pgv13accept import oracles as O


class OCRTests(unittest.TestCase):
    def test_small_bilingual_source_pixels_sparse_page_and_exact_counts(self):
        O.ocr_environment()
        image=Image.new('RGB',O.GEOMETRY['a4-portrait'],'white')
        draw=ImageDraw.Draw(image)
        rows=[('Сравнение паспортов свойств ряда',26),
              ('Числовые метрики по этапам',22),
              ('Качественные и категориальные изменения',22),
              ('Определения:',22),('FFT — периоды',14),('seasonal_periods',14)]
        for index,(text,size) in enumerate(rows):
            draw.text((40,40+index*50),text,font=ImageFont.truetype('DejaVuSans-Bold.ttf',size),fill='#171717')
        for x,text in [(40,'37'),(240,'7'),(440,'100')]:
            draw.text((x,400),text,font=ImageFont.truetype('DejaVuSans.ttf',12),fill='#171717')
        for y in (900,1500,2100):
            draw.text((40,y),'БЕРЁЗА КИРИЛЛИЦА',font=ImageFont.truetype('DejaVuSans.ttf',12),fill='#171717')
        draw.text((40,3470),'Страница',font=ImageFont.truetype('DejaVuSans.ttf',10),fill='#171717')
        with tempfile.TemporaryDirectory(prefix='pgv13-small-ocr-') as temp:
            path=Path(temp)/'small.png';image.save(path,dpi=(300,300))
            before=path.read_bytes()
            result=O.recognize_png(path)
            required=['Сравнение паспортов','Числовые метрики','Качественные и категориальные изменения',
                      'Определения','FFT','seasonal_periods','Страница','БЕРЁЗА']
            accepted=O.check_document_ocr(result['tsv'],result['latin_tsv'],required,['37','7','100'],image.size,{'БЕРЁЗА':3})
            self.assertTrue(accepted['passed'])
            self.assertEqual(before,path.read_bytes())
            self.assertGreaterEqual(len(result['regions']),4)
            for missing in ['НЕСУЩЕСТВУЮЩИЙ РАЗДЕЛ','nonexistent_group']:
                with self.subTest(missing=missing),self.assertRaises(ValueError):
                    O.check_document_ocr(result['tsv'],result['latin_tsv'],[missing],[],image.size)
            with self.assertRaises(ValueError):
                O.check_document_ocr(result['tsv'],result['latin_tsv'],required,[],image.size,{'БЕРЁЗА':4})
        print(json.dumps({'small_bilingual_pixel_control':'PASS','product_chromium_acceptance':False}))

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
