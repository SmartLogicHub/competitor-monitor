import unittest

from activity_service import ActivityService


class ActivityServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = ActivityService(
            {
                "国补": ["领取政府补贴15%", "领取政府补贴", "政府补贴", "国补"],
                "跟价协议": ["超级爆款"],
                "超级立减": ["超级立减", "立减"],
                "淘金币": ["淘金币抵扣", "淘金币"],
                "消费券": ["消费券", "平台消费券"],
            },
            keep_original_activities=["618开门红", "618狂欢节"],
        )

    def test_recognizes_mapped_and_original_activities(self):
        result = self.service.recognize(
            "平台加补后 ￥268.52 起 领取政府补贴15% 超级爆款 618开门红"
        )

        self.assertEqual(result, ["国补", "跟价协议", "618开门红"])

    def test_returns_slash_when_no_activity_matches(self):
        self.assertEqual(self.service.recognize("平台加补后 ￥268.52 起"), ["/"])

    def test_merges_existing_activities_without_duplicates(self):
        merged = self.service.merge_activities("国补、消费券", ["国补", "淘金币"])

        self.assertEqual(merged, "国补、消费券、淘金币")


if __name__ == "__main__":
    unittest.main()
