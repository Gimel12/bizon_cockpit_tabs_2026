#!/usr/bin/env python3
"""Check the real packages' native Cockpit navigation without starting services.

Cockpit renders dashboard as Apps before menu/System and tools/Tools. Keeping
the grouping in manifests lets first login, search and keyboard focus share the
same order; no custom page script has to run before navigation is correct.
https://docs.cockpit-project.org/cockpit-guide/main/guide/packages.html
"""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
EXPECTED=[
    ('cockpit_bizon_ai','bizon-ai','index.html'),
    ('cockpit_gpu','gpu-monitor','index.html'),
    ('cockpit_vnc','pinger','index.html'),
    ('cockpit_containers','docker-images','active_containers.html'),
    ('cockpit_support','drive-tests','drives.html'),
    ('cockpit_support','raid-manager','raid.html'),
    ('cockpit_jupyter','jupyter','index.html'),
    ('cockpit_tutorials','video-tutorials','index.html'),
    ('cockpit_support','update-tabs','support.html'),
]

class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.manifests={package:json.loads((ROOT/package/'manifest.json').read_text())
                        for package,_,_ in EXPECTED}

    def test_all_nine_custom_entries_are_in_native_apps_group(self):
        actual={(package,key) for package,manifest in self.manifests.items()
                for key in manifest.get('dashboard',{})}
        self.assertEqual(actual,{(package,key) for package,key,_ in EXPECTED})
        for package,manifest in self.manifests.items():
            with self.subTest(package=package):
                self.assertFalse(manifest.get('menu'), 'BIZON tabs must not mix into System')
                self.assertFalse(manifest.get('tools'), 'BIZON tabs must not mix into stock Tools')

    def test_navigation_preserves_entry_pages_and_has_no_duplicate_routes(self):
        routes=[]
        for package,key,page in EXPECTED:
            with self.subTest(package=package,entry=key):
                entry=self.manifests[package]['dashboard'][key]
                self.assertEqual(entry['path'],page)
                self.assertTrue((ROOT/package/page).is_file())
                self.assertTrue(entry['label'].strip())
                routes.append((package,entry['path']))
        self.assertEqual(len(routes),len(set(routes)))

    def test_custom_order_is_unambiguous(self):
        orders=[self.manifests[package]['dashboard'][key]['order'] for package,key,_ in EXPECTED]
        self.assertTrue(all(type(order) is int for order in orders))
        self.assertEqual(orders,sorted(set(orders)))

if __name__=='__main__':
    unittest.main(verbosity=2)
