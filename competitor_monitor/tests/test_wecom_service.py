import json
import unittest
from unittest.mock import patch

import wecom_service


class WeComServiceTest(unittest.TestCase):
    def test_post_json_sends_chinese_text_as_utf8_without_question_mark_replacement(self):
        captured = {}

        def fake_load_json_response(request):
            captured["headers"] = dict(request.header_items())
            captured["data"] = request.data
            return {"errcode": 0, "errmsg": "ok"}

        payload = {"msgtype": "text", "text": {"content": "竞品监控任务完成\n状态：成功\n周末 BI 上新采集完成"}}

        with patch.object(wecom_service, "_load_json_response", fake_load_json_response):
            response = wecom_service._post_json("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test", payload)

        self.assertEqual(response["errcode"], 0)
        self.assertEqual(captured["headers"]["Content-type"], "application/json; charset=utf-8")
        decoded = captured["data"].decode("utf-8")
        self.assertIn("竞品监控任务完成", decoded)
        self.assertIn("周末 BI 上新采集完成", decoded)
        self.assertNotIn("????", decoded)
        self.assertEqual(json.loads(decoded), payload)


if __name__ == "__main__":
    unittest.main()
