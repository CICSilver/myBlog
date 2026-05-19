import unittest

from app.ip_location import resolve_ip_location


class IpLocationTest(unittest.TestCase):
    def test_resolves_china_public_ipv4_to_region_city_and_isp(self):
        location = resolve_ip_location("113.118.113.77")

        self.assertEqual(location["ip_country"], "中国")
        self.assertEqual(location["ip_region"], "广东省")
        self.assertEqual(location["ip_city"], "深圳市")
        self.assertEqual(location["ip_isp"], "电信")
        self.assertEqual(location["ip_country_code"], "CN")
        self.assertEqual(location["ip_location"], "中国 / 广东省 / 深圳市 / 电信")

    def test_local_network_addresses_are_marked_as_local(self):
        for ip in ("127.0.0.1", "192.168.1.10", "10.0.0.2", "172.16.0.2", "::1"):
            with self.subTest(ip=ip):
                self.assertEqual(resolve_ip_location(ip)["ip_location"], "本地/内网")

    def test_invalid_empty_and_public_ipv6_addresses_are_unknown(self):
        for ip in ("", "not-an-ip", "240e:3b7:3272:d8d0:db09:c067:8d59:539e"):
            with self.subTest(ip=ip):
                self.assertEqual(resolve_ip_location(ip)["ip_location"], "未知")


if __name__ == "__main__":
    unittest.main()
