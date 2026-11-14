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
            archive.writestr('/Subfolder/file.pdf', b'pdf contents')
            archive.writestr('/Subfolder/extra.pdf', b'other contents')
            archive.writestr('../escape.txt', b'unsafe')

        client = app.Client.__new__(app.Client)
        client.page = lambda url: (course_page, course, '')

        def open_url(url):
            if url == folder:
                return Response(url, folder_html, 'text/html')
            if url == archive_url:
                return Response(url, data.getvalue(), 'application/zip')
            if url == file_url:
                return Response(url, b'pdf contents', 'application/pdf')
            self.fail('Unexpected URL: ' + url)

        client.open = open_url
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'desktop', return_value=Path(temp)):
            root, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (2, 1, 0))
            self.assertEqual((root / 'Cartella/Subfolder/file.pdf').read_bytes(), b'pdf contents')
            self.assertEqual((root / 'Cartella/Subfolder/extra.pdf').read_bytes(), b'other contents')
            self.assertFalse((Path(temp) / 'escape.txt').exists())
            _, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (0, 3, 0))

    def test_inline_folder_without_archive_keeps_directory_tree(self):
        course = app.BASE + '/course/view.php?id=42'
        file_url = app.BASE + '/pluginfile.php/123/mod_folder/content/0/Subfolder/file.pdf'
        html = (
            '<h1>Corso prova</h1><ul class="foldertree"><li role="treeitem">'
            '<p>Materiali</p><ul role="group"><li role="treeitem">'
            '<p>Subfolder</p><ul role="group"><li role="treeitem">'
            f'<p><a href="{file_url}">file.pdf</a></p>'
            '</li></ul></li></ul></li></ul>'
        )
        client = app.Client.__new__(app.Client)
        client.page = lambda url: (app.Page(html), course, html)
        client.open = lambda url: Response(url, b'pdf contents', 'application/pdf')
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'desktop', return_value=Path(temp)):
            root, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (1, 0, 0))
            self.assertEqual((root / 'Materiali/Subfolder/file.pdf').read_bytes(), b'pdf contents')

    def test_archive_does_not_stop_later_course_sections(self):
        course = app.BASE + '/course/view.php?id=42'
        archive_url = app.BASE + '/mod/folder/download_folder.php?id=7'
        section_url = app.BASE + '/course/section.php?id=123'
        resource_url = app.BASE + '/mod/resource/view.php?id=8'
        html = (
            '<h1>Corso prova</h1><form action="/mod/folder/download_folder.php" method="get">'
            '<input name="id" value="7"></form><div data-sectionid="123"></div>'
        )
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('/inside.pdf', b'inside')
        client = app.Client.__new__(app.Client)
        client.page = lambda url: (app.Page(html), course, html)

        def open_url(url):
            if url == archive_url:
                return Response(url, data.getvalue(), 'application/zip')
            if url == section_url:
                return Response(url, b'<a href="/mod/resource/view.php?id=8">File</a>', 'text/html')
            if url == resource_url:
                return Response(url, b'resource', 'application/pdf')
            self.fail('Unexpected URL: ' + url)

        client.open = open_url
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'desktop', return_value=Path(temp)):
            root, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (2, 0, 0))
            self.assertEqual((root / 'Cartella_7/inside.pdf').read_bytes(), b'inside')

    def test_folder_page_discovered_from_data_url_without_archive(self):
        course = app.BASE + '/course/view.php?id=42'
        folder = app.BASE + '/mod/folder/view.php?id=7'
        file_url = app.BASE + '/pluginfile.php/123/mod_folder/content/0/Sottocartella/file.pdf'
        course_html = '<h1>Corso prova</h1><div data-url="/mod/folder/view.php?id=7"></div>'
        folder_html = (
            '<ul class="foldertree"><li role="treeitem"><p>Materiali</p>'
            '<ul role="group"><li role="treeitem"><p>Sottocartella</p>'
            f'<ul role="group"><li role="treeitem"><p><a href="{file_url}">file.pdf</a></p>'
            '</li></ul></li></ul></li></ul>'
        )
        client = app.Client.__new__(app.Client)
        client.page = lambda url: (app.Page(course_html), course, course_html)

        def open_url(url):
            if url == folder:
                return Response(url, folder_html.encode(), 'text/html')
            if url == file_url:
                return Response(url, b'pdf contents', 'application/pdf')
            self.fail('Unexpected URL: ' + url)

        client.open = open_url
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'desktop', return_value=Path(temp)):
            root, count, skipped, failed = client.download(course, lambda _: None)
            self.assertEqual((count, skipped, failed), (1, 0, 0))
            self.assertEqual((root / 'Materiali/Sottocartella/file.pdf').read_bytes(), b'pdf contents')


if __name__ == '__main__':
    unittest.main()
