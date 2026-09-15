"""PDF contents, required model image, and optional schedule pagination."""
import base64
import copy
from io import BytesIO
import unittest

from PIL import Image
from pypdf import PdfReader

import steel_model
from steel_report import build_report, report_filename, validate_image
from test_visualizer import project_fixture


def image_fixture(size=(600, 300)):
    image = BytesIO()
    Image.new('RGB', size, '#367f89').save(image, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode('ascii')


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project = project_fixture()
        project.update(mezzanine_enabled=True, mezzanines=[{
            'id': 'MZ001', 'name': 'Office mezzanine', 'enabled': True,
            'x_start_line_index': 1, 'x_end_line_index': 2,
            'y_start_line_index': 1, 'y_end_line_index': 2,
            'elevation_ft': 12, 'dead_load_psf': 25, 'live_load_psf': 80,
            'joist_spaces_per_bay': 4,
        }])
        cls.model = steel_model.calculate_project(project)
        cls.png = image_fixture()

    def test_pdf_embeds_model_and_reports_calculated_quantities(self):
        before = copy.deepcopy(self.model)
        report = PdfReader(BytesIO(build_report(self.model, self.png, {
            'company': 'QA & Co <Review>', 'prepared_by': 'Report test', 'revision': 'R3',
        })))
        text = '\n'.join(page.extract_text() for page in report.pages)
        self.assertEqual(len(report.pages[0].images), 1)
        for expected in ['QA & Co <Review>', 'Office mezzanine', 'Roof profile & elevations',
                         'Area (sf)', 'Tilt wall panels', 'Panels', 'Slab on grade',
                         'Total concrete', 'Steel section schedule', 'Pad size (ft)',
                         f'{self.model["summary"]["selected_weight_lbs"]:,.0f} lb']:
            self.assertIn(expected, text)
        self.assertNotIn('Detailed member schedule', text)
        for i, page in enumerate(report.pages, 1):
            self.assertIn(f'{i:02d} / {len(report.pages):02d}', page.extract_text())
            self.assertEqual((float(page.mediabox.width), float(page.mediabox.height)), (792, 612))
        self.assertEqual(self.model, before, 'Export must not mutate assignments or geometry')

    def test_optional_appendix_keeps_every_member_across_page_breaks(self):
        report = PdfReader(BytesIO(build_report(self.model, self.png, {'include_members': True})))
        pages = [page.extract_text() for page in report.pages]
        appendix = '\n'.join(p for p in pages if 'Detailed member schedule' in p)
        self.assertGreater(sum('Detailed member schedule' in p for p in pages), 1)
        for member in self.model['members']:
            self.assertIn(member['id'], appendix)
        for page in pages:
            if 'Detailed member schedule' in page:
                self.assertIn('Required load', page)

    def test_report_refuses_missing_corrupt_or_undersized_model_images(self):
        for value in [None, '', 'data:image/png;base64,broken!',
                      'data:image/png;base64,' + base64.b64encode(b'not a PNG').decode(),
                      image_fixture((100, 100))]:
            with self.subTest(value=str(value)[:50]), self.assertRaises(ValueError):
                validate_image(value)

    def test_metadata_is_validated_and_download_filename_is_safe(self):
        with self.assertRaises(ValueError):
            build_report(self.model, self.png, ['invalid details'])
        filename = report_filename({'name': '../Shark"\r\nInjected: value'})
        self.assertNotRegex(filename, r'[\r\n/\\:"]')
        self.assertTrue(filename.endswith('.pdf'))
