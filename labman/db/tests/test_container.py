# ----------------------------------------------------------------------------
# Copyright (c) 2017-, labman development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------

from unittest import main

from labman.db.testing import LabmanTestCase
from labman.db.container import Well, Tube, Container
from labman.db.plate import Plate
from labman.db.process import SamplePlatingProcess, PoolingProcess
from labman.db.composition import PoolComposition, SampleComposition


class TestContainer(LabmanTestCase):
    def test_factory(self):
        self.assertEqual(Container.factory(1540), Tube(4))
        self.assertEqual(Container.factory(1829), Well(1824))


class TestTube(LabmanTestCase):
    # The creation of a tube is always linked to a Process, we are going to
    # test the creation of a tube on those processes rather than here
    def test_properties(self):
        tester = Tube(4)
        self.assertEqual(tester.external_id, 'Test Pool from Plate 1')
        self.assertFalse(tester.discarded)
        self.assertEqual(tester.remaining_volume, 96)
        self.assertIsNone(tester.notes)
        self.assertEqual(tester.latest_process, PoolingProcess(1))
        self.assertEqual(tester.container_id, 1540)
        self.assertEqual(tester.composition, PoolComposition(1))

    def test_discarded(self):
        tester = Tube(5)
        self.assertFalse(tester.discarded)
        tester.discard()
        self.assertTrue(tester.discarded)
        regex = "Can't discard tube 5: it's already discarded."
        self.assertRaisesRegex(ValueError, regex, tester.discard)


class TestWell(LabmanTestCase):
    # The creation of a well is always linked to a Process, we are going to
    # test the creation of a well on those processes rather than here
    def test_properties(self):
        tester = Well(1537)
        self.assertEqual(tester.plate, Plate(17))
        self.assertEqual(tester.row, 1)
        self.assertEqual(tester.column, 1)
        self.assertEqual(tester.remaining_volume, 10)
        self.assertIsNone(tester.notes)
        self.assertEqual(tester.latest_process, SamplePlatingProcess(6))
        self.assertEqual(tester.container_id, 1542)
        self.assertEqual(tester.composition, SampleComposition(1))


if __name__ == '__main__':
    main()