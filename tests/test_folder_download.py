import io
import tempfile
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import moodle_downloader as app


class Response(io.BytesIO):
    def __init__(self, url, body, content_type):
        super().__init__(body)
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = content_type


class FolderDownloadTest(unittest.TestCase):
    def test_archive_includes_nested_files_and_skips_existing_files(self):
        course = app.BASE + '/course/view.php?id=42'
        folder = app.BASE + '/mod/folder/view.php?id=7'
        archive_url = app.BASE + '/mod/folder/download_folder.php?id=7'
        file_url = app.BASE + '/pluginfile.php/123/mod_folder/content/0/Subfolder/file.pdf'
        course_page = app.Page('<h1>Corso prova</h1><a href="/mod/folder/view.php?id=7">Cartella</a>')
        folder_html = (
            '<form action="/mod/folder/download_folder.php" method="get">'
            '<input name="id" value="7"></form>'
            f'<a href="{file_url}">file.pdf</a>'
        ).encode()
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('Subfolder/file.pdf', b'pdf contents')
            archive.writestr('../escape.txt', b'unsafe')

        client = app.Client.__new__(app.Client)
        client.page = lambda url: (course_page, course, '')

        def open_url(url):
            if url == folder:
                return Response(url, folder_html, 'text/html')
            if url == archive_url:
                return Response(url, data.getvalue(), 'application/zip')
            self.fail('Unexpected URL: ' + url)

        client.open = open_url
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'desktop', return_value=Path(temp)):
            root, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (1, 0, 0))
            self.assertEqual((root / 'Subfolder/file.pdf').read_bytes(), b'pdf contents')
            self.assertFalse((Path(temp) / 'escape.txt').exists())
            _, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (0, 1, 0))


if __name__ == '__main__':
    unittest.main()
