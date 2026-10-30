"""Verify the actual image payload without contacting a visual model."""

import base64
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from infrastructure.shared.models.vision import VisualModel, compress_image


def encode(image, **options):
    buffer = BytesIO()
    image.save(buffer, format='PNG', **options)
    return buffer.getvalue()


class ImageCompression(unittest.TestCase):
    def test_invalid_visual_json_receives_feedback_with_the_same_image(self):
        model = VisualModel.__new__(VisualModel)
        model.name, model.client = 'test-model', object()
        replies = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
            for content in ('{broken', '{"layout":"test","elements":[],"style":"test"}')]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'reference.png'
            path.write_bytes(encode(Image.new('RGB', (16, 8), 'white')))
            with patch('infrastructure.shared.models.vision.invoke', side_effect=replies) as invoke, redirect_stdout(StringIO()):
                result = model.analyze(path)
        self.assertEqual(result['layout'], 'test')
        self.assertEqual(invoke.call_count, 2)
        first, second = [call.args[1]['messages'][0]['content'] for call in invoke.call_args_list]
        self.assertEqual(first[1], second[1])
        self.assertIn('JSONDecodeError', second[0]['text'])
        self.assertIn('{broken', second[0]['text'])

    def test_large_transparent_image_is_resized_with_correct_aspect_and_white_background(self):
        original = encode(Image.new('RGBA', (3000, 1500), (255, 0, 0, 0)))
        data, mime = compress_image(original, 'image/png')
        self.assertEqual(mime, 'image/jpeg')
        with Image.open(BytesIO(data)) as result:
            self.assertEqual(result.size, (2048, 1024))
            self.assertEqual(result.mode, 'RGB')
            self.assertTrue(all(channel >= 250 for channel in result.getpixel((0, 0))))

    def test_small_image_is_not_enlarged_or_replaced_with_a_larger_encoding(self):
        original = encode(Image.new('RGB', (16, 8), 'white'))
        data, mime = compress_image(original, 'image/png')
        self.assertEqual(data, original)
        self.assertEqual(mime, 'image/png')

    def test_actual_request_uses_compressed_bytes_matching_its_mime_without_changing_source(self):
        image = Image.frombytes('RGB', (320, 200), Random(7).randbytes(320 * 200 * 3))
        original = encode(image)
        model = VisualModel.__new__(VisualModel)
        model.name, model.client = 'test-model', object()
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"layout":"test","elements":[],"style":"test"}'))])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'reference.png'
            path.write_bytes(original)
            with patch('infrastructure.shared.models.vision.invoke', return_value=response) as invoke, redirect_stdout(StringIO()):
                model.analyze(path)
            self.assertEqual(path.read_bytes(), original)
        url = invoke.call_args.args[1]['messages'][0]['content'][1]['image_url']['url']
        header, payload = url.split(',', 1)
        self.assertEqual(header, 'data:image/jpeg;base64')
        data = base64.b64decode(payload)
        self.assertLess(len(data), len(original))
        with Image.open(BytesIO(data)) as sent:
            self.assertEqual(sent.format, 'JPEG')
            self.assertEqual(sent.size, (320, 200))


if __name__ == '__main__':
    unittest.main()
