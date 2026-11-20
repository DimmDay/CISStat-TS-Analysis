"""Pixel-derived OCR regions; no expected text is given to the recognizer."""
import argparse
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from scripts.pgv13accept import client as C, oracles as O, verify_vm as V


class PixelOCRTests(unittest.TestCase):
    def image(self, folder):
        image = Image.new('RGB', (2480, 3508), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 100, 250, 125), fill='black')
        draw.rectangle((40, 3400, 250, 3425), fill='black')
        path = Path(folder) / 'source.png'
        image.save(path, dpi=(300, 300))
        return path

    def test_regions_include_footer_and_project_words_to_original_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.image(folder)
            before = path.read_bytes()
            commands = []

            def capture(cmd):
                commands.append(cmd)
                with Image.open(cmd[1]) as crop:
                    self.assertLessEqual(crop.width * crop.height, O.OCR_MAX_PIXELS)
                return ('left\ttop\twidth\theight\tconf\ttext\n'
                        '24\t24\t30\t30\t95\tБЕРЁЗА\n')

            with patch.object(O, 'capture', side_effect=capture):
                result = O.recognize_png(path)
            self.assertEqual(len(result['regions']), 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result['source_sha256'], O.sha(before))
            words = list(csv.DictReader(io.StringIO(result['tsv']), delimiter='\t'))
            self.assertEqual([(int(w['left']), int(w['top'])) for w in words], [(40,100),(40,3400)])
            self.assertTrue(O.check_ocr(result['tsv'], ['БЕРЁЗА'], [], (2480,3508), {'БЕРЁЗА':2})['passed'])
            with self.assertRaisesRegex(ValueError, 'occurrence'):
                O.check_ocr(result['tsv'], ['БЕРЁЗА'], [], (2480,3508), {'БЕРЁЗА':3})
            self.assertEqual([cmd[cmd.index('-l')+1] for cmd in commands],['rus+eng','eng']*2)
            self.assertTrue(all(cmd[cmd.index('--psm')+1] == '6' for cmd in commands))

    def test_small_font_wrong_word_and_low_confidence_still_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            for text, conf in [('Keteropnensniie',95), ('категориальные',0)]:
                with self.subTest(text=text, conf=conf), patch.object(O, 'capture', return_value=
                    f'left\ttop\twidth\theight\tconf\ttext\n24\t24\t30\t30\t{conf}\t{text}\n'):
                    result = O.recognize_png(self.image(folder))
                    with self.assertRaises(ValueError):
                        O.check_ocr(result['tsv'], ['категориальные'], [], (2480,3508))

    def test_bad_crop_coordinates_are_rejected_before_projection(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(O, 'capture', return_value=
            'left\ttop\twidth\theight\tconf\ttext\n99999\t0\t30\t30\t95\tОпределения\n'):
            with self.assertRaisesRegex(ValueError, 'bounds'):
                O.recognize_png(self.image(folder))

    def test_upscale_adapts_to_pixel_budget_without_dropping_a_region(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(O,'OCR_MAX_PIXELS',10_000), \
            patch.object(O,'capture',return_value='left\ttop\twidth\theight\tconf\ttext\n8\t8\t10\t10\t95\tТекст\n'):
            result=O.recognize_png(self.image(folder))
            self.assertEqual(len(result['regions']),2)
            self.assertTrue(all(region['scale']==1 for region in result['regions']))

    def test_source_contract_preserves_unknown_group_key(self):
        self.assertIn('seasonal_periods', C.GROUPS)
        self.assertNotIn('Сезонные периоды', C.GROUPS)
        self.assertEqual(set(C.passport(0)), {'basic_stats','freq','stationarity','determinism',
            'autocorrelation','trend','seasonality','seasonal_periods','fft','wavelet','certificate_tail'})

    def test_phrases_are_not_assembled_across_languages(self):
        def words(text):
            return 'left\ttop\twidth\theight\tconf\ttext\n1\t1\t30\t30\t95\t'+text+'\n'
        with self.assertRaisesRegex(ValueError, 'missing'):
            O.check_document_ocr(words('Качественные'),words('категориальные'),
                                  ['Качественные категориальные'],[],(2480,3508))
        with self.assertRaisesRegex(ValueError, 'FFT'):
            O.check_document_ocr(words('FFT'),words('ЕЕТ'),['FFT'],[],(2480,3508))

    def test_finalize_reports_ocr_failure_without_calling_it_postgres_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'report.json'
            path.write_text(json.dumps({'automated_passed':False, 'detail':'PNG pixel/OCR checks failed for: p02-missing'}))
            with self.assertRaisesRegex(ValueError, 'pixel/OCR'):
                V.finalize(argparse.Namespace(report=path, review=Path(folder)/'absent.json'))


if __name__ == '__main__':
    unittest.main()
