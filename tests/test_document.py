import tempfile
import unittest
from pathlib import Path

from document import InvalidReply, render_document, write_document


def payload(token='test-current-route'):
    return {
        'route_token': token, 'location': '客厅', 'scene_time': '傍晚',
        'body': ''.join(chr(0x4e00 + index) for index in range(1050)),
        'mood': '放松', 'relationship_value': 10,
        'options': ['聊聊画稿', '一起准备茶水', '看看窗外的雨', '询问今天的安排'],
        'brief_note': '当前是两位成年朋友在客厅的日常交流。',
    }


class DocumentTests(unittest.TestCase):
    def test_host_builds_every_required_section(self):
        source = payload()
        text = render_document(source, 1000)
        self.assertTrue(text.startswith('【客厅/傍晚】'))
        self.assertIn(source['body'], text)
        for required in ['心情：放松', '关系温度：10/100', 'A. 聊聊画稿', 'B. 一起准备茶水', 'C. 看看窗外的雨', 'D. 询问今天的安排', '简要说明：']:
            self.assertIn(required, text)

    def test_ascii_and_status_do_not_count_as_chinese_body(self):
        source = payload()
        source['body'] = '雨荷整理画稿。' + 'A1 ' * 1000
        with self.assertRaisesRegex(InvalidReply, 'requires at least 1000'):
            render_document(source, 1000)

    def test_missing_or_duplicate_choices_are_not_sent(self):
        for options in [['相同选项'] * 4, ['只有一个选项']]:
            source = payload()
            source['options'] = options
            with self.assertRaises(InvalidReply):
                render_document(source)

    def test_boolean_is_not_accepted_as_relationship_score(self):
        source = payload()
        source['relationship_value'] = True
        with self.assertRaises(InvalidReply):
            render_document(source)

    def test_hidden_tags_and_route_leaks_are_rejected(self):
        for invalid in ['<think>test</think>', 'test-current-route']:
            source = payload()
            source['body'] = invalid
            with self.assertRaises(InvalidReply):
                render_document(source)

    def test_document_has_bom_and_cannot_escape_its_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_document(directory, 'fus-' + '0' * 32 + '.txt', '中文\n第二行')
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertEqual(path.read_text(encoding='utf-8-sig'), '中文\n第二行')
            with self.assertRaises(ValueError):
                write_document(directory, '../outside.txt', 'test')
            with self.assertRaises(FileExistsError):
                write_document(directory, path.name, 'replace')


if __name__ == '__main__':
    unittest.main()
